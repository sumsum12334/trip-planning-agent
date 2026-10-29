# Agent 1 - Search Stays

Finds accommodation under budget / near the user-specified destination.

## Role

- **Input:** `TripRequest` (`destination`, optional `budget`, `days`, `interests`, ...)
- **Output:** `list[StayCandidate]` (up to 5, cheapest first when costs exist)
- **Nightly cap:** `budget / days` if `days` is set, else `budget / 3` when budget is set

## Tool mode (`TOOL_STAYS_MODE`)

| Mode | Behavior |
|------|----------|
| `stub` (default) | Curated fake catalog; filter by nightly cap + location text overlap; generic fallback if no city match |
| `api` | Not wired - raises `NotImplementedError` (no fake API keys) |

## Layout

- `tools.py` - `search_stays(...)` tool + stub catalog
- `agent.py` - `run(request)` / `health()`; enriches notes with mode + filter rationale

## Local calls

Python (no server):

```powershell
cd C:\dev\trip-planning-agent
.\.venv\Scripts\python.exe -c "from shared.schemas import TripRequest; from agents.search_stays import run; print(run(TripRequest(destination='Tokyo', budget=400, days=4, interests=['food'])))"
```

HTTP (with backend running):

```powershell
# Start: .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/agents/search_stays -ContentType 'application/json' -Body '{"destination":"Tokyo","budget":400,"days":4,"interests":["food"]}'
```

Tests:

```powershell
.\.venv\Scripts\pytest.exe tests\test_search_stays.py -q
```