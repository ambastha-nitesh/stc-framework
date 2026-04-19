"""Per-tenant RPS rate limiter.

Budget caps spend; this caps *requests* per second. Without it, a tenant
whose cheap queries consume budget slowly can still flood the system
and starve other tenants of resources.

Implementation: classic token bucket, one bucket per tenant, bounded by
a ring-buffer cap so a million-tenant deployment does not blow the heap.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import RLock


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class RateLimitExceeded(Exception):
    def __init__(self, tenant_id: str, rate: float) -> None:
        super().__init__(
            f"tenant {tenant_id!r} exceeded rate limit ({rate:.2f} rps)"
        )
        self.tenant_id = tenant_id
        self.rate = rate


class TenantRateLimiter:
    """Token-bucket rate limiter keyed by tenant id.

    Parameters
    ----------
    rps:
        Sustained requests per second per tenant. ``<= 0`` disables the
        limiter (``acquire`` always succeeds).
    burst:
        Maximum burst size (bucket capacity). Defaults to ``rps`` so the
        limiter behaves approximately like a moving average over one
        second.
    max_tenants:
        Hard cap on tracked buckets; the oldest bucket is evicted when
        exceeded. Prevents memory blow-up in an unbounded-tenant
        deployment.

    """

    def __init__(
        self,
        *,
        rps: float = 0.0,
        burst: float | None = None,
        max_tenants: int = 100_000,
    ) -> None:
        self.rps = rps
        self.burst = burst if burst is not None else max(rps, 1.0)
        self._buckets: dict[str, _Bucket] = {}
        self._lock = RLock()
        self._max_tenants = max_tenants

    def acquire(self, tenant_id: str | None, *, cost: float = 1.0) -> None:
        """Consume ``cost`` tokens; raise :class:`RateLimitExceeded` on failure."""
        if self.rps <= 0 or not tenant_id:
            return
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(tenant_id)
            if bucket is None:
                bucket = _Bucket(tokens=self.burst, last_refill=now)
                self._buckets[tenant_id] = bucket
                # Evict oldest if over capacity.
                if len(self._buckets) > self._max_tenants:
                    oldest = min(
                        self._buckets, key=lambda k: self._buckets[k].last_refill
                    )
                    self._buckets.pop(oldest, None)
            # Refill.
            elapsed = now - bucket.last_refill
            bucket.tokens = min(self.burst, bucket.tokens + elapsed * self.rps)
            bucket.last_refill = now

            if bucket.tokens < cost:
                raise RateLimitExceeded(tenant_id, self.rps)
            bucket.tokens -= cost

    def erase_tenant(self, tenant_id: str) -> int:
        with self._lock:
            return 1 if self._buckets.pop(tenant_id, None) else 0

    def snapshot(self, tenant_id: str) -> dict[str, float]:
        with self._lock:
            bucket = self._buckets.get(tenant_id)
            if bucket is None:
                return {"tokens": self.burst, "rps": self.rps}
            return {"tokens": bucket.tokens, "rps": self.rps}
