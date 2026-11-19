"""Weather tool: deterministic local stub (no live weather API key required).

Returns approximate current conditions for a destination so the model can factor
weather into trip planning. All values are illustrative stubs — never real-time
data — and are labelled as such in the result.
"""

from __future__ import annotations

from typing import Any, Optional

from config.settings import get_settings


class WeatherResult(dict):
    """Weather result dict with helpful accessors."""


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


def run(destination: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict[str, Any]:
    """Return weather info for a destination (stub)."""
    settings = get_settings()
    mode = getattr(settings, "weather_mode", "stub")

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

    result = {
        "destination": destination,
        "mode": mode,
        "condition": data["condition"],
        "temperature_c": data["temp_c"],
        "temperature_f": data["temp_f"],
        "humidity": data["humidity"],
        "notes": data["notes"],
        "stub": mode == "stub",
    }
    if start_date:
        result["start_date"] = start_date
    if end_date:
        result["end_date"] = end_date
    return result


def health() -> dict[str, str]:
    return {"tool": "weather", "mode": getattr(get_settings(), "weather_mode", "stub")}
