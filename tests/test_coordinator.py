"""Tests for Agent 3 coordinator itinerary rendering."""

from __future__ import annotations

from datetime import date

import pytest

from agents.coordinator.agent import run, trip_length
from shared.schemas import TripRequest


@pytest.fixture(autouse=True)
def _stub_model_and_tools(monkeypatch):
    from config import settings as settings_mod

    monkeypatch.setenv("QWEN_BASE_URL", "")
    monkeypatch.setenv("LANGFUSE_ENABLED", "0")
    monkeypatch.setenv("TOOL_STAYS_MODE", "stub")
    monkeypatch.setenv("TOOL_MAPS_MODE", "stub")
    monkeypatch.setenv("ENABLE_TRAVEL_HISTORY", "0")
    settings_mod.get_settings.cache_clear()
    yield
    settings_mod.get_settings.cache_clear()


def test_trip_length_prefers_days_then_inclusive_dates():
    assert trip_length(TripRequest(destination="Tokyo", days=3)) == 3
    assert trip_length(
        TripRequest(
            destination="Tokyo",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 3),
        )
    ) == 3
    assert trip_length(TripRequest(destination="Tokyo")) == 1


def test_multi_day_plan_emits_one_day_per_request():
    req = TripRequest(
        destination="Tokyo",
        origin="Tokyo Shinjuku",
        budget=400,
        days=3,
    )
    itinerary = run(req)
    assert [day.day_index for day in itinerary.days] == [1, 2, 3]
    stay_names = {stay.name for day in itinerary.days for stay in day.stays}
    assert stay_names, "expected a chosen stay on the itinerary"
    assert all(day.stays and day.stays[0].name == next(iter(stay_names)) for day in itinerary.days)
    assert len(itinerary.days[0].transports) == 1
    assert itinerary.days[1].transports == []
    assert itinerary.days[2].transports == []
    stay = itinerary.days[0].stays[0]
    arrival = itinerary.days[0].transports[0]
    expected = (stay.nightly_cost or 0) * 3 + (arrival.cost or 0)
    assert itinerary.total_estimated_cost == expected
    assert sum(day.estimated_cost or 0 for day in itinerary.days) == expected


def test_single_day_plan_still_has_arrival_transport():
    req = TripRequest(destination="Hong Kong", origin="Hong Kong Airport", days=1, budget=200)
    itinerary = run(req)
    assert len(itinerary.days) == 1
    assert itinerary.days[0].day_index == 1
    assert itinerary.days[0].transports
    assert itinerary.days[0].stays


def test_multi_day_plan_packs_unique_pois():
    req = TripRequest(destination="Tokyo", origin="Tokyo Shinjuku", budget=400, days=3)
    itinerary = run(req)
    all_pois = [poi for day in itinerary.days for poi in day.pois]
    assert all(day.pois for day in itinerary.days)
    assert len(all_pois) == len(set(all_pois))
    assert len(all_pois) >= 6


def test_interest_food_ranks_food_pois_first():
    req = TripRequest(
        destination="Tokyo",
        origin="Tokyo Shinjuku",
        budget=400,
        days=1,
        interests=["food"],
    )
    itinerary = run(req)
    assert itinerary.days[0].pois
    assert itinerary.days[0].pois[0] in {"Tsukiji Outer Market", "Ichiran Shibuya"}


def test_avoid_visited_skips_named_pois(tmp_path, monkeypatch):
    from agents.travel_history.agent import TravelHistoryStore
    from config import settings as settings_mod

    url = f"sqlite:///{(tmp_path / 'history.sqlite').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("ENABLE_TRAVEL_HISTORY", "1")
    settings_mod.get_settings.cache_clear()
    TravelHistoryStore(url).record_visit("poi-eval-user", "Shibuya Crossing")
    req = TripRequest(
        destination="Tokyo",
        origin="Tokyo Shinjuku",
        budget=400,
        days=3,
        avoid_visited=True,
        user_id="poi-eval-user",
    )
    itinerary = run(req)
    all_pois = [poi for day in itinerary.days for poi in day.pois]
    assert all("shibuya crossing" not in poi.casefold() for poi in all_pois)
    assert all_pois
