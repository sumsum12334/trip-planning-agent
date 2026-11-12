"""Fixed evaluation cases for Baseline A vs Proposed.

Cases are deterministic against the stub stay / transport catalogs.
History-avoidance cases seed Agent 4 and set avoid_visited=True.
"""

from __future__ import annotations

from typing import Any, TypedDict


class HistorySeed(TypedDict, total=False):
    location: str
    city: str
    country: str


class CaseExpect(TypedDict, total=False):
    min_stays: int
    stay_location_contains: list[str]
    nightly_cost_within_budget: bool
    transport_required: bool
    expected_days: int
    history_avoidance: bool
    allow_generic_fallback: bool
    transport_same_place: bool
    transport_from: str
    transport_to: str


class EvalCase(TypedDict, total=False):
    id: str
    description: str
    request: dict[str, Any]
    history: list[HistorySeed]
    expect: CaseExpect


CASES: list[EvalCase] = [
    {
        "id": "tokyo_budget_ok",
        "description": "Tokyo 4-day trip under a $400 budget; catalog stays stay in Tokyo and under the nightly cap.",
        "request": {
            "destination": "Tokyo",
            "origin": "Tokyo Shinjuku",
            "days": 4,
            "budget": 400,
            "interests": ["food"],
            "avoid_visited": False,
            "user_id": "eval-tokyo-budget",
        },
        "history": [],
        "expect": {
            "min_stays": 1,
            "stay_location_contains": ["tokyo"],
            "nightly_cost_within_budget": True,
            "transport_required": True,
            "expected_days": 4,
            "history_avoidance": False,
            "allow_generic_fallback": False,
        },
    },
    {
        "id": "tokyo_history_avoid_shibuya",
        "description": "Same Tokyo trip, but history includes Tokyo Shibuya; Proposed should drop Shibuya stays, Baseline A should still suggest them.",
        "request": {
            "destination": "Tokyo",
            "origin": "Tokyo Shinjuku",
            "days": 4,
            "budget": 400,
            "interests": ["food"],
            "avoid_visited": True,
            "user_id": "eval-tokyo-history",
        },
        "history": [
            {"location": "Tokyo Shibuya", "city": "Tokyo", "country": "Japan"},
        ],
        "expect": {
            "min_stays": 1,
            "stay_location_contains": ["tokyo"],
            "nightly_cost_within_budget": True,
            "transport_required": True,
            "expected_days": 4,
            "history_avoidance": True,
            "allow_generic_fallback": False,
        },
    },
    {
        "id": "tokyo_history_without_avoid_flag",
        "description": "History is present but avoid_visited is false; neither variant should filter Shibuya.",
        "request": {
            "destination": "Tokyo",
            "origin": "Tokyo Shinjuku",
            "days": 3,
            "budget": 360,
            "interests": [],
            "avoid_visited": False,
            "user_id": "eval-tokyo-no-avoid",
        },
        "history": [
            {"location": "Tokyo Shibuya", "city": "Tokyo", "country": "Japan"},
        ],
        "expect": {
            "min_stays": 1,
            "stay_location_contains": ["tokyo"],
            "nightly_cost_within_budget": True,
            "transport_required": True,
            "expected_days": 3,
            "history_avoidance": False,
            "allow_generic_fallback": False,
        },
    },
    {
        "id": "hk_budget_ok",
        "description": "Hong Kong 3-day trip with a mid budget; stays should match Hong Kong labels.",
        "request": {
            "destination": "Hong Kong",
            "origin": "Hong Kong Airport",
            "days": 3,
            "budget": 300,
            "interests": ["city"],
            "avoid_visited": False,
            "user_id": "eval-hk-budget",
        },
        "history": [],
        "expect": {
            "min_stays": 1,
            "stay_location_contains": ["hong kong"],
            "nightly_cost_within_budget": True,
            "transport_required": True,
            "expected_days": 3,
            "history_avoidance": False,
            "allow_generic_fallback": False,
        },
    },
    {
        "id": "hk_tight_budget",
        "description": "Hong Kong tight budget (nightly cap 50) should only admit the cheapest catalog hostel.",
        "request": {
            "destination": "Hong Kong",
            "origin": "Hong Kong Central",
            "days": 3,
            "budget": 150,
            "interests": [],
            "avoid_visited": False,
            "user_id": "eval-hk-tight",
        },
        "history": [],
        "expect": {
            "min_stays": 1,
            "stay_location_contains": ["hong kong"],
            "nightly_cost_within_budget": True,
            "transport_required": True,
            "expected_days": 3,
            "history_avoidance": False,
            "allow_generic_fallback": False,
        },
    },
    {
        "id": "hk_history_avoid_central",
        "description": "Visited Hong Kong Central; Proposed should avoid Central stays, Baseline A should not.",
        "request": {
            "destination": "Hong Kong",
            "origin": "Hong Kong Airport",
            "days": 3,
            "budget": 600,
            "interests": [],
            "avoid_visited": True,
            "user_id": "eval-hk-history",
        },
        "history": [
            {"location": "Hong Kong Central", "city": "Hong Kong", "country": "HK"},
        ],
        "expect": {
            "min_stays": 1,
            "stay_location_contains": ["hong kong"],
            "nightly_cost_within_budget": True,
            "transport_required": True,
            "expected_days": 3,
            "history_avoidance": True,
            "allow_generic_fallback": False,
        },
    },
    {
        "id": "amsterdam_ok",
        "description": "Amsterdam catalog match under budget.",
        "request": {
            "destination": "Amsterdam",
            "origin": "Amsterdam Schiphol",
            "days": 3,
            "budget": 400,
            "interests": ["museums"],
            "avoid_visited": False,
            "user_id": "eval-amsterdam",
        },
        "history": [],
        "expect": {
            "min_stays": 1,
            "stay_location_contains": ["amsterdam"],
            "nightly_cost_within_budget": True,
            "transport_required": True,
            "expected_days": 3,
            "history_avoidance": False,
            "allow_generic_fallback": False,
        },
    },
    {
        "id": "unknown_city_generic_fallback",
        "description": "Unknown city should fall back to the generic stay catalog without exceeding budget.",
        "request": {
            "destination": "Atlantis",
            "origin": "Atlantis Harbor",
            "days": 3,
            "budget": 300,
            "interests": [],
            "avoid_visited": False,
            "user_id": "eval-atlantis",
        },
        "history": [],
        "expect": {
            "min_stays": 1,
            "stay_location_contains": ["generic"],
            "nightly_cost_within_budget": True,
            "transport_required": True,
            "expected_days": 3,
            "history_avoidance": False,
            "allow_generic_fallback": True,
        },
    },
    {
        "id": "empty_catalog_tight_budget",
        "description": "Budget below every catalog nightly rate; Agent 1 may return no stays, itinerary should still be produced.",
        "request": {
            "destination": "Tokyo",
            "origin": "Tokyo Shinjuku",
            "days": 3,
            "budget": 20,
            "interests": [],
            "avoid_visited": False,
            "user_id": "eval-tokyo-empty",
        },
        "history": [],
        "expect": {
            "min_stays": 0,
            "nightly_cost_within_budget": True,
            "transport_required": True,
            "expected_days": 3,
            "history_avoidance": False,
            "allow_generic_fallback": True,
        },
    },
    {
        "id": "transport_same_place_walk",
        "description": "Direct Agent 2 check: identical from/to should be a short walk with zero cost.",
        "request": {
            "destination": "Tokyo",
            "origin": "Tokyo Shibuya",
            "days": 2,
            "budget": 200,
            "interests": [],
            "avoid_visited": False,
            "user_id": "eval-walk",
        },
        "history": [],
        "expect": {
            "min_stays": 0,
            "transport_required": True,
            "transport_same_place": True,
            "transport_from": "Tokyo Shibuya",
            "transport_to": "Tokyo Shibuya",
            "expected_days": 2,
            "history_avoidance": False,
            "allow_generic_fallback": True,
        },
    },
    {
        "id": "tokyo_history_multiple_places",
        "description": "Visited Shibuya and Shinjuku; with a higher budget, Proposed should still have Asakusa while Baseline A keeps all three.",
        "request": {
            "destination": "Tokyo",
            "origin": "Tokyo Shinjuku",
            "days": 4,
            "budget": 800,
            "interests": ["culture"],
            "avoid_visited": True,
            "user_id": "eval-tokyo-multi-history",
        },
        "history": [
            {"location": "Tokyo Shibuya", "city": "Tokyo", "country": "Japan"},
            {"location": "Tokyo Shinjuku", "city": "Tokyo", "country": "Japan"},
        ],
        "expect": {
            "min_stays": 1,
            "stay_location_contains": ["tokyo"],
            "nightly_cost_within_budget": True,
            "transport_required": True,
            "expected_days": 4,
            "history_avoidance": True,
            "allow_generic_fallback": False,
        },
    },
    {
        "id": "tokyo_history_unrelated_place",
        "description": "History is Hong Kong but the trip is Tokyo; avoid_visited should not strip Tokyo stays.",
        "request": {
            "destination": "Tokyo",
            "origin": "Tokyo Shinjuku",
            "days": 3,
            "budget": 360,
            "interests": [],
            "avoid_visited": True,
            "user_id": "eval-tokyo-unrelated-history",
        },
        "history": [
            {"location": "Hong Kong Central", "city": "Hong Kong", "country": "HK"},
        ],
        "expect": {
            "min_stays": 1,
            "stay_location_contains": ["tokyo"],
            "nightly_cost_within_budget": True,
            "transport_required": True,
            "expected_days": 3,
            "history_avoidance": False,
            "allow_generic_fallback": False,
            "no_false_history_exclusion": True,
        },
    },
    {
        "id": "hk_over_budget_transport",
        "description": "Tight total budget can be blown by transport even when nightly stay cap is met. Tracks whether Coordinator revises; current Agent 3 has no revise loop.",
        "request": {
            "destination": "Hong Kong",
            "origin": "Hong Kong Airport",
            "days": 3,
            "budget": 150,
            "interests": [],
            "avoid_visited": False,
            "user_id": "eval-hk-overrun",
        },
        "history": [],
        "expect": {
            "min_stays": 1,
            "stay_location_contains": ["hong kong"],
            "nightly_cost_within_budget": True,
            "transport_required": True,
            "expected_days": 3,
            "history_avoidance": False,
            "allow_generic_fallback": False,
            "expect_revise": True,
        },
    },
]
