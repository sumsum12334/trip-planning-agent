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

# Temporal tails ("Japan last year", "Kyoto in 2019") are not part of the
# place name; cut the capture at the first temporal marker.
_TEMPORAL_TAIL = re.compile(
    r"\b(?:yesterday|tonight|ago|recently|"
    r"last\s+(?:year|month|week|summer|winter|spring|autumn|fall)|"
    r"when\s+i\s+was|in\s+(?:19|20)\d{2})\b.*$",
    re.IGNORECASE,
)

# Everyday activities that follow "went to / been to" but are not travel
# destinations ("I went to bed early", "been to the doctor").
_NON_PLACE_HEADS = frozenset(
    {
        "bed",
        "bathroom",
        "cinema",
        "court",
        "dentist",
        "doctor",
        "gym",
        "home",
        "hospital",
        "jail",
        "movies",
        "prison",
        "school",
        "sleep",
        "theater",
        "theatre",
        "work",
        "church",
    }
)

# A capture longer than this is a clause, not a place name.
_MAX_PLACE_WORDS = 6

_PLACE_ALIASES = {
    "the peak": "Victoria Peak",
    "peak": "Victoria Peak",
    "victoria peak": "Victoria Peak",
}


def _is_non_place(place: str) -> bool:
    """True for everyday phrases ("bed", "the doctor") that are not places."""
    words = place.split()
    if not words:
        return True
    head = words[0].casefold()
    if head == "the" and len(words) > 1:
        head = words[1].casefold()
    return head in _NON_PLACE_HEADS


def extract_visited_places(message: str) -> list[str]:
    """Return places explicitly described as visited in a user message."""
    places: list[str] = []
    for match in _VISIT_PATTERN.finditer(message):
        place = " ".join(match.group("place").split()).strip(" .,!?:;")
        if place.casefold().endswith(" before"):
            place = place[:-7].rstrip()
        place = _TEMPORAL_TAIL.sub("", place).strip(" .,!?:;")
        if not place or len(place.split()) > _MAX_PLACE_WORDS:
            continue
        if _is_non_place(place):
            continue
        place = _PLACE_ALIASES.get(place.casefold(), place)
        if place.casefold() not in {item.casefold() for item in places}:
            places.append(place)
    return places
