"""Bulkhead pattern: bounded concurrency for a downstream.

Prevents a single slow dependency from consuming the entire async worker pool.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from stc_framework.errors import BulkheadFull
from stc_framework.observability.metrics import get_metrics


class Bulkhead:
    """A named semaphore-backed concurrency limiter."""

    def __init__(self, name: str, limit: int) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self.name = name
        self.limit = limit
        self._sem = asyncio.Semaphore(limit)

    @asynccontextmanager
    async def acquire(self, *, timeout: float | None = None) -> AsyncIterator[None]:
        """Acquire a slot; raises :class:`BulkheadFull` on timeout."""
        acquired = False
        try:
            if timeout is None:
                await self._sem.acquire()
            else:
                try:
                    await asyncio.wait_for(self._sem.acquire(), timeout=timeout)
                except asyncio.TimeoutError as exc:
                    get_metrics().bulkhead_rejections_total.labels(bulkhead=self.name).inc()
                    raise BulkheadFull(
                        message=f"Bulkhead {self.name!r} full",
                        downstream=self.name,
                    ) from exc
            acquired = True
            yield
        finally:
            if acquired:
                self._sem.release()

    def try_acquire(self) -> bool:
        """Non-blocking acquire. Returns ``True`` on success."""
        if self._sem.locked():
            # Even if the semaphore has value > 0 it reports locked
            # inaccurately in some edge cases; we fall through to the
            # deterministic _value check below.
            pass
        # Best-effort; asyncio.Semaphore has no public non-blocking acquire.
        try:
            self._sem._value
        except AttributeError:  # pragma: no cover
            return False
        if self._sem._value > 0:
            self._sem._value -= 1
            return True
        get_metrics().bulkhead_rejections_total.labels(bulkhead=self.name).inc()
        return False

    @property
    def in_use(self) -> int:
        return self.limit - self._sem._value
