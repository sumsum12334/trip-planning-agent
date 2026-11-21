"""FastAPI backend for trip planning and the browser UI."""

from __future__ import annotations

import json
import queue
import threading
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from agents.chat_tools import (
    AGENT_TOOL_NAMES,
    AGENT_TOOL_SCHEMAS,
    execute_agent_tool,
)
from agents.coordinator import revise as revise_plan
from agents.coordinator import run as coordinate
from agents.coordinator.agent import NoFeasiblePlanError, health as coordinator_health
from agents.estimate_transport.agent import health as transport_health
from agents.search_stays.agent import health as stays_health
from agents.search_stays.agent import run as search_stays_run
from agents.travel_history.agent import health as history_health
from agents.travel_history.agent import remember_from_message
from agents.travel_history.agent import TravelHistoryStore
from agents.web_search.agent import health as web_search_health
from agents.web_search import run as web_search
from agents.weather.agent import health as weather_health
from agents.weather.agent import run as weather_run
from config.settings import get_model_config, get_settings, update_model_config
from shared.schemas import (
    ChatEvent,
    ChatStopRequest,
    StayCandidate,
    TransportLeg,
    EstimateTransportRequest,
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    ConversationSummary,
    Itinerary,
    ModelSettingsResponse,
    ModelSettingsUpdate,
    PlanReviseRequest,
    TripRequest,
    TravelHistoryCreate,
    TravelHistoryEntry,
    TripPlanUpdate,
    WebSearchRequest,
)
from shared.prompts import TRIP_PLANNING_SYSTEM_PROMPT
from shared.trip_plan import (
    TRIP_PLAN_TOOL_NAMES,
    TRIP_PLAN_TOOLS,
    TRIP_PLAN_UI_TOOL,
    apply_trip_plan_tool,
    assemble_trip_plan,
    format_plan_context,
)
from trip_planning_agent.tacc_client import TACCClient
from trip_planning_agent.cancellation import clear as clear_cancel
from trip_planning_agent.cancellation import register as register_cancel
from trip_planning_agent.cancellation import request_stop
from trip_planning_agent.conversation_store import ConversationStore
from trip_planning_agent.observability import (
    end_trace,
    start_trace,
    trace_context_for,
    ls_create_run,
    ls_update_generation,
)

app = FastAPI(title="trip-planning-agent", version="0.1.0")
# The shipped UI is served same-origin from this app, so cross-origin access
# is only needed for the Vite dev server and local tooling. Note "testclient"
# is the client address FastAPI's TestClient reports; it is localhost-equivalent.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|testclient)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Model-settings changes repoint the shared model endpoint, so they are only
# accepted from the local machine (see update_model_settings).
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}

# Cooperative cancellation for in-flight streaming turns lives in
# trip_planning_agent.cancellation. The client sends a `request_id` with the
# stream and can call POST /api/chat/stop to set its event; the streaming loop
# and the model client check the event between deltas.


def _apply_trip_plan_tool(
    store: ConversationStore, conversation_id: str, name: str, arguments: dict[str, Any]
) -> tuple[Any, dict[str, Any] | None]:
    """Apply one trip-plan tool, persist the plan, and return (result, ui_plan).

    Invalid arguments return a labeled error result (with no UI plan) so the
    model can correct itself instead of failing the whole turn.
    """
    plan = store.get_trip_plan(conversation_id)
    try:
        new_plan, model_result = apply_trip_plan_tool(name, arguments, plan)
    except ValueError as error:
        return {"ok": False, "tool": name, "error": str(error)}, None
    if name == "get_trip_plan":
        # Reading the plan does not change the UI.
        return model_result, None
    store.save_trip_plan(conversation_id, new_plan)
    return model_result, assemble_trip_plan(new_plan)


def _trip_plan_event(name: str, ui_plan: dict[str, Any]) -> ChatEvent:
    """Build the UI event that renders the currently assembled trip plan."""
    return ChatEvent(
        type="tool",
        label=f"Trip plan updated ({name})",
        status="completed",
        data={"tool": TRIP_PLAN_UI_TOOL, "result": ui_plan, "action": name},
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
        "weather_mode": s.weather_mode,
        "agents": {
            "search_stays": stays_health(),
            "estimate_transport": transport_health(),
            "coordinator": coordinator_health(),
            "travel_history": history_health(),
            "web_search": web_search_health(),
            "weather": weather_health(),
        },
    }


@app.post("/plan", response_model=Itinerary)
def plan(request: TripRequest) -> Itinerary:
    try:
        return coordinate(request, session_id=f"plan-{uuid.uuid4()}")
    except NoFeasiblePlanError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/plan/revise", response_model=Itinerary)
def plan_revise(body: PlanReviseRequest) -> Itinerary:
    """Revise loop: re-run the agent pipeline for changed budget/dates/interests.

    The agents execute again (travel history, stay search, cost check, render)
    instead of appending ad-hoc chat text; the response notes what changed.
    """
    try:
        return revise_plan(
            body.request,
            body.itinerary,
            session_id=f"plan-revise-{uuid.uuid4()}",
        )
    except NoFeasiblePlanError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/agents/search_stays", response_model=list[StayCandidate])
def agent_search_stays(request: TripRequest) -> list[StayCandidate]:
    """Direct Agent 1 stay search (stub catalog or configured provider)."""
    from agents.search_stays.agent import run as search_stays_run

    return search_stays_run(request)


@app.post("/agents/estimate_transport", response_model=TransportLeg)
def agent_estimate_transport(body: EstimateTransportRequest) -> TransportLeg:
    """Direct Agent 2 transport estimate (stub catalog or configured maps API)."""
    from agents.estimate_transport.agent import run as estimate_transport_run

    destination = body.destination or body.to_place
    request = TripRequest(
        destination=destination,
        origin=body.origin,
        days=body.days,
        budget=body.budget,
        interests=body.interests,
    )
    try:
        return estimate_transport_run(request, body.from_place, body.to_place)
    except NotImplementedError as error:
        raise HTTPException(
            status_code=503,
            detail=f"estimate_transport is unavailable in api mode: {error}",
        ) from error


@app.post("/agents/weather")
def agent_weather(request: TripRequest) -> dict:
    """Direct weather tool for a destination."""
    return weather_run(request.destination, request.start_date.isoformat() if request.start_date else None, request.end_date.isoformat() if request.end_date else None)





@app.get("/api/travel-history", response_model=list[TravelHistoryEntry])
def list_travel_history(
    user_id: str = Query(default="local-user", min_length=1, max_length=200),
) -> list[TravelHistoryEntry]:
    store = TravelHistoryStore(get_settings().database_url)
    return [TravelHistoryEntry(**entry) for entry in store.list_entries(user_id, fresh=True)]


@app.post("/api/travel-history", response_model=TravelHistoryEntry, status_code=201)
def add_travel_history(request: TravelHistoryCreate) -> TravelHistoryEntry:
    store = TravelHistoryStore(get_settings().database_url)
    entry_id = store.add_entry(
        user_id=request.user_id,
        country=request.country,
        city=request.city,
        location=request.location,
    )
    entry = next(
        item for item in store.list_entries(request.user_id) if item["id"] == entry_id
    )
    return TravelHistoryEntry(**entry)


@app.delete("/api/travel-history/{entry_id}", status_code=204)
def delete_travel_history(
    entry_id: int,
    user_id: str = Query(default="local-user", min_length=1, max_length=200),
) -> None:
    if not TravelHistoryStore(get_settings().database_url).delete(user_id, entry_id):
        raise HTTPException(status_code=404, detail="Travel-history entry not found.")


@app.put("/api/travel-history/{entry_id}", response_model=TravelHistoryEntry)
def update_travel_history(
    entry_id: int,
    request: TravelHistoryCreate,
    user_id: str = Query(default="local-user", min_length=1, max_length=200),
) -> TravelHistoryEntry:
    """Update a travel history entry (e.g., country, city, location)."""
    store = TravelHistoryStore(get_settings().database_url)
    # First check if entry exists and belongs to user
    existing = store.get(user_id, entry_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Travel-history entry not found.")
    # Update the entry
    store.update(entry_id, user_id, request.country, request.city, request.location)
    # Return updated entry
    updated = store.get(user_id, entry_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Travel-history entry not found after update.")
    return TravelHistoryEntry(**updated)


@app.get("/api/settings")
def public_settings() -> dict:
    s = get_settings()
    client = TACCClient(s)
    model_config = get_model_config(s)
    return {
        "qwen_configured": client.configured,
        "qwen_model": client.model,
        "endpoint_url": model_config["base_url"],
        "api_key_configured": bool(model_config["api_key"]),
        "enable_travel_history": s.enable_travel_history,
        "reconsider_prompt_enabled": s.reconsider_prompt_enabled,
        "tool_stays_mode": s.tool_stays_mode,
        "tool_maps_mode": s.tool_maps_mode,
        "web_search_mode": s.web_search_mode,
        "default_origin": s.default_origin,
    }


@app.post("/api/tools/web-search")
def search_web(request: WebSearchRequest) -> dict:
    """Run the optional web-search tool for development and agent testing."""
    try:
        results = web_search(request.query, limit=request.limit)
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="Web search provider failed.") from error
    return {
        "query": request.query,
        "mode": get_settings().web_search_mode,
        "results": [result.model_dump() for result in results],
    }


@app.put("/api/settings/model", response_model=ModelSettingsResponse)
def update_model_settings(
    request: ModelSettingsUpdate, http_request: Request
) -> ModelSettingsResponse:
    client_host = (http_request.client.host if http_request.client else "") or ""
    if client_host not in _LOCAL_HOSTS:
        raise HTTPException(
            status_code=403,
            detail="Model settings can only be changed from the local machine.",
        )
    endpoint = request.endpoint_url.strip()
    if endpoint:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(
                status_code=422,
                detail="Endpoint URL must be an absolute http:// or https:// URL.",
            )
    update_model_config(
        base_url=endpoint,
        model=request.model.strip(),
        api_key=request.api_key,
    )
    model_config = get_model_config()
    return ModelSettingsResponse(
        endpoint_url=model_config["base_url"],
        model=model_config["model"],
        api_key_configured=bool(model_config["api_key"]),
    )


@app.post("/api/chat/stop")
def stop_chat(request: ChatStopRequest) -> dict:
    """Cooperatively stop a streaming turn started with the same request_id."""
    return {
        "request_id": request.request_id,
        "stopped": request_stop(request.request_id),
    }


def _looks_like_trip_request(message: str) -> bool:
    """Heuristic: does the user message read like a trip-planning request?"""
    lowered = message.lower().strip()
    if not lowered:
        return False
    greetings = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening", "yo", "sup"}
    if lowered in greetings:
        return False
    trip_keywords = (
        "plan", "trip", "visit", "travel", "go to", "flight", "hotel",
        "stay", "itinerary", "vacation", "holiday", "destination", "tour",
    )
    return any(kw in lowered for kw in trip_keywords)


def _run_multi_agent_plan(
    request_message: str,
    session_id: str,
    user_id: str,
    trace_context: dict | None,
    stream_queue: "queue.Queue[tuple[str, object]]",
) -> dict | None:
    """Run the multi-agent coordinator pipeline and stream agent events.

    Emits SSE agent events for Travel History → Stay Search → Transport Estimate → Coordinator
    so the Live workflow panel shows each agent working. Returns a dict with
    the itinerary (or an error) for the ``done`` frame.
    """
    from shared.schemas import TripRequest
    from agents.estimate_transport import run as estimate_transport

    def _emit(agent: str, label: str, status: str, detail: str = "", data: dict | None = None) -> None:
        stream_queue.put(("event", {
            "type": "agent",
            "label": label,
            "status": status,
            "detail": detail,
            "data": data or {},
        }))

    _emit("travel_history", "Travel History Agent", "running", "Checking travel history")
    _emit("search_stays", "Stay Search Agent", "running", "Searching accommodations")
    _emit("estimate_transport", "Transport Estimate Agent", "running", "Estimating transport")
    _emit("coordinate", "Coordinator Agent", "running", "Building itinerary")

    # Extract destination city from message (e.g. "Plan a trip to Tokyo" -> "Tokyo")
    import re as _re
    dest_caps = _re.findall(r'\b[A-Z][a-z]+\b', request_message)
    dest_city = dest_caps[-1] if dest_caps else request_message.strip()

    # Extract number of days from message (e.g. "3-day trip", "5 days")
    days = None
    day_match = _re.search(r'(\d+)\s*[- ]?day', request_message, _re.IGNORECASE)
    if day_match:
        days = int(day_match.group(1))

    # Extract budget from message (e.g. "$2000", "budget of $1500")
    # Require the dollar sign so we don't accidentally match day counts like "3-day"
    budget = None
    budget_match = _re.search(r'(?:budget\s+(?:of\s+)?)?\$(\d[\d,]*)', request_message)
    if budget_match:
        budget = float(budget_match.group(1).replace(",", ""))

    trip_request = TripRequest(
        destination=dest_city,
        user_id=user_id,
        budget=budget,
        days=days,
        interests=[],
    )

    try:
        # Step 1: Travel History
        from agents.travel_history import run as travel_history
        visited = travel_history(trip_request)
        _emit("travel_history", "Travel History Agent", "completed", "History checked", {})

        # Step 2: Stay Search
        from agents.search_stays import run as search_stays
        excluded = visited if trip_request.avoid_visited else []
        stays = search_stays(trip_request, excluded_locations=excluded)
        stay_count = len(stays)
        _emit("search_stays", "Stay Search Agent", "completed", f"{stay_count} stays evaluated", {})

        # Step 3: Transport Estimate (origin to destination)
        origin = trip_request.origin or trip_request.destination
        transport = estimate_transport(trip_request, origin, dest_city)
        _emit("estimate_transport", "Transport Estimate Agent", "completed", f"Arrival via {transport.mode or 'transport'}", {})

        # Step 4: Coordinator
        itinerary = coordinate(trip_request, session_id=session_id)

        cost = itinerary.total_estimated_cost or 0
        currency = itinerary.currency or ""

        _emit("coordinate", "Coordinator Agent", "completed", f"Itinerary ready: {currency}{cost}", {})

        # Emit display_trip_plan event so the frontend can render the trip plan
        from shared.trip_plan import assemble_trip_plan

        # Build a UI-compatible plan dict from the Itinerary model.
        # assemble_trip_plan expects top-level destination/budget, but Itinerary
        # nests them in request/total_estimated_cost, so we map them explicitly.
        plan_dict = {
            "destination": itinerary.request.destination,
            "destination_coordinates": itinerary.destination_coordinates,
            "airport": itinerary.airport,
            "start_date": itinerary.request.start_date,
            "currency": itinerary.currency or "",
            "budget": itinerary.total_estimated_cost,
            "budget_items": [],
            "days": [
                {
                    "day": day.day_index,
                    "title": f"Day {day.day_index}",
                    "activities": list(day.pois),
                    "notes": [],
                    "coordinates": day.coordinates,
                    "places": day.places or [],
                    "stays": [
                        {
                            "name": s.name,
                            "location": s.location or "",
                            "nightly_cost": s.nightly_cost,
                            "currency": s.currency,
                            "rating": s.rating,
                            "amenities": s.amenities or [],
                            "source_url": s.source_url,
                            "coordinates": s.coordinates,
                        }
                        for s in (day.stays or [])
                    ],
                    "budget": day.estimated_cost,
                    "budget_items": [],
                }
                for day in itinerary.days
            ],
            "notes": list(itinerary.notes),
            "references": [],
            "status": "displayed",
        }
        ui_plan = assemble_trip_plan(plan_dict)
        _emit("display_trip_plan", "Trip plan updated", "completed", f"Plan ready for {itinerary.request.destination}", {
            "tool": "display_trip_plan",
            "result": ui_plan,
            "action": "display_trip_plan",
        })

        return {
            "kind": "itinerary",
            "itinerary": itinerary.model_dump(mode="json"),
            "text": _format_itinerary_summary(itinerary),
        }
    except NoFeasiblePlanError as error:
        _emit("coordinate", "Coordinator Agent", "error", str(error), {})
        return {"kind": "error", "message": str(error)}


def _format_itinerary_summary(itinerary: Any) -> str:
    """Build a plain-text summary of the itinerary for the chat bubble."""
    lines = [f"✈️ {itinerary.request.destination} — {len(itinerary.days)} day(s)"]
    if itinerary.currency and itinerary.total_estimated_cost is not None:
        lines.append(f"💰 Estimated total: {itinerary.currency}{itinerary.total_estimated_cost}")
    for day in itinerary.days:
        lines.append(f"\n**Day {day.day_index}**")
        for stay in (day.stays or []):
            lines.append(f"  🏨 {stay.name} — {stay.nightly_cost} {stay.currency or ''}/night")
        for leg in (day.transports or []):
            lines.append(f"  🚗 {leg.mode or 'transport'} — {leg.cost} {leg.currency or ''}")
    if itinerary.notes:
        lines.append(f"\n📝 {' | '.join(itinerary.notes[:3])}")
    return "\n".join(lines)


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    store = ConversationStore(get_settings().database_url)
    conversation = list(request.conversation[-20:])
    plan_context = format_plan_context(request.plan_context)
    prompt = request.message
    if conversation:
        prompt = "\n".join(
            f"{item.get('role', 'user')}: {item.get('content', '')}" for item in conversation
        ) + f"\nuser: {request.message}"
    if plan_context:
        prompt = f"{plan_context}\n\n{prompt}"
    conversation.append({"role": "user", "content": request.message})
    conversation_id = store.save(request.conversation_id, conversation, [])
    memory_user_id = request.user_id or conversation_id
    remembered_places = remember_from_message(memory_user_id, request.message)
    history_store = TravelHistoryStore(get_settings().database_url)
    # Surface known places from the in-process cache (database only on a cache
    # miss or after writes). Do not require a history tool call on every plan.
    known_places = (
        history_store.list_places(memory_user_id)[:20]
        if get_settings().enable_travel_history
        else []
    )
    if known_places:
        prompt = (
            "Known travel history for this user (already loaded; do not call "
            "search_travel_history just to re-read this list): "
            + ", ".join(known_places)
            + "\n\n"
            + prompt
        )
    history_tools = [{
        "type": "function",
        "function": {
            "name": "search_travel_history",
            "description": "Filter or refresh the user's saved travel history for a destination or place. Use only when known history was not already provided, or a filtered lookup is needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Destination, city, country, or location to search for.",
                    },
                },
                "required": ["query"],
            },
        },
    }, {
        "type": "function",
        "function": {
            "name": "ask_user_question",
            "description": "Ask the user a focused clarification question with selectable options when a planning decision is needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "A concise question for the user."},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 6,
                        "description": "Two to six concise selectable answers.",
                    },
                },
                "required": ["question", "options"],
            },
        },
    }, *TRIP_PLAN_TOOLS, *AGENT_TOOL_SCHEMAS]

    def execute_history_tool(name: str, arguments: dict[str, Any]) -> Any:
        if name == "search_travel_history":
            return history_store.search(memory_user_id, str(arguments.get("query", "")))
        if name == "ask_user_question":
            question = str(arguments.get("question", "")).strip()
            options = [str(option).strip() for option in arguments.get("options", [])]
            if not question or len(options) < 2 or any(not option for option in options):
                raise ValueError("ask_user_question requires a question and at least two options.")
            return {"question": question, "options": options[:6], "status": "awaiting_user"}
        if name in AGENT_TOOL_NAMES:
            return execute_agent_tool(name, arguments)
        raise ValueError(f"Unknown tool requested: {name}")

    def events():
        activity: list[ChatEvent] = []
        initial_events: list[ChatEvent] = [
            ChatEvent(type="agent", label="Coordinator agent started", status="running")
        ]
        if remembered_places:
            initial_events.append(
                ChatEvent(
                    type="agent",
                    label="Travel history updated",
                    detail=", ".join(remembered_places),
                    status="completed",
                )
            )
        def emit(event: ChatEvent) -> str:
            activity.append(event)
            return f"data: {json.dumps({'kind': 'event', **event.model_dump()})}\n\n"

        for event in initial_events:
            yield emit(event)
        yield emit(ChatEvent(type="model", label="Model request queued", status="running"))
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        client = TACCClient()
        trace = start_trace(
            name="chat.turn",
            input={
                "message": request.message,
                "history_turns": max(len(conversation) - 1, 0),
            },
            session_id=conversation_id,
            metadata={"stream": True, "model": client.model},
        )
        trace_finished = False
        stream_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        pending_question: dict[str, Any] | None = None
        cancel_event = register_cancel(request.request_id)
        cancelled = False

        def save_pause(messages: list[dict[str, Any]], result: dict[str, Any]) -> None:
            stream_queue.put(("pause", (messages, result)))

        def run_model() -> None:
            def tool_executor(name: str, arguments: dict[str, Any]) -> Any:
                if name in TRIP_PLAN_TOOL_NAMES:
                    model_result, ui_plan = _apply_trip_plan_tool(store, conversation_id, name, arguments)
                    if ui_plan is not None:
                        stream_queue.put(("event", _trip_plan_event(name, ui_plan).model_dump()))
                    return model_result
                try:
                    return execute_history_tool(name, arguments)
                except ValueError as error:
                    return {"ok": False, "tool": name, "error": str(error)}

            use_multi_agent = _looks_like_trip_request(request.message)

            # Build role-separated conversation messages for the model so that
            # LangSmith traces show clean user input (not mixed with prior model
            # outputs). The full history is passed via initial_messages; prompt
            # carries only the current user turn for clean tracing.
            initial_messages: list[dict[str, str]] = []
            if TRIP_PLANNING_SYSTEM_PROMPT:
                initial_messages.append(
                    {"role": "system", "content": TRIP_PLANNING_SYSTEM_PROMPT}
                )
            if known_places:
                initial_messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Known travel history for this user (already loaded; do not call "
                            "search_travel_history just to re-read this list): "
                            + ", ".join(known_places)
                        ),
                    }
                )
            if plan_context:
                initial_messages.append(
                    {"role": "system", "content": plan_context}
                )
            for item in conversation:
                role = item.get("role", "user")
                content = item.get("content", "")
                if role in ("user", "assistant", "system"):
                    initial_messages.append({"role": role, "content": content})
            initial_messages.append({"role": "user", "content": request.message})

            # --- Backend-side tool calling (Ollama/vLLM doesn't support tool calling) ---
            # Call tools directly and prepend results as context to the model prompt.
            tool_context_messages: list[dict[str, str]] = []
            import re as _re

            # Travel history search for trip-related messages
            if _looks_like_trip_request(request.message) or "weather" in request.message.lower():
                try:
                    ls_hist, hist_run_id = ls_create_run(
                        name="search_travel_history",
                        run_type="tool",
                        inputs={"query": request.message},
                        tags=["trip-planning-agent", "tool-call", "search_travel_history"],
                    )
                    history_results = history_store.search(memory_user_id, request.message)
                    if history_results:
                        places = [e["location"] for e in history_results if e.get("location")]
                        if places:
                            tool_context_messages.append({
                                "role": "system",
                                "content": f"Travel history for this user (past locations): {', '.join(places[:10])}. "
                                           f"Avoid repeating these unless specifically requested.",
                            })
                    ls_update_generation(
                        ls_hist,
                        output={"results": history_results},
                    )
                except Exception as e:
                    print(f"DEBUG Travel history tool failed: {e}", flush=True)
                    ls_hist = None
                    hist_run_id = None

            # Weather forecast when mentioned
            if "weather" in request.message.lower():
                try:
                    weather_dest = request.message.strip()
                    caps = _re.findall(r'\b[A-Z][a-z]+\b', weather_dest)
                    if caps:
                        weather_dest = caps[-1]
                    print(f"DEBUG Weather tool: calling weather_run('{weather_dest}')", flush=True)
                    ls_weather, weather_run_id = ls_create_run(
                        name="weather_run",
                        run_type="tool",
                        inputs={"query": weather_dest},
                        tags=["trip-planning-agent", "tool-call", "weather_run"],
                    )
                    weather_result = weather_run(weather_dest)
                    print(f"DEBUG Weather tool result: {weather_result}", flush=True)
                    ls_update_generation(
                        ls_weather,
                        output={"result": weather_result},
                    )
                    tool_context_messages.append({
                        "role": "system",
                        "content": f"Weather forecast for {weather_dest}: "
                                  f"{weather_result.get('condition', 'unknown')}, "
                                  f"{weather_result.get('temperature_c', '?')}°C, "
                                  f"{weather_result.get('notes', '')}",
                    })
                except Exception as e:
                    print(f"DEBUG Weather tool failed: {e}", flush=True)

            # Stay search for trip requests
            if _looks_like_trip_request(request.message):
                try:
                    stay_caps = _re.findall(r'\b[A-Z][a-z]+\b', request.message)
                    stay_dest = stay_caps[-1] if stay_caps else request.message.strip()
                    print(f"DEBUG Stay search tool: calling search_stays_run('{stay_dest}')", flush=True)
                    ls_stays, stays_run_id = ls_create_run(
                        name="search_stays",
                        run_type="tool",
                        inputs={"destination": stay_dest},
                        tags=["trip-planning-agent", "tool-call", "search_stays"],
                    )
                    stay_request = TripRequest(
                        destination=stay_dest,
                        user_id=request.user_id or conversation_id,
                        budget=None,
                        days=None,
                        interests=[],
                    )
                    stays = search_stays_run(stay_request)
                    print(f"DEBUG Stay search result: {len(stays)} stays", flush=True)
                    ls_update_generation(
                        ls_stays,
                        output={"stays": [s.model_dump() for s in stays]},
                    )
                    if stays:
                        stay_names = [s.name for s in stays[:5]]
                        tool_context_messages.append({
                            "role": "system",
                            "content": f"Available stays for {stay_dest}: {', '.join(stay_names)}.",
                        })
                except Exception as e:
                    print(f"DEBUG Stay search tool failed: {e}", flush=True)

            # Prepend tool context to initial_messages
            tool_context_messages.extend(initial_messages)
            initial_messages = tool_context_messages

            try:
                if use_multi_agent:
                    result = _run_multi_agent_plan(
                        request.message,
                        conversation_id,
                        request.user_id or conversation_id,
                        trace_context_for(trace),
                        stream_queue,
                    )
                    stream_queue.put(("done", result))
                else:
                    for delta in client.stream(
                        request.message,
                        system=TRIP_PLANNING_SYSTEM_PROMPT,
                        initial_messages=initial_messages,
                        tool_executor=tool_executor,
                        on_pause=save_pause,
                        session_id=conversation_id,
                        trace_context=trace_context_for(trace),
                        cancel_event=cancel_event,
                    ):
                        stream_queue.put(("delta", delta))
                    stream_queue.put(("done", None))
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                stream_queue.put(("error", error))

        threading.Thread(target=run_model, daemon=True).start()
        try:
            while True:
                if cancel_event.is_set():
                    cancelled = True
                    break
                try:
                    kind, payload = stream_queue.get(timeout=0.25)
                except queue.Empty:
                    continue
                if kind == "event":
                    yield emit(ChatEvent(**payload))
                    continue
                if kind == "error":
                    raise payload
                if kind == "pause":
                    pending_messages, question = payload
                    pending_question = question
                    store.save_pending_question(
                        conversation_id,
                        memory_user_id,
                        pending_messages,
                        question["question"],
                        question["options"],
                    )
                    continue
                if kind == "done":
                    cancelled = cancel_event.is_set()
                    if isinstance(payload, dict):
                        if payload.get("kind") == "itinerary":
                            itinerary = payload["itinerary"]
                            assistant_message = {"role": "assistant", "content": payload["text"]}
                            conversation_with_response = conversation + [assistant_message]
                            store.save(
                                conversation_id,
                                conversation_with_response,
                                [event.model_dump() for event in activity],
                            )
                            end_trace(trace, output=payload["text"])
                            trace_finished = True
                            yield (
                                f"data: {json.dumps({'kind': 'done', 'text': payload['text'], 'reasoning': '', 'model': 'coordinator-multi-agent', 'stub': False, 'conversation_id': conversation_id, 'pending_question': None, 'events': [event.model_dump() for event in activity], 'itinerary': itinerary})}\n\n"
                            )
                            return
                        if payload.get("kind") == "error":
                            yield emit(
                                ChatEvent(
                                    type="model",
                                    label="Multi-agent plan failed",
                                    detail=payload["message"],
                                    status="error",
                                )
                            )
                            end_trace(
                                trace,
                                output={"error": payload["message"]},
                                error=ValueError(payload["message"]),
                            )
                            trace_finished = True
                            yield (
                                f"data: {json.dumps({'kind': 'done', 'text': '', 'reasoning': '', 'model': 'coordinator-multi-agent', 'stub': False, 'conversation_id': conversation_id, 'pending_question': None, 'events': [event.model_dump() for event in activity]})}\n\n"
                            )
                            return
                    break
                delta = payload
                if delta["kind"] == "reasoning":
                    reasoning_parts.append(delta["text"])
                else:
                    text_parts.append(delta["text"])
                yield f"data: {json.dumps({'kind': delta['kind'], 'text': delta['text']})}\n\n"
            if cancelled:
                yield emit(
                    ChatEvent(
                        type="agent",
                        label="Stopped by user",
                        detail="The response was stopped before it completed.",
                        status="completed",
                    )
                )
                stopped_message = {
                    "role": "assistant",
                    "content": "".join(text_parts) or "[Stopped] The response was stopped.",
                    "reasoning": "".join(reasoning_parts),
                }
                store.save(
                    conversation_id,
                    conversation
                    if pending_question is not None
                    else conversation + [stopped_message],
                    [event.model_dump() for event in activity],
                )
                end_trace(trace, output="".join(text_parts) or {"status": "stopped"})
                trace_finished = True
                yield (
                    f"data: {json.dumps({'kind': 'done', 'stopped': True, 'text': ''.join(text_parts), 'reasoning': ''.join(reasoning_parts), 'model': client.model, 'stub': not client.configured, 'conversation_id': conversation_id, 'pending_question': pending_question, 'events': [event.model_dump() for event in activity]})}\n\n"
                )
                return
            if not "".join(text_parts).strip() and pending_question is None:
                yield emit(
                    ChatEvent(
                        type="model",
                        label="Model returned an empty response",
                        detail="The model finished without content. Please retry or rephrase.",
                        status="error",
                    )
                )
                text_parts = [
                    "[The model returned an empty response. Please retry or rephrase "
                    "your request.]"
                ]
            yield emit(
                ChatEvent(
                    type="agent",
                    label="Coordinator agent completed",
                    status="completed",
                )
            )
            assistant_message = {"role": "assistant", "content": "".join(text_parts)}
            if reasoning_parts:
                assistant_message["reasoning"] = "".join(reasoning_parts)
            conversation_with_response = (
                conversation if pending_question is not None
                else conversation + [assistant_message]
            )
            store.save(
                conversation_id,
                conversation_with_response,
                [event.model_dump() for event in activity],
            )
            final_text = "".join(text_parts)
            if final_text:
                trace_output: Any = final_text
            elif pending_question is not None:
                trace_output = {
                    "status": "awaiting_user",
                    "question": pending_question.get("question", ""),
                }
            else:
                trace_output = {"text": ""}
            end_trace(trace, output=trace_output)
            trace_finished = True
            yield (
                f"data: {json.dumps({'kind': 'done', 'text': final_text, 'reasoning': ''.join(reasoning_parts), 'model': client.model, 'stub': not client.configured, 'conversation_id': conversation_id, 'pending_question': pending_question, 'events': [event.model_dump() for event in activity]})}\n\n"
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            end_trace(
                trace,
                output="".join(text_parts) or {"error": str(error)},
                error=error,
            )
            trace_finished = True
            failure = ChatEvent(
                type="model",
                label="Model request failed",
                detail=str(error),
                status="error",
            )
            agent_failure = ChatEvent(
                type="agent",
                label="Coordinator agent failed",
                status="error",
            )
            failed_conversation = conversation
            if text_parts or reasoning_parts:
                failed_conversation = conversation + [
                    {
                        "role": "assistant",
                        "content": "".join(text_parts)
                        or "The model response was interrupted. Please retry.",
                        "reasoning": "".join(reasoning_parts),
                    }
                ]
            store.save(
                conversation_id,
                failed_conversation,
                [event.model_dump() for event in activity]
                + [failure.model_dump(), agent_failure.model_dump()],
            )
            yield f"data: {json.dumps({'kind': 'error', 'message': 'The model request failed. The user message was saved and can be retried.', 'conversation_id': conversation_id, 'events': [failure.model_dump(), agent_failure.model_dump()]})}\n\n"
        finally:
            clear_cancel(request.request_id, cancel_event)
            if not trace_finished:
                end_trace(
                    trace,
                    output="".join(text_parts) or {"text": ""},
                )

    return StreamingResponse(events(), media_type="text/event-stream")


def _prepare_question_continuation(request: ChatRequest) -> dict[str, Any]:
    """Validate a paused-question answer and build the continuation context.

    Shared by the non-streaming and streaming continuation endpoints so both
    enforce the same conversation/user/option checks and expose the same tool
    set. The returned dict carries the store, pending record, messages, tool
    executor, activity events, model client, and Langfuse trace.
    """
    if not request.conversation_id:
        raise HTTPException(status_code=400, detail="A conversation_id is required.")
    store = ConversationStore(get_settings().database_url)
    pending = store.get_pending_question(request.conversation_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="No question is waiting for this conversation.")
    if pending["user_id"] != request.user_id:
        raise HTTPException(status_code=422, detail="Choose one of the displayed question options.")
    if not request.custom and request.message not in pending["options"]:
        raise HTTPException(status_code=422, detail="Choose one of the displayed question options.")

    history_store = TravelHistoryStore(get_settings().database_url)
    tools = [{
        "type": "function",
        "function": {
            "name": "search_travel_history",
            "description": "Filter or refresh the user's saved travel history for a destination or place. Use only when known history was not already provided, or a filtered lookup is needed.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }, {
        "type": "function",
        "function": {
            "name": "ask_user_question",
            "description": "Ask the user a focused clarification question with selectable options when a planning decision is needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
                },
                "required": ["question", "options"],
            },
        },
    }, *TRIP_PLAN_TOOLS, *AGENT_TOOL_SCHEMAS]

    events: list[ChatEvent] = [
        ChatEvent(type="user", label="Answer recorded", detail=request.message, status="completed")
    ]

    def execute_tool(name: str, arguments: dict[str, Any]) -> Any:
        if name in TRIP_PLAN_TOOL_NAMES:
            model_result, ui_plan = _apply_trip_plan_tool(
                store, request.conversation_id or "", name, arguments
            )
            if ui_plan is not None:
                events.append(_trip_plan_event(name, ui_plan))
            return model_result
        try:
            if name == "search_travel_history":
                return history_store.search(request.user_id, str(arguments.get("query", "")))
            if name == "ask_user_question":
                question = str(arguments.get("question", "")).strip()
                options = [str(option).strip() for option in arguments.get("options", [])]
                if not question or len(options) < 2 or any(not option for option in options):
                    raise ValueError("ask_user_question requires a question and at least two options.")
                return {"question": question, "options": options[:6], "status": "awaiting_user"}
            if name in AGENT_TOOL_NAMES:
                return execute_agent_tool(name, arguments)
            raise ValueError(f"Unknown tool requested: {name}")
        except ValueError as error:
            return {"ok": False, "tool": name, "error": str(error)}

    messages = list(pending["messages"])
    messages.append({"role": "user", "content": request.message})
    client = TACCClient()
    trace = start_trace(
        name="chat.question",
        input={
            "answer": request.message,
            "question": pending["question"],
            "conversation_id": request.conversation_id,
        },
        session_id=request.conversation_id,
        metadata={"stream": True, "model": client.model, "continuation": True},
    )
    return {
        "store": store,
        "pending": pending,
        "messages": messages,
        "tools": tools,
        "execute_tool": execute_tool,
        "events": events,
        "client": client,
        "trace": trace,
    }


@app.post("/api/chat/question", response_model=ChatResponse)
def answer_chat_question(request: ChatRequest) -> ChatResponse:
    """Resume a paused model tool call with a selected option."""
    context = _prepare_question_continuation(request)
    store = context["store"]
    pending = context["pending"]
    messages = context["messages"]
    tools = context["tools"]
    execute_tool = context["execute_tool"]
    events = context["events"]
    client = context["client"]
    trace = context["trace"]
    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    next_pending: dict[str, Any] | None = None

    def save_pause(next_messages: list[dict[str, Any]], result: dict[str, Any]) -> None:
        nonlocal next_pending
        next_pending = result
        store.save_pending_question(
            request.conversation_id or "",
            request.user_id,
            next_messages,
            result["question"],
            result["options"],
        )

    last_error: Exception | None = None
    for attempt in range(1, 4):
        text_parts.clear()
        reasoning_parts.clear()
        try:
            for delta in client.stream(
                "",
                tools=tools,
                tool_executor=execute_tool,
                initial_messages=messages,
                on_event=lambda event: events.append(ChatEvent(**event)),
                on_pause=save_pause,
                session_id=request.conversation_id,
                trace_context=trace_context_for(trace),
            ):
                if delta["kind"] == "reasoning":
                    reasoning_parts.append(delta["text"])
                else:
                    text_parts.append(delta["text"])
            last_error = None
            break
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            last_error = error
            if attempt < 3:
                events.append(
                    ChatEvent(
                        type="model",
                        label=f"Retrying continuation ({attempt}/3)",
                        detail="The model request was interrupted; retrying automatically.",
                        status="running",
                    )
                )
    if last_error is not None:
        error_text = str(last_error) or last_error.__class__.__name__
        end_trace(
            trace,
            output="".join(text_parts) or {"error": error_text},
            error=last_error,
        )
        failure = ChatEvent(
            type="model",
            label="Continuation failed; answer can be retried",
            detail=error_text,
            status="error",
            data={"tool": "ask_user_question", "selected": request.message},
        )
        conversation = store.get(request.conversation_id)
        if conversation is not None:
            store.save(
                request.conversation_id,
                conversation["messages"],
                [failure.model_dump()],
            )
        raise HTTPException(
            status_code=502,
            detail={
                "message": "The assistant could not continue yet. Your choice is still saved for retry.",
                "conversation_id": request.conversation_id,
                "retryable": True,
            },
        ) from last_error

    if next_pending is not None:
        trace_output: Any = {
            "status": "awaiting_user",
            "question": next_pending.get("question", ""),
        }
    else:
        trace_output = "".join(text_parts) or {"text": ""}
    end_trace(trace, output=trace_output)

    if next_pending is None:
        store.clear_pending_question(request.conversation_id)
    store.mark_question_answered(
        request.conversation_id,
        request.message,
        pending["question"],
    )
    conversation = store.get(request.conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    answer_message = {
        "role": "assistant",
        "content": "".join(text_parts),
        "reasoning": "".join(reasoning_parts),
    }
    conversation["messages"].append({"role": "user", "content": request.message})
    conversation["messages"].append(answer_message)
    conversation_id = store.save(
        request.conversation_id,
        conversation["messages"],
        [event.model_dump() for event in events],
    )
    return ChatResponse(
        text=answer_message["content"],
        reasoning=answer_message["reasoning"],
        model=client.model,
        conversation_id=conversation_id,
        events=events,
    )


@app.post("/api/chat/question/stream")
def answer_chat_question_stream(request: ChatRequest) -> StreamingResponse:
    """Stream the continuation of a paused question.

    Emits the same frame kinds as /api/chat/stream (event, reasoning, content,
    done, error) so the browser can show the agents working, render partial
    text, and stop the turn instead of waiting on a silent request.
    """
    context = _prepare_question_continuation(request)
    store = context["store"]
    pending = context["pending"]
    messages = context["messages"]
    tools = context["tools"]
    execute_tool = context["execute_tool"]
    events = context["events"]
    client = context["client"]
    trace = context["trace"]
    conversation_id = request.conversation_id or ""

    def frames():
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        next_pending: dict[str, Any] | None = None
        emitted = 0
        cancelled = False
        trace_finished = False
        cancel_event = register_cancel(request.request_id)

        def save_pause(next_messages: list[dict[str, Any]], result: dict[str, Any]) -> None:
            nonlocal next_pending
            next_pending = result
            store.save_pending_question(
                conversation_id,
                request.user_id,
                next_messages,
                result["question"],
                result["options"],
            )

        def new_events() -> list[ChatEvent]:
            nonlocal emitted
            pending_events = events[emitted:]
            emitted = len(events)
            return pending_events

        def frame(payload: dict[str, Any]) -> str:
            return f"data: {json.dumps(payload)}\n\n"

        def event_frame(event: ChatEvent) -> str:
            return frame({"kind": "event", **event.model_dump()})

        try:
            for event in new_events():
                yield event_frame(event)
            for delta in client.stream(
                "",
                tools=tools,
                tool_executor=execute_tool,
                initial_messages=messages,
                on_event=lambda event: events.append(ChatEvent(**event)),
                on_pause=save_pause,
                session_id=conversation_id,
                trace_context=trace_context_for(trace),
                cancel_event=cancel_event,
            ):
                if cancel_event.is_set():
                    cancelled = True
                    break
                for event in new_events():
                    yield event_frame(event)
                if delta["kind"] == "reasoning":
                    reasoning_parts.append(delta["text"])
                else:
                    text_parts.append(delta["text"])
                yield frame({"kind": delta["kind"], "text": delta["text"]})
            for event in new_events():
                yield event_frame(event)

            if cancelled:
                stopped = ChatEvent(
                    type="agent",
                    label="Stopped by user",
                    detail="The response was stopped before it completed.",
                    status="completed",
                )
                events.append(stopped)
                yield event_frame(stopped)
                stopped_message = {
                    "role": "assistant",
                    "content": "".join(text_parts) or "[Stopped] The response was stopped.",
                    "reasoning": "".join(reasoning_parts),
                }
                conversation = store.get(conversation_id)
                if conversation is not None:
                    stored_messages = (
                        conversation["messages"]
                        if next_pending is not None
                        else conversation["messages"] + [stopped_message]
                    )
                    store.save(
                        conversation_id,
                        stored_messages,
                        [event.model_dump() for event in events],
                    )
                end_trace(trace, output="".join(text_parts) or {"status": "stopped"})
                trace_finished = True
                yield frame(
                    {
                        "kind": "done",
                        "stopped": True,
                        "text": "".join(text_parts),
                        "reasoning": "".join(reasoning_parts),
                        "model": client.model,
                        "stub": not client.configured,
                        "conversation_id": conversation_id,
                        "pending_question": next_pending,
                        "events": [event.model_dump() for event in events],
                    }
                )
                return

            if not "".join(text_parts).strip() and next_pending is None:
                empty = ChatEvent(
                    type="model",
                    label="Model returned an empty response",
                    detail="The model finished without content. Please retry or rephrase.",
                    status="error",
                )
                events.append(empty)
                yield event_frame(empty)
                text_parts = [
                    "[The model returned an empty response. Please retry or rephrase "
                    "your request.]"
                ]
            completed = ChatEvent(
                type="agent",
                label="Coordinator agent completed",
                status="completed",
            )
            events.append(completed)
            yield event_frame(completed)

            if next_pending is None:
                store.clear_pending_question(conversation_id)
            store.mark_question_answered(
                conversation_id,
                request.message,
                pending["question"],
            )
            conversation = store.get(conversation_id)
            if conversation is None:
                yield frame(
                    {
                        "kind": "error",
                        "message": "The conversation was deleted before the answer was saved.",
                        "conversation_id": conversation_id,
                        "events": [],
                    }
                )
                return
            answer_message = {
                "role": "assistant",
                "content": "".join(text_parts),
                "reasoning": "".join(reasoning_parts),
            }
            conversation["messages"].append({"role": "user", "content": request.message})
            conversation["messages"].append(answer_message)
            store.save(
                conversation_id,
                conversation["messages"],
                [event.model_dump() for event in events],
            )
            final_text = "".join(text_parts)
            if final_text:
                trace_output: Any = final_text
            elif next_pending is not None:
                trace_output = {
                    "status": "awaiting_user",
                    "question": next_pending.get("question", ""),
                }
            else:
                trace_output = {"text": ""}
            end_trace(trace, output=trace_output)
            trace_finished = True
            yield frame(
                {
                    "kind": "done",
                    "text": final_text,
                    "reasoning": "".join(reasoning_parts),
                    "model": client.model,
                    "stub": not client.configured,
                    "conversation_id": conversation_id,
                    "pending_question": next_pending,
                    "events": [event.model_dump() for event in events],
                }
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            end_trace(
                trace,
                output="".join(text_parts) or {"error": str(error)},
                error=error,
            )
            trace_finished = True
            failure = ChatEvent(
                type="model",
                label="Continuation failed; answer can be retried",
                detail=str(error) or error.__class__.__name__,
                status="error",
                data={"tool": "ask_user_question", "selected": request.message},
            )
            events.append(failure)
            conversation = store.get(conversation_id)
            if conversation is not None:
                store.save(
                    conversation_id,
                    conversation["messages"],
                    [event.model_dump() for event in events],
                )
            yield frame(
                {
                    "kind": "error",
                    "message": (
                        "The assistant could not continue yet. "
                        "Your choice is still saved for retry."
                    ),
                    "conversation_id": conversation_id,
                    "events": [failure.model_dump()],
                }
            )
        finally:
            clear_cancel(request.request_id, cancel_event)
            if not trace_finished:
                end_trace(
                    trace,
                    output="".join(text_parts) or {"text": ""},
                )

    return StreamingResponse(frames(), media_type="text/event-stream")


@app.put("/api/conversations/{conversation_id}/trip-plan")
def update_trip_plan(conversation_id: str, request: TripPlanUpdate) -> dict:
    """Persist user-edited budget fields onto the conversation's latest plan."""
    currency = None if request.currency is None else request.currency.strip()[:12]
    budget_items: list[dict[str, Any]] = []
    for item in request.budget_items[:12]:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="Each budget item must be an object.")
        category = str(item.get("category", "")).strip()
        amount = item.get("amount")
        if (
            not category
            or isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or amount < 0
        ):
            raise HTTPException(
                status_code=422,
                detail="Each budget item needs a category and a non-negative amount.",
            )
        budget_items.append(
            {"category": category, "amount": float(amount), "currency": currency or ""}
        )
    store = ConversationStore(get_settings().database_url)
    plan = store.get_trip_plan(conversation_id)
    if plan is None:
        raise HTTPException(
            status_code=404, detail="No trip plan found for this conversation."
        )

    updated_plan = dict(plan)
    if request.budget is not None:
        updated_plan["budget"] = request.budget
    if currency is not None:
        updated_plan["currency"] = currency
    if request.mode != "day":
        updated_plan["budget_items"] = budget_items

    # Full day edits (itinerary + budget together) from the merged day editor.
    if request.mode != "category":
        for entry in request.days:
            if not isinstance(entry, dict):
                raise HTTPException(status_code=422, detail="Each day must be an object.")
            try:
                updated_plan, _ = apply_trip_plan_tool(
                    "set_trip_day",
                    {
                        "day": entry.get("day"),
                        "title": entry.get("title"),
                        "activities": entry.get("activities", []),
                        "notes": entry.get("notes", []),
                        "places": entry.get("places", []),
                        "coordinates": entry.get("coordinates"),
                        "budget": entry.get("budget"),
                        "budget_items": entry.get("budget_items", []),
                    },
                    updated_plan,
                )
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error

    assembled = assemble_trip_plan(updated_plan)
    store.save_trip_plan(conversation_id, updated_plan)
    store.set_latest_trip_plan_event(conversation_id, assembled)
    return {
        "updated": True,
        "budget": request.budget,
        "currency": currency,
        "budget_items": budget_items,
    }


@app.get("/api/conversations", response_model=list[ConversationSummary])
def list_conversations() -> list[ConversationSummary]:
    return [ConversationSummary(**item) for item in ConversationStore(get_settings().database_url).list()]


@app.get("/api/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(conversation_id: str) -> ConversationResponse:
    result = ConversationStore(get_settings().database_url).get(conversation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return ConversationResponse(**result)


@app.delete("/api/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str) -> None:
    if not ConversationStore(get_settings().database_url).delete(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")


frontend_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


def main() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run("backend.main:app", host=s.app_host, port=s.app_port, reload=True)


if __name__ == "__main__":
    main()

