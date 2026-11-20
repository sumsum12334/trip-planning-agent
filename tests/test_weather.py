"""Tests for the weather tool's mode handling and stub fallback."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.weather import agent as weather_agent


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch):
    """Point settings at an explicit mode without reading the real .env."""
    monkeypatch.setattr(
        weather_agent,
        "get_settings",
        lambda: SimpleNamespace(weather_mode="stub"),
    )


def test_stub_mode_never_touches_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail_geocode(destination):
        raise AssertionError("stub mode must not geocode")

    monkeypatch.setattr(weather_agent, "_geocode_destination", _fail_geocode)
    result = weather_agent.run("Tokyo")
    assert result["mode"] == "stub"
    assert result["stub"] is True
    assert result["condition"] == "Sunny"
    assert result["temperature_c"] == 22
    assert result["start_date"] and result["end_date"]


def test_unknown_destination_stub_result() -> None:
    result = weather_agent.run("Nowhereville")
    assert result["mode"] == "stub"
    assert result["condition"] == "Unknown"
    assert result["temperature_c"] is None
    assert "Nowhereville" in result["notes"]


def test_live_mode_falls_back_to_stub_without_geocode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_geocode(destination):
        return None

    monkeypatch.setattr(
        weather_agent,
        "get_settings",
        lambda: SimpleNamespace(weather_mode="open-meteo"),
    )
    monkeypatch.setattr(weather_agent, "_geocode_destination", _no_geocode)
    result = weather_agent.run("Tokyo")
    # Fallback data is labeled as a stub while the configured mode is preserved.
    assert result["mode"] == "open-meteo"
    assert result["stub"] is True
    assert result["condition"] == "Sunny"


def test_live_mode_uses_open_meteo_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _geocode(destination):
        return {"latitude": 35.0, "longitude": 139.0, "name": "Tokyo"}

    async def _fake_fetch(lat, lon, start_date, end_date):
        assert lat == 35.0 and lon == 139.0
        return {
            "condition": "Light rain",
            "temp_c": 15,
            "temp_f": 59,
            "humidity": 80,
            "notes": f"Open-Meteo forecast for {start_date}",
        }

    monkeypatch.setattr(
        weather_agent,
        "get_settings",
        lambda: SimpleNamespace(weather_mode="api"),
    )
    monkeypatch.setattr(weather_agent, "_geocode_destination", _geocode)
    monkeypatch.setattr(weather_agent, "_fetch_weather_open_meteo", _fake_fetch)
    result = weather_agent.run("Tokyo")
    assert result["mode"] == "open-meteo"
    assert result["stub"] is False
    assert result["condition"] == "Light rain"
    assert result["temperature_c"] == 15


def test_failed_fetch_leaves_module_stub_table_unmodified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_geocode(destination):
        return None

    monkeypatch.setattr(
        weather_agent,
        "get_settings",
        lambda: SimpleNamespace(weather_mode="open-meteo"),
    )
    monkeypatch.setattr(weather_agent, "_geocode_destination", _no_geocode)
    before = dict(weather_agent._WEATHER_STUB["tokyo"])
    weather_agent.run("Tokyo")
    assert weather_agent._WEATHER_STUB["tokyo"] == before
    assert "stub" not in weather_agent._WEATHER_STUB["tokyo"]


def test_health_reports_configured_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        weather_agent,
        "get_settings",
        lambda: SimpleNamespace(weather_mode="open-meteo"),
    )
    assert weather_agent.health() == {"tool": "weather", "mode": "open-meteo"}
