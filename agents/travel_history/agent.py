"""Agent 4 - travel_history: previously visited locations backed by SQLite."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import get_settings
from shared.schemas import TripRequest
from .memory import extract_visited_places


def _database_path(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Travel history currently requires a SQLite DATABASE_URL.")
    return Path(database_url.removeprefix("sqlite:///"))


class TravelHistoryStore:
    """Small storage abstraction for user-scoped visited places."""

    def __init__(self, database_url: str) -> None:
        self.path = _database_path(database_url)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS travel_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    place TEXT NOT NULL,
                    country TEXT,
                    city TEXT,
                    location TEXT,
                    visited_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(travel_history)")
            }
            if "country" not in columns:
                connection.execute("ALTER TABLE travel_history ADD COLUMN country TEXT")
            if "city" not in columns:
                connection.execute("ALTER TABLE travel_history ADD COLUMN city TEXT")
            if "location" not in columns:
                connection.execute("ALTER TABLE travel_history ADD COLUMN location TEXT")
            connection.execute(
                "UPDATE travel_history SET location = place WHERE location IS NULL"
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_travel_history_user
                ON travel_history (user_id, visited_at)
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

    def list_entries(self, user_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, country, city, COALESCE(location, place), visited_at
                FROM travel_history
                WHERE user_id = ?
                ORDER BY visited_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "user_id": row[1],
                "country": row[2],
                "city": row[3],
                "location": row[4],
                "visited_at": row[5],
            }
            for row in rows
        ]

    def list_places(self, user_id: str) -> list[str]:
        return list(dict.fromkeys(entry["location"] for entry in self.list_entries(user_id)))

    def search(self, user_id: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
        terms = [term.casefold() for term in query.split() if term.strip()]
        return [
            entry
            for entry in self.list_entries(user_id)
            if not terms
            or all(
                term in " ".join(
                    filter(None, [entry["country"], entry["city"], entry["location"]])
                ).casefold()
                for term in terms
            )
        ][:limit]

    def record_visit(
        self,
        user_id: str,
        place: str,
        *,
        country: str | None = None,
        city: str | None = None,
    ) -> int:
        cleaned_user_id = user_id.strip()
        cleaned_place = place.strip()
        if not cleaned_user_id or not cleaned_place:
            raise ValueError("Travel history records require a user_id and place.")
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO travel_history
                    (user_id, place, country, city, location, visited_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    cleaned_user_id,
                    cleaned_place,
                    country.strip() if country else None,
                    city.strip() if city else None,
                    cleaned_place,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def delete(self, user_id: str, entry_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM travel_history WHERE id = ? AND user_id = ?",
                (entry_id, user_id.strip()),
            )
        return cursor.rowcount > 0

    def add_entry(
        self,
        *,
        user_id: str,
        country: str | None,
        city: str | None,
        location: str,
    ) -> int:
        return self.record_visit(user_id, location, country=country, city=city)


def run(request: TripRequest) -> list[str]:
    """Return previously visited place names for this user."""
    settings = get_settings()
    if not settings.enable_travel_history:
        return []
    if not request.user_id:
        return []
    return TravelHistoryStore(settings.database_url).list_places(request.user_id)


def remember_from_message(user_id: str, message: str) -> list[str]:
    """Persist only places explicitly described as previously visited."""
    settings = get_settings()
    if not settings.enable_travel_history:
        return []
    places = extract_visited_places(message)
    if not places:
        return []
    store = TravelHistoryStore(settings.database_url)
    for place in places:
        store.record_visit(user_id, place)
    return places


def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "agent": "travel_history",
        "enabled": s.enable_travel_history,
        "database_url": s.database_url,
        "storage": "sqlite",
    }
