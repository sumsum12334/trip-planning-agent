"""Shared pytest fixtures.

The suite must stay independent of the developer's local ``.env``: tests that
exercise live providers patch their own settings or carry the ``live`` marker,
so provider modes are pinned to offline-safe defaults for every test.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _offline_provider_modes(monkeypatch: pytest.MonkeyPatch):
    """Pin tool/provider modes so local .env values cannot leak into tests."""
    from config.settings import get_settings

    monkeypatch.setenv("TOOL_STAYS_MODE", "stub")
    monkeypatch.setenv("TOOL_MAPS_MODE", "stub")
    monkeypatch.setenv("WEB_SEARCH_MODE", "stub")
    monkeypatch.setenv("WEATHER_MODE", "stub")
    monkeypatch.setenv("GEOCODING_ENABLED", "0")
    monkeypatch.setenv("RECONSIDER_PROMPT_ENABLED", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
