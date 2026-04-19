"""In-flight request counter used for graceful shutdown and saturation signals.

Tracks the number of queries currently being processed. Exposed via the
``stc_inflight_requests`` Prometheus gauge and consulted by
:meth:`STCSystem.astop` so shutdown can wait for pending work.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from threading import RLock
from typing import AsyncIterator

from stc_framework.observability.metrics import get_metrics


class InflightTracker:
    def __init__(self) -> None:
        self._count = 0
        self._lock = RLock()
        self._event = asyncio.Event()
        self._event.set()  # start signalled — nothing in flight

    @property
    def current(self) -> int:
        with self._lock:
            return self._count

    @asynccontextmanager
    async def track(self) -> AsyncIterator[None]:
        self._increment()
        try:
            yield
        finally:
            self._decrement()

    def _increment(self) -> None:
        with self._lock:
            self._count += 1
            if self._count == 1:
                # Transitioned from idle → busy; clear the drain event.
                try:
                    self._event.clear()
                except Exception:  # pragma: no cover
                    pass
            get_metrics().inflight_requests.set(self._count)

    def _decrement(self) -> None:
        with self._lock:
            self._count = max(0, self._count - 1)
            if self._count == 0:
                try:
                    self._event.set()
                except Exception:  # pragma: no cover
                    pass
            get_metrics().inflight_requests.set(self._count)

    async def wait_idle(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds for in-flight work to finish.

        Returns ``True`` if the tracker became idle, ``False`` on timeout.
        """
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
