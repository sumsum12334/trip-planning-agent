"""Stay-search tool: stub catalog (local MVP), OpenStreetMap Overpass API,
live web search (preferred live mode), or OBO Travel live booking API
(legacy; prefer ``web``)."""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date, timedelta
from typing import Any, Optional

import httpx
from urllib.parse import parse_qs, urlencode, urlparse

from agents.web_search import run as web_search_run
from config.settings import get_settings
from shared.schemas import StayCandidate

from . import pricing

logger = logging.getLogger(__name__)

# Curated stub catalog: several city labels + generic entries.
# Destination is user-specified; city labels are only for stub matching.
_STUB_CATALOG: list[dict[str, Any]] = [
    {
        "name": "Harbour View Hostel",
        "location": "Hong Kong Central",
        "nightly_cost": 45.0,
        "currency": "HKD",
        "rating": 4.1,
        "phone": "+852 2555 1234",
        "amenities": ["wifi", "locker"],
        "source_url": "https://example.com/stays/hk-hostel",
    },
    {
        "name": "Kowloon Budget Inn",
        "location": "Hong Kong Kowloon",
        "nightly_cost": 70.0,
        "currency": "HKD",
        "rating": 3.9,
        "phone": "+852 2789 5678",
        "amenities": ["wifi", "breakfast"],
        "source_url": "https://example.com/stays/hk-inn",
    },
    {
        "name": "Victoria Peak Boutique Hotel",
        "location": "Hong Kong Mid-Levels",
        "nightly_cost": 180.0,
        "currency": "HKD",
        "rating": 4.6,
        "phone": "+852 2845 9012",
        "amenities": ["wifi", "gym", "view"],
        "source_url": "https://example.com/stays/hk-boutique",
    },
    {
        "name": "Shibuya Capsule Pod",
        "location": "Tokyo Shibuya",
        "nightly_cost": 55.0,
        "currency": "USD",
        "rating": 4.0,
        "phone": "+81 3-5555-0123",
        "amenities": ["wifi", "locker"],
        "source_url": "https://example.com/stays/tyo-capsule",
        "coordinates": {"lat": 35.6580, "lng": 139.7016},
    },
    {
        "name": "Asakusa Traditional Ryokan",
        "location": "Tokyo Asakusa",
        "nightly_cost": 120.0,
        "currency": "USD",
        "rating": 4.7,
        "phone": "+81 3-5555-3456",
        "amenities": ["wifi", "onsen", "breakfast"],
        "source_url": "https://example.com/stays/tyo-ryokan",
        "coordinates": {"lat": 35.7148, "lng": 139.7967},
    },
    {
        "name": "Shinjuku Business Hotel",
        "location": "Tokyo Shinjuku",
        "nightly_cost": 95.0,
        "currency": "USD",
        "rating": 4.2,
        "phone": "+81 3-5555-7890",
        "amenities": ["wifi", "desk"],
        "source_url": "https://example.com/stays/tyo-business",
        "coordinates": {"lat": 35.6938, "lng": 139.7034},
    },
    {
        "name": "Canal-Side Guesthouse",
        "location": "Amsterdam Centrum",
        "nightly_cost": 85.0,
        "currency": "USD",
        "rating": 4.3,
        "phone": "+31 20 555 0123",
        "amenities": ["wifi", "bike"],
        "source_url": "https://example.com/stays/ams-guest",
    },
    {
        "name": "Museum Quarter Flat",
        "location": "Amsterdam Museumkwartier",
        "nightly_cost": 140.0,
        "currency": "USD",
        "rating": 4.5,
        "phone": "+31 20 555 4567",
        "amenities": ["wifi", "kitchen"],
        "source_url": "https://example.com/stays/ams-flat",
    },
    {
        "name": "Downtown Transit Hostel",
        "location": "Generic City Center",
        "nightly_cost": 40.0,
        "currency": "USD",
        "rating": 3.8,
        "phone": "+1 555-0123",
        "amenities": ["wifi", "locker"],
        "source_url": "https://example.com/stays/generic-hostel",
    },
    {
        "name": "City Park Midrange Hotel",
        "location": "Generic Downtown",
        "nightly_cost": 90.0,
        "currency": "USD",
        "rating": 4.1,
        "phone": "+1 555-4567",
        "amenities": ["wifi", "breakfast", "parking"],
        "source_url": "https://example.com/stays/generic-mid",
    },
    {
        "name": "Riverside Suites",
        "location": "Generic Waterfront",
        "nightly_cost": 160.0,
        "currency": "USD",
        "rating": 4.4,
        "phone": "+1 555-7890",
        "amenities": ["wifi", "kitchen", "laundry"],
        "source_url": "https://example.com/stays/generic-suites",
    },
    {
        "name": "Airport Express Motel",
        "location": "Generic Airport Area",
        "nightly_cost": 65.0,
        "currency": "USD",
        "rating": 3.6,
        "phone": "+1 555-8901",
        "amenities": ["wifi", "shuttle"],
        "source_url": "https://example.com/stays/generic-airport",
    },
]


# ---------------------------------------------------------------------------
# Simple TTL cache
# ---------------------------------------------------------------------------

class _TTLCache:
    """Thread-safe in-memory cache with TTL expiration."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_geocode_cache = _TTLCache(ttl_seconds=86400.0)   # geocodes cached for 24h
_search_cache = _TTLCache(ttl_seconds=300.0)      # search results cached for 5min


# ---------------------------------------------------------------------------
# Budget helper
# ---------------------------------------------------------------------------

def nightly_budget_cap(budget: Optional[float], days: Optional[int]) -> Optional[float]:
    """Max nightly spend derived from total budget and trip length."""
    if budget is None:
        return None
    night_count = days if days and days > 0 else 3
    return budget / night_count


# ---------------------------------------------------------------------------
# Geocoding (free OpenStreetMap Nominatim, no API key required)
# ---------------------------------------------------------------------------

class NominatimGeocoder:
    """Resolve a destination name to latitude/longitude via Nominatim.

    Nominatim is free but rate-limited (1 request/sec). Results are cached for
    24h to be polite to the service.
    """

    def __init__(self, base_url: str = "https://nominatim.openstreetmap.org") -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=15.0, headers={"User-Agent": "trip-planning-agent/0.1"})

    def geocode(self, destination: str) -> Optional[dict[str, float]]:
        """Return {"lat": ..., "lng": ...} or None if not found."""
        if not destination or not destination.strip():
            return None
        key = f"geocode:{destination.strip().lower()}"
        cached = _geocode_cache.get(key)
        if cached is not None:
            return cached
        try:
            params = {"q": destination.strip(), "format": "json", "limit": 1}
            encoded = urlencode(params)
            url = f"{self.base_url}/search?{encoded}"
            response = self._client.get(url)
            response.raise_for_status()
            data = response.json()
            if not data:
                return None
            result = {
                "lat": float(data[0]["lat"]),
                "lng": float(data[0]["lon"]),
            }
            _geocode_cache.set(key, result)
            return result
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            logger.warning("Geocoding failed for %r: %s", destination, error)
            return None


# ---------------------------------------------------------------------------
# Overpass API provider (free OpenStreetMap, no API key required)
# ---------------------------------------------------------------------------

class OverpassProvider:
    """Query OpenStreetMap Overpass API for hotels/lodging near a destination.

    Overpass is free and requires no authentication. The provider tries multiple
    public mirror instances in sequence so that a single outage doesn't break
    the search. Results include real hotel names, coordinates, and addresses
    from OpenStreetMap.

    Does NOT return: nightly cost, real-time availability, review scores.
    """

    DEFAULT_MIRRORS: list[str] = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
    ]

    def __init__(
        self,
        base_urls: list[str] | None = None,
        timeout: float = 30.0,
        radius_meters: int = 5000,
    ) -> None:
        self.base_urls = base_urls or list(self.DEFAULT_MIRRORS)
        self.timeout = timeout
        self.radius_meters = radius_meters
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": "trip-planning-agent/0.1"})

    def _build_query(self, lat: float, lng: float) -> str:
        """Build an Overpass QL query for lodging near a point."""
        # Query hotels, motels, guest houses, hostels within radius
        return (
            '[out:json][timeout:%d];\n'
            '(\n'
            '  node["tourism"="hotel"](around:%d,%f,%f);\n'
            '  node["tourism"="motel"](around:%d,%f,%f);\n'
            '  node["tourism"="guest_house"](around:%d,%f,%f);\n'
            '  node["tourism"="hostel"](around:%d,%f,%f);\n'
            '  way["tourism"="hotel"](around:%d,%f,%f);\n'
            '  way["tourism"="motel"](around:%d,%f,%f);\n'
            '  way["tourism"="guest_house"](around:%d,%f,%f);\n'
            '  way["tourism"="hostel"](around:%d,%f,%f);\n'
            '  relation["tourism"="hotel"](around:%d,%f,%f);\n'
            '  relation["tourism"="motel"](around:%d,%f,%f);\n'
            '  relation["tourism"="guest_house"](around:%d,%f,%f);\n'
            '  relation["tourism"="hostel"](around:%d,%f,%f);\n'
            ');\n'
            'out center tags;'
        ) % (
            int(self.timeout),
            self.radius_meters, lat, lng,
            self.radius_meters, lat, lng,
            self.radius_meters, lat, lng,
            self.radius_meters, lat, lng,
            self.radius_meters, lat, lng,
            self.radius_meters, lat, lng,
            self.radius_meters, lat, lng,
            self.radius_meters, lat, lng,
            self.radius_meters, lat, lng,
            self.radius_meters, lat, lng,
            self.radius_meters, lat, lng,
            self.radius_meters, lat, lng,
        )

    def search(
        self,
        destination: str,
        budget: Optional[float] = None,
        days: Optional[int] = None,
        interests: Optional[list[str]] = None,
        coordinates: Optional[dict[str, float]] = None,
    ) -> list[StayCandidate]:
        """Find lodging near destination using Overpass API.

        If ``coordinates`` is not provided, the destination is geocoded first
        via Nominatim.
        """
        if coordinates is None:
            geocoder = NominatimGeocoder()
            coordinates = geocoder.geocode(destination)
        if coordinates is None:
            logger.warning("Could not geocode %r for Overpass search", destination)
            return [
                StayCandidate(
                    name="Geocoding failed",
                    location=destination,
                    nightly_cost=None,
                    notes="overpass: could not resolve destination to coordinates",
                )
            ]

        lat = coordinates["lat"]
        lng = coordinates["lng"]

        cache_key = f"overpass:{lat:.4f}:{lng:.4f}:{self.radius_meters}"
        cached = _search_cache.get(cache_key)
        if cached is not None:
            return cached

        query = self._build_query(lat, lng)
        last_error: Exception | None = None
        for base_url in self.base_urls:
            try:
                response = self._client.post(
                    base_url,
                    data={"data": query},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                data = response.json()
                elements = data.get("elements", []) if isinstance(data, dict) else []
                candidates = [_map_overpass_element(el, lat, lng) for el in elements]
                # Sort by rating (stars) descending, then name
                candidates.sort(
                    key=lambda c: (c.rating or 0, c.name or ""),
                    reverse=True,
                )
                candidates = candidates[:5]
                _search_cache.set(cache_key, candidates)
                return candidates
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                last_error = error
                logger.warning("Overpass mirror %s failed for %r: %s", base_url, destination, error)
                continue

        logger.warning("All Overpass mirrors failed for %r", destination)
        return [
            StayCandidate(
                name="Provider error",
                location=destination,
                nightly_cost=None,
                notes=f"overpass: all mirrors failed — {last_error}",
            )
        ]

    def health(self) -> dict[str, Any]:
        return {
            "provider": "overpass",
            "base_urls": self.base_urls,
            "radius_meters": self.radius_meters,
            "offline_safe": False,
            "timeout_seconds": self.timeout,
        }


# ---------------------------------------------------------------------------
# OBO Travel API provider (Agent 1, legacy; used when TOOL_STAYS_MODE=api).
# Kept for rollback — prefer TOOL_STAYS_MODE=web for live results.
# ---------------------------------------------------------------------------

class ApiProvider:
    """OBO Travel accommodation provider via MCP JSON-RPC 2.0 endpoint.

    Legacy provider kept for rollback — prefer ``TOOL_STAYS_MODE=web``, which
    sources live stay results from the shared DuckDuckGo web-search tool.

    Endpoint: https://onebookingonline.com/mcp
    Auth: None required (optional X-OBO-Key header for higher limits)
    Rate limits (keyless): 30 req/min, 500 req/day; 10 live searches/min,
    150 live searches/day.

    Returns real hotel data with live prices, booking URLs, cancellation info,
    and star ratings. No nightly-cost estimation needed — prices are live.
    """

    DEFAULT_ENDPOINT = "https://onebookingonline.com/mcp"

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        api_key: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": "trip-planning-agent/0.1"})
        self._request_id = 0

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _derive_dates(
        self,
        check_in: Optional[str],
        check_out: Optional[str],
        days: Optional[int],
    ) -> tuple[str, str]:
        """Resolve check-in/check-out dates from inputs, defaulting to tomorrow."""
        if check_in is None:
            check_in = (date.today() + timedelta(days=1)).isoformat()
        ci = date.fromisoformat(check_in) if isinstance(check_in, str) else check_in
        if check_out is None:
            if days and days > 0:
                check_out = (ci + timedelta(days=days)).isoformat()
            else:
                check_out = (ci + timedelta(days=3)).isoformat()
        elif isinstance(check_out, date):
            check_out = check_out.isoformat()
        return ci.isoformat(), check_out

    def search(
        self,
        destination: str,
        budget: Optional[float] = None,
        days: Optional[int] = None,
        interests: Optional[list[str]] = None,
        check_in: Optional[str] = None,
        check_out: Optional[str] = None,
    ) -> list[StayCandidate]:
        """Find live hotel availability via OBO Travel MCP API.

        Returns StayCandidate objects with live nightly_cost, currency="USD",
        booking_url as source_url, star rating, and cancellation policy.
        """
        check_in, check_out = self._derive_dates(check_in, check_out, days)

        # Derive per-night price cap from total budget
        max_price_per_night: Optional[float] = None
        if budget and days and days > 0:
            max_price_per_night = round(budget / days, 2)

        # Build JSON-RPC 2.0 request
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": "tools/call",
            "params": {
                "name": "search_hotels",
                "arguments": {
                    "destination": destination,
                    "check_in": check_in,
                    "check_out": check_out,
                    "limit": 5,
                },
            },
        }
        if max_price_per_night is not None:
            payload["params"]["arguments"]["max_price_per_night"] = max_price_per_night

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-OBO-Key"] = self.api_key

        try:
            response = self._client.post(self.endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

            # Parse JSON-RPC 2.0 response
            if data.get("jsonrpc") != "2.0":
                logger.warning("Unexpected JSON-RPC version: %s", data.get("jsonrpc"))

            result = data.get("result", {})
            if not isinstance(result, dict):
                logger.warning("Unexpected result type: %s", type(result))
                return [
                    StayCandidate(
                        name="Provider error",
                        location=destination,
                        nightly_cost=None,
                        notes=f"api: obo travel unexpected response type",
                    )
                ]

            # Check for error
            if result.get("isError"):
                sc = result.get("structuredContent", {})
                err = sc.get("error", {})
                msg = err.get("message", "Unknown error") if isinstance(err, dict) else str(err)
                logger.warning("OBO Travel API error: %s", msg)
                return [
                    StayCandidate(
                        name="Provider error",
                        location=destination,
                        nightly_cost=None,
                        notes=f"api: obo travel error — {msg}",
                    )
                ]

            # Hotels are in structuredContent.results
            sc = result.get("structuredContent", {}) or {}
            hotels = sc.get("results", [])
            if not isinstance(hotels, list):
                hotels = []

            candidates = [_map_obo_result(h, destination, sc) for h in hotels]

            # Client-side budget filter (in case provider doesn't support it)
            if max_price_per_night is not None:
                candidates = [
                    c
                    for c in candidates
                    if c.nightly_cost is None or c.nightly_cost <= max_price_per_night
                ]

            # Sort by price ascending (None costs last)
            candidates.sort(
                key=lambda c: (c.nightly_cost is None, c.nightly_cost or float("inf"))
            )
            candidates = candidates[:5]
            return candidates

        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            logger.warning("OBO Travel search failed for %r: %s", destination, error)
            return [
                StayCandidate(
                    name="Provider error",
                    location=destination,
                    nightly_cost=None,
                    notes=f"api: obo travel search failed — {error}",
                )
            ]

    def health(self) -> dict[str, Any]:
        return {
            "provider": "obo_travel",
            "endpoint": self.endpoint,
            "api_key_configured": bool(self.api_key),
            "offline_safe": False,
            "timeout_seconds": self.timeout,
        }


# ---------------------------------------------------------------------------
# Web-search-backed provider (Agent 1, used when TOOL_STAYS_MODE=web)
# ---------------------------------------------------------------------------

# Bounded query plan: at most one request per template (web_search.run applies
# its own ~15s per-request timeout), and the third query runs only when the
# first two did not yield enough priced candidates.
_WEB_QUERY_TEMPLATES: tuple[str, ...] = (
    "{destination} hotels price per night",
    "{destination} guesthouse hostel nightly rate",
    "{destination} budget hotel room rates",
)
_WEB_MAX_QUERIES = 3
_WEB_RESULTS_PER_QUERY = 8
_WEB_MIN_PRICED_RESULTS = 3
_WEB_RESULT_CAP = 10

# Lodging relevance keywords: a search result must mention at least one of
# these in its title/snippet to become a StayCandidate.
_STAY_KEYWORDS: tuple[str, ...] = (
    "hotel", "hostel", "guesthouse", "guest house", "motel", "resort",
    "ryokan", "inn", "b&b", "bed and breakfast", "apartment", "lodging",
    "accommodation", "capsule", "per night", "nightly", "stay",
)

# Property-type inference for pricing.apply_estimates on unpriced results.
_PROPERTY_TYPE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("hostel", "hostel"),
    ("capsule", "capsule"),
    ("ryokan", "ryokan"),
    ("guest house", "guest_house"),
    ("guesthouse", "guest_house"),
    ("b&b", "guest_house"),
    ("bed and breakfast", "guest_house"),
    ("motel", "motel"),
    ("resort", "resort"),
    ("apartment", "apartment"),
)

# --- Nightly price parsing from search snippets ---------------------------
# Symbol → ISO code. Longer symbols must be tried first so "US$" is not read
# as "$". "¥" is ambiguous (JPY/CNY) and resolved by amount magnitude.
_CURRENCY_SYMBOLS: dict[str, str] = {
    "US$": "USD", "HK$": "HKD", "NT$": "TWD", "S$": "SGD",
    "A$": "AUD", "C$": "CAD", "NZ$": "NZD",
    "$": "USD", "€": "EUR", "£": "GBP",
}
_CURRENCY_CODES: frozenset[str] = frozenset({
    "USD", "EUR", "GBP", "JPY", "HKD", "TWD", "THB", "KRW", "INR",
    "SGD", "AUD", "CAD", "CHF", "CNY", "MYR", "NZD",
})
_CURRENCY_WORDS: dict[str, str] = {"yen": "JPY", "yuan": "CNY"}

# Plausible per-night lodging range per currency, in the currency's own units.
# Amounts outside the range are treated as fees, transport, or other noise.
_PLAUSIBLE_NATIVE_RANGE: dict[str, tuple[float, float]] = {
    "USD": (15.0, 5000.0),
    "EUR": (15.0, 5000.0),
    "GBP": (10.0, 4000.0),
    "JPY": (3000.0, 200000.0),
    "CNY": (80.0, 30000.0),
    "HKD": (100.0, 30000.0),
    "TWD": (500.0, 100000.0),
    "THB": (300.0, 100000.0),
    "KRW": (20000.0, 2000000.0),
    "INR": (500.0, 150000.0),
    "SGD": (20.0, 8000.0),
    "AUD": (20.0, 6000.0),
    "CAD": (20.0, 6000.0),
    "CHF": (20.0, 5000.0),
    "MYR": (30.0, 15000.0),
    "NZD": (20.0, 6000.0),
}

# Approximate fixed rates for normalizing parsed prices to USD so budget caps
# and plan currency stay consistent (the rest of the pipeline is USD-based).
# Deliberately static and labeled as approximate in the result notes.
_APPROX_USD_PER_UNIT: dict[str, float] = {
    "USD": 1.0, "EUR": 1.1, "GBP": 1.3, "JPY": 0.0068, "CNY": 0.14,
    "HKD": 0.13, "TWD": 0.032, "THB": 0.029, "KRW": 0.00075, "INR": 0.012,
    "SGD": 0.75, "AUD": 0.66, "CAD": 0.73, "CHF": 1.1, "MYR": 0.24,
    "NZD": 0.6,
}

_AMOUNT_PATTERN = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"
_SYMBOL_ALTERNATION = "|".join(
    re.escape(symbol)
    for symbol in sorted(_CURRENCY_SYMBOLS, key=len, reverse=True)
)
_CODE_ALTERNATION = "|".join(sorted(_CURRENCY_CODES, key=len, reverse=True))
_WORD_ALTERNATION = "|".join(sorted(_CURRENCY_WORDS, key=len, reverse=True))

# Currency written before the amount: "US$120", "USD 120", "¥18,000", "yen 12,000"
_PRICE_BEFORE_RE = re.compile(
    rf"(?P<cur>{_SYMBOL_ALTERNATION}|¥|\b(?:{_CODE_ALTERNATION}|{_WORD_ALTERNATION})\b)"
    rf"\s?(?P<amt>{_AMOUNT_PATTERN})",
    re.IGNORECASE,
)
# Currency written after the amount: "120 USD", "1,200 THB", "12,000 yen"
_PRICE_AFTER_RE = re.compile(
    rf"(?P<amt>{_AMOUNT_PATTERN})\s?(?P<cur>\b(?:{_CODE_ALTERNATION}|{_WORD_ALTERNATION})\b)",
    re.IGNORECASE,
)
# Monthly/weekly rates and stay totals are not per-night prices.
_NEGATIVE_CONTEXT_RE = re.compile(
    r"(?:per|a|/)\s?(?:month|week)|monthly|weekly", re.IGNORECASE
)
_NIGHT_CONTEXT_RE = re.compile(r"night", re.IGNORECASE)

# Neighborhood hint: "… in Shibuya, Tokyo …" / "… near Kyoto Station …"
_AREA_HINT_RE = re.compile(
    r"\b(?:in|near)\s+([A-Z][A-Za-z0-9'’-]+(?:\s+[A-Z][A-Za-z0-9'’-]+){0,2})"
)
_AREA_STOPWORDS = frozenset({
    "from", "per", "with", "and", "the", "a", "near", "best", "top",
    "cheap", "budget", "luxury", "rates", "rate", "price", "prices",
    "night", "nights", "hotel", "hotels", "hostel", "hostels",
    "guesthouse", "guest", "house", "motel", "resort", "inn", "stay",
})


def _resolve_currency(token: str, amount: float) -> Optional[str]:
    """Map a matched currency token to an ISO code, or None if unknown."""
    code = _CURRENCY_SYMBOLS.get(token)
    if code:
        return code
    if token == "¥":
        # ¥ means JPY in Japan but CNY elsewhere; magnitude disambiguates
        # (¥18,000/night is Tokyo, ¥350/night is a mainland China hostel).
        return "JPY" if amount >= 2000 else "CNY"
    word = _CURRENCY_WORDS.get(token.casefold())
    if word:
        return word
    upper = token.upper()
    return upper if upper in _CURRENCY_CODES else None


def parse_nightly_price(text: str) -> Optional[tuple[float, str]]:
    """Parse a per-night lodging price from free text (title/snippet).

    Returns ``(amount, currency_code)`` in the currency as written, or None
    when no confident per-night lodging price is present. Only amounts within
    a plausible per-night range for the currency are accepted, monthly/weekly
    rates and stay totals are rejected, and matches near "per night"/"nightly"
    wording are preferred over unrelated numbers.
    """
    if not text:
        return None
    lowered = text.casefold()
    matches: list[tuple[float, str, int, bool]] = []
    for regex in (_PRICE_BEFORE_RE, _PRICE_AFTER_RE):
        for match in regex.finditer(text):
            raw_amount = match.group("amt").replace(",", "")
            try:
                amount = float(raw_amount)
            except ValueError:
                continue
            code = _resolve_currency(match.group("cur"), amount)
            if code is None:
                continue
            low, high = _PLAUSIBLE_NATIVE_RANGE.get(code, (0.0, float("inf")))
            if not low <= amount <= high:
                continue
            start, end = match.span()
            before = lowered[max(0, start - 40):start]
            after = lowered[end:end + 15]
            if _NEGATIVE_CONTEXT_RE.search(after):
                continue
            if "total" in before[-15:]:
                continue
            night_context = bool(
                _NIGHT_CONTEXT_RE.search(after)
                or _NIGHT_CONTEXT_RE.search(lowered[max(0, start - 40):start])
            )
            matches.append((amount, code, start, night_context))
    if not matches:
        return None
    # Prefer per-night wording; tie-break on position.
    matches.sort(key=lambda entry: (not entry[3], entry[2]))
    amount, code, _, _ = matches[0]
    return amount, code


def _to_usd(amount: float, code: str) -> float:
    """Normalize a parsed price to approximate USD (labeled in notes)."""
    return round(amount * _APPROX_USD_PER_UNIT.get(code, 1.0), 2)


def _format_amount(amount: float) -> str:
    """Render 12000.0 as "12,000" and 81.5 as "81.5" for notes."""
    if amount == int(amount):
        return f"{int(amount):,}"
    return f"{amount:,}"


def _unwrap_search_url(url: str) -> str:
    """Resolve DuckDuckGo redirect wrappers (…/l/?uddg=…) to the target page.

    Mirrors ``agents.search_stays.agent._unwrap_result_url``; kept local so
    this module has no import cycle with the agent layer.
    """
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        text = "https:" + text
    try:
        parsed = urlparse(text)
    except ValueError:
        return text
    if "duckduckgo.com" in parsed.netloc.casefold():
        return parse_qs(parsed.query).get("uddg", [""])[0] or text
    return text


def _infer_property_type(folded_text: str) -> str:
    for keyword, property_type in _PROPERTY_TYPE_KEYWORDS:
        if keyword in folded_text:
            return property_type
    return "hotel"


def _extract_area_hint(text: str, destination: str) -> str:
    """Best-effort neighborhood hint ("Shibuya") from "… in Shibuya, Tokyo …"."""
    dest_tokens = {
        token
        for token in destination.casefold().replace(",", " ").split()
        if token
    }
    for match in _AREA_HINT_RE.finditer(text):
        words = [word for word in match.group(1).split()]
        while words and words[0].casefold() in _AREA_STOPWORDS:
            words.pop(0)
        while words and words[-1].casefold() in _AREA_STOPWORDS:
            words.pop()
        # Drop destination-token overlap: "Shibuya Tokyo" → "Shibuya".
        while words and words[0].casefold() in dest_tokens:
            words.pop(0)
        while words and words[-1].casefold() in dest_tokens:
            words.pop()
        if words:
            return " ".join(words)
    return ""


def _map_web_result(result: Any, destination: str) -> Optional[StayCandidate]:
    """Map one web-search result to a StayCandidate, or None if unusable.

    Results are dropped when they don't read as lodging (no stay keyword) or
    clearly don't match the destination. ``nightly_cost`` is set only when a
    price is confidently parsed and normalized to approximate USD; otherwise
    it stays None so ``pricing.apply_estimates`` can label an estimate.
    """
    title = str(getattr(result, "title", "") or "").strip()
    snippet = str(getattr(result, "snippet", "") or "").strip()
    url = _unwrap_search_url(str(getattr(result, "url", "") or ""))
    if not title or not url:
        return None
    text = f"{title}. {snippet}"
    folded = text.casefold()
    if not any(keyword in folded for keyword in _STAY_KEYWORDS):
        return None
    if not _location_matches(text, destination):
        return None

    try:
        host = urlparse(url).netloc.casefold() or "web"
    except ValueError:
        host = "web"
    parsed = parse_nightly_price(text)
    if parsed is not None:
        amount, code = parsed
        nightly_cost = _to_usd(amount, code)
        if code == "USD":
            price_note = f"listed {_format_amount(amount)} USD/night"
        else:
            price_note = (
                f"listed {_format_amount(amount)} {code}/night"
                f" ≈ {nightly_cost:g} USD (approx. fixed rate)"
            )
        currency: Optional[str] = "USD"
    else:
        nightly_cost = None
        currency = None
        price_note = "no nightly price in snippet; estimate below"

    area = _extract_area_hint(text, destination)
    location = f"{destination} {area}" if area else destination
    return StayCandidate(
        name=title,
        location=location,
        nightly_cost=nightly_cost,
        source_url=url,
        notes=f"web search: {host}; {price_note}",
        currency=currency,
        rating=None,
        amenities=[],
        property_type=_infer_property_type(folded),
    )


def _web_stub_fallback(
    destination: str,
    budget: Optional[float],
    days: Optional[int],
    interests: Optional[list[str]],
    reason: str,
) -> list[StayCandidate]:
    """Return the curated stub catalog with a labeled web-mode note."""
    logger.info("Web stays fallback for %r: %s", destination, reason)
    candidates = _search_stub(destination, budget, days, interests)
    for stay in candidates:
        prefix = f"web: {reason}"
        stay.notes = f"{prefix}; {stay.notes}" if stay.notes else prefix
    return candidates


class WebSearchProvider:
    """Find stays via the shared web-search tool (DuckDuckGo HTML search).

    Live engine (``WEB_SEARCH_MODE=duckduckgo``): runs 1–3 bounded queries per
    search (web_search.run applies its own ~15s per-request timeout), maps
    results to StayCandidate, and parses nightly prices from snippets when
    confidently listed (normalized to approximate USD and labeled). Results
    are provenance-labeled with ``web search: <host>`` in notes.

    When the web-search tool itself is in stub mode, the network fails, or no
    usable results come back, the curated stub catalog is returned with a
    labeled note — results are never fabricated.
    """

    def __init__(
        self,
        max_queries: int = _WEB_MAX_QUERIES,
        results_per_query: int = _WEB_RESULTS_PER_QUERY,
    ) -> None:
        self.max_queries = max_queries
        self.results_per_query = results_per_query

    def _run_query(self, query: str) -> list[Any]:
        return web_search_run(query, limit=self.results_per_query)

    def search(
        self,
        destination: str,
        budget: Optional[float] = None,
        days: Optional[int] = None,
        interests: Optional[list[str]] = None,
    ) -> list[StayCandidate]:
        """Search the web for stays at ``destination`` and parse prices."""
        settings = get_settings()
        if getattr(settings, "web_search_mode", "stub") != "duckduckgo":
            return _web_stub_fallback(
                destination, budget, days, interests,
                reason="web search unavailable; showing stub catalog",
            )

        cap = nightly_budget_cap(budget, days)
        cache_key = f"web:{destination.strip().casefold()}:{cap}"
        cached = _search_cache.get(cache_key)
        if cached is not None:
            return cached

        candidates: list[StayCandidate] = []
        seen: set[tuple[str, str]] = set()
        priced_count = 0
        for index, template in enumerate(_WEB_QUERY_TEMPLATES[: self.max_queries]):
            # Third query only when we still lack priced results — this keeps
            # total requests bounded at 3 while usually parsing some prices.
            if index >= 2 and priced_count >= _WEB_MIN_PRICED_RESULTS:
                break
            query = template.format(destination=destination.strip())
            try:
                results = self._run_query(query)
            except Exception as error:  # noqa: BLE001 — network failures must not abort the turn
                logger.warning(
                    "Web stays search query %r failed for %r: %s",
                    query, destination, error,
                )
                return _web_stub_fallback(
                    destination, budget, days, interests,
                    reason="web search unavailable; showing stub catalog",
                )
            for result in results:
                candidate = _map_web_result(result, destination)
                if candidate is None:
                    continue
                key = (candidate.name.casefold(), candidate.source_url or "")
                if key in seen:
                    continue
                seen.add(key)
                if candidate.nightly_cost is not None:
                    priced_count += 1
                candidates.append(candidate)

        if not candidates:
            return _web_stub_fallback(
                destination, budget, days, interests,
                reason="web search returned no usable results; showing stub catalog",
            )

        # Budget cap: priced candidates above the cap are dropped; candidates
        # without a parseable price are kept but sorted last (same as OBO).
        kept = [
            candidate
            for candidate in candidates
            if cap is None or candidate.nightly_cost is None
            or candidate.nightly_cost <= cap
        ]
        if not kept:
            return _web_stub_fallback(
                destination, budget, days, interests,
                reason="web search results over nightly budget; showing stub catalog",
            )

        kept.sort(
            key=lambda c: (c.nightly_cost is None, c.nightly_cost or float("inf"))
        )
        kept = kept[:_WEB_RESULT_CAP]
        _search_cache.set(cache_key, kept)
        return kept

    def health(self) -> dict[str, Any]:
        settings = get_settings()
        engine = getattr(settings, "web_search_mode", "stub")
        return {
            "provider": "web_search",
            "engine_mode": engine,
            "offline_safe": engine == "stub",  # stub engine falls back to the catalog
            "max_queries": self.max_queries,
            "results_per_query": self.results_per_query,
        }


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


def _map_obo_result(
    hotel: dict[str, Any], destination: str, structured_content: dict[str, Any] | None = None
) -> StayCandidate:
    """Map an OBO Travel hotel result to a StayCandidate."""
    name = str(hotel.get("name", "Unnamed hotel"))

    # Location: try structured content destination first, then hotel fields
    location = destination
    if structured_content and isinstance(structured_content, dict):
        loc = structured_content.get("destination")
        if loc:
            location = str(loc)
    if not location or location == destination:
        location = str(
            hotel.get("location")
            or hotel.get("address")
            or hotel.get("city")
            or destination
        )

    # Use per_night_usd (live per-night price) rather than total_price_usd
    nightly_cost = hotel.get("per_night_usd")
    if nightly_cost is None:
        nightly_cost = hotel.get("total_price_usd")
    if nightly_cost is not None:
        try:
            nightly_cost = float(nightly_cost)
        except (TypeError, ValueError):
            nightly_cost = None
    stars = hotel.get("stars")
    rating = None
    if stars is not None:
        try:
            rating = float(stars)
        except (TypeError, ValueError):
            rating = None

    notes_parts = [f"api: obo travel | live price"]
    if rating is not None:
        notes_parts.append(f"stars={rating}")
    fc = hotel.get("free_cancellation_until")
    if fc:
        notes_parts.append(f"free_cancellation_until={fc}")
    token = hotel.get("hotel_token")
    if token:
        notes_parts.append(f"token={token}")

    # Prefer booking_url; photo_url as backup reference
    source_url = hotel.get("booking_url") or hotel.get("photo_url")

    return StayCandidate(
        name=name,
        location=location,
        nightly_cost=nightly_cost,
        source_url=source_url,
        phone=None,
        notes="; ".join(notes_parts),
        currency="USD",
        rating=rating,
        amenities=[],
        property_type="hotel",
        coordinates=None,
        check_in=None,
        check_out=None,
        cancellation_policy=(
            f"Free cancellation until {fc}" if fc else None
        ),
    )

def _location_matches(location: str, destination: str) -> bool:
    loc = location.casefold()
    dest = destination.casefold().strip()
    if not dest:
        return False
    if dest in loc or loc in dest:
        return True
    dest_tokens = [t for t in dest.replace(",", " ").split() if len(t) > 1]
    return any(t in loc for t in dest_tokens)


def _to_candidate(row: dict[str, Any], notes: str) -> StayCandidate:
    return StayCandidate(
        name=row["name"],
        location=row["location"],
        nightly_cost=row.get("nightly_cost"),
        source_url=row.get("source_url"),
        phone=row.get("phone"),
        notes=notes,
        currency=row.get("currency"),
        rating=row.get("rating"),
        amenities=list(row.get("amenities") or []),
        coordinates=row.get("coordinates"),
    )


def _map_overpass_element(el: dict[str, Any], center_lat: float, center_lng: float) -> StayCandidate:
    """Map an Overpass element to a StayCandidate."""
    tags = el.get("tags", {}) or {}
    name = tags.get("name") or "Unnamed lodging"

    # Coordinates: node has lat/lon directly; way/relation has center.lat/center.lon
    lat = el.get("lat") or el.get("center", {}).get("lat") or center_lat
    lng = el.get("lon") or el.get("center", {}).get("lon") or center_lng

    # Build location string from address tags
    addr_parts = []
    for key in ("addr:housenumber", "addr:street", "addr:city", "addr:district", "addr:state"):
        val = tags.get(key)
        if val:
            addr_parts.append(str(val))
    location = ", ".join(addr_parts) if addr_parts else f"Near ({lat:.4f}, {lng:.4f})"

    # Optional OSM tags
    website = tags.get("website")
    phone = tags.get("phone")
    stars = tags.get("stars")
    rating = None
    if stars is not None:
        try:
            rating = float(stars)
        except (TypeError, ValueError):
            rating = None

    amenities: list[str] = []
    if tags.get("internet_access") == "wlan":
        amenities.append("wifi")
    if tags.get("breakfast") == "yes":
        amenities.append("breakfast")
    if tags.get("parking"):
        amenities.append("parking")

    notes_parts = [f"overpass: OpenStreetMap {el.get('type', 'unknown')} id={el.get('id')}"]
    if website:
        notes_parts.append(f"website={website}")
    if phone:
        notes_parts.append(f"phone={phone}")

    return StayCandidate(
        name=str(name),
        location=location,
        nightly_cost=None,
        source_url=website,
        phone=phone,
        notes="; ".join(notes_parts),
        currency=None,
        rating=rating,
        amenities=amenities,
        property_type=tags.get("tourism") or "lodging",
        coordinates={"lat": float(lat), "lng": float(lng)},
        check_in=tags.get("check_in"),
        check_out=tags.get("check_out"),
    )


# ---------------------------------------------------------------------------
# Public search entry point
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, Any] = {}
_PROVIDERS_LOCK = threading.Lock()


def _search_stub(
    destination: str,
    budget: Optional[float],
    days: Optional[int],
    interests: Optional[list[str]] = None,
    limit: int = 5,
) -> list[StayCandidate]:
    cap = nightly_budget_cap(budget, days)
    interests = interests or []

    matched: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []

    for row in _STUB_CATALOG:
        cost = row.get("nightly_cost")
        if cap is not None and cost is not None and cost > cap:
            continue
        if _location_matches(row["location"], destination):
            matched.append(row)
        elif "generic" in row["location"].casefold():
            fallback.append(row)

    pool = matched if matched else fallback
    pool = sorted(
        pool,
        key=lambda r: (r.get("nightly_cost") is None, r.get("nightly_cost") or 0.0),
    )
    pool = pool[: min(len(pool), limit)]

    interest_hint = ""
    if interests:
        interest_hint = "; interests=" + str(interests)
    if cap is not None:
        cap_hint = "; nightly_cap=%.2f" % cap
    else:
        cap_hint = ""
    if matched:
        rationale = "stub: location overlap with %r%s%s" % (destination, cap_hint, interest_hint)
    else:
        rationale = (
            "stub: no city match for %r, using generic catalog%s%s"
            % (destination, cap_hint, interest_hint)
        )

    return [_to_candidate(row, rationale) for row in pool]


def _get_provider(mode: str) -> Any:
    with _PROVIDERS_LOCK:
        if mode in _PROVIDERS:
            return _PROVIDERS[mode]
        settings = get_settings()
        if mode == "stub":
            provider: Any = None  # stub is handled inline, no provider object needed
        elif mode == "overpass":
            provider = OverpassProvider(
                base_urls=[
                    url.strip()
                    for url in getattr(settings, "overpass_api_url", "https://overpass-api.de/api/interpreter").split(",")
                    if url.strip()
                ],
                timeout=float(getattr(settings, "overpass_timeout", 30) or 30),
                radius_meters=int(getattr(settings, "overpass_radius_meters", 5000) or 5000),
            )
        elif mode == "web":
            provider = WebSearchProvider()
        elif mode == "api":
            # legacy OBO Travel provider, kept for rollback (prefer "web")
            provider = ApiProvider(
                endpoint=getattr(settings, "stays_api_base_url", "https://onebookingonline.com/mcp"),
                api_key=getattr(settings, "stays_api_key", ""),
                timeout=float(getattr(settings, "stays_api_timeout", 30) or 30),
            )
        else:
            # unknown modes fall back to stub
            provider = None
        _PROVIDERS[mode] = provider
        return provider


def _clean_destination_for_api(destination: str) -> str:
    """Strip country/region suffixes that external stay APIs don't accept.

    The model may emit destinations like ``"Tokyo, Japan"`` or ``"Paris, France"``,
    but OBO Travel (and most stay APIs) expect just the city name. Remove
    everything after the first comma and trim whitespace.
    """
    if not destination:
        return destination
    # Take only the part before the first comma
    city = destination.split(",")[0].strip()
    return city if city else destination


def _search_api(
    destination: str,
    budget: Optional[float],
    days: Optional[int],
    interests: Optional[list[str]] = None,
    check_in: Optional[str] = None,
    check_out: Optional[str] = None,
) -> list[StayCandidate]:
    """Search via the configured API provider (OBO Travel by default).

    Legacy path kept for rollback — prefer ``TOOL_STAYS_MODE=web``.
    """
    settings = get_settings()
    provider = _get_provider("api")
    if provider is None:
        logger.warning("ApiProvider not initialized")
        return [
            StayCandidate(
                name="Provider error",
                location=destination,
                nightly_cost=None,
                notes="api: provider not initialized",
            )
        ]
    try:
        candidates = provider.search(
            destination=_clean_destination_for_api(destination),
            budget=budget,
            days=days,
            interests=interests,
            check_in=check_in,
            check_out=check_out,
        )
        return candidates
    except Exception as error:  # noqa: BLE001 — provider failures must not abort the turn
        logger.exception("ApiProvider raised unexpectedly for %r", destination)
        return [
            StayCandidate(
                name="Provider error",
                location=destination,
                nightly_cost=None,
                notes=f"api: provider raised {type(error).__name__}: {error}",
            )
        ]


def search_stays(
    destination: str,
    budget: Optional[float] = None,
    days: Optional[int] = None,
    interests: Optional[list[str]] = None,
    use_geocoding: Optional[bool] = None,
    check_in: Optional[str] = None,
    check_out: Optional[str] = None,
) -> list[StayCandidate]:
    """Find stay candidates under a derived nightly budget near destination.

    Modes (TOOL_STAYS_MODE):
      * ``stub`` — curated local catalog (default, offline-safe).
      * ``overpass`` — real OpenStreetMap lodging via Overpass API (no auth).
      * ``web`` — live results via the shared DuckDuckGo web-search tool;
        nightly prices are kept only when confidently parsed from the snippet
        (normalized to approximate USD), otherwise labeled estimates are filled
        in. Requires ``WEB_SEARCH_MODE=duckduckgo``; falls back to the stub
        catalog with a labeled note when web search is unavailable.
      * ``api`` — legacy OBO Travel MCP API (kept for rollback; prefer ``web``).

    If ``use_geocoding`` is true (or GEOCODING_ENABLED=1) the destination is
    geocoded first and coordinates are passed to the provider so results can be
    distance-aware. Overpass always geocodes internally when coordinates aren't
    supplied.

    ``check_in`` and ``check_out`` are ISO-format date strings (YYYY-MM-DD).
    If omitted, check-in defaults to tomorrow and check-out is derived from
    ``days`` (default 3 nights).
    """
    settings = get_settings()
    mode = settings.tool_stays_mode

    if mode == "stub":
        return _search_stub(destination, budget, days, interests)
    if mode == "overpass":
        provider = _get_provider("overpass")
        if provider is None:
            logger.warning("Overpass provider not initialized")
            return _search_stub(destination, budget, days, interests)
        try:
            candidates = provider.search(
                destination=destination,
                budget=budget,
                days=days,
                interests=interests,
            )
            # Overpass returns no nightly cost — fill in heuristic estimates
            candidates = pricing.apply_estimates(candidates, destination)
            return candidates
        except Exception as error:  # noqa: BLE001 — provider failures must not abort the turn
            logger.exception("Overpass provider raised unexpectedly for %r", destination)
            return [
                StayCandidate(
                    name="Provider error",
                    location=destination,
                    nightly_cost=None,
                    notes=f"overpass: provider raised {type(error).__name__}: {error}",
                )
            ]
    if mode == "web":
        provider = _get_provider("web")
        if provider is None:
            logger.warning("Web stays provider not initialized")
            return _search_stub(destination, budget, days, interests)
        try:
            candidates = provider.search(
                destination=destination,
                budget=budget,
                days=days,
                interests=interests,
            )
            # Web snippets often lack a parseable nightly price — fill in
            # labeled heuristic estimates for those, like the overpass path.
            return pricing.apply_estimates(candidates, destination)
        except Exception as error:  # noqa: BLE001 — provider failures must not abort the turn
            logger.exception("Web stays provider raised unexpectedly for %r", destination)
            return [
                StayCandidate(
                    name="Provider error",
                    location=destination,
                    nightly_cost=None,
                    notes=f"web: provider raised {type(error).__name__}: {error}",
                )
            ]
    if mode == "api":
        return _search_api(
            destination,
            budget,
            days,
            interests,
            check_in=check_in,
            check_out=check_out,
        )
    logger.warning("Unknown TOOL_STAYS_MODE=%r; treating as stub", mode)
    return _search_stub(destination, budget, days, interests)


def clear_caches() -> None:
    """Clear all internal caches (mostly for testing)."""
    _geocode_cache.clear()
    _search_cache.clear()
    with _PROVIDERS_LOCK:
        _PROVIDERS.clear()
