"""Tests for the optional web-search tool (stub mode + DuckDuckGo parser)."""

from __future__ import annotations

import httpx
import pytest
from types import SimpleNamespace

from agents.web_search.agent import (
    WebSearchResult,
    _DuckDuckGoParser,
    health,
    run,
)

_DUCK_HTML = """
<html><body>
<div class="results">
  <a class="result__a" href="https://example.com/a">Result A title</a>
  <div class="result__snippet">Snippet A text</div>
  <a class="result__a" href="https://example.com/b">Result B title</a>
  <div class="result__snippet">Snippet B text</div>
</div>
</body></html>
"""


def test_stub_mode_returns_labeled_result(monkeypatch):
    from config import settings as settings_mod

    monkeypatch.setenv("WEB_SEARCH_MODE", "stub")
    settings_mod.get_settings.cache_clear()
    try:
        results = run("things to do in Kyoto", limit=5)
        assert len(results) == 1
        assert results[0].url.startswith("https://example.com/")
        assert "WEB_SEARCH_MODE=duckduckgo" in results[0].snippet
    finally:
        settings_mod.get_settings.cache_clear()


def test_duckduckgo_parser_extracts_titles_and_snippets():
    parser = _DuckDuckGoParser()
    parser.feed(_DUCK_HTML)
    assert parser.results == [
        WebSearchResult(title="Result A title", url="https://example.com/a", snippet="Snippet A text"),
        WebSearchResult(title="Result B title", url="https://example.com/b", snippet="Snippet B text"),
    ]


def test_parser_ignores_results_without_href():
    parser = _DuckDuckGoParser()
    parser.feed('<a class="result__a">no href</a><div class="result__snippet">x</div>')
    assert parser.results == []


def test_api_mode_parses_live_html(monkeypatch):
    from config import settings as settings_mod

    monkeypatch.setenv("WEB_SEARCH_MODE", "duckduckgo")
    settings_mod.get_settings.cache_clear()

    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["agent"] = (headers or {}).get("User-Agent")
        return SimpleNamespace(
            raise_for_status=lambda: None,
            text=_DUCK_HTML,
            status_code=200,
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    try:
        results = run("kyoto temples", limit=1)
        assert len(results) == 1
        assert results[0].title == "Result A title"
        assert captured["url"].startswith("https://html.duckduckgo.com/html/?q=")
        assert captured["agent"].startswith("trip-planning-agent/")
    finally:
        settings_mod.get_settings.cache_clear()


def test_api_mode_raises_on_http_error(monkeypatch):
    from config import settings as settings_mod

    monkeypatch.setenv("WEB_SEARCH_MODE", "duckduckgo")
    settings_mod.get_settings.cache_clear()

    def fake_get(url, headers=None, timeout=None):
        request = httpx.Request("GET", url)
        raise httpx.HTTPStatusError("boom", request=request, response=None)

    monkeypatch.setattr(httpx, "get", fake_get)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            run("query", limit=3)
    finally:
        settings_mod.get_settings.cache_clear()


def test_health_reports_mode():
    info = health()
    assert info["tool"] == "web_search"
    assert info["mode"] in {"stub", "duckduckgo"}
