"""Pluggable session state manager.

Keeps conversation context, surrogate token maps, per-session cost
counters, and per-minute request counters in one place, all routed
through :class:`KeyValueStore` so in-memory dev deployments and
Redis-backed production deployments share the same API.

Key namespacing (matches the experimental prototype so dashboards keep
working during the migration):

    session:{id}:context   -> JSON conversation state
    session:{id}:tokens    -> encrypted surrogate token blob
    session:{id}:meta      -> creation time, tenant id, data tier
    cost:{date}:{persona}  -> atomic micro-dollars counter
    rate:{persona}:{minute}-> atomic requests-in-minute counter

Cost is stored in **micro-dollars** (integer ``int(usd * 1e6)``) so the
``incr`` op stays atomic; convert via :func:`usd_from_micro` when
reading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stc_framework._internal.ttl import TTL
from stc_framework.errors import SessionExpired
from stc_framework.governance.events import AuditEvent
from stc_framework.infrastructure.store import KeyValueStore
from stc_framework.observability.audit import AuditLogger, AuditRecord
from stc_framework.observability.metrics import get_metrics, tenant_label


@dataclass
class SessionMetadata:
    session_id: str
    tenant_id: str = ""
    data_tier: str = "public"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str = ""
    request_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


def usd_to_micro(usd: float) -> int:
    """Convert USD → micro-dollars for atomic counter storage."""
    return round(usd * 1_000_000)


def usd_from_micro(micro: int) -> float:
    return micro / 1_000_000


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _current_minute() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M")


class SessionManager:
    """All per-session state is routed through this class."""

    def __init__(
        self,
        store: KeyValueStore,
        *,
        default_ttl_seconds: int = 3600,
        audit: AuditLogger | None = None,
        backend_label: str = "memory",
    ) -> None:
        self._store = store
        self._default_ttl = default_ttl_seconds
        self._audit = audit
        self._backend = backend_label

    # ----- lifecycle ----------------------------------------------------

    async def create_session(
        self,
        session_id: str,
        *,
        tenant_id: str = "",
        data_tier: str = "public",
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionMetadata:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        deadline = TTL.from_seconds(ttl)
        expires_iso = datetime.fromtimestamp(deadline.expires_at, tz=timezone.utc).isoformat()
        meta = SessionMetadata(
            session_id=session_id,
            tenant_id=tenant_id,
            data_tier=data_tier,
            expires_at=expires_iso,
            metadata=dict(metadata or {}),
        )
        await self._store.set(
            f"session:{session_id}:meta",
            self._meta_to_dict(meta),
            ttl_seconds=float(ttl),
        )
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    tenant_id=tenant_id or None,
                    event_type=AuditEvent.SESSION_CREATED.value,
                    persona="infrastructure",
                    extra={"session_id": session_id, "data_tier": data_tier, "ttl_seconds": ttl},
                )
            )
        try:
            get_metrics().session_active.labels(backend=self._backend).inc()
        except Exception:
            pass
        return meta

    async def get_metadata(self, session_id: str) -> SessionMetadata | None:
        raw = await self._store.get(f"session:{session_id}:meta")
        return self._meta_from_dict(raw) if raw else None

    async def destroy_session(self, session_id: str) -> None:
        meta = await self.get_metadata(session_id)
        await self._store.delete(f"session:{session_id}:meta")
        await self._store.delete(f"session:{session_id}:context")
        await self._store.delete(f"session:{session_id}:tokens")
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    tenant_id=(meta.tenant_id or None) if meta else None,
                    event_type=AuditEvent.SESSION_DESTROYED.value,
                    persona="infrastructure",
                    extra={"session_id": session_id},
                )
            )
        try:
            get_metrics().session_active.labels(backend=self._backend).dec()
        except Exception:
            pass

    async def assert_active(self, session_id: str) -> SessionMetadata:
        meta = await self.get_metadata(session_id)
        if meta is None:
            raise SessionExpired(message=f"session {session_id!r} does not exist or has expired")
        if meta.expires_at:
            expiry = datetime.fromisoformat(meta.expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= expiry:
                raise SessionExpired(message=f"session {session_id!r} expired at {meta.expires_at}")
        return meta

    # ----- context + tokens ---------------------------------------------

    async def save_context(self, session_id: str, context: dict[str, Any]) -> None:
        meta = await self.assert_active(session_id)
        remaining = self._remaining_ttl(meta)
        await self._store.set(f"session:{session_id}:context", context, ttl_seconds=remaining)

    async def load_context(self, session_id: str) -> dict[str, Any] | None:
        await self.assert_active(session_id)
        raw = await self._store.get(f"session:{session_id}:context")
        return raw if isinstance(raw, dict) else None

    async def save_token_map(self, session_id: str, blob: str) -> None:
        meta = await self.assert_active(session_id)
        remaining = self._remaining_ttl(meta)
        await self._store.set(f"session:{session_id}:tokens", blob, ttl_seconds=remaining)

    async def load_token_map(self, session_id: str) -> str | None:
        await self.assert_active(session_id)
        raw = await self._store.get(f"session:{session_id}:tokens")
        return raw if isinstance(raw, str) else None

    # ----- atomic counters ----------------------------------------------

    async def increment_cost(self, persona: str, *, usd: float, tenant_id: str = "") -> float:
        """Add ``usd`` to today's ``cost:{date}:{persona}`` counter.

        Returns the new total in USD. Internally stored as micro-dollars
        to keep ``incr`` atomic on any backend.
        """
        micro = usd_to_micro(usd)
        key = f"cost:{_today_utc()}:{persona}"
        new_micro = await self._store.incr(key, amount=micro, ttl_seconds=48 * 3600)
        total = usd_from_micro(int(new_micro))
        try:
            get_metrics().session_cost_usd_total.labels(tenant=tenant_label(tenant_id or None)).inc(usd)
        except Exception:
            pass
        return total

    async def check_rate_limit(self, persona: str, *, per_minute_cap: int) -> int:
        """Increment per-minute request counter; return new count."""
        key = f"rate:{persona}:{_current_minute()}"
        new_count = await self._store.incr(key, ttl_seconds=120)
        return int(new_count)

    # ----- health -------------------------------------------------------

    async def health(self) -> bool:
        return await self._store.healthcheck()

    # ----- helpers ------------------------------------------------------

    @staticmethod
    def _meta_to_dict(meta: SessionMetadata) -> dict[str, Any]:
        return {
            "session_id": meta.session_id,
            "tenant_id": meta.tenant_id,
            "data_tier": meta.data_tier,
            "created_at": meta.created_at,
            "expires_at": meta.expires_at,
            "request_count": meta.request_count,
            "metadata": dict(meta.metadata),
        }

    @staticmethod
    def _meta_from_dict(raw: dict[str, Any]) -> SessionMetadata:
        return SessionMetadata(
            session_id=raw["session_id"],
            tenant_id=raw.get("tenant_id", ""),
            data_tier=raw.get("data_tier", "public"),
            created_at=raw.get("created_at", ""),
            expires_at=raw.get("expires_at", ""),
            request_count=int(raw.get("request_count", 0)),
            metadata=dict(raw.get("metadata", {})),
        )

    @staticmethod
    def _remaining_ttl(meta: SessionMetadata) -> float | None:
        """Seconds remaining until ``meta.expires_at``, or None if open-ended."""
        if not meta.expires_at:
            return None
        expiry = datetime.fromisoformat(meta.expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        delta = (expiry - datetime.now(timezone.utc)).total_seconds()
        return max(1.0, delta)


__all__ = ["SessionManager", "SessionMetadata", "usd_from_micro", "usd_to_micro"]
