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
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Conversation storage currently requires a SQLite DATABASE_URL.")
    return Path(database_url.removeprefix("sqlite:///"))


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
        return cursor.rowcount > 0
