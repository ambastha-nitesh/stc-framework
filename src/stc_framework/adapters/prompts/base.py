"""Prompt registry protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class PromptRecord:
    name: str
    version: str
    content: str
    active: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class PromptRegistry(Protocol):
    """Versioned prompt storage. Multiple versions can exist; one is active."""

    async def get(self, name: str, version: str | None = None) -> PromptRecord: ...

    async def register(self, record: PromptRecord) -> None: ...

    async def set_active(self, name: str, version: str) -> None: ...

    async def list_versions(self, name: str) -> list[PromptRecord]: ...

    async def healthcheck(self) -> bool: ...
