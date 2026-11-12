"""Smoke tests for the Baseline A vs Proposed eval harness."""

from __future__ import annotations

from eval.cases import CASES
from eval.runner import run_suite


def test_eval_cases_have_unique_ids():
    ids = [case["id"] for case in CASES]
    assert ids
    assert len(ids) == len(set(ids))


def test_history_avoidance_contrast_and_budget_cases_pass():
    report = run_suite(
        [
            "tokyo_budget_ok",
            "tokyo_history_avoid_shibuya",
            "hk_history_avoid_central",
            "transport_same_place_walk",
        ]
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

    hk = by_id["hk_history_avoid_central"]
    assert hk["history_contrast"]["pass"] is True
    assert hk["pass"]

    walk = by_id["transport_same_place_walk"]
    assert walk["variants"]["proposed"]["agent2"]["checks"]["walk_mode"] is True
    assert walk["pass"]
