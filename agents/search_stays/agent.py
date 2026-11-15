"""Agent 1 - search_stays: accommodation under budget and location."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from config.settings import get_settings
from shared.history_match import stay_overlaps_places
from shared.schemas import StayCandidate, TripRequest

from . import tools


def _overlaps_excluded(stay: StayCandidate, excluded: set[str]) -> bool:
    """True if stay name or location matches a specific visited place."""
    return stay_overlaps_places(stay.name, stay.location, excluded)


def run(
    request: TripRequest,
    excluded_locations: Iterable[str] = (),
) -> list[StayCandidate]:
    """Return stay candidates via tools catalog, excluding travel-history places.

    Uses TOOL_STAYS_MODE (stub catalog or future API). The coordinator passes
    Agent 4 visited places when avoid_visited=true.
    """
    settings = get_settings()
    if settings.tool_stays_mode != "stub" and settings.tool_stays_mode != "api":
        # tools.search_stays already falls back to stub for unknown modes
        pass

    candidates = tools.search_stays(
        destination=request.destination,
        budget=request.budget,
        days=request.days,
        interests=request.interests or None,
    )
    excluded = {place.strip().casefold() for place in excluded_locations if place and place.strip()}
    if not excluded:
        return candidates
    return [stay for stay in candidates if not _overlaps_excluded(stay, excluded)]


def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "agent": "search_stays",
        "tool_mode": s.tool_stays_mode,
        "provider_configured": s.tool_stays_mode == "stub",
        "catalog": "tools.stub" if s.tool_stays_mode == "stub" else s.tool_stays_mode,
    }
