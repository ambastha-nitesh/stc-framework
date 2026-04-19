"""Hash-chained JSONL audit backend.

Design:

- One file per UTC day (rotates on size or day rollover).
- Every line is one :class:`AuditRecord` serialized as JSON.
- ``prev_hash`` points at the previous record's ``entry_hash``, starting
  at ``0 * 64`` for the very first record in the directory.
- Mutating the file (reordering, inserting, editing) breaks the chain
  and is detected by :func:`stc_framework.observability.audit.verify_chain`.

The backend is process-safe for a single writer; for multi-writer
deployments you should use a centralized backend instead (e.g. a database
with an append-only table).
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from stc_framework.adapters.audit_backend.base import AuditBackend
from stc_framework.observability.audit import (
    _GENESIS_HASH,
    AuditRecord,
    _KeyManager,
    compute_entry_hash,
)


class JSONLAuditBackend(AuditBackend):
    """Writes each record as a JSON line and chains records by hash."""

    def __init__(
        self,
        directory: str | Path = ".stc/audit",
        *,
        rotate_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._rotate_bytes = rotate_bytes
        self._lock = RLock()
        self._path = self._active_path()
        self._prev_hash = self._load_tail_hash()

    # ------------------------------------------------------------------
    # File layout helpers
    # ------------------------------------------------------------------

    def _active_path(self) -> Path:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        return self._dir / f"audit-{today}.jsonl"

    def _all_files(self) -> list[Path]:
        return sorted(self._dir.glob("audit-*.jsonl"))

    def _load_tail_hash(self) -> str:
        """Return the hash of the last record across all audit files."""
        for path in reversed(self._all_files()):
            try:
                with path.open("rb") as fh:
                    # Seek to end, read backwards until we find a newline.
                    fh.seek(0, os.SEEK_END)
                    length = fh.tell()
                    if length == 0:
                        continue
                    # Simple approach: read the whole file — audit files
                    # are bounded at rotate_bytes so this is fine at
                    # process start.
                    fh.seek(0)
                    last_line = b""
                    for line in fh:
                        line = line.strip()
                        if line:
                            last_line = line
                    if last_line:
                        record = json.loads(last_line)
                        return record.get("entry_hash") or _GENESIS_HASH
            except (OSError, json.JSONDecodeError):
                continue
        return _GENESIS_HASH

    def _rotate_if_needed(self) -> None:
        expected = self._active_path()
        if expected != self._path:
            self._path = expected
            return
        if not self._path.exists():
            return
        if self._path.stat().st_size < self._rotate_bytes:
            return
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        rotated = self._path.with_suffix(f".{ts}.jsonl")
        os.replace(self._path, rotated)
        self._path = self._active_path()

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def _seal(self, record: AuditRecord) -> AuditRecord:
        """Produce a sealed copy of ``record`` with prev_hash / entry_hash set."""
        data = record.model_dump()
        data["prev_hash"] = self._prev_hash
        data["entry_hash"] = None
        data["key_id"] = _KeyManager.key_id()
        tmp = AuditRecord(**data)
        entry_hash = compute_entry_hash(tmp)
        data["entry_hash"] = entry_hash
        return AuditRecord(**data)

    def _write(self, record: AuditRecord) -> AuditRecord:
        with self._lock:
            self._rotate_if_needed()
            sealed = self._seal(record)
            line = sealed.model_dump_json() + "\n"
            # Write with O_APPEND so concurrent writers within one process
            # do not overlap.
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)
            self._prev_hash = sealed.entry_hash or self._prev_hash
            return sealed

    async def append(self, record: AuditRecord) -> AuditRecord:
        return await asyncio.to_thread(self._write, record)

    def append_sync(self, record: AuditRecord) -> AuditRecord:
        return self._write(record)

    async def close(self) -> None:  # pragma: no cover - nothing to close
        return None

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def iter_records(self) -> Iterator[AuditRecord]:
        with self._lock:
            files = list(self._all_files())
        for path in files:
            try:
                with path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            yield AuditRecord(**json.loads(line))
                        except Exception:  # pragma: no cover
                            # Skip corrupt lines rather than break iteration;
                            # they will also fail chain verification.
                            continue
            except FileNotFoundError:  # pragma: no cover - racy rotation
                continue

    # ------------------------------------------------------------------
    # Retention + erasure
    # ------------------------------------------------------------------

    def prune_before(self, cutoff_iso: str) -> int:
        """Delete entire files whose records pre-date ``cutoff_iso``.

        Before deletion, a **seal record** is appended to the currently
        active file recording the last ``entry_hash`` of the oldest
        retained file. :func:`verify_chain` can then cross the deletion
        boundary without reporting a broken chain.
        """
        removed = 0
        last_pruned_hash: str | None = None
        with self._lock:
            for path in list(self._all_files()):
                if self._file_is_entirely_before(path, cutoff_iso):
                    last_pruned_hash = self._last_hash_in_file(path) or last_pruned_hash
                    try:
                        os.remove(path)
                        removed += 1
                    except FileNotFoundError:  # pragma: no cover
                        pass

            if removed:
                # Write a seal binding the surviving chain to the hash
                # of the last pruned record. verify_chain treats this as
                # a checkpoint.
                seal = AuditRecord(
                    event_type="retention_prune_seal",
                    persona="system",
                    extra={
                        "cutoff_iso": cutoff_iso,
                        "files_removed": removed,
                        "last_pruned_entry_hash": last_pruned_hash,
                    },
                )
                self._rotate_if_needed()
                sealed = self._seal(seal)
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(sealed.model_dump_json() + "\n")
                self._prev_hash = sealed.entry_hash or self._prev_hash
        return removed

    def _last_hash_in_file(self, path: Path) -> str | None:
        try:
            with path.open("r", encoding="utf-8") as fh:
                last = None
                for line in fh:
                    line = line.strip()
                    if line:
                        last = line
                if last is None:
                    return None
                return json.loads(last).get("entry_hash")
        except (OSError, json.JSONDecodeError):  # pragma: no cover
            return None

    def _file_is_entirely_before(self, path: Path, cutoff_iso: str) -> bool:
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    if record.get("timestamp", "") >= cutoff_iso:
                        return False
                return True
        except (OSError, json.JSONDecodeError):  # pragma: no cover
            return False

    def erase_tenant(self, tenant_id: str) -> int:
        """Rewrite every audit file omitting rows for ``tenant_id``.

        The hash chain is recomputed so the result remains verifiable.
        An :class:`AuditRecord` with ``event_type = "erasure"`` should be
        appended by the governance workflow to record the operation
        itself (see :mod:`stc_framework.governance.erasure`).
        """
        removed = 0
        with self._lock:
            prev = _GENESIS_HASH
            for path in list(self._all_files()):
                new_lines: list[str] = []
                kept_any = False
                try:
                    with path.open("r", encoding="utf-8") as fh:
                        for line in fh:
                            line_s = line.strip()
                            if not line_s:
                                continue
                            try:
                                record = json.loads(line_s)
                            except json.JSONDecodeError:
                                continue
                            if record.get("tenant_id") == tenant_id:
                                removed += 1
                                continue
                            record["prev_hash"] = prev
                            record["entry_hash"] = None
                            record["key_id"] = _KeyManager.key_id()
                            rebuilt = AuditRecord(**record)
                            entry_hash = compute_entry_hash(rebuilt)
                            sealed = AuditRecord(**{**record, "entry_hash": entry_hash})
                            new_lines.append(sealed.model_dump_json())
                            prev = entry_hash
                            kept_any = True
                except FileNotFoundError:  # pragma: no cover
                    continue

                if not kept_any:
                    try:
                        os.remove(path)
                    except FileNotFoundError:  # pragma: no cover
                        pass
                else:
                    tmp = path.with_suffix(path.suffix + ".erase.tmp")
                    tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                    os.replace(tmp, path)
            self._prev_hash = prev
        return removed
