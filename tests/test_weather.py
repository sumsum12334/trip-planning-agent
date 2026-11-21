"""Tests for the weather tool's mode handling and stub fallback."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.weather import agent as weather_agent


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch):
    """Point settings at an explicit mode without reading the real .env."""
    weather_agent._WEATHER_CACHE.clear()
    monkeypatch.setattr(
        weather_agent,
        "get_settings",
        lambda: SimpleNamespace(weather_mode="stub"),
    )
    yield
    weather_agent._WEATHER_CACHE.clear()


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


def test_live_mode_falls_back_to_stub_when_forecast_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A geocode hit with no forecast data still degrades to the stub."""
    async def _geocode(destination):
        return {"latitude": 35.0, "longitude": 139.0, "name": "Tokyo"}

    async def _empty_forecast(lat, lon, start_date, end_date):
        return None

    monkeypatch.setattr(
        weather_agent,
        "get_settings",
        lambda: SimpleNamespace(weather_mode="open-meteo"),
    )
    monkeypatch.setattr(weather_agent, "_geocode_destination", _geocode)
    monkeypatch.setattr(weather_agent, "_fetch_weather_open_meteo", _empty_forecast)
    result = weather_agent.run("Tokyo")
    assert result["mode"] == "open-meteo"
    assert result["stub"] is True
    assert result["condition"] == "Sunny"
    assert result["temperature_c"] == 22


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


def test_date_beyond_forecast_horizon_skips_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open-Meteo only serves ~16 days ahead; a later date must not be requested."""
    from datetime import date, timedelta

    far_date = (date.today() + timedelta(days=30)).isoformat()

    def _fail_fetch(lat, lon, start_date, end_date):
        raise AssertionError("dates beyond the horizon must not be fetched")

    monkeypatch.setattr(
        weather_agent,
        "get_settings",
        lambda: SimpleNamespace(weather_mode="api"),
    )
    monkeypatch.setattr(weather_agent, "_fetch_weather_open_meteo", _fail_fetch)
    result = weather_agent.run("Tokyo", start_date=far_date, end_date=far_date)
    assert result["stub"] is True
    assert result["mode"] == "api"
    assert "horizon" in result["notes"]
    assert far_date in result["notes"]


def test_identical_requests_are_served_from_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """The plan UI refetches per day on every plan update; repeat calls within
    the TTL must not hit the geocoder and Open-Meteo again."""
    from datetime import date, timedelta

    day = (date.today() + timedelta(days=5)).isoformat()
    calls = {"geocode": 0, "fetch": 0}

    async def _geocode(destination):
        calls["geocode"] += 1
        return {"latitude": 35.0, "longitude": 139.0, "name": "Tokyo"}

    async def _fetch(lat, lon, start_date, end_date):
        calls["fetch"] += 1
        return {
            "condition": "Clear sky",
            "temp_c": 20,
            "temp_f": 68,
            "humidity": 50,
            "notes": f"Open-Meteo forecast for {start_date}",
        }

    monkeypatch.setattr(
        weather_agent,
        "get_settings",
        lambda: SimpleNamespace(weather_mode="api"),
    )
    monkeypatch.setattr(weather_agent, "_geocode_destination", _geocode)
    monkeypatch.setattr(weather_agent, "_fetch_weather_open_meteo", _fetch)

    first = weather_agent.run("Tokyo", start_date=day, end_date=day)
    second = weather_agent.run("Tokyo", start_date=day, end_date=day)
    assert calls == {"geocode": 1, "fetch": 1}
    assert first == second

    # A different destination or date must not reuse the cached entry.
    other_day = (date.today() + timedelta(days=6)).isoformat()
    weather_agent.run("Osaka", start_date=day, end_date=day)
    weather_agent.run("Tokyo", start_date=other_day, end_date=other_day)
    assert calls == {"geocode": 3, "fetch": 3}
