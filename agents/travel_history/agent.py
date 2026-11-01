"""Agent 4 - travel_history: previously visited locations (SQLite or Postgres)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from config.settings import get_settings
from shared.schemas import TripRequest
from .memory import extract_visited_places

StorageKind = Literal["sqlite", "postgres"]


def storage_kind(database_url: str) -> StorageKind:
    """Return the travel-history backend implied by DATABASE_URL."""
    scheme = urlparse(database_url).scheme.lower()
    if scheme in {"sqlite", ""}:
        if database_url.startswith("sqlite:///"):
            return "sqlite"
        raise ValueError(
            "Travel history requires sqlite:///... or a postgresql:// DATABASE_URL."
        )
    if scheme in {"postgresql", "postgres", "postgresql+psycopg"}:
        return "postgres"
    # SQLAlchemy-style driver suffix, e.g. postgresql+psycopg2
    if scheme.startswith("postgresql+") or scheme.startswith("postgres+"):
        return "postgres"
    raise ValueError(
        "Travel history requires sqlite:///... or a postgresql:// DATABASE_URL."
    )


def _sqlite_path(database_url: str) -> Path:
    return Path(database_url.removeprefix("sqlite:///"))


def _psycopg_conninfo(database_url: str) -> str:
    """Normalize SQLAlchemy-style URLs to a psycopg conninfo string."""
    url = database_url.strip()
    for prefix in (
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
        "postgres+psycopg://",
    ):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


class TravelHistoryStore:
    """Small storage abstraction for user-scoped visited places."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.kind = storage_kind(database_url)
        if self.kind == "sqlite":
            self.path = _sqlite_path(database_url)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as connection:
                self._ensure_sqlite_schema(connection)
        else:
            self.path = None
            with self._connection() as connection:
                self._ensure_postgres_schema(connection)

    def _connect_sqlite(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _connect_postgres(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - exercised when extra missing
            raise ImportError(
                "Postgres travel history requires psycopg. "
                "Install with: pip install 'trip-planning-agent[db]' "
                "or pip install 'psycopg[binary]'."
            ) from exc
        return psycopg.connect(_psycopg_conninfo(self.database_url))

    @contextmanager
    def _connection(self):
        if self.kind == "sqlite":
            connection = self._connect_sqlite()
            try:
                yield connection
                connection.commit()
            finally:
                connection.close()
        else:
            connection = self._connect_postgres()
            try:
                yield connection
                connection.commit()
            finally:
                connection.close()

    def _ensure_sqlite_schema(self, connection: sqlite3.Connection) -> None:
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

    def _ensure_postgres_schema(self, connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS travel_history (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                place TEXT NOT NULL,
                country TEXT,
                city TEXT,
                location TEXT,
                visited_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_travel_history_user
            ON travel_history (user_id, visited_at)
            """
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'travel_history'
                """
            )
            columns = {row[0] for row in cursor.fetchall()}
        for column in ("country", "city", "location"):
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE travel_history ADD COLUMN {column} TEXT"
                )
        connection.execute(
            "UPDATE travel_history SET location = place WHERE location IS NULL"
        )

    def list_entries(self, user_id: str) -> list[dict[str, Any]]:
        sql = """
            SELECT id, user_id, country, city, COALESCE(location, place), visited_at
            FROM travel_history
            WHERE user_id = {ph}
            ORDER BY visited_at DESC, id DESC
        """
        if self.kind == "sqlite":
            with self._connection() as connection:
                rows = connection.execute(
                    sql.format(ph="?"),
                    (user_id,),
                ).fetchall()
        else:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql.format(ph="%s"), (user_id,))
                    rows = cursor.fetchall()
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
        values = (
            cleaned_user_id,
            cleaned_place,
            country.strip() if country else None,
            city.strip() if city else None,
            cleaned_place,
            datetime.now(timezone.utc).isoformat(),
        )
        if self.kind == "sqlite":
            with self._connection() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO travel_history
                        (user_id, place, country, city, location, visited_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                return int(cursor.lastrowid)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO travel_history
                        (user_id, place, country, city, location, visited_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    values,
                )
                return int(cursor.fetchone()[0])

    def delete(self, user_id: str, entry_id: int) -> bool:
        if self.kind == "sqlite":
            with self._connection() as connection:
                cursor = connection.execute(
                    "DELETE FROM travel_history WHERE id = ? AND user_id = ?",
                    (entry_id, user_id.strip()),
                )
                return cursor.rowcount > 0
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM travel_history WHERE id = %s AND user_id = %s",
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
    try:
        kind = storage_kind(s.database_url)
    except ValueError:
        kind = "sqlite"
    return {
        "agent": "travel_history",
        "enabled": s.enable_travel_history,
        "database_url": s.database_url,
        "storage": kind,
    }
