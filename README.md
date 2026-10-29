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

## Run local (Windows)

From PowerShell:

```powershell
cd C:\dev\trip-planning-agent

# 1. Env file (fill TACC_* when you have course credentials; stubs work with blanks)
copy .env.example .env

# 2. Virtualenv + deps
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# If Activate.ps1 is blocked:
# Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 3. Start backend
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Check:
- Health: http://127.0.0.1:8000/health  (expect `"ok": true`)
- API docs: http://127.0.0.1:8000/docs
- Frontend placeholder: open `frontend\index.html` in a browser

Stop the server with `Ctrl+C` in that terminal.

### Key `.env` knobs
| Variable | Notes |
|----------|--------|
| `TACC_MODEL_ENDPOINT` / `TACC_API_KEY` / `TACC_MODEL` | Course model-serving; leave blank for stub |
| `ENABLE_TRAVEL_HISTORY` | `1` = proposed (Agent1–4); `0` = Baseline A (Agent1–3) |
| `TOOL_STAYS_MODE` / `TOOL_MAPS_MODE` | `stub` or `api` |
| `DATABASE_URL` | Default SQLite under `./data/` |
| `LANGFUSE_*` | Optional observability (`LANGFUSE_ENABLED=1`) |

UI is not hosted on TACC; only the backend calls the course model-serving endpoint (request → queue → worker).
