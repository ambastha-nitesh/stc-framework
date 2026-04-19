"""Lightning recorder protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Transition:
    """Single RL transition tuple for Agent Lightning."""

    trace_id: str
    state: dict[str, Any]
    action: dict[str, Any]
    reward: float
    signals: list[dict[str, Any]] = field(default_factory=list)
    timestamp: str = ""


@runtime_checkable
class LightningRecorder(Protocol):
    """Records transitions for RL optimization."""

    async def record(self, transition: Transition) -> None: ...

    async def snapshot(self, *, limit: int | None = None) -> list[Transition]: ...

    async def healthcheck(self) -> bool: ...
