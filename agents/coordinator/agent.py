"""Agent 3 — coordinator: distribute / cost / render / revise / POI (MVP)."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.estimate_transport import run as estimate_transport
from agents.search_stays import run as search_stays
from agents.travel_history import run as travel_history
from config.settings import get_settings
from shared.schemas import DayPlan, Itinerary, TripRequest
from shared.prompts import TRIP_PLANNING_SYSTEM_PROMPT
from trip_planning_agent.tacc_client import TACCClient


class CoordinatorState(TypedDict, total=False):
    request: TripRequest
    visited: list[str]
    stays: list[Any]
    itinerary: Itinerary


def _travel_history_node(state: CoordinatorState) -> CoordinatorState:
    """Run Agent 4 and place its memory result in graph state."""
    return {"visited": travel_history(state["request"])}


def _search_stays_node(state: CoordinatorState) -> CoordinatorState:
    """Run Agent 1 and place accommodation candidates in graph state."""
    return {"stays": search_stays(state["request"])}


def _coordinate_node(state: CoordinatorState) -> CoordinatorState:
    request = state["request"]
    settings = get_settings()
    tacc = TACCClient(settings)

    visited = state.get("visited", [])
    stays = state.get("stays", [])
    used_history = settings.enable_travel_history
    origin = request.origin or request.destination
    stay_loc = stays[0].location if stays else request.destination
    transport = estimate_transport(request, origin, stay_loc)

    # Optional LLM nudge via TACC (stub-safe)
    _ = tacc.complete(
        f"Outline a day plan for {request.destination} "
        f"budget={request.budget} interests={request.interests} "
        f"avoid={visited if request.avoid_visited else []}",
        system=TRIP_PLANNING_SYSTEM_PROMPT,
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

    itinerary = Itinerary(
        request=request,
        days=[day],
        total_estimated_cost=day.estimated_cost,
        used_travel_history=used_history,
        notes=notes,
    )
    return {"itinerary": itinerary}


_graph = StateGraph(CoordinatorState)
_graph.add_node("travel_history", _travel_history_node)
_graph.add_node("search_stays", _search_stays_node)
_graph.add_node("coordinate", _coordinate_node)
_graph.add_edge(START, "travel_history")
_graph.add_edge("travel_history", "search_stays")
_graph.add_edge("search_stays", "coordinate")
_graph.add_edge("coordinate", END)
_coordinator_graph = _graph.compile()


def run(request: TripRequest) -> Itinerary:
    """Run the current coordinator through the LangGraph boundary."""
    return _coordinator_graph.invoke({"request": request})["itinerary"]


def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "agent": "coordinator",
        "enable_travel_history": s.enable_travel_history,
        "baseline_a": s.baseline_a,
        "tacc_configured": TACCClient(s).configured,
    }
