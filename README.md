# trip-planning-agent
CSIT6000V Course Project

## Architecture
<img width="3066" height="1746" alt="trip_agent_multiagent_overview" src="docs/figures/trip_agent_multiagent_overview.png" />

### Architecture flow

```
User (web UI)
    │  trip constraints: destination, dates, budget, interests
    ▼
Frontend  ──HTTP──►  Backend (FastAPI)
                         │
                         │  load settings (.env)
                         │  ENABLE_TRAVEL_HISTORY?  →  Baseline A = Agents 1–3 only
                         ▼
                    Agent 3 Coordinator
                    (distribute · cost check · POI · render · revise)
                         │
         ┌───────────────┼───────────────────┐
         ▼               ▼                   ▼
   Agent 1           Agent 2            Agent 4 (optional)
   Search Stays      Estimate Transport Travel History
         │               │                   │
         ▼               ▼                   ▼
   stay search       maps / distance    SQLite|Postgres
   (stub|api)        (stub|api)         (DATABASE_URL)
         │               │                   │
         └───────────────┴───────────────────┘
                         │
                         ▼
              TACC model-serving endpoint
              (request → queue → model worker)
              Backend only — UI is NOT hosted on TACC
                         │
                         ▼
              Structured itinerary + logs
              (optional Langfuse traces)
                         │
                         ▼
              User sees plan; on edit → revise loop
```

| Piece | Role |
|-------|------|
| **Frontend** | Collect constraints; show itinerary |
| **Backend** | Session, orchestration, `/plan` + `/plan/revise` + `/health` |
| **Agent 1 `search_stays`** | Accommodation under budget / location |
| **Agent 2 `estimate_transport`** | Travel time & cost between points |
| **Agent 3 `coordinator`** | Distribute work, cost check, render, revise; POI for MVP |
| **Agent 4 `travel_history`** | Previously visited places (proposed only; off in Baseline A) |
| **TACC client** | LLM calls via course endpoint |
| **Tools** | Stay / maps APIs or stubs |

**Proposed:** Agents 1–4. **Baseline A:** Agents 1–3 only (`ENABLE_TRAVEL_HISTORY=0`).

### Development direction

LangGraph is now the orchestration foundation. Agent 4 (`travel_history`) and
Agent 1 (`search_stays`) are explicit graph nodes that prepare shared state
before the coordinator node renders the itinerary. This keeps the existing
architecture stable while future work can add explicit planning, tool, revision,
and rendering nodes.

Agent 1 uses the curated stub catalog in `agents/search_stays/tools.py`
(city match + generic fallback, ordered by nightly cost under budget/nights).
`run(..., excluded_locations=...)` filters out name/location overlaps from
Agent 4 when `avoid_visited=true`. Direct probe: `POST /agents/search_stays`.
`TOOL_STAYS_MODE=web` sources live stay results from the DuckDuckGo
web-search tool (requires `WEB_SEARCH_MODE=duckduckgo`; falls back to the
labeled stub catalog when web search is unavailable).
`TOOL_STAYS_MODE=api` is the legacy OBO Travel provider, kept for rollback.

Agent 4 uses `DATABASE_URL` and stores visits in the `travel_history`
table, keyed by `TripRequest.user_id`. It returns distinct places in
most-recent-first order and is disabled for Baseline A when
`ENABLE_TRAVEL_HISTORY=0`. Evaluation fixtures or application code can add a
visit through `TravelHistoryStore.record_visit`. Chat conversations remain on
local SQLite even when travel history points at Postgres.

#### Plan currency (`/plan` workflow)

The coordinator enforces the budget in a single currency: it derives one plan
currency from the costed stay and transport components and sets
`Itinerary.currency`. When costed components carry different currencies the
request fails closed with `NoFeasiblePlanError` instead of silently summing
them, and when a positive cost has no currency label the plan notes that the
budget was not enforced. The stub catalogs are consistent per city
(Hong Kong in HKD; Tokyo, Amsterdam, and the generic catalog in USD).

#### Revise loop (`POST /plan/revise`)

When the user changes budget, dates, or interests on an existing `/plan`
result, `POST /plan/revise` re-enters the agent pipeline (Agent 4 travel
history, Agent 1 stay search, coordinator cost check, render) with the updated
`TripRequest` instead of appending ad-hoc chat text. The request carries the
previous `Itinerary` plus the new constraints; the response notes what changed
(`Revised for new budget: 350.0 (was 600.0)`, `Revised for new trip length: ...
`) and re-applies the stay step-down and fail-closed cost check to the new
figures. Revisions keep the same destination (a destination change returns 422;
start a new plan instead). On the chat side, constraint changes already flow
back through `plan_context` on the next turn.

The coordinator also uses the model for its proposal role: after the plan is
feasible it asks the configured endpoint for 1-3 short user-facing summary
notes (returned as labeled `Model summary:` notes in `Itinerary.notes`). Stub
mode, network errors, and malformed output leave the deterministic notes
unchanged, and the summary is never hidden chain-of-thought.

#### Travel history database (`DATABASE_URL`)

| Backend | When to use | Connection |
|---------|-------------|------------|
| **SQLite (default)** | Local without Docker/cloud | `DATABASE_URL=sqlite:///./data/travel_history.sqlite` |
| **Postgres (Docker)** | Optional local Postgres | `docker compose up -d postgres`, then `DATABASE_URL=postgresql://trip:trip@localhost:5432/travel_history` |
| **Postgres (Neon)** | Course/cloud shared DB | Update `.env`: set `DATABASE_URL` to the pooled Neon connection string (optional: `DATABASE_URL_UNPOOLED`, `NEON_BRANCH`). `neon init` / `neon deploy` / `neon env pull` can write these values into `.env`. |

**Driver:** install once with `pip install ".[db]"` (pulls `psycopg[binary]`), or `pip install "psycopg[binary]"`.

**Neon:** to use Neon for Agent 4 travel history, update `.env` with the pooled `DATABASE_URL`. Optionally also set `DATABASE_URL_UNPOOLED` (direct URL for migrations/admin) and `NEON_BRANCH` (for example `production`). The app reads only these `.env` values, not the Neon project files. The Neon CLI (`neon init` / `neon deploy` / `neon env pull`) can write or refresh the credentials in `.env`. `.env` is gitignored — never commit real URLs or passwords; use placeholders in docs only.

**Health check:** `GET /health` → `agents.travel_history.storage` is `sqlite` or `postgres` (also reports a redacted connection summary).
Chat messages also record explicit past-visit statements, using the
conversation ID as the memory key. For example, "I have gone to the Peak
before" is stored as "Victoria Peak" and produces a visible travel-history
activity event. The chat model receives `search_travel_history` as a callable
tool and decides when to search related saved locations; travel history is not
injected into the system prompt or user prompt.

The web UI exposes agent activity (coordinator lifecycle, model request
preparation, agent steps,
model calls, thinking status, results, and errors) without displaying private
chain-of-thought. "Thinking" is represented by safe execution status rather
than hidden model reasoning.

The UI also includes a Travel history page. Entries store country, city, and
visited location, and can be added or removed manually. The page is organized by
**country**, with cities nested inside each country and a place count, so the
memory reads as a country-oriented list. Chat activity renders safe
workflow/tool events such as travel-history lookup and memory updates; private
chain-of-thought is never used as an activity event.

The chat workflow also provides an `ask_user_question` tool. When the model
needs a planning decision, it can return a structured question with two to six
options; the UI renders selectable options plus an **Other…** field for a custom
free-text answer (validated server-side) instead of requiring the model to print
a question list. Tool arguments and results are persisted in the
conversation events. The Live workflow is collapsed by default to keep the
chat compact; expand it to inspect the ordered tool calls and saved results.
Selecting an option resumes the same model tool session through
`POST /api/chat/question/stream`; it is not sent as an ordinary chat message.
The continuation streams the same `event` / `reasoning` / `content` / `done`
frames as `/api/chat/stream`, so the UI keeps showing agent activity, partial
text, and the **Stop** button instead of waiting on a silent request.
`POST /api/chat/question` remains available as the non-streaming equivalent.
The question is shown above the chat while waiting, and a failed continuation
keeps the pending choice available for retry instead of marking it answered.
The trip plan is built with several small tools instead of one large payload, so
the UI renders it part by part and follow-up edits stay small (fewer tokens):
`start_trip_plan` (destination, arrival `airport`, coordinates, currency,
estimated total, notes), `set_trip_day` (one day at a time), `set_trip_budget`
(the overall total or a single day's budget and/or items), `set_trip_references`,
`remove_trip_day`, and `get_trip_plan` (read the current plan). The assembled
plan is stored per conversation and rendered as the focal, wide trip-plan panel
to the right of the conversation. The chat pane is intentionally smaller, the
sidebar is collapsible, and the card is theme-aware (light/dark). It draws the
route on an interactive OpenStreetMap/Leaflet map: the **arrival airport is the
first point** of the route (shown with a distinct marker), and a map link is
shown when no coordinates are provided. Tool payloads are validated in
`shared/trip_plan.py`, invalid tool arguments come back as labeled errors (they do
not abort the turn), and only `http(s)` reference URLs are accepted.

Each day card **merges the route with its own itemized budget**, so the day's
activities/places and its budget are viewed and edited together (the day **Edit**
saves both). The plan has an **Overview / Day by day** toggle: the overview lists
each day with its budget and map reference, and the day-by-day view uses
collapsible day cards with Expand all / Collapse all to avoid long scrolling. The
panel also shows an independent **estimated total** (never derived from the item
breakdown) and the global category items with an **items total** and a note when
it differs from the estimate; the estimated total and the category items are
edited via their own **Edit**. It also renders externally linked references and
numbered day/place labels that reference the map markers. The Live workflow panel
scrolls to the latest event and names the agent currently working. The plan can be
exported as a day-by-day Markdown file or a printable, day-oriented PDF report
(hero summary, route-by-day timeline, per-day details and budgets). Categories are
expected to use concrete labels rather than a vague "other" bucket.

Edited budgets are persisted with `PUT /api/conversations/{id}/trip-plan` and
are sent to the model on the next turn as a `plan_context` block, so the agent
reflects the user's corrected figures without a separate notification message.

The chat model can also call the sub-agent tools `search_stays` (Agent 1),
`estimate_transport` (Agent 2), and `web_search` during a turn, defined in
`agents/chat_tools.py`. It can also call `get_weather_forecast` with a location
and an optional 1–7 day range. Weather uses an offline-safe, clearly labeled
sample by default; set `WEATHER_FORECAST_MODE=open_meteo` to geocode with
Nominatim and fetch daily data from Open-Meteo. The forecast tool is registered
with the existing chat/coordinator dispatcher and does not add a separate
weather-agent route. Tool results carry their mode and provider failures are
returned as labeled errors so one failing tool does not abort the turn.

The chat composer shows a **Stop** button while a model turn is streaming. The
button calls `POST /api/chat/stop` with the turn's `request_id`, then aborts the
local stream; the backend sets a cooperative cancel event that the streaming
loop and `TACCClient` check between deltas, saving the partial response. After a
response, the UI also shows contextual **Next steps** suggestions, and the
"YOUR INPUT NEEDED" question panel is hidden once its question has been
answered.

Travel history API endpoints:

- `GET /api/travel-history?user_id=...`
- `POST /api/travel-history`
- `DELETE /api/travel-history/{entry_id}?user_id=...`

Assistant responses render GitHub-flavored Markdown, including headings, lists,
links, tables, inline code, and fenced code blocks. User messages remain plain
text.

Chat and coordinator model calls share the system prompt in
`shared/prompts.py`. It directs the model to produce practical trip plans,
label estimates and assumptions, ask focused clarification questions when
essential details are missing, format answers as Markdown, and avoid exposing
private chain-of-thought.

The repository includes an optional web-search tool for testing:

```text
WEB_SEARCH_MODE=stub       # safe default; no network request
WEB_SEARCH_MODE=duckduckgo # uses DuckDuckGo HTML results
```

Test it with `POST /api/tools/web-search` and a JSON body such as
`{"query":"things to do in Tokyo","limit":5}`. Search results are not treated
as reservations or verified live availability.

### Stay search (Agent 1)

`search_stays` returns accommodation candidates under budget near the
destination. Four modes are controlled by `TOOL_STAYS_MODE`:

| Mode | Source | Returns |
|------|--------|---------|
| `stub` | Curated local catalog | Name, location, nightly cost, phone, website, rating, amenities |
| `overpass` | OpenStreetMap Overpass API | Real names, coordinates, addresses, star ratings (no cost/availability) |
| `web` | DuckDuckGo web search (via `agents/web_search`) | Real stay pages with provenance (`web search: <host>`); nightly prices parsed from snippets when confidently listed (normalized to approximate USD), labeled estimates otherwise |
| `api` | OBO Travel MCP (legacy, kept for rollback) | Live nightly rates, booking URLs, star ratings, cancellation policy |

Set `TOOL_STAYS_MODE` in `.env` (default: `stub`). `web` mode also needs
`WEB_SEARCH_MODE=duckduckgo`; when web search is unavailable it falls back to
the labeled stub catalog. For legacy `api` mode, also set
`STAYS_API_BASE_URL=https://onebookingonline.com/mcp`. The OBO Travel API is
free for anonymous use (30 req/min, 500 req/day); no signup or credit card
required.

Example:
```bash
POST /agents/search_stays
{"destination":"Tokyo","budget":500,"days":3,"interests":["temples","food"],"check_in":"2026-12-10","check_out":"2026-12-13"}
```

See [`agents/search_stays/README.md`](./agents/search_stays/README.md) for
full details on all three modes and environment variables.


For reasoning-capable models such as NVIDIA Nemotron, the streaming client
requests thinking output and displays the returned `reasoning_content` (or
`reasoning`) in a separate collapsed **Model reasoning** block. Providers that
do not return a reasoning field continue to display the final answer normally.
The NVIDIA-compatible request uses `temperature=1`, `top_p=0.95`,
`max_tokens=16384`, and `reasoning_budget=16384`; the larger shared budget
prevents reasoning from consuming the entire response before answer tokens are
generated.

The user message is saved before the model request begins. Conversations and
their model/agent activity are stored in the configured SQLite database, so a
failed request remains available for retry. The UI provides a conversation
list, retrieval, deletion, retry, and new-conversation control.
The chat endpoints are:

- `GET /api/conversations`
- `GET /api/conversations/{conversation_id}`
- `DELETE /api/conversations/{conversation_id}`
- `POST /api/chat/stream` (accepts an optional `request_id` used for cancellation and `plan_context`)
- `POST /api/chat/question/stream` (resumes a paused question; same frames and `request_id` cancellation as the chat stream)
- `POST /api/chat/question` (non-streaming equivalent)
- `POST /api/chat/stop` (body `{"request_id": "..."}`; sets the turn's cancel event)
- `PUT /api/conversations/{conversation_id}/trip-plan` (persist edited `budget`, `currency`, and `budget_items` onto the latest plan)

## Run local (Windows)

From PowerShell:

```powershell
# From the repository root (PowerShell on Windows; the equivalent bash
# commands work on macOS/Linux, e.g. `copy` -> `cp`, `.\.venv\Scripts\Activate.ps1`
# -> `source .venv/bin/activate`).
cd trip-planning-agent

# 1. Env file (fill QWEN_* when you have course credentials; stubs work with blanks)
copy .env.example .env

# 2. Virtualenv + deps
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Build the React UI
npm install
npm run build

# If Activate.ps1 is blocked:
# Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 4. Start backend and UI
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Check:
- Health: http://127.0.0.1:8000/health  (expect `"ok": true`)
- API docs: http://127.0.0.1:8000/docs
- UI: http://127.0.0.1:8000/

The Settings tab can change the model endpoint, model name, and API key for
the running process. The key is write-only and is not returned by the API.
These changes are not persisted across restarts; use `.env` for persistent
deployment defaults.

### Security notes (local development scope)

- The UI is served same-origin; CORS is limited to `localhost`/`127.0.0.1`
  origins, and `PUT /api/settings/model` is only accepted from the local
  machine because it repoints the shared model endpoint.
- Cancellation (`/api/chat/stop`), the in-process model-configuration
  overrides, and the conversation store locks are **per-process**: run the
  backend with a single uvicorn worker (the default) for these to behave.
- There is no authentication: `user_id` is client-supplied, so travel history
  and conversations are only as isolated as the host allows. Treat a deployed
  instance as single-user/group-internal (course scope).
- Chat conversations and travel history live in local SQLite files under
  `data/`; Docker is local-debug only and is not the TACC deployment path.

Stop the server with `Ctrl+C` in that terminal.

The UI is built with React and Vite. During UI development, run `npm run dev`
for the Vite development server; the normal backend workflow serves the
production build from `frontend/dist`.

### Docker (local debugging only)

The backend and UI are packaged together for local debugging:

```powershell
copy .env.example .env
New-Item -ItemType Directory -Force data
docker compose up --build
```

The compose file bind-mounts the local `./data` folder to `/app/data`, so
SQLite conversations (and SQLite travel-history when that is the backend) remain
on the host and survive container recreation. Open http://localhost:8000/.
Docker is only for local development and is not the TACC deployment mechanism.
The optional `QWEN_BASE_URL` can point to a running course service, or remain
blank to use local stub responses.

Optional local Postgres for Agent 4 travel history (same compose file):

```powershell
docker compose up -d postgres
pip install ".[db]"
# then in .env:
# DATABASE_URL=postgresql://trip:trip@localhost:5432/travel_history
```

Credentials match `.env.example` (`trip` / `trip` / `travel_history`). Stop
only Postgres with `docker compose stop postgres`; `docker compose down` keeps
the `pgdata` volume unless you add `-v`.

For cloud Postgres (Neon), keep Docker Postgres off and update `.env`: set
`DATABASE_URL` to the pooled connection string (see Travel history database
above). Do not put real Neon passwords in the README or git.

Useful checks from another PowerShell window:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/conversations
```

Stop the container with `docker compose down`; the local `data` folder is
preserved. Use `docker compose logs -f app` to inspect startup or request
errors.

### Key `.env` knobs
| Variable | Notes |
|----------|--------|
| `QWEN_BASE_URL` / `QWEN_MODEL` / `QWEN_API_KEY` | OpenAI-compatible model endpoint and model identifier. Set the base URL including `/v1`; set the key when required by the provider. |
| `MODEL_MAX_TOKENS` / `MODEL_TEMPERATURE` / `MODEL_TOP_P` / `MODEL_REASONING_BUDGET` | Sampling defaults sent in the chat-completions payload (defaults: `16384` / `1.0` / `0.95` / `16384`). |
| `MODEL_ENABLE_THINKING` | Optional override for Qwen thinking mode. Unset keeps the default: enabled while streaming, disabled for one-shot completions. |
| `ENABLE_TRAVEL_HISTORY` | `1` = proposed (Agent1–4); `0` = Baseline A (Agent1–3) |
| `TOOL_STAYS_MODE` | `stub` (default, offline-safe), `overpass` (OpenStreetMap, no auth), `web` (live web-search results; needs `WEB_SEARCH_MODE=duckduckgo`, falls back to stub), `api` (OBO Travel — legacy, kept for rollback) |
| `TOOL_MAPS_MODE` | `stub` or `api` |
| `WEB_SEARCH_MODE` | `stub` (default, offline-safe) or `duckduckgo` (live DuckDuckGo HTML search; powers the web-search tool and `TOOL_STAYS_MODE=web`) |
| `WEATHER_MODE` | `stub` (default, offline-safe) or `open-meteo` (live Open-Meteo forecasts, no auth; falls back to stub on failure) |
| `GEOCODING_ENABLED` | Set to `1` to resolve Overpass destinations with rate-limited Nominatim geocoding |
| `STAYS_API_BASE_URL` | OBO Travel MCP base URL, e.g. `https://onebookingonline.com/mcp` (legacy; used when `TOOL_STAYS_MODE=api`) |
| `STAYS_API_KEY` | Optional OBO Travel API key for higher rate limits |
| `STAYS_API_TIMEOUT` | Request timeout seconds (default 30) |
| `OVERPASS_API_URL` | Comma-separated Overpass mirror URLs (used when `TOOL_STAYS_MODE=overpass`) |
| `OVERPASS_TIMEOUT` | Overpass request timeout seconds (default 30) |
| `OVERPASS_RADIUS_METERS` | Overpass search radius in meters (default 5000) |
| `DATABASE_URL` | Travel history DB. Default SQLite: `sqlite:///./data/travel_history.sqlite`. Local Docker Postgres: `postgresql://trip:trip@localhost:5432/travel_history` (`pip install ".[db]"`, `docker compose up -d postgres`). To use Neon, update `.env` with the pooled URL (`neon init` / `neon deploy` / `neon env pull` can write it). Chat stays on SQLite. `GET /health` → `agents.travel_history.storage` = `sqlite` \| `postgres`. |
| `DATABASE_URL_UNPOOLED` | Optional Neon direct URL (migrations/admin). App runtime uses pooled `DATABASE_URL`. |
| `NEON_BRANCH` | Optional Neon branch name (e.g. `production`) when using Neon. |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | Langfuse 5.x credentials and host |
| `LANGFUSE_ENABLED` | Set to `1` to emit flushed model-generation traces |
| `LANGSMITH_API_KEY` | Optional LangSmith API key. When set, every LLM call is traced for evaluation (TTFT, TPOS, input, and output). Create a key at https://smith.langchain.com. |
| `LANGSMITH_ENDPOINT` | Optional LangSmith API URL (default `https://api.smith.langchain.com`). |
| `LANGSMITH_PROJECT` | Optional LangSmith project name (default `trip-planning-agent`). |
| `NEMOTRON_API_KEY` / `NEMOTRON_API_URL` | Optional Nemotron judge API used by API-mode evaluation |

Install the Langfuse extra before starting the backend:

```powershell
pip install -e ".[langfuse]"
```

Each chat turn creates one Langfuse trace (`chat.turn`, or `chat.question` for
a resumed clarification) with the Qwen requests recorded as child generations.
Tool-call rounds stay in the same trace and record the requested tool names and
arguments as their output, so multi-step turns no longer appear as separate
traces. `/plan` requests create a `plan.request` trace around the coordinator
workflow. Chat traces use the application `conversation_id` as their Langfuse
session ID, so all turns in one conversation can be reviewed together.
Standalone `/plan` requests receive a generated session ID. Streaming requests
record the final answer text, while private reasoning content is not sent to
Langfuse. Tracking errors are logged without changing the model request result.

**LangSmith (optional evaluation traces).** LangSmith is off until you set `LANGSMITH_API_KEY` in `.env` (there is no separate enable flag). Install the client with `pip install langsmith`, create an API key at [LangSmith](https://smith.langchain.com), then update `.env`:

```powershell
# Required to turn LangSmith on:
LANGSMITH_API_KEY=your-key
# Optional; these are the defaults:
# LANGSMITH_ENDPOINT=https://api.smith.langchain.com
# LANGSMITH_PROJECT=trip-planning-agent
```

Restart the app, run a request that calls the model, then open [LangSmith](https://smith.langchain.com) and select the project (`trip-planning-agent` by default). Traces record model input and output separately, plus TTFT and TPOS. Tracking errors are logged without changing the model request result. Do not commit the API key. The graded stub evaluation does not use LangSmith.

UI is not hosted on TACC; only the backend calls the course model-serving endpoint (request → queue → worker).

### Deploy to TACC

The repository includes a self-contained deployment package in
[`tacc/`](./tacc/). It does not depend on `tacc_reference`. Submit
[`tacc/qwen-public-serve/`](./tacc/qwen-public-serve/) first, copy its
`SERVICE_BASE_URL` into [`server-url.txt`](./server-url.txt), then submit the
repository root using [`tuxiv.conf`](./tuxiv.conf). See
[`tacc/README.md`](./tacc/README.md) for the complete sequence.

## Evaluation (Baseline A vs Proposed)

The project evaluates Baseline A (`ENABLE_TRAVEL_HISTORY=0`, Agents 1–3) against Proposed (`ENABLE_TRAVEL_HISTORY=1`, Agents 1–4) in three complementary ways: a reproducible automatic stub harness, **AI evaluation** of live model outputs, and **human evaluation** with an explicit scoring rubric. Langfuse and LangSmith are optional tracing tools; they do not replace these checks. Details and commands are in [`eval/README.md`](./eval/README.md).

### Automatic stub harness

```powershell
.\.venv\Scripts\python.exe -m eval.runner
```

The suite compares the two variants on stay budget and location, transport fields, history avoidance, revise, and fail-closed behaviour. Stub mode is offline by default and does not use LangSmith or a live model. On the current codebase the expected result is `Eval [STUB] 30/30` (25 plan/revise cases plus 5 tool-layer cases), with History contrast `4/4` and Tool layer `5/5`. This is the graded reproduction path.

### AI evaluation

`--mode api` uses the configured Qwen endpoint and requires `QWEN_BASE_URL` (or `--model-url`). It records response metrics such as TTFT and tokens per second in the JSON/CSV report under `eval/results/`. When `NEMOTRON_API_KEY` and `NEMOTRON_API_URL` are set, the runner also attaches an LLM-as-a-judge score from NVIDIA Nemotron (Nemotron-3.5-Bolt-E4B). The judge rates each model response on a 1–5 integer scale for four dimensions:

- **relevance:** does the response address the requested destination, dates or days, and other stated constraints?
- **completeness:** are stays, transport, and daily activities present for the requested trip length?
- **helpfulness:** is the itinerary usable and actionable?
- **accuracy:** are recommended places, costs, and details consistent with the request and with each other?

A model response is treated as acceptable on the AI judge if every dimension is at least 3. Live scores can vary with the endpoint and are not part of the stub 30/30 count. API mode talks to the model directly and does not send traces to LangSmith.

To inspect live LLM calls from the running app in LangSmith (TTFT, TPOS, and model input/output), set `LANGSMITH_API_KEY` in `.env` as described under Key `.env` knobs above, install `langsmith`, restart the app, then open the traces at [LangSmith](https://smith.langchain.com) in the project named by `LANGSMITH_PROJECT` (default `trip-planning-agent`). If the LangSmith organization is in the GCP APAC region, open [APAC LangSmith](https://apac.smith.langchain.com) and set `LANGSMITH_ENDPOINT=https://apac.api.smith.langchain.com`. The stub harness does not use LangSmith.

### Human evaluation

Human raters score the same Baseline A versus Proposed trip plans (and, when available, API-mode model itineraries) with a fixed rubric, so success criteria and scoring rules are explicit. The 1–5 dimensions match the AI judge — relevance, completeness, helpfulness, and accuracy — using the same questions listed above, so the two sets of scores can be compared.

Raters also mark these binary checks, which align with the automatic harness:

- **Stay location and budget:** the stay is in the requested city and does not exceed the nightly budget.
- **Transport:** transport is present and city-consistent (for example, a Paris airport must not reuse a Hong Kong catalog row).
- **History contrast:** on `avoid_visited` cases, Proposed must drop the visited stay or POI. Baseline A is expected to still include it; do not mark Baseline A as failing this check for that reason. Record whether the contrast holds (Proposed avoids, Baseline A does not).
- **Revise:** after a tighter budget or a shorter trip, the new plan still meets the revised constraints.
- **Fail-closed:** an invalid or infeasible request fails clearly and does not silently overspend.
- **Source links:** when the plan includes source links, they should open and refer to the recommended place. Leave this check blank when no links are present.

**Scoring rules.** Each 1–5 dimension is an integer from 1 (poor) to 5 (excellent). A rater marks a plan *acceptable* only if every applicable dimension is at least 3 and every applicable binary check passes. For an invalid or infeasible request, the item is acceptable only if the system fails closed and the failure is understandable. Raters should score independently and record `case id`, variant (`baseline_a` or `proposed`), rater id, the four dimension scores, the binary checks, an acceptable/not-acceptable mark, and a short note. Store that sheet as a CSV under `eval/results/` (this file is not written by `eval.runner`). The stub 30/30 result does not require human raters.

## Getting Started Instructions

This section is a short kick-the-tires path. After a normal Python setup you can confirm that the artifact runs in well under 30 minutes, with no TACC account, API keys, or Docker.

### Prerequisites

- Python 3.11 or newer
- Git
- A virtual environment tool (`python -m venv` is enough)
- **Optional, for the web UI only:** Node.js 18+ with npm
- **Optional:** Docker, for local container debugging
- **Optional:** a TACC/`tcloud` login, only if you want to serve the course Qwen model

The commands below are written for Windows PowerShell. On Linux or macOS, use `.venv/bin/python` instead of `.\.venv\Scripts\python.exe`, and `cp` instead of `copy`.

### Setup

```powershell
git clone https://github.com/sumsum12334/trip-planning-agent.git
cd trip-planning-agent
copy .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` and retry, or call the venv Python with an explicit path as shown below. Leave the Qwen fields in `.env` blank for this smoke test, and leave the default `DATABASE_URL` (local SQLite). To use Neon later for Agent 4 travel history, update `.env` with the pooled `DATABASE_URL` as described under Travel history database above. Never commit `.env`.

### End-to-end example: one evaluation case

From the repository root, with the virtual environment available:

```powershell
.\.venv\Scripts\python.exe -m eval.runner --case tokyo_history_avoid_shibuya
```

This case seeds a visit to Shibuya and asks for a Tokyo plan with `avoid_visited=true`. It runs the same request under Baseline A and Proposed.

**Expected output** (elapsed times vary by machine; the pass/fail fields should match):

```
Eval 1/1 cases passed (96.6 ms). History contrast 1/1. Tool layer 0/0.
tokyo_history_avoid_shibuya  kind=plan  baseline=PASS  proposed=PASS  days=4/4  extra=PASS
Wrote eval/results/eval-YYYYMMDD-HHMMSS.json
Wrote eval/results/eval-YYYYMMDD-HHMMSS.csv
```

How to read this line:

- `baseline` and `proposed` are both `PASS`, so both variants return a valid 4-day itinerary (`days (exp)` is `4/4`).
- `extra` is the history-contrast check: Proposed must drop the already-visited Shibuya stay, while Baseline A (no Agent 4) still recommends it. `PASS` means that contrast holds.

A LangChain/LangGraph deprecation warning from the installed library may appear on stderr. It does not fail the case.

### Optional: start the web app and check `/health`

This is not required to reproduce the evaluation. It confirms that the UI and API start locally.

```powershell
npm install
npm run build
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Then open:

- UI: http://127.0.0.1:8000/
- Health: http://127.0.0.1:8000/health — the JSON should include `"ok": true`
- API docs: http://127.0.0.1:8000/docs

Without `QWEN_BASE_URL`, chat uses a local stub. Stay search defaults to the offline `stub` catalog. Stop the server with `Ctrl+C`. For UI-only development, `npm run dev` starts the Vite dev server; the commands above serve the production build from `frontend/dist`.

## Detailed Instructions

This section explains how to rerun the evaluation that supports the project's main findings, and how to interpret the outputs.

### What the harness measures

`eval/runner.py` runs each plan case twice:

- **Baseline A:** `ENABLE_TRAVEL_HISTORY=0` (Agents 1–3)
- **Proposed:** `ENABLE_TRAVEL_HISTORY=1` (Agents 1–4)

It always forces stub stay and maps tools and an isolated temporary SQLite database. It does not use your `.env` `DATABASE_URL` or a live model.

The checks cover:

- Stay budget and location constraints
- Required transport fields and city-consistent catalog matches
- History avoidance (Proposed drops a visited stay or POI; Baseline A still includes it)
- Multi-day coverage (`expected_days`)
- Budget revise (switch to a cheaper stay when the plan is over budget)
- The revise loop (`REVISE_CASES`): after an initial plan, re-enter the pipeline with a cut budget or a shorter trip and check the new constraints
- Fail-closed behaviour for invalid or infeasible requests
- Gold tool-call cases in `eval/tool_cases.py` (the chat tool layer with the arguments a model should pass). This is **not** live model tool-routing accuracy.

### Reproduce the full evaluation

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m eval.runner
```

Useful variants:

```powershell
.\.venv\Scripts\python.exe -m eval.runner --plan-only
.\.venv\Scripts\python.exe -m eval.runner --tools-only
.\.venv\Scripts\python.exe -m eval.runner --case tokyo_revise_cheaper_stay --case tokyo_history_avoid_poi
```

Optional live-model mode (not required to reproduce the stub results):

```powershell
.\.venv\Scripts\python.exe -m eval.runner --mode api
```

API mode is the AI evaluation path described under Evaluation above. It requires `QWEN_BASE_URL` (including `/v1`) or `--model-url`. It is separate from the deterministic Baseline A vs Proposed tool checks: it calls the configured model and records response metrics such as TTFT and tokens per second in the JSON/CSV report. If `NEMOTRON_API_KEY` and `NEMOTRON_API_URL` are set, the runner attaches Nemotron LLM-as-a-judge scores (relevance, completeness, helpfulness, and accuracy, each 1–5). A response is treated as acceptable on the AI judge if every dimension is at least 3. Live scores can vary and are not the graded stub reproduction path. API mode does not send traces to LangSmith.

To inspect live LLM calls from the running app in LangSmith, set `LANGSMITH_API_KEY` in `.env` (see Key `.env` knobs), install `langsmith`, restart the app, and open [LangSmith](https://smith.langchain.com) in the `LANGSMITH_PROJECT` (default `trip-planning-agent`). If the organization is in the GCP APAC region, use [APAC LangSmith](https://apac.smith.langchain.com) and set `LANGSMITH_ENDPOINT=https://apac.api.smith.langchain.com`. Traces include TTFT, TPOS, and model input/output. The stub evaluation does not use LangSmith.

Human evaluation uses the rubric and scoring rules in the Human evaluation subsection above. Score Baseline A and Proposed plans (and API-mode itineraries when available) independently, then save a CSV under `eval/results/`. Human ratings are not produced by `eval.runner` and are not required to reproduce the stub 30/30 result.

Reports from the runner are written to `eval/results/` as JSON and CSV. That directory is gitignored.

Unit tests (including a determinism check that the same stub case twice agrees) are optional:

```powershell
pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest
```

### Test cases, data, and configuration

Cases are defined in `eval/cases.py` and `eval/tool_cases.py`. They are written against the stub catalogs in `agents/search_stays/tools.py` and `agents/estimate_transport/tools.py`. No external data download is required.

**Plan cases**

| Case id | What it checks |
|---------|----------------|
| `tokyo_budget_ok` | Tokyo stay under budget, location match |
| `tokyo_history_avoid_shibuya` | Proposed avoids a visited Shibuya stay; Baseline A still recommends it |
| `tokyo_history_without_avoid_flag` | History exists but `avoid_visited` is off |
| `hk_budget_ok` | Hong Kong stay under budget |
| `hk_tight_budget` | Tight budget still yields a feasible stay |
| `hk_history_avoid_central` | Proposed avoids a visited Central stay |
| `amsterdam_ok` | Amsterdam stub catalog path |
| `unknown_city_generic_fallback` | Unknown city may use the generic fallback |
| `empty_catalog_tight_budget` | No feasible stay: fail closed |
| `transport_same_place_walk` | Same-place transport is a walk |
| `tokyo_history_multiple_places` | Several visited places are avoided |
| `tokyo_history_unrelated_place` | A Hong Kong visit must not drop Tokyo stays |
| `hk_over_budget_transport` | Over-budget plan is revised or fail-closed |
| `tokyo_history_alias_shibuya` | Lowercase `shibuya` still matches |
| `tokyo_history_city_too_broad` | A visit recorded only as `Tokyo` must not drop every Tokyo stay |
| `paris_airport_not_hk_catalog` | Paris airport transport must not reuse the Hong Kong Airport Express row |
| `empty_destination_fail_closed` | Empty destination should fail closed at validation |
| `invalid_days_zero` | `days=0` should fail closed |
| `tokyo_airport_cost_scale` | Large transport vs stay budget is flagged; the case can still pass |
| `tokyo_revise_cheaper_stay` | Coordinator revises to a cheaper stay when over budget |
| `tokyo_pois_interest_food` | POI packing respects interest ranking |
| `tokyo_history_avoid_poi` | Proposed drops a visited POI; Baseline A still includes it |
| `tokyo_dates_span_three_days` | Inclusive start/end dates with no `days` field still yield a 3-day itinerary |
| `hk_revise_budget_cut` | After an initial plan, the revise loop must satisfy a lower budget |
| `tokyo_revise_shorter_trip` | After an initial plan, the revise loop must cover a shorter trip |

**Tool-layer cases** (run with the default suite, or `--tools-only`): `tool_search_stays_tokyo`, `tool_estimate_transport_hk`, `tool_stays_and_transport_amsterdam`, `tool_search_stays_missing_destination`, `tool_unknown_name`.

### Expected results and how they map to the report

On the current codebase, a full stub run prints a header of the form:

```
Eval [STUB] 30/30 cases passed (... ms). History contrast 4/4. Tool layer 5/5.
```

followed by one row per case and `Wrote` paths for the JSON and CSV reports. Latency numbers vary by machine; pass/fail columns should not. This count is 25 plan/revise cases plus 5 tool-layer cases.

The metrics that support the main findings are:

- **History contrast** (`History contrast 4/4` in the header, and `extra=PASS` on the avoidance cases). This is the Baseline A vs Proposed difference: with a seeded visit and `avoid_visited=true`, Proposed drops the visited stay or POI and Baseline A does not. See the history-avoidance cases above.
- **Per-agent plan checks** (`baseline` / `proposed` columns): stay budget and location, transport fields, day coverage, revise, and fail-closed.
- **Revise loop** (`kind=revise` rows such as `hk_revise_budget_cut` and `tokyo_revise_shorter_trip`): after the first plan, the coordinator is re-entered with tighter constraints and must still pass.
- **Tool layer** (`Tool layer 5/5`): the gold tool-call cases succeed independently of a live model.
- **AI evaluation** (`--mode api`, optional): JSON/CSV fields for TTFT and tokens per second, plus Nemotron judge scores for relevance, completeness, helpfulness, and accuracy when the Nemotron key is set. These are not part of the stub 30/30 count.
- **Optional LangSmith traces** (live app only): when `LANGSMITH_API_KEY` is set, LLM traces in [LangSmith](https://smith.langchain.com) (or [APAC LangSmith](https://apac.smith.langchain.com) for an APAC organization) show TTFT, TPOS, and model input/output. This is not part of the stub 30/30 result.
- **Human evaluation:** rater CSVs under `eval/results/` using the rubric above (the same four 1–5 dimensions, plus the binary checks and the acceptable/not-acceptable rule). These scores are collected by raters, not by `eval.runner`.

Please map the automatic outputs, AI judge scores, and human scores to the corresponding tables or figures in the project report when you discuss Baseline A vs Proposed, history avoidance, budget revise, and fail-closed behaviour. The JSON/CSV files in `eval/results/` are the machine-readable source for those numbers.

Environment variables, Docker, TACC deployment, and the live web-app demo are documented in the sections above.

### Known limitations and expected variation

- The graded reproduction path is the stub eval harness. It does not measure live-model tool-routing quality, Overpass/OBO or live web-search results, or TACC serving performance.
- Latency in the printed summary varies by machine. Pass/fail on stub cases should be stable; `tests/test_eval_runner.py` checks determinism for a stub case.
- Live stay/maps/weather modes and live model endpoints can vary with availability, rate limits, and provider data. They may differ from the stub catalogs used in the report's main tables.
- API-mode results and optional Nemotron judge scores depend on a live endpoint and can vary. They are not required to reproduce the stub evaluation. LangSmith traces are also optional and are not used by the stub harness.
- Human ratings can vary between raters. They complement the automatic harness and the AI judge; they are not a substitute for the stub 30/30 result.
- `tokyo_airport_cost_scale` may print a cost-scale warning without failing the case.
- TACC jobs expire after the partition limit (1 hour). Leftover vLLM processes on a node can also hold GPU memory and block later jobs; cancel your own jobs when finished.
- Do not commit `.env`, secrets, `.venv`, or `node_modules`.

Further detail lives in [`eval/README.md`](./eval/README.md), [`tacc/README.md`](./tacc/README.md), and the per-agent README files under `agents/`.
