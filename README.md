# trip-planning-agent
CSIT6000V Course Project

## Architecture
<img width="3066" height="1746" alt="trip_agent_multiagent_overview" src="https://github.com/user-attachments/assets/c9eecec0-1fcf-442e-bbf3-e9a99719cfc7" />

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
| **Backend** | Session, orchestration, `/plan` + `/health` |
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
`TOOL_STAYS_MODE=api` fails explicitly until a real provider is configured.

Agent 4 uses `DATABASE_URL` and stores visits in the `travel_history`
table, keyed by `TripRequest.user_id`. It returns distinct places in
most-recent-first order and is disabled for Baseline A when
`ENABLE_TRAVEL_HISTORY=0`. Evaluation fixtures or application code can add a
visit through `TravelHistoryStore.record_visit`. Chat conversations remain on
local SQLite even when travel history points at Postgres.

#### Travel history database (`DATABASE_URL`)

| Backend | When to use | Connection |
|---------|-------------|------------|
| **SQLite (default)** | Local without Docker/cloud | `DATABASE_URL=sqlite:///./data/travel_history.sqlite` |
| **Postgres (Docker)** | Optional local Postgres | `docker compose up -d postgres`, then `DATABASE_URL=postgresql://trip:trip@localhost:5432/travel_history` |
| **Postgres (Neon)** | Course/cloud shared DB | Pooled `DATABASE_URL` from `.env` after `neon init` / `neon deploy` |

**Driver:** install once with `pip install ".[db]"` (pulls `psycopg[binary]`), or `pip install "psycopg[binary]"`.

**Neon:** this repo can be linked with Neon CLI (`neon init` / `neon deploy`). The app reads the pooled `DATABASE_URL` from `.env` (also `DATABASE_URL_UNPOOLED` and `NEON_BRANCH`). Refresh credentials with `neon env pull` (or re-run deploy). `.env` is gitignored — never commit real URLs or passwords; use placeholders in docs only.

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
`POST /api/chat/question`; it is not sent as an ordinary chat message.
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
`agents/chat_tools.py`. Tool results carry their mode (`stub`/`api`) and
provider failures are returned as labeled errors so one failing tool does not
abort the turn.

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
destination. Three modes are controlled by `TOOL_STAYS_MODE`:

| Mode | Source | Returns |
|------|--------|---------|
| `stub` | Curated local catalog | Name, location, nightly cost, phone, website, rating, amenities |
| `overpass` | OpenStreetMap Overpass API | Real names, coordinates, addresses, star ratings (no cost/availability) |
| `api` | OBO Travel MCP | Live nightly rates, booking URLs, star ratings, cancellation policy |

Set `TOOL_STAYS_MODE` in `.env` (default: `stub`). For `api` mode, also set
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
- `POST /api/chat` (accepts an optional `conversation_id`)
- `POST /api/chat/stream` (accepts an optional `request_id` used for cancellation and `plan_context`)
- `POST /api/chat/stop` (body `{"request_id": "..."}`; sets the turn's cancel event)
- `PUT /api/conversations/{conversation_id}/trip-plan` (persist edited `budget`, `currency`, and `budget_items` onto the latest plan)

## Run local (Windows)

From PowerShell:

```powershell
cd C:\dev\trip-planning-agent

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

For cloud Postgres (Neon), keep Docker Postgres off and set `DATABASE_URL` to
the pooled connection string in `.env` (see Travel history database above). Do
not put real Neon passwords in the README or git.

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
| `ENABLE_TRAVEL_HISTORY` | `1` = proposed (Agent1–4); `0` = Baseline A (Agent1–3) |
| `TOOL_STAYS_MODE` | `stub` (default, offline-safe), `overpass` (OpenStreetMap, no auth), `api` (OBO Travel, live prices) |
| `TOOL_MAPS_MODE` | `stub` or `api` |
| `GEOCODING_ENABLED` | Set to `1` to resolve Overpass destinations with rate-limited Nominatim geocoding |
| `STAYS_API_BASE_URL` | OBO Travel MCP base URL, e.g. `https://onebookingonline.com/mcp` (used when `TOOL_STAYS_MODE=api`) |
| `STAYS_API_KEY` | Optional OBO Travel API key for higher rate limits |
| `STAYS_API_TIMEOUT` | Request timeout seconds (default 30) |
| `OVERPASS_API_URL` | Comma-separated Overpass mirror URLs (used when `TOOL_STAYS_MODE=overpass`) |
| `OVERPASS_TIMEOUT` | Overpass request timeout seconds (default 30) |
| `OVERPASS_RADIUS_METERS` | Overpass search radius in meters (default 5000) |
| `DATABASE_URL` | Travel history DB. Default SQLite: `sqlite:///./data/travel_history.sqlite`. Local Docker Postgres: `postgresql://trip:trip@localhost:5432/travel_history` (`pip install ".[db]"`, `docker compose up -d postgres`). Neon: pooled URL from `.env` after `neon init` / `neon deploy` (refresh with `neon env pull`). Chat stays on SQLite. `GET /health` → `agents.travel_history.storage` = `sqlite` \| `postgres`. |
| `DATABASE_URL_UNPOOLED` | Optional Neon direct URL (migrations/admin). App runtime uses pooled `DATABASE_URL`. |
| `NEON_BRANCH` | Optional Neon branch name (e.g. `production`) when using Neon. |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | Langfuse 5.x credentials and host |
| `LANGFUSE_ENABLED` | Set to `1` to emit flushed model-generation traces |
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

UI is not hosted on TACC; only the backend calls the course model-serving endpoint (request → queue → worker).

### Deploy to TACC

The repository includes a self-contained deployment package in
[`tacc/`](./tacc/). It does not depend on `tacc_reference`. Submit
[`tacc/qwen-public-serve/`](./tacc/qwen-public-serve/) first, copy its
`SERVICE_BASE_URL` into [`server-url.txt`](./server-url.txt), then submit the
repository root using [`tuxiv.conf`](./tuxiv.conf). See
[`tacc/README.md`](./tacc/README.md) for the complete sequence.

## Evaluation (Baseline A vs Proposed)

Langfuse is optional tracing only. To score the agents, run the fixed-case harness:

```powershell
.\.venv\Scripts\python.exe -m eval.runner
```

See [`eval/README.md`](./eval/README.md). The suite compares Baseline A (`ENABLE_TRAVEL_HISTORY=0`) with Proposed (`ENABLE_TRAVEL_HISTORY=1`) on stay budget/location, transport fields, and history avoidance. Stub mode is offline by default; `--mode api` uses the configured QWEN endpoint and requires `QWEN_BASE_URL` (or `--model-url`).

