"""Base types for Critic validators.

What a validator is
-------------------
A validator is an async callable that inspects a request or response
and emits a :class:`GuardrailResult`. The Critic's :class:`RailRunner`
looks up validators by ``rail_name`` (a class attribute, not an init
arg) and runs them in parallel under a bulkhead + timeout.

The ``rail_name`` class attribute is the **stable identifier** that
the declarative spec references under ``critic.guardrails.*_rails[*].name``.
It MUST NOT be a constructor argument — that would let two instances
claim to be the same rail, and would decouple the spec's identifier
from the class's identity. Renaming the class attribute is a
spec-breaking change.

What to set on ``GuardrailResult``
----------------------------------
- ``passed`` — True if the response is acceptable.
- ``severity`` — ``"critical"`` causes the Critic to block; ``"high"``
  causes a warn; ``"low"`` is informational only.
- ``action`` — the recommended disposition (``"pass"``, ``"warn"``,
  ``"block"``, ``"redact"``). Advisory; the Critic aggregates and
  picks the final action based on severity.
- ``details`` — a short human-readable explanation. Goes into audit
  but not into the caller-facing response (the caller only sees rail
  names).
- ``evidence`` — a structured dict for auditor review. Put matched
  pattern names, numeric values, grounding scores here. Do NOT put
  raw user content (that would leak PII into audit).

Adding a new validator
----------------------
See :file:`CONTRIBUTING.md` → Recipe 1 (Add a Critic rail) for the
full checklist. The short version:

1. Subclass :class:`Validator`, set ``rail_name`` and ``severity`` as
   class attributes.
2. Implement ``async def avalidate(self, ctx)``.
3. Register the instance in :class:`stc_framework.critic.critic.Critic`
   under the same string key as the spec's ``name:`` field.
4. Declare the rail in the spec YAML.
5. Write a regression test under ``tests/unit/test_<name>_validator.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ValidationContext:
    """Everything a validator may need to see."""

    query: str
    response: str
    context: str = ""
    source_chunks: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str = ""
    data_tier: str = "public"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GuardrailResult:
    rail_name: str
    passed: bool
    severity: str = "low"  # critical | high | medium | low
    action: str = "pass"  # pass | warn | block | redact
    details: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_utc_now)


@dataclass
class GovernanceVerdict:
    trace_id: str
    passed: bool
    results: list[GuardrailResult]
    action: str  # pass | warn | block | escalate
    escalation_level: str | None = None
    timestamp: str = field(default_factory=_utc_now)


@runtime_checkable
class Validator(Protocol):
    """Protocol implemented by every Critic validator."""

    rail_name: str
    severity: str

    async def avalidate(self, ctx: ValidationContext) -> GuardrailResult: ...
