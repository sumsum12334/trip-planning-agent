"""Load settings from environment (.env) with sane local defaults."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from threading import RLock

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    # Qwen-compatible model-serving endpoint. QWEN_BASE_URL should include /v1.
    qwen_base_url: str = Field(default="", alias="QWEN_BASE_URL")
    qwen_model: str = Field(default="qwen3.8-27b", alias="QWEN_MODEL")
    qwen_api_key: str = Field(default="", alias="QWEN_API_KEY")

    # Baseline A = 0 (Agents 1–3); Proposed = 1 (include Agent 4 Travel_History)
    enable_travel_history: bool = Field(default=True, alias="ENABLE_TRAVEL_HISTORY")

    # Tools
    tool_stays_mode: Literal["stub", "overpass", "api"] = Field(default="stub", alias="TOOL_STAYS_MODE")
    tool_maps_mode: Literal["stub", "api"] = Field(default="stub", alias="TOOL_MAPS_MODE")
    web_search_mode: Literal["stub", "duckduckgo"] = Field(
        default="stub", alias="WEB_SEARCH_MODE"
    )
    weather_mode: Literal["stub", "api"] = Field(default="stub", alias="WEATHER_MODE")

    # Travel History DB
    database_url: str = Field(
        default="sqlite:///./data/travel_history.sqlite",
        alias="DATABASE_URL",
    )

    # Langfuse (optional)
    langfuse_public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="https://cloud.langfuse.com", alias="LANGFUSE_HOST")
    langfuse_enabled: bool = Field(default=False, alias="LANGFUSE_ENABLED")

    # Optional form default only — not a hard product requirement
    default_origin: str = Field(default="", alias="DEFAULT_ORIGIN")

    # Geocoding for Overpass provider (free Nominatim, rate-limited)
    geocoding_enabled: bool = Field(default=False, alias="GEOCODING_ENABLED")

    # --- OpenStreetMap Overpass API (Agent 1, used when TOOL_STAYS_MODE=overpass) ---
    # Free, no authentication required. Queries OSM for hotels/motels/hostels near
    # the destination. Returns real names, coordinates, and addresses — but no
    # nightly cost or real-time availability.
    overpass_api_url: str = Field(
        default="https://overpass-api.de/api/interpreter", alias="OVERPASS_API_URL"
    )
    overpass_timeout: float = Field(default=30.0, alias="OVERPASS_TIMEOUT")
    overpass_radius_meters: int = Field(default=5000, alias="OVERPASS_RADIUS_METERS")

    # --- Stay search provider (Agent 1, used when TOOL_STAYS_MODE=api) ---
    # OBO Travel MCP API (https://onebookingonline.com/mcp) — free, no auth
    # required for keyless access (30 req/min, 500 req/day). Set
    # STAYS_API_KEY for higher limits (60 req/min, 2000 req/day).
    stays_api_base_url: str = Field(
        default="https://onebookingonline.com/mcp", alias="STAYS_API_BASE_URL"
    )
    stays_api_key: str = Field(default="", alias="STAYS_API_KEY")
    stays_api_timeout: float = Field(default=30.0, alias="STAYS_API_TIMEOUT")

    # --- NVIDIA Nemotron API (Agent 6, used when EVENTS_MODE=ticketmaster) ---
    # Get a free API key from https://build.nvidia.com/
    # Rate limits: 5 requests/second, 10000 requests/day (free tier).
    nemotron_api_key: str = Field(default="", alias="NEMOTRON_API_KEY")
    nemotron_api_url: str = Field(
        default="https://integrate.api.nvidia.com/v1/chat/completions",
        alias="NEMOTRON_API_URL",
    )

    @property
    def baseline_a(self) -> bool:
        """True when Agent 4 is disabled (Agents 1–3 only)."""
        return not self.enable_travel_history


_model_override_lock = RLock()
_model_overrides: dict[str, str] = {}


def get_model_config(settings: Settings | None = None) -> dict[str, str]:
    """Return environment defaults combined with process-local UI overrides."""
    current = settings or get_settings()
    with _model_override_lock:
        return {
            "base_url": _model_overrides.get(
                "base_url",
                current.qwen_base_url,
            ),
            "model": _model_overrides.get(
                "model",
                current.qwen_model,
            ),
            "api_key": _model_overrides.get(
                "api_key",
                current.qwen_api_key,
            ),
        }


def update_model_config(*, base_url: str, model: str, api_key: str | None) -> None:
    """Update model configuration for the running application process only."""
    with _model_override_lock:
        _model_overrides["base_url"] = base_url
        _model_overrides["model"] = model
        if api_key is not None:
            _model_overrides["api_key"] = api_key


def reset_model_config() -> None:
    """Drop process-local model overrides (used by tests and reloads)."""
    with _model_override_lock:
        _model_overrides.clear()


@lru_cache
def get_settings() -> Settings:
    return Settings()
