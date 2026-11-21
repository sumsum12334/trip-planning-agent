"""Small optional web-search tool with a deterministic local stub."""

from __future__ import annotations

import os
from html.parser import HTMLParser
from urllib.parse import quote_plus

import httpx
from langsmith import traceable
from pydantic import BaseModel

from config.settings import get_settings


class WebSearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[WebSearchResult] = []
        self._current: dict[str, str] | None = None
        self._text: list[str] = []
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "a" and "result__a" in classes and attributes.get("href"):
            self._current = {"url": attributes["href"], "title": ""}
            self._text = []
            self._in_title = True
        elif self._current and "result__snippet" in classes:
            self._text = []
            self._in_snippet = True

    def handle_data(self, data: str) -> None:
        if self._current and (self._in_title or self._in_snippet):
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._in_title and tag == "a" and self._current:
            self._current["title"] = " ".join("".join(self._text).split())
            self._text = []
            self._in_title = False
        elif self._in_snippet and tag in {"a", "div"} and self._current:
            self.results.append(
                WebSearchResult(
                    title=self._current["title"],
                    url=self._current["url"],
                    snippet=" ".join("".join(self._text).split()),
                )
            )
            self._current = None
            self._text = []
            self._in_snippet = False


@traceable(
    run_type="tool",
    name="agent_web_search",
    project_name=os.getenv("LANGSMITH_PROJECT", "trip-planning-agent"),
    metadata={"agent": "web_search"},
)
def run(query: str, *, limit: int = 5) -> list[WebSearchResult]:
    """Search the web when enabled, otherwise return a safe local result."""
    settings = get_settings()
    if settings.web_search_mode == "stub":
        return [
            WebSearchResult(
                title="Web search stub",
                url="https://example.com/web-search",
                snippet=f"Enable WEB_SEARCH_MODE=duckduckgo to search for: {query}",
            )
        ]

    response = httpx.get(
        "https://html.duckduckgo.com/html/?q=" + quote_plus(query),
        headers={"User-Agent": "trip-planning-agent/0.1"},
        timeout=15.0,
    )
    response.raise_for_status()
    parser = _DuckDuckGoParser()
    parser.feed(response.text)
    return parser.results[:limit]


def health() -> dict[str, str]:
    return {"tool": "web_search", "mode": get_settings().web_search_mode}
