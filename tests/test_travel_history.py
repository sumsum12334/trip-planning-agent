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


def test_extract_visited_places_keeps_real_places() -> None:
    from agents.travel_history.memory import extract_visited_places

    assert extract_visited_places("I have gone to the Peak before.") == [
        "Victoria Peak"
    ]
    assert extract_visited_places("I went to Japan last year.") == ["Japan"]
    assert extract_visited_places("I visited Kyoto in 2019 and loved it.") == [
        "Kyoto"
    ]
    assert extract_visited_places(
        "I have been to Tokyo before and I love hiking."
    ) == ["Tokyo"]


def test_extract_visited_places_drops_non_place_phrases() -> None:
    from agents.travel_history.memory import extract_visited_places

    assert extract_visited_places("I went to bed early yesterday.") == []
    assert extract_visited_places("I have been to the doctor twice.") == []
    assert extract_visited_places("After work I go to the gym.") == []
    assert extract_visited_places("We went home late.") == []


def test_extract_visited_places_ignores_clauses() -> None:
    from agents.travel_history.memory import extract_visited_places

    assert (
        extract_visited_places(
            "I went to a very small town near the mountains far away from here."
        )
        == []
    )



def test_list_places_uses_cache_after_first_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.travel_history.agent import clear_travel_history_cache

    clear_travel_history_cache()
    url = f"sqlite:///{tmp_path / 'history.sqlite'}"
    store = TravelHistoryStore(url)
    store.record_visit("u1", "Kyoto", country="JP", city="Kyoto")

    fetches = {"n": 0}
    original = TravelHistoryStore._fetch_entries

    def wrapped(self: TravelHistoryStore, user_id: str):
        fetches["n"] += 1
        return original(self, user_id)

    monkeypatch.setattr(TravelHistoryStore, "_fetch_entries", wrapped)

    assert store.list_places("u1") == ["Kyoto"]
    assert store.list_places("u1") == ["Kyoto"]
    assert TravelHistoryStore(url).list_places("u1") == ["Kyoto"]
    assert store.search("u1", "kyoto")[0]["location"] == "Kyoto"
    assert fetches["n"] == 1

    store.record_visit("u1", "Osaka", country="JP", city="Osaka")
    assert store.list_places("u1") == ["Osaka", "Kyoto"]
    assert fetches["n"] == 2
    store.list_entries("u1", fresh=True)
    assert fetches["n"] == 3


def test_cache_is_isolated_by_user_and_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url_a = f"sqlite:///{tmp_path / 'a.sqlite'}"
    url_b = f"sqlite:///{tmp_path / 'b.sqlite'}"
    store_a = TravelHistoryStore(url_a)
    store_b = TravelHistoryStore(url_b)
    store_a.record_visit("u1", "Kyoto")
    store_a.record_visit("u2", "Tokyo")
    store_b.record_visit("u1", "Taipei")

    fetches = {"n": 0}
    original = TravelHistoryStore._fetch_entries

    def wrapped(self: TravelHistoryStore, user_id: str):
        fetches["n"] += 1
        return original(self, user_id)

    monkeypatch.setattr(TravelHistoryStore, "_fetch_entries", wrapped)

    assert store_a.list_places("u1") == ["Kyoto"]
    assert store_a.list_places("u2") == ["Tokyo"]
    assert store_b.list_places("u1") == ["Taipei"]
    assert fetches["n"] == 3
    assert store_a.list_places("u1") == ["Kyoto"]
    assert fetches["n"] == 3

    store_a.record_visit("u1", "Osaka")
    assert store_a.list_places("u1") == ["Osaka", "Kyoto"]
    assert store_a.list_places("u2") == ["Tokyo"]
    assert fetches["n"] == 4


def test_schema_is_ensured_once_per_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.travel_history.agent import clear_travel_history_cache

    clear_travel_history_cache()
    url = f"sqlite:///{tmp_path / 'history.sqlite'}"
    ensures = {"n": 0}
    original = TravelHistoryStore._ensure_sqlite_schema

    def wrapped(self: TravelHistoryStore, connection) -> None:
        ensures["n"] += 1
        return original(self, connection)

    monkeypatch.setattr(TravelHistoryStore, "_ensure_sqlite_schema", wrapped)
    TravelHistoryStore(url)
    TravelHistoryStore(url)
    TravelHistoryStore(url).list_places("u1")
    assert ensures["n"] == 1


def test_delete_and_update_invalidate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"sqlite:///{tmp_path / 'history.sqlite'}"
    store = TravelHistoryStore(url)
    first = store.record_visit("u1", "Kyoto", country="JP", city="Kyoto")
    store.record_visit("u1", "Osaka", country="JP", city="Osaka")
    assert "Kyoto" in store.list_places("u1")

    fetches = {"n": 0}
    original = TravelHistoryStore._fetch_entries

    def wrapped(self: TravelHistoryStore, user_id: str):
        fetches["n"] += 1
        return original(self, user_id)

    monkeypatch.setattr(TravelHistoryStore, "_fetch_entries", wrapped)
    assert store.list_places("u1")  # cached from the earlier list
    assert fetches["n"] == 0

    assert store.update(first, "u1", "JP", "Kyoto", "Fushimi") is True
    assert store.list_places("u1") == ["Osaka", "Fushimi"]
    assert fetches["n"] == 1
    assert store.delete("u1", first) is True
    assert store.list_places("u1") == ["Osaka"]
    assert fetches["n"] == 2
