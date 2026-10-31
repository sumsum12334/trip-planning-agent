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
   stay search       maps / distance    SQLite / memory
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
The web UI exposes agent activity (coordinator lifecycle, model request
preparation, agent steps,
model calls, thinking status, results, and errors) without displaying private
chain-of-thought. "Thinking" is represented by safe execution status rather
than hidden model reasoning.

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
SQLite conversations and travel-history data remain on the host and survive
container recreation. Open http://localhost:8000/. Docker is only for local
development and is not the TACC deployment mechanism.
The optional `QWEN_BASE_URL` can point to a running course service, or remain
blank to use local stub responses.

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
| `QWEN_BASE_URL` / `QWEN_MODEL` / `QWEN_API_KEY` | Course Qwen OpenAI-compatible endpoint, model, and API key |
| `ENABLE_TRAVEL_HISTORY` | `1` = proposed (Agent1–4); `0` = Baseline A (Agent1–3) |
| `TOOL_STAYS_MODE` / `TOOL_MAPS_MODE` | `stub` or `api` |
| `DATABASE_URL` | Default SQLite under `./data/` |
| `LANGFUSE_*` | Optional observability (`LANGFUSE_ENABLED=1`) |

UI is not hosted on TACC; only the backend calls the course model-serving endpoint (request → queue → worker).

### Deploy to TACC

The repository includes a self-contained deployment package in
[`tacc/`](./tacc/). It does not depend on `tacc_reference`. Submit
[`tacc/qwen-public-serve/`](./tacc/qwen-public-serve/) first, copy its
`SERVICE_BASE_URL` into [`server-url.txt`](./server-url.txt), then submit the
repository root using [`tuxiv.conf`](./tuxiv.conf). See
[`tacc/README.md`](./tacc/README.md) for the complete sequence.
