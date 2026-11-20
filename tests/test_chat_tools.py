"""Tests for the chat model's sub-agent tools."""

from __future__ import annotations

import pytest

from agents.chat_tools import AGENT_TOOL_NAMES, AGENT_TOOL_SCHEMAS, execute_agent_tool


def test_schemas_cover_expected_agent_tools():
    names = {schema["function"]["name"] for schema in AGENT_TOOL_SCHEMAS}
    assert names == AGENT_TOOL_NAMES == {"search_stays", "estimate_transport", "web_search", "weather"}


def test_search_stays_returns_stub_candidates():
    result = execute_agent_tool("search_stays", {"destination": "Tokyo", "budget": 400, "days": 4})
    assert result["mode"] == "stub"
    assert result["stays"], "expected stub stay candidates"
    assert result["stays"][0]["name"]


def test_estimate_transport_returns_leg():
    leg = execute_agent_tool("estimate_transport", {"from_place": "A", "to_place": "B"})
    assert leg["from_place"] == "A"
    assert leg["to_place"] == "B"
    # `mode` is the travel mode; the stub source is labeled in `notes`.
    assert leg["mode"] in {"metro", "bus", "walk", "taxi"}
    assert leg["mode"] != "unknown"
    assert "stub" in (leg.get("notes") or "").casefold()
    assert leg["duration_minutes"] is not None
    assert leg["cost"] is not None
    assert leg.get("currency") == "USD"


def test_estimate_transport_unavailable_returns_labeled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unavailable(request, from_place, to_place):
        raise NotImplementedError("api mode is not implemented")

    monkeypatch.setattr("agents.chat_tools.estimate_transport_run", _unavailable)
    result = execute_agent_tool("estimate_transport", {"from_place": "A", "to_place": "B"})
    # A provider failure becomes a labeled tool result, not an aborted turn.
    assert result["mode"] == "unavailable"
    assert "Transport provider unavailable" in result["error"]
    assert result["from_place"] == "A"
    assert result["to_place"] == "B"


def test_web_search_stub_mode():
    result = execute_agent_tool("web_search", {"query": "things to do in Kyoto", "limit": 3})
    from config.settings import get_settings
    assert result["mode"] == get_settings().web_search_mode
    assert result["results"]


def test_weather_stub_mode():
    result = execute_agent_tool("weather", {"destination": "Kyoto"})
    assert result["destination"] == "Kyoto"
    assert result["mode"] == "stub"
    assert result["condition"]
    assert result["stub"] is True
    assert result["temperature_c"] is not None


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("search_stays", {"destination": "  "}),
        ("estimate_transport", {"from_place": "A"}),
        ("web_search", {"query": ""}),
        ("weather", {"destination": "  "}),
        ("not_a_tool", {}),
    ],
)
def test_invalid_agent_tool_arguments_raise(name, arguments):
    with pytest.raises(ValueError):
        execute_agent_tool(name, arguments)
