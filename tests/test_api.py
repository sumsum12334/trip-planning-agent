"""FastAPI endpoint tests (offline: stub tools, no model endpoint).

Covers the public HTTP contract: /health, /plan, /plan/revise, the direct
agent endpoints, travel history CRUD, settings, the chat stream/stop/question
flow, and the trip-plan persistence endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config import settings as settings_mod


@pytest.fixture(autouse=True)
def _offline_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from config.settings import reset_model_config

    monkeypatch.setenv("QWEN_BASE_URL", "")
    monkeypatch.setenv("QWEN_API_KEY", "")
    monkeypatch.setenv("LANGFUSE_ENABLED", "0")
    monkeypatch.setenv("TOOL_STAYS_MODE", "stub")
    monkeypatch.setenv("TOOL_MAPS_MODE", "stub")
    monkeypatch.setenv("WEB_SEARCH_MODE", "stub")
    monkeypatch.setenv("ENABLE_TRAVEL_HISTORY", "0")
    monkeypatch.setenv(
        "DATABASE_URL", "sqlite:///" + (tmp_path / "api-test.sqlite").as_posix()
    )
    # Drop process-local model overrides so tests stay isolated from
    # PUT /api/settings/model calls made by earlier tests.
    reset_model_config()
    settings_mod.get_settings.cache_clear()
    yield
    reset_model_config()
    settings_mod.get_settings.cache_clear()


@pytest.fixture()
def client() -> TestClient:
    from backend.main import app

    return TestClient(app)


def test_health_reports_agents(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["baseline_a"] is True
    assert set(payload["agents"]) == {
        "search_stays",
        "estimate_transport",
        "coordinator",
        "travel_history",
        "web_search",
        "weather",
    }
    assert payload["weather_mode"] == "stub"
    assert payload["agents"]["weather"]["mode"] == "stub"


def test_plan_returns_itinerary_offline(client: TestClient) -> None:
    response = client.post(
        "/plan",
        json={"destination": "Hong Kong", "origin": "Hong Kong Airport", "days": 2},
    )
    assert response.status_code == 200
    itinerary = response.json()
    assert len(itinerary["days"]) == 2
    assert itinerary["currency"] == "HKD"
    assert itinerary["total_estimated_cost"] is not None


def test_plan_rejects_invalid_days(client: TestClient) -> None:
    response = client.post("/plan", json={"destination": "Tokyo", "days": 0})
    assert response.status_code == 422


def test_plan_revise_roundtrip_and_guards(client: TestClient) -> None:
    initial = client.post(
        "/plan",
        json={"destination": "Hong Kong", "origin": "Hong Kong Airport", "days": 3, "budget": 600},
    ).json()
    response = client.post(
        "/plan/revise",
        json={
            "itinerary": initial,
            "request": {
                "destination": "Hong Kong",
                "origin": "Hong Kong Airport",
                "days": 3,
                "budget": 350,
            },
        },
    )
    assert response.status_code == 200
    revised = response.json()
    assert any("budget" in note.casefold() for note in revised["notes"])

    destination_change = client.post(
        "/plan/revise",
        json={"itinerary": initial, "request": {"destination": "Tokyo", "days": 3}},
    )
    assert destination_change.status_code == 422

    infeasible = client.post(
        "/plan/revise",
        json={
            "itinerary": initial,
            "request": {
                "destination": "Hong Kong",
                "origin": "Hong Kong Airport",
                "days": 3,
                "budget": 20,
            },
        },
    )
    assert infeasible.status_code == 422


def test_direct_agent_endpoints(client: TestClient) -> None:
    stays = client.post(
        "/agents/search_stays", json={"destination": "Tokyo", "days": 2, "budget": 300}
    )
    assert stays.status_code == 200
    assert len(stays.json()) >= 1

    leg = client.post(
        "/agents/estimate_transport",
        json={"from_place": "Hong Kong Airport", "to_place": "Central"},
    )
    assert leg.status_code == 200
    payload = leg.json()
    assert payload["mode"] == "airport_express"
    assert payload["notes"] and "stub" in payload["notes"].casefold()


def test_estimate_transport_unavailable_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _unavailable(request, from_place, to_place):
        raise NotImplementedError("api mode is not implemented")

    monkeypatch.setattr(
        "agents.estimate_transport.agent.run", _unavailable
    )
    response = client.post(
        "/agents/estimate_transport",
        json={"from_place": "Hong Kong Airport", "to_place": "Central"},
    )
    assert response.status_code == 503
    assert "estimate_transport is unavailable" in response.json()["detail"]


def test_weather_endpoint_stub_mode(client: TestClient) -> None:
    response = client.post("/agents/weather", json={"destination": "Tokyo"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["destination"] == "Tokyo"
    assert payload["mode"] == "stub"
    assert payload["stub"] is True
    assert payload["temperature_c"] is not None


def test_travel_history_crud(client: TestClient) -> None:
    created = client.post(
        "/api/travel-history",
        json={"user_id": "api-test-user", "country": "Japan", "city": "Tokyo", "location": "Shibuya"},
    )
    assert created.status_code == 201
    entry_id = created.json()["id"]

    listed = client.get("/api/travel-history", params={"user_id": "api-test-user"})
    assert listed.status_code == 200
    assert [item["location"] for item in listed.json()] == ["Shibuya"]

    deleted = client.delete(
        f"/api/travel-history/{entry_id}", params={"user_id": "api-test-user"}
    )
    assert deleted.status_code == 204
    missing = client.delete(
        f"/api/travel-history/{entry_id}", params={"user_id": "api-test-user"}
    )
    assert missing.status_code == 404


def test_web_search_stub_mode(client: TestClient) -> None:
    response = client.post(
        "/api/tools/web-search", json={"query": "things to do in Kyoto", "limit": 3}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "stub"
    assert payload["results"]


def test_settings_endpoints(client: TestClient) -> None:
    current = client.get("/api/settings")
    assert current.status_code == 200
    assert current.json()["qwen_configured"] is False
    assert current.json()["reconsider_prompt_enabled"] is True

    updated = client.put(
        "/api/settings/model",
        json={"endpoint_url": "http://127.0.0.1:9999/v1", "model": "test-model"},
    )
    assert updated.status_code == 200
    assert updated.json()["endpoint_url"] == "http://127.0.0.1:9999/v1"
    assert updated.json()["api_key_configured"] is False

    invalid = client.put(
        "/api/settings/model",
        json={"endpoint_url": "not-a-url", "model": "test-model"},
    )
    assert invalid.status_code == 422


def _sse_frames(response) -> list[dict]:
    frames = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            frames.append(json.loads(line[len("data: ") :]))
    return frames


def test_chat_stream_stub_and_conversation_persisted(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "Hello there", "user_id": "api-stream-user"},
    ) as response:
        assert response.status_code == 200
        frames = _sse_frames(response)
    done = next(frame for frame in frames if frame.get("kind") == "done")
    assert done["stub"] is True
    conversation_id = done["conversation_id"]
    assert conversation_id

    stored = client.get(f"/api/conversations/{conversation_id}")
    assert stored.status_code == 200
    roles = [message["role"] for message in stored.json()["messages"]]
    assert roles == ["user", "assistant"]


def test_chat_stop_unknown_request_id(client: TestClient) -> None:
    response = client.post("/api/chat/stop", json={"request_id": "req-does-not-exist"})
    assert response.status_code == 200
    assert response.json()["stopped"] is False


def test_chat_question_without_pending_question(client: TestClient) -> None:
    response = client.post(
        "/api/chat/question",
        json={"message": "Tokyo", "conversation_id": "missing", "user_id": "api-user"},
    )
    assert response.status_code == 404


def test_chat_question_stream_resumes_pending_question(client: TestClient) -> None:
    from config.settings import get_settings
    from trip_planning_agent.conversation_store import ConversationStore

    store = ConversationStore(get_settings().database_url)
    conversation_id = store.save(
        None,
        [{"role": "user", "content": "Plan a trip"}],
        [
            {
                "type": "tool",
                "label": "ask_user_question",
                "status": "completed",
                "data": {
                    "tool": "ask_user_question",
                    "result": {"question": "Which month?", "options": ["March", "April"]},
                },
            }
        ],
    )
    store.save_pending_question(
        conversation_id,
        "api-user",
        [{"role": "user", "content": "Plan a trip"}],
        "Which month?",
        ["March", "April"],
    )

    with client.stream(
        "POST",
        "/api/chat/question/stream",
        json={
            "message": "March",
            "conversation_id": conversation_id,
            "user_id": "api-user",
            "request_id": "req-question-stream",
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = _sse_frames(response)

    # The browser must see progress, not a silent request: events and content
    # stream before the final frame.
    assert any(frame.get("kind") == "event" for frame in frames)
    assert any(frame.get("kind") == "content" for frame in frames)
    done = next(frame for frame in frames if frame.get("kind") == "done")
    assert done["conversation_id"] == conversation_id
    assert done["stub"] is True
    assert "Model stub" in done["text"]
    assert done["pending_question"] is None

    # The answer is persisted and the question is no longer pending.
    assert store.get_pending_question(conversation_id) is None
    stored = client.get(f"/api/conversations/{conversation_id}")
    assert stored.status_code == 200
    body = stored.json()
    assert [message["role"] for message in body["messages"]] == [
        "user",
        "user",
        "assistant",
    ]
    assert body["messages"][1]["content"] == "March"
    questions = [
        event
        for event in body["events"]
        if event.get("data", {}).get("tool") == "ask_user_question"
    ]
    assert questions and questions[-1]["data"]["selected"] == "March"


def test_conversations_list_get_delete(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "List me", "user_id": "api-list-user"},
    ) as response:
        frames = _sse_frames(response)
    conversation_id = next(f for f in frames if f.get("kind") == "done")["conversation_id"]

    listed = client.get("/api/conversations")
    assert listed.status_code == 200
    assert any(item["id"] == conversation_id for item in listed.json())

    deleted = client.delete(f"/api/conversations/{conversation_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/conversations/{conversation_id}").status_code == 404
    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 404


def test_trip_plan_update_and_validation(client: TestClient) -> None:
    from trip_planning_agent.conversation_store import ConversationStore
    from config.settings import get_settings

    store = ConversationStore(get_settings().database_url)
    conversation_id = store.save(None, [{"role": "user", "content": "plan"}], [])
    store.save_trip_plan(
        conversation_id,
        {
            "destination": "Hong Kong",
            "currency": "HKD",
            "budget": 600,
            "budget_items": [],
            "days": [
                {
                    "day": 1,
                    "title": "Arrival",
                    "activities": ["Check in"],
                    "notes": [],
                    "coordinates": None,
                    "places": [],
                    "stays": [],
                    "budget": 300,
                    "budget_items": [],
                }
            ],
            "notes": [],
            "references": [],
            "status": "displayed",
        },
    )

    missing = client.put(
        f"/api/conversations/{conversation_id}/trip-plan",
        json={},
    )
    # A PUT with no fields is a no-op: it must not wipe the stored budget.
    assert missing.status_code == 200
    assert store.get_trip_plan(conversation_id)["budget"] == 600

    updated = client.put(
        f"/api/conversations/{conversation_id}/trip-plan",
        json={"budget": 350, "currency": "HKD", "mode": "category"},
    )
    assert updated.status_code == 200
    stored_plan = store.get_trip_plan(conversation_id)
    assert stored_plan["budget"] == 350

    bad_item = client.put(
        f"/api/conversations/{conversation_id}/trip-plan",
        json={"budget_items": [{"category": "", "amount": 5}]},
    )
    assert bad_item.status_code == 422

    bad_amount = client.put(
        f"/api/conversations/{conversation_id}/trip-plan",
        json={"budget_items": [{"category": "food", "amount": -1}]},
    )
    assert bad_amount.status_code == 422


def test_trip_plan_update_unknown_conversation(client: TestClient) -> None:
    response = client.put(
        "/api/conversations/does-not-exist/trip-plan", json={"budget": 100}
    )
    assert response.status_code == 404


def test_trip_plan_update_ignores_removed_legacy_fields(client: TestClient) -> None:
    """day_budgets/day_items were removed; sending them must be a no-op."""
    from trip_planning_agent.conversation_store import ConversationStore
    from config.settings import get_settings

    store = ConversationStore(get_settings().database_url)
    conversation_id = store.save(None, [{"role": "user", "content": "plan"}], [])
    store.save_trip_plan(
        conversation_id,
        {
            "destination": "Hong Kong",
            "currency": "HKD",
            "budget": 600,
            "budget_items": [],
            "days": [
                {
                    "day": 1,
                    "title": "Arrival",
                    "activities": ["Check in"],
                    "notes": [],
                    "coordinates": None,
                    "places": [],
                    "stays": [],
                    "budget": 300,
                    "budget_items": [],
                }
            ],
            "notes": [],
            "references": [],
            "status": "displayed",
        },
    )
    legacy = client.put(
        f"/api/conversations/{conversation_id}/trip-plan",
        json={
            "day_budgets": [{"day": 1, "amount": 999}],
            "day_items": [{"day": 1, "category": "food", "amount": 1}],
        },
    )
    assert legacy.status_code == 200
    assert "day_budgets" not in legacy.json()
    stored = store.get_trip_plan(conversation_id)
    assert stored["budget"] == 600
    assert stored["days"][0]["budget"] == 300


def test_model_settings_reject_remote_client() -> None:
    from backend.main import app

    remote = TestClient(app, client=("203.0.113.5", 12345))
    response = remote.put(
        "/api/settings/model",
        json={"endpoint_url": "http://127.0.0.1:9999/v1", "model": "test-model"},
    )
    assert response.status_code == 403
