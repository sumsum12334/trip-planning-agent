"""Tests for the typed weather forecast tool."""

from __future__ import annotations

import httpx
import pytest

from agents.chat_tools import execute_agent_tool
from agents.weather_forecast.tools import WeatherForecastRequest, get_weather_forecast
from config import settings as settings_mod


@pytest.fixture(autouse=True)
def clear_settings_cache():
    settings_mod.get_settings.cache_clear()
    yield
    settings_mod.get_settings.cache_clear()


def _set_weather_mode(monkeypatch, mode: str) -> None:
    monkeypatch.setenv("WEATHER_FORECAST_MODE", mode)
    settings_mod.get_settings.cache_clear()


def test_stub_forecast_is_offline_safe_and_labeled(monkeypatch):
    _set_weather_mode(monkeypatch, "stub")

    def unexpected_request(*args, **kwargs):
        raise AssertionError("stub mode must not make network requests")

    monkeypatch.setattr(httpx, "get", unexpected_request)
    result = execute_agent_tool(
        "get_weather_forecast", {"location": "Tokyo", "forecast_days": 2}
    )

    assert result["mode"] == "stub"
    assert len(result["days"]) == 2
    assert "not a live forecast" in result["note"]
    assert result["days"][0]["condition"] == "Partly cloudy (sample)"


def test_open_meteo_forecast_uses_geocoded_location(monkeypatch):
    _set_weather_mode(monkeypatch, "open_meteo")
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if "nominatim" in url:
            return FakeResponse(
                [{"lat": "35.68", "lon": "139.69", "display_name": "Tokyo, Japan"}]
            )
        return FakeResponse(
            {
                "timezone": "Asia/Tokyo",
                "daily": {
                    "time": ["2026-11-20", "2026-11-21"],
                    "weather_code": [0, 61],
                    "temperature_2m_max": [18.5, 16.0],
                    "temperature_2m_min": [10.0, 9.5],
                    "precipitation_probability_max": [5, 60],
                    "wind_speed_10m_max": [12.0, 20.0],
                },
            }
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    result = get_weather_forecast(
        WeatherForecastRequest(location="Tokyo", forecast_days=2)
    )

    assert result.mode == "open_meteo"
    assert result.location == "Tokyo, Japan"
    assert result.latitude == 35.68
    assert result.days[0].condition == "Clear sky"
    assert result.days[1].precipitation_probability_max_percent == 60
    assert len(calls) == 2
    assert calls[1][1]["params"]["forecast_days"] == 2


@pytest.mark.parametrize(
    "arguments",
    [
        {"location": ""},
        {"location": "Tokyo", "forecast_days": 0},
        {"location": "Tokyo", "forecast_days": 8},
        {"location": "Tokyo", "forecast_days": True},
        {"location": "Tokyo", "unexpected": "value"},
    ],
)
def test_invalid_forecast_arguments_are_rejected_without_network(monkeypatch, arguments):
    _set_weather_mode(monkeypatch, "open_meteo")

    def unexpected_request(*args, **kwargs):
        raise AssertionError("invalid input must not make network requests")

    monkeypatch.setattr(httpx, "get", unexpected_request)
    with pytest.raises(ValueError):
        execute_agent_tool("get_weather_forecast", arguments)


def test_provider_http_failure_is_labeled(monkeypatch):
    _set_weather_mode(monkeypatch, "open_meteo")

    def failed_request(*args, **kwargs):
        request = httpx.Request("GET", args[0])
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError("service unavailable", request=request, response=response)

    monkeypatch.setattr(httpx, "get", failed_request)
    result = execute_agent_tool("get_weather_forecast", {"location": "Tokyo"})

    assert result["ok"] is False
    assert result["mode"] == "open_meteo"
    assert "provider failed" in result["error"]
