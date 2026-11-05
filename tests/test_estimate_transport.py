"""Tests for Agent 2 estimate_transport (stub mode)."""

from __future__ import annotations

import pytest

from agents.estimate_transport.agent import health, run
from agents.estimate_transport.tools import estimate_transport, match_catalog_row
from shared.schemas import TripRequest


def test_stub_tokyo_returns_sensible_leg():
    req = TripRequest(destination="Tokyo", origin="Shibuya")
    leg = run(req, "Shibuya", "Shinjuku")
    assert leg.from_place == "Shibuya"
    assert leg.to_place == "Shinjuku"
    assert leg.mode in {"metro", "train", "walk", "bus", "tram", "taxi", "bike", "airport_express"}
    assert leg.duration_minutes is not None and leg.duration_minutes > 0
    assert leg.cost is not None and leg.cost >= 0
    assert leg.source_url
    assert leg.notes and "stub" in leg.notes.casefold()
    matched = match_catalog_row("Shibuya Tokyo", "Shinjuku Tokyo")
    assert matched is not None


def test_stub_hong_kong_airport_leg():
    req = TripRequest(destination="Hong Kong")
    leg = run(req, "Hong Kong Airport", "Central")
    assert leg.duration_minutes is not None and leg.duration_minutes > 0
    assert leg.mode in {"airport_express", "metro", "train", "taxi", "bus"}
    assert leg.notes and "stub" in leg.notes.casefold()


def test_same_place_returns_short_walk():
    req = TripRequest(destination="Amsterdam")
    leg = run(req, "Dam Square", "Dam Square")
    assert leg.mode == "walk"
    assert leg.duration_minutes is not None
    assert 5.0 <= leg.duration_minutes <= 10.0
    assert leg.cost == 0.0
    assert "same place" in (leg.notes or "").casefold()


def test_unknown_places_get_generic_heuristic():
    leg = estimate_transport("Foo District", "Bar Quay", destination="Atlantis")
    assert leg.from_place == "Foo District"
    assert leg.to_place == "Bar Quay"
    assert leg.mode in {"metro", "bus", "walk", "taxi"}
    assert leg.duration_minutes is not None and leg.duration_minutes > 0
    assert leg.cost is not None and leg.cost >= 0
    assert leg.notes and "generic" in leg.notes.casefold()
    # Deterministic: same inputs → same outputs
    again = estimate_transport("Foo District", "Bar Quay", destination="Atlantis")
    assert again.duration_minutes == leg.duration_minutes
    assert again.cost == leg.cost
    assert again.mode == leg.mode


def test_health_reports_stub_catalog():
    info = health()
    assert info["agent"] == "estimate_transport"
    assert info["tool_mode"] == "stub"
    assert info["provider_configured"] is True
    assert info["catalog"] == "tools.stub"


def test_api_mode_raises(monkeypatch):
    from config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setenv("TOOL_MAPS_MODE", "api")
    settings_mod.get_settings.cache_clear()
    with pytest.raises(NotImplementedError):
        estimate_transport("Central", "Kowloon", destination="Hong Kong")
    monkeypatch.delenv("TOOL_MAPS_MODE", raising=False)
    settings_mod.get_settings.cache_clear()
