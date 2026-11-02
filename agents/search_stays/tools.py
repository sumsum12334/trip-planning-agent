"""Stay-search tool: stub catalog (local MVP) or future API."""

from __future__ import annotations

import logging
from typing import Any, Optional

from config.settings import get_settings
from shared.schemas import StayCandidate

logger = logging.getLogger(__name__)

# Curated fake catalog: several city labels + generic entries.
# Destination is user-specified; city labels are only for stub matching.
_STUB_CATALOG: list[dict[str, Any]] = [
    {
        "name": "Harbour View Hostel",
        "location": "Hong Kong Central",
        "nightly_cost": 45.0,
        "currency": "HKD",
        "rating": 4.1,
        "amenities": ["wifi", "locker"],
        "source_url": "https://example.com/stays/hk-hostel",
    },
    {
        "name": "Kowloon Budget Inn",
        "location": "Hong Kong Kowloon",
        "nightly_cost": 70.0,
        "currency": "HKD",
        "rating": 3.9,
        "amenities": ["wifi", "breakfast"],
        "source_url": "https://example.com/stays/hk-inn",
    },
    {
        "name": "Victoria Peak Boutique Hotel",
        "location": "Hong Kong Mid-Levels",
        "nightly_cost": 180.0,
        "currency": "HKD",
        "rating": 4.6,
        "amenities": ["wifi", "gym", "view"],
        "source_url": "https://example.com/stays/hk-boutique",
    },
    {
        "name": "Shibuya Capsule Pod",
        "location": "Tokyo Shibuya",
        "nightly_cost": 55.0,
        "currency": "USD",
        "rating": 4.0,
        "amenities": ["wifi", "locker"],
        "source_url": "https://example.com/stays/tyo-capsule",
    },
    {
        "name": "Asakusa Traditional Ryokan",
        "location": "Tokyo Asakusa",
        "nightly_cost": 120.0,
        "currency": "USD",
        "rating": 4.7,
        "amenities": ["wifi", "onsen", "breakfast"],
        "source_url": "https://example.com/stays/tyo-ryokan",
    },
    {
        "name": "Shinjuku Business Hotel",
        "location": "Tokyo Shinjuku",
        "nightly_cost": 95.0,
        "currency": "USD",
        "rating": 4.2,
        "amenities": ["wifi", "desk"],
        "source_url": "https://example.com/stays/tyo-business",
    },
    {
        "name": "Canal-Side Guesthouse",
        "location": "Amsterdam Centrum",
        "nightly_cost": 85.0,
        "currency": "USD",
        "rating": 4.3,
        "amenities": ["wifi", "bike"],
        "source_url": "https://example.com/stays/ams-guest",
    },
    {
        "name": "Museum Quarter Flat",
        "location": "Amsterdam Museumkwartier",
        "nightly_cost": 140.0,
        "currency": "USD",
        "rating": 4.5,
        "amenities": ["wifi", "kitchen"],
        "source_url": "https://example.com/stays/ams-flat",
    },
    {
        "name": "Downtown Transit Hostel",
        "location": "Generic City Center",
        "nightly_cost": 40.0,
        "currency": "USD",
        "rating": 3.8,
        "amenities": ["wifi", "locker"],
        "source_url": "https://example.com/stays/generic-hostel",
    },
    {
        "name": "City Park Midrange Hotel",
        "location": "Generic Downtown",
        "nightly_cost": 90.0,
        "currency": "USD",
        "rating": 4.1,
        "amenities": ["wifi", "breakfast", "parking"],
        "source_url": "https://example.com/stays/generic-mid",
    },
    {
        "name": "Riverside Suites",
        "location": "Generic Waterfront",
        "nightly_cost": 160.0,
        "currency": "USD",
        "rating": 4.4,
        "amenities": ["wifi", "kitchen", "laundry"],
        "source_url": "https://example.com/stays/generic-suites",
    },
    {
        "name": "Airport Express Motel",
        "location": "Generic Airport Area",
        "nightly_cost": 65.0,
        "currency": "USD",
        "rating": 3.6,
        "amenities": ["wifi", "shuttle"],
        "source_url": "https://example.com/stays/generic-airport",
    },
]


def nightly_budget_cap(budget: Optional[float], days: Optional[int]) -> Optional[float]:
    """Max nightly spend derived from total budget and trip length."""
    if budget is None:
        return None
    night_count = days if days and days > 0 else 3
    return budget / night_count


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
        notes=notes,
        currency=row.get("currency"),
        rating=row.get("rating"),
        amenities=list(row.get("amenities") or []),
    )


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
    pool = pool[: min(len(pool), 5)]

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


def _search_api(
    destination: str,
    budget: Optional[float],
    days: Optional[int],
    interests: Optional[list[str]] = None,
) -> list[StayCandidate]:
    msg = (
        "TOOL_STAYS_MODE=api is not wired yet "
        "(destination=%r, budget=%s, days=%s, interests=%s)"
        % (destination, budget, days, interests)
    )
    logger.warning(msg)
    raise NotImplementedError(msg)


def search_stays(
    destination: str,
    budget: Optional[float] = None,
    days: Optional[int] = None,
    interests: Optional[list[str]] = None,
) -> list[StayCandidate]:
    """Find stay candidates under a derived nightly budget near destination."""
    settings = get_settings()
    mode = settings.tool_stays_mode
    if mode == "stub":
        return _search_stub(destination, budget, days, interests)
    if mode == "api":
        return _search_api(destination, budget, days, interests)
    logger.warning("Unknown TOOL_STAYS_MODE=%s; treating as stub", mode)
    return _search_stub(destination, budget, days, interests)