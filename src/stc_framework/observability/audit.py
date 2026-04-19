"""Immutable, tamper-evident audit log.

Every record is frozen (:class:`AuditRecord`) and written through a
pluggable backend. The default JSONL backend computes a per-entry HMAC
chained to the previous entry's hash, so any post-hoc modification to
the file is detectable with :func:`verify_chain` — **provided the
verifier has the HMAC key**.

Why HMAC and not plain SHA-256
------------------------------
Plain SHA-256 is a public hash: an attacker with write access to the
audit file can delete any prefix, rewrite the new first record's
``prev_hash`` to the genesis sentinel, and recompute every subsequent
``entry_hash``. The chain would still verify and nobody would notice.

HMAC-SHA256 requires a secret key at seal time. Without the key an
attacker cannot produce valid ``entry_hash`` values; truncation and
tampering become detectable.

Key management
--------------
- Production: the key **must** be set via ``STC_AUDIT_HMAC_KEY``
  (base64-urlsafe, at least 16 bytes). :class:`STCSystem` strict-prod
  startup refuses to boot without it.
- Dev: a per-process ephemeral key is generated on first use. Chains
  written by one process cannot be verified by another.

External anchoring
------------------
Even with HMAC, operators should anchor the daily tail ``entry_hash``
to an external WORM store (S3 Object Lock, Immudb, OpenTimestamps) so
an attacker with KMS access still cannot forge history undetected. See
:mod:`stc_framework.adapters.audit_backend.worm` for a WORM-shaped
backend that refuses erase/prune operations.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from stc_framework.adapters.audit_backend.base import AuditBackend


_GENESIS_HASH = "0" * 64


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditRecord(BaseModel):
    """A single immutable audit log entry."""

    timestamp: str = Field(default_factory=_utcnow_iso)
    trace_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    persona: str | None = None
    event_type: str
    spec_version: str | None = None

    # Data sovereignty
    data_tier: str | None = None
    boundary_crossing: bool = False
    model: str | None = None

    # Governance
    rail_results: list[dict[str, Any]] = Field(default_factory=list)
    action: str | None = None
    escalation_level: str | None = None

    # Cost & usage
    cost_usd: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    # Redactions
    redactions: int = 0
    redaction_entities: list[str] = Field(default_factory=list)

    # Tamper evidence — filled in by backends that support chaining.
    prev_hash: str | None = None
    entry_hash: str | None = None

    # Identifier of the HMAC key that sealed this record. Lets operators
    # rotate keys without losing verifiability of old records.
    key_id: str | None = None

    # Extras (never accept raw user content here).
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    def hashable_payload(self) -> dict[str, Any]:
        """Return the fields that participate in the integrity hash.

        ``entry_hash`` itself is excluded; ``prev_hash`` and ``key_id``
        are included so the chain is bound end-to-end.
        """
        return self.model_dump(exclude={"entry_hash"})


# ---------------------------------------------------------------------------
# HMAC key management
# ---------------------------------------------------------------------------


class _KeyManager:
    """Resolves the HMAC key for chain seal and verification.

    Singleton: one key per process. Tests can reset via
    :func:`_KeyManager.reset_for_tests`.
    """

    _ENV = "STC_AUDIT_HMAC_KEY"
    _lock = threading.Lock()
    _cached_key: bytes | None = None
    _cached_key_id: str | None = None
    _is_ephemeral: bool = False

    @classmethod
    def key(cls) -> bytes:
        with cls._lock:
            if cls._cached_key is not None:
                return cls._cached_key
            raw = os.getenv(cls._ENV)
            if raw:
                try:
                    key = base64.urlsafe_b64decode(raw)
                except Exception as exc:  # pragma: no cover
                    raise ValueError(f"Invalid {cls._ENV}: {exc}") from exc
                if len(key) < 16:
                    raise ValueError(f"{cls._ENV} must decode to >= 16 bytes; got {len(key)}")
                cls._cached_key = key
                cls._cached_key_id = "env-" + hashlib.sha256(key).hexdigest()[:8]
                cls._is_ephemeral = False
            else:
                cls._cached_key = secrets.token_bytes(32)
                cls._cached_key_id = "ephemeral-" + secrets.token_hex(4)
                cls._is_ephemeral = True
            return cls._cached_key

    @classmethod
    def key_id(cls) -> str:
        cls.key()
        assert cls._cached_key_id is not None
        return cls._cached_key_id

    @classmethod
    def is_ephemeral(cls) -> bool:
        cls.key()
        return cls._is_ephemeral

    @classmethod
    def reset_for_tests(cls) -> None:
        with cls._lock:
            cls._cached_key = None
            cls._cached_key_id = None
            cls._is_ephemeral = False


def compute_entry_hash(record: AuditRecord, *, key: bytes | None = None) -> str:
    """Compute HMAC-SHA256 of a record bound to ``record.prev_hash``."""
    hmac_key = key if key is not None else _KeyManager.key()
    payload = record.hashable_payload()
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hmac.new(hmac_key, blob, hashlib.sha256).hexdigest()


def verify_chain(
    records: Iterator[AuditRecord],
    *,
    key: bytes | None = None,
    accept_unknown_genesis: bool = False,
) -> tuple[bool, int, str]:
    """Verify a sequence preserves the HMAC-chained integrity.

    Returns ``(ok, count, failure_reason)``. Caller must pass the HMAC
    key used to seal the chain — the current process key is used when
    ``key=None``, which only works for chains sealed by this process.

    Parameters
    ----------
    accept_unknown_genesis:
        When ``True``, the first record's ``prev_hash`` is accepted as
        given; verification only checks that subsequent records chain
        to each other. This is the correct mode for verifying a log
        that has been through one or more :meth:`prune_before` passes —
        the first surviving record's predecessor has been deleted.
        Strict mode (the default) still requires the chain to begin at
        :data:`_GENESIS_HASH`.

    """
    prev: str | None = None if accept_unknown_genesis else _GENESIS_HASH
    count = 0
    for record in records:
        if prev is None:
            # Accept-unknown-genesis mode: the first record's prev_hash
            # is taken verbatim as the effective starting point.
            prev = record.prev_hash or _GENESIS_HASH
        if record.prev_hash != prev:
            return (
                False,
                count,
                f"prev_hash mismatch at entry {count}: expected {prev} got {record.prev_hash}",
            )
        expected_hash = compute_entry_hash(record, key=key)
        if not hmac.compare_digest(record.entry_hash or "", expected_hash):
            return (
                False,
                count,
                f"entry_hash mismatch at entry {count}: HMAC did not verify",
            )
        prev = record.entry_hash or _GENESIS_HASH
        count += 1
    return (True, count, "")


class AuditLogger:
    """Writes :class:`AuditRecord` instances through a pluggable backend.

    Every write also bumps the ``stc_governance_events_total`` counter.
    """

    def __init__(self, backend: AuditBackend) -> None:
        self._backend = backend

    def _record_metric(self, record: AuditRecord) -> None:
        from stc_framework.observability.metrics import get_metrics

        try:
            get_metrics().governance_events_total.labels(event_type=record.event_type).inc()
        except Exception:  # pragma: no cover
            pass

    async def emit(self, record: AuditRecord) -> AuditRecord:
        sealed = await self._backend.append(record)
        self._record_metric(sealed)
        return sealed

    def emit_sync(self, record: AuditRecord) -> AuditRecord:
        sealed = self._backend.append_sync(record)
        self._record_metric(sealed)
        return sealed

    async def close(self) -> None:
        await self._backend.close()

    @property
    def backend(self) -> AuditBackend:
        return self._backend
