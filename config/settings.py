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

    # Legacy names retained for existing deployments.
    tacc_model_endpoint: str = Field(default="", alias="TACC_MODEL_ENDPOINT")
    tacc_api_key: str = Field(default="", alias="TACC_API_KEY")
    tacc_model: str = Field(default="", alias="TACC_MODEL")

    # Baseline A = 0 (Agents 1–3); Proposed = 1 (include Agent 4 Travel_History)
    enable_travel_history: bool = Field(default=True, alias="ENABLE_TRAVEL_HISTORY")

    # Tools
    tool_stays_mode: Literal["stub", "api"] = Field(default="stub", alias="TOOL_STAYS_MODE")
    tool_maps_mode: Literal["stub", "api"] = Field(default="stub", alias="TOOL_MAPS_MODE")

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
                current.qwen_base_url or current.tacc_model_endpoint,
            ),
            "model": _model_overrides.get(
                "model",
                current.qwen_model if current.qwen_base_url else current.tacc_model
                or current.qwen_model,
            ),
            "api_key": _model_overrides.get("api_key", current.tacc_api_key),
        }


def update_model_config(*, base_url: str, model: str, api_key: str | None) -> None:
    """Update model configuration for the running application process only."""
    with _model_override_lock:
        _model_overrides["base_url"] = base_url
        _model_overrides["model"] = model
        if api_key is not None:
            _model_overrides["api_key"] = api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
