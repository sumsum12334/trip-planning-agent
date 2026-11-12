"""Constraint checks for one itinerary / agent output."""

from __future__ import annotations

from typing import Any

from agents.search_stays.tools import nightly_budget_cap
from shared.schemas import Itinerary, StayCandidate, TransportLeg, TripRequest


def _norm(value: str) -> str:
    return value.casefold().strip()


def stay_overlaps_history(stay: StayCandidate, history_places: list[str]) -> bool:
    """True if stay name or location overlaps a visited place (same rule as Agent 1)."""
    excluded = [_norm(place) for place in history_places if place and place.strip()]
    if not excluded:
        return False
    name = _norm(stay.name)
    location = _norm(stay.location)
    return any(place in name or place in location for place in excluded)


def _location_ok(stay: StayCandidate, tokens: list[str], allow_generic: bool) -> bool:
    loc = _norm(stay.location)
    if tokens and any(token in loc for token in tokens):
        return True
    return allow_generic and "generic" in loc


def score_stays(
    stays: list[StayCandidate],
    request: TripRequest,
    expect: dict[str, Any],
    history_places: list[str],
    *,
    apply_history_filter: bool,
) -> dict[str, Any]:
    min_stays = int(expect.get("min_stays") or 0)
    tokens = [_norm(t) for t in expect.get("stay_location_contains") or []]
    allow_generic = bool(expect.get("allow_generic_fallback"))
    check_budget = bool(expect.get("nightly_cost_within_budget"))
    check_avoid = bool(expect.get("history_avoidance")) and apply_history_filter
    cap = nightly_budget_cap(request.budget, request.days)

    overlapping = [stay.name for stay in stays if stay_overlaps_history(stay, history_places)]
    budget_violations = []
    if check_budget and cap is not None:
        budget_violations = [
            stay.name
            for stay in stays
            if stay.nightly_cost is not None and stay.nightly_cost > cap
        ]
    location_violations = [
        stay.location
        for stay in stays
        if tokens and not _location_ok(stay, tokens, allow_generic)
    ]

    checks = {
        "has_min_stays": len(stays) >= min_stays,
        "within_nightly_budget": not budget_violations,
        "location_match": not location_violations,
        "avoids_visited": not overlapping if check_avoid else None,
        "no_false_history_exclusion": (
            not overlapping if expect.get("no_false_history_exclusion") else None
        ),
    }
    applicable = {k: v for k, v in checks.items() if v is not None}
    return {
        "stay_count": len(stays),
        "stay_names": [stay.name for stay in stays],
        "stay_locations": [stay.location for stay in stays],
        "nightly_cap": cap,
        "overlapping_history": overlapping,
        "budget_violations": budget_violations,
        "location_violations": location_violations,
        "checks": checks,
        "pass": all(applicable.values()) if applicable else True,
    }


def score_transport(leg: TransportLeg | None, expect: dict[str, Any]) -> dict[str, Any]:
    required = bool(expect.get("transport_required"))
    same_place = bool(expect.get("transport_same_place"))
    if not required and leg is None:
        return {"present": False, "checks": {}, "pass": True}
    if leg is None:
        return {"present": False, "checks": {"present": False}, "pass": False}

    checks = {
        "present": True,
        "known_mode": bool(leg.mode) and leg.mode != "unknown",
        "non_negative_duration": leg.duration_minutes is not None and leg.duration_minutes >= 0,
        "non_negative_cost": leg.cost is not None and leg.cost >= 0,
    }
    if same_place:
        checks["walk_mode"] = _norm(leg.mode) == "walk"
        checks["zero_cost"] = (leg.cost or 0) == 0
    return {
        "present": True,
        "mode": leg.mode,
        "duration_minutes": leg.duration_minutes,
        "cost": leg.cost,
        "from_place": leg.from_place,
        "to_place": leg.to_place,
        "notes": leg.notes,
        "checks": checks,
        "pass": all(checks.values()),
    }


def score_itinerary(
    itinerary: Itinerary,
    request: TripRequest,
    expect: dict[str, Any],
    history_places: list[str],
    *,
    apply_history_filter: bool,
) -> dict[str, Any]:
    stays: list[StayCandidate] = []
    transports: list[TransportLeg] = []
    for day in itinerary.days:
        stays.extend(day.stays)
        transports.extend(day.transports)

    stay_score = score_stays(
        stays,
        request,
        expect,
        history_places,
        apply_history_filter=apply_history_filter,
    )
    transport_score = score_transport(transports[0] if transports else None, expect)

    expected_days = expect.get("expected_days")
    day_count = len(itinerary.days)
    day_check = day_count == expected_days if expected_days else None

    total = itinerary.total_estimated_cost
    budget_ok = True
    if request.budget is not None and total is not None:
        budget_ok = total <= request.budget + 1e-6

    expect_revise = bool(expect.get("expect_revise"))
    checks = {
        "agent1_stays": stay_score["pass"],
        "agent2_transport": transport_score["pass"],
        "budget_total": budget_ok if not expect_revise else None,
        "day_coverage": day_check,
        "budget_revise": budget_ok if expect_revise else None,
    }
    # Day coverage and budget_revise are reported (Agent 3 currently emits one
    # day and has no revise loop) but do not fail the case on their own.
    applicable = {
        key: value
        for key, value in checks.items()
        if value is not None and key not in {"day_coverage", "budget_revise"}
    }
    return {
        "day_count": day_count,
        "expected_days": expected_days,
        "total_estimated_cost": total,
        "budget": request.budget,
        "used_travel_history": itinerary.used_travel_history,
        "notes": list(itinerary.notes or []),
        "stays": stay_score,
        "transport": transport_score,
        "checks": checks,
        "pass": all(applicable.values()) if applicable else True,
    }
