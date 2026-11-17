"""Tests for Agent 3 coordinator itinerary rendering."""

from __future__ import annotations

from datetime import date

import pytest

from agents.coordinator.agent import NoFeasiblePlanError, revise, run, trip_length
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


def test_revise_steps_down_from_over_budget_stay():
    req = TripRequest(
        destination="Tokyo",
        origin="Tokyo Haneda Airport",
        budget=370,
        days=3,
    )
    itinerary = run(req)
    stay = itinerary.days[0].stays[0]
    assert stay.name == "Shinjuku Business Hotel"
    assert itinerary.total_estimated_cost is not None
    assert itinerary.total_estimated_cost <= 370
    assert any(
        "Revised stay from Asakusa Traditional Ryokan to Shinjuku Business Hotel" in note
        for note in itinerary.notes
    )


def test_under_budget_plan_is_not_revised():
    req = TripRequest(
        destination="Hong Kong",
        origin="Hong Kong Airport",
        days=1,
        budget=400,
    )
    itinerary = run(req)
    assert itinerary.total_estimated_cost is not None
    assert itinerary.total_estimated_cost <= 400
    assert all("Revised stay" not in note for note in itinerary.notes)
    assert all("Revise could not meet budget" not in note for note in itinerary.notes)


def test_fail_closed_when_all_stays_over_budget():
    req = TripRequest(destination="Hong Kong", origin="Hong Kong Airport", days=1, budget=30)
    with pytest.raises(NoFeasiblePlanError, match="all candidates over budget"):
        run(req)


def test_fail_closed_when_revise_cannot_meet_budget():
    req = TripRequest(
        destination="Tokyo",
        origin="Narita Airport",
        budget=180,
        days=3,
    )
    with pytest.raises(NoFeasiblePlanError, match="still exceeds budget after revise"):
        run(req)


def test_plan_currency_is_single_per_city():
    hk = run(
        TripRequest(destination="Hong Kong", origin="Hong Kong Airport", days=1, budget=400)
    )
    assert hk.currency == "HKD"
    tokyo = run(
        TripRequest(destination="Tokyo", origin="Tokyo Shinjuku", budget=400, days=3)
    )
    assert tokyo.currency == "USD"
    for day in tokyo.days:
        for stay in day.stays:
            assert stay.currency == "USD"
        for leg in day.transports:
            assert leg.currency in (None, "USD")


def test_mixed_currency_components_fail_closed(monkeypatch):
    from agents.coordinator import agent as coordinator_agent
    from shared.schemas import StayCandidate

    def fake_search(request, excluded_locations=()):
        return [
            StayCandidate(
                name="Euro Hotel",
                location="Tokyo Asakusa",
                nightly_cost=90.0,
                currency="EUR",
                rating=4.0,
                source_url="https://example.com/stays/euro",
            )
        ]

    monkeypatch.setattr(coordinator_agent, "search_stays", fake_search)
    with pytest.raises(NoFeasiblePlanError, match="mix currencies"):
        coordinator_agent.run(
            TripRequest(destination="Tokyo", origin="Tokyo Shinjuku", budget=400, days=3)
        )


def test_unlabeled_costs_skip_budget_enforcement(monkeypatch):
    from agents.coordinator import agent as coordinator_agent
    from shared.schemas import StayCandidate

    def fake_search(request, excluded_locations=()):
        return [
            StayCandidate(
                name="No-Currency Hotel",
                location="Tokyo Central",
                nightly_cost=90.0,
                currency=None,
                rating=4.0,
            )
        ]

    monkeypatch.setattr(coordinator_agent, "search_stays", fake_search)
    itinerary = coordinator_agent.run(
        TripRequest(destination="Tokyo", origin="Tokyo Shinjuku", budget=10, days=3)
    )
    assert itinerary.currency is None
    assert any("Budget not enforced" in note for note in itinerary.notes)


def test_revise_reenters_pipeline_and_notes_budget_change():
    initial = run(
        TripRequest(
            destination="Hong Kong",
            origin="Hong Kong Airport",
            days=3,
            budget=600,
        )
    )
    revised = revise(
        TripRequest(
            destination="Hong Kong",
            origin="Hong Kong Airport",
            days=3,
            budget=350,
        ),
        initial,
    )
    assert any(
        "budget" in note.casefold() and "350" in note for note in revised.notes
    )
    assert revised.request.budget == 350
    assert revised.total_estimated_cost is not None
    assert revised.total_estimated_cost <= 350
    assert len(revised.days) == 3


def test_revise_notes_trip_length_change():
    initial = run(
        TripRequest(destination="Tokyo", origin="Tokyo Shinjuku", days=4, budget=800)
    )
    revised = revise(
        TripRequest(destination="Tokyo", origin="Tokyo Shinjuku", days=2, budget=800),
        initial,
    )
    assert any(
        "trip length" in note.casefold() and "2" in note for note in revised.notes
    )
    assert len(revised.days) == 2


def test_revise_rejects_destination_change():
    initial = run(
        TripRequest(destination="Tokyo", origin="Tokyo Shinjuku", days=2, budget=400)
    )
    with pytest.raises(ValueError, match="same destination"):
        revise(
            TripRequest(destination="Hong Kong", origin="Hong Kong Airport", days=2, budget=400),
            initial,
        )


def test_summary_notes_from_model(monkeypatch):
    from agents.coordinator import agent as coordinator_agent

    class FakeTACC:
        configured = True

        def complete(self, prompt, **kwargs):
            assert "JSON" in prompt
            return {
                "ok": True,
                "stub": False,
                "text": '{"notes": ["Stay fits the budget", "Arrival by metro"]}',
            }

    monkeypatch.setattr(coordinator_agent, "TACCClient", lambda settings=None: FakeTACC())
    itinerary = run(
        TripRequest(destination="Hong Kong", origin="Hong Kong Airport", days=1, budget=400)
    )
    assert any(
        note.startswith("Model summary: Stay fits the budget")
        for note in itinerary.notes
    )


def test_summary_skipped_for_stub_response(monkeypatch):
    from agents.coordinator import agent as coordinator_agent

    class FakeTACC:
        configured = True

        def complete(self, prompt, **kwargs):
            return {"ok": False, "stub": True, "text": "[Model stub] set endpoint"}

    monkeypatch.setattr(coordinator_agent, "TACCClient", lambda settings=None: FakeTACC())
    itinerary = run(
        TripRequest(destination="Hong Kong", origin="Hong Kong Airport", days=1, budget=400)
    )
    assert all(not note.startswith("Model summary:") for note in itinerary.notes)


def test_summary_tolerates_malformed_model_output(monkeypatch):
    from agents.coordinator import agent as coordinator_agent

    class FakeTACC:
        configured = True

        def complete(self, prompt, **kwargs):
            return {"ok": True, "stub": False, "text": "not json at all"}

    monkeypatch.setattr(coordinator_agent, "TACCClient", lambda settings=None: FakeTACC())
    itinerary = run(
        TripRequest(destination="Hong Kong", origin="Hong Kong Airport", days=1, budget=400)
    )
    assert all(not note.startswith("Model summary:") for note in itinerary.notes)


