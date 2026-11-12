"""Smoke tests for the Baseline A vs Proposed eval harness."""

from __future__ import annotations

from eval.cases import CASES
from eval.runner import run_suite
from eval.tool_cases import TOOL_CASES


def test_eval_cases_have_unique_ids():
    ids = [case["id"] for case in CASES] + [case["id"] for case in TOOL_CASES]
    assert ids
    assert len(ids) == len(set(ids))


def test_history_avoidance_contrast_and_budget_cases_pass():
    report = run_suite(
        [
            "tokyo_budget_ok",
            "tokyo_history_avoid_shibuya",
            "tokyo_history_multiple_places",
            "tokyo_history_unrelated_place",
            "hk_history_avoid_central",
            "transport_same_place_walk",
        ],
        include_tools=False,
    )
    by_id = {case["id"]: case for case in report["cases"]}

    tokyo_budget = by_id["tokyo_budget_ok"]
    assert tokyo_budget["pass"]
    assert tokyo_budget["history_contrast"] is None

    history = by_id["tokyo_history_avoid_shibuya"]
    assert history["history_contrast"]["pass"] is True
    assert history["history_contrast"]["baseline_overlap"]
    assert history["history_contrast"]["proposed_overlap"] == []
    assert history["pass"]

    multi = by_id["tokyo_history_multiple_places"]
    assert multi["history_contrast"]["pass"] is True
    assert multi["pass"]

    unrelated = by_id["tokyo_history_unrelated_place"]
    assert unrelated["history_contrast"] is None
    assert unrelated["pass"]
    proposed_stays = unrelated["variants"]["proposed"]["agent1"]["stay_locations"]
    assert any("tokyo" in loc.casefold() for loc in proposed_stays)

    hk = by_id["hk_history_avoid_central"]
    assert hk["history_contrast"]["pass"] is True
    assert hk["pass"]

    walk = by_id["transport_same_place_walk"]
    assert walk["variants"]["proposed"]["agent2"]["checks"]["walk_mode"] is True
    assert walk["pass"]


def test_gold_tool_cases_pass():
    report = run_suite(
        [
            "tool_search_stays_tokyo",
            "tool_estimate_transport_hk",
            "tool_stays_and_transport_amsterdam",
            "tool_search_stays_missing_destination",
            "tool_unknown_name",
        ],
        include_plan=False,
    )
    assert report["tool_total"] == 5
    assert report["tool_pass"] == 5
    assert all(case["pass"] for case in report["cases"])
