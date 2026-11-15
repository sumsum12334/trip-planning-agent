"""Visit-history overlap used by Agent 1 and the eval harness."""

from __future__ import annotations

import re
from collections.abc import Iterable


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold().strip())


def _tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", _norm(value)) if token]


def _contains_phrase(phrase: str, text: str) -> bool:
    needle, haystack = _tokens(phrase), _tokens(text)
    if not needle or not haystack:
        return False
    width = len(needle)
    return any(haystack[i : i + width] == needle for i in range(len(haystack) - width + 1))


def _is_word_prefix(phrase: str, text: str) -> bool:
    needle, haystack = _tokens(phrase), _tokens(text)
    return bool(needle) and len(needle) < len(haystack) and haystack[: len(needle)] == needle


def place_overlaps_stay(place: str, *, name: str, location: str) -> bool:
    """True if a visited place is specific enough to match this stay.

    A city-only label such as "Tokyo" is a word-prefix of "Tokyo Shibuya"
    and does not count; a neighborhood alias such as "shibuya" does.
    """
    place_n = _norm(place)
    name_n = _norm(name)
    location_n = _norm(location)
    if not place_n:
        return False
    if place_n == location_n or place_n == name_n:
        return True
    for text, text_n in ((location, location_n), (name, name_n)):
        if not _contains_phrase(place, text):
            continue
        # City-level prefix of the location (e.g. "Tokyo" vs "Tokyo Shibuya").
        if text_n == location_n and _is_word_prefix(place, location):
            continue
        return True
    return False


def stay_overlaps_places(name: str, location: str, places: Iterable[str]) -> bool:
    return any(
        place_overlaps_stay(place, name=name, location=location)
        for place in places
        if place and str(place).strip()
    )
