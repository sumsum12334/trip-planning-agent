"""Shared schema and validation for the `display_trip_plan` UI tool.

The chat endpoints expose this tool so the model can render a structured
itinerary. Keeping the JSON schema and the payload validation in one module
keeps the streaming and continuation endpoints consistent.
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

TRIP_PLAN_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "display_trip_plan",
        "description": (
            "Display a structured trip itinerary after enough planning details are known. "
            "Include approximate coordinates only for well-known places so the UI can map "
            "the route, and add reference links (with title and http(s) url) for sources "
            "that the plan relies on."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "destination": {"type": "string"},
                "destination_coordinates": _COORDINATE_SCHEMA,
                "days": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {"type": "integer", "minimum": 1},
                            "title": {"type": "string"},
                            "activities": {"type": "array", "items": {"type": "string"}},
                            "notes": {"type": "array", "items": {"type": "string"}},
                            "coordinates": _COORDINATE_SCHEMA,
                            "places": {"type": "array", "items": _PLACE_SCHEMA},
                        },
                        "required": ["day", "title", "activities"],
                    },
                    "minItems": 1,
                    "maxItems": MAX_DAYS,
                },
                "budget": {"type": "number", "description": "Estimated total budget."},
                "currency": {"type": "string", "description": "Currency code or symbol for the budget."},
                "budget_items": {
                    "type": "array",
                    "description": "Optional per-category budget breakdown; amounts should sum to the total.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string", "description": "Category such as accommodation, transport, food, or activities."},
                            "amount": {"type": "number", "minimum": 0},
                        },
                        "required": ["category", "amount"],
                    },
                    "maxItems": MAX_BUDGET_ITEMS,
                },
                "notes": {"type": "array", "items": {"type": "string"}},
                "references": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                        },
                        "required": ["title", "url"],
                    },
                },
            },
            "required": ["destination", "days"],
        },
    },
}


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


def normalize_trip_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a `display_trip_plan` tool payload.

    Raises ``ValueError`` with a user-safe message when the payload is invalid.
    """
    if not isinstance(arguments, dict):
        raise ValueError("display_trip_plan requires an object of arguments.")
    destination = str(arguments.get("destination", "")).strip()
    days = arguments.get("days", [])
    if not destination or not isinstance(days, list) or not 1 <= len(days) <= MAX_DAYS:
        raise ValueError(
            "display_trip_plan requires a destination and one to fourteen days."
        )

    normalized_days: list[dict[str, Any]] = []
    for item in days:
        if not isinstance(item, dict):
            raise ValueError("Each trip day must be an object.")
        activities = _clean_strings(item.get("activities", []))
        title = str(item.get("title", "")).strip()
        if not title or not activities:
            raise ValueError("Each trip day requires a title and activities.")
        day_number = int(item.get("day", len(normalized_days) + 1))
        normalized_days.append(
            {
                "day": day_number,
                "title": title,
                "activities": activities,
                "notes": _clean_strings(item.get("notes", [])),
                "coordinates": _coordinate(
                    item.get("coordinates"), field=f"Day {day_number} coordinates"
                ),
                "places": _places(item.get("places"), day_number=day_number),
            }
        )

    currency = str(arguments.get("currency", "")).strip()[:MAX_CURRENCY_CHARS]
    budget_items = _budget_items(arguments.get("budget_items"), currency=currency)
    budget = arguments.get("budget")
    if budget in (None, ""):
        budget = round(sum(item["amount"] for item in budget_items), 2) if budget_items else None
    elif isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget < 0:
        raise ValueError("display_trip_plan budget must be a non-negative number.")
    else:
        budget = float(budget)

    return {
        "destination": destination,
        "destination_coordinates": _coordinate(
            arguments.get("destination_coordinates"),
            field="Destination coordinates",
        ),
        "days": normalized_days,
        "budget": budget,
        "currency": currency,
        "budget_items": budget_items,
        "notes": _clean_strings(arguments.get("notes", [])),
        "references": _references(arguments.get("references")),
        "status": "displayed",
    }


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
    total = context.get("budget")
    if not destination and total in (None, "") and not items:
        return ""
    lines = [
        "Current trip-plan state (the user may have edited this; treat it as the "
        "latest confirmed values):"
    ]
    if destination:
        lines.append(f"- Destination: {destination}")
    if total not in (None, ""):
        lines.append(f"- Total budget: {currency + ' ' if currency else ''}{total}")
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
