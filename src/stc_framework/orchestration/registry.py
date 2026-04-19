"""StalwartRegistry — capability-based Stalwart lookup.

A workflow's planner emits abstract tasks with capability tags
(``retrieval``, ``summarisation``, ``table_extraction`` etc.). The
registry maps those tags to concrete registered Stalwarts.

Registration stores callable dispatchers so the orchestrator can
invoke a matched Stalwart without knowing its implementation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

DispatchFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class StalwartRegistration:
    stalwart_id: str
    capabilities: tuple[str, ...] = ()
    dispatch: DispatchFn | None = None
    cost_weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


class StalwartRegistry:
    """In-memory registry of known Stalwarts keyed by id."""

    def __init__(self) -> None:
        self._entries: dict[str, StalwartRegistration] = {}

    def register(self, entry: StalwartRegistration) -> None:
        self._entries[entry.stalwart_id] = entry

    def get(self, stalwart_id: str) -> StalwartRegistration | None:
        return self._entries.get(stalwart_id)

    def match(self, capability: str) -> list[StalwartRegistration]:
        return [e for e in self._entries.values() if capability in e.capabilities]

    def pick(self, capability: str) -> StalwartRegistration | None:
        """Pick the lowest-cost capability match."""
        matches = self.match(capability)
        if not matches:
            return None
        return min(matches, key=lambda e: e.cost_weight)

    def list_all(self) -> list[StalwartRegistration]:
        return list(self._entries.values())


__all__ = ["DispatchFn", "StalwartRegistration", "StalwartRegistry"]
