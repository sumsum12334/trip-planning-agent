"""Tests for Langfuse tracking guards (no network, fake client)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from trip_planning_agent import observability


class FakeObservation:
    def __init__(self) -> None:
        self.updates: list[dict] = []
        self.end_count = 0

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)

    def end(self) -> None:
        self.end_count += 1


class FakeLangfuseClient:
    def __init__(self) -> None:
        self.observations: list[FakeObservation] = []
        self.flush_count = 0

    def start_observation(self, **kwargs) -> FakeObservation:
        observation = FakeObservation()
        self.observations.append(observation)
        return observation

    def flush(self) -> None:
        self.flush_count += 1


def _langfuse_settings() -> SimpleNamespace:
    return SimpleNamespace(
        langfuse_enabled=True,
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        langfuse_host="http://localhost",
    )


@pytest.fixture()
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeLangfuseClient:
    client = FakeLangfuseClient()
    # The eval-branch refactor renamed the accessor to _langfuse_client and
    # added the parallel _langsmith_client; pin both so the tests exercise
    # only the Langfuse path with the fake client.
    monkeypatch.setattr(
        observability, "_langfuse_client", lambda settings=None: client
    )
    monkeypatch.setattr(
        observability, "_langsmith_client", lambda settings=None: None
    )
    return client


def _generation_kwargs() -> dict:
    return {
        "name": "tacc.chat_completion_stream",
        "model": "test-model",
        "prompt": "hello",
        "system": "sys",
        "input": [{"role": "user", "content": "hello"}],
        "session_id": "s1",
        "metadata": {},
        "trace_context": None,
    }


def test_model_generation_closes_unended_observation(fake_client) -> None:
    # Simulate the 400-without-tools retry: the caller exits the context
    # without calling finish_generation, which previously leaked an open
    # generation in Langfuse.
    with observability.model_generation(**_generation_kwargs()) as generation:
        assert generation is fake_client.observations[0]
    assert fake_client.observations[0].end_count == 1


def test_model_generation_does_not_double_end(fake_client) -> None:
    with observability.model_generation(**_generation_kwargs()) as generation:
        observability.finish_generation(generation, output="answer")
    observation = fake_client.observations[0]
    assert observation.end_count == 1
    assert observation.updates[-1]["output"] == "answer"


def test_finish_generation_records_error_level(fake_client) -> None:
    with observability.model_generation(**_generation_kwargs()) as generation:
        observability.finish_generation(
            generation, output={"error": "boom"}, error=ValueError("boom")
        )
    observation = fake_client.observations[0]
    assert observation.updates[-1]["level"] == "ERROR"


def test_finish_generation_ignores_none(fake_client) -> None:
    observability.finish_generation(None, output="x")
    assert fake_client.observations == []
