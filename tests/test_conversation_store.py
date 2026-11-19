"""Concurrency and behavior tests for the SQLite conversation store."""

from __future__ import annotations

import threading
from pathlib import Path

from trip_planning_agent.conversation_store import ConversationStore


def test_concurrent_saves_keep_all_events(tmp_path: Path) -> None:
    url = "sqlite:///" + (tmp_path / "conc.sqlite").as_posix()
    store = ConversationStore(url)
    conversation_id = store.save(None, [{"role": "user", "content": "seed"}], [])

    errors: list[Exception] = []

    def worker(index: int) -> None:
        try:
            worker_store = ConversationStore(url)
            worker_store.save(
                conversation_id,
                [{"role": "user", "content": f"message-{index}"}],
                [{"type": "agent", "label": f"event-{index}"}],
            )
        except Exception as exc:  # pragma: no cover - surfaced by the assert
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    result = store.get(conversation_id)
    labels = [event["label"] for event in result["events"]]
    # Every concurrent turn appended exactly one event; a lost update would
    # drop some of them (read-modify-write without the per-path lock).
    assert sorted(labels) == sorted(f"event-{index}" for index in range(8))


def test_pending_question_roundtrip(tmp_path: Path) -> None:
    store = ConversationStore("sqlite:///" + (tmp_path / "p.sqlite").as_posix())
    assert store.get_pending_question("c1") is None

    store.save_pending_question(
        "c1",
        "user-1",
        [{"role": "user", "content": "plan"}],
        "Which month?",
        ["March", "April"],
    )
    pending = store.get_pending_question("c1")
    assert pending == {
        "user_id": "user-1",
        "messages": [{"role": "user", "content": "plan"}],
        "question": "Which month?",
        "options": ["March", "April"],
    }

    # A new question replaces the old one.
    store.save_pending_question("c1", "user-1", [], "Which city?", ["Osaka"])
    assert store.get_pending_question("c1")["question"] == "Which city?"

    store.clear_pending_question("c1")
    assert store.get_pending_question("c1") is None
    # Clearing an unknown conversation is a no-op.
    store.clear_pending_question("c1")


def test_trip_plan_persistence_and_event_rewrite(tmp_path: Path) -> None:
    store = ConversationStore("sqlite:///" + (tmp_path / "t.sqlite").as_posix())
    conversation_id = store.save(None, [{"role": "user", "content": "hi"}], [])
    assert store.get_trip_plan(conversation_id) is None

    plan = {"destination": "Tokyo", "budget": 500, "days": []}
    store.save_trip_plan(conversation_id, plan)
    assert store.get_trip_plan(conversation_id)["budget"] == 500

    # A plan event in the conversation can be repointed at the edited plan.
    event = {
        "type": "tool",
        "label": "Trip plan updated (start_trip_plan)",
        "status": "completed",
        "data": {"tool": "display_trip_plan", "result": {"destination": "Tokyo"}},
    }
    store.save(conversation_id, [], [event])
    edited = {"destination": "Tokyo", "budget": 350, "days": []}
    assert store.set_latest_trip_plan_event(conversation_id, edited) is True
    stored = store.get(conversation_id)
    assert stored["events"][-1]["data"]["result"]["budget"] == 350
    # Unknown conversation has no event to rewrite.
    assert store.set_latest_trip_plan_event("missing", edited) is False


def test_mark_question_answered_updates_latest_event(tmp_path: Path) -> None:
    store = ConversationStore("sqlite:///" + (tmp_path / "q.sqlite").as_posix())
    conversation_id = store.save(None, [], [])
    question_event = {
        "type": "tool",
        "label": "ask_user_question result received",
        "status": "running",
        "detail": "Which month?",
        "data": {
            "tool": "ask_user_question",
            "result": {"question": "Which month?", "options": ["March", "April"], "status": "awaiting_user"},
        },
    }
    store.save(conversation_id, [], [question_event])

    assert store.mark_question_answered(conversation_id, "March", "Which month?") is True
    stored = store.get(conversation_id)
    updated = stored["events"][-1]
    assert updated["data"]["selected"] == "March"
    assert updated["status"] == "completed"
    assert updated["detail"] == "Answer selected: March"
    # Second call does not overwrite a different (already answered) event.
    assert store.mark_question_answered(conversation_id, "April", "Which month?") is False
    # Unknown conversation reports False.
    assert store.mark_question_answered("missing", "March") is False
