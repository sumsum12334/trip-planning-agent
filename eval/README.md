# Artifact Evaluation README — Trip-Planning Agent

This artifact accompanies the trip-planning-agent project: a FastAPI backend
with a React/Vite browser UI, LangGraph-based multi-agent orchestration, SQLite
conversation/travel-history persistence, and a fixed-case evaluation harness
(`eval/`) that compares **Baseline A** (Agents 1–3) against **Proposed**
(Agents 1–4, including Travel History).

The artifact is intended to be **installed on a server and accessed through a
stable URL**, as expected for artifact evaluation. Reviewers should be able to
reach the running backend and frontend over the network without local setup.

This README has two sections:

1. **Getting Started Instructions** — kick-the-tires check (~30 minutes).
2. **Detailed Instructions** — full evaluation of the artifact.

## Artifact claims (concrete)

- **Backend:** FastAPI app at `backend/main.py`, serving REST + streaming chat.
  Runs on a server reachable at a stable URL (default `http://127.0.0.1:8000`
  locally; bind to `0.0.0.0` for external access). Health endpoint:
  `GET /health`.
- **Frontend:** Vite dev server at `http://127.0.0.1:5173` locally (bind to
  `0.0.0.0` for external access), proxying `/api/` to the backend.
- **Model:** Configured via `QWEN_BASE_URL`, `QWEN_MODEL`, `QWEN_API_KEY`.
  Currently set to the NVIDIA-compatible endpoint
  `https://integrate.api.nvidia.com/v1` with model
  `nvidia/nemotron-3.5-super-vl-120b-a12b` and a live NVIDIA API key. The
  backend's `TACCClient` falls back to a labeled local stub when the model is
  unconfigured; stub outputs are explicitly marked `[Model stub]`.
- **Evaluation:** `eval/runner.py` runs fixed cases in **stub mode**
  (offline, deterministic stub stay/maps/tools catalogs) and **API mode**
  (live model calls). Cases compare Baseline A vs Proposed on stay budget,
  location, transport fields, day coverage, revise behavior, POI packing,
  fail-closed validation, and history avoidance (visited stays/POIs dropped by
  Proposed but kept by Baseline A). An optional **LLM-as-a-Judge** scores model
  responses on relevance/completeness/helpfulness/accuracy (1–5) using the
  Nemotron judge (`NEMOTRON_API_KEY`) or the model under test itself.
- **Reproducibility:** Stub-mode runs are deterministic
  (`tests/test_eval_runner.py::test_stub_plan_is_deterministic`); each suite
  run uses an isolated temp SQLite database and writes timestamped JSON + CSV
  reports to `eval/results/eval-YYYYMMDD-HHMMSS.{json,csv}`.
- **Maturity:** Stub mode is offline-safe and deterministic. API mode requires
  network access to the model endpoint and may produce non-deterministic model
  output; archived JSON/CSV reports pin a specific run's results. The Nemotron
  judge is disabled unless `NEMOTRON_API_KEY` is set.

**No malicious or destructive operations.** The artifact only reads/writes a
local SQLite file, calls the configured model endpoint over HTTPS, and serves
HTTP locally. No data is exfiltrated, no system commands are executed, and no
tracking or analytics are embedded.

---

# 1. Getting Started Instructions

Goal: verify the artifact is functional within ~30 minutes (kick-the-tires).
These steps use **stub mode** (offline, no model API key required). The artifact
is expected to be installed on a server and accessed through a stable URL.

### Prerequisites

- Python 3.11+ with `uvicorn`, `fastapi`, `httpx`, `pydantic-settings`,
  `langgraph`, `psycopg` (optional, for Postgres history).
- Node.js + npm (for the frontend).
- Repository: `/home/mkchan/CSIT6000V/trip-planning-agent` (referred to as
  `<ROOT>` below).
- A server with network access and a stable URL reachable by reviewers.

### 1.1 Install and start the backend on the server

```bash
cd <ROOT>
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Bind to `0.0.0.0` so the backend is reachable from outside the server. Verify
from any machine with network access:

```bash
curl -s http://<SERVER-URL>:8000/health | python3 -m json.tool
```

Expected: `"ok": true`, `"tacc_configured": true` (when `QWEN_BASE_URL` is set).

The stable URL reference for the backend is:
`http://<SERVER-URL>:8000/`

### 1.2 Install and start the frontend on the server

```bash
cd <ROOT>
export PATH="$HOME/.local/nodejs/bin:$PATH"
npm run dev -- --host 0.0.0.0   # or: npx vite --host 0.0.0.0
```

Bind to `0.0.0.0` so the frontend is reachable externally. Open:

```
http://<SERVER-URL>:5173
```

The UI should load. Because the backend is running, `/api/` proxy requests will
no longer fail with `ECONNREFUSED 127.0.0.1:8000`.

### 1.3 Run a quick smoke chat through the server URL

```bash
python3 -c "
import json, urllib.request
payload = {'message': 'Plan a 2-day trip to Tokyo', 'conversation_id': 'smoke-1'}
data = json.dumps(payload).encode()
req = urllib.request.Request(
    'http://<SERVER-URL>:8000/api/chat/stream',
    data=data,
    headers={'Content-Type':'application/json','Accept':'text/event-stream'},
)
with urllib.request.urlopen(req, timeout=60) as r:
    for line in r:
        print(line.decode('utf-8','replace')[:300])
"
```

Expected: streaming `content`/`model` events ending with a `done` event;
`stub: false` if the model endpoint is reachable from the server, otherwise a
labeled `[Model stub]` message.

### 1.4 Run the deterministic eval suite on the server (stub mode)

```bash
cd <ROOT>
python -m eval.runner
```

Expected output: a summary table like `Eval [STUB] N/M cases passed`, followed
by `Wrote eval/results/eval-<timestamp>.json` and `.csv`. All stub cases should
pass. Exit code 0 means full success.

### 1.5 (Optional) Run a single case

```bash
cd <ROOT>
python -m eval.runner --case tokyo_history_avoid_shibuya
```

---

# 2. Detailed Instructions

Full evaluation of the artifact: server deployment, deterministic constraint
checks, API-mode live model evaluation, LLM-as-a-Judge scoring, and
reproducibility/archive workflow.

## 2.1 Server deployment and URL reference

The artifact is evaluated through a stable URL on a server:

| Component | Local default | Server URL pattern |
|---|---|---|
| Backend (FastAPI) | `http://127.0.0.1:8000` | `http://<SERVER-URL>:8000/` |
| Backend health | `GET /health` | `http://<SERVER-URL>:8000/health` |
| Chat stream | `POST /api/chat/stream` | `http://<SERVER-URL>:8000/api/chat/stream` |
| Frontend (Vite) | `http://127.0.0.1:5173` | `http://<SERVER-URL>:5173` |

Bind both services to `0.0.0.0` (not `127.0.0.1`) so reviewers can reach them
through the server's stable URL. Keep both processes running for the duration
of the evaluation.

If the URL is access-protected, provide the required credentials in the artifact
submission so reviewers can reach it.

## 2.2 Repository layout (relevant parts)

```
<ROOT>/
  backend/main.py           # FastAPI app + streaming chat + trip-plan tools
  agents/                   # LangGraph agents (coordinator, search_stays,
                            #   estimate_transport, travel_history, weather,
                            #   web_search, local_events)
  config/settings.py        # Pydantic settings from .env
  shared/trip_plan.py       # Trip-plan tools (start_trip_plan, set_trip_day,
                            #   set_trip_budget, set_trip_references,
                            #   remove_trip_day, get_trip_plan)
  shared/prompts.py         # System prompts (Qwen-only contract)
  shared/schemas.py         # Pydantic request/response schemas
  trip_planning_agent/tacc_client.py   # OpenAI-compatible model client (TACC)
  trip_planning_agent/conversation_store.py  # SQLite conversation persistence
  eval/cases.py             # Fixed eval cases (CASES, REVISE_CASES)
  eval/metrics.py           # Constraint checks (stays, transport, itinerary)
  eval/runner.py            # Evaluation harness: stub & API modes, LLM judge
  eval/tool_cases.py        # Gold chat-tool executions
  eval/tool_metrics.py      # Gold tool-call scoring
  eval/results/             # Timestamped JSON + CSV reports
  tests/                    # pytest suite (incl. test_eval_runner.py)
  .env                      # Runtime configuration (QWEN_*, NEMOTRON_*, etc.)
```

## 2.3 Configuration (`.env`)

Key variables (see `.env` for the full list):

| Variable | Purpose | Current value |
|---|---|---|
| `QWEN_BASE_URL` | Model endpoint base (must include `/v1`) | `https://integrate.api.nvidia.com/v1` |
| `QWEN_MODEL` | Model under test | `nvidia/nemotron-3.5-super-vl-120b-a12b` |
| `QWEN_API_KEY` | Bearer token for the model endpoint | (set) |
| `NEMOTRON_API_URL` | Nemotron judge endpoint | `https://integrate.api.nvidia.com/v1/chat/completions` |
| `NEMOTRON_API_KEY` | Nemotron judge key (enables LLM-as-a-Judge) | **empty → judge disabled** |
| `ENABLE_TRAVEL_HISTORY` | 1 = Proposed (Agents 1–4), 0 = Baseline A (Agents 1–3) | `1` |
| `TOOL_STAYS_MODE` / `TOOL_MAPS_MODE` | `stub` (offline) | `stub` |
| `DATABASE_URL` | Travel-history store | SQLite (default) or Postgres |
| `MODEL_MAX_TOKENS` / `MODEL_TEMPERATURE` / `MODEL_TOP_P` | Sampling defaults | 2048 / 1.0 / 0.95 |

To switch models, edit `.env` and restart the backend. The Qwen-only contract
(`QWEN_BASE_URL`, `QWEN_MODEL`, `QWEN_API_KEY`) is preserved; `shared/prompts.py`
holds the system prompts used across chat and agents.

## 2.4 Evaluation modes

### Stub mode (default, offline, deterministic)

```bash
cd <ROOT>
python -m eval.runner
```

- Uses stub stay/maps/web-search/weather tools; no live model calls.
- Runs every `CASES`, `REVISE_CASES`, and `TOOL_CASES` in both Baseline A and
  Proposed variants.
- Deterministic: repeated runs of the same case yield identical stay names,
  transport mode/cost/duration.
- Each run writes `eval/results/eval-<timestamp>.json` and `.csv`.

Single case:
```bash
python -m eval.runner --case tokyo_history_avoid_shibuya
```
Tools only:
```bash
python -m eval.runner --tools-only
```
Plan only:
```bash
python -m eval.runner --plan-only
```

### API mode (live model, requires network + `QWEN_BASE_URL`)

```bash
cd <ROOT>
python -m eval.runner --mode api \
  --model-url https://integrate.api.nvidia.com/v1/chat/completions
```

- Sends a trip-planning prompt to the configured model and records
  `ttft_ms`, `total_time_ms`, `token_count`, `tps`, `tpot_ms`.
- Extracts hotel/stay mentions from the response text and scores them.
- **LLM-as-a-Judge:** scores the model response on relevance, completeness,
  helpfulness, accuracy (1–5 each). Uses the Nemotron judge when
  `NEMOTRON_API_KEY` is set (`temperature=0.0`);
  otherwise falls back to self-judging with the model under test.
- Judge scores are stored under `model_metrics.model_judge` in the JSON report
  and as `judge_relevance/completeness/helpfulness/accuracy` columns in the CSV.

Override the judge URL with `--model-url` for the model-under-test call; the
Nemotron judge URL comes from `NEMOTRON_API_URL`.

## 2.5 What is scored (metrics)

Per case, per variant (Baseline A / Proposed):

- **Agent 1 (stays):** `has_min_stays`, `within_nightly_budget`,
  `location_match`, `avoids_visited` (when history avoidance applies),
  `no_false_history_exclusion`.
- **Agent 2 (transport):** `present`, `known_mode`, `non_negative_duration`,
  `non_negative_cost`, `walk_mode`/`zero_cost` (same-place), `city_consistent`.
- **Itinerary (coordinator):** `agent1_stays`, `agent2_transport`,
  `budget_total`, `day_coverage` (matches `expected_days`),
  `currency_consistent`, `fail_closed` (invalid/infeasible requests),
  `revise_noted` / `revision_note` (revise cases), `unique_pois`,
  `pois_per_day`, `interest_ranked_pois`, `avoids_visited_pois`.
- **History contrast:** Baseline A still recommends a visited stay while
  Proposed avoids all of them (and similarly for POIs).
- **Model metrics (API mode):**
  - **TTFT (Time To First Token):** `start_time → first_delta_time` in ms.
    Measures how long from sending the request until the first content/reasoning
    token arrives.
  - **TPS (Tokens Per Second):** `token_count / total_time`. Output throughput
    over the full generation.
  - **TPOT (Time Per Output Token):** `total_time_ms / token_count`. Average
    latency per token.
  - Token count is estimated as `len(content.split())` (word count), not actual
    model tokens, since the streaming endpoint returns text deltas without token
    counts.
  - LLM-as-a-Judge relevance/completeness/helpfulness/accuracy (1–5 each).

A case passes only when all applicable checks pass for both variants and all
contrasts pass.

## 2.6 Reproducibility & archiving

- **Deterministic baseline:** Always archive the stub-mode JSON/CSV report as
  the reproducible reference; it does not depend on the model API.
- **API-mode runs:** Model output may vary between runs. Archive the produced
  `eval/results/eval-<timestamp>.json`/`.csv` to pin that run's scores and
  latency metrics.
- **Isolated DB:** Each `run_suite` uses a fresh temp SQLite file, so seeded
  travel history never leaks between runs.
- **Case IDs are unique** (enforced by `test_eval_cases_have_unique_ids`).
- To re-run a specific set of cases identically: pass the same `--case` list.

## 2.7 Running the unit tests

```bash
cd <ROOT>
pip install -e ".[test]"
pytest tests/ -q
```

Relevant for evaluation reproducibility:
- `tests/test_eval_runner.py` — determinism, history avoidance, revise, tool
  cases, validation/fail-closed.
- `tests/test_tacc_client.py` — model client behavior (configured vs stub).

## 2.8 Known limitations / difficulties for evaluators

- **API mode requires network** to `https://integrate.api.nvidia.com/v1` from
  the server; if unreachable, the backend emits a labeled `[Model stub]` instead
  of a real model response.
- **`NEMOTRON_API_KEY` is empty** in the shipped `.env`, so the Nemotron
  LLM-as-a-Judge is disabled by default; set it to enable judge scores.
- **API-mode model output is non-deterministic** by nature; compare against the
  archived stub-mode report for deterministic checks, and archive API reports
  per run.
- **Server binding:** both backend and frontend must bind to `0.0.0.0` to be
  reachable through the server's stable URL; binding to `127.0.0.1` only allows
  local access.
- Postgres travel history (`DATABASE_URL=postgresql+psycopg://...`) requires a
  running Postgres on `localhost:5433`; the default is local SQLite, which
  works offline.

## 2.9 Contact / questions

Project-specific questions may be directed to the artifact authors through the
submission system during the review period.
