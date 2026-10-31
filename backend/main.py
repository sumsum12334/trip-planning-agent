"""FastAPI backend for trip planning and the browser UI."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from agents.coordinator import run as coordinate
from agents.coordinator.agent import health as coordinator_health
from agents.estimate_transport.agent import health as transport_health
from agents.search_stays.agent import health as stays_health
from agents.travel_history.agent import health as history_health
from agents.web_search.agent import health as web_search_health
from agents.web_search import run as web_search
from config.settings import get_model_config, get_settings, update_model_config
from shared.schemas import (
    ChatEvent,
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    ConversationSummary,
    Itinerary,
    ModelSettingsResponse,
    ModelSettingsUpdate,
    TripRequest,
    WebSearchRequest,
)
from shared.prompts import TRIP_PLANNING_SYSTEM_PROMPT
from trip_planning_agent.tacc_client import TACCClient
from trip_planning_agent.conversation_store import ConversationStore

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
            "web_search": web_search_health(),
        },
    }


@app.post("/plan", response_model=Itinerary)
def plan(request: TripRequest) -> Itinerary:
    return coordinate(request)


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
    prompt = request.message
    if conversation:
        prompt = "\n".join(
            f"{item.get('role', 'user')}: {item.get('content', '')}" for item in conversation
        ) + f"\nuser: {request.message}"
    conversation.append({"role": "user", "content": request.message})
    conversation_id = store.save(
        request.conversation_id,
        conversation,
        [event.model_dump() for event in events],
    )
    try:
        result = TACCClient().complete(
            prompt,
            system=TRIP_PLANNING_SYSTEM_PROMPT,
            on_event=lambda event: events.append(ChatEvent(**event)),
        )
        if not result.get("ok") and not result.get("stub"):
            raise ValueError("The model service returned an invalid response.")
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
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
    client = TACCClient()
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


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    store = ConversationStore(get_settings().database_url)
    conversation = list(request.conversation[-20:])
    prompt = request.message
    if conversation:
        prompt = "\n".join(
            f"{item.get('role', 'user')}: {item.get('content', '')}" for item in conversation
        ) + f"\nuser: {request.message}"
    conversation.append({"role": "user", "content": request.message})
    conversation_id = store.save(request.conversation_id, conversation, [])

    def events():
        activity: list[ChatEvent] = [
            ChatEvent(type="agent", label="Coordinator agent started", status="running")
        ]

        def emit(event: ChatEvent) -> str:
            activity.append(event)
            return f"data: {json.dumps({'kind': 'event', **event.model_dump()})}\n\n"

        yield emit(ChatEvent(type="model", label="Model is thinking", status="running"))
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        try:
            for delta in TACCClient().stream(
                prompt,
                system=TRIP_PLANNING_SYSTEM_PROMPT,
                on_event=lambda event: activity.append(ChatEvent(**event)),
            ):
                if delta["kind"] == "reasoning":
                    reasoning_parts.append(delta["text"])
                else:
                    text_parts.append(delta["text"])
                yield f"data: {json.dumps({'kind': delta['kind'], 'text': delta['text']})}\n\n"
            yield emit(
                ChatEvent(
                    type="agent",
                    label="Coordinator agent completed",
                    status="completed",
                )
            )
            client = TACCClient()
            assistant_message = {"role": "assistant", "content": "".join(text_parts)}
            if reasoning_parts:
                assistant_message["reasoning"] = "".join(reasoning_parts)
            conversation_with_response = conversation + [assistant_message]
            store.save(
                conversation_id,
                conversation_with_response,
                [event.model_dump() for event in activity],
            )
            final_text = "".join(text_parts)
            yield (
                f"data: {json.dumps({'kind': 'done', 'text': final_text, 'reasoning': ''.join(reasoning_parts), 'model': client.model, 'stub': not client.configured, 'conversation_id': conversation_id, 'events': [event.model_dump() for event in activity]})}\n\n"
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
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

    return StreamingResponse(events(), media_type="text/event-stream")


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
