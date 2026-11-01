"""Extract explicit past-visit statements from user chat messages."""

from __future__ import annotations

import re

_VISIT_PATTERN = re.compile(
    r"\b(?:i\s+)?(?:have\s+)?(?:already\s+)?"
    r"(?:been\s+to|went\s+to|go\s+to|gone\s+to|visited|travelled\s+to|traveled\s+to)"
    r"\s+(?P<place>[^.!?,;\n]+?)"
    r"(?=\s+before\b|\s+and\s+(?:i\s+)?(?:have\s+)?(?:been|went|go|gone|visited|travelled|traveled)\b|[.!?,;\n]|$)",
    re.IGNORECASE,
)
_PLACE_ALIASES = {
    "the peak": "Victoria Peak",
    "peak": "Victoria Peak",
    "victoria peak": "Victoria Peak",
}


def extract_visited_places(message: str) -> list[str]:
    """Return places explicitly described as visited in a user message."""
    places: list[str] = []
    for match in _VISIT_PATTERN.finditer(message):
        place = " ".join(match.group("place").split()).strip(" .,!?:;")
        if place.casefold().endswith(" before"):
            place = place[:-7].rstrip()
        if not place:
            continue
        place = _PLACE_ALIASES.get(place.casefold(), place)
        if place.casefold() not in {item.casefold() for item in places}:
            places.append(place)
    return places
