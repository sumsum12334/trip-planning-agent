"""Chat routing heuristics used by the stream endpoint.

Covers trip-request detection and the best-effort constraint parsing that feeds
the deterministic fallback pipeline (so fallback plans never carry dummy
``None`` values).
"""

from __future__ import annotations

from backend.main import _looks_like_trip_request, _parse_trip_constraints


def test_trip_request_detection() -> None:
    assert _looks_like_trip_request(
        "Plan a 4-day trip to Kyoto for $1,200, temples and food"
    )
    assert _looks_like_trip_request("Find me a hotel in Tokyo")
    assert not _looks_like_trip_request("Hello there")
    assert not _looks_like_trip_request("   ")


def test_constraints_parse_complete_starter_prompt() -> None:
    parsed = _parse_trip_constraints(
        "Plan a 5-day trip to Tokyo for $1,500, food and culture"
    )
    assert parsed == {"budget": 1500.0, "days": 5, "destination": "Tokyo"}


def test_constraints_keep_partial_results() -> None:
    parsed = _parse_trip_constraints("Plan a 3 day vacation for 800 dollars")
    assert parsed == {"budget": 800.0, "days": 3}


def test_constraints_parse_decimal_budget() -> None:
    parsed = _parse_trip_constraints("Plan a 2-day trip to Paris for $750.50")
    assert parsed["budget"] == 750.5
    assert parsed["days"] == 2
    assert parsed["destination"] == "Paris"


def test_ensure_destination_coordinates_fills_missing_point(
    monkeypatch,
) -> None:
    from backend.main import _ensure_destination_coordinates

    monkeypatch.setattr(
        "backend.main._destination_coordinates",
        lambda destination: {"lat": 35.01, "lng": 135.76},
    )
    plan = {"destination": "Kyoto", "days": [{"day": 1, "coordinates": None}]}
    filled = _ensure_destination_coordinates(plan)
    assert filled["destination_coordinates"] == {"lat": 35.01, "lng": 135.76}
    # The input plan is not mutated.
    assert "destination_coordinates" not in plan


def test_ensure_destination_coordinates_keeps_existing_points(
    monkeypatch,
) -> None:
    from backend.main import _ensure_destination_coordinates

    calls = []
    monkeypatch.setattr(
        "backend.main._destination_coordinates",
        lambda destination: calls.append(destination) or {"lat": 0, "lng": 0},
    )
    plan = {
        "destination": "Kyoto",
        "airport": {"name": "KIX", "coordinates": {"lat": 34.43, "lng": 135.23}},
        "days": [],
    }
    assert _ensure_destination_coordinates(plan) is plan
    assert calls == []

    day_plan = {
        "destination": "Kyoto",
        "days": [{"day": 1, "coordinates": {"lat": 35.0, "lng": 135.7}}],
    }
    assert _ensure_destination_coordinates(day_plan) is day_plan
    assert calls == []
