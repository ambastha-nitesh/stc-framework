"""FR-3 / FR-5 filter-chain orchestrator.

Implements the exact semantics the PRD requires on the input and
output sides:

* **Sequential execution** in a fixed filter order. The first non-ALLOW
  short-circuits the chain — no later filter runs.
* **Per-filter 300 ms deadline** via :func:`asyncio.wait_for`. A
  timeout produces an ``ERROR`` verdict.
* **Fail-closed** on timeout OR exception. The orchestrator raises
  :class:`FilterChainError` with the PRD code (``guardrail_timeout`` or
  ``guardrail_error``) so the caller knows to return 503 — never to
  fall through to Bedrock.
* **BLOCK** from any filter raises :class:`FilterChainBlocked` with the
  PRD code ``guardrail_input_block`` / ``guardrail_output_block`` and
  the blocking filter's name — maps to HTTP 422 (input) or 502 (output)
  per Appendix A.
* Every verdict (including ALLOWs that ran before the short-circuit) is
  collected so :func:`compose_audit_record` can write ``filter_verdicts``
  matching PRD §4.13.4.

The orchestrator does NOT invoke a filter concurrently with another.
Parallelisation is an explicit v1.1 tracked item (PRD §4.3.1) and
requires a design review because the PRD's fail-closed contract is
simpler to reason about sequentially.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from stc_framework.ai_hub.errors import AIHubError, AIHubErrorCode

# Per-filter deadline (PRD §4.3.4 + §4.5). Exceeding this on any filter
# trips the fail-closed path.
DEFAULT_FILTER_DEADLINE_MS = 300


class FilterDirection(str, Enum):
    """Whether this filter runs on the prompt side or the completion side."""

    INPUT = "input"
    OUTPUT = "output"


class FilterOutcome(str, Enum):
    """Three outcomes a filter may report (PRD §4.3.2)."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    ERROR = "ERROR"


@dataclass
class FilterInput:
    """Payload delivered to a filter (PRD §4.3.2 ``FilterInput``)."""

    request_id: str
    domain_id: str
    agent_id: str
    payload: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class FilterVerdict:
    """Result a filter returns (PRD §4.3.2 ``FilterVerdict``)."""

    filter_name: str
    direction: FilterDirection
    outcome: FilterOutcome
    reason_code: str | None = None
    detected_categories: list[str] | None = None
    latency_ms: int = 0
    raw_vendor_response_ref: str | None = None

    def as_audit_entry(self) -> dict[str, Any]:
        """Serialise for the audit record's ``filter_verdicts`` array."""
        return {
            "filter_name": self.filter_name,
            "direction": self.direction.value,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "detected_categories": self.detected_categories,
            "latency_ms": self.latency_ms,
            "raw_vendor_response_ref": self.raw_vendor_response_ref,
        }


@runtime_checkable
class Filter(Protocol):
    """Async filter protocol (PRD §4.3.2)."""

    name: str
    direction: FilterDirection

    async def run(self, input: FilterInput, deadline_ms: int) -> FilterVerdict: ...


class FilterChainError(AIHubError):
    """Raised when a filter times out or errors out.

    Carries the PRD code ``guardrail_timeout`` or ``guardrail_error``
    and the name of the filter that failed. The orchestrator also
    stores the partial :class:`FilterVerdict` list on this exception so
    audit record composition can record the ALLOWs that ran before the
    failure.
    """

    def __init__(
        self,
        code: AIHubErrorCode,
        filter_name: str,
        verdicts: list[FilterVerdict],
        message: str = "",
    ) -> None:
        super().__init__(
            code=code,
            message=message or code.value,
            filter_name=filter_name,
        )
        self.verdicts = verdicts


class FilterChainBlocked(AIHubError):
    """Raised when any filter returns BLOCK."""

    def __init__(
        self,
        direction: FilterDirection,
        filter_name: str,
        verdicts: list[FilterVerdict],
        reason_code: str | None = None,
    ) -> None:
        code = (
            AIHubErrorCode.GUARDRAIL_INPUT_BLOCK
            if direction is FilterDirection.INPUT
            else AIHubErrorCode.GUARDRAIL_OUTPUT_BLOCK
        )
        message = f"{filter_name} blocked the {'prompt' if direction is FilterDirection.INPUT else 'completion'}" + (
            f"; reason={reason_code}" if reason_code else ""
        )
        super().__init__(
            code=code,
            message=message,
            filter_name=filter_name,
            extra={"reason_code": reason_code} if reason_code else {},
        )
        self.direction = direction
        self.verdicts = verdicts
        self.reason_code = reason_code


class FilterChainOrchestrator:
    """Runs a list of filters sequentially with per-filter deadlines.

    Callers instantiate one orchestrator per chain (``input`` or
    ``output``) and call :meth:`run`. The orchestrator is stateless
    across calls so a single instance may be reused across requests.
    """

    def __init__(
        self,
        filters: Sequence[Filter],
        *,
        direction: FilterDirection,
        deadline_ms: int = DEFAULT_FILTER_DEADLINE_MS,
    ) -> None:
        # Validate upfront that every filter's declared direction
        # matches the chain's direction — a stray output filter in an
        # input chain silently running on the prompt would be very hard
        # to debug, so we fail at construction time.
        for f in filters:
            if f.direction is not direction:
                raise ValueError(
                    f"filter {f.name!r} declares direction {f.direction.value!r} but chain is {direction.value!r}"
                )
        self._filters = tuple(filters)
        self._direction = direction
        self._deadline_ms = deadline_ms

    @property
    def direction(self) -> FilterDirection:
        return self._direction

    @property
    def filter_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self._filters)

    async def run(self, input: FilterInput) -> list[FilterVerdict]:
        """Execute the chain. Return the list of verdicts on ALLOW.

        On BLOCK raises :class:`FilterChainBlocked`. On timeout or any
        exception raises :class:`FilterChainError`. In both cases the
        ``verdicts`` attribute on the exception carries every verdict
        that ran, in order, so the caller can still audit the chain's
        state at the point of failure.
        """
        verdicts: list[FilterVerdict] = []
        deadline_seconds = self._deadline_ms / 1000.0

        for f in self._filters:
            started = time.perf_counter()
            try:
                verdict = await asyncio.wait_for(
                    f.run(input, self._deadline_ms),
                    timeout=deadline_seconds,
                )
            except asyncio.TimeoutError as exc:
                elapsed = int((time.perf_counter() - started) * 1000)
                verdicts.append(
                    FilterVerdict(
                        filter_name=f.name,
                        direction=self._direction,
                        outcome=FilterOutcome.ERROR,
                        reason_code="timeout",
                        latency_ms=elapsed,
                    )
                )
                raise FilterChainError(
                    code=AIHubErrorCode.GUARDRAIL_TIMEOUT,
                    filter_name=f.name,
                    verdicts=verdicts,
                    message=f"{f.name} exceeded {self._deadline_ms}ms deadline",
                ) from exc
            except Exception as exc:
                elapsed = int((time.perf_counter() - started) * 1000)
                verdicts.append(
                    FilterVerdict(
                        filter_name=f.name,
                        direction=self._direction,
                        outcome=FilterOutcome.ERROR,
                        reason_code=type(exc).__name__,
                        latency_ms=elapsed,
                    )
                )
                raise FilterChainError(
                    code=AIHubErrorCode.GUARDRAIL_ERROR,
                    filter_name=f.name,
                    verdicts=verdicts,
                    message=f"{f.name} raised {type(exc).__name__}: {exc}",
                ) from exc

            if not isinstance(verdict.latency_ms, int) or verdict.latency_ms == 0:
                # Filters that forgot to populate latency are stamped by
                # the orchestrator so audit records are never missing it.
                verdict.latency_ms = int((time.perf_counter() - started) * 1000)
            verdicts.append(verdict)

            if verdict.outcome is FilterOutcome.BLOCK:
                raise FilterChainBlocked(
                    direction=self._direction,
                    filter_name=f.name,
                    verdicts=verdicts,
                    reason_code=verdict.reason_code,
                )
            if verdict.outcome is FilterOutcome.ERROR:
                raise FilterChainError(
                    code=AIHubErrorCode.GUARDRAIL_ERROR,
                    filter_name=f.name,
                    verdicts=verdicts,
                    message=f"{f.name} self-reported ERROR",
                )

        return verdicts


__all__ = [
    "DEFAULT_FILTER_DEADLINE_MS",
    "Filter",
    "FilterChainBlocked",
    "FilterChainError",
    "FilterChainOrchestrator",
    "FilterDirection",
    "FilterInput",
    "FilterOutcome",
    "FilterVerdict",
]
