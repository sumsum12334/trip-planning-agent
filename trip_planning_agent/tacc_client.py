"""Client for the configured NVIDIA-compatible OpenAI chat endpoint."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from typing import Any, Optional

import httpx

from config.settings import Settings, get_model_config, get_settings
from trip_planning_agent.observability import (
    finish_generation,
    model_generation,
    update_generation,
)


class TACCClient:
    """Keep the existing client name while speaking the chat completions protocol."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    @property
    def base_url(self) -> str:
        return get_model_config(self.settings)["base_url"]

    @property
    def model(self) -> str:
        return get_model_config(self.settings)["model"]

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def complete(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        session_id: str | None = None,
        trace_context: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Submit one chat completion, or return a useful local stub."""
        if not self.configured:
            if on_event:
                on_event(
                    {
                        "type": "model",
                        "label": "Using local model stub",
                        "status": "completed",
                    }
                )
            return {
                "ok": False,
                "stub": True,
                "text": "[Model stub] Set QWEN_BASE_URL to call the configured model.",
                "model": self.model,
                "prompt_chars": len(prompt),
                "system_chars": len(system or ""),
                "extra": extra or {},
            }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        if on_event:
            on_event({"type": "model", "label": "Preparing model request", "status": "completed"})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 16384,
            "temperature": 1.0,
            "top_p": 0.95,
            "reasoning_budget": 16384,
            "chat_template_kwargs": {"enable_thinking": False},
            **(extra or {}),
        }
        headers = {"Content-Type": "application/json"}
        api_key = get_model_config(self.settings)["api_key"]
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if on_event:
            on_event(
                {
                    "type": "model",
                    "label": "Model is thinking",
                    "detail": self.model,
                    "status": "running",
                }
            )
        with model_generation(
            name="tacc.chat_completion",
            model=self.model,
            prompt=prompt,
            system=system,
            input=messages,
            session_id=session_id,
            metadata={"stream": False},
            trace_context=trace_context,
            settings=self.settings,
        ) as generation:
            try:
                with httpx.Client(timeout=300.0) as client:
                    response = client.post(
                        self.base_url.rstrip("/") + "/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                text = data["choices"][0]["message"]["content"]
                finish_generation(generation, output=text)
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                finish_generation(
                    generation,
                    output={"error": str(error)},
                    error=error,
                )
                raise
        if on_event:
            on_event({"type": "model", "label": "Model response received", "status": "completed"})
        return {"ok": True, "stub": False, "text": text, "raw": data}

    def stream(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
        initial_messages: list[dict[str, Any]] | None = None,
        on_pause: Callable[[list[dict[str, Any]], dict[str, Any]], None] | None = None,
        session_id: str | None = None,
        trace_context: dict[str, str] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[dict[str, str]]:
        """Yield reasoning and answer deltas from the OpenAI-compatible SSE endpoint.

        When ``cancel_event`` is set the generator stops at the next delta and
        returns, closing the upstream request.
        """
        if not self.configured:
            if on_event:
                on_event({"type": "model", "label": "Using local model stub", "status": "completed"})
            yield {"kind": "content", "text": "[Model stub] Set QWEN_BASE_URL to call the configured model."}
            return

        messages: list[dict[str, Any]] = list(initial_messages or [])
        if not messages:
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
        headers = {"Content-Type": "application/json"}
        api_key = get_model_config(self.settings)["api_key"]
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if on_event:
            on_event(
                {
                    "type": "model",
                    "label": "Preparing model request",
                    "status": "completed",
                }
            )
            on_event({"type": "model", "label": "Model is thinking", "detail": self.model, "status": "running"})

        cancelled = False
        with httpx.Client(timeout=300.0) as client:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    return
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 16384,
                    "temperature": 1.0,
                    "top_p": 0.95,
                    "reasoning_budget": 16384,
                    "stream": True,
                    "chat_template_kwargs": {"enable_thinking": True},
                }
                if tools:
                    payload["tools"] = tools
                tool_calls: dict[int, dict[str, Any]] = {}
                streamed_text: list[str] = []
                with model_generation(
                    name="tacc.chat_completion_stream",
                    model=self.model,
                    prompt=prompt,
                    system=system,
                    input=messages,
                    session_id=session_id,
                    metadata={"stream": True, "message_count": len(messages)},
                    trace_context=trace_context,
                    settings=self.settings,
                ) as generation:
                    try:
                        with client.stream(
                            "POST",
                            self.base_url.rstrip("/") + "/chat/completions",
                            headers=headers,
                            json=payload,
                        ) as response:
                            response.raise_for_status()
                            for line in response.iter_lines():
                                if cancel_event is not None and cancel_event.is_set():
                                    cancelled = True
                                    break
                                if not line.startswith("data:"):
                                    continue
                                data = line[5:].strip()
                                if data == "[DONE]":
                                    break
                                chunk = json.loads(data)
                                choices = chunk.get("choices", [])
                                if not choices:
                                    continue
                                choice = choices[0]
                                delta = choice.get("delta") or {}
                                message = choice.get("message") or {}
                                reasoning = (
                                    delta.get("reasoning_content")
                                    or delta.get("reasoning")
                                    or message.get("reasoning_content")
                                    or message.get("reasoning")
                                    or choice.get("reasoning_content")
                                    or choice.get("reasoning")
                                )
                                if reasoning:
                                    yield {"kind": "reasoning", "text": self._chunk_text(reasoning)}
                                content = (
                                    delta.get("content")
                                    or delta.get("text")
                                    or message.get("content")
                                    or choice.get("text")
                                    or choice.get("content")
                                )
                                if content:
                                    text = self._chunk_text(content)
                                    streamed_text.append(text)
                                    update_generation(
                                        generation,
                                        output="".join(streamed_text),
                                    )
                                    yield {"kind": "content", "text": text}
                                for call in delta.get("tool_calls") or []:
                                    index = call.get("index", 0)
                                    current = tool_calls.setdefault(
                                        index, {"id": "", "name": "", "arguments": ""}
                                    )
                                    current["id"] += call.get("id") or ""
                                    function = call.get("function") or {}
                                    current["name"] += function.get("name") or ""
                                    current["arguments"] += function.get("arguments") or ""
                        output_text = "".join(streamed_text)
                        if cancelled:
                            generation_output: Any = {
                                "status": "stopped",
                                "partial": output_text,
                            }
                        elif output_text:
                            generation_output = output_text
                        elif tool_calls:
                            generation_output = {
                                "tool_calls": self._tool_call_summary(tool_calls)
                            }
                        else:
                            generation_output = {"text": ""}
                        finish_generation(generation, output=generation_output)
                    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                        finish_generation(
                            generation,
                            output="".join(streamed_text) or {"error": str(error)},
                            error=error,
                        )
                        raise
                if cancelled:
                    return
                if not tool_calls:
                    break
                if not tool_executor:
                    raise ValueError("The model requested a tool, but no executor is configured.")
                assistant_calls = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call["arguments"]},
                    }
                    for call in tool_calls.values()
                ]
                messages.append({"role": "assistant", "tool_calls": assistant_calls})
                for call in assistant_calls:
                    arguments = json.loads(call["function"]["arguments"] or "{}")
                    if on_event:
                        on_event(
                            {
                                "type": "tool",
                                "label": f"Calling {call['function']['name']}",
                                "status": "running",
                                "data": {
                                    "tool": call["function"]["name"],
                                    "arguments": arguments,
                                },
                            }
                        )
                    result = tool_executor(call["function"]["name"], arguments)
                    if on_event:
                        on_event(
                            {
                                "type": "tool",
                                "label": f"{call['function']['name']} result received",
                                "detail": (
                                    f"{len(result)} match(es)"
                                    if isinstance(result, list)
                                    else None
                                ),
                                "status": "completed",
                                "data": {
                                    "tool": call["function"]["name"],
                                    "result": result,
                                },
                            }
                        )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(result),
                        }
                    )
                    if (
                        call["function"]["name"] == "ask_user_question"
                        and isinstance(result, dict)
                        and result.get("status") == "awaiting_user"
                    ):
                        if on_pause:
                            on_pause(messages, result)
                        if on_event:
                            on_event(
                                {
                                    "type": "agent",
                                    "label": "Waiting for your answer",
                                    "detail": result["question"],
                                    "status": "running",
                                }
                            )
                        return
        if on_event:
            on_event({"type": "model", "label": "Model response received", "status": "completed"})

    @staticmethod
    def _tool_call_summary(tool_calls: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        """Return a trace-safe summary of tool calls without private reasoning."""
        summary: list[dict[str, Any]] = []
        for call in tool_calls.values():
            arguments: Any = call.get("arguments") or ""
            try:
                arguments = json.loads(arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                pass
            summary.append(
                {
                    "name": call.get("name") or "",
                    "arguments": arguments,
                }
            )
        return summary

    @staticmethod
    def _chunk_text(value: Any) -> str:
        """Normalize provider text parts into a displayable string."""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in value
            )
        return str(value)
