"""Minimal FastAPI backend that wires agents + TACC client stub."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.coordinator import run as coordinate
from agents.coordinator.agent import health as coordinator_health
from agents.estimate_transport.agent import health as transport_health
from agents.search_stays.agent import health as stays_health
from agents.search_stays.agent import run as search_stays_run
from agents.travel_history.agent import health as history_health
from config.settings import get_settings
from shared.schemas import Itinerary, StayCandidate, TripRequest
from trip_planning_agent.tacc_client import TACCClient

app = FastAPI(title="trip-planning-agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {
        "ok": True,
        "enable_travel_history": s.enable_travel_history,
        "baseline_a": s.baseline_a,
        "tacc_configured": TACCClient(s).configured,
        "tool_stays_mode": s.tool_stays_mode,
        "tool_maps_mode": s.tool_maps_mode,
        "agents": {
            "search_stays": stays_health(),
            "estimate_transport": transport_health(),
            "coordinator": coordinator_health(),
            "travel_history": history_health(),
        },
    }


@app.post("/plan", response_model=Itinerary)
def plan(request: TripRequest) -> Itinerary:
    return coordinate(request)


@app.post("/agents/search_stays", response_model=list[StayCandidate])
def agent_search_stays(request: TripRequest) -> list[StayCandidate]:
    """Run Agent 1 alone (local testing / debugging)."""
    return search_stays_run(request)


def main() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run("backend.main:app", host=s.app_host, port=s.app_port, reload=True)


if __name__ == "__main__":
    main()