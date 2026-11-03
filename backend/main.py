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
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from agents.chat_tools import (
    AGENT_TOOL_NAMES,
    AGENT_TOOL_SCHEMAS,
    execute_agent_tool,
)
from agents.coordinator import run as coordinate
from agents.coordinator.agent import health as coordinator_health
from agents.estimate_transport.agent import health as transport_health
from agents.search_stays.agent import health as stays_health
from agents.travel_history.agent import health as history_health
from agents.travel_history.agent import remember_from_message
from agents.travel_history.agent import TravelHistoryStore
from agents.web_search.agent import health as web_search_health
from agents.web_search import run as web_search
from config.settings import get_model_config, get_settings, update_model_config
from shared.schemas import (
    ChatEvent,
    ChatStopRequest,
    StayCandidate,
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    ConversationSummary,
    Itinerary,
    ModelSettingsResponse,
    ModelSettingsUpdate,
    TripRequest,
    TravelHistoryCreate,
    TravelHistoryEntry,
    TripPlanUpdate,
    WebSearchRequest,
)
from shared.prompts import TRIP_PLANNING_SYSTEM_PROMPT
from shared.trip_plan import TRIP_PLAN_TOOL, format_plan_context, normalize_trip_plan
from trip_planning_agent.tacc_client import TACCClient
from trip_planning_agent.cancellation import clear as clear_cancel
from trip_planning_agent.cancellation import register as register_cancel
from trip_planning_agent.cancellation import request_stop
from trip_planning_agent.conversation_store import ConversationStore
from trip_planning_agent.observability import (
    end_trace,
    start_trace,
    trace_context_for,
)

app = FastAPI(title="trip-planning-agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cooperative cancellation for in-flight streaming turns lives in
# trip_planning_agent.cancellation. The client sends a `request_id` with the
# stream and can call POST /api/chat/stop to set its event; the streaming loop
# and the model client check the event between deltas.


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
            "web_search": web_search_health(),
        },
    }


@app.post("/plan", response_model=Itinerary)
def plan(request: TripRequest) -> Itinerary:
    return coordinate(request, session_id=f"plan-{uuid.uuid4()}")


@app.post("/agents/search_stays", response_model=list[StayCandidate])
def agent_search_stays(request: TripRequest) -> list[StayCandidate]:
    """Direct Agent 1 stay search (stub catalog or configured provider)."""
    from agents.search_stays.agent import run as search_stays_run

    return search_stays_run(request)



@app.get("/api/travel-history", response_model=list[TravelHistoryEntry])
def list_travel_history(
    user_id: str = Query(default="local-user", min_length=1, max_length=200),
) -> list[TravelHistoryEntry]:
    store = TravelHistoryStore(get_settings().database_url)
    return [TravelHistoryEntry(**entry) for entry in store.list_entries(user_id)]


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
def update_model_settings(request: ModelSettingsUpdate) -> ModelSettingsResponse:
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


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    store = ConversationStore(get_settings().database_url)
    conversation = list(request.conversation[-20:])
    events: list[ChatEvent] = [
        ChatEvent(type="agent", label="Agent request queued", status="completed"),
    ]
    plan_context = format_plan_context(request.plan_context)
    prompt = request.message
    if conversation:
        prompt = "\n".join(
            f"{item.get('role', 'user')}: {item.get('content', '')}" for item in conversation
        ) + f"\nuser: {request.message}"
    if plan_context:
        prompt = f"{plan_context}\n\n{prompt}"
    conversation.append({"role": "user", "content": request.message})
    conversation_id = store.save(
        request.conversation_id,
        conversation,
        [event.model_dump() for event in events],
    )
    memory_user_id = request.user_id or conversation_id
    remembered_places = remember_from_message(memory_user_id, request.message)
    if remembered_places:
        events.append(
            ChatEvent(
                type="agent",
                label="Travel history updated",
                detail=", ".join(remembered_places),
                status="completed",
            )
        )
    client = TACCClient()
    trace = start_trace(
        name="chat.turn",
        input={
            "message": request.message,
            "history_turns": max(len(conversation) - 1, 0),
        },
        session_id=conversation_id,
        metadata={"stream": False, "model": client.model},
    )
    try:
        result = client.complete(
            prompt,
            system=TRIP_PLANNING_SYSTEM_PROMPT,
            on_event=lambda event: events.append(ChatEvent(**event)),
            session_id=conversation_id,
            trace_context=trace_context_for(trace),
        )
        if not result.get("ok") and not result.get("stub"):
            raise ValueError("The model service returned an invalid response.")
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        end_trace(trace, output={"error": str(error)}, error=error)
        failure_event = ChatEvent(
            type="model",
            label="Model request failed",
            detail=str(error),
            status="error",
        )
        store.save(
            conversation_id,
            conversation,
            [event.model_dump() for event in events[1:]]
            + [failure_event.model_dump()],
        )
        raise HTTPException(
            status_code=502,
            detail={
                "message": "The model request failed. The user message was saved and can be retried.",
                "conversation_id": conversation_id,
            },
        ) from error
    end_trace(trace, output=str(result["text"]))
    conversation.extend(
        [{"role": "assistant", "content": str(result["text"])}]
    )
    conversation_id = store.save(
        conversation_id,
        conversation,
        [event.model_dump() for event in events[1:]],
    )
    return ChatResponse(
        text=str(result["text"]),
        stub=bool(result.get("stub")),
        model=client.model,
        conversation_id=conversation_id,
        events=events,
    )


@app.post("/api/chat/stop")
def stop_chat(request: ChatStopRequest) -> dict:
    """Cooperatively stop a streaming turn started with the same request_id."""
    return {
        "request_id": request.request_id,
        "stopped": request_stop(request.request_id),
    }


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
    history_tools = [{
        "type": "function",
        "function": {
            "name": "search_travel_history",
            "description": "Search the user's saved travel history for locations related to a destination or place.",
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
    }, TRIP_PLAN_TOOL, *AGENT_TOOL_SCHEMAS]

    def execute_history_tool(name: str, arguments: dict[str, Any]) -> Any:
        if name == "search_travel_history":
            return history_store.search(memory_user_id, str(arguments.get("query", "")))
        if name == "ask_user_question":
            question = str(arguments.get("question", "")).strip()
            options = [str(option).strip() for option in arguments.get("options", [])]
            if not question or len(options) < 2 or any(not option for option in options):
                raise ValueError("ask_user_question requires a question and at least two options.")
            return {"question": question, "options": options[:6], "status": "awaiting_user"}
        if name == "display_trip_plan":
            return normalize_trip_plan(arguments)
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
            try:
                for delta in client.stream(
                    prompt,
                    system=TRIP_PLANNING_SYSTEM_PROMPT,
                    on_event=lambda event: stream_queue.put(("event", event)),
                    tools=history_tools,
                    tool_executor=execute_history_tool,
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


@app.post("/api/chat/question", response_model=ChatResponse)
def answer_chat_question(request: ChatRequest) -> ChatResponse:
    """Resume a paused model tool call with a selected option."""
    if not request.conversation_id:
        raise HTTPException(status_code=400, detail="A conversation_id is required.")
    store = ConversationStore(get_settings().database_url)
    pending = store.get_pending_question(request.conversation_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="No question is waiting for this conversation.")
    if pending["user_id"] != request.user_id or request.message not in pending["options"]:
        raise HTTPException(status_code=422, detail="Choose one of the displayed question options.")

    history_store = TravelHistoryStore(get_settings().database_url)
    tools = [{
        "type": "function",
        "function": {
            "name": "search_travel_history",
            "description": "Search the user's saved travel history for locations related to a destination or place.",
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
    }, TRIP_PLAN_TOOL, *AGENT_TOOL_SCHEMAS]

    def execute_tool(name: str, arguments: dict[str, Any]) -> Any:
        if name == "search_travel_history":
            return history_store.search(request.user_id, str(arguments.get("query", "")))
        if name == "ask_user_question":
            question = str(arguments.get("question", "")).strip()
            options = [str(option).strip() for option in arguments.get("options", [])]
            if not question or len(options) < 2 or any(not option for option in options):
                raise ValueError("ask_user_question requires a question and at least two options.")
            return {"question": question, "options": options[:6], "status": "awaiting_user"}
        if name == "display_trip_plan":
            return normalize_trip_plan(arguments)
        if name in AGENT_TOOL_NAMES:
            return execute_agent_tool(name, arguments)
        raise ValueError(f"Unknown tool requested: {name}")

    messages = list(pending["messages"])
    messages.append({"role": "user", "content": request.message})
    events: list[ChatEvent] = [
        ChatEvent(type="user", label="Answer recorded", detail=request.message, status="completed")
    ]
    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    next_pending: dict[str, Any] | None = None
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
    day_budgets: list[dict[str, Any]] = []
    for item in request.day_budgets[:30]:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="Each day budget must be an object.")
        day = item.get("day")
        amount = item.get("amount")
        if isinstance(day, bool) or not isinstance(day, (int, float)) or day < 1:
            raise HTTPException(status_code=422, detail="Each day budget needs a day number.")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 0:
            raise HTTPException(
                status_code=422, detail="Each day budget needs a non-negative amount."
            )
        day_budgets.append({"day": int(day), "amount": float(amount)})
    updated = ConversationStore(get_settings().database_url).update_latest_trip_plan(
        conversation_id,
        {
            "budget": request.budget,
            "currency": currency,
            "budget_items": budget_items,
            "day_budgets": day_budgets,
        },
    )
    if not updated:
        raise HTTPException(
            status_code=404, detail="No trip plan found for this conversation."
        )
    return {
        "updated": True,
        "budget": request.budget,
        "currency": currency,
        "budget_items": budget_items,
        "day_budgets": day_budgets,
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

