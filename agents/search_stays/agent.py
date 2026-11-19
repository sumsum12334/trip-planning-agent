"""Agent 1 - search_stays: accommodation under budget and location.

Provider selection is driven by ``TOOL_STAYS_MODE``:
  * ``stub``   — curated local catalog (default, offline-safe).
  * ``overpass`` — real OpenStreetMap lodging via Overpass API (no auth).
  * ``api``    — real accommodation provider via OBO Travel MCP API
                 (live prices, booking URLs, no API key required).

OBO Travel requires destination and dates (check_in/check_out). Dates are
derived from TripRequest.start_date/end_date or from ``days``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from config.settings import get_settings
from shared.schemas import StayCandidate, TripRequest

from . import tools


def _overlaps_excluded(stay: StayCandidate, excluded: set[str]) -> bool:
    """True if stay name or location overlaps any excluded place (casefold)."""
    if not excluded:
        return False
    name = stay.name.casefold()
    location = stay.location.casefold()
    return any(place in name or place in location for place in excluded)


def run(
    request: TripRequest,
    excluded_locations: Iterable[str] = (),
) -> list[StayCandidate]:
    """Return stay candidates, excluding travel-history places.

    Uses TOOL_STAYS_MODE (stub catalog or Overpass API). The coordinator passes
    Agent 4 visited places when avoid_visited=true.
    """
    settings = get_settings()
    mode = settings.tool_stays_mode
    if mode not in ("stub", "overpass", "api"):
        # tools.search_stays already falls back to stub for unknown modes
        pass

    candidates = tools.search_stays(
        destination=request.destination,
        budget=request.budget,
        days=request.days,
        interests=request.interests or None,
        use_geocoding=settings.geocoding_enabled,
        check_in=request.start_date.isoformat() if request.start_date else None,
        check_out=request.end_date.isoformat() if request.end_date else None,
    )
    destination = request.destination.strip().casefold()
    excluded = {
        place.strip().casefold()
        for place in excluded_locations
        if place and place.strip() and place.strip().casefold() != destination
    }
    if not excluded:
        return candidates
    return [stay for stay in candidates if not _overlaps_excluded(stay, excluded)]


def health() -> dict[str, Any]:
    s = get_settings()
    provider_info: dict[str, Any] = {"provider": "stub", "offline_safe": True}
    if s.tool_stays_mode == "overpass":
        provider_info = {
            "provider": "overpass",
            "base_urls": [u.strip() for u in s.overpass_api_url.split(",") if u.strip()],
            "radius_meters": s.overpass_radius_meters,
            "offline_safe": False,
            "timeout_seconds": s.overpass_timeout,
        }
    elif s.tool_stays_mode == "api":
        provider_info = {
            "provider": "obo_travel",
            "endpoint": s.stays_api_base_url,
            "api_key_configured": bool(s.stays_api_key),
            "offline_safe": False,
            "timeout_seconds": s.stays_api_timeout,
        }
    if s.tool_stays_mode == "stub":
        provider_configured = True
    elif s.tool_stays_mode == "overpass":
        provider_configured = bool(s.overpass_api_url.strip())
    else:  # api
        provider_configured = bool(s.stays_api_base_url.strip())

    return {
        "agent": "search_stays",
        "tool_mode": s.tool_stays_mode,
        "provider_configured": provider_configured,
        "catalog": s.tool_stays_mode,
        "provider": provider_info,
    }
