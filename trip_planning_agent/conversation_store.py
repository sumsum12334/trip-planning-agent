"""Small SQLite conversation store for the browser chat."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def _database_path(database_url: str) -> Path:
    """Resolve the conversation SQLite file.

    Chat still uses SQLite. When DATABASE_URL points at Postgres (travel
    history), conversations fall back to `./data/conversations.sqlite`.
    """
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    return Path("./data/conversations.sqlite")


class ConversationStore:
    """SQLite-backed store, safe for concurrent use within one process.

    Store instances are created per request, so read-modify-write operations
    (event appends, event rewrites) are serialized by a per-database-file
    lock shared across instances. WAL mode keeps readers and writers from
    blocking each other across threads.
    """

    _path_locks: dict[str, threading.RLock] = {}
    _path_locks_guard = threading.Lock()

    def __init__(self, database_url: str) -> None:
        self.path = _database_path(database_url)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = self._lock_for(self.path)
        with self._lock:
            with self._connection() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversations (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        messages TEXT NOT NULL,
                        events TEXT NOT NULL DEFAULT '[]',
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(conversations)")
                }
                if "events" not in columns:
                    connection.execute(
                        "ALTER TABLE conversations ADD COLUMN events TEXT NOT NULL DEFAULT '[]'"
                    )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pending_questions (
                        conversation_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        messages TEXT NOT NULL,
                        question TEXT NOT NULL,
                        options TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trip_plans (
                        conversation_id TEXT PRIMARY KEY,
                        plan TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )

    @classmethod
    def _lock_for(cls, path: Path) -> threading.RLock:
        key = str(path.resolve())
        with cls._path_locks_guard:
            if key not in cls._path_locks:
                cls._path_locks[key] = threading.RLock()
            return cls._path_locks[key]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def save(
        self,
        conversation_id: str | None,
        messages: list[dict[str, str]],
        events: list[dict[str, Any]] | None = None,
    ) -> str:
        conversation_id = conversation_id or str(uuid4())
        title = next(
            (item["content"].strip() for item in messages if item.get("role") == "user"),
            "New conversation",
        )[:80]
        updated_at = datetime.now(timezone.utc).isoformat()
        # The event append is a read-modify-write; hold the per-path lock so
        # concurrent turns on the same conversation cannot drop events.
        with self._lock:
            with self._connection() as connection:
                existing = connection.execute(
                    "SELECT events FROM conversations WHERE id = ?",
                    (conversation_id,),
                ).fetchone()
                stored_events = json.loads(existing[0]) if existing else []
                connection.execute(
                    """
                    INSERT INTO conversations (id, title, messages, events, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title,
                        messages=excluded.messages,
                        events=excluded.events,
                        updated_at=excluded.updated_at
                    """,
                    (
                        conversation_id,
                        title,
                        json.dumps(messages),
                        json.dumps(stored_events + (events or [])),
                        updated_at,
                    ),
                )
        return conversation_id

    def list(self) -> list[dict[str, str]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, title, updated_at FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
        return [
            {"id": row[0], "title": row[1], "updated_at": row[2]}
            for row in rows
        ]

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id, title, messages, events, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "title": row[1],
            "messages": json.loads(row[2]),
            "events": json.loads(row[3]),
            "updated_at": row[4],
        }

    def delete(self, conversation_id: str) -> bool:
        with self._lock:
            with self._connection() as connection:
                cursor = connection.execute(
                    "DELETE FROM conversations WHERE id = ?",
                    (conversation_id,),
                )
                connection.execute(
                    "DELETE FROM pending_questions WHERE conversation_id = ?",
                    (conversation_id,),
                )
                connection.execute(
                    "DELETE FROM trip_plans WHERE conversation_id = ?",
                    (conversation_id,),
                )
        return cursor.rowcount > 0

    def save_pending_question(
        self,
        conversation_id: str,
        user_id: str,
        messages: list[dict[str, Any]],
        question: str,
        options: list[str],
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO pending_questions
                    (conversation_id, user_id, messages, question, options, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    messages=excluded.messages,
                    question=excluded.question,
                    options=excluded.options,
                    updated_at=excluded.updated_at
                """,
                (
                    conversation_id,
                    user_id,
                    json.dumps(messages),
                    question,
                    json.dumps(options),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_pending_question(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT user_id, messages, question, options
                FROM pending_questions WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "user_id": row[0],
            "messages": json.loads(row[1]),
            "question": row[2],
            "options": json.loads(row[3]),
        }

    def clear_pending_question(self, conversation_id: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM pending_questions WHERE conversation_id = ?",
                (conversation_id,),
            )

    def get_trip_plan(self, conversation_id: str) -> dict[str, Any] | None:
        """Return the assembled trip plan stored for a conversation."""
        if not conversation_id:
            return None
        with self._connection() as connection:
            row = connection.execute(
                "SELECT plan FROM trip_plans WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None

    def save_trip_plan(self, conversation_id: str, plan: dict[str, Any]) -> None:
        """Persist the assembled trip plan for a conversation."""
        if not conversation_id:
            return
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO trip_plans (conversation_id, plan, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    plan=excluded.plan,
                    updated_at=excluded.updated_at
                """,
                (
                    conversation_id,
                    json.dumps(plan),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def set_latest_trip_plan_event(
        self, conversation_id: str, plan: dict[str, Any]
    ) -> bool:
        """Point the latest trip-plan UI event at the given assembled plan.

        Used after the user edits the budget so the browser re-renders the
        current plan; the plan itself lives in the ``trip_plans`` table.
        """
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT events FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if row is None:
                return False
            events = json.loads(row[0])
            for event in reversed(events):
                data = event.get("data", {})
                if data.get("tool") == "display_trip_plan" and isinstance(data.get("result"), dict):
                    data["result"] = plan
                    event["data"] = data
                    connection.execute(
                        "UPDATE conversations SET events = ?, updated_at = ? WHERE id = ?",
                        (
                            json.dumps(events),
                            datetime.now(timezone.utc).isoformat(),
                            conversation_id,
                        ),
                    )
                    return True
            return False

    def mark_question_answered(
        self, conversation_id: str, selected: str, question: str | None = None
    ) -> bool:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT events FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if row is None:
                return False
            events = json.loads(row[0])
            updated = False
            for event in reversed(events):
                data = event.get("data", {})
                if (
                    data.get("tool") == "ask_user_question"
                    and data.get("result")
                    and (question is None or data["result"].get("question") == question)
                    and not data.get("selected")
                ):
                    data["selected"] = selected
                    event["data"] = data
                    event["detail"] = f"Answer selected: {selected}"
                    event["status"] = "completed"
                    updated = True
                    break
            if updated:
                connection.execute(
                    "UPDATE conversations SET events = ?, updated_at = ? WHERE id = ?",
                    (
                        json.dumps(events),
                        datetime.now(timezone.utc).isoformat(),
                        conversation_id,
                    ),
                )
            return updated
