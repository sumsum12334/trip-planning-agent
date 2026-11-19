"""Smoke tests for the Baseline A vs Proposed eval harness."""

from __future__ import annotations

from config import settings as settings_mod
from eval.cases import CASES
from eval import runner as runner_mod
from eval.runner import run_suite
from eval.tool_cases import TOOL_CASES


def test_model_call_uses_configured_qwen_model_and_api_key(monkeypatch):
    request: dict = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return iter(
                [
                    'data: {"choices":[{"delta":{"content":"Hotel suggestion"}}]}',
                    "data: [DONE]",
                ]
            )

    def fake_stream(method, url, **kwargs):
        request.update(method=method, url=url, **kwargs)
        return FakeResponse()

    with monkeypatch.context() as patch:
        patch.setenv("QWEN_MODEL", "configured-model")
        patch.setenv("QWEN_API_KEY", "test-key")
        patch.setattr(runner_mod.httpx, "stream", fake_stream)
        settings_mod.get_settings.cache_clear()
        try:
            text, metrics = runner_mod._call_model_stream(
                "Plan a trip",
                "https://model.example/v1",
                "eval-user",
            )
        finally:
            settings_mod.get_settings.cache_clear()
    settings_mod.get_settings.cache_clear()

    assert text == "Hotel suggestion"
    assert request["json"]["model"] == "configured-model"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert metrics["token_count"] == 2


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

def test_alias_history_and_validation_cases():
    report = run_suite(
        [
            "tokyo_history_alias_shibuya",
            "tokyo_history_city_too_broad",
            "paris_airport_not_hk_catalog",
            "empty_destination_fail_closed",
            "invalid_days_zero",
            "tokyo_airport_cost_scale",
        ],
        include_tools=False,
    )
    by_id = {case["id"]: case for case in report["cases"]}
    assert all(case["pass"] for case in report["cases"])

    alias = by_id["tokyo_history_alias_shibuya"]
    assert alias["history_contrast"]["pass"] is True
    assert alias["history_contrast"]["proposed_overlap"] == []

    broad = by_id["tokyo_history_city_too_broad"]
    assert broad["history_contrast"] is None
    assert broad["variants"]["baseline_a"]["agent1"]["stay_count"] >= 1
    assert broad["variants"]["proposed"]["agent1"]["stay_count"] >= 1
    proposed_plan = broad["variants"]["proposed"]["plan"] or {}
    assert proposed_plan["checks"]["city_level_keeps_stays"] is True
    proposed_stays = broad["variants"]["proposed"]["agent1"]["stay_locations"]
    assert any("tokyo" in loc.casefold() for loc in proposed_stays)

    paris = by_id["paris_airport_not_hk_catalog"]
    assert paris["variants"]["proposed"]["agent2"]["mode"] != "airport_express"
    assert "hong kong" not in (paris["variants"]["proposed"]["agent2"].get("notes") or "").casefold()
    assert paris["variants"]["proposed"]["agent2"]["checks"]["city_consistent"] is True

    empty = by_id["empty_destination_fail_closed"]
    assert empty["variants"]["proposed"]["error"]
    assert empty["variants"]["proposed"]["plan"]["checks"]["expect_error"] is True
    assert empty["variants"]["proposed"]["plan"]["checks"]["fail_closed"] is True

    days0 = by_id["invalid_days_zero"]
    assert days0["variants"]["proposed"]["error"]
    assert days0["variants"]["proposed"]["plan"]["checks"]["expect_error"] is True

    scale = by_id["tokyo_airport_cost_scale"]
    assert scale["variants"]["proposed"]["error"]
    assert "NoFeasiblePlanError" in scale["variants"]["proposed"]["error"]
    assert scale["variants"]["proposed"]["plan"]["checks"]["expect_error"] is True
    assert scale["variants"]["proposed"]["plan"]["checks"]["fail_closed"] is True


def test_stub_plan_is_deterministic():
    first = run_suite(["tokyo_budget_ok"], include_tools=False)
    second = run_suite(["tokyo_budget_ok"], include_tools=False)

    def _sig(report):
        case = report["cases"][0]
        rows = []
        for name in ("baseline_a", "proposed"):
            variant = case["variants"][name]
            rows.append(
                (
                    name,
                    variant["agent1"].get("stay_names"),
                    variant["agent2"].get("mode"),
                    variant["agent2"].get("cost"),
                    variant["agent2"].get("duration_minutes"),
                )
            )
        return rows

    assert _sig(first) == _sig(second)

def test_agent3_day_revise_and_poi_cases():
    report = run_suite(
        [
            "tokyo_budget_ok",
            "empty_catalog_tight_budget",
            "hk_over_budget_transport",
            "tokyo_revise_cheaper_stay",
            "tokyo_pois_interest_food",
            "tokyo_history_avoid_poi",
            "tokyo_dates_span_three_days",
        ],
        include_tools=False,
    )
    by_id = {case["id"]: case for case in report["cases"]}
    assert all(case["pass"] for case in report["cases"])

    days = by_id["tokyo_budget_ok"]
    proposed = days["variants"]["proposed"]["plan"]
    assert proposed["day_count"] == 4
    assert proposed["checks"]["day_coverage"] is True
    assert proposed["checks"]["pois_per_day"] is True
    assert proposed["checks"]["unique_pois"] is True
    assert len(proposed["pois"]) >= 8

    empty = by_id["empty_catalog_tight_budget"]
    assert "NoFeasiblePlanError" in empty["variants"]["proposed"]["error"]
    assert empty["variants"]["proposed"]["plan"]["checks"]["fail_closed"] is True

    overrun = by_id["hk_over_budget_transport"]
    assert "NoFeasiblePlanError" in overrun["variants"]["proposed"]["error"]
    assert "still exceeds budget after revise" in overrun["variants"]["proposed"]["error"]

    revise = by_id["tokyo_revise_cheaper_stay"]
    plan = revise["variants"]["proposed"]["plan"]
    assert plan["checks"]["budget_revise"] is True
    assert plan["checks"]["revise_noted"] is True
    assert plan["total_estimated_cost"] <= 400
    assert plan["day_count"] == 3
    stays = plan["stays"]["stay_names"]
    assert "Shinjuku Business Hotel" in stays
    assert any("Revised stay from Asakusa Traditional Ryokan" in note for note in plan["notes"])

    food = by_id["tokyo_pois_interest_food"]
    food_plan = food["variants"]["proposed"]["plan"]
    assert food_plan["day_count"] == 1
    assert food_plan["pois"][0] in {"Tsukiji Outer Market", "Ichiran Shibuya"}
    assert food_plan["checks"]["interest_ranked_pois"] is True

    poi = by_id["tokyo_history_avoid_poi"]
    assert poi["poi_contrast"]["pass"] is True
    assert poi["poi_contrast"]["baseline_overlap"]
    assert poi["poi_contrast"]["proposed_overlap"] == []
    assert all(
        "shibuya crossing" not in name.casefold()
        for name in poi["variants"]["proposed"]["plan"]["pois"]
    )

    dates = by_id["tokyo_dates_span_three_days"]
    dates_plan = dates["variants"]["proposed"]["plan"]
    assert dates_plan["day_count"] == 3
    assert dates_plan["checks"]["day_coverage"] is True
    assert dates_plan["checks"]["pois_per_day"] is True

