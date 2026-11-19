# Eval — Baseline A vs Proposed

Langfuse traces are useful for debugging, but they do not score the agents.
This folder is a fixed-case harness that runs the same requests twice:

- **Baseline A:** `ENABLE_TRAVEL_HISTORY=0` (Agents 1–3 only)
- **Proposed:** `ENABLE_TRAVEL_HISTORY=1` (Agents 1–4)

It measures per-agent constraints (stay budget/location, transport fields) and
**history avoidance**: for cases with a seeded travel history and
`avoid_visited=true`, Proposed must drop visited stays while Baseline A still
recommends at least one of them.

The runner uses stub stay/maps tools and an isolated SQLite file. Stub mode is
offline and does not call a live model endpoint. API mode sends a trip-planning
prompt to the configured OpenAI-compatible `QWEN_BASE_URL` using `QWEN_MODEL`
and `QWEN_API_KEY`, and may use the optional Nemotron judge configuration.

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

To evaluate a live model, configure `QWEN_BASE_URL` (including `/v1`) and run:

```powershell
.\.venv\Scripts\python.exe -m eval.runner --mode api
```

You can override the configured base URL with `--model-url`. API mode is
separate from the deterministic baseline/proposed tool checks; it requests
model-suggested stays and records response metrics.

Reports are written to `eval/results/` as JSON and CSV.

## Cases

See `cases.py`. They are written against the stub catalogs in
`agents/search_stays/tools.py` and `agents/estimate_transport/tools.py`.

After Agent 3, the coordinator emits **one day plan per requested day** (or
per inclusive start/end dates), packs stub POIs across those days, revises to a
cheaper stay when the total is over budget, and fail-closes when no feasible
stay fits. `expected_days`, revise, POI packing, and fail-closed are hard
checks. The report still shows `days (exp)`.

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

- Agent 3 hard checks: multi-day coverage (`expected_days`), revise-to-cheaper-stay
  (`tokyo_revise_cheaper_stay`), and fail-closed when no stay fits or revise cannot
  meet the total (`empty_catalog_tight_budget`, `hk_over_budget_transport`,
  `tokyo_airport_cost_scale`).
- POI packing: existing multi-day cases require unique POIs on every day.
  `tokyo_pois_interest_food` checks interest ranking; `tokyo_history_avoid_poi`
  checks that Proposed drops a visited POI while Baseline A still includes it.
- `tokyo_dates_span_three_days` uses inclusive start/end dates with no `days`
  field and still expects a 3-day itinerary.
