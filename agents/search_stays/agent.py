"""Agent 1 - search_stays: accommodation under budget / location."""

from __future__ import annotations

from typing import Any

from agents.search_stays.tools import nightly_budget_cap, search_stays
from config.settings import get_settings
from shared.schemas import StayCandidate, TripRequest


def run(request: TripRequest) -> list[StayCandidate]:
    """Run stay search for a trip request via the stays tool."""
    settings = get_settings()
    mode = settings.tool_stays_mode
    cap = nightly_budget_cap(request.budget, request.days)

    stays = search_stays(
        destination=request.destination,
        budget=request.budget,
        days=request.days,
        interests=request.interests,
    )

    enriched: list[StayCandidate] = []
    for stay in stays:
        note_parts = [
            "TOOL_STAYS_MODE=%s" % mode,
            "filter: destination=%r" % request.destination,
        ]
        if cap is not None:
            note_parts.append("nightly_cap=%.2f" % cap)
        if stay.notes:
            note_parts.append(stay.notes)
        enriched.append(stay.model_copy(update={"notes": "; ".join(note_parts)}))
    return enriched


def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "agent": "search_stays",
        "tool_mode": s.tool_stays_mode,
        "catalog": "stub" if s.tool_stays_mode == "stub" else "api-pending",
    }