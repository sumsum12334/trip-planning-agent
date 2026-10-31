"""Client for the configured NVIDIA-compatible OpenAI chat endpoint."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any, Optional

import httpx

from config.settings import Settings, get_model_config, get_settings


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
        with httpx.Client(timeout=300.0) as client:
            response = client.post(
                self.base_url.rstrip("/") + "/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        if on_event:
            on_event({"type": "model", "label": "Model response received", "status": "completed"})
        text = data["choices"][0]["message"]["content"]
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
    ) -> Iterator[dict[str, str]]:
        """Yield reasoning and answer deltas from the OpenAI-compatible SSE endpoint."""
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

        with httpx.Client(timeout=300.0) as client:
            while True:
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
                with client.stream(
                    "POST",
                    self.base_url.rstrip("/") + "/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
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
                            yield {"kind": "content", "text": self._chunk_text(content)}
                        for call in delta.get("tool_calls") or []:
                            index = call.get("index", 0)
                            current = tool_calls.setdefault(
                                index, {"id": "", "name": "", "arguments": ""}
                            )
                            current["id"] += call.get("id") or ""
                            function = call.get("function") or {}
                            current["name"] += function.get("name") or ""
                            current["arguments"] += function.get("arguments") or ""
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
