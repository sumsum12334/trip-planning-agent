"""Cooperative cancellation for in-flight streaming chat turns.

The chat stream registers an event under the client-supplied ``request_id``.
A stop request sets that event, and the streaming loop / model client check it
between deltas so a turn can end before the model finishes.
"""

from __future__ import annotations

import threading

_CANCEL_EVENTS: dict[str, threading.Event] = {}
_CANCEL_LOCK = threading.Lock()


def register(request_id: str | None) -> threading.Event:
    """Return the cancel event for a turn, registering it when an id is given."""
    event = threading.Event()
    if request_id:
        with _CANCEL_LOCK:
            _CANCEL_EVENTS[request_id] = event
    return event


def clear(request_id: str | None, event: threading.Event) -> None:
    """Remove a turn's cancel event once the stream has finished."""
    if not request_id:
        return
    with _CANCEL_LOCK:
        if _CANCEL_EVENTS.get(request_id) is event:
            _CANCEL_EVENTS.pop(request_id, None)


def request_stop(request_id: str) -> bool:
    """Set the cancel event for a turn. Returns True when a turn was found."""
    with _CANCEL_LOCK:
        event = _CANCEL_EVENTS.get(request_id)
    if event is None:
        return False
    event.set()
    return True
