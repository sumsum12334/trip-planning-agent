"""Agent 3 — coordinator: distribute / cost / render / revise / POI (MVP)."""

from __future__ import annotations

import json
from typing import Any, Optional, TypedDict

import httpx

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


class NoFeasiblePlanError(ValueError):
    """Raised when the coordinator cannot meet the request constraints."""


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


def _components_currency(
    stays: list[StayCandidate], transports: list[TransportLeg]
) -> Optional[str]:
    """Single currency across all costed components, or None when unknown.

    Raises NoFeasiblePlanError when costed components carry different
    currencies: summing them would make the budget check meaningless. Returns
    None when nothing is costed, or when a positive cost has no currency label
    (the caller notes that the budget was not enforced).
    """
    known: set[str] = set()
    has_unlabeled_cost = False
    for stay in stays:
        if (stay.nightly_cost or 0) > 0:
            if stay.currency:
                known.add(stay.currency)
            else:
                has_unlabeled_cost = True
    for leg in transports:
        if (leg.cost or 0) > 0:
            if leg.currency:
                known.add(leg.currency)
            else:
                has_unlabeled_cost = True
    if len(known) > 1:
        raise NoFeasiblePlanError(
            "no feasible stay: plan components mix currencies ("
            + ", ".join(sorted(known))
            + "); the budget cannot be checked honestly"
        )
    if has_unlabeled_cost:
        return None
    return next(iter(known)) if known else None


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
    currency = _components_currency([stay] if stay else [], [transport])
    return Itinerary(
        request=request,
        days=days,
        total_estimated_cost=sum((day.estimated_cost or 0) for day in days),
        currency=currency,
        used_travel_history=used_history,
        notes=list(notes),
    )


def _over_budget(itinerary: Itinerary) -> bool:
    budget = itinerary.request.budget
    if budget is None or itinerary.currency is None:
        # Without a known plan currency the total cannot be compared honestly.
        return False
    return (itinerary.total_estimated_cost or 0) > budget


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
        try:
            trial = render_itinerary(request, stay, visited, used_history, itinerary.notes)
        except NoFeasiblePlanError:
            # The alternative mixes currencies; it cannot be cost-checked.
            continue
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

    if not stays:
        raise NoFeasiblePlanError(
            "no feasible stay: all candidates over budget or none matched"
        )

    itinerary = render_itinerary(request, _chosen_stay(stays), visited, used_history, notes)
    itinerary = revise_itinerary(request, stays, itinerary, visited, used_history)
    if _over_budget(itinerary):
        raise NoFeasiblePlanError(
            "no feasible stay: plan still exceeds budget after revise"
        )
    if request.budget is not None and itinerary.currency is None:
        itinerary.notes.append(
            "Budget not enforced: some cost components have no currency label"
        )
    itinerary.notes.extend(
        _summary_notes(
            tacc,
            request,
            itinerary,
            session_id=state.get("session_id"),
            trace_context=state.get("trace_context"),
        )
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


def _parse_summary_notes(text: str) -> list[str]:
    """Parse the model's JSON summary; tolerate code fences and junk."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").lstrip()
        if cleaned[:4].casefold() == "json":
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    raw_notes = parsed.get("notes") if isinstance(parsed, dict) else None
    if not isinstance(raw_notes, list):
        return []
    notes: list[str] = []
    for item in raw_notes[:3]:
        if not isinstance(item, str):
            continue
        note = item.strip()
        if note:
            notes.append(f"Model summary: {note[:160]}")
    return notes


def _summary_notes(
    tacc: TACCClient,
    request: TripRequest,
    itinerary: Itinerary,
    *,
    session_id: str | None = None,
    trace_context: dict[str, str] | None = None,
) -> list[str]:
    """Agent 3 summarize role: model-authored notes on the finalized plan.

    The notes are used only when the model endpoint is configured and returns
    parseable JSON; stub mode, network errors, and malformed output leave the
    deterministic notes unchanged. The response is a summary, never hidden
    chain-of-thought.
    """
    if not tacc.configured:
        return []
    stay = (
        itinerary.days[0].stays[0]
        if itinerary.days and itinerary.days[0].stays
        else None
    )
    day_lines = "; ".join(
        f"Day {day.day_index}: " + (", ".join(day.pois) if day.pois else "no stops listed")
        for day in itinerary.days
    )
    stay_text = "none"
    if stay is not None:
        stay_text = stay.name
        if stay.nightly_cost is not None:
            stay_text += f" at {stay.nightly_cost} {stay.currency or ''} per night"
    arrival = (
        itinerary.days[0].transports[0].mode
        if itinerary.days and itinerary.days[0].transports
        else "none"
    )
    prompt = (
        "Summarize this finalized trip plan for the traveler in 1-3 short notes "
        "(each under 120 characters): what the plan covers, the stay and arrival "
        "transport choice, and the main budget trade-off.\n"
        f"Destination: {request.destination}. "
        f"Trip length: {len(itinerary.days)} day(s). "
        f"Stay: {stay_text}. "
        f"Arrival transport: {arrival}. "
        f"Total estimated cost: {itinerary.total_estimated_cost} "
        f"{itinerary.currency or ''} against budget {request.budget}.\n"
        f"Plan outline: {day_lines}.\n"
        'Respond with JSON only: {"notes": ["..."]}'
    )
    try:
        result = tacc.complete(
            prompt,
            system=TRIP_PLANNING_SYSTEM_PROMPT,
            session_id=session_id,
            trace_context=trace_context,
        )
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return []
    if not result.get("ok") or result.get("stub"):
        return []
    return _parse_summary_notes(str(result.get("text") or ""))


def _constraint_changes(previous: TripRequest, current: TripRequest) -> list[str]:
    """Human-readable diff between the previous and revised trip constraints."""
    notes: list[str] = []
    if previous.budget != current.budget:
        old = "none" if previous.budget is None else str(previous.budget)
        new = "none" if current.budget is None else str(current.budget)
        notes.append(f"Revised for new budget: {new} (was {old})")
    previous_days = trip_length(previous)
    current_days = trip_length(current)
    if previous_days != current_days:
        notes.append(
            f"Revised for new trip length: {current_days} day(s) (was {previous_days})"
        )
    elif (previous.start_date, previous.end_date) != (
        current.start_date,
        current.end_date,
    ):
        notes.append("Revised for new dates")
    if sorted(item.casefold() for item in previous.interests) != sorted(
        item.casefold() for item in current.interests
    ):
        notes.append(
            "Revised interests: "
            + (", ".join(current.interests) or "none")
            + " (was "
            + (", ".join(previous.interests) or "none")
            + ")"
        )
    if previous.avoid_visited != current.avoid_visited:
        notes.append(
            "Repeat avoidance enabled" if current.avoid_visited else "Repeat avoidance disabled"
        )
    if not notes:
        notes.append("Constraints unchanged; plan re-validated")
    return notes


def revise(
    request: TripRequest, previous: Itinerary, *, session_id: str | None = None
) -> Itinerary:
    """Revise loop: re-enter the agent pipeline with updated constraints.

    Re-runs Agent 4 (travel history), Agent 1 (stays), and the coordinator node
    so the cost check and rendering apply to the new budget/dates/interests
    instead of appending ad-hoc chat text. The returned plan notes what changed.
    """
    if (
        request.destination.strip().casefold()
        != previous.request.destination.strip().casefold()
    ):
        raise ValueError(
            "Revisions keep the same destination; run a new plan to change it."
        )
    trace = start_trace(
        name="plan.revise",
        input={
            "previous": previous.request.model_dump(mode="json"),
            "request": request.model_dump(mode="json"),
        },
        session_id=session_id,
        metadata={"workflow": "revise"},
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
    itinerary.notes = _constraint_changes(previous.request, request) + list(
        itinerary.notes or []
    )
    end_trace(trace, output=itinerary.model_dump(mode="json"))
    return itinerary


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
