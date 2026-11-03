"""Tests for persisting the assembled trip plan."""

from __future__ import annotations

from trip_planning_agent.conversation_store import ConversationStore


def _store(tmp_path) -> ConversationStore:
    return ConversationStore(f"sqlite:///{(tmp_path / 'conv.sqlite').as_posix()}")


def test_save_and_get_trip_plan(tmp_path):
    store = _store(tmp_path)
    conversation_id = store.save(None, [{"role": "user", "content": "hi"}], [])
    plan = {"destination": "Rome", "days": [{"day": 1, "title": "t", "activities": ["a"]}], "budget": 100}
    store.save_trip_plan(conversation_id, plan)
    assert store.get_trip_plan(conversation_id)["destination"] == "Rome"


def test_set_latest_trip_plan_event_updates_result(tmp_path):
    store = _store(tmp_path)
    event = {
        "type": "tool",
        "label": "Trip plan updated",
        "status": "completed",
        "data": {"tool": "display_trip_plan", "result": {"destination": "Old"}},
    }
    conversation_id = store.save(None, [{"role": "user", "content": "hi"}], [event])
    assert store.set_latest_trip_plan_event(conversation_id, {"destination": "New"}) is True
    events = store.get(conversation_id)["events"]
    result = [item for item in events if item["data"].get("tool") == "display_trip_plan"][-1]["data"]["result"]
    assert result["destination"] == "New"


def test_get_trip_plan_missing_returns_none(tmp_path):
    store = _store(tmp_path)
    conversation_id = store.save(None, [{"role": "user", "content": "hi"}], [])
    assert store.get_trip_plan(conversation_id) is None
