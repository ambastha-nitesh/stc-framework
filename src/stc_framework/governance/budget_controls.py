"""FinOps controls layered on top of :class:`TenantBudgetTracker`.

``TenantBudgetTracker`` caps **spend**. This module adds three orthogonal
guards that together make the system resilient against runaway loops,
token-bomb inputs, and unexpected model-price changes:

1. :class:`TokenGovernor` — per-request input/output token caps, plus
   per-persona daily token quotas. Catches over-long inputs before an
   LLM call even happens.
2. :class:`BurstController` — per-workflow call counter. A single user
   query that somehow produces 500 LLM calls is almost certainly a
   logic bug or a jailbreak attempt; the controller raises and aborts
   the workflow.
3. :class:`CostCircuitBreaker` — a stateful escalation ladder for
   per-persona daily spend: ``warn → throttle → pause → halt``. Each
   band is a percentage of the persona's daily budget. Emits metrics at
   every transition so operators can react before the hard ``halt``.

All three raise explicit :class:`STCError` subclasses so the gateway /
workflow engine can translate them into HTTP responses or fallbacks.
They are in-memory and per-process; multi-process deployments should
share state via Redis-backed equivalents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from threading import RLock

from stc_framework.errors import LLMQuotaExceeded, OrchestrationError, WorkflowBudgetExhausted


class TokenLimitExceeded(LLMQuotaExceeded):
    """Per-request or per-persona token quota exceeded."""


@dataclass
class TokenGovernorConfig:
    max_input_tokens: int = 16_000
    max_output_tokens: int = 4_000
    daily_tokens_per_persona: int | None = None  # None disables the quota


class TokenGovernor:
    """Enforces input/output token caps and per-persona daily quotas.

    Call :meth:`check_input` before the LLM call; :meth:`record_usage`
    after. Quotas roll over at UTC midnight.
    """

    def __init__(self, config: TokenGovernorConfig | None = None) -> None:
        self._cfg = config or TokenGovernorConfig()
        self._usage: dict[tuple[str, date], int] = {}
        self._lock = RLock()

    def check_input(self, *, input_tokens: int, max_output_tokens: int | None = None) -> None:
        if input_tokens > self._cfg.max_input_tokens:
            raise TokenLimitExceeded(
                message=f"input tokens {input_tokens} exceed cap {self._cfg.max_input_tokens}",
                retryable=False,
            )
        output_cap = max_output_tokens if max_output_tokens is not None else self._cfg.max_output_tokens
        if output_cap > self._cfg.max_output_tokens:
            raise TokenLimitExceeded(
                message=f"requested output tokens {output_cap} exceed cap {self._cfg.max_output_tokens}",
                retryable=False,
            )

    def check_persona_quota(self, persona: str) -> None:
        if self._cfg.daily_tokens_per_persona is None:
            return
        today = datetime.now(timezone.utc).date()
        used = self._usage.get((persona, today), 0)
        if used >= self._cfg.daily_tokens_per_persona:
            raise TokenLimitExceeded(
                message=f"persona {persona!r} exceeded daily token quota {self._cfg.daily_tokens_per_persona}",
                retryable=False,
            )

    def record_usage(self, persona: str, *, tokens_used: int) -> None:
        if self._cfg.daily_tokens_per_persona is None or tokens_used <= 0:
            return
        with self._lock:
            key = (persona, datetime.now(timezone.utc).date())
            self._usage[key] = self._usage.get(key, 0) + tokens_used

    def usage_today(self, persona: str) -> int:
        today = datetime.now(timezone.utc).date()
        return self._usage.get((persona, today), 0)


# ---------------------------------------------------------------------------
# Burst controller
# ---------------------------------------------------------------------------


class BurstController:
    """Bounds the number of LLM calls a single workflow execution may make.

    Catches runaway re-plan loops in multi-Stalwart orchestration and
    jailbreak attempts that induce a self-recursive tool chain. Keyed by
    an opaque workflow id; callers pass the same id for every call in
    the workflow's lifetime.
    """

    def __init__(self, *, max_llm_calls_per_workflow: int = 20) -> None:
        self._max = max_llm_calls_per_workflow
        self._counts: dict[str, int] = {}
        self._lock = RLock()

    def record_llm_call(self, workflow_id: str) -> int:
        """Record a call and raise if the workflow would exceed its cap."""
        with self._lock:
            current = self._counts.get(workflow_id, 0) + 1
            if current > self._max:
                raise OrchestrationError(
                    message=(
                        f"workflow {workflow_id!r} made {current} LLM calls "
                        f"(cap {self._max}) — aborting as runaway loop"
                    ),
                    retryable=False,
                )
            self._counts[workflow_id] = current
            return current

    def reset(self, workflow_id: str) -> None:
        with self._lock:
            self._counts.pop(workflow_id, None)

    def count(self, workflow_id: str) -> int:
        return self._counts.get(workflow_id, 0)


# ---------------------------------------------------------------------------
# Cost circuit breaker
# ---------------------------------------------------------------------------


class CostBreakerState(str, Enum):
    NORMAL = "normal"
    WARN = "warn"
    THROTTLE = "throttle"
    PAUSE = "pause"
    HALT = "halt"


@dataclass
class CostBreakerConfig:
    daily_budget_usd: float
    warn_at_percent: float = 50.0
    throttle_at_percent: float = 75.0
    pause_at_percent: float = 90.0
    halt_at_percent: float = 100.0

    def classify(self, spent_usd: float) -> CostBreakerState:
        if self.daily_budget_usd <= 0:
            return CostBreakerState.NORMAL
        pct = (spent_usd / self.daily_budget_usd) * 100.0
        if pct >= self.halt_at_percent:
            return CostBreakerState.HALT
        if pct >= self.pause_at_percent:
            return CostBreakerState.PAUSE
        if pct >= self.throttle_at_percent:
            return CostBreakerState.THROTTLE
        if pct >= self.warn_at_percent:
            return CostBreakerState.WARN
        return CostBreakerState.NORMAL


@dataclass
class _BreakerState:
    state: CostBreakerState = CostBreakerState.NORMAL
    history: list[tuple[str, CostBreakerState]] = field(default_factory=list)


class CostCircuitBreaker:
    """Per-persona daily-spend escalation ladder.

    Does NOT track spend itself — it consumes the ``observed`` value
    that :class:`TenantBudgetTracker` already computes. Keeps the state
    machine in one place so callers don't each reinvent the ladder.
    """

    def __init__(self, config: CostBreakerConfig) -> None:
        self._cfg = config
        self._states: dict[str, _BreakerState] = {}
        self._lock = RLock()

    def observe(self, persona: str, *, spent_usd: float) -> CostBreakerState:
        new_state = self._cfg.classify(spent_usd)
        with self._lock:
            bs = self._states.setdefault(persona, _BreakerState())
            if new_state != bs.state:
                bs.history.append((datetime.now(timezone.utc).isoformat(), new_state))
                bs.state = new_state
        return new_state

    def enforce(self, persona: str, *, spent_usd: float) -> None:
        """Observe the spend and raise at the ``HALT`` band.

        ``PAUSE`` callers are expected to shed load at a higher level
        (the System / orchestrator), while ``HALT`` is hard-stop here.
        """
        state = self.observe(persona, spent_usd=spent_usd)
        if state is CostBreakerState.HALT:
            raise WorkflowBudgetExhausted(
                message=(
                    f"persona {persona!r} cost breaker HALT: "
                    f"${spent_usd:.4f} >= {self._cfg.halt_at_percent}% of "
                    f"${self._cfg.daily_budget_usd:.4f}"
                )
            )

    def state(self, persona: str) -> CostBreakerState:
        return self._states.get(persona, _BreakerState()).state


__all__ = [
    "BurstController",
    "CostBreakerConfig",
    "CostBreakerState",
    "CostCircuitBreaker",
    "TokenGovernor",
    "TokenGovernorConfig",
    "TokenLimitExceeded",
]
