"""Transport-estimate tool: stub route catalog (local MVP) or future maps API."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Optional

from config.settings import get_settings
from shared.schemas import TransportLeg

logger = logging.getLogger(__name__)

# Curated fake legs: city labels for stub matching + generic templates.
# Places are free-form; city tokens only help the stub pick a sensible mode.
_STUB_CATALOG: list[dict[str, Any]] = [
    # Hong Kong
    {
        "city_tokens": ["hong kong", "hk", "kowloon", "central", "tsim sha tsui", "mong kok"],
        "from_hint": "Central",
        "to_hint": "Kowloon",
        "mode": "metro",
        "duration_minutes": 18.0,
        "cost": 12.0,
        "currency": "HKD",
        "source_url": "https://example.com/maps/hk-mtr-central-kowloon",
    },
    {
        "city_tokens": ["hong kong", "hk", "airport", "central"],
        "from_hint": "Hong Kong Airport",
        "to_hint": "Central",
        "mode": "airport_express",
        "duration_minutes": 24.0,
        "cost": 115.0,
        "currency": "HKD",
        "source_url": "https://example.com/maps/hk-airport-express",
    },
    {
        "city_tokens": ["hong kong", "hk", "mid-levels", "central"],
        "from_hint": "Central",
        "to_hint": "Mid-Levels",
        "mode": "walk",
        "duration_minutes": 22.0,
        "cost": 0.0,
        "currency": "HKD",
        "source_url": "https://example.com/maps/hk-central-midlevels",
    },
    {
        "city_tokens": ["hong kong", "hk", "tst", "tsim sha tsui", "mong kok"],
        "from_hint": "Tsim Sha Tsui",
        "to_hint": "Mong Kok",
        "mode": "bus",
        "duration_minutes": 15.0,
        "cost": 5.5,
        "currency": "HKD",
        "source_url": "https://example.com/maps/hk-bus-tst-mk",
    },
    # Tokyo
    {
        "city_tokens": ["tokyo", "shibuya", "shinjuku", "asakusa"],
        "from_hint": "Shibuya",
        "to_hint": "Shinjuku",
        "mode": "metro",
        "duration_minutes": 12.0,
        "cost": 180.0,
        "currency": "JPY",
        "source_url": "https://example.com/maps/tyo-metro-shibuya-shinjuku",
    },
    {
        "city_tokens": ["tokyo", "narita", "haneda", "airport", "shinjuku"],
        "from_hint": "Narita Airport",
        "to_hint": "Shinjuku",
        "mode": "train",
        "duration_minutes": 80.0,
        "cost": 3200.0,
        "currency": "JPY",
        "source_url": "https://example.com/maps/tyo-narita-express",
    },
    {
        "city_tokens": ["tokyo", "asakusa", "shibuya"],
        "from_hint": "Asakusa",
        "to_hint": "Shibuya",
        "mode": "metro",
        "duration_minutes": 35.0,
        "cost": 280.0,
        "currency": "JPY",
        "source_url": "https://example.com/maps/tyo-metro-asakusa-shibuya",
    },
    {
        "city_tokens": ["tokyo", "shinjuku"],
        "from_hint": "Shinjuku Station",
        "to_hint": "Shinjuku Hotel",
        "mode": "walk",
        "duration_minutes": 10.0,
        "cost": 0.0,
        "currency": "JPY",
        "source_url": "https://example.com/maps/tyo-walk-shinjuku",
    },
    # Amsterdam
    {
        "city_tokens": ["amsterdam", "centrum", "museumkwartier", "museum"],
        "from_hint": "Amsterdam Centraal",
        "to_hint": "Museumkwartier",
        "mode": "tram",
        "duration_minutes": 20.0,
        "cost": 3.4,
        "currency": "EUR",
        "source_url": "https://example.com/maps/ams-tram-centraal-museum",
    },
    {
        "city_tokens": ["amsterdam", "schiphol", "airport", "centrum"],
        "from_hint": "Schiphol Airport",
        "to_hint": "Amsterdam Centraal",
        "mode": "train",
        "duration_minutes": 18.0,
        "cost": 5.9,
        "currency": "EUR",
        "source_url": "https://example.com/maps/ams-train-schiphol",
    },
    {
        "city_tokens": ["amsterdam", "centrum", "canal"],
        "from_hint": "Dam Square",
        "to_hint": "Canal Belt",
        "mode": "bike",
        "duration_minutes": 12.0,
        "cost": 0.0,
        "currency": "EUR",
        "source_url": "https://example.com/maps/ams-bike-dam-canal",
    },
    # Generic templates (used when no city match)
    {
        "city_tokens": ["generic"],
        "from_hint": "City Center",
        "to_hint": "Downtown Stay",
        "mode": "metro",
        "duration_minutes": 25.0,
        "cost": 3.5,
        "currency": "USD",
        "source_url": "https://example.com/maps/generic-metro",
        "generic": True,
    },
    {
        "city_tokens": ["generic"],
        "from_hint": "Airport",
        "to_hint": "City Center",
        "mode": "taxi",
        "duration_minutes": 40.0,
        "cost": 35.0,
        "currency": "USD",
        "source_url": "https://example.com/maps/generic-airport-taxi",
        "generic": True,
    },
    {
        "city_tokens": ["generic"],
        "from_hint": "Hotel",
        "to_hint": "Attraction",
        "mode": "bus",
        "duration_minutes": 22.0,
        "cost": 2.5,
        "currency": "USD",
        "source_url": "https://example.com/maps/generic-bus",
        "generic": True,
    },
    {
        "city_tokens": ["generic"],
        "from_hint": "Station",
        "to_hint": "Hotel",
        "mode": "walk",
        "duration_minutes": 14.0,
        "cost": 0.0,
        "currency": "USD",
        "source_url": "https://example.com/maps/generic-walk",
        "generic": True,
    },
]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").casefold().strip())


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", _normalize(text)) if len(t) > 1}


def _places_same(a: str, b: str) -> bool:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    # Strong overlap: one fully contained in the other, or Jaccard high
    if ta <= tb or tb <= ta:
        return True
    inter = len(ta & tb)
    union = len(ta | tb)
    return union > 0 and (inter / union) >= 0.8


# Tokens that describe a place type, not a city. Matching only on these
# (e.g. "airport") would let a Hong Kong catalog row win for Paris CDG.
_GENERIC_CITY_TOKENS = frozenset({
    "airport",
    "central",
    "station",
    "museum",
    "downtown",
    "hotel",
    "generic",
    "harbour",
    "harbor",
    "canal",
    "park",
    "city",
    "area",
})


def _distinctive_city_tokens(row: dict[str, Any]) -> list[str]:
    return [
        token
        for token in (row.get("city_tokens") or [])
        if token and _normalize(token) not in _GENERIC_CITY_TOKENS
    ]


def _score_row(row: dict[str, Any], from_place: str, to_place: str) -> float:
    """Higher is better. Distinctive city-token hits + hint overlap with from/to."""
    if row.get("generic"):
        return -1.0
    place_blob = _normalize(f"{from_place} {to_place}")
    city_hits = sum(1 for tok in _distinctive_city_tokens(row) if tok in place_blob)
    if city_hits == 0:
        return 0.0
    from_toks = _tokens(from_place)
    to_toks = _tokens(to_place)
    hint_from = _tokens(str(row.get("from_hint") or ""))
    hint_to = _tokens(str(row.get("to_hint") or ""))
    hint_score = len(from_toks & hint_from) + len(to_toks & hint_to)
    # Also reward reverse direction lightly
    reverse = len(from_toks & hint_to) + len(to_toks & hint_from)
    return float(city_hits * 10 + hint_score * 3 + reverse)


def _deterministic_scale(from_place: str, to_place: str) -> float:
    """Stable 0.75–1.75 scale from place strings (no randomness)."""
    digest = hashlib.sha256(f"{_normalize(from_place)}|{_normalize(to_place)}".encode()).hexdigest()
    bucket = int(digest[:8], 16) % 101  # 0..100
    return 0.75 + (bucket / 100.0)  # 0.75..1.75


def _pick_generic_template(from_place: str, to_place: str) -> dict[str, Any]:
    blob = _normalize(f"{from_place} {to_place}")
    generics = [r for r in _STUB_CATALOG if r.get("generic")]
    if "airport" in blob:
        return next(r for r in generics if r["mode"] == "taxi")
    if "station" in blob or "hotel" in blob:
        walk = next((r for r in generics if r["mode"] == "walk"), generics[-1])
        return walk
    # Prefer metro for city hops; bus as alternate based on hash
    scale_bucket = int(hashlib.sha256(blob.encode()).hexdigest()[:2], 16)
    if scale_bucket % 2 == 0:
        return next(r for r in generics if r["mode"] == "metro")
    return next(r for r in generics if r["mode"] == "bus")


def match_catalog_row(from_place: str, to_place: str) -> Optional[dict[str, Any]]:
    """Best non-generic catalog row for tests / debugging, or None."""
    best: Optional[dict[str, Any]] = None
    best_score = 0.0
    for row in _STUB_CATALOG:
        score = _score_row(row, from_place, to_place)
        if score > best_score:
            best_score = score
            best = row
    return best if best_score > 0 else None


def _same_place_leg(from_place: str, to_place: str) -> TransportLeg:
    return TransportLeg(
        from_place=from_place,
        to_place=to_place,
        mode="walk",
        duration_minutes=7.0,
        cost=0.0,
        source_url="https://example.com/maps/stub-same-place",
        notes="stub: same place (or near-identical labels); short walk",
    )


def _leg_from_row(
    row: dict[str, Any],
    from_place: str,
    to_place: str,
    *,
    scale: float = 1.0,
    notes: str,
) -> TransportLeg:
    duration = float(row["duration_minutes"]) * scale
    cost = float(row["cost"]) * scale
    return TransportLeg(
        from_place=from_place,
        to_place=to_place,
        mode=str(row["mode"]),
        duration_minutes=round(duration, 1),
        cost=round(cost, 2),
        source_url=row.get("source_url"),
        notes=notes,
    )


def _estimate_stub(
    from_place: str,
    to_place: str,
    destination: Optional[str] = None,
) -> TransportLeg:
    if _places_same(from_place, to_place):
        return _same_place_leg(from_place, to_place)

    # Enrich matching with trip destination when places are sparse labels
    enriched_from = from_place
    enriched_to = to_place
    if destination:
        dest = destination.strip()
        if dest and dest.casefold() not in _normalize(from_place):
            enriched_from = f"{from_place} {dest}"
        if dest and dest.casefold() not in _normalize(to_place):
            enriched_to = f"{to_place} {dest}"

    matched = match_catalog_row(enriched_from, enriched_to)
    if matched is None and destination:
        matched = match_catalog_row(destination, destination)

    if matched is not None:
        notes = (
            "stub: catalog match city=%s mode=%s"
            % (",".join(matched.get("city_tokens") or [])[:40], matched["mode"])
        )
        return _leg_from_row(matched, from_place, to_place, notes=notes)

    template = _pick_generic_template(from_place, to_place)
    scale = _deterministic_scale(from_place, to_place)
    # Longer token distance → slightly longer trip (still deterministic)
    token_gap = abs(len(_tokens(from_place)) - len(_tokens(to_place))) + max(
        len(_tokens(from_place) | _tokens(to_place)), 1
    )
    distance_factor = 0.9 + min(token_gap, 12) * 0.04  # ~0.94..1.38
    scale *= distance_factor
    notes = (
        "stub: no city match for %r→%r; generic %s scaled=%.2f"
        % (from_place, to_place, template["mode"], scale)
    )
    return _leg_from_row(template, from_place, to_place, scale=scale, notes=notes)


def _estimate_api(
    from_place: str,
    to_place: str,
    destination: Optional[str] = None,
) -> TransportLeg:
    msg = (
        "TOOL_MAPS_MODE=api is not wired yet "
        "(from_place=%r, to_place=%r, destination=%r)"
        % (from_place, to_place, destination)
    )
    logger.warning(msg)
    raise NotImplementedError(msg)


def estimate_transport(
    from_place: str,
    to_place: str,
    destination: Optional[str] = None,
) -> TransportLeg:
    """Estimate a single transport leg between two places."""
    settings = get_settings()
    mode = settings.tool_maps_mode
    if mode == "stub":
        return _estimate_stub(from_place, to_place, destination)
    if mode == "api":
        return _estimate_api(from_place, to_place, destination)
    logger.warning("Unknown TOOL_MAPS_MODE=%s; treating as stub", mode)
    return _estimate_stub(from_place, to_place, destination)
