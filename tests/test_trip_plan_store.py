"""Tests for persisting user-edited trip-plan budgets."""

from __future__ import annotations

from trip_planning_agent.conversation_store import ConversationStore


def _store(tmp_path) -> ConversationStore:
    return ConversationStore(f"sqlite:///{(tmp_path / 'conv.sqlite').as_posix()}")


def _plan_event(store, conversation_id):
    conversation = store.get(conversation_id)
    events = [event for event in conversation["events"] if event["data"].get("tool") == "display_trip_plan"]
    return events[-1]["data"]["result"]


def test_update_latest_trip_plan_overwrites_budget(tmp_path):
    store = _store(tmp_path)
    plan = {
        "destination": "Rome",
        "budget": 420,
        "currency": "EUR",
        "budget_items": [{"category": "Food", "amount": 120, "currency": "EUR"}],
        "days": [{"day": 1, "title": "Arrival", "activities": ["Check in"]}],
    }
    events = [{
        "type": "tool",
        "label": "display_trip_plan result received",
        "status": "completed",
        "data": {"tool": "display_trip_plan", "result": plan},
    }]
    conversation_id = store.save(None, [{"role": "user", "content": "hi"}], events)

    updated = store.update_latest_trip_plan(
        conversation_id,
        {
            "budget": 300,
            "currency": "USD",
            "budget_items": [{"category": "Stay", "amount": 200, "currency": "USD"}],
            "day_budgets": [{"day": 1, "amount": 150}],
            "day_items": [{"day": 1, "category": "Food", "amount": 60}],
        },
    )
    assert updated is True
    result = _plan_event(store, conversation_id)
    assert result["budget"] == 300
    assert result["currency"] == "USD"
    assert result["budget_items"][0]["category"] == "Stay"
    assert result["days"][0]["budget"] == 150
    assert result["days"][0]["budget_items"][0]["category"] == "Food"


def test_update_without_plan_returns_false(tmp_path):
    store = _store(tmp_path)
    conversation_id = store.save(None, [{"role": "user", "content": "hi"}], [])
    assert store.update_latest_trip_plan(
        conversation_id, {"budget": 1, "currency": "", "budget_items": []}
    ) is False
