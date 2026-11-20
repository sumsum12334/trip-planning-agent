"""Weather tool: Open-Meteo live weather API (free, no API key required).

Returns live weather forecasts for a destination so the model can factor
weather into trip planning. Falls back to stub data if API unavailable.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
from config.settings import get_settings


logger = logging.getLogger(__name__)


# Stub fallback data for when API fails
_WEATHER_STUB: dict[str, dict[str, Any]] = {
    "kyoto": {"condition": "Partly cloudy", "temp_c": 18, "temp_f": 64, "humidity": 60, "notes": "Spring weather, mild"},
    "tokyo": {"condition": "Sunny", "temp_c": 22, "temp_f": 72, "humidity": 55, "notes": "Clear skies, warm"},
    "osaka": {"condition": "Cloudy", "temp_c": 20, "temp_f": 68, "humidity": 65, "notes": "Overcast, mild"},
    "hong kong": {"condition": "Humid", "temp_c": 26, "temp_f": 79, "humidity": 80, "notes": "Tropical, humid"},
    "bangkok": {"condition": "Hot", "temp_c": 32, "temp_f": 90, "humidity": 70, "notes": "Hot and humid"},
    "singapore": {"condition": "Rainy", "temp_c": 28, "temp_f": 82, "humidity": 85, "notes": "Frequent showers"},
    "london": {"condition": "Overcast", "temp_c": 14, "temp_f": 57, "humidity": 75, "notes": "Cool and grey"},
    "paris": {"condition": "Partly cloudy", "temp_c": 17, "temp_f": 63, "humidity": 60, "notes": "Mild spring"},
    "new york": {"condition": "Sunny", "temp_c": 20, "temp_f": 68, "humidity": 55, "notes": "Clear"},
    "sydney": {"condition": "Sunny", "temp_c": 21, "temp_f": 70, "humidity": 60, "notes": "Clear, mild"},
}


# WMO weather code to condition mapping
_WMO_CODES = {
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
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
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


async def _geocode_destination(destination: str) -> Optional[dict[str, float]]:
    """Geocode a destination using Open-Meteo's geocoding API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={
                    "name": destination,
                    "count": 1,
                    "language": "en",
                    "format": "json",
                },
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            if results:
                return {
                    "latitude": results[0]["latitude"],
                    "longitude": results[0]["longitude"],
                    "name": results[0].get("name", destination),
                    "country": results[0].get("country", ""),
                }
    except Exception as e:
        logger.warning("Geocoding failed for %r: %s", destination, e)
    return None


async def _fetch_weather_open_meteo(lat: float, lon: float, start_date: str, end_date: str) -> Optional[dict[str, Any]]:
    """Fetch weather from Open-Meteo API."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "start_date": start_date,
                    "end_date": end_date,
                    "daily": ["weathercode", "temperature_2m_max", "temperature_2m_min", "relative_humidity_2m_mean"],
                    "timezone": "auto",
                },
            )
            response.raise_for_status()
            data = response.json()
            
            daily = data.get("daily", {})
            if not daily:
                return None
                
            # Return first day's data (for single-day queries)
            weathercode = daily.get("weathercode", [None])[0]
            temp_max = daily.get("temperature_2m_max", [None])[0]
            temp_min = daily.get("temperature_2m_min", [None])[0]
            humidity = daily.get("relative_humidity_2m_mean", [None])[0]
            
            if weathercode is None or temp_max is None:
                return None
                
            condition = _WMO_CODES.get(weathercode, "Unknown")
            temp_c = round((temp_max + temp_min) / 2) if temp_min is not None else round(temp_max)
            temp_f = round(temp_c * 9/5 + 32)
            
            return {
                "condition": condition,
                "temp_c": temp_c,
                "temp_f": temp_f,
                "humidity": humidity,
                "notes": f"Open-Meteo forecast for {start_date}",
            }
    except Exception as e:
        logger.warning("Open-Meteo API failed: %s", e)
    return None


def run(destination: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict[str, Any]:
    """Return weather info for a destination using Open-Meteo API."""
    settings = get_settings()
    configured_mode = getattr(settings, "weather_mode", "stub")

    # Default to tomorrow if no date provided
    if not start_date:
        from datetime import date, timedelta
        start_date = (date.today() + timedelta(days=1)).isoformat()
    if not end_date:
        end_date = start_date

    # Try to get live data from Open-Meteo unless the stub mode is forced.
    live_data = None
    mode = configured_mode
    if configured_mode != "stub":
        import asyncio
        try:
            # Run async geocoding and weather fetch
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                geo = loop.run_until_complete(_geocode_destination(destination))
                if geo:
                    live_data = loop.run_until_complete(
                        _fetch_weather_open_meteo(geo["latitude"], geo["longitude"], start_date, end_date)
                    )
            finally:
                loop.close()
        except Exception as e:
            logger.warning("Failed to fetch live weather: %s", e)

    # Fallback to stub
    key = destination.strip().lower()
    data = _WEATHER_STUB.get(key)

    if data is None:
        data = {
            "condition": "Unknown",
            "temp_c": None,
            "temp_f": None,
            "humidity": None,
            "notes": f"No weather data for {destination} (stub)",
        }
    else:
        # Copy so the module-level stub table is never mutated per request.
        data = dict(data)

    # Use live data if available
    if live_data:
        data = live_data
        data["stub"] = False
        mode = "open-meteo"
    else:
        data["stub"] = True

    result = {
        "destination": destination,
        "mode": mode,
        "condition": data["condition"],
        "temperature_c": data.get("temp_c"),
        "temperature_f": data.get("temp_f"),
        "humidity": data.get("humidity"),
        "notes": data.get("notes", ""),
        "stub": data.get("stub", True),
    }
    if start_date:
        result["start_date"] = start_date
    if end_date:
        result["end_date"] = end_date
    return result


def health() -> dict[str, str]:
    return {"tool": "weather", "mode": getattr(get_settings(), "weather_mode", "stub")}