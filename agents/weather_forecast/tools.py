"""Typed weather forecasts with an offline-safe stub and Open-Meteo provider."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from config.settings import get_settings

_USER_AGENT = "trip-planning-agent/0.1 (weather forecast)"
_TIMEOUT_SECONDS = 15.0
_DAILY_FIELDS = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_probability_max",
    "wind_speed_10m_max",
)


class WeatherForecastRequest(BaseModel):
    """Validated arguments for a forecast lookup."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    location: str = Field(min_length=1, max_length=200)
    forecast_days: int = Field(default=3, ge=1, le=7)

    @field_validator("forecast_days", mode="before")
    @classmethod
    def reject_boolean_days(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("forecast_days must be an integer from 1 to 7.")
        return value


class WeatherForecastDay(BaseModel):
    date: date
    weather_code: int
    condition: str
    temperature_max_c: float
    temperature_min_c: float
    precipitation_probability_max_percent: int | None = None
    wind_speed_max_kmh: float | None = None


class WeatherForecast(BaseModel):
    mode: Literal["stub", "open_meteo"]
    location: str
    latitude: float | None = None
    longitude: float | None = None
    timezone: str
    days: list[WeatherForecastDay]
    note: str


def _condition_for_code(code: int) -> str:
    conditions = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }
    return conditions.get(code, f"Weather code {code}")


def _stub_forecast(request: WeatherForecastRequest) -> WeatherForecast:
    today = date.today()
    return WeatherForecast(
        mode="stub",
        location=request.location,
        timezone="local (stub)",
        days=[
            WeatherForecastDay(
                date=today + timedelta(days=index),
                weather_code=2,
                condition="Partly cloudy (sample)",
                temperature_max_c=20.0,
                temperature_min_c=14.0,
            )
            for index in range(request.forecast_days)
        ],
        note="Offline-safe sample only; these values are not a live forecast.",
    )


def _geocode(location: str) -> tuple[float, float, str]:
    response = httpx.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": location, "format": "jsonv2", "limit": 1},
        headers={"User-Agent": _USER_AGENT},
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    results = response.json()
    if not isinstance(results, list) or not results:
        raise ValueError(f"No location found for {location!r}.")

    result = results[0]
    try:
        latitude = float(result["lat"])
        longitude = float(result["lon"])
        display_name = str(result["display_name"]).strip()
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Location provider returned an invalid result.") from error
    if not display_name:
        raise ValueError("Location provider returned an invalid result.")
    return latitude, longitude, display_name


def _open_meteo_forecast(request: WeatherForecastRequest) -> WeatherForecast:
    latitude, longitude, display_name = _geocode(request.location)
    response = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "daily": ",".join(_DAILY_FIELDS),
            "timezone": "auto",
            "forecast_days": request.forecast_days,
        },
        headers={"User-Agent": _USER_AGENT},
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    daily = payload.get("daily") if isinstance(payload, dict) else None
    if not isinstance(daily, dict):
        raise ValueError("Weather provider returned an invalid forecast.")

    try:
        days = [
            WeatherForecastDay(
                date=day,
                weather_code=code,
                condition=_condition_for_code(code),
                temperature_max_c=maximum,
                temperature_min_c=minimum,
                precipitation_probability_max_percent=precipitation,
                wind_speed_max_kmh=wind_speed,
            )
            for day, code, maximum, minimum, precipitation, wind_speed in zip(
                daily["time"],
                daily["weather_code"],
                daily["temperature_2m_max"],
                daily["temperature_2m_min"],
                daily.get("precipitation_probability_max", [None] * request.forecast_days),
                daily.get("wind_speed_10m_max", [None] * request.forecast_days),
                strict=True,
            )
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Weather provider returned an invalid forecast.") from error
    if len(days) != request.forecast_days:
        raise ValueError("Weather provider returned an incomplete forecast.")

    return WeatherForecast(
        mode="open_meteo",
        location=display_name,
        latitude=latitude,
        longitude=longitude,
        timezone=str(payload.get("timezone") or "unknown"),
        days=days,
        note="Forecast from Open-Meteo; weather codes follow WMO interpretation.",
    )


def get_weather_forecast(
    request: WeatherForecastRequest | dict[str, Any],
) -> WeatherForecast:
    """Return a validated forecast, using live providers only when configured."""
    validated = (
        request
        if isinstance(request, WeatherForecastRequest)
        else WeatherForecastRequest.model_validate(request)
    )
    if get_settings().weather_forecast_mode == "stub":
        return _stub_forecast(validated)
    return _open_meteo_forecast(validated)
