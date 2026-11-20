"""Tool schemas and executors for the chat model's sub-agent tools.

These wrap the existing agent modules (Agent 1 `search_stays`, Agent 2
`estimate_transport`, and the optional `web_search`) so the chat model can call
them during a turn. Provider failures are returned as labeled error results so a
single failed tool does not abort the whole turn.

Weather is intentionally NOT a chat tool: the trip-plan UI integrates it
directly (per-day forecasts via POST /agents/weather), so the model neither
calls nor fabricates forecasts.
"""

from __future__ import annotations

from typing import Any

import httpx

from agents.estimate_transport.agent import run as estimate_transport_run
from agents.search_stays.agent import run as search_stays_run
from agents.web_search.agent import run as web_search_run
from config.settings import get_settings
from shared.schemas import TripRequest

AGENT_TOOL_NAMES = {"search_stays", "estimate_transport", "web_search"}

AGENT_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_stays",
            "description": (
                "Search accommodation candidates for a destination, optionally under "
                "a total budget and number of nights. Results may come from a stub "
                "catalog in local development; label them accordingly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string"},
                    "budget": {"type": "number", "description": "Optional total trip budget."},
                    # No fixed day limit (proposal scope); requests of any
                    # length are accepted and rendered one day per day.
                    "days": {"type": "integer", "minimum": 1},
                    "interests": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estimate_transport",
            "description": (
                "Estimate travel time and cost between two places. Values may be "
                "stubs in local development; label them as estimates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_place": {"type": "string"},
                    "to_place": {"type": "string"},
                    "mode": {"type": "string", "description": "Optional travel mode hint."},
                },
                "required": ["from_place", "to_place"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for travel information. Results are not verified live "
                "availability and may be a local stub."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
        },
    },
]


def _optional_int(value: Any, *, minimum: int, maximum: int | None = None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = max(minimum, int(value))
    if maximum is not None:
        result = min(maximum, result)
    return result


def _clean_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item).strip())]


def execute_agent_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Run one sub-agent tool. Raises ValueError for invalid arguments."""
    if not isinstance(arguments, dict):
        raise ValueError(f"{name} requires an object of arguments.")

    if name == "search_stays":
        destination = str(arguments.get("destination", "")).strip()
        if not destination:
            raise ValueError("search_stays requires a destination.")
        request = TripRequest(
            destination=destination,
            budget=arguments.get("budget"),
            days=_optional_int(arguments.get("days"), minimum=1),
            interests=_clean_strings(arguments.get("interests")),
            start_date=arguments.get("check_in"),
            end_date=arguments.get("check_out"),
        )
        try:
            stays = search_stays_run(request)
        except NotImplementedError as error:
            return {"mode": "api", "error": str(error), "stays": []}
        return {"mode": get_settings().tool_stays_mode, "stays": [stay.model_dump() for stay in stays]}

    if name == "estimate_transport":
        from_place = str(arguments.get("from_place", "")).strip()
        to_place = str(arguments.get("to_place", "")).strip()
        if not from_place or not to_place:
            raise ValueError("estimate_transport requires from_place and to_place.")
        try:
            leg = estimate_transport_run(
                TripRequest(destination=from_place), from_place, to_place
            )
        except NotImplementedError as error:
            return {
                "mode": "unavailable",
                "error": f"Transport provider unavailable: {error}",
                "from_place": from_place,
                "to_place": to_place,
            }
        result = leg.model_dump()
        if arguments.get("mode"):
            result["mode_hint"] = str(arguments["mode"])
        return result

    if name == "web_search":
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("web_search requires a query.")
        limit = _optional_int(arguments.get("limit"), minimum=1, maximum=10) or 5
        mode = get_settings().web_search_mode
        try:
            results = web_search_run(query, limit=limit)
        except httpx.HTTPError as error:
            return {"mode": mode, "error": f"Web search failed: {error}", "results": []}
        return {"mode": mode, "results": [result.model_dump() for result in results]}

    raise ValueError(f"Unknown agent tool requested: {name}")
