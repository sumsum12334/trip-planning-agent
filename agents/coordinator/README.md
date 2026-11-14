# Agent 3 — Coordinator
Task distribute, cost check, render, revise; POI for MVP. Calls TACC via `tacc_client`.

The coordinator emits **one `DayPlan` per requested day** (from `days`, or inclusive
start/end dates). Day 1 includes the arrival transport; each day lists the chosen stay
and charges one night, so the stay total is `nightly_cost * days`.

The coordinator also packs unique stub POIs across those days, preferring interest matches and skipping places already in travel history when `avoid_visited` is on.

If the first plan exceeds the total budget, the coordinator revises by stepping down to a cheaper stay that still fits, and records that change in `notes`. If no stay can meet the budget, it notes that revise could not meet budget.

If no stay is feasible, or the plan is still over budget after revise, the coordinator fail-closes with `NoFeasiblePlanError` (HTTP 422 on `/plan`) instead of returning a silent overspend.

