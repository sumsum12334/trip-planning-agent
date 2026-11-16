"""Stay price estimation for Overpass results (no external provider needed).

OpenStreetMap does not store nightly rates or real-time availability, so this
module derives *estimates* from property type, star rating, and location tier.
Every estimated price is clearly labeled so users know it is not live pricing.

Estimation model (all values in USD per night unless otherwise noted):
  * Base by property type:
      hostel/capsule   $35–$70
      guest_house      $60–$110
      hotel            $90–$200
      motel            $50–$95
      ryokan           $150–$300
      apartment        $100–$220
      unknown          $70–$130
  * Star rating adjustment:
      each star adds ~15% (1 star ≈ base, 5 stars ≈ base × 1.75)
  * Location tier (destination keyword heuristic):
      major world city (Tokyo, NYC, London, Paris, etc.) × 1.3
      tourist city (Kyoto, Osaka, Barcelona, etc.) × 1.15
      default × 1.0
  * Currency: estimates are in USD; if a currency override is desired the
    caller can post-process.

This is intentionally simple and transparent — not a rate shopper. For real,
bookable rates wire up a provider such as Rakuten Travel, Agoda, or Booking.com.
"""

from __future__ import annotations

from typing import Optional

from shared.schemas import StayCandidate

# Base nightly rate range (USD) by OpenStreetMap tourism type.
_BASE_RATE_BY_TYPE: dict[str, tuple[float, float]] = {
    "hostel": (35.0, 70.0),
    "capsule": (35.0, 70.0),
    "guest_house": (60.0, 110.0),
    "guesthouse": (60.0, 110.0),
    "hotel": (90.0, 200.0),
    "motel": (50.0, 95.0),
    "ryokan": (150.0, 300.0),
    "apartment": (100.0, 220.0),
    "chalet": (80.0, 150.0),
    "resort": (150.0, 350.0),
    "camp_site": (20.0, 60.0),
    "alpine_hut": (30.0, 70.0),
    "unknown": (70.0, 130.0),
}

# Destination keywords that suggest higher price tiers.
_MAJOR_CITY_KEYWORDS = {
    "tokyo", "osaka", "kyoto", "new york", "london", "paris", "sydney",
    "singapore", "hong kong", "bangkok", "seoul", "dubai", "san francisco",
    "los angeles", "chicago", "berlin", "rome", "amsterdam", "barcelona",
    "madrid", "milan", "vienna", "prague", "budapest",
}
_TOURIST_CITY_KEYWORDS = {
    "kyoto", "osaka", "nara", "hiroshima", "kanazawa", "takayama",
    "barcelona", "prague", "budapest", "dubrovnik", "santorini", "venice",
    "florence", "cape town", "marrakech", "bali", "phuket", "chiang mai",
    "queenstown", "banff", "reykjavik",
}

_STAR_MULTIPLIER = 0.15  # each star adds 15% of base


def _tier_multiplier(destination: str) -> float:
    dest = destination.casefold()
    for kw in _MAJOR_CITY_KEYWORDS:
        if kw in dest:
            return 1.30
    for kw in _TOURIST_CITY_KEYWORDS:
        if kw in dest:
            return 1.15
    return 1.00


def _base_for_type(property_type: Optional[str]) -> tuple[float, float]:
    key = (property_type or "unknown").casefold().strip()
    if key in _BASE_RATE_BY_TYPE:
        return _BASE_RATE_BY_TYPE[key]
    # Fallback: match common substrings
    for k, v in _BASE_RATE_BY_TYPE.items():
        if k in key or key in k:
            return v
    return _BASE_RATE_BY_TYPE["unknown"]


def estimate_nightly_cost(
    stay: StayCandidate,
    destination: str,
    currency: str = "USD",
) -> float:
    """Return an estimated nightly cost in ``currency`` for ``stay``.

    The estimate is derived from property type, star rating, and destination
    tier. It is clearly *not* a live rate — callers must label results as
    estimates.
    """
    low, high = _base_for_type(stay.property_type)
    base = (low + high) / 2.0

    # Star rating adjustment: each star adds ~15% of base
    stars = stay.rating or 0.0
    stars = max(0.0, min(5.0, stars))
    base *= 1.0 + stars * _STAR_MULTIPLIER

    # Location tier
    base *= _tier_multiplier(destination)

    # Round to nearest 5 USD for readability
    estimated = round(base / 5.0) * 5.0
    return max(estimated, 15.0)  # floor at $15/night


def apply_estimates(
    stays: list[StayCandidate],
    destination: str,
    currency: str = "USD",
) -> list[StayCandidate]:
    """Return a copy of ``stays`` with estimated nightly costs filled in.

    Stays that already have a ``nightly_cost`` are left unchanged. Estimated
    stays get ``currency`` set and an estimate note appended to ``notes``.
    """
    result: list[StayCandidate] = []
    for stay in stays:
        # Skip error/placeholder candidates (no real lodging data)
        if stay.nightly_cost is not None:
            result.append(stay)
            continue
        name_lower = (stay.name or "").casefold()
        if any(token in name_lower for token in ("error", "failed", "not configured")):
            result.append(stay)
            continue
        estimated = estimate_nightly_cost(stay, destination, currency)
        notes = (stay.notes or "").rstrip()
        estimate_note = f"estimated_nightly_cost=${estimated:.0f} {currency} (heuristic, not live rate)"
        notes = f"{notes}; {estimate_note}" if notes else estimate_note
        result.append(
            StayCandidate(
                name=stay.name,
                location=stay.location,
                nightly_cost=estimated,
                source_url=stay.source_url,
                notes=notes,
                currency=currency,
                rating=stay.rating,
                review_count=stay.review_count,
                amenities=stay.amenities,
                property_type=stay.property_type,
                coordinates=stay.coordinates,
                check_in=stay.check_in,
                check_out=stay.check_out,
                cancellation_policy=stay.cancellation_policy,
            )
        )
    return result
