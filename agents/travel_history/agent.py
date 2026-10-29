"""Agent 4 — travel_history: previously visited locations (memory)."""

from __future__ import annotations

from typing import Any

from config.settings import get_settings
from shared.schemas import TripRequest


def run(request: TripRequest) -> list[str]:
    """Return previously visited place names for this user (stub list for now)."""
    settings = get_settings()
    if not settings.enable_travel_history:
        return []
    # Stub memory; later: read DATABASE_URL store keyed by request.user_id
    if not request.user_id:
        return []
    return [f"stub-visited-near-{request.destination}"]


def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "agent": "travel_history",
        "enabled": s.enable_travel_history,
        "database_url": s.database_url,
    }
