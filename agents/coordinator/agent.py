"""Agent 3 — coordinator: distribute / cost / render / revise / POI (MVP)."""

from __future__ import annotations

from typing import Any

from agents.estimate_transport import run as estimate_transport
from agents.search_stays import run as search_stays
from agents.travel_history import run as travel_history
from config.settings import get_settings
from shared.schemas import DayPlan, Itinerary, TripRequest
from trip_planning_agent.tacc_client import TACCClient


def run(request: TripRequest) -> Itinerary:
    settings = get_settings()
    tacc = TACCClient(settings)

    visited: list[str] = []
    used_history = False
    if settings.enable_travel_history:
        visited = travel_history(request)
        used_history = True

    stays = search_stays(request)
    origin = request.origin or request.destination
    stay_loc = stays[0].location if stays else request.destination
    transport = estimate_transport(request, origin, stay_loc)

    # Optional LLM nudge via TACC (stub-safe)
    _ = tacc.complete(
        f"Outline a day plan for {request.destination} "
        f"budget={request.budget} interests={request.interests} "
        f"avoid={visited if request.avoid_visited else []}"
    )

    day = DayPlan(
        day_index=1,
        stays=stays,
        transports=[transport],
        pois=[],  # Coordinator owns POI for MVP
        estimated_cost=(stays[0].nightly_cost if stays else 0) or 0,
    )
    notes = []
    if settings.baseline_a:
        notes.append("Baseline A: Agent 4 disabled (ENABLE_TRAVEL_HISTORY=0)")
    if used_history:
        notes.append(f"Travel history entries considered: {len(visited)}")

    return Itinerary(
        request=request,
        days=[day],
        total_estimated_cost=day.estimated_cost,
        used_travel_history=used_history,
        notes=notes,
    )


def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "agent": "coordinator",
        "enable_travel_history": s.enable_travel_history,
        "baseline_a": s.baseline_a,
        "tacc_configured": TACCClient(s).configured,
    }
