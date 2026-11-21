"""Chat routing helpers used by the stream endpoint.

Covers the route-map coordinate fallback that keeps the trip-plan map usable
when the model omits coordinates.
"""

from __future__ import annotations

from backend.main import _ensure_destination_coordinates


def test_ensure_destination_coordinates_fills_missing_point(
    monkeypatch,
) -> None:
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
