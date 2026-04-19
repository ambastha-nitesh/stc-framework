"""Thread-safe in-memory vector store with cosine similarity + keyword fallback."""

from __future__ import annotations

import math
from threading import RLock
from typing import Any

import numpy as np

from stc_framework.adapters.vector_store.base import (
    RetrievedChunk,
    VectorRecord,
    VectorStore,
)
from stc_framework.errors import CollectionMissing


class InMemoryVectorStore(VectorStore):
    """Deterministic, dependency-free default vector store."""

    def __init__(self) -> None:
        self._collections: dict[str, list[VectorRecord]] = {}
        self._lock = RLock()

    async def ensure_collection(self, name: str, vector_size: int) -> None:
        with self._lock:
            self._collections.setdefault(name, [])

    async def upsert(self, collection: str, records: list[VectorRecord]) -> None:
        with self._lock:
            bucket = self._collections.setdefault(collection, [])
            existing = {r.id: i for i, r in enumerate(bucket)}
            for rec in records:
                if rec.id in existing:
                    bucket[existing[rec.id]] = rec
                else:
                    bucket.append(rec)

    async def search(
        self,
        collection: str,
        vector: list[float],
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        with self._lock:
            if collection not in self._collections:
                raise CollectionMissing(
                    message=f"Unknown collection {collection!r}",
                    downstream="in_memory_vector_store",
                )
            records = list(self._collections[collection])

        if not records:
            return []

        query_vec = np.asarray(vector, dtype=np.float32)
        q_norm = float(np.linalg.norm(query_vec)) or 1.0

        scored: list[tuple[float, VectorRecord]] = []
        for rec in records:
            if filters and not _matches(rec.metadata, filters):
                continue
            vec = np.asarray(rec.vector, dtype=np.float32)
            denom = (float(np.linalg.norm(vec)) or 1.0) * q_norm
            score = float(np.dot(query_vec, vec) / denom)
            if math.isnan(score):
                score = 0.0
            scored.append((score, rec))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            RetrievedChunk(id=r.id, text=r.text, score=score, metadata=dict(r.metadata)) for score, r in scored[:top_k]
        ]

    async def keyword_search(
        self,
        collection: str,
        query: str,
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        with self._lock:
            if collection not in self._collections:
                raise CollectionMissing(
                    message=f"Unknown collection {collection!r}",
                    downstream="in_memory_vector_store",
                )
            records = [r for r in self._collections[collection] if not filters or _matches(r.metadata, filters)]

        tokens = {t.lower() for t in query.split() if len(t) > 2}
        if not tokens:
            return []

        scored: list[tuple[float, VectorRecord]] = []
        for rec in records:
            text_tokens = {t.lower() for t in rec.text.split() if len(t) > 2}
            if not text_tokens:
                continue
            overlap = len(tokens & text_tokens) / len(tokens)
            if overlap > 0:
                scored.append((overlap, rec))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            RetrievedChunk(id=r.id, text=r.text, score=score, metadata=dict(r.metadata)) for score, r in scored[:top_k]
        ]

    async def healthcheck(self) -> bool:
        return True

    async def list_for_tenant(self, tenant_id: str) -> list[dict[str, object]]:
        with self._lock:
            out: list[dict[str, object]] = []
            for bucket in self._collections.values():
                for rec in bucket:
                    if rec.metadata.get("tenant_id") == tenant_id:
                        out.append(
                            {
                                "id": rec.id,
                                "text": rec.text,
                                "metadata": dict(rec.metadata),
                            }
                        )
            return out

    async def erase_tenant(self, tenant_id: str) -> int:
        """Delete every record whose metadata carries the given tenant id."""
        removed = 0
        with self._lock:
            for name, bucket in self._collections.items():
                kept = [r for r in bucket if r.metadata.get("tenant_id") != tenant_id]
                removed += len(bucket) - len(kept)
                self._collections[name] = kept
        return removed


def _matches(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
    return all(metadata.get(k) == v for k, v in filters.items())
