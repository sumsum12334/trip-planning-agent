"""Agent 4 - travel_history: previously visited locations (SQLite or Postgres)."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from config.settings import get_settings
from shared.schemas import TripRequest
from .memory import extract_visited_places

StorageKind = Literal["sqlite", "postgres"]

_schema_lock = threading.Lock()
_schema_ensured: set[str] = set()
_cache_lock = threading.Lock()
_entries_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}


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


def _backend_key(database_url: str) -> str:
    """Stable in-process key that does not keep the raw URL (it may contain a password)."""
    return hashlib.sha256(database_url.encode("utf-8")).hexdigest()


def _copy_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(entry) for entry in entries]


def clear_travel_history_cache() -> None:
    """Drop the in-process entry cache and schema-ensure markers (used by tests)."""
    with _cache_lock:
        _entries_cache.clear()
    with _schema_lock:
        _schema_ensured.clear()


class TravelHistoryStore:
    """Small storage abstraction for user-scoped visited places.

    Reads are served from an in-process cache after the first fetch for a
    user. The cache is invalidated on writes. Pass ``fresh=True`` to
    ``list_entries`` to reload from the database (for example the History page).
    Schema setup runs once per process per database URL.
    """

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.kind = storage_kind(database_url)
        if self.kind == "sqlite":
            self.path = _sqlite_path(database_url)
            self.path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.path = None
        self._ensure_schema()

    def _cache_key(self, user_id: str) -> tuple[str, str]:
        return (_backend_key(self.database_url), user_id)

    def _cached_entries(self, user_id: str) -> list[dict[str, Any]] | None:
        with _cache_lock:
            cached = _entries_cache.get(self._cache_key(user_id))
            return _copy_entries(cached) if cached is not None else None

    def _store_entries(self, user_id: str, entries: list[dict[str, Any]]) -> None:
        with _cache_lock:
            _entries_cache[self._cache_key(user_id)] = _copy_entries(entries)

    def _invalidate_user(self, user_id: str) -> None:
        with _cache_lock:
            _entries_cache.pop(self._cache_key(user_id), None)

    def _ensure_schema(self) -> None:
        key = _backend_key(self.database_url)
        with _schema_lock:
            if key in _schema_ensured:
                return
            with self._connection() as connection:
                if self.kind == "sqlite":
                    self._ensure_sqlite_schema(connection)
                else:
                    self._ensure_postgres_schema(connection)
            _schema_ensured.add(key)

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

    def _fetch_entries(self, user_id: str) -> list[dict[str, Any]]:
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

    def list_entries(self, user_id: str, *, fresh: bool = False) -> list[dict[str, Any]]:
        cleaned = user_id.strip()
        if not fresh:
            cached = self._cached_entries(cleaned)
            if cached is not None:
                return cached
        entries = self._fetch_entries(cleaned)
        self._store_entries(cleaned, entries)
        return deepcopy(entries)

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
                entry_id = int(cursor.lastrowid)
        else:
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
                    entry_id = int(cursor.fetchone()[0])
        self._invalidate_user(cleaned_user_id)
        return entry_id

    def delete(self, user_id: str, entry_id: int) -> bool:
        cleaned_user_id = user_id.strip()
        if self.kind == "sqlite":
            with self._connection() as connection:
                cursor = connection.execute(
                    "DELETE FROM travel_history WHERE id = ? AND user_id = ?",
                    (entry_id, cleaned_user_id),
                )
                deleted = cursor.rowcount > 0
        else:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM travel_history WHERE id = %s AND user_id = %s",
                        (entry_id, cleaned_user_id),
                    )
                    deleted = cursor.rowcount > 0
        if deleted:
            self._invalidate_user(cleaned_user_id)
        return deleted

    def update(self, entry_id: int, user_id: str, country: str | None, city: str | None, location: str) -> bool:
        """Update a travel history entry."""
        cleaned_user_id = user_id.strip()
        cleaned_country = country.strip() if country else None
        cleaned_city = city.strip() if city else None
        cleaned_location = location.strip()
        if not cleaned_user_id or not cleaned_location:
            raise ValueError("Travel history records require a user_id and location.")
        if self.kind == "sqlite":
            with self._connection() as connection:
                cursor = connection.execute(
                    """
                    UPDATE travel_history
                    SET country = ?, city = ?, location = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (cleaned_country, cleaned_city, cleaned_location, entry_id, cleaned_user_id),
                )
                updated = cursor.rowcount > 0
        else:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE travel_history
                        SET country = %s, city = %s, location = %s
                        WHERE id = %s AND user_id = %s
                        """,
                        (cleaned_country, cleaned_city, cleaned_location, entry_id, cleaned_user_id),
                    )
                    updated = cursor.rowcount > 0
        if updated:
            self._invalidate_user(cleaned_user_id)
        return updated

    def get(self, user_id: str, entry_id: int) -> dict[str, Any] | None:
        """Get a single travel history entry by ID."""
        cleaned = user_id.strip()
        cached = self._cached_entries(cleaned)
        if cached is not None:
            for entry in cached:
                if entry["id"] == entry_id:
                    return entry
            return None
        sql = """
            SELECT id, user_id, country, city, COALESCE(location, place), visited_at
            FROM travel_history
            WHERE user_id = {ph} AND id = {ph}
        """
        if self.kind == "sqlite":
            with self._connection() as connection:
                row = connection.execute(
                    sql.format(ph="?"),
                    (cleaned, entry_id),
                ).fetchone()
        else:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql.format(ph="%s"), (cleaned, entry_id))
                    row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "user_id": row[1],
            "country": row[2],
            "city": row[3],
            "location": row[4],
            "visited_at": row[5],
        }

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
