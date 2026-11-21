"""Offline tests for the web-search-backed stays provider (TOOL_STAYS_MODE=web).

All tests mock ``agents.search_stays.tools.web_search_run`` (or avoid it via
WEB_SEARCH_MODE=stub) so the suite never touches the network.
"""

from __future__ import annotations

import httpx
import pytest
from typing import get_args

from agents.search_stays import tools as tools_mod
from agents.web_search import WebSearchResult
from shared.schemas import StayCandidate


@pytest.fixture
def web_env(monkeypatch: pytest.MonkeyPatch):
    """Run with TOOL_STAYS_MODE=web and a live web-search engine."""
    from config import settings as settings_mod

    monkeypatch.setenv("TOOL_STAYS_MODE", "web")
    monkeypatch.setenv("WEB_SEARCH_MODE", "duckduckgo")
    settings_mod.get_settings.cache_clear()
    tools_mod.clear_caches()
    yield
    monkeypatch.delenv("TOOL_STAYS_MODE", raising=False)
    monkeypatch.delenv("WEB_SEARCH_MODE", raising=False)
    settings_mod.get_settings.cache_clear()
    tools_mod.clear_caches()


def _results(*items: tuple[str, str, str]) -> list[WebSearchResult]:
    return [WebSearchResult(title=t, url=u, snippet=s) for t, u, s in items]


# ---------------------------------------------------------------------------
# (a) Price parser
# ---------------------------------------------------------------------------


class TestParseNightlyPrice:
    def test_dollar_symbol(self):
        assert tools_mod.parse_nightly_price("Rooms from $120 per night") == (120.0, "USD")

    def test_us_dollar_prefix_symbol(self):
        assert tools_mod.parse_nightly_price("US$120 nightly rate") == (120.0, "USD")

    def test_iso_code_before_amount(self):
        assert tools_mod.parse_nightly_price("USD 120 per night") == (120.0, "USD")

    def test_iso_code_after_amount(self):
        assert tools_mod.parse_nightly_price("rooms from 1,200 THB") == (1200.0, "THB")

    def test_yen_thousands_is_jpy(self):
        assert tools_mod.parse_nightly_price("from ¥18,000 per night") == (18000.0, "JPY")

    def test_small_yen_amount_is_cny(self):
        assert tools_mod.parse_nightly_price("¥350 per night") == (350.0, "CNY")

    def test_yen_word(self):
        assert tools_mod.parse_nightly_price("rooms from 12,000 yen") == (12000.0, "JPY")

    def test_euro(self):
        assert tools_mod.parse_nightly_price("doubles from €95 a night") == (95.0, "EUR")

    def test_pound(self):
        assert tools_mod.parse_nightly_price("£80 per night") == (80.0, "GBP")

    def test_hong_kong_dollar(self):
        assert tools_mod.parse_nightly_price("HK$600 per night") == (600.0, "HKD")

    def test_prefers_per_night_context_over_other_prices(self):
        # $50 is the airport bus; $150 is the room rate near "per night".
        price = tools_mod.parse_nightly_price("Airport bus $50. Rooms from $150 per night.")
        assert price == (150.0, "USD")

    def test_monthly_rate_rejected(self):
        assert tools_mod.parse_nightly_price("Apartments $1,200 per month") is None

    def test_stay_total_rejected(self):
        assert tools_mod.parse_nightly_price("total $360 for 3 nights") is None

    def test_implausible_amounts_rejected(self):
        assert tools_mod.parse_nightly_price("Wi-Fi for $0.99") is None
        assert tools_mod.parse_nightly_price("Penthouse suites from $9,000") is None
        assert tools_mod.parse_nightly_price("Palace suites from ¥2,000,000") is None

    def test_non_price_text_returns_none(self):
        assert tools_mod.parse_nightly_price("Free cancellation, 12 km from the airport") is None
        assert tools_mod.parse_nightly_price("4.5 stars · 2 guests · 1 bedroom") is None
        assert tools_mod.parse_nightly_price("") is None


# ---------------------------------------------------------------------------
# (b) Mapping fake search results to StayCandidates
# ---------------------------------------------------------------------------


def test_map_web_results_to_candidates(monkeypatch, web_env):
    monkeypatch.setattr(
        tools_mod,
        "web_search_run",
        lambda query, limit=8: _results(
            (
                "Shinjuku Business Hotel — Tokyo",
                "https://hotels.example.com/shinjuku",
                "Rooms from $95 per night, free wifi",
            ),
            (
                "Asakusa Guesthouse Tokyo",
                "https://stay.example.com/asakusa",
                "Guesthouse in Asakusa, nightly rate ¥12,000",
            ),
            (
                "Best restaurants in Osaka",
                "https://food.example.com/osaka",
                "Ramen and sushi guide",
            ),
            (
                "Tokyo Tower tickets",
                "https://tickets.example.com/tower",
                "Skip-the-line admission",
            ),
        ),
    )
    stays = tools_mod.search_stays(destination="Tokyo", budget=300, days=3)

    # Non-lodging and wrong-city results are filtered out.
    assert [s.name for s in stays] == [
        "Asakusa Guesthouse Tokyo",
        "Shinjuku Business Hotel — Tokyo",
    ]
    for stay in stays:
        assert isinstance(stay, StayCandidate)
        assert stay.source_url
        assert (stay.notes or "").startswith("web search:")
        assert stay.currency == "USD"

    # ¥12,000/night is parsed and normalized to approximate USD (¥1 ≈ $0.0068).
    assert stays[0].nightly_cost == pytest.approx(81.6)
    assert "12,000 JPY" in stays[0].notes
    assert "approx. fixed rate" in stays[0].notes
    # Area hint extracted from "in Asakusa".
    assert stays[0].location == "Tokyo Asakusa"
    assert stays[0].property_type == "guest_house"

    assert stays[1].nightly_cost == pytest.approx(95.0)
    assert "listed 95 USD/night" in stays[1].notes


def test_results_for_other_cities_are_filtered(monkeypatch, web_env):
    monkeypatch.setattr(
        tools_mod,
        "web_search_run",
        lambda query, limit=8: _results(
            (
                "Seoul boutique stays",
                "https://x.example.com/seoul",
                "Hotels in Seoul from $80 per night",
            ),
            (
                "Tokyo capsule pods",
                "https://x.example.com/tokyo",
                "Capsule hotels from $35 per night",
            ),
        ),
    )
    stays = tools_mod.search_stays(destination="Tokyo", budget=300, days=3)
    assert [s.name for s in stays] == ["Tokyo capsule pods"]


def test_budget_cap_drops_priced_and_sorts_unpriced_last(monkeypatch, web_env):
    monkeypatch.setattr(
        tools_mod,
        "web_search_run",
        lambda query, limit=8: _results(
            (
                "Luxury Tower Tokyo",
                "https://x.example.com/lux",
                "Suites from $500 per night",
            ),
            (
                "Budget Pod Tokyo",
                "https://x.example.com/pod",
                "Capsule hotel from $40 per night",
            ),
            (
                "Mystery Ryokan Tokyo",
                "https://x.example.com/ryokan",
                "Traditional ryokan, check availability",
            ),
        ),
    )
    # Nightly cap = 300 / 3 = 100 → $500 is dropped.
    stays = tools_mod.search_stays(destination="Tokyo", budget=300, days=3)

    assert [s.name for s in stays] == ["Budget Pod Tokyo", "Mystery Ryokan Tokyo"]
    assert stays[0].nightly_cost == pytest.approx(40.0)
    # Unpriced candidate kept, sorted last, and labeled with an estimate.
    assert "estimated_nightly_cost" in stays[1].notes


def test_results_capped_at_ten(monkeypatch, web_env):
    raw = _results(
        *[
            (
                f"Tokyo Budget Hotel {i}",
                f"https://x.example.com/{i}",
                f"Rooms from ${20 + i} per night",
            )
            for i in range(14)
        ]
    )
    monkeypatch.setattr(tools_mod, "web_search_run", lambda query, limit=8: raw)
    stays = tools_mod.search_stays(destination="Tokyo", budget=10000, days=3)
    assert len(stays) == 10


def test_at_most_three_queries_and_stub_fallback_on_no_results(monkeypatch, web_env):
    calls: list[str] = []

    def _search(query, limit=8):
        calls.append(query)
        return []

    monkeypatch.setattr(tools_mod, "web_search_run", _search)
    stays = tools_mod.search_stays(destination="Tokyo", budget=300, days=3)

    assert len(calls) <= 3, f"expected bounded queries, got {len(calls)}"
    assert stays, "no usable web results must fall back to the stub catalog"
    for stay in stays:
        assert "web search returned no usable results" in (stay.notes or "")
        assert "stub catalog" in (stay.notes or "")


def test_duckduckgo_redirect_urls_are_unwrapped(monkeypatch, web_env):
    wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fstay.example.com%2Fpod&rut=z"
    monkeypatch.setattr(
        tools_mod,
        "web_search_run",
        lambda query, limit=8: _results(
            ("Budget Pod Tokyo", wrapped, "Capsule hotel from $40 per night"),
        ),
    )
    stays = tools_mod.search_stays(destination="Tokyo", budget=300, days=3)
    assert stays
    assert stays[0].source_url == "https://stay.example.com/pod"
    assert "web search: stay.example.com" in stays[0].notes


# ---------------------------------------------------------------------------
# (c) Fallbacks and labeled errors
# ---------------------------------------------------------------------------


def test_stub_web_search_mode_falls_back_to_catalog(monkeypatch, web_env):
    from config import settings as settings_mod

    monkeypatch.setenv("WEB_SEARCH_MODE", "stub")
    settings_mod.get_settings.cache_clear()

    def _must_not_run(query, limit=8):
        raise AssertionError("web_search.run must not be called in stub mode")

    monkeypatch.setattr(tools_mod, "web_search_run", _must_not_run)
    stays = tools_mod.search_stays(destination="Tokyo", budget=300, days=3)

    assert stays
    for stay in stays:
        assert "web search unavailable" in (stay.notes or "")
        assert "stub" in (stay.notes or "")
        # Catalog entries keep their real curated nightly cost.
        assert stay.nightly_cost is not None


def test_network_failure_falls_back_to_catalog(monkeypatch, web_env):
    def _fail(query, limit=8):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(tools_mod, "web_search_run", _fail)
    stays = tools_mod.search_stays(destination="Tokyo", budget=300, days=3)

    assert stays
    for stay in stays:
        assert "web search unavailable" in (stay.notes or "")
        assert "stub catalog" in (stay.notes or "")
    assert all(s.nightly_cost is not None for s in stays)


def test_provider_exception_returns_labeled_error(monkeypatch, web_env):
    class ExplodingProvider:
        def search(self, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(tools_mod, "_get_provider", lambda mode: ExplodingProvider())
    stays = tools_mod.search_stays(destination="Tokyo", budget=300, days=3)

    assert len(stays) == 1
    assert stays[0].name == "Provider error"
    assert "RuntimeError" in (stays[0].notes or "")


# ---------------------------------------------------------------------------
# Config surface
# ---------------------------------------------------------------------------


def test_tool_stays_mode_default_stays_stub_and_allows_web():
    from config.settings import Settings

    field = Settings.model_fields["tool_stays_mode"]
    assert field.default == "stub", "web must not become the default mode"
    assert "web" in get_args(field.annotation)
    assert "stub" in get_args(field.annotation)
    assert "overpass" in get_args(field.annotation)
    assert "api" in get_args(field.annotation)


def test_health_reports_web_provider(web_env):
    from agents.search_stays.agent import health

    info = health()
    assert info["agent"] == "search_stays"
    assert info["tool_mode"] == "web"
    assert info["provider_configured"] is True
    assert info["provider"]["provider"] == "web_search"
    assert info["provider"]["engine_mode"] == "duckduckgo"
    assert info["provider"]["offline_safe"] is False


def test_web_mode_with_stub_engine_reports_offline_safe(monkeypatch, web_env):
    from agents.search_stays.agent import health
    from config import settings as settings_mod

    monkeypatch.setenv("WEB_SEARCH_MODE", "stub")
    settings_mod.get_settings.cache_clear()
    info = health()
    assert info["provider"]["engine_mode"] == "stub"
    assert info["provider"]["offline_safe"] is True
