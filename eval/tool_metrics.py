"""Scoring for gold chat-tool executions."""

from __future__ import annotations

from typing import Any

from agents.chat_tools import execute_agent_tool


def score_tool_calls(gold_calls: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    all_pass = True
    for gold in gold_calls:
        name = gold["name"]
        arguments = gold.get("arguments") or {}
        expect_error = bool(gold.get("expect_error"))
        error = None
        payload = None
        try:
            payload = execute_agent_tool(name, arguments)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        checks: dict[str, bool] = {}
        if expect_error:
            checks["raised_error"] = error is not None
        else:
            checks["no_error"] = error is None
            if gold.get("min_stays") is not None:
                stays = (payload or {}).get("stays") if isinstance(payload, dict) else None
                checks["min_stays"] = isinstance(stays, list) and len(stays) >= int(gold["min_stays"])
            if gold.get("require_transport_fields"):
                checks["transport_fields"] = isinstance(payload, dict) and all(
                    payload.get(key) is not None
                    for key in ("mode", "duration_minutes", "cost")
                ) and payload.get("mode") != "unknown"
        passed = all(checks.values()) if checks else False
        all_pass = all_pass and passed
        results.append(
            {
                "name": name,
                "arguments": arguments,
                "expect_error": expect_error,
                "error": error,
                "result_preview": _preview(payload),
                "checks": checks,
                "pass": passed,
            }
        )
    return {"calls": results, "pass": all_pass and bool(results)}


def _preview(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    if "stays" in payload:
        return {
            "mode": payload.get("mode"),
            "stay_count": len(payload.get("stays") or []),
            "stay_names": [row.get("name") for row in (payload.get("stays") or [])][:5],
        }
    keep = {key: payload.get(key) for key in ("from_place", "to_place", "mode", "duration_minutes", "cost", "error") if key in payload}
    return keep
