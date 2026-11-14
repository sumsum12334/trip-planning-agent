# Agent 3 — Coordinator
Task distribute, cost check, render, revise; POI for MVP. Calls TACC via `tacc_client`.

The coordinator emits **one `DayPlan` per requested day** (from `days`, or inclusive
start/end dates). Day 1 includes the arrival transport; each day lists the chosen stay
and charges one night, so the stay total is `nightly_cost * days`.

The coordinator also packs unique stub POIs across those days, preferring interest matches and skipping places already in travel history when `avoid_visited` is on.
