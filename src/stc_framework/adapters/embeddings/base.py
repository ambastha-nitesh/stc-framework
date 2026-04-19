"""Embeddings client protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingsClient(Protocol):
    """Produces vector embeddings for text."""

    vector_size: int

    async def aembed(self, text: str) -> list[float]: ...

    async def aembed_batch(self, texts: list[str]) -> list[list[float]]: ...

    async def healthcheck(self) -> bool: ...
