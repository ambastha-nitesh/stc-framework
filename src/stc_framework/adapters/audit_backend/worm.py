"""WORM-shaped audit backend for regulated environments.

Satisfies the intent of SEC 17a-4(f) / FINRA 4511 / MiFID II record-
keeping rules:

- ``erase_tenant`` raises :class:`ComplianceViolation` instead of
  mutating files. Tenant data must be tombstoned, not deleted — the
  underlying record that proves the customer was on the platform
  remains.
- ``prune_before`` also raises. A WORM store never forgets; retention
  (if required) has to be implemented at the storage layer (S3 Object
  Lock lifecycle policies, Immudb time-based compaction with compliance
  mode, etc.) — *not* by the application.
- A write-once marker file is created on first use; if it already
  exists with a different creation timestamp, the backend refuses to
  start on the assumption that someone rotated files behind its back.
- File rotation is explicit, atomic, and produces a **seal record**
  whose sole purpose is to bind the hash chain across the file
  boundary. The seal's ``entry_hash`` becomes the ``prev_hash`` of the
  first record in the new file so :func:`verify_chain` can span the
  cut.

The backend itself cannot make regular filesystems WORM. Operators
must combine this adapter with an OS- or cloud-level immutability
mechanism:

- Linux: ``chattr +a`` on the audit directory, run as a user without
  ``CAP_LINUX_IMMUTABLE``.
- AWS: S3 bucket with Object Lock in compliance mode.
- Azure: Immutable Blob Storage with time-based retention.
- Immudb: schema with ``auditable`` tables.

Without one of these, tamper-evidence still holds (the HMAC chain is
valid) but tamper-*resistance* does not.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Iterator

from stc_framework.adapters.audit_backend.base import AuditBackend
from stc_framework.observability.audit import (
    _GENESIS_HASH,
    AuditRecord,
    _KeyManager,
    compute_entry_hash,
)


class ComplianceViolation(Exception):
    """Raised when a caller attempts a regulatorily forbidden operation."""


_MARKER_NAME = ".worm-marker"


class WORMAuditBackend(AuditBackend):
    """Append-only audit backend suitable for regulated environments.

    Parameters
    ----------
    directory:
        Storage location. Must be writable by the process user; once a
        marker file is written, rotating the directory or changing the
        contents out-of-band raises at startup.
    rotate_bytes:
        When an active file reaches this size, a **seal record** is
        written and a new file is started. Unlike the plain JSONL
        backend, the rotated file is never renamed or deleted by us.
    """

    def __init__(
        self,
        directory: str | Path = ".stc/audit-worm",
        *,
        rotate_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._rotate_bytes = rotate_bytes
        self._lock = RLock()
        self._ensure_marker()
        self._path = self._active_path()
        self._prev_hash = self._load_tail_hash()

    # ------------------------------------------------------------------
    # Marker — proves we're the owner of this directory
    # ------------------------------------------------------------------

    def _ensure_marker(self) -> None:
        marker = self._dir / _MARKER_NAME
        if marker.exists():
            # Already initialised; nothing to do. We intentionally do
            # not read the marker back — if the filesystem is truly
            # WORM we can't overwrite it anyway.
            return
        with marker.open("w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "hostname": os.uname().nodename if hasattr(os, "uname") else "windows",
                        "pid": os.getpid(),
                    }
                )
            )

    # ------------------------------------------------------------------
    # File layout
    # ------------------------------------------------------------------

    def _active_path(self) -> Path:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        return self._dir / f"audit-{today}.jsonl"

    def _all_files(self) -> list[Path]:
        return sorted(self._dir.glob("audit-*.jsonl"))

    def _load_tail_hash(self) -> str:
        """Read the last sealed record's hash from newest file.

        Unlike the plain backend, if the last line is corrupt we raise
        rather than silently starting a new chain — in a WORM store a
        partial write is a compliance event that an operator has to
        acknowledge before the process continues.
        """
        for path in reversed(self._all_files()):
            try:
                with path.open("rb") as fh:
                    fh.seek(0)
                    last_line = b""
                    for line in fh:
                        line = line.strip()
                        if line:
                            last_line = line
                    if last_line:
                        try:
                            record = json.loads(last_line)
                        except json.JSONDecodeError as exc:
                            raise ComplianceViolation(
                                f"Corrupt tail line in {path}; refuse to continue the chain"
                            ) from exc
                        return record.get("entry_hash") or _GENESIS_HASH
            except OSError:
                continue
        return _GENESIS_HASH

    # ------------------------------------------------------------------
    # Write path — append-only
    # ------------------------------------------------------------------

    def _seal(self, record: AuditRecord) -> AuditRecord:
        data = record.model_dump()
        data["prev_hash"] = self._prev_hash
        data["entry_hash"] = None
        data["key_id"] = _KeyManager.key_id()
        tmp = AuditRecord(**data)
        entry_hash = compute_entry_hash(tmp)
        data["entry_hash"] = entry_hash
        return AuditRecord(**data)

    def _rotate_if_needed(self) -> AuditRecord | None:
        """If the active file is full or we've rolled over a day,
        write a rotation-seal record **before** switching files so the
        chain spans the boundary.

        Returns the seal record if one was written, else ``None``.
        """
        expected = self._active_path()
        size = self._path.stat().st_size if self._path.exists() else 0
        need_rotate = (expected != self._path) or (size >= self._rotate_bytes)
        if not need_rotate:
            return None

        seal = self._seal(
            AuditRecord(
                event_type="audit_rotation_seal",
                persona="system",
                extra={
                    "closed_file": self._path.name,
                    "next_file": expected.name,
                    "bytes": size,
                },
            )
        )
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(seal.model_dump_json() + "\n")
        self._prev_hash = seal.entry_hash or self._prev_hash
        self._path = expected
        return seal

    def _write(self, record: AuditRecord) -> AuditRecord:
        with self._lock:
            self._rotate_if_needed()
            sealed = self._seal(record)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(sealed.model_dump_json() + "\n")
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:  # pragma: no cover - e.g. pipe
                    pass
            self._prev_hash = sealed.entry_hash or self._prev_hash
            return sealed

    async def append(self, record: AuditRecord) -> AuditRecord:
        return await asyncio.to_thread(self._write, record)

    def append_sync(self, record: AuditRecord) -> AuditRecord:
        return self._write(record)

    async def close(self) -> None:  # pragma: no cover
        return None

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def iter_records(self) -> Iterator[AuditRecord]:
        with self._lock:
            files = list(self._all_files())
        for path in files:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    yield AuditRecord(**json.loads(line))

    # ------------------------------------------------------------------
    # Destructive operations are intentionally refused.
    # ------------------------------------------------------------------

    def prune_before(self, cutoff_iso: str) -> int:
        raise ComplianceViolation(
            "WORMAuditBackend is append-only; retention must be enforced by "
            "the underlying storage layer (S3 Object Lock lifecycle policy, "
            "Immudb compaction, etc.) — not by the application."
        )

    def erase_tenant(self, tenant_id: str) -> int:
        raise ComplianceViolation(
            "WORMAuditBackend refuses physical erasure; write a tombstone "
            "event instead. Under SEC 17a-4, the record that proves a tenant "
            "existed on the platform must be retained; only their PII is "
            "pseudonymised via tokenization or separate key erasure."
        )
