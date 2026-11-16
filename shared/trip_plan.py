"""Shared schema, validation, and assembly for the trip-plan UI tools.

The plan is built with several small tools instead of one large
`display_trip_plan` payload so the model only sends the part it changes and the
UI can render the plan part by part:

- ``start_trip_plan``      overview (destination, arrival airport, currency, total, notes)
- ``set_trip_day``         one day (call once per day)
- ``set_trip_budget``      the total or one day's budget and/or item breakdown
- ``set_trip_references``  reference links
- ``remove_trip_day``      drop a day
- ``get_trip_plan``        read the current plan before adjusting it

The assembled plan is stored per conversation and rendered by the browser.
Keeping the JSON schema and validation in one module keeps the streaming and
continuation endpoints consistent.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

MAX_DAYS = 14
MAX_PLACES_PER_DAY = 12
MAX_REFERENCES = 20
MAX_BUDGET_ITEMS = 12
MAX_CURRENCY_CHARS = 12
ALLOWED_URL_SCHEMES = {"http", "https"}

# The UI renders any event whose data.tool is this marker and data.result is a plan.
TRIP_PLAN_UI_TOOL = "display_trip_plan"

_COORDINATE_SCHEMA = {
    "type": "object",
    "description": "Approximate geographic point.",
    "properties": {
        "lat": {"type": "number", "minimum": -90, "maximum": 90},
        "lng": {"type": "number", "minimum": -180, "maximum": 180},
    },
    "required": ["lat", "lng"],
}

_PLACE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Place name shown in the plan and map."},
        "coordinates": _COORDINATE_SCHEMA,
        "url": {"type": "string", "description": "Optional http(s) reference for this place."},
    },
    "required": ["name"],
}

_AIRPORT_SCHEMA = {
    "type": "object",
    "description": (
        "Arrival airport for the destination. It is used as the first point of "
        "the route map, so provide the airport the traveller flies into."
    ),
    "properties": {
        "name": {"type": "string", "description": "Airport name or IATA code."},
        "coordinates": _COORDINATE_SCHEMA,
        "url": {"type": "string", "description": "Optional http(s) reference for the airport."},
    },
    "required": ["name"],
}

_BUDGET_ITEMS_SCHEMA = {
    "type": "array",
    "description": (
        "Per-category budget breakdown. Use concrete categories "
        "(accommodation, transport, food, activities, entrance fees, shopping, "
        "buffer). Avoid a vague 'other' bucket unless the amount is genuinely "
        "small and miscellaneous."
    ),
    "items": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "description": "A concrete spending category."},
            "amount": {"type": "number", "minimum": 0},
        },
        "required": ["category", "amount"],
    },
    "maxItems": MAX_BUDGET_ITEMS,
}

_REFERENCES_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "url": {"type": "string"},
        },
        "required": ["title", "url"],
    },
    "maxItems": MAX_REFERENCES,
}

TRIP_PLAN_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "start_trip_plan",
            "description": (
                "Create or update the trip-plan overview: destination, arrival "
                "airport, currency, estimated total budget, and notes. Call this "
                "once before adding days."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string"},
                    "destination_coordinates": _COORDINATE_SCHEMA,
                    "airport": _AIRPORT_SCHEMA,
                    "currency": {"type": "string"},
                    "budget": {"type": "number", "minimum": 0, "description": "Estimated total budget (independent of item breakdowns)."},
                    "notes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_trip_day",
            "description": (
                "Add or replace a single day of the plan. Call once per day and "
                "send only that day's fields; re-call it to change one day."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "day": {"type": "integer", "minimum": 1},
                    "title": {"type": "string"},
                    "activities": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "array", "items": {"type": "string"}},
                    "coordinates": _COORDINATE_SCHEMA,
                    "places": {"type": "array", "items": _PLACE_SCHEMA},
                    "stays": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "location": {"type": "string"},
                                "nightly_cost": {"type": "number"},
                                "currency": {"type": "string"},
                                "rating": {"type": "number"},
                                "property_type": {"type": "string"},
                                "check_in": {"type": "string"},
                                "check_out": {"type": "string"},
                                "cancellation_policy": {"type": "string"},
                                "amenities": {"type": "array", "items": {"type": "string"}},
                                "source_url": {"type": "string"},
                                "phone": {"type": "string"},
                                "coordinates": _COORDINATE_SCHEMA,
                                "notes": {"type": "string"},
                            },
                            "required": ["name"],
                        },
                    },
                    "budget": {"type": "number", "minimum": 0, "description": "Estimated cost for this day."},
                    "budget_items": _BUDGET_ITEMS_SCHEMA,
                },
                "required": ["day", "title", "activities"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_trip_budget",
            "description": (
                "Set the estimated budget. Pass `day` to set that day's estimate "
                "and/or its item breakdown, or omit `day` for the overall total "
                "and/or the global item breakdown. Send only the parts that changed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "day": {"type": "integer", "minimum": 1},
                    "budget": {"type": "number", "minimum": 0},
                    "currency": {"type": "string"},
                    "items": _BUDGET_ITEMS_SCHEMA,
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_trip_references",
            "description": "Set the reference links for the plan.",
            "parameters": {
                "type": "object",
                "properties": {"references": _REFERENCES_SCHEMA},
                "required": ["references"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_trip_day",
            "description": "Remove a day from the plan by its number.",
            "parameters": {
                "type": "object",
                "properties": {"day": {"type": "integer", "minimum": 1}},
                "required": ["day"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trip_plan",
            "description": (
                "Return the current trip plan so you can read it before an "
                "adjustment. Do not use it to display the plan."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TRIP_PLAN_TOOL_NAMES = {tool["function"]["name"] for tool in TRIP_PLAN_TOOLS}


def _coordinate(value: Any, *, field: str) -> dict[str, float] | None:
    """Validate an optional ``{lat, lng}`` point and return a normalized copy."""
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object with lat and lng.")
    lat = value.get("lat")
    lng = value.get("lng", value.get("lon"))
    if (
        isinstance(lat, bool)
        or isinstance(lng, bool)
        or not isinstance(lat, (int, float))
        or not isinstance(lng, (int, float))
    ):
        raise ValueError(f"{field} must include numeric lat and lng.")
    if not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise ValueError(f"{field} is outside valid latitude and longitude bounds.")
    return {"lat": float(lat), "lng": float(lng)}


def _url(value: Any, *, field: str) -> str:
    """Validate an absolute http(s) URL."""
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in ALLOWED_URL_SCHEMES or not parsed.netloc:
        raise ValueError(f"{field} must be an absolute http:// or https:// URL.")
    return text


def _clean_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item).strip())]


def _optional_number(value: Any, *, field: str) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{field} must be a non-negative number.")
    return float(value)


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _places(value: Any, *, day_number: int) -> list[dict[str, Any]]:
    """Normalize an optional list of per-day places with coordinates and links."""
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("Each trip day's places must be a list.")
    places: list[dict[str, Any]] = []
    for item in value[:MAX_PLACES_PER_DAY]:
        if isinstance(item, str):
            name = item.strip()
            if name:
                places.append({"name": name, "coordinates": None, "url": None})
            continue
        if not isinstance(item, dict):
            raise ValueError("Each place must be a name string or an object.")
        name = str(item.get("name", "")).strip()
        if not name:
            raise ValueError(f"Day {day_number} has a place without a name.")
        raw_url = item.get("url")
        places.append(
            {
                "name": name,
                "coordinates": _coordinate(
                    item.get("coordinates"),
                    field=f"Day {day_number} place coordinates",
                ),
                "url": _url(raw_url, field=f"Day {day_number} place URL")
                if raw_url not in (None, "")
                else None,
            }
        )
    return places


def _stays(value: Any, *, day_number: int) -> list[dict[str, Any]]:
    """Normalize an optional list of stay candidates with booking URLs."""
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("Each trip day's stays must be a list.")
    stays: list[dict[str, Any]] = []
    for item in value[:MAX_PLACES_PER_DAY]:
        if not isinstance(item, dict):
            raise ValueError(f"Day {day_number} has a stay that is not an object.")
        name = str(item.get("name", "")).strip()
        if not name:
            raise ValueError(f"Day {day_number} has a stay without a name.")
        raw_url = item.get("source_url")
        stays.append(
            {
                "name": name,
                "location": str(item.get("location", "")).strip() or None,
                "nightly_cost": _number_or_none(item.get("nightly_cost")),
                "currency": str(item.get("currency", "")).strip() or None,
                "rating": _number_or_none(item.get("rating")),
                "property_type": str(item.get("property_type", "")).strip() or None,
                "check_in": str(item.get("check_in", "")).strip() or None,
                "check_out": str(item.get("check_out", "")).strip() or None,
                "cancellation_policy": str(
                    item.get("cancellation_policy", "")
                ).strip()
                or None,
                "amenities": list(item.get("amenities") or []),
                "source_url": _url(raw_url, field=f"Day {day_number} stay URL")
                if raw_url not in (None, "")
                else None,
                "phone": str(item.get("phone", "")).strip() or None,
                "coordinates": _coordinate(
                    item.get("coordinates"),
                    field=f"Day {day_number} stay coordinates",
                )
                if item.get("coordinates")
                else None,
                "notes": str(item.get("notes", "")).strip() or None,
            }
        )
    return stays


def _airport(value: Any) -> dict[str, Any] | None:
    """Normalize the optional arrival airport (the first route point)."""
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise ValueError("airport must be an object with a name.")
    name = str(value.get("name", "")).strip()
    if not name:
        raise ValueError("airport requires a name.")
    raw_url = value.get("url")
    return {
        "name": name,
        "coordinates": _coordinate(value.get("coordinates"), field="Airport coordinates"),
        "url": _url(raw_url, field="Airport URL") if raw_url not in (None, "") else None,
    }


def _budget_items(value: Any, *, currency: str) -> list[dict[str, Any]]:
    """Normalize an optional per-category budget breakdown."""
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("Budget items must be a list of category and amount objects.")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value[:MAX_BUDGET_ITEMS]:
        if not isinstance(item, dict):
            raise ValueError("Each budget item must be an object with category and amount.")
        category = str(item.get("category", "")).strip()
        amount = item.get("amount")
        if not category:
            raise ValueError("Each budget item requires a category.")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 0:
            raise ValueError(f"Budget item '{category}' requires a non-negative amount.")
        key = category.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append({"category": category, "amount": float(amount), "currency": currency})
    return items


def _references(value: Any) -> list[dict[str, str]]:
    """Normalize an optional list of title/url reference links."""
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("References must be a list of title and url objects.")
    references: list[dict[str, str]] = []
    for item in value[:MAX_REFERENCES]:
        if not isinstance(item, dict):
            raise ValueError("Each reference must be an object with title and url.")
        title = str(item.get("title", "")).strip()
        if not title:
            raise ValueError("Each reference requires a title.")
        references.append(
            {"title": title, "url": _url(item.get("url"), field="Reference URL")}
        )
    return references


def empty_trip_plan() -> dict[str, Any]:
    """Return a blank plan used before the model has called any tool."""
    return {
        "destination": "",
        "destination_coordinates": None,
        "airport": None,
        "currency": "",
        "budget": None,
        "budget_items": [],
        "days": [],
        "notes": [],
        "references": [],
        "status": "draft",
    }


def assemble_trip_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Return a UI-safe, sorted copy of the plan."""
    source = plan if isinstance(plan, dict) else {}
    days: list[dict[str, Any]] = []
    for index, day in enumerate(source.get("days", []) or []):
        if not isinstance(day, dict):
            continue
        number = day.get("day")
        number = int(number) if isinstance(number, (int, float)) and not isinstance(number, bool) else index + 1
        days.append(
            {
                "day": number,
                "title": str(day.get("title", "")).strip() or f"Day {number}",
                "activities": _clean_strings(day.get("activities", [])),
                "notes": _clean_strings(day.get("notes", [])),
                "coordinates": day.get("coordinates") if isinstance(day.get("coordinates"), dict) else None,
                "places": day.get("places") if isinstance(day.get("places"), list) else [],
                "stays": day.get("stays") if isinstance(day.get("stays"), list) else [],
                "budget": _number_or_none(day.get("budget")),
                "budget_items": day.get("budget_items") if isinstance(day.get("budget_items"), list) else [],
            }
        )
    days.sort(key=lambda day: day["day"])
    return {
        "destination": str(source.get("destination", "")).strip(),
        "destination_coordinates": source.get("destination_coordinates") or None,
        "airport": source.get("airport") or None,
        "currency": str(source.get("currency", "")).strip()[:MAX_CURRENCY_CHARS],
        "budget": _number_or_none(source.get("budget")),
        "budget_items": source.get("budget_items") if isinstance(source.get("budget_items"), list) else [],
        "days": days,
        "notes": _clean_strings(source.get("notes", [])),
        "references": source.get("references") if isinstance(source.get("references"), list) else [],
        "status": "displayed",
    }


def _day_numbers(days: list[dict[str, Any]]) -> list[int]:
    return [day["day"] for day in days]


def _find_day(days: list[dict[str, Any]], number: int) -> dict[str, Any] | None:
    return next((day for day in days if day.get("day") == number), None)


def apply_trip_plan_tool(
    name: str, arguments: Any, plan: dict[str, Any] | None
) -> tuple[dict[str, Any], Any]:
    """Apply one trip-plan tool to ``plan``.

    Returns ``(new_plan, model_result)``. ``model_result`` is a compact summary
    for the model (except ``get_trip_plan``, which returns the assembled plan)
    so re-sending the whole plan is unnecessary.
    """
    if not isinstance(arguments, dict):
        raise ValueError(f"{name} requires an object of arguments.")
    current = dict(plan) if isinstance(plan, dict) else empty_trip_plan()
    current.setdefault("days", [])
    current.setdefault("budget_items", [])
    current.setdefault("references", [])
    current.setdefault("notes", [])
    currency = str(current.get("currency", "")).strip()[:MAX_CURRENCY_CHARS]

    if name == "start_trip_plan":
        destination = str(arguments.get("destination", "")).strip()
        if not destination:
            raise ValueError("start_trip_plan requires a destination.")
        current["destination"] = destination
        if "destination_coordinates" in arguments:
            current["destination_coordinates"] = _coordinate(
                arguments.get("destination_coordinates"), field="Destination coordinates"
            )
        if "airport" in arguments:
            current["airport"] = _airport(arguments.get("airport"))
        if "currency" in arguments:
            currency = str(arguments.get("currency", "")).strip()[:MAX_CURRENCY_CHARS]
            current["currency"] = currency
        if "budget" in arguments:
            current["budget"] = _optional_number(arguments.get("budget"), field="budget")
        if "notes" in arguments:
            current["notes"] = _clean_strings(arguments.get("notes"))
        result: Any = {"ok": True, "tool": name, "destination": destination, "days": _day_numbers(current["days"])}

    elif name == "set_trip_day":
        number = arguments.get("day")
        if isinstance(number, bool) or not isinstance(number, (int, float)) or int(number) < 1:
            raise ValueError("set_trip_day requires a positive day number.")
        number = int(number)
        title = str(arguments.get("title", "")).strip()
        activities = _clean_strings(arguments.get("activities", []))
        if not title or not activities:
            raise ValueError("set_trip_day requires a title and activities.")
        day = {
            "day": number,
            "title": title,
            "activities": activities,
            "notes": _clean_strings(arguments.get("notes", [])),
            "coordinates": _coordinate(arguments.get("coordinates"), field=f"Day {number} coordinates"),
            "places": _places(arguments.get("places"), day_number=number),
            "stays": _stays(arguments.get("stays"), day_number=number),
            "budget": _optional_number(arguments.get("budget"), field=f"Day {number} budget"),
            "budget_items": _budget_items(arguments.get("budget_items"), currency=currency),
        }
        current["days"] = [d for d in current["days"] if d.get("day") != number] + [day]
        current["days"].sort(key=lambda d: d.get("day", 0))
        result = {"ok": True, "tool": name, "day": number, "days": _day_numbers(current["days"])}

    elif name == "set_trip_budget":
        if "currency" in arguments:
            currency = str(arguments.get("currency", "")).strip()[:MAX_CURRENCY_CHARS]
            current["currency"] = currency
        budget = _optional_number(arguments.get("budget"), field="budget") if "budget" in arguments else None
        items = _budget_items(arguments.get("items"), currency=currency) if "items" in arguments else None
        number = arguments.get("day")
        if number not in (None, ""):
            if isinstance(number, bool) or not isinstance(number, (int, float)) or int(number) < 1:
                raise ValueError("set_trip_budget day must be a positive integer.")
            number = int(number)
            target = _find_day(current["days"], number)
            if target is None:
                target = {
                    "day": number,
                    "title": f"Day {number}",
                    "activities": [],
                    "notes": [],
                    "coordinates": None,
                    "places": [],
                    "budget": None,
                    "budget_items": [],
                }
                current["days"].append(target)
                current["days"].sort(key=lambda d: d.get("day", 0))
            if budget is not None:
                target["budget"] = budget
            if items is not None:
                target["budget_items"] = items
            result = {"ok": True, "tool": name, "scope": f"day {number}", "budget": target.get("budget")}
        else:
            if budget is not None:
                current["budget"] = budget
            if items is not None:
                current["budget_items"] = items
            result = {"ok": True, "tool": name, "scope": "total", "budget": current.get("budget")}

    elif name == "set_trip_references":
        references = _references(arguments.get("references"))
        current["references"] = references
        result = {"ok": True, "tool": name, "references": len(references)}

    elif name == "remove_trip_day":
        number = arguments.get("day")
        if isinstance(number, bool) or not isinstance(number, (int, float)) or int(number) < 1:
            raise ValueError("remove_trip_day requires a positive day number.")
        number = int(number)
        before = len(current["days"])
        current["days"] = [d for d in current["days"] if d.get("day") != number]
        result = {
            "ok": True,
            "tool": name,
            "removed": number if len(current["days"]) < before else None,
            "days": _day_numbers(current["days"]),
        }

    elif name == "get_trip_plan":
        assembled = assemble_trip_plan(current)
        return current, assembled

    else:
        raise ValueError(f"Unknown trip-plan tool: {name}")

    current["status"] = "displayed"
    return current, result


def format_plan_context(context: dict[str, Any] | None) -> str:
    """Render a compact trip-plan context so the model knows the latest budget.

    The context is attached to the next user turn after a budget edit so the
    change is reflected without a separate notification message.
    """
    if not isinstance(context, dict):
        return ""
    destination = str(context.get("destination", "")).strip()
    currency = str(context.get("currency", "")).strip()
    items = context.get("budget_items") if isinstance(context.get("budget_items"), list) else []
    days = context.get("days") if isinstance(context.get("days"), list) else []
    airport = context.get("airport") if isinstance(context.get("airport"), dict) else None
    total = context.get("budget")
    if not destination and total in (None, "") and not items and not days:
        return ""
    lines = [
        "Current trip-plan state (the user may have edited this; treat it as the "
        "latest confirmed values):"
    ]
    if destination:
        lines.append(f"- Destination: {destination}")
    if airport and str(airport.get("name", "")).strip():
        lines.append(f"- Arrival airport: {str(airport['name']).strip()}")
    if total not in (None, ""):
        lines.append(f"- Total budget: {currency + ' ' if currency else ''}{total}")
    for day in days:
        if isinstance(day, dict) and day.get("budget") not in (None, ""):
            lines.append(
                f"- Day {day.get('day', '?')} budget: {currency + ' ' if currency else ''}{day['budget']}"
            )
    for item in items:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", "")).strip()
        amount = item.get("amount")
        if category and amount not in (None, ""):
            item_currency = str(item.get("currency", "")).strip() or currency
            lines.append(
                f"- Budget item {category}: {item_currency + ' ' if item_currency else ''}{amount}"
            )
    if len(lines) == 1:
        return ""
    lines.append(
        "Use these values for revision requests; do not reintroduce older budget figures."
    )
    return "\n".join(lines)
