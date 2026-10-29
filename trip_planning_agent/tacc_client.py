"""Client for the course Qwen OpenAI-compatible model endpoint."""

from __future__ import annotations

from typing import Any, Optional

import httpx

from config.settings import Settings, get_model_config, get_settings


class TACCClient:
    """Keep the existing client name while speaking the Qwen chat protocol."""

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
    ) -> dict[str, Any]:
        """Submit one chat completion, or return a useful local stub."""
        if not self.configured:
            return {
                "ok": False,
                "stub": True,
                "text": "[Qwen stub] Set QWEN_BASE_URL to call the course model.",
                "model": self.model,
                "prompt_chars": len(prompt),
                "system_chars": len(system or ""),
                "extra": extra or {},
            }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 512,
            "temperature": 0.7,
            "chat_template_kwargs": {"enable_thinking": False},
            **(extra or {}),
        }
        headers = {"Content-Type": "application/json"}
        api_key = get_model_config(self.settings)["api_key"]
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        with httpx.Client(timeout=300.0) as client:
            response = client.post(
                self.base_url.rstrip("/") + "/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        text = data["choices"][0]["message"]["content"]
        return {"ok": True, "stub": False, "text": text, "raw": data}
