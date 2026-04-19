"""Secure destruction utilities for retention and DSAR erasure.

Regulators (SEC 17a-4, GDPR Art. 17, NYDFS Part 500) require that
"deletion" actually means the data is unrecoverable, not just that the
filesystem pointer is removed. This module provides the building
blocks:

* :class:`DestructionMethod` — overwrite / crypto-erase / standard-delete.
* :func:`overwrite_file` — DoD 5220.22-M-style three-pass overwrite.
* :func:`crypto_erase` — drop the encryption key so ciphertext is
  permanently unrecoverable (only applicable if the data was encrypted
  with a per-artifact key in the first place).
* :func:`verify_destruction` — confirms the file is gone or zeroised.
* :class:`DestructionRecord` — audit-friendly receipt that goes into the
  audit chain.

Every destruction first consults the legal-hold registry (if enabled)
and refuses to proceed if the artifact is under an active hold. The
refusal itself is audited via ``destruction_blocked_by_hold``.

This module is intentionally backend-agnostic — it deletes file paths
and emits audit records. Store-specific destroyers (vector index purge,
token-map shred) live in the subsystems that own those stores.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from stc_framework.errors import LegalHoldActive
from stc_framework.governance.events import AuditEvent
from stc_framework.observability.audit import AuditLogger, AuditRecord


class DestructionMethod(str, Enum):
    SECURE_OVERWRITE = "secure_overwrite"
    CRYPTO_ERASE = "crypto_erase"
    STANDARD_DELETE = "standard_delete"


@dataclass
class DestructionRecord:
    """A single destruction receipt written to the audit chain."""

    data_store: str
    artifact: str  # path, key id, or resource id depending on store
    method: DestructionMethod
    verified: bool
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    actor: str = "retention_sweep"
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LegalHoldChecker(Protocol):
    """A callable the retention layer consults before destroying anything.

    Implementations live in :mod:`stc_framework.compliance.legal_hold`
    (Phase 3). Keeping the interface here avoids a cyclic import.
    """

    async def check_destruction_allowed(
        self, *, artifact: str, data_store: str, tenant_id: str | None = None
    ) -> tuple[bool, str | None]: ...


_DOD_PATTERNS: tuple[bytes, ...] = (
    b"\x00",
    b"\xff",
    b"\xaa",  # random pattern fallback — real random bytes added per pass
)


def overwrite_file(path: str | Path, *, passes: int = 3) -> bool:
    """Overwrite a file in place with ``passes`` rounds, then unlink.

    Uses fixed bit patterns for the first N-1 passes and cryptographic
    random bytes for the final pass, mirroring DoD 5220.22-M without
    claiming compliance (real compliance requires hardware-level
    guarantees that Python cannot provide).

    Returns True if the file no longer exists after the call.
    Non-file paths return False without raising.
    """
    p = Path(path)
    if not p.is_file():
        return False
    size = p.stat().st_size
    try:
        with open(p, "r+b", buffering=0) as fh:
            for pass_idx in range(passes):
                fh.seek(0)
                if pass_idx == passes - 1:
                    # Final pass: cryptographic random
                    remaining = size
                    while remaining > 0:
                        chunk = min(remaining, 1 << 20)  # 1 MB
                        fh.write(secrets.token_bytes(chunk))
                        remaining -= chunk
                else:
                    pattern = _DOD_PATTERNS[pass_idx % len(_DOD_PATTERNS)]
                    remaining = size
                    while remaining > 0:
                        chunk = min(remaining, 1 << 20)
                        fh.write(pattern * chunk)
                        remaining -= chunk
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    # fsync not supported on all filesystems (e.g. some
                    # Windows network shares). Best-effort.
                    pass
    except OSError:
        return False
    try:
        p.unlink()
    except OSError:
        return False
    return not p.exists()


def crypto_erase(key_identifier: str, *, key_registry: dict[str, Any] | None = None) -> bool:
    """Drop an encryption key so any ciphertext encrypted with it is permanently unreadable.

    The caller owns the key registry; we simply pop the entry and
    confirm it's gone. Returns True if the key was present and removed.
    """
    if key_registry is None or key_identifier not in key_registry:
        return False
    key_registry.pop(key_identifier, None)
    return key_identifier not in key_registry


def verify_destruction(path: str | Path) -> bool:
    """Confirm a file no longer exists. Used after ``overwrite_file`` runs."""
    return not Path(path).exists()


async def destroy_with_hold_check(
    *,
    data_store: str,
    artifact: str,
    method: DestructionMethod,
    destroy_fn: Any,
    legal_hold: LegalHoldChecker | None = None,
    tenant_id: str | None = None,
    actor: str = "retention_sweep",
    reason: str = "",
    audit: AuditLogger | None = None,
) -> DestructionRecord:
    """Destroy ``artifact`` via ``destroy_fn`` after a legal-hold check.

    ``destroy_fn`` is any async callable that performs the actual
    destruction and returns True on success. It receives no arguments
    (bind parameters via closure or ``functools.partial`` at the call
    site).

    Raises :class:`LegalHoldActive` if a hold is in force; emits
    ``destruction_blocked_by_hold`` to the audit chain and does not call
    ``destroy_fn``.
    """
    if legal_hold is not None:
        allowed, hold_id = await legal_hold.check_destruction_allowed(
            artifact=artifact,
            data_store=data_store,
            tenant_id=tenant_id,
        )
        if not allowed:
            if audit is not None:
                await audit.emit(
                    AuditRecord(
                        tenant_id=tenant_id,
                        event_type=AuditEvent.DESTRUCTION_BLOCKED_BY_HOLD.value,
                        persona="governance",
                        action="blocked",
                        extra={
                            "artifact": artifact,
                            "data_store": data_store,
                            "hold_id": hold_id or "",
                        },
                    )
                )
            raise LegalHoldActive(
                message=f"destruction of {artifact!r} blocked by active legal hold",
                hold_id=hold_id or "",
            )

    verified = bool(await destroy_fn())
    record = DestructionRecord(
        data_store=data_store,
        artifact=artifact,
        method=method,
        verified=verified,
        actor=actor,
        reason=reason,
    )
    if audit is not None:
        await audit.emit(
            AuditRecord(
                tenant_id=tenant_id,
                event_type=AuditEvent.RETENTION_SWEEP.value,
                persona="governance",
                action="destroyed" if verified else "destruction_failed",
                extra={
                    "artifact": artifact,
                    "data_store": data_store,
                    "method": method.value,
                    "verified": verified,
                    "actor": actor,
                    "reason": reason,
                },
            )
        )
    return record


__all__ = [
    "DestructionMethod",
    "DestructionRecord",
    "LegalHoldChecker",
    "crypto_erase",
    "destroy_with_hold_check",
    "overwrite_file",
    "verify_destruction",
]
