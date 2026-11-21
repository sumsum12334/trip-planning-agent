"""Agent 1 - search_stays: accommodation under budget and location.

Provider selection is driven by ``TOOL_STAYS_MODE``:
  * ``stub``   — curated local catalog (default, offline-safe).
  * ``overpass`` — real OpenStreetMap lodging via Overpass API (no auth).
  * ``web``    — live results via the shared DuckDuckGo web-search tool
                 (preferred live mode; needs ``WEB_SEARCH_MODE=duckduckgo``,
                 falls back to the stub catalog when search is unavailable).
  * ``api``    — legacy OBO Travel MCP provider (live prices, booking URLs,
                 no API key required). Kept for rollback; prefer ``web``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
import os
from urllib.parse import parse_qs, urlencode, urlparse

from langsmith import traceable

from config.settings import get_settings
from shared.history_match import stay_overlaps_places
from shared.schemas import StayCandidate, TripRequest
from agents.web_search import run as web_search_run

from . import tools


def _overlaps_excluded(stay: StayCandidate, excluded: set[str]) -> bool:
    """True if a visited place is specific enough to match this stay.

    Uses the shared matcher so a city-level visit ("Tokyo") does not exclude
    every stay in that city, while a neighborhood visit ("shibuya") does.
    """
    if not excluded:
        return False
    return stay_overlaps_places(stay.name, stay.location, excluded)


def _trip_com_search_url(query: str) -> str:
    """Build a trip.com hotel-search link for a destination or hotel name."""
    return "https://www.trip.com/hotels/list?" + urlencode({"searchWord": query.strip()})


def _needs_search_link(url: str | None) -> bool:
    """True when a stay has no real provider link (missing or placeholder)."""
    text = str(url or "").strip()
    if not text:
        return True
    try:
        host = urlparse(text).netloc.casefold()
    except ValueError:
        return True
    return (not host) or "example.com" in host


def _unwrap_result_url(url: str) -> str:
    """Resolve DuckDuckGo redirect wrappers (…/l/?uddg=…) to the target page."""
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        text = "https:" + text
    try:
        parsed = urlparse(text)
    except ValueError:
        return text
    if "duckduckgo.com" in parsed.netloc.casefold():
        return parse_qs(parsed.query).get("uddg", [""])[0] or text
    return text


def _verified_trip_com_urls(
    candidates: list[StayCandidate], destination: str
) -> dict[str, str]:
    """Ask the live web-search agent which stays actually appear on trip.com.

    Only runs when WEB_SEARCH_MODE=duckduckgo; the stub mode never touches the
    network, so those stays fall back to a destination-level search link.
    """
    settings = get_settings()
    if getattr(settings, "web_search_mode", "stub") != "duckduckgo":
        return {}
    verified: dict[str, str] = {}
    for stay in candidates:
        if not _needs_search_link(stay.source_url):
            continue
        try:
            results = web_search_run(
                f"{stay.name} {destination} hotel trip.com", limit=5
            )
        except Exception:
            continue
        for result in results:
            url = _unwrap_result_url(str(getattr(result, "url", "") or ""))
            try:
                host = urlparse(url).netloc.casefold()
            except ValueError:
                continue
            if "trip.com" in host:
                verified[stay.name] = url
                break
    return verified


def _with_search_links(
    candidates: list[StayCandidate], destination: str
) -> list[StayCandidate]:
    """Give every stay a clickable travel-site link when the provider has none.

    Real provider URLs (booking APIs, Overpass websites) are kept. Otherwise a
    live web search verifies the hotel on trip.com when available; the fallback
    is a destination-level trip.com search, which always lists hotels instead
    of dead-ending on a name the site may not know.
    """
    verified = _verified_trip_com_urls(candidates, destination)
    for stay in candidates:
        if _needs_search_link(stay.source_url):
            stay.source_url = verified.get(stay.name) or _trip_com_search_url(
                destination
            )
    return candidates


@traceable(
    run_type="tool",
    name="agent_search_stays",
    project_name=os.getenv("LANGSMITH_PROJECT", "trip-planning-agent"),
    metadata={"agent": "search_stays"},
)
def run(
    request: TripRequest,
    excluded_locations: Iterable[str] = (),
) -> list[StayCandidate]:
    """Return stay candidates, excluding travel-history places.

    Uses TOOL_STAYS_MODE (stub catalog or Overpass API). The coordinator passes
    Agent 4 visited places when avoid_visited=true.
    """
    settings = get_settings()
    mode = settings.tool_stays_mode
    if mode not in ("stub", "overpass", "api", "web"):
        # tools.search_stays already falls back to stub for unknown modes
        pass

    candidates = tools.search_stays(
        destination=request.destination,
        budget=request.budget,
        days=request.days,
        interests=request.interests or None,
        use_geocoding=settings.geocoding_enabled,
        check_in=request.start_date.isoformat() if request.start_date else None,
        check_out=request.end_date.isoformat() if request.end_date else None,
    )
    destination = request.destination.strip().casefold()
    excluded = {
        place.strip().casefold()
        for place in excluded_locations
        if place and place.strip() and place.strip().casefold() != destination
    }
    candidates = _with_search_links(candidates, request.destination)
    if not excluded:
        return candidates
    return [stay for stay in candidates if not _overlaps_excluded(stay, excluded)]


def health() -> dict[str, Any]:
    s = get_settings()
    provider_info: dict[str, Any] = {"provider": "stub", "offline_safe": True}
    if s.tool_stays_mode == "overpass":
        provider_info = {
            "provider": "overpass",
            "base_urls": [u.strip() for u in s.overpass_api_url.split(",") if u.strip()],
            "radius_meters": s.overpass_radius_meters,
            "offline_safe": False,
            "timeout_seconds": s.overpass_timeout,
        }
    elif s.tool_stays_mode == "web":
        engine = s.web_search_mode
        provider_info = {
            "provider": "web_search",
            "engine_mode": engine,
            "offline_safe": engine == "stub",  # stub engine falls back to the catalog
        }
    elif s.tool_stays_mode == "api":  # legacy; prefer web
        provider_info = {
            "provider": "obo_travel",
            "endpoint": s.stays_api_base_url,
            "api_key_configured": bool(s.stays_api_key),
            "offline_safe": False,
            "timeout_seconds": s.stays_api_timeout,
        }
    if s.tool_stays_mode == "stub":
        provider_configured = True
    elif s.tool_stays_mode == "overpass":
        provider_configured = bool(s.overpass_api_url.strip())
    elif s.tool_stays_mode == "web":
        provider_configured = True  # DuckDuckGo search needs no key
    else:  # api (legacy OBO Travel)
        provider_configured = bool(s.stays_api_base_url.strip())

    return {
        "agent": "search_stays",
        "tool_mode": s.tool_stays_mode,
        "provider_configured": provider_configured,
        "catalog": s.tool_stays_mode,
        "provider": provider_info,
    }
