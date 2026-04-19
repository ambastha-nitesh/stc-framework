"""Idempotency cache for ``aquery``.

At-least-once delivery is the norm for API clients, retrying proxies, and
message queues. Without an idempotency key, the same logical request can
be executed twice — double-charged, double-audited, double-counted.

The cache stores completed :class:`QueryResult` objects keyed by
``(tenant_id, idempotency_key)`` and returns the cached result on repeat.
Entries expire after a configurable TTL so the cache cannot grow
unbounded.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any


@dataclass
class _Entry:
    result: Any
    expires_at: datetime


class IdempotencyCache:
    """LRU + TTL cache for deduplicating queries."""

    def __init__(
        self,
        *,
        max_entries: int = 10_000,
        ttl_seconds: int = 24 * 60 * 60,
    ) -> None:
        self._max = max_entries
        self._ttl = timedelta(seconds=ttl_seconds)
        self._data: OrderedDict[tuple[str, str], _Entry] = OrderedDict()
        self._lock = RLock()

    def _key(self, tenant_id: str | None, idempotency_key: str) -> tuple[str, str]:
        return (tenant_id or "__global__", idempotency_key)

    def get(self, tenant_id: str | None, idempotency_key: str) -> Any | None:
        if not idempotency_key:
            return None
        with self._lock:
            key = self._key(tenant_id, idempotency_key)
            entry = self._data.get(key)
            if entry is None:
                return None
            if entry.expires_at < datetime.now(timezone.utc):
                self._data.pop(key, None)
                return None
            # Touch for LRU behaviour.
            self._data.move_to_end(key)
            return entry.result

    def put(self, tenant_id: str | None, idempotency_key: str, result: Any) -> None:
        if not idempotency_key:
            return
        with self._lock:
            key = self._key(tenant_id, idempotency_key)
            self._data[key] = _Entry(
                result=result,
                expires_at=datetime.now(timezone.utc) + self._ttl,
            )
            self._data.move_to_end(key)
            # Enforce capacity.
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def erase_tenant(self, tenant_id: str) -> int:
        """Remove every cached entry for a tenant (right-to-erasure hook)."""
        with self._lock:
            keys = [k for k in self._data if k[0] == tenant_id]
            for k in keys:
                self._data.pop(k, None)
            return len(keys)

    def __len__(self) -> int:
        return len(self._data)
