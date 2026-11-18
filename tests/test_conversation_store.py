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
