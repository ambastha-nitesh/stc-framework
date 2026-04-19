"""In-memory Lightning recorder used as the zero-install default."""

from __future__ import annotations

from collections import deque
from threading import RLock

from stc_framework.adapters.lightning.base import LightningRecorder, Transition


class InMemoryRecorder(LightningRecorder):
    """Ring-buffered transition recorder."""

    def __init__(self, capacity: int = 10_000) -> None:
        self._buffer: deque[Transition] = deque(maxlen=capacity)
        self._lock = RLock()

    async def record(self, transition: Transition) -> None:
        with self._lock:
            self._buffer.append(transition)

    async def snapshot(self, *, limit: int | None = None) -> list[Transition]:
        with self._lock:
            data = list(self._buffer)
        if limit is None:
            return data
        return data[-limit:]

    async def healthcheck(self) -> bool:
        return True
