"""Tests for Agent 1 search_stays (stub mode)."""

from __future__ import annotations

import pytest

from agents.search_stays.agent import health, run
from agents.search_stays.tools import nightly_budget_cap, search_stays
from shared.schemas import TripRequest


def test_stub_search_tokyo_respects_budget_and_returns_results():
    req = TripRequest(destination="Tokyo", budget=400, days=4, interests=["food"])
    stays = run(req)
    assert stays, "expected non-empty stub results for Tokyo"
    assert 1 <= len(stays) <= 5
    cap = nightly_budget_cap(req.budget, req.days)
    assert cap == 100.0
    for stay in stays:
        assert stay.nightly_cost is not None
        assert stay.nightly_cost <= cap
        assert "tokyo" in stay.location.casefold()
        assert stay.notes and "stub" in stay.notes.casefold()
    costs = [s.nightly_cost for s in stays if s.nightly_cost is not None]
    assert costs == sorted(costs)


def test_excluded_locations_filters_name_or_location():
    req = TripRequest(destination="Tokyo", budget=400, days=4)
    all_stays = run(req)
    assert all_stays
    # Exclude by location token that appears in Tokyo Shinjuku / Shibuya / Asakusa rows
    filtered = run(req, excluded_locations=["Shinjuku", "capsule"])
    names = {s.name for s in filtered}
    locations = {s.location.casefold() for s in filtered}
    assert all("shinjuku" not in loc for loc in locations)
    assert all("capsule" not in name.casefold() for name in names)
    assert len(filtered) < len(all_stays)


def test_stub_generic_fallback_for_unknown_city():
    stays = search_stays(destination="Atlantis", budget=300, days=3)
    assert stays, "expected generic catalog fallback"
    assert all("generic" in s.location.casefold() for s in stays)
    cap = nightly_budget_cap(300, 3)
    assert all(s.nightly_cost is not None and s.nightly_cost <= cap for s in stays)


def test_health_reports_stub_catalog():
    info = health()
    assert info["agent"] == "search_stays"
    assert info["tool_mode"] == "stub"
    assert info["provider_configured"] is True
    assert "catalog" in info


def test_api_mode_raises(monkeypatch):
    from config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setenv("TOOL_STAYS_MODE", "api")
    settings_mod.get_settings.cache_clear()
    with pytest.raises(NotImplementedError):
        search_stays(destination="Tokyo", budget=200, days=2)
    monkeypatch.delenv("TOOL_STAYS_MODE", raising=False)
    settings_mod.get_settings.cache_clear()


def test_city_level_history_does_not_drop_all_stays():
    req = TripRequest(destination="Tokyo", budget=800, days=4)
    all_stays = run(req)
    kept = run(req, excluded_locations=["Tokyo", "tokyo"])
    assert [stay.location for stay in kept] == [stay.location for stay in all_stays]
    narrowed = run(req, excluded_locations=["shibuya"])
    assert all("shibuya" not in stay.location.casefold() for stay in narrowed)
    assert len(narrowed) < len(all_stays)


def test_empty_destination_fails_closed():
    with pytest.raises(ValueError, match="destination"):
        search_stays(destination="")
    with pytest.raises(ValueError, match="destination"):
        search_stays(destination="   ")
