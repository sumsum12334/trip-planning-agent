"""Agent 2 - estimate_transport: travel time & cost between points."""

from __future__ import annotations

from typing import Any

from config.settings import get_settings
from shared.schemas import TransportLeg, TripRequest

from . import tools


def run(request: TripRequest, from_place: str, to_place: str) -> TransportLeg:
    """Return one transport leg via tools catalog (stub or future maps API).

    Signature is fixed for the coordinator: run(request, from_place, to_place).
    Destination / origin on the TripRequest enrich stub city matching.
    """
    return tools.estimate_transport(
        from_place=from_place,
        to_place=to_place,
        destination=request.destination or request.origin,
    )


def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "agent": "estimate_transport",
        "tool_mode": s.tool_maps_mode,
        "provider_configured": s.tool_maps_mode == "stub",
        "catalog": "tools.stub" if s.tool_maps_mode == "stub" else s.tool_maps_mode,
    }
