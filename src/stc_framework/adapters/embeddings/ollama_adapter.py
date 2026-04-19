"""Ollama embeddings via its HTTP API (async, httpx)."""

from __future__ import annotations

import httpx

from stc_framework.adapters.embeddings.base import EmbeddingsClient
from stc_framework.errors import EmbeddingError


class OllamaEmbeddings(EmbeddingsClient):
    def __init__(
        self,
        *,
        endpoint: str = "http://localhost:11434",
        model: str = "bge-large-en-v1.5",
        vector_size: int = 1024,
        timeout: float = 10.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.vector_size = vector_size
        self._client = httpx.AsyncClient(timeout=timeout, base_url=self.endpoint)

    async def aembed(self, text: str) -> list[float]:
        try:
            response = await self._client.post("/api/embeddings", json={"model": self.model, "prompt": text})
            response.raise_for_status()
            payload = response.json()
            return list(payload["embedding"])
        except httpx.HTTPError as exc:
            raise EmbeddingError(
                message=f"Ollama embeddings request failed: {exc}",
                downstream="ollama",
            ) from exc

    async def aembed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.aembed(t) for t in texts]

    async def healthcheck(self) -> bool:
        try:
            response = await self._client.get("/")
            return response.status_code < 500
        except httpx.HTTPError:  # pragma: no cover
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
