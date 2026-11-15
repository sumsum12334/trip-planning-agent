"""Stub points of interest for Agent 3 to pack into day plans."""

from __future__ import annotations

from collections.abc import Iterable

# City catalogs: (name, interest tags). Tags are lowercase and optional.
_CITY_POIS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "tokyo": [
        ("Tsukiji Outer Market", ("food",)),
        ("Ichiran Shibuya", ("food",)),
        ("Senso-ji", ("culture", "temple")),
        ("Meiji Shrine", ("culture", "temple")),
        ("teamLab Planets", ("museum", "art")),
        ("Shibuya Crossing", ()),
        ("Tokyo Skytree", ()),
        ("Shinjuku Gyoen", ("outdoors", "park")),
        ("Akihabara Electric Town", ()),
    ],
    "hong kong": [
        ("Victoria Peak", ("outdoors", "view")),
        ("Star Ferry", ()),
        ("Temple Street Night Market", ("food",)),
        ("Ladies Market", ()),
        ("Tian Tan Buddha", ("culture", "temple")),
        ("Central-Mid-Levels Escalator", ()),
        ("Tsim Sha Tsui Promenade", ("outdoors", "view")),
        ("Man Mo Temple", ("culture", "temple")),
    ],
    "amsterdam": [
        ("Rijksmuseum", ("museum", "art", "culture")),
        ("Van Gogh Museum", ("museum", "art")),
        ("Anne Frank House", ("museum", "culture")),
        ("Canal cruise", ("outdoors",)),
        ("Vondelpark", ("outdoors", "park")),
        ("Jordaan", ("food",)),
        ("Albert Cuyp Market", ("food",)),
    ],
}

_GENERIC_POIS: list[tuple[str, tuple[str, ...]]] = [
    ("City Park", ("outdoors", "park")),
    ("Old Town Square", ("culture",)),
    ("Central Market", ("food",)),
    ("Waterfront Promenade", ("outdoors",)),
    ("City Museum", ("museum", "art", "culture")),
    ("Night Market", ("food",)),
]


def _catalog_for(destination: str) -> list[tuple[str, tuple[str, ...]]]:
    dest = destination.casefold()
    for city, rows in _CITY_POIS.items():
        if city in dest or dest in city:
            return list(rows)
    # Also allow "Hong Kong Central" style destinations via token overlap.
    for city, rows in _CITY_POIS.items():
        if any(token and token in dest for token in city.split()):
            return list(rows)
    return list(_GENERIC_POIS)


def _interest_score(tags: tuple[str, ...], interests: list[str]) -> int:
    if not interests:
        return 0
    wanted = {item.casefold() for item in interests if item}
    return sum(1 for tag in tags if tag in wanted)


def _is_excluded(name: str, excluded: set[str]) -> bool:
    folded = name.casefold()
    return any(place in folded or folded in place for place in excluded)


def pack_pois(
    destination: str,
    days: int,
    interests: Iterable[str] | None = None,
    excluded: Iterable[str] | None = None,
    per_day: int = 2,
) -> list[list[str]]:
    """Pack unique stub POIs across ``days`` plans, preferring interest matches."""
    length = max(days, 1)
    interest_list = [item for item in (interests or []) if item]
    excluded_set = {place.strip().casefold() for place in (excluded or []) if place and place.strip()}
    catalog = [
        row for row in _catalog_for(destination) if not _is_excluded(row[0], excluded_set)
    ]
    catalog = sorted(
        enumerate(catalog),
        key=lambda item: (-_interest_score(item[1][1], interest_list), item[0]),
    )
    names = [name for _index, (name, _tags) in catalog]
    packed: list[list[str]] = [[] for _ in range(length)]
    if not names or per_day <= 0:
        return packed
    cursor = 0
    for day_index in range(length):
        for _ in range(per_day):
            if cursor >= len(names):
                return packed
            packed[day_index].append(names[cursor])
            cursor += 1
    return packed
