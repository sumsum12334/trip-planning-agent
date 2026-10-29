"""
Thin stub for the course TACC model-serving endpoint.

Call shape (conceptual — no real secrets here):
  client → POST TACC_MODEL_ENDPOINT  (auth: TACC_API_KEY)
        → request enters a queue
        → a model worker picks it up and returns completion text / JSON

The web UI is NOT hosted on TACC; only the backend uses this client.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from config.settings import Settings, get_settings


class TACCClient:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    @property
    def configured(self) -> bool:
        return bool(self.settings.tacc_model_endpoint)

    def complete(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Submit one LLM request.

        Real course wiring: HTTP request → TACC queue → model worker → response.
        This stub returns a placeholder when endpoint/key are empty so local
        agent stubs can run without credentials.
        """
        if not self.configured:
            return {
                "ok": False,
                "stub": True,
                "text": "[TACC stub] Set TACC_MODEL_ENDPOINT / TACC_API_KEY to call the queue.",
                "model": self.settings.tacc_model or None,
                "prompt_chars": len(prompt),
                "system_chars": len(system or ""),
                "extra": extra or {},
            }

        headers = {"Authorization": f"Bearer {self.settings.tacc_api_key}"}
        payload: dict[str, Any] = {
            "model": self.settings.tacc_model or None,
            "prompt": prompt,
            "system": system,
            **(extra or {}),
        }
        # Placeholder path — replace with the course's real request schema.
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                self.settings.tacc_model_endpoint,
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return {"ok": True, "stub": False, "raw": data}
