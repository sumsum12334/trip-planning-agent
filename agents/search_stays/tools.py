"""Stay-search tool: stub catalog (local MVP), OpenStreetMap Overpass API,
or OBO Travel live booking API."""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, timedelta
from typing import Any, Optional

import httpx
from urllib.parse import urlencode

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
# OBO Travel API provider (Agent 1, used when TOOL_STAYS_MODE=api)
# ---------------------------------------------------------------------------

class ApiProvider:
    """OBO Travel accommodation provider via MCP JSON-RPC 2.0 endpoint.

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
        elif mode == "api":
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


def _search_api(
    destination: str,
    budget: Optional[float],
    days: Optional[int],
    interests: Optional[list[str]] = None,
    check_in: Optional[str] = None,
    check_out: Optional[str] = None,
) -> list[StayCandidate]:
    """Search via the configured API provider (OBO Travel by default)."""
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
            destination=destination,
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
      * ``api`` — real accommodation provider via OBO Travel MCP API.

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
