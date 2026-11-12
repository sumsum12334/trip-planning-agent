"""Run fixed cases against Baseline A (Agents 1-3) and Proposed (Agents 1-4).

Usage (from the repo root, with the project venv):

    .venv/Scripts/python.exe -m eval.runner
    .venv/Scripts/python.exe -m eval.runner --case tokyo_history_avoid_shibuya

Writes JSON + CSV under eval/results/ and prints a summary table.
The runner uses an isolated SQLite file so it does not touch your .env database.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.estimate_transport.agent import run as estimate_transport_run
from agents.search_stays.agent import run as search_stays_run
from agents.coordinator.agent import run as coordinator_run
from agents.travel_history.agent import TravelHistoryStore
from config import settings as settings_mod
from eval.cases import CASES, EvalCase
from eval.metrics import score_itinerary, score_stays, score_transport, stay_overlaps_history
from shared.schemas import TripRequest

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "eval" / "results"
VARIANTS = ("baseline_a", "proposed")


def _set_runtime(*, enable_travel_history: bool, database_url: str) -> None:
    os.environ["ENABLE_TRAVEL_HISTORY"] = "1" if enable_travel_history else "0"
    os.environ["DATABASE_URL"] = database_url
    os.environ["TOOL_STAYS_MODE"] = "stub"
    os.environ["TOOL_MAPS_MODE"] = "stub"
    os.environ["WEB_SEARCH_MODE"] = "stub"
    # Keep eval offline even if the developer has a Qwen endpoint in .env.
    os.environ["QWEN_BASE_URL"] = ""
    os.environ["QWEN_API_KEY"] = ""
    settings_mod.get_settings.cache_clear()


def _seed_history(database_url: str, user_id: str, history: list[dict[str, str]]) -> list[str]:
    if not history:
        return []
    store = TravelHistoryStore(database_url)
    for item in history:
        store.record_visit(
            user_id,
            item["location"],
            country=item.get("country"),
            city=item.get("city"),
        )
    return store.list_places(user_id)


def _first_transport_from_expect(case: EvalCase, request: TripRequest) -> tuple[str, str]:
    expect = case.get("expect") or {}
    from_place = expect.get("transport_from") or request.origin or request.destination
    to_place = expect.get("transport_to") or request.destination
    return from_place, to_place


def run_variant(
    case: EvalCase,
    *,
    variant: str,
    database_url: str,
) -> dict[str, Any]:
    enable_history = variant == "proposed"
    _set_runtime(enable_travel_history=enable_history, database_url=database_url)
    request = TripRequest.model_validate(case["request"])
    history_places = _seed_history(database_url, request.user_id or "eval-user", case.get("history") or [])

    started = time.perf_counter()
    error = None
    itinerary = None
    try:
        itinerary = coordinator_run(request, session_id=f"eval-{case['id']}-{variant}")
    except Exception as exc:  # pragma: no cover - surfaced in the report
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    excluded = history_places if (request.avoid_visited and enable_history) else []
    stays = search_stays_run(request, excluded_locations=excluded)
    from_place, to_place = _first_transport_from_expect(case, request)
    transport = estimate_transport_run(request, from_place, to_place)

    expect = case.get("expect") or {}
    apply_filter = bool(expect.get("history_avoidance")) and enable_history and request.avoid_visited
    agent1 = score_stays(
        stays,
        request,
        expect,
        history_places,
        apply_history_filter=apply_filter,
    )
    agent2 = score_transport(transport, expect)
    plan = None
    if itinerary is not None:
        plan = score_itinerary(
            itinerary,
            request,
            expect,
            history_places,
            apply_history_filter=apply_filter,
        )

    passed = error is None and agent1["pass"] and agent2["pass"] and (plan["pass"] if plan else False)
    return {
        "variant": variant,
        "enable_travel_history": enable_history,
        "elapsed_ms": elapsed_ms,
        "error": error,
        "history_places": history_places,
        "agent1": agent1,
        "agent2": agent2,
        "plan": plan,
        "pass": passed,
    }


def _history_contrast(case: EvalCase, results: dict[str, Any]) -> dict[str, Any] | None:
    if not (case.get("expect") or {}).get("history_avoidance"):
        return None
    request = TripRequest.model_validate(case["request"])
    if not request.avoid_visited:
        return None
    baseline_stays = (results["baseline_a"].get("plan") or {}).get("stays") or results["baseline_a"]["agent1"]
    proposed_stays = (results["proposed"].get("plan") or {}).get("stays") or results["proposed"]["agent1"]
    history = results["proposed"].get("history_places") or []
    baseline_overlap = baseline_stays.get("overlapping_history") or []
    proposed_overlap = proposed_stays.get("overlapping_history") or []
    # Fallback: if plan stays were empty lists after filtering, also inspect agent1.
    if not baseline_overlap:
        baseline_overlap = results["baseline_a"]["agent1"].get("overlapping_history") or []
    if not proposed_overlap:
        proposed_overlap = results["proposed"]["agent1"].get("overlapping_history") or []
    passed = bool(history) and bool(baseline_overlap) and not proposed_overlap
    return {
        "history_places": history,
        "baseline_overlap": baseline_overlap,
        "proposed_overlap": proposed_overlap,
        "pass": passed,
        "detail": (
            "Proposed avoided visited stays while Baseline A still recommended them"
            if passed
            else "Expected Baseline A to still recommend a visited stay, and Proposed to avoid all of them"
        ),
    }


def run_case(case: EvalCase, database_url: str) -> dict[str, Any]:
    variants = {name: run_variant(case, variant=name, database_url=database_url) for name in VARIANTS}
    contrast = _history_contrast(case, variants)
    passed = all(variants[name]["pass"] for name in VARIANTS)
    if contrast is not None:
        passed = passed and contrast["pass"]
    return {
        "id": case["id"],
        "description": case.get("description"),
        "request": case["request"],
        "variants": variants,
        "history_contrast": contrast,
        "pass": passed,
    }


def run_suite(case_ids: list[str] | None = None) -> dict[str, Any]:
    selected = [case for case in CASES if not case_ids or case["id"] in case_ids]
    missing = [cid for cid in (case_ids or []) if cid not in {c["id"] for c in CASES}]
    if missing:
        raise SystemExit(f"Unknown case id(s): {', '.join(missing)}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="trip-eval-") as tmp:
        database_url = "sqlite:///" + str(Path(tmp) / "travel_history.sqlite")
        started = time.perf_counter()
        cases = [run_case(case, database_url) for case in selected]
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    passed = sum(1 for case in cases if case["pass"])
    contrast_cases = [case for case in cases if case.get("history_contrast") is not None]
    report = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "case_count": len(cases),
        "passed": passed,
        "failed": len(cases) - passed,
        "elapsed_ms": elapsed_ms,
        "history_contrast_pass": sum(1 for case in contrast_cases if case["history_contrast"]["pass"]),
        "history_contrast_total": len(contrast_cases),
        "cases": cases,
    }
    return report


def _write_outputs(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"eval-{stamp}.json"
    csv_path = out_dir / f"eval-{stamp}.csv"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rows: list[dict[str, Any]] = []
    for case in report["cases"]:
        contrast = case.get("history_contrast") or {}
        for name in VARIANTS:
            variant = case["variants"][name]
            plan = variant.get("plan") or {}
            stays = (plan.get("stays") or variant.get("agent1") or {})
            transport = (plan.get("transport") or variant.get("agent2") or {})
            rows.append(
                {
                    "case_id": case["id"],
                    "variant": name,
                    "pass": variant["pass"],
                    "elapsed_ms": variant["elapsed_ms"],
                    "error": variant.get("error") or "",
                    "agent1_pass": (variant.get("agent1") or {}).get("pass"),
                    "agent2_pass": (variant.get("agent2") or {}).get("pass"),
                    "plan_pass": plan.get("pass"),
                    "day_count": plan.get("day_count"),
                    "expected_days": plan.get("expected_days"),
                    "total_estimated_cost": plan.get("total_estimated_cost"),
                    "budget": plan.get("budget"),
                    "stay_names": "; ".join(stays.get("stay_names") or []),
                    "transport_mode": transport.get("mode"),
                    "history_contrast_pass": contrast.get("pass", ""),
                }
            )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["case_id"])
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path


def _fmt_bool(value: Any) -> str:
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    return "-"


def print_summary(report: dict[str, Any], json_path: Path, csv_path: Path) -> None:
    print(
        f"Eval {report['passed']}/{report['case_count']} cases passed "
        f"({report['elapsed_ms']} ms). "
        f"History contrast {report['history_contrast_pass']}/{report['history_contrast_total']}."
    )
    print(
        f"{'case':<34} {'baseline':<10} {'proposed':<10} {'days (exp)':<12} {'contrast':<10}"
    )
    print("-" * 80)
    for case in report["cases"]:
        baseline = case["variants"]["baseline_a"]
        proposed = case["variants"]["proposed"]
        plan = proposed.get("plan") or {}
        days = plan.get("day_count")
        expected = plan.get("expected_days")
        contrast = case.get("history_contrast")
        print(
            f"{case['id']:<34} "
            f"{_fmt_bool(baseline['pass']):<10} "
            f"{_fmt_bool(proposed['pass']):<10} "
            f"{str(days) + '/' + str(expected):<12} "
            f"{_fmt_bool(contrast['pass'] if contrast else None):<10}"
        )
        if not case["pass"]:
            reasons = []
            if baseline.get("error"):
                reasons.append(f"baseline error: {baseline['error']}")
            if proposed.get("error"):
                reasons.append(f"proposed error: {proposed['error']}")
            for name in VARIANTS:
                plan = case["variants"][name].get("plan") or {}
                checks = plan.get("checks") or {}
                failed = [key for key, ok in checks.items() if ok is False]
                if failed:
                    reasons.append(f"{name}: {', '.join(failed)}")
            if contrast and not contrast["pass"]:
                reasons.append(contrast["detail"])
            if reasons:
                print("    " + " | ".join(reasons))
    print()
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Baseline A vs Proposed eval cases.")
    parser.add_argument("--case", action="append", dest="cases", help="Case id to run (repeatable).")
    parser.add_argument(
        "--out",
        default=str(RESULTS_DIR),
        help="Directory for JSON/CSV reports (default: eval/results).",
    )
    args = parser.parse_args(argv)
    report = run_suite(args.cases)
    json_path, csv_path = _write_outputs(report, Path(args.out))
    print_summary(report, json_path, csv_path)
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
