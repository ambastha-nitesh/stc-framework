"""Vector store protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class VectorRecord:
    id: str
    vector: list[float]
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievedChunk:
    id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class VectorStore(Protocol):
    """Async vector store."""

    async def ensure_collection(self, name: str, vector_size: int) -> None: ...

    async def upsert(self, collection: str, records: list[VectorRecord]) -> None: ...

    async def search(
        self,
        collection: str,
        vector: list[float],
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]: ...

    async def keyword_search(
        self,
        collection: str,
        query: str,
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """Fallback keyword search used when embedding-based search is unavailable."""
        ...

    async def list_for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        """Optional DSAR support: list every document stored for a tenant."""
        return []

    async def erase_tenant(self, tenant_id: str) -> int:
        """Optional right-to-erasure support; returns count removed."""
        return 0

    async def healthcheck(self) -> bool: ...
