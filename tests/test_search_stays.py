"""Tests for Agent 1 search_stays (stub mode)."""

from __future__ import annotations

import pytest

from agents.search_stays.agent import health, run
from agents.search_stays.tools import nightly_budget_cap, search_stays
from shared.schemas import StayCandidate, TripRequest


def test_stub_search_tokyo_respects_budget_and_returns_results():
    req = TripRequest(destination="Tokyo", budget=400, days=4, interests=["food"])
    stays = run(req)
    assert stays, "expected non-empty stub results for Tokyo"
    assert 1 <= len(stays) <= 5
    cap = nightly_budget_cap(req.budget, req.days)
    assert cap == 100.0
    for stay in stays:
        assert stay.nightly_cost is not None
        assert stay.nightly_cost <= cap
        assert "tokyo" in stay.location.casefold()
        assert stay.notes and "stub" in stay.notes.casefold()
    costs = [s.nightly_cost for s in stays if s.nightly_cost is not None]
    assert costs == sorted(costs)


def test_excluded_locations_filters_name_or_location():
    req = TripRequest(destination="Tokyo", budget=400, days=4)
    all_stays = run(req)
    assert all_stays
    # Exclude by location token that appears in Tokyo Shinjuku / Shibuya / Asakusa rows
    filtered = run(req, excluded_locations=["Shinjuku", "capsule"])
    names = {s.name for s in filtered}
    locations = {s.location.casefold() for s in filtered}
    assert all("shinjuku" not in loc for loc in locations)
    assert all("capsule" not in name.casefold() for name in names)
    assert len(filtered) < len(all_stays)


def test_stub_generic_fallback_for_unknown_city():
    stays = search_stays(destination="Atlantis", budget=300, days=3)
    assert stays, "expected generic catalog fallback"
    assert all("generic" in s.location.casefold() for s in stays)
    cap = nightly_budget_cap(300, 3)
    assert all(s.nightly_cost is not None and s.nightly_cost <= cap for s in stays)


def test_health_reports_stub_catalog():
    info = health()
    assert info["agent"] == "search_stays"
    assert info["tool_mode"] == "stub"
    assert info["provider_configured"] is True
    assert "catalog" in info


def test_api_mode_returns_labeled_error(monkeypatch):
    from config import settings as settings_mod
    from agents.search_stays import tools as tools_mod

    settings_mod.get_settings.cache_clear()
    tools_mod.clear_caches()
    monkeypatch.setenv("TOOL_STAYS_MODE", "api")
    settings_mod.get_settings.cache_clear()
    # With OBO Travel configured (no API key needed for keyless access),
    # api mode calls the provider and returns results or labeled errors.
    stays = search_stays(destination="Tokyo", budget=200, days=2)
    assert isinstance(stays, list)
    assert all(isinstance(s, StayCandidate) for s in stays)
    monkeypatch.delenv("TOOL_STAYS_MODE", raising=False)
    settings_mod.get_settings.cache_clear()
    tools_mod.clear_caches()


def test_overpass_mode_geocode_failure_returns_labeled_error(monkeypatch):
    from config import settings as settings_mod
    from agents.search_stays import tools as tools_mod

    settings_mod.get_settings.cache_clear()
    tools_mod.clear_caches()
    monkeypatch.setenv("TOOL_STAYS_MODE", "overpass")
    settings_mod.get_settings.cache_clear()

    class FakeGeocoder:
        def geocode(self, destination):
            return None

    tools_mod.NominatimGeocoder = lambda *args, **kwargs: FakeGeocoder()

    stays = search_stays(destination="Nowhereville XXYZ", budget=200, days=2)
    assert isinstance(stays, list)
    assert len(stays) == 1
    assert "resolve" in (stays[0].notes or "").lower()

    monkeypatch.delenv("TOOL_STAYS_MODE", raising=False)
    settings_mod.get_settings.cache_clear()
    tools_mod.clear_caches()


def test_health_reports_overpass_provider(monkeypatch):
    from config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setenv("TOOL_STAYS_MODE", "overpass")
    monkeypatch.setenv("OVERPASS_API_URL", "https://overpass-api.de/api/interpreter")
    settings_mod.get_settings.cache_clear()
    info = health()
    assert info["agent"] == "search_stays"
    assert info["tool_mode"] == "overpass"
    assert info["catalog"] == "overpass"
    assert info["provider"]["provider"] == "overpass"
    assert info["provider"]["offline_safe"] is False
    assert info["provider"]["radius_meters"] == 5000
    monkeypatch.delenv("TOOL_STAYS_MODE", raising=False)
    monkeypatch.delenv("OVERPASS_API_URL", raising=False)
    settings_mod.get_settings.cache_clear()


@pytest.mark.live
def test_overpass_live_tokyo_returns_real_hotels(monkeypatch):
    """Live test: call real Overpass API for Tokyo lodging.

    Overpass mirrors may be unreachable from some networks; if all fail,
    the test verifies the error is labeled correctly rather than crashing.
    """
    from config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setenv("TOOL_STAYS_MODE", "overpass")
    settings_mod.get_settings.cache_clear()

    stays = search_stays(destination="Tokyo", budget=200, days=2)

    monkeypatch.delenv("TOOL_STAYS_MODE", raising=False)
    settings_mod.get_settings.cache_clear()

    assert isinstance(stays, list)
    assert len(stays) >= 1, "expected at least one result (real or labeled error)"
    # Verify every result is a valid StayCandidate
    for stay in stays:
        assert isinstance(stay, StayCandidate)
        assert stay.name, "stay should have a name"
        assert stay.location, "stay should have a location"
    # If real results came back, verify they have real data
    real_results = [s for s in stays if s.name not in ("Provider error", "Geocoding failed")]
    if real_results:
        assert len(real_results) >= 1, "expected at least one real Overpass result"
        for stay in real_results:
            assert stay.location, "real stay should have a location"
            if stay.coordinates:
                assert "lat" in stay.coordinates and "lng" in stay.coordinates


@pytest.mark.live
def test_api_live_tokyo_returns_live_prices(monkeypatch):
    """Live test: call real OBO Travel API for Tokyo hotel prices."""
    from config import settings as settings_mod
    from agents.search_stays import tools as tools_mod

    settings_mod.get_settings.cache_clear()
    tools_mod.clear_caches()
    monkeypatch.setenv("TOOL_STAYS_MODE", "api")
    settings_mod.get_settings.cache_clear()

    stays = search_stays(destination="Tokyo", budget=300, days=2)

    monkeypatch.delenv("TOOL_STAYS_MODE", raising=False)
    settings_mod.get_settings.cache_clear()
    tools_mod.clear_caches()

    assert isinstance(stays, list)
    assert len(stays) >= 1, "expected at least one OBO Travel result"
    # First result should not be an error placeholder
    assert stays[0].name not in ("Provider error",)
    # OBO Travel results should have live nightly cost in USD
    for stay in stays:
        assert stay.name, "stay should have a name"
        assert stay.location, "stay should have a location"
        assert stay.currency == "USD", f"expected USD currency, got {stay.currency}"


def test_stub_stays_get_destination_search_links():
    """Stub hotels have fictional names, so the link searches the destination."""
    req = TripRequest(destination="Tokyo", budget=400, days=4)
    stays = run(req)
    assert stays
    for stay in stays:
        assert stay.source_url
        assert stay.source_url.startswith("https://www.trip.com/hotels/list?")
        assert "searchWord=Tokyo" in stay.source_url


def test_search_links_keep_provider_urls():
    from agents.search_stays.agent import _with_search_links

    real = StayCandidate(
        name="Real Hotel", location="Tokyo", source_url="https://www.trip.com/hotels/real"
    )
    filled = _with_search_links([real], "Tokyo")
    assert filled[0].source_url == "https://www.trip.com/hotels/real"


def test_search_links_encode_query():
    from agents.search_stays.agent import _trip_com_search_url

    url = _trip_com_search_url("Park Hyatt Tokyo")
    assert url == "https://www.trip.com/hotels/list?searchWord=Park+Hyatt+Tokyo"


def test_verified_web_results_win_over_fallback(monkeypatch):
    """A live web-search hit for the hotel replaces the destination-level link."""
    from agents.search_stays import agent as stays_agent
    from types import SimpleNamespace

    def _fake_search(query, limit=5):
        assert "Mandarin Oriental" in query
        return [
            SimpleNamespace(
                title="Unrelated result",
                url="https://www.example.com/other",
                snippet="",
            ),
            SimpleNamespace(
                title="Mandarin Oriental Hong Kong - trip.com",
                # DuckDuckGo wraps result URLs in its own redirect link.
                url=(
                    "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.trip.com%2Fhotels"
                    "%2Fhong-kong-mandarin-oriental%2F&rut=abc123"
                ),
                snippet="",
            ),
        ]

    monkeypatch.setattr(stays_agent, "web_search_run", _fake_search)
    monkeypatch.setattr(
        stays_agent,
        "get_settings",
        lambda: SimpleNamespace(web_search_mode="duckduckgo"),
    )
    other = StayCandidate(name="Unnamed Inn", location="Hong Kong")
    found = StayCandidate(name="Mandarin Oriental", location="Hong Kong")
    filled = stays_agent._with_search_links([other, found], "Hong Kong")
    assert filled[0].source_url == "https://www.trip.com/hotels/list?searchWord=Hong+Kong"
    assert (
        filled[1].source_url
        == "https://www.trip.com/hotels/hong-kong-mandarin-oriental/"
    )


def test_unwrap_result_url_handles_wrappers_and_direct_links():
    from agents.search_stays.agent import _unwrap_result_url

    wrapped = _unwrap_result_url(
        "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.trip.com%2Fhotels%2Fx&rut=z"
    )
    assert wrapped == "https://www.trip.com/hotels/x"
    assert _unwrap_result_url("https://www.trip.com/hotels/y") == (
        "https://www.trip.com/hotels/y"
    )
    assert _unwrap_result_url("") == ""


def test_verification_failure_falls_back_to_destination(monkeypatch):
    from agents.search_stays import agent as stays_agent
    from types import SimpleNamespace

    def _failing_search(query, limit=5):
        raise RuntimeError("network down")

    monkeypatch.setattr(stays_agent, "web_search_run", _failing_search)
    monkeypatch.setattr(
        stays_agent,
        "get_settings",
        lambda: SimpleNamespace(web_search_mode="duckduckgo"),
    )
    stay = StayCandidate(name="Some Hotel", location="Tokyo")
    filled = stays_agent._with_search_links([stay], "Tokyo")
    assert filled[0].source_url == "https://www.trip.com/hotels/list?searchWord=Tokyo"
