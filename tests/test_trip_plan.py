"""Tests for the split trip-plan tools and assembly."""

from __future__ import annotations

import pytest

from shared.trip_plan import (
    TRIP_PLAN_TOOL_NAMES,
    TRIP_PLAN_TOOLS,
    apply_trip_plan_tool,
    assemble_trip_plan,
    empty_trip_plan,
    format_plan_context,
)


def test_tool_names():
    names = {tool["function"]["name"] for tool in TRIP_PLAN_TOOLS}
    assert names == TRIP_PLAN_TOOL_NAMES
    assert {"start_trip_plan", "set_trip_day", "set_trip_budget", "get_trip_plan"} <= names


def test_start_days_and_budget():
    plan, _ = apply_trip_plan_tool(
        "start_trip_plan",
        {
            "destination": "Kyoto",
            "airport": {"name": "KIX", "coordinates": {"lat": 34.4347, "lng": 135.2329}},
            "currency": "JPY",
            "budget": 100000,
        },
        None,
    )
    plan, _ = apply_trip_plan_tool("set_trip_day", {"day": 2, "title": "Day two", "activities": ["B"], "budget": 40000}, plan)
    plan, result = apply_trip_plan_tool(
        "set_trip_day",
        {"day": 1, "title": "Day one", "activities": ["A"], "budget": 60000, "budget_items": [{"category": "Food", "amount": 10000}]},
        plan,
    )
    assert [day["day"] for day in plan["days"]] == [1, 2]
    assert result["days"] == [1, 2]

    plan, result = apply_trip_plan_tool("set_trip_budget", {"day": 1, "budget": 65000}, plan)
    assert plan["days"][0]["budget"] == 65000
    assert result["scope"] == "day 1"

    plan, result = apply_trip_plan_tool("set_trip_budget", {"items": [{"category": "Stay", "amount": 50000}]}, plan)
    assert plan["budget_items"][0]["category"] == "Stay"
    assert result["scope"] == "total"


def test_budget_is_independent_of_items():
    plan, _ = apply_trip_plan_tool("start_trip_plan", {"destination": "Rome"}, None)
    plan, _ = apply_trip_plan_tool("set_trip_budget", {"items": [{"category": "Food", "amount": 100}]}, plan)
    assert plan["budget"] is None


def test_references_and_remove_day():
    plan, _ = apply_trip_plan_tool("start_trip_plan", {"destination": "Rome"}, None)
    plan, _ = apply_trip_plan_tool("set_trip_day", {"day": 1, "title": "t", "activities": ["a"]}, plan)
    plan, result = apply_trip_plan_tool("set_trip_references", {"references": [{"title": "T", "url": "https://example.com"}]}, plan)
    assert result["references"] == 1
    assert plan["references"][0]["url"] == "https://example.com"
    plan, result = apply_trip_plan_tool("remove_trip_day", {"day": 1}, plan)
    assert result["days"] == []
    assert plan["days"] == []


def test_get_trip_plan_returns_assembled():
    plan = empty_trip_plan()
    plan["destination"] = "Rome"
    _, result = apply_trip_plan_tool("get_trip_plan", {}, plan)
    assert result["destination"] == "Rome"
    assert result["status"] == "displayed"


def test_assemble_sorts_and_defaults():
    assembled = assemble_trip_plan(
        {
            "destination": "X",
            "days": [
                {"day": 2, "title": "", "activities": None},
                {"day": 1, "title": "One", "activities": ["a"]},
            ],
        }
    )
    assert [day["day"] for day in assembled["days"]] == [1, 2]
    assert assembled["days"][0]["title"] == "One"
    assert assembled["days"][1]["title"] == "Day 2"
    assert assembled["days"][1]["activities"] == []


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("start_trip_plan", {"destination": "  "}),
        ("set_trip_day", {"day": 1, "title": "", "activities": ["a"]}),
        ("set_trip_day", {"day": 1, "title": "t", "activities": []}),
        ("set_trip_budget", {"day": 0}),
        ("remove_trip_day", {"day": 0}),
        ("set_trip_references", {"references": [{"title": "x", "url": "javascript:alert(1)"}]}),
        ("not_a_tool", {}),
    ],
)
def test_invalid_arguments_raise(name, arguments):
    with pytest.raises(ValueError):
        apply_trip_plan_tool(name, arguments, None)


def test_format_plan_context_includes_items_days_and_airport():
    context = format_plan_context(
        {
            "destination": "Rome",
            "currency": "EUR",
            "budget": 420,
            "budget_items": [{"category": "Food", "amount": 120, "currency": "EUR"}],
            "days": [{"day": 1, "budget": 200}],
            "airport": {"name": "FCO"},
        }
    )
    assert "Destination: Rome" in context
    assert "Arrival airport: FCO" in context
    assert "Total budget: EUR 420" in context
    assert "Day 1 budget: EUR 200" in context
    assert "Budget item Food: EUR 120" in context
    assert format_plan_context(None) == ""
    assert format_plan_context({}) == ""
