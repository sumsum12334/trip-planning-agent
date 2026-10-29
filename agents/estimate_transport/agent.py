"""Agent 2 — estimate_transport: travel time & cost between points."""

from __future__ import annotations

from typing import Any

from config.settings import get_settings
from shared.schemas import TransportLeg, TripRequest


def run(request: TripRequest, from_place: str, to_place: str) -> TransportLeg:
    settings = get_settings()
    if settings.tool_maps_mode == "stub":
        return TransportLeg(
            from_place=from_place,
            to_place=to_place,
            mode="stub",
            duration_minutes=30.0,
            cost=5.0,
            source_url="https://example.com/maps/stub",
        )
    # api mode: call maps / transit API (not wired yet)
    return TransportLeg(from_place=from_place, to_place=to_place, mode="unwired")


def health() -> dict[str, Any]:
    s = get_settings()
    return {"agent": "estimate_transport", "tool_mode": s.tool_maps_mode}
