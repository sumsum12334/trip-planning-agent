"""Unit tests for the TACC model client (protocol layer, no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from trip_planning_agent.tacc_client import TACCClient


def _fake_settings(**overrides):
    base = {
        "qwen_base_url": "http://fake-endpoint/v1",
        "qwen_model": "test-model",
        "qwen_api_key": "test-key",
        "langfuse_enabled": False,
        "langfuse_public_key": "",
        "langfuse_secret_key": "",
        "langfuse_host": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeResponse:
    """Minimal SSE response for the streaming client."""

    def __init__(self, sse_lines=None, status_code=200, body="", json_data=None):
        self._lines = sse_lines or []
        self.status_code = status_code
        self._body = body
        self._json_data = json_data

    @property
    def is_success(self):
        return self.status_code < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=None
            )

    def iter_lines(self):
        return iter(self._lines)

    def read(self):
        return self._body.encode("utf-8")

    @property
    def text(self):
        return self._body

    def json(self):
        return self._json_data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeHttpClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.request_bodies = []

    def stream(self, method, url, headers=None, json=None):
        self.request_bodies.append(json)
        return self._responses.pop(0)

    def post(self, url, headers=None, json=None):
        self.request_bodies.append(json)
        return self._responses.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _sse(*payloads):
    lines = [f"data: {json.dumps(payload)}" for payload in payloads if payload is not None]
    lines.append("data: [DONE]")
    return FakeResponse(lines)


def test_complete_returns_stub_when_not_configured():
    client = TACCClient(_fake_settings(qwen_base_url=""))
    events = []
    result = client.complete("hello", on_event=events.append)
    assert result["stub"] is True
    assert result["ok"] is False
    assert "[Model stub]" in result["text"]
    assert any(event["label"] == "Using local model stub" for event in events)


def test_complete_posts_configured_payload(monkeypatch):
    ok_response = FakeResponse(
        json_data={"choices": [{"message": {"content": "the answer"}}]}
    )
    fake = FakeHttpClient([ok_response])
    monkeypatch.setattr(
        "trip_planning_agent.tacc_client.httpx.Client", lambda timeout=None: fake
    )
    client = TACCClient(_fake_settings())
    result = client.complete("hello", system="sys")
    assert result["ok"] is True
    assert result["text"] == "the answer"
    body = fake.request_bodies[0]
    assert body["model"] == "test-model"
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]


def test_complete_uses_legacy_sampling_defaults(monkeypatch):
    ok_response = FakeResponse(
        json_data={"choices": [{"message": {"content": "ok"}}]}
    )
    fake = FakeHttpClient([ok_response])
    monkeypatch.setattr(
        "trip_planning_agent.tacc_client.httpx.Client", lambda timeout=None: fake
    )
    TACCClient(_fake_settings()).complete("hello")
    body = fake.request_bodies[0]
    assert body["max_tokens"] == 16384
    assert body["temperature"] == 1.0
    assert body["top_p"] == 0.95
    assert body["reasoning_budget"] == 16384
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


def test_stream_sampling_defaults_enable_thinking(monkeypatch):
    fake = FakeHttpClient([_sse({"choices": [{"delta": {"content": "hi"}}]}, None)])
    monkeypatch.setattr(
        "trip_planning_agent.tacc_client.httpx.Client", lambda timeout=None: fake
    )
    list(TACCClient(_fake_settings()).stream("hello"))
    body = fake.request_bodies[0]
    assert body["stream"] is True
    assert body["max_tokens"] == 16384
    assert body["temperature"] == 1.0
    assert body["top_p"] == 0.95
    assert body["reasoning_budget"] == 16384
    assert body["chat_template_kwargs"] == {"enable_thinking": True}


def test_sampling_settings_override_payload(monkeypatch):
    fake = FakeHttpClient([_sse({"choices": [{"delta": {"content": "hi"}}]}, None)])
    monkeypatch.setattr(
        "trip_planning_agent.tacc_client.httpx.Client", lambda timeout=None: fake
    )
    settings = _fake_settings(
        model_max_tokens=512,
        model_temperature=0.3,
        model_top_p=0.9,
        model_reasoning_budget=0,
        model_enable_thinking=False,
    )
    list(TACCClient(settings).stream("hello"))
    body = fake.request_bodies[0]
    assert body["max_tokens"] == 512
    assert body["temperature"] == 0.3
    assert body["top_p"] == 0.9
    # A reasoning budget of 0 drops the field instead of sending a disabled value.
    assert "reasoning_budget" not in body
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


def test_chunk_text_handles_providers_shapes():
    assert TACCClient._chunk_text("plain") == "plain"
    assert TACCClient._chunk_text([{"text": "a"}, {"text": "b"}]) == "ab"
    assert TACCClient._chunk_text([{"text": "a"}, "raw"]) == "araw"
    assert TACCClient._chunk_text(7) == "7"


def test_tool_call_summary_tolerates_bad_arguments():
    summary = TACCClient._tool_call_summary(
        {
            0: {"name": "good", "arguments": '{"day": 1}'},
            1: {"name": "bad", "arguments": "{not json"},
            2: {"name": "empty", "arguments": None},
        }
    )
    assert summary[0] == {"name": "good", "arguments": {"day": 1}}
    assert summary[1]["name"] == "bad" and summary[1]["arguments"] == "{not json"
    assert summary[2] == {"name": "empty", "arguments": {}}  # empty -> {} fallback


def test_missing_tool_support_detection():
    response = SimpleNamespace(
        is_success=False,
        status_code=400,
        text="enable-auto-tool-choice is not enabled",
    )
    assert TACCClient._missing_tool_support(response) is True
    assert TACCClient._missing_tool_support(SimpleNamespace(text="other error")) is False


def test_stream_runs_one_tool_round(monkeypatch):
    first = _sse(
        {"choices": [{"delta": {"reasoning_content": "thinking"}}]},
        {"choices": [{"delta": {"content": "Let me check"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "function": {
                                    "name": "search_stays",
                                    "arguments": '{"destination": "Tokyo"}',
                                },
                            }
                        ]
                    }
                }
            ]
        },
        None,
    )
    second = _sse({"choices": [{"delta": {"content": "final answer"}}]}, None)
    fake = FakeHttpClient([first, second])
    monkeypatch.setattr(
        "trip_planning_agent.tacc_client.httpx.Client", lambda timeout=None: fake
    )

    events = []
    executed = []

    def executor(name, arguments):
        executed.append((name, arguments))
        return {"mode": "stub", "stays": ["A"]}

    client = TACCClient(_fake_settings())
    deltas = list(
        client.stream(
            "find stays",
            system="sys",
            on_event=events.append,
            tool_executor=executor,
            session_id="s1",
        )
    )

    kinds = [delta["kind"] for delta in deltas]
    assert kinds == ["reasoning", "content", "content"]
    assert deltas[-1]["text"] == "final answer"
    assert executed == [("search_stays", {"destination": "Tokyo"})]
    labels = [event["label"] for event in events]
    assert "Calling search_stays" in labels
    assert "search_stays result received" in labels

    # The follow-up request carries the assistant tool call and the tool result.
    followup = fake.request_bodies[1]["messages"]
    assert followup[-2]["role"] == "assistant"
    assert followup[-2]["tool_calls"][0]["function"]["name"] == "search_stays"
    assert followup[-1]["role"] == "tool"
    assert json.loads(followup[-1]["content"]) == {"mode": "stub", "stays": ["A"]}


def test_stream_stops_when_cancelled(monkeypatch):
    cancelled = __import__("threading").Event()
    cancelled.set()
    fake = FakeHttpClient([])
    monkeypatch.setattr(
        "trip_planning_agent.tacc_client.httpx.Client", lambda timeout=None: fake
    )
    client = TACCClient(_fake_settings())
    deltas = list(client.stream("hello", cancel_event=cancelled))
    assert deltas == []
    assert fake.request_bodies == []


def test_stream_without_executor_raises(monkeypatch):
    first = _sse(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "function": {"name": "x", "arguments": "{}"},
                            }
                        ]
                    }
                }
            ]
        },
        None,
    )
    monkeypatch.setattr(
        "trip_planning_agent.tacc_client.httpx.Client", lambda timeout=None: FakeHttpClient([first])
    )
    client = TACCClient(_fake_settings())
    with pytest.raises(ValueError, match="no executor"):
        list(client.stream("hello", tool_executor=None))


def test_stream_retry_without_tools_ends_generation(monkeypatch):
    """The 400-without-tools retry must close the first Langfuse generation."""
    from trip_planning_agent import observability

    class FakeObservation:
        def __init__(self):
            self.end_count = 0

        def update(self, **kwargs):
            pass

        def end(self):
            self.end_count += 1

    class FakeLangfuse:
        def __init__(self):
            self.observations = []

        def start_observation(self, **kwargs):
            observation = FakeObservation()
            self.observations.append(observation)
            return observation

        def flush(self):
            pass

    langfuse = FakeLangfuse()
    monkeypatch.setattr(observability, "_client", lambda settings=None: langfuse)

    no_tools = FakeResponse(status_code=400, body="tool-call-parser is not enabled")
    ok = _sse({"choices": [{"delta": {"content": "final answer"}}]}, None)
    fake = FakeHttpClient([no_tools, ok])
    monkeypatch.setattr(
        "trip_planning_agent.tacc_client.httpx.Client", lambda timeout=None: fake
    )

    settings = _fake_settings(
        langfuse_enabled=True,
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        langfuse_host="http://localhost",
    )
    tools = [
        {
            "type": "function",
            "function": {"name": "search_stays", "parameters": {"type": "object"}},
        }
    ]
    deltas = list(TACCClient(settings).stream("hello", system="sys", tools=tools))

    assert deltas[-1]["text"] == "final answer"
    assert len(fake.request_bodies) == 2
    assert fake.request_bodies[0].get("tools")
    assert "tools" not in fake.request_bodies[1]
    # Both generations (the rejected request and the retry) were closed.
    assert len(langfuse.observations) == 2
    assert all(obs.end_count == 1 for obs in langfuse.observations)
