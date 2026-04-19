"""TTL (time-to-live) arithmetic helpers.

Used by session state, data catalog freshness checks, retention sweeps,
and idempotency caches. Kept here to ensure everyone agrees on the
"epoch seconds vs monotonic vs ISO-8601" convention.

Convention: epoch seconds (float) for arithmetic; ISO-8601 UTC for audit
serialisation. Callers who need monotonic behaviour should use
``time.monotonic`` directly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone


def now_epoch() -> float:
    """Current wall-clock time in epoch seconds."""
    return time.time()


def now_iso() -> str:
    """Current wall-clock time as an ISO-8601 UTC string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TTL:
    """A deadline in epoch seconds.

    Not a timer — just a number that lets callers ask "is this expired?"
    and "how many seconds remain?".
    """

    expires_at: float

    @classmethod
    def from_seconds(cls, seconds: float) -> TTL:
        return cls(expires_at=now_epoch() + seconds)

    def is_expired(self, *, now: float | None = None) -> bool:
        return (now if now is not None else now_epoch()) >= self.expires_at

    def remaining(self, *, now: float | None = None) -> float:
        return max(0.0, self.expires_at - (now if now is not None else now_epoch()))

    def refresh(self, seconds: float) -> TTL:
        """Return a new TTL extended ``seconds`` from now. Immutable-style."""
        return TTL(expires_at=now_epoch() + seconds)


def is_stale(updated_at_iso: str, *, max_age_seconds: float) -> bool:
    """Return True if ``updated_at_iso`` is older than ``max_age_seconds``."""
    try:
        ts = datetime.fromisoformat(updated_at_iso.replace("Z", "+00:00"))
    except ValueError:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return age > max_age_seconds


__all__ = ["TTL", "is_stale", "now_epoch", "now_iso"]
