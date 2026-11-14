"""Agent 3 — coordinator: distribute / cost / render / revise / POI (MVP)."""

from __future__ import annotations

from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.coordinator.pois import pack_pois
from agents.estimate_transport import run as estimate_transport
from agents.search_stays import run as search_stays
from agents.travel_history import run as travel_history
from config.settings import get_settings
from shared.schemas import DayPlan, Itinerary, StayCandidate, TransportLeg, TripRequest
from shared.prompts import TRIP_PLANNING_SYSTEM_PROMPT
from trip_planning_agent.observability import (
    end_trace,
    start_trace,
    trace_context_for,
)
from trip_planning_agent.tacc_client import TACCClient


class CoordinatorState(TypedDict, total=False):
    request: TripRequest
    session_id: str
    trace_context: dict[str, str] | None
    visited: list[str]
    stays: list[Any]
    itinerary: Itinerary


def trip_length(request: TripRequest) -> int:
    """Number of itinerary days: `days`, else inclusive start/end dates, else 1."""
    if request.days is not None and request.days >= 1:
        return request.days
    if request.start_date and request.end_date:
        return max((request.end_date - request.start_date).days + 1, 1)
    return 1


def _chosen_stay(stays: list[StayCandidate]) -> Optional[StayCandidate]:
    """Prefer the highest-rated candidate; later revise may step down to fit budget."""
    if not stays:
        return None
    return max(stays, key=lambda stay: ((stay.rating or 0), -(stay.nightly_cost or 0)))


def _arrival_transport(request: TripRequest, stay: Optional[StayCandidate]) -> TransportLeg:
    origin = request.origin or request.destination
    stay_loc = stay.location if stay else request.destination
    return estimate_transport(request, origin, stay_loc)


def _day_cost(stay: Optional[StayCandidate], transports: list[TransportLeg]) -> float:
    stay_cost = (stay.nightly_cost or 0) if stay else 0
    return stay_cost + sum((leg.cost or 0) for leg in transports)


def render_days(
    request: TripRequest,
    stays: list[StayCandidate],
    transport: TransportLeg,
    pois_by_day: list[list[str]] | None = None,
) -> list[DayPlan]:
    """Emit one DayPlan per requested day, charging one night on each day."""
    stay = _chosen_stay(stays)
    packed = pois_by_day or []
    days: list[DayPlan] = []
    for index in range(1, trip_length(request) + 1):
        transports = [transport] if index == 1 else []
        pois = packed[index - 1] if index - 1 < len(packed) else []
        days.append(
            DayPlan(
                day_index=index,
                stays=[stay] if stay else [],
                transports=transports,
                pois=list(pois),
                estimated_cost=_day_cost(stay, transports),
            )
        )
    return days


def render_itinerary(
    request: TripRequest,
    stay: Optional[StayCandidate],
    visited: list[str],
    used_history: bool,
    notes: list[str],
) -> Itinerary:
    """Render a complete itinerary around one chosen stay."""
    transport = _arrival_transport(request, stay)
    excluded = visited if request.avoid_visited else []
    packed = pack_pois(
        request.destination,
        trip_length(request),
        interests=request.interests,
        excluded=excluded,
    )
    days = render_days(request, [stay] if stay else [], transport, packed)
    return Itinerary(
        request=request,
        days=days,
        total_estimated_cost=sum((day.estimated_cost or 0) for day in days),
        used_travel_history=used_history,
        notes=list(notes),
    )


def _over_budget(itinerary: Itinerary) -> bool:
    budget = itinerary.request.budget
    return budget is not None and (itinerary.total_estimated_cost or 0) > budget


def revise_itinerary(
    request: TripRequest,
    stays: list[StayCandidate],
    itinerary: Itinerary,
    visited: list[str],
    used_history: bool,
) -> Itinerary:
    """If the plan exceeds budget, step down to a cheaper stay that still fits."""
    if not _over_budget(itinerary):
        return itinerary
    current = itinerary.days[0].stays[0] if itinerary.days and itinerary.days[0].stays else None
    alternatives = [
        stay
        for stay in stays
        if current is None or stay.name != current.name
    ]
    alternatives.sort(key=lambda stay: (-(stay.rating or 0), stay.nightly_cost or 0))
    for stay in alternatives:
        trial = render_itinerary(request, stay, visited, used_history, itinerary.notes)
        if not _over_budget(trial):
            started = current.name if current else "no stay"
            trial.notes = list(itinerary.notes) + [
                f"Revised stay from {started} to {stay.name} to fit budget"
            ]
            return trial
    itinerary.notes = list(itinerary.notes) + ["Revise could not meet budget"]
    return itinerary


def _travel_history_node(state: CoordinatorState) -> CoordinatorState:
    """Run Agent 4 and place its memory result in graph state."""
    return {"visited": travel_history(state["request"])}


def _search_stays_node(state: CoordinatorState) -> CoordinatorState:
    """Run Agent 1 and place accommodation candidates in graph state."""
    request = state["request"]
    excluded = state.get("visited", []) if request.avoid_visited else []
    return {"stays": search_stays(request, excluded_locations=excluded)}


def _coordinate_node(state: CoordinatorState) -> CoordinatorState:
    request = state["request"]
    settings = get_settings()
    tacc = TACCClient(settings)

    visited = state.get("visited", [])
    stays = state.get("stays", [])
    used_history = settings.enable_travel_history
    notes: list[str] = []
    if settings.baseline_a:
        notes.append("Baseline A: Agent 4 disabled (ENABLE_TRAVEL_HISTORY=0)")
    if used_history:
        notes.append(f"Travel history entries considered: {len(visited)}")

    # Optional LLM nudge via TACC (stub-safe)
    _ = tacc.complete(
        f"Outline a {trip_length(request)}-day plan for {request.destination} "
        f"budget={request.budget} interests={request.interests} "
        f"avoid={visited if request.avoid_visited else []}",
        system=TRIP_PLANNING_SYSTEM_PROMPT,
        session_id=state.get("session_id"),
        trace_context=state.get("trace_context"),
    )

    itinerary = render_itinerary(request, _chosen_stay(stays), visited, used_history, notes)
    itinerary = revise_itinerary(request, stays, itinerary, visited, used_history)
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


def run(request: TripRequest, *, session_id: str | None = None) -> Itinerary:
    """Run the current coordinator through the LangGraph boundary."""
    trace = start_trace(
        name="plan.request",
        input=request.model_dump(mode="json"),
        session_id=session_id,
        metadata={"workflow": "plan"},
    )
    try:
        itinerary = _coordinator_graph.invoke(
            {
                "request": request,
                "session_id": session_id,
                "trace_context": trace_context_for(trace),
            }
        )["itinerary"]
    except Exception as error:
        end_trace(trace, output={"error": str(error)}, error=error)
        raise
    end_trace(trace, output=itinerary.model_dump(mode="json"))
    return itinerary


def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "agent": "coordinator",
        "enable_travel_history": s.enable_travel_history,
        "baseline_a": s.baseline_a,
        "tacc_configured": TACCClient(s).configured,
    }
