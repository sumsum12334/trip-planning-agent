"""Tests for travel history storage backends."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agents.travel_history.agent import (
    TravelHistoryStore,
    health,
    storage_kind,
    _psycopg_conninfo,
)
from trip_planning_agent.conversation_store import _database_path as conversation_path


def test_storage_kind_sqlite_and_postgres_urls() -> None:
    assert storage_kind("sqlite:///./data/travel_history.sqlite") == "sqlite"
    assert storage_kind("postgresql://trip:trip@localhost:5432/travel_history") == "postgres"
    assert (
        storage_kind("postgresql+psycopg://trip:trip@localhost:5432/travel_history")
        == "postgres"
    )
    assert storage_kind("postgres://trip:trip@localhost:5432/travel_history") == "postgres"
    with pytest.raises(ValueError):
        storage_kind("mysql://localhost/db")


def test_psycopg_conninfo_normalizes_sqlalchemy_style() -> None:
    assert (
        _psycopg_conninfo("postgresql+psycopg://trip:trip@localhost:5432/travel_history")
        == "postgresql://trip:trip@localhost:5432/travel_history"
    )
    assert (
        _psycopg_conninfo("postgres://trip:trip@localhost:5432/travel_history")
        == "postgresql://trip:trip@localhost:5432/travel_history"
    )


def test_sqlite_store_roundtrip(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'history.sqlite'}"
    store = TravelHistoryStore(url)
    assert store.kind == "sqlite"
    entry_id = store.record_visit("u1", "Victoria Peak", country="HK", city="Hong Kong")
    assert entry_id > 0
    assert store.list_places("u1") == ["Victoria Peak"]
    rows = store.search("u1", "peak")
    assert len(rows) == 1
    assert rows[0]["location"] == "Victoria Peak"
    assert store.delete("u1", entry_id) is True
    assert store.list_places("u1") == []


def test_conversation_store_falls_back_when_database_url_is_postgres() -> None:
    path = conversation_path("postgresql://trip:trip@localhost:5432/travel_history")
    assert path == Path("./data/conversations.sqlite")
    assert conversation_path("sqlite:///./data/travel_history.sqlite") == Path(
        "./data/travel_history.sqlite"
    )


def test_health_reports_storage_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://trip:trip@localhost:5432/travel_history")
    settings_mod.get_settings.cache_clear()
    try:
        payload = health()
        assert payload["storage"] == "postgres"
    finally:
        settings_mod.get_settings.cache_clear()


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL", "").startswith(("postgres", "postgresql")),
    reason="Set TEST_DATABASE_URL=postgresql://... to run live Postgres checks",
)
def test_postgres_store_roundtrip_optional() -> None:
    url = os.environ["TEST_DATABASE_URL"]
    store = TravelHistoryStore(url)
    assert store.kind == "postgres"
    user_id = "pytest-pg-user"
    entry_id = store.record_visit(user_id, "Shibuya", country="JP", city="Tokyo")
    try:
        assert entry_id > 0
        assert "Shibuya" in store.list_places(user_id)
    finally:
        store.delete(user_id, entry_id)
