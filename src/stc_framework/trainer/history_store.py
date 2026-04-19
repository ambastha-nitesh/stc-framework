"""Performance history persistence.

Two backends:
- :class:`InMemoryHistoryStore` — per-process ring buffer.
- :class:`SQLiteHistoryStore` — durable, shareable across worker processes
  via a single SQLite file. Suitable for moderate scale; for very large
  deployments plug in a custom store over Postgres/ClickHouse.
"""

from __future__ import annotations

import sqlite3
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Protocol, runtime_checkable


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HistoryRecord:
    trace_id: str = ""
    model_used: str = ""
    accuracy: float = 0.0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    hallucination_detected: bool = False
    data_tier: str = "public"
    timestamp: str = field(default_factory=_iso)
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class HistoryStore(Protocol):
    def add(self, record: HistoryRecord) -> None: ...
    def recent(self, *, since: datetime | None = None, limit: int | None = None) -> list[HistoryRecord]: ...
    def all(self, *, limit: int | None = None) -> list[HistoryRecord]: ...

    def erase_tenant(self, tenant_id: str) -> int:
        """Delete every record whose metadata carries ``tenant_id``."""
        return 0

    def prune_before(self, cutoff: datetime) -> int:
        """Delete records older than ``cutoff``. Returns count removed."""
        return 0


class InMemoryHistoryStore(HistoryStore):
    def __init__(self, capacity: int = 10_000) -> None:
        self._buffer: deque[HistoryRecord] = deque(maxlen=capacity)
        self._lock = RLock()

    def add(self, record: HistoryRecord) -> None:
        with self._lock:
            self._buffer.append(record)

    def recent(self, *, since: datetime | None = None, limit: int | None = None) -> list[HistoryRecord]:
        with self._lock:
            data = list(self._buffer)
        if since is not None:
            data = [r for r in data if datetime.fromisoformat(r.timestamp.replace("Z", "+00:00")) >= since]
        if limit is not None:
            data = data[-limit:]
        return data

    def all(self, *, limit: int | None = None) -> list[HistoryRecord]:
        return self.recent(limit=limit)

    def erase_tenant(self, tenant_id: str) -> int:
        with self._lock:
            before = len(self._buffer)
            self._buffer = deque(
                (r for r in self._buffer if r.metadata.get("tenant_id") != tenant_id),
                maxlen=self._buffer.maxlen,
            )
            return before - len(self._buffer)

    def prune_before(self, cutoff: datetime) -> int:
        cutoff_iso = cutoff.isoformat()
        with self._lock:
            before = len(self._buffer)
            self._buffer = deque(
                (r for r in self._buffer if r.timestamp >= cutoff_iso),
                maxlen=self._buffer.maxlen,
            )
            return before - len(self._buffer)


class SQLiteHistoryStore(HistoryStore):
    """Thread-safe SQLite-backed history store."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trace_id TEXT,
        model_used TEXT,
        accuracy REAL,
        cost_usd REAL,
        latency_ms REAL,
        hallucination_detected INTEGER,
        data_tier TEXT,
        timestamp TEXT,
        metadata TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_history_timestamp ON history(timestamp);
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False, isolation_level=None)
        self._conn.executescript(self._SCHEMA)

    def add(self, record: HistoryRecord) -> None:
        import json

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO history
                    (trace_id, model_used, accuracy, cost_usd, latency_ms,
                     hallucination_detected, data_tier, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.trace_id,
                    record.model_used,
                    record.accuracy,
                    record.cost_usd,
                    record.latency_ms,
                    int(record.hallucination_detected),
                    record.data_tier,
                    record.timestamp,
                    json.dumps(record.metadata),
                ),
            )

    def _rows_to_records(self, rows: list[tuple[Any, ...]]) -> list[HistoryRecord]:
        import json

        out: list[HistoryRecord] = []
        for row in rows:
            (
                _id,
                trace_id,
                model_used,
                accuracy,
                cost_usd,
                latency_ms,
                hallucination_detected,
                data_tier,
                timestamp,
                metadata,
            ) = row
            out.append(
                HistoryRecord(
                    trace_id=trace_id or "",
                    model_used=model_used or "",
                    accuracy=accuracy or 0.0,
                    cost_usd=cost_usd or 0.0,
                    latency_ms=latency_ms or 0.0,
                    hallucination_detected=bool(hallucination_detected),
                    data_tier=data_tier or "public",
                    timestamp=timestamp or "",
                    metadata=json.loads(metadata or "{}"),
                )
            )
        return out

    def recent(self, *, since: datetime | None = None, limit: int | None = None) -> list[HistoryRecord]:
        with self._lock:
            query = "SELECT * FROM history"
            params: list[Any] = []
            if since is not None:
                query += " WHERE timestamp >= ?"
                params.append(since.isoformat())
            query += " ORDER BY id DESC"
            if limit:
                query += " LIMIT ?"
                params.append(limit)
            rows = self._conn.execute(query, params).fetchall()
        return self._rows_to_records(rows)[::-1]

    def all(self, *, limit: int | None = None) -> list[HistoryRecord]:
        return self.recent(limit=limit)

    def erase_tenant(self, tenant_id: str) -> int:
        # The tenant_id lives inside the JSON metadata column. LIKE match
        # is not ideal but is parameterized and sufficient for the default
        # backend; production deployments should use a schema with a
        # dedicated tenant column.
        pattern = f'%"tenant_id": "{tenant_id}"%'
        with self._lock:
            cursor = self._conn.execute("DELETE FROM history WHERE metadata LIKE ?", (pattern,))
            return cursor.rowcount or 0

    def prune_before(self, cutoff: datetime) -> int:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM history WHERE timestamp < ?", (cutoff.isoformat(),))
            return cursor.rowcount or 0


# ---------------------------------------------------------------------------
# Trace → HistoryRecord with data minimization
# ---------------------------------------------------------------------------


_COPIED_FIELDS = {
    "trace_id",
    "model_used",
    "accuracy",
    "cost_usd",
    "latency_ms",
    "hallucination_detected",
    "data_tier",
}

# Fields we refuse to copy into ``HistoryRecord.metadata`` — they are
# either raw user content (query/response/context) or retrieved chunks
# that could contain PII. Dropping them at the Trainer boundary ensures
# the history store does not become a secondary PII reservoir.
_PII_RISK_FIELDS = {
    "query",
    "response",
    "context",
    "retrieved_chunks",
    "retrieval_scores",
    "citations",
    "metadata",
    "error",
}


def record_from_trace(trace: dict[str, Any]) -> HistoryRecord:
    """Build a :class:`HistoryRecord` without raw user content.

    Tenant id is promoted to metadata so erasure and DSAR can find the
    row; everything else is filtered through ``_PII_RISK_FIELDS`` to
    uphold data-minimization obligations (GDPR Art. 5(1)(c)).
    """
    safe_metadata: dict[str, Any] = {}
    for k, v in trace.items():
        if k in _COPIED_FIELDS or k in _PII_RISK_FIELDS:
            continue
        safe_metadata[k] = v
    if "tenant_id" in trace:
        safe_metadata["tenant_id"] = trace["tenant_id"]

    return HistoryRecord(
        trace_id=trace.get("trace_id", ""),
        model_used=trace.get("model_used", ""),
        accuracy=float(trace.get("accuracy", 0.0) or 0.0),
        cost_usd=float(trace.get("cost_usd", 0.0) or 0.0),
        latency_ms=float(trace.get("latency_ms", 0.0) or 0.0),
        hallucination_detected=bool(trace.get("hallucination_detected", False)),
        data_tier=trace.get("data_tier", "public") or "public",
        metadata=safe_metadata,
    )
