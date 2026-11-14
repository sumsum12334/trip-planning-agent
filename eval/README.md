# Eval — Baseline A vs Proposed

Langfuse traces are useful for debugging, but they do not score the agents.
This folder is a fixed-case harness that runs the same requests twice:

- **Baseline A:** `ENABLE_TRAVEL_HISTORY=0` (Agents 1–3 only)
- **Proposed:** `ENABLE_TRAVEL_HISTORY=1` (Agents 1–4)

It measures per-agent constraints (stay budget/location, transport fields) and
**history avoidance**: for cases with a seeded travel history and
`avoid_visited=true`, Proposed must drop visited stays while Baseline A still
recommends at least one of them.

The runner always uses stub stay/maps tools and an isolated SQLite file. It
does not call your `.env` database or a live model endpoint.

## Run

From the repository root:

```powershell
cd C:\dev\trip-planning-agent
.\.venv\Scripts\python.exe -m eval.runner
```

One case only:

```powershell
.\.venv\Scripts\python.exe -m eval.runner --case tokyo_history_avoid_shibuya
```

Reports are written to `eval/results/` as JSON and CSV.

## Cases

See `cases.py`. They are written against the stub catalogs in
`agents/search_stays/tools.py` and `agents/estimate_transport/tools.py`.

The coordinator currently emits a **single day** even when the request asks
for more. The report still shows `days (exp)` so that gap is visible; it does
not fail the case on its own.

## Add a case

Append a dict to `CASES` in `cases.py` with:

- `request`: fields for `TripRequest` (`destination`, `days`, `budget`, …)
- `history`: optional visited places to seed for that `user_id`
- `expect`: `min_stays`, `stay_location_contains`, `nightly_cost_within_budget`,
  `transport_required`, `expected_days`, `history_avoidance`


## Added coverage

- More history cases: multiple visited places, and an unrelated-history control
  (Tokyo trip should not drop stays just because Hong Kong was visited).
- Over-budget transport (`hk_over_budget_transport`): records whether the
  coordinator revises an itinerary that exceeds the total budget. This is a
  **known Agent 3 gap** today (no revise loop) and does not fail the suite alone.
- Gold tool-call cases (`eval/tool_cases.py`): execute the chat tool layer with
  the arguments a model should pass. Run with the default suite, or:

  ```powershell
  .\.venv\Scripts\python.exe -m eval.runner --tools-only
  ```

  This is **not** live model routing accuracy; that still needs a configured
  Qwen / TACC endpoint.

- History alias / case folding (`tokyo_history_alias_shibuya`): a lowercase
  `shibuya` seed should still be avoided by Proposed.
- City-level history (`tokyo_history_city_too_broad`): a visit recorded only as
  `Tokyo` must not drop every Tokyo stay. Matching now requires a more specific
  place phrase or token, not a city-only word prefix of the stay location.
- Cross-city transport (`paris_airport_not_hk_catalog`): Paris Charles de Gaulle
  must not reuse the Hong Kong Airport Express row. Generic tokens such as
  `airport` no longer score a catalog hit on their own, so this case must stay
  city-consistent.
- Invalid requests: `invalid_days_zero` and `empty_destination_fail_closed`
  must fail closed at validation (empty destination no longer returns generic stays).
- Cost-scale warning (`tokyo_airport_cost_scale`): Narita train cost 3200 vs a
  400 stay budget is flagged, but does not fail the case.
- Determinism is checked in `tests/test_eval_runner.py` (same stub case twice).
