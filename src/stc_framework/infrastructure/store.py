"""Pluggable async key-value store used across v0.3.0 subsystems.

Risk register, data catalog, data lineage, session state, legal-hold
registry, and workflow checkpoints all need persistent state. Rather
than each subsystem inventing its own backend, they route through a
single :class:`KeyValueStore` Protocol.

Shipped defaults:
  * :class:`InMemoryStore` — process-local dict, thread-safe via
    ``asyncio.Lock``; suitable for tests and single-process deployments.

A Redis-backed implementation lives behind the ``[session]`` extra and
is wired in :mod:`stc_framework.infrastructure.session_state`.

Keys are strings (namespace with ``prefix:subkey`` by convention).
Values are opaque bytes or JSON-serialisable Python objects; the
interface does not enforce a schema.

**Tenant scoping**: keys are NOT automatically tenant-scoped. Callers
that store per-tenant data must include the tenant id as a
**colon-delimited segment** in the key (``"risk:{tenant}:{risk_id}"``
or ``"session:{tenant}:{sid}"``). ``erase_tenant`` matches segments
exactly — substring matching would conflate tenants whose ids are
prefixes of each other (``"t"`` vs ``"t1"``). Implementations MUST
follow this contract.
"""

from __future__ import annotations

import asyncio
import fnmatch
import time
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable


class StoreError(Exception):
    """Backend-level failure (connection, serialisation, etc.)."""


@runtime_checkable
class KeyValueStore(Protocol):
    """Async key-value store contract.

    Every method is async to allow network-backed implementations.
    In-process implementations may fulfil the contract synchronously and
    wrap in ``async def`` with no await.
    """

    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any, *, ttl_seconds: float | None = None) -> None: ...

    async def delete(self, key: str) -> bool: ...

    async def exists(self, key: str) -> bool: ...

    async def incr(self, key: str, *, amount: int = 1, ttl_seconds: float | None = None) -> int: ...

    async def keys(self, pattern: str = "*") -> list[str]: ...

    async def scan(self, pattern: str = "*") -> AsyncIterator[str]: ...

    async def erase_tenant(self, tenant_id: str, *, key_prefix: str = "") -> int: ...

    async def healthcheck(self) -> bool: ...

    async def close(self) -> None: ...


class InMemoryStore:
    """Process-local dict-backed store.

    Thread-safe via an ``asyncio.Lock``. TTL is enforced lazily on access
    (no background sweeper), which matches Redis-like semantics and keeps
    the implementation dependency-free.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._expiry: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            self._purge_if_expired(key)
            return self._data.get(key)

    async def set(self, key: str, value: Any, *, ttl_seconds: float | None = None) -> None:
        async with self._lock:
            self._data[key] = value
            if ttl_seconds is not None and ttl_seconds > 0:
                self._expiry[key] = time.time() + ttl_seconds
            elif key in self._expiry:
                del self._expiry[key]

    async def delete(self, key: str) -> bool:
        async with self._lock:
            existed = key in self._data
            self._data.pop(key, None)
            self._expiry.pop(key, None)
            return existed

    async def exists(self, key: str) -> bool:
        async with self._lock:
            self._purge_if_expired(key)
            return key in self._data

    async def incr(self, key: str, *, amount: int = 1, ttl_seconds: float | None = None) -> int:
        async with self._lock:
            self._purge_if_expired(key)
            current = int(self._data.get(key, 0))
            new_value = current + amount
            self._data[key] = new_value
            if ttl_seconds is not None and ttl_seconds > 0 and key not in self._expiry:
                self._expiry[key] = time.time() + ttl_seconds
            return new_value

    async def keys(self, pattern: str = "*") -> list[str]:
        async with self._lock:
            # Purge expired in-line so callers see a clean snapshot.
            for k in list(self._data.keys()):
                self._purge_if_expired(k)
            return sorted(k for k in self._data if fnmatch.fnmatch(k, pattern))

    async def scan(self, pattern: str = "*") -> AsyncIterator[str]:
        # Snapshot under lock then yield outside to avoid holding during iteration.
        matched = await self.keys(pattern)

        async def _iter() -> AsyncIterator[str]:
            for k in matched:
                yield k

        return _iter()

    async def erase_tenant(self, tenant_id: str, *, key_prefix: str = "") -> int:
        """Delete every key whose colon-delimited segments contain ``tenant_id``.

        Matching is **segment-exact**, not substring. ``"risk:t:r-1"``
        matches ``tenant_id="t"`` but ``"risk:t1:r-1"`` does not. This
        prevents cross-tenant deletion when tenant ids share prefixes.

        ``key_prefix`` lets callers restrict the sweep to a subsystem's
        namespace (e.g. ``risk:`` or ``session:``).
        """
        if not tenant_id:
            return 0
        removed = 0
        async with self._lock:
            for k in list(self._data.keys()):
                if key_prefix and not k.startswith(key_prefix):
                    continue
                segments = k.split(":")
                if tenant_id in segments:
                    self._data.pop(k, None)
                    self._expiry.pop(k, None)
                    removed += 1
        return removed

    async def healthcheck(self) -> bool:
        return True

    async def close(self) -> None:
        async with self._lock:
            self._data.clear()
            self._expiry.clear()

    def _purge_if_expired(self, key: str) -> None:
        """Must be called under the lock."""
        if key in self._expiry and time.time() >= self._expiry[key]:
            self._data.pop(key, None)
            self._expiry.pop(key, None)


__all__ = ["InMemoryStore", "KeyValueStore", "StoreError"]
