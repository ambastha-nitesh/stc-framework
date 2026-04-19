"""External guardrail adapter protocols."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class GuardrailCheck:
    """Result of an external guardrail invocation."""

    name: str
    passed: bool
    details: str = ""
    severity: str = "medium"
    evidence: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ExternalGuardrailClient(Protocol):
    """Protocol for wrapping an external guardrail service (NeMo, Guardrails AI)."""

    async def check(self, rail_name: str, text: str, **kwargs: Any) -> GuardrailCheck: ...

    async def healthcheck(self) -> bool: ...
