"""Agent 1 — search_stays: accommodation under budget / location."""

from __future__ import annotations

from typing import Any

from config.settings import get_settings
from shared.schemas import StayCandidate, TripRequest


def run(request: TripRequest) -> list[StayCandidate]:
    settings = get_settings()
    if settings.tool_stays_mode == "stub":
        return [
            StayCandidate(
                name="Stub Stay Near Destination",
                location=request.destination,
                nightly_cost=(request.budget or 100) / max(request.days or 3, 1),
                source_url="https://example.com/stay/stub",
                notes=f"stub mode; TOOL_STAYS_MODE={settings.tool_stays_mode}",
            )
        ]
    # api mode: call third-party stay API (not wired yet)
    return []


def health() -> dict[str, Any]:
    s = get_settings()
    return {"agent": "search_stays", "tool_mode": s.tool_stays_mode}
