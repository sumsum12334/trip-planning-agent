"""Tests for cooperative streaming cancellation."""

from __future__ import annotations

import threading

from config.settings import Settings
from trip_planning_agent.cancellation import clear, register, request_stop
from trip_planning_agent.tacc_client import TACCClient


def test_registry_sets_and_clears_event():
    event = register("req-1")
    assert not event.is_set()
    assert request_stop("req-1") is True
    assert event.is_set()
    clear("req-1", event)
    assert request_stop("req-1") is False


def test_request_stop_unknown_id_returns_false():
    assert request_stop("does-not-exist") is False


def test_register_without_id_does_not_track():
    event = register(None)
    assert request_stop("") is False
    assert not event.is_set()


def test_stream_returns_immediately_when_cancelled_before_start():
    settings = Settings(**{"QWEN_BASE_URL": "http://127.0.0.1:9/v1", "QWEN_MODEL": "test-model"})
    client = TACCClient(settings)
    event = threading.Event()
    event.set()
    assert list(client.stream("hello", cancel_event=event)) == []
