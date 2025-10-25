"""Client for interacting with the Ollama inference service."""
from __future__ import annotations

from typing import Any, Dict

import httpx


class OllamaClient:
    """HTTP client for Ollama chat completions."""

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=60.0)

    async def generate(self, prompt: str, context: list[dict[str, Any]] | None = None) -> str:
        """Call the Ollama chat endpoint and return the generated text."""

        payload: Dict[str, Any] = {"model": self._model, "prompt": prompt}
        if context:
            payload["context"] = context
        response = await self._client.post("/api/generate", json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("response", "")

    async def close(self) -> None:
        """Close the underlying HTTP client."""

        await self._client.aclose()
