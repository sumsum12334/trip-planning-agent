"""Tests for the shared `display_trip_plan` schema and payload validation."""

from __future__ import annotations

import pytest

from shared.trip_plan import (
    TRIP_PLAN_TOOL,
    format_plan_context,
    normalize_trip_plan,
)


def test_normalize_full_payload_keeps_map_and_references():
    plan = normalize_trip_plan(
        {
            "destination": "Kyoto",
            "currency": "JPY",
            "budget": 800,
            "destination_coordinates": {"lat": 35.0116, "lng": 135.7681},
            "days": [
                {
                    "day": 1,
                    "title": "Arrival",
                    "activities": ["Check in", "Walk Gion"],
                    "notes": ["Jet lag friendly"],
                    "places": [
                        {
                            "name": "Gion",
                            "coordinates": {"lat": 35.0037, "lng": 135.7788},
                            "url": "https://example.com/gion",
                        }
                    ],
                }
            ],
            "references": [{"title": "Guide", "url": "https://example.com/guide"}],
        }
    )
    assert plan["status"] == "displayed"
    assert plan["destination_coordinates"] == {"lat": 35.0116, "lng": 135.7681}
    assert plan["budget"] == 800.0
    assert plan["currency"] == "JPY"
    assert plan["days"][0]["places"][0]["coordinates"] == {"lat": 35.0037, "lng": 135.7788}
    assert plan["references"][0]["url"] == "https://example.com/guide"


def test_normalize_defaults_optional_fields():
    plan = normalize_trip_plan(
        {"destination": "Lisbon", "days": [{"day": 1, "title": "Old town", "activities": ["Tram 28"]}]}
    )
    assert plan["budget"] is None
    assert plan["currency"] == ""
    assert plan["airport"] is None
    assert plan["destination_coordinates"] is None
    assert plan["days"][0]["coordinates"] is None
    assert plan["days"][0]["places"] == []
    assert plan["references"] == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"destination": "", "days": [{"day": 1, "title": "t", "activities": ["a"]}]},
        {"destination": "X", "days": []},
        {"destination": "X", "days": [{"day": 1, "title": "", "activities": ["a"]}]},
        {"destination": "X", "days": [{"day": 1, "title": "t", "activities": []}]},
        {"destination": "X", "days": [{"day": 1, "title": "t", "activities": ["a"], "coordinates": {"lat": 200, "lng": 0}}]},
        {"destination": "X", "days": [{"day": 1, "title": "t", "activities": ["a"]}], "budget": -5},
        {"destination": "X", "days": [{"day": 1, "title": "t", "activities": ["a"]}], "references": [{"title": "bad", "url": "javascript:alert(1)"}]},
        {"destination": "X", "days": [{"day": 1, "title": "t", "activities": ["a"]}], "references": [{"title": "", "url": "https://example.com"}]},
    ],
)
def test_normalize_rejects_invalid_payloads(arguments):
    with pytest.raises(ValueError):
        normalize_trip_plan(arguments)


def test_tool_schema_requires_destination_and_days():
    parameters = TRIP_PLAN_TOOL["function"]["parameters"]
    assert TRIP_PLAN_TOOL["function"]["name"] == "display_trip_plan"
    assert set(parameters["required"]) == {"destination", "days"}
    assert "references" in parameters["properties"]
    assert "destination_coordinates" in parameters["properties"]
    assert "budget_items" in parameters["properties"]


def test_budget_items_do_not_affect_estimated_total():
    plan = normalize_trip_plan(
        {
            "destination": "Rome",
            "currency": "EUR",
            "days": [{"day": 1, "title": "Arrival", "activities": ["Check in"]}],
            "budget_items": [
                {"category": "Accommodation", "amount": 300},
                {"category": "transport", "amount": 120},
                {"category": "Accommodation", "amount": 500},  # duplicate category dropped
            ],
        }
    )
    # The estimated total stays independent of the item breakdown.
    assert plan["budget"] is None
    assert [item["category"] for item in plan["budget_items"]] == ["Accommodation", "transport"]
    assert plan["budget_items"][0]["currency"] == "EUR"


def test_airport_and_per_day_budget_are_normalized():
    plan = normalize_trip_plan(
        {
            "destination": "Hong Kong",
            "airport": {"name": "Hong Kong International Airport", "coordinates": {"lat": 22.308, "lng": 113.9185}},
            "days": [
                {
                    "day": 1,
                    "title": "Arrival",
                    "activities": ["Land"],
                    "budget": 1200,
                    "budget_items": [{"category": "Transport", "amount": 200}, {"category": "Food", "amount": 100}],
                }
            ],
        }
    )
    assert plan["airport"]["name"] == "Hong Kong International Airport"
    assert plan["airport"]["coordinates"] == {"lat": 22.308, "lng": 113.9185}
    assert plan["days"][0]["budget"] == 1200.0
    assert [item["category"] for item in plan["days"][0]["budget_items"]] == ["Transport", "Food"]
    assert plan["days"][0]["budget_items"][0]["currency"] == ""


def test_budget_items_reject_bad_amounts():
    with pytest.raises(ValueError):
        normalize_trip_plan(
            {
                "destination": "Rome",
                "days": [{"day": 1, "title": "Arrival", "activities": ["Check in"]}],
                "budget_items": [{"category": "Food", "amount": -3}],
            }
        )


def test_format_plan_context_includes_items_and_total():
    context = format_plan_context(
        {
            "destination": "Rome",
            "currency": "EUR",
            "budget": 420,
            "budget_items": [{"category": "Food", "amount": 120, "currency": "EUR"}],
        }
    )
    assert "Destination: Rome" in context
    assert "Total budget: EUR 420" in context
    assert "Budget item Food: EUR 120" in context
    assert format_plan_context(None) == ""
    assert format_plan_context({}) == ""
