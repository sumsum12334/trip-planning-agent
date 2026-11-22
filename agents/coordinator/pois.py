"""Points of interest for Agent 3 — stub catalog plus dynamic web search."""

from __future__ import annotations

from collections.abc import Iterable

from config.settings import get_settings

# City catalogs: (name, interest tags, lat, lng). Tags are lowercase and optional.
# Fallback when web search is disabled or unavailable.
_CITY_POIS: dict[str, list[tuple[str, tuple[str, ...], float, float]]] = {
    "tokyo": [
        ("Tsukiji Outer Market", ("food",), 35.6654, 139.7708),
        ("Ichiran Shibuya", ("food",), 35.6597, 139.7006),
        ("Senso-ji", ("culture", "temple"), 35.7118, 139.7967),
        ("Meiji Shrine", ("culture", "temple"), 35.6765, 139.6993),
        ("teamLab Planets", ("museum", "art"), 35.6289, 139.7874),
        ("Shibuya Crossing", (), 35.6595, 139.7005),
        ("Tokyo Skytree", (), 35.7101, 139.8107),
        ("Shinjuku Gyoen", ("outdoors", "park"), 35.6844, 139.7112),
        ("Akihabara Electric Town", (), 35.7010, 139.7720),
    ],
    "hong kong": [
        ("Victoria Peak", ("outdoors", "view"), 22.2700, 114.1459),
        ("Star Ferry", (), 22.2889, 114.1592),
        ("Temple Street Night Market", ("food",), 22.3201, 114.1685),
        ("Ladies Market", (), 22.3228, 114.1669),
        ("Tian Tan Buddha", ("culture", "temple"), 22.2555, 113.9701),
        ("Central-Mid-Levels Escalator", (), 22.2805, 114.1532),
        ("Tsim Sha Tsui Promenade", ("outdoors", "view"), 22.2942, 114.1729),
        ("Man Mo Temple", ("culture", "temple"), 22.2867, 114.1528),
    ],
    "amsterdam": [
        ("Rijksmuseum", ("museum", "art", "culture"), 52.3594, 4.8849),
        ("Van Gogh Museum", ("museum", "art"), 52.3574, 4.8837),
        ("Anne Frank House", ("museum", "culture"), 52.3752, 4.8853),
        ("Canal cruise", ("outdoors",), 52.3676, 4.9041),
        ("Vondelpark", ("outdoors", "park"), 52.3562, 4.8773),
        ("Jordaan", ("food",), 52.3647, 4.8850),
        ("Albert Cuyp Market", ("food",), 52.3542, 4.9034),
    ],
}

_GENERIC_POIS: list[tuple[str, tuple[str, ...], float, float]] = [
    ("City Park", ("outdoors", "park"), 0.0, 0.0),
    ("Old Town Square", ("culture",), 0.0, 0.0),
    ("Central Market", ("food",), 0.0, 0.0),
    ("Waterfront Promenade", ("outdoors",), 0.0, 0.0),
    ("City Museum", ("museum", "art", "culture"), 0.0, 0.0),
    ("Night Market", ("food",), 0.0, 0.0),
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
) -> list[list[dict]]:
    """Pack unique POIs across ``days`` plans, preferring interest matches.

    Tries live web search first (when ``WEB_SEARCH_MODE=duckduckgo``), then
    falls back to the hardcoded stub catalog.

    Returns a list of lists of place dicts with ``name`` and ``coordinates``
    so the map can render each stop.
    """
    # Dynamic web search only when explicitly enabled: in stub mode the
    # placeholder result would otherwise take over the deterministic catalog
    # that tests and the evaluation harness rely on.
    if get_settings().web_search_mode == "duckduckgo":
        try:
            from agents.web_search import run as web_search
            from agents.search_stays.tools import NominatimGeocoder

            web_results = web_search(
                f"top tourist attractions {destination}", limit=days * per_day
            )
            if web_results:
                geocoder = NominatimGeocoder()
                dynamic_places: list[list[dict]] = [[] for _ in range(max(days, 1))]
                cursor = 0
                for result in web_results:
                    coords = None
                    try:
                        coords = geocoder.geocode(result.title)
                    except Exception:
                        coords = None
                    place = {
                        "name": result.title,
                        "coordinates": coords,
                        "url": result.url,
                        "snippet": result.snippet,
                    }
                    dynamic_places[cursor % max(days, 1)].append(place)
                    cursor += 1
                # Trim empty days
                dynamic_places = [d for d in dynamic_places if d]
                while len(dynamic_places) < max(days, 1):
                    dynamic_places.append([])
                return dynamic_places[: max(days, 1)]
        except Exception:
            # Web search unavailable — fall through to stub catalog
            pass

    # Fallback: stub catalog
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
    places: list[dict] = []
    for _index, (name, tags, lat, lng) in catalog:
        places.append({
            "name": name,
            "coordinates": {"lat": lat, "lng": lng},
        })
    packed: list[list[dict]] = [[] for _ in range(length)]
    if not places or per_day <= 0:
        return packed
    cursor = 0
    for day_index in range(length):
        for _ in range(per_day):
            if cursor >= len(places):
                return packed
            packed[day_index].append(places[cursor])
            cursor += 1
    return packed
