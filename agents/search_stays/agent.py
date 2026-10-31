"""Agent 1 - search_stays: accommodation under budget and location."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from config.settings import get_settings
from shared.schemas import StayCandidate, TripRequest


_STUB_STAYS = (
    ("Harbour View Guesthouse", 55.0),
    ("Central Market Hotel", 85.0),
    ("Summit Boutique Hotel", 120.0),
)


def run(
    request: TripRequest,
    excluded_locations: Iterable[str] = (),
) -> list[StayCandidate]:
    """Return stay candidates, excluding locations supplied by travel history.

    The stub is deliberately deterministic so the coordinator and evaluation
    workflow can be exercised without reservation credentials.
    """
    settings = get_settings()
    if settings.tool_stays_mode != "stub":
        raise RuntimeError(
            "TOOL_STAYS_MODE=api is not implemented; use stub until a stay provider is configured."
        )

    excluded = {place.strip().casefold() for place in excluded_locations if place.strip()}
    nights = max(request.days or 3, 1)
    nightly_budget = request.budget / nights if request.budget is not None else None
    candidates = []
    for name, nightly_cost in _STUB_STAYS:
        if nightly_budget is not None and nightly_cost > nightly_budget:
            continue
        if any(
            excluded_place in name.casefold() or excluded_place in request.destination.casefold()
            for excluded_place in excluded
        ):
            continue
        candidates.append(
            StayCandidate(
                name=name,
                location=request.destination,
                nightly_cost=nightly_cost,
                source_url="https://example.com/stay/stub",
                notes="deterministic local candidate; availability requires confirmation",
            )
        )
    return candidates


def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "agent": "search_stays",
        "tool_mode": s.tool_stays_mode,
        "provider_configured": s.tool_stays_mode == "stub",
    }
