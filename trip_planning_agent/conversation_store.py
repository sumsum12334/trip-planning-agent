"""Small SQLite conversation store for the browser chat."""

from __future__ import annotations

import json
import sqlite3
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
    def __init__(self, database_url: str) -> None:
        self.path = _database_path(database_url)
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

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
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM conversations WHERE id = ?",
                (conversation_id,),
            )
            connection.execute(
                "DELETE FROM pending_questions WHERE conversation_id = ?",
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

    def update_latest_trip_plan(
        self, conversation_id: str, updates: dict[str, Any]
    ) -> bool:
        """Overwrite the budget fields on the latest display_trip_plan event.

        Used when the user edits the trip budget so the change survives reloads
        and is available to the next model turn.
        """
        with self._connection() as connection:
            row = connection.execute(
                "SELECT events FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if row is None:
                return False
            events = json.loads(row[0])
            for event in reversed(events):
                data = event.get("data", {})
                result = data.get("result")
                if data.get("tool") == "display_trip_plan" and isinstance(result, dict):
                    result["budget"] = updates.get("budget")
                    if updates.get("currency") is not None:
                        result["currency"] = updates["currency"]
                    result["budget_items"] = updates.get("budget_items", [])
                    currency = updates.get("currency") or ""
                    day_budgets = {
                        int(item["day"]): item.get("amount")
                        for item in updates.get("day_budgets", [])
                        if isinstance(item, dict)
                        and isinstance(item.get("day"), (int, float))
                        and not isinstance(item.get("day"), bool)
                    }
                    day_items: dict[int, list[dict[str, Any]]] = {}
                    for item in updates.get("day_items", []):
                        if (
                            isinstance(item, dict)
                            and isinstance(item.get("day"), (int, float))
                            and not isinstance(item.get("day"), bool)
                        ):
                            day_items.setdefault(int(item["day"]), []).append(
                                {
                                    "category": str(item.get("category", "")).strip(),
                                    "amount": item.get("amount"),
                                    "currency": currency,
                                }
                            )
                    for day in result.get("days", []):
                        if not isinstance(day, dict):
                            continue
                        if day.get("day") in day_budgets:
                            day["budget"] = day_budgets[day["day"]]
                        if day.get("day") in day_items:
                            day["budget_items"] = day_items[day["day"]]
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
        with self._connection() as connection:
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
