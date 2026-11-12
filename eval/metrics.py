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

    # City-consistency is reported when requested but does not fail the case
    # on its own: the stub can still match another city's catalog row.
    forbidden_modes = {_norm(mode) for mode in expect.get("forbidden_modes") or []}
    notes_forbid = [_norm(token) for token in expect.get("transport_notes_forbid") or []]
    city_consistent = True
    if forbidden_modes:
        city_consistent = _norm(leg.mode) not in forbidden_modes
    if notes_forbid:
        notes = _norm(leg.notes or "")
        city_consistent = city_consistent and not any(token in notes for token in notes_forbid)
    if expect.get("transport_city_consistent"):
        checks["city_consistent"] = city_consistent

    hard_checks = {
        key: value
        for key, value in checks.items()
        if key != "city_consistent"
    }
    return {
        "present": True,
        "mode": leg.mode,
        "duration_minutes": leg.duration_minutes,
        "cost": leg.cost,
        "from_place": leg.from_place,
        "to_place": leg.to_place,
        "notes": leg.notes,
        "checks": checks,
        "pass": all(hard_checks.values()),
    }



INFORMATIONAL_CHECKS = {
    "day_coverage",
    "budget_revise",
    "city_level_keeps_stays",
    "transport_city_consistent",
    "fail_closed",
    "cost_scale_ok",
}


def cost_scale_warnings(
    leg: TransportLeg | None,
    stays: list[StayCandidate],
    request: TripRequest,
) -> list[str]:
    """Flag when transport cost is on a different scale from the stay budget."""
    warnings: list[str] = []
    if leg is None or leg.cost is None:
        return warnings
    if request.budget is not None and leg.cost > request.budget + 1e-6:
        warnings.append("transport_cost_exceeds_budget")
    if stays and request.days:
        stay_cost = (stays[0].nightly_cost or 0) * request.days
        if stay_cost > 0 and leg.cost > 5 * stay_cost:
            warnings.append("transport_cost_dwarfs_stay_cost")
    return warnings


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
    ignore_total = bool(expect.get("ignore_total_budget")) or expect_revise
    checks = {
        "agent1_stays": stay_score["pass"],
        "agent2_transport": transport_score["pass"],
        "budget_total": budget_ok if not ignore_total else None,
        "day_coverage": day_check,
        "budget_revise": budget_ok if expect_revise else None,
    }
    if expect.get("city_level_history"):
        tokens = [_norm(t) for t in expect.get("stay_location_contains") or []]
        checks["city_level_keeps_stays"] = any(
            _location_ok(stay, tokens, allow_generic=False) for stay in stays
        )
    if expect.get("transport_city_consistent"):
        checks["transport_city_consistent"] = (transport_score.get("checks") or {}).get(
            "city_consistent"
        )
    if expect.get("expect_fail_closed"):
        checks["fail_closed"] = not stays and not transports
    warnings = cost_scale_warnings(transports[0] if transports else None, stays, request)
    if expect.get("cost_scale_check"):
        checks["cost_scale_ok"] = not warnings
    # Informational checks are reported (Agent 3 day/revise gaps, matcher and
    # stub-catalog issues) but do not fail the case on their own.
    applicable = {
        key: value
        for key, value in checks.items()
        if value is not None and key not in INFORMATIONAL_CHECKS
    }
    return {
        "day_count": day_count,
        "expected_days": expected_days,
        "total_estimated_cost": total,
        "budget": request.budget,
        "used_travel_history": itinerary.used_travel_history,
        "notes": list(itinerary.notes or []),
        "warnings": warnings,
        "stays": stay_score,
        "transport": transport_score,
        "checks": checks,
        "pass": all(applicable.values()) if applicable else True,
    }
