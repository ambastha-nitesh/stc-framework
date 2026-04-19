"""Redis-backed :class:`KeyValueStore` for multi-replica deployments.

Multi-replica ECS Fargate deployments require a shared state backend
for budget tracking, rate limiting, and idempotency — each replica's
in-memory :class:`InMemoryStore` would otherwise double-spend budgets
and fragment rate-limit windows. This module implements the Protocol
in :mod:`~stc_framework.infrastructure.store` on top of
``redis.asyncio.Redis``.

Design notes:

* Keys are optionally prefixed with a deployment-wide namespace so a
  shared Redis can serve multiple environments or services without
  collision.
* ``keys``/``scan``/``erase_tenant`` use ``SCAN`` (cursor-based) — never
  ``KEYS`` — to avoid blocking the server.
* ``erase_tenant`` performs the same **segment-exact** match as
  :class:`InMemoryStore` (the v0.3.0 staff-review R1 finding); a prefix
  tenant id does not accidentally delete keys for a longer tenant id.
* TLS is required when ``STCSettings.env == "prod"`` — the ctor
  validates the URL scheme.
* Every low-level ``redis.exceptions.RedisError`` is wrapped in
  :class:`StoreError` so callers can catch uniformly.
"""

from __future__ import annotations

import fnmatch
from collections.abc import AsyncIterator
from typing import Any, cast

from stc_framework.infrastructure.store import StoreError


class RedisStore:
    """Async ``KeyValueStore`` implementation backed by Redis.

    The Redis client is provided by the caller so tests can inject
    :class:`fakeredis.aioredis.FakeRedis`. Callers who don't supply a
    client should use :meth:`from_url` to construct one with the
    pinned TLS + timeout settings.
    """

    def __init__(
        self,
        client: Any,
        *,
        namespace: str = "stc",
    ) -> None:
        self._client = client
        self._ns = namespace

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        namespace: str = "stc",
        tls_ca_path: str | None = None,
        require_tls: bool = False,
    ) -> RedisStore:
        """Build a :class:`RedisStore` from a ``redis://`` or ``rediss://`` URL.

        ``require_tls=True`` raises :class:`ValueError` if the URL is
        not ``rediss://``; prod deployments set this via
        :class:`~stc_framework.config.settings.STCSettings`.
        """
        if require_tls and not url.startswith("rediss://"):
            raise ValueError("prod deployments require a rediss:// URL (TLS)")
        try:
            import redis.asyncio as redis_asyncio
        except ImportError as exc:
            raise StoreError("redis is not installed; rebuild the image with 'redis' in DEPLOYED_SUBSYSTEMS") from exc
        kwargs: dict[str, Any] = {
            "decode_responses": False,  # operate on bytes; we decode at the edges
            "socket_timeout": 2.0,
            "socket_connect_timeout": 2.0,
            "retry_on_timeout": True,
        }
        if tls_ca_path:
            kwargs["ssl_ca_certs"] = tls_ca_path
        client = redis_asyncio.from_url(url, **kwargs)
        return cls(client=client, namespace=namespace)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _key(self, key: str) -> bytes:
        return f"{self._ns}:{key}".encode()

    def _strip(self, raw: bytes) -> str:
        """Remove the namespace prefix from a raw key."""
        prefix = f"{self._ns}:".encode()
        if raw.startswith(prefix):
            return raw[len(prefix) :].decode()
        return raw.decode()

    @staticmethod
    def _decode_value(raw: Any) -> Any:
        """Best-effort decode: JSON first, else utf-8, else return raw bytes."""
        if raw is None:
            return None
        import json

        if isinstance(raw, bytes):
            try:
                return json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                try:
                    return raw.decode("utf-8")
                except UnicodeDecodeError:
                    return raw
        return raw

    @staticmethod
    def _encode_value(value: Any) -> bytes:
        """Encode any JSON-serialisable Python value to bytes for storage."""
        import json

        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        return json.dumps(value, separators=(",", ":"), default=str).encode("utf-8")

    # ------------------------------------------------------------------
    # KeyValueStore Protocol methods
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._client.get(self._key(key))
        except Exception as exc:
            raise StoreError(f"redis get failed: {exc}") from exc
        return self._decode_value(raw)

    async def set(self, key: str, value: Any, *, ttl_seconds: float | None = None) -> None:
        payload = self._encode_value(value)
        kwargs: dict[str, Any] = {}
        if ttl_seconds is not None and ttl_seconds > 0:
            # ``PX`` takes milliseconds; round up so short TTLs never resolve to 0.
            kwargs["px"] = max(1, round(ttl_seconds * 1000))
        try:
            await self._client.set(self._key(key), payload, **kwargs)
        except Exception as exc:
            raise StoreError(f"redis set failed: {exc}") from exc

    async def delete(self, key: str) -> bool:
        try:
            removed = await self._client.delete(self._key(key))
        except Exception as exc:
            raise StoreError(f"redis delete failed: {exc}") from exc
        return bool(removed)

    async def exists(self, key: str) -> bool:
        try:
            return bool(await self._client.exists(self._key(key)))
        except Exception as exc:
            raise StoreError(f"redis exists failed: {exc}") from exc

    async def incr(self, key: str, *, amount: int = 1, ttl_seconds: float | None = None) -> int:
        redis_key = self._key(key)
        try:
            existed = await self._client.exists(redis_key)
            new_value = await self._client.incrby(redis_key, amount)
            if ttl_seconds is not None and ttl_seconds > 0 and not existed:
                # Only set TTL when the counter was newly created;
                # subsequent increments must not extend the window.
                await self._client.pexpire(redis_key, max(1, round(ttl_seconds * 1000)))
        except Exception as exc:
            raise StoreError(f"redis incr failed: {exc}") from exc
        return int(new_value)

    async def keys(self, pattern: str = "*") -> list[str]:
        # SCAN the full namespace; filter client-side to support the
        # ``fnmatch``-style pattern semantics documented in the Protocol.
        ns_pattern = f"{self._ns}:*".encode()
        out: list[str] = []
        try:
            async for raw in self._client.scan_iter(match=ns_pattern, count=500):
                stripped = self._strip(raw)
                if fnmatch.fnmatch(stripped, pattern):
                    out.append(stripped)
        except Exception as exc:
            raise StoreError(f"redis scan failed: {exc}") from exc
        return sorted(out)

    async def scan(self, pattern: str = "*") -> AsyncIterator[str]:
        matched = await self.keys(pattern)

        async def _iter() -> AsyncIterator[str]:
            for k in matched:
                yield k

        return _iter()

    async def erase_tenant(self, tenant_id: str, *, key_prefix: str = "") -> int:
        """Delete every key whose colon-delimited segments contain ``tenant_id``.

        Matches :class:`InMemoryStore.erase_tenant` semantics exactly:
        segment-exact only, so ``"t"`` does not clobber ``"t1"``.
        """
        if not tenant_id:
            return 0
        ns_pattern = f"{self._ns}:*".encode()
        candidates: list[bytes] = []
        try:
            async for raw in self._client.scan_iter(match=ns_pattern, count=500):
                stripped = self._strip(raw)
                if key_prefix and not stripped.startswith(key_prefix):
                    continue
                segments = stripped.split(":")
                if tenant_id in segments:
                    candidates.append(cast(bytes, raw))
        except Exception as exc:
            raise StoreError(f"redis scan failed: {exc}") from exc

        removed = 0
        # Batch deletes in chunks of 500 to keep individual commands small.
        for i in range(0, len(candidates), 500):
            chunk = candidates[i : i + 500]
            try:
                removed += int(await self._client.delete(*chunk))
            except Exception as exc:
                raise StoreError(f"redis delete batch failed: {exc}") from exc
        return removed

    async def healthcheck(self) -> bool:
        try:
            result = await self._client.ping()
        except Exception:
            return False
        return bool(result)

    async def close(self) -> None:
        try:
            aclose = getattr(self._client, "aclose", None)
            if callable(aclose):
                await aclose()
            else:
                # Older redis-py variants expose close() as async.
                await self._client.close()
        except Exception:
            # Closing is best-effort — never raise during shutdown.
            pass


__all__ = ["RedisStore"]
