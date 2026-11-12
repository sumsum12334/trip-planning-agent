"""Gold tool-call cases for the chat tool executor (Agent 1 / 2 / web_search).

These score the tool layer: given the arguments a model *should* pass, do the
tools run and return usable results? Live model routing accuracy needs a
configured QWEN endpoint and is not part of this default suite.
"""

from __future__ import annotations

from typing import Any, TypedDict


class GoldCall(TypedDict, total=False):
    name: str
    arguments: dict[str, Any]
    expect_error: bool
    min_stays: int
    require_transport_fields: bool


class ToolCase(TypedDict, total=False):
    id: str
    description: str
    message: str
    gold_calls: list[GoldCall]


TOOL_CASES: list[ToolCase] = [
    {
        "id": "tool_search_stays_tokyo",
        "description": "User asks for a Tokyo stay; gold call is search_stays with destination, days, and budget.",
        "message": "Find a cheap hotel in Tokyo for 4 days, budget 400.",
        "gold_calls": [
            {
                "name": "search_stays",
                "arguments": {
                    "destination": "Tokyo",
                    "days": 4,
                    "budget": 400,
                    "interests": ["food"],
                },
                "min_stays": 1,
            }
        ],
    },
    {
        "id": "tool_estimate_transport_hk",
        "description": "User asks travel time Central to Kowloon; gold call is estimate_transport.",
        "message": "How long does it take from Hong Kong Central to Hong Kong Kowloon?",
        "gold_calls": [
            {
                "name": "estimate_transport",
                "arguments": {
                    "from_place": "Hong Kong Central",
                    "to_place": "Hong Kong Kowloon",
                },
                "require_transport_fields": True,
            }
        ],
    },
    {
        "id": "tool_stays_and_transport_amsterdam",
        "description": "User asks for a stay and airport transfer; both tools should be invoked.",
        "message": "Book a place in Amsterdam and tell me how to get from Schiphol to Centrum.",
        "gold_calls": [
            {
                "name": "search_stays",
                "arguments": {"destination": "Amsterdam", "days": 3, "budget": 400},
                "min_stays": 1,
            },
            {
                "name": "estimate_transport",
                "arguments": {
                    "from_place": "Amsterdam Schiphol",
                    "to_place": "Amsterdam Centrum",
                },
                "require_transport_fields": True,
            },
        ],
    },
    {
        "id": "tool_search_stays_missing_destination",
        "description": "search_stays without destination should fail closed.",
        "message": "Find me a hotel.",
        "gold_calls": [
            {
                "name": "search_stays",
                "arguments": {"budget": 200, "days": 3},
                "expect_error": True,
            }
        ],
    },
    {
        "id": "tool_unknown_name",
        "description": "An unknown tool name should raise a clear error.",
        "message": "(invalid tool)",
        "gold_calls": [
            {
                "name": "book_flight",
                "arguments": {"destination": "Tokyo"},
                "expect_error": True,
            }
        ],
    },
]
