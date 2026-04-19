"""Qdrant-backed vector store adapter (optional extra)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from stc_framework.adapters.vector_store.base import (
    RetrievedChunk,
    VectorRecord,
    VectorStore,
)
from stc_framework.errors import CollectionMissing, VectorStoreUnavailable


class QdrantAdapter(VectorStore):
    """Thin async wrapper around :class:`qdrant_client.QdrantClient`.

    The underlying client is synchronous; we run calls in the default
    asyncio executor to avoid blocking the loop.
    """

    def __init__(self, host: str = "http://localhost:6333") -> None:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http.models import Distance, VectorParams
        except ImportError as exc:  # pragma: no cover - optional
            raise ImportError("qdrant-client is not installed; `pip install stc-framework[qdrant]`") from exc
        self._client = QdrantClient(url=host)
        self._VectorParams = VectorParams
        self._Distance = Distance

    async def ensure_collection(self, name: str, vector_size: int) -> None:
        def _do() -> None:
            existing = {c.name for c in self._client.get_collections().collections}
            if name not in existing:
                self._client.create_collection(
                    collection_name=name,
                    vectors_config=self._VectorParams(size=vector_size, distance=self._Distance.COSINE),
                )

        await asyncio.to_thread(_do)

    async def upsert(self, collection: str, records: list[VectorRecord]) -> None:
        from qdrant_client.http.models import PointStruct

        points = [
            PointStruct(
                id=r.id or str(uuid.uuid4()),
                vector=r.vector,
                payload={"text": r.text, **r.metadata},
            )
            for r in records
        ]
        try:
            await asyncio.to_thread(self._client.upsert, collection_name=collection, points=points)
        except Exception as exc:  # pragma: no cover
            raise VectorStoreUnavailable(message=str(exc), downstream="qdrant") from exc

    async def search(
        self,
        collection: str,
        vector: list[float],
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        def _do() -> list[Any]:
            return self._client.search(
                collection_name=collection,
                query_vector=vector,
                limit=top_k,
            )

        try:
            results = await asyncio.to_thread(_do)
        except Exception as exc:  # pragma: no cover
            if "not found" in str(exc).lower():
                raise CollectionMissing(message=str(exc), downstream="qdrant") from exc
            raise VectorStoreUnavailable(message=str(exc), downstream="qdrant") from exc

        return [
            RetrievedChunk(
                id=str(r.id),
                text=(r.payload or {}).get("text", ""),
                score=float(r.score),
                metadata={k: v for k, v in (r.payload or {}).items() if k != "text"},
            )
            for r in results
        ]

    async def keyword_search(self, collection: str, query: str, *, top_k: int = 5) -> list[RetrievedChunk]:
        # Qdrant doesn't have a first-class keyword index; fall back to scroll + filter.
        try:
            from qdrant_client.http.models import (
                FieldCondition,
                Filter,
                MatchText,
            )
        except ImportError:  # pragma: no cover
            return []

        def _do() -> list[Any]:
            points, _ = self._client.scroll(
                collection_name=collection,
                scroll_filter=Filter(must=[FieldCondition(key="text", match=MatchText(text=query))]),
                limit=top_k,
            )
            return points

        try:
            points = await asyncio.to_thread(_do)
        except Exception:
            return []

        return [
            RetrievedChunk(
                id=str(p.id),
                text=(p.payload or {}).get("text", ""),
                score=0.5,
                metadata={k: v for k, v in (p.payload or {}).items() if k != "text"},
            )
            for p in points
        ]

    async def healthcheck(self) -> bool:
        try:
            await asyncio.to_thread(self._client.get_collections)
            return True
        except Exception:  # pragma: no cover
            return False
