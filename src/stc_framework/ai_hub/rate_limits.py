"""FR-9 rate limits + spend cap projection.

The MVP has three enforcement layers, all implemented here:

* **RPM — requests per minute, per agent.** Sliding-window counter
  across a 60-second rolling window. PRD default 60.
* **TPM — tokens per minute, per agent.** Sliding-window counter sized
  by ``input_estimate + max_tokens``. Crucially, enforcement happens on
  a **projection** (current window sum + projected tokens) *before*
  Bedrock is invoked, so a request that would push the agent over its
  limit never incurs cost (PRD §4.9.3).
* **Spend cap — monthly USD per domain.** Projected against the
  domain's month-to-date spend; rejects if the projection would exceed
  the effective cap (base cap + any active override).

All checks return early with the PRD error code on the first breach.

The in-memory implementation here is the reference. Production
deployments pair it with a Redis-backed store (existing
:class:`~stc_framework.infrastructure.redis_store.RedisStore` already
satisfies the Protocol) and a Postgres-backed spend ledger so multiple
replicas share one view (per FR-14 fail-behavior semantics: Redis is
fail-open; Postgres fail-closed).

Why a separate module from ``governance/rate_limit.py``? The existing
module implements a **requests-per-second** token bucket with tenant
ids; the PRD speaks the vocabulary of RPM / TPM with *minute* windows
keyed by *agent*. The primitives are close but not identical, and the
naming and audit outcome strings differ. Keeping this module separate
avoids retrofitting PRD vocabulary into a general-purpose tenant
limiter and lets the existing tests continue to pass unchanged.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from threading import RLock

from stc_framework.ai_hub.errors import AIHubError, AIHubErrorCode

_WINDOW_SECONDS = 60.0


class RateLimitExceeded(AIHubError):
    """Wrapper around :class:`AIHubError` with specific PRD codes."""


class SpendCapExceeded(AIHubError):
    """Projected request cost would exceed the domain's effective cap."""


@dataclass
class TPMSample:
    timestamp: float
    tokens: int


@dataclass
class _AgentState:
    rpm: deque[float] = field(default_factory=deque)
    tpm: deque[TPMSample] = field(default_factory=deque)


class TPMWindow:
    """Sliding 60-second token window per agent.

    Used by :class:`AgentRateLimiter`; exposed standalone so callers
    that just need the windowing primitive can reuse it.
    """

    def __init__(self) -> None:
        self._samples: deque[TPMSample] = deque()
        self._lock = RLock()

    def current_sum(self, *, now: float | None = None) -> int:
        current = now if now is not None else time.time()
        with self._lock:
            self._evict(current)
            return sum(s.tokens for s in self._samples)

    def record(self, tokens: int, *, now: float | None = None) -> None:
        current = now if now is not None else time.time()
        with self._lock:
            self._evict(current)
            self._samples.append(TPMSample(timestamp=current, tokens=tokens))

    def _evict(self, now: float) -> None:
        cutoff = now - _WINDOW_SECONDS
        while self._samples and self._samples[0].timestamp < cutoff:
            self._samples.popleft()


class AgentRateLimiter:
    """Combined RPM + TPM enforcement (PRD §4.9.3 pre-check phase)."""

    def __init__(self) -> None:
        self._state: dict[str, _AgentState] = {}
        self._lock = RLock()

    def _state_for(self, agent_id: str) -> _AgentState:
        with self._lock:
            s = self._state.get(agent_id)
            if s is None:
                s = _AgentState()
                self._state[agent_id] = s
            return s

    # --- RPM --------------------------------------------------------

    def check_rpm(
        self,
        agent_id: str,
        *,
        rpm_limit: int,
        now: float | None = None,
    ) -> None:
        """Raise :class:`RateLimitExceeded` (rate_limit_rpm) if this call would exceed RPM."""
        current = now if now is not None else time.time()
        state = self._state_for(agent_id)
        cutoff = current - _WINDOW_SECONDS
        while state.rpm and state.rpm[0] < cutoff:
            state.rpm.popleft()
        if len(state.rpm) >= rpm_limit:
            retry_after = max(1, int(_WINDOW_SECONDS - (current - state.rpm[0]) + 1))
            raise RateLimitExceeded(
                code=AIHubErrorCode.RATE_LIMIT_RPM,
                message=(f"agent {agent_id!r} exceeded RPM limit ({rpm_limit}); " f"retry after {retry_after}s"),
                extra={"retry_after_seconds": retry_after},
            )

    def record_request(self, agent_id: str, *, now: float | None = None) -> None:
        """Record a request hit; pair with :meth:`check_rpm`."""
        current = now if now is not None else time.time()
        state = self._state_for(agent_id)
        state.rpm.append(current)

    # --- TPM --------------------------------------------------------

    def check_tpm_projection(
        self,
        agent_id: str,
        *,
        projected_tokens: int,
        tpm_limit: int,
        now: float | None = None,
    ) -> None:
        """Raise if ``current_window_sum + projected_tokens > tpm_limit``.

        PRD §4.9.3: enforcement happens on the *projection* before
        Bedrock is invoked.
        """
        if projected_tokens < 0:
            raise ValueError("projected_tokens must be >= 0")
        current = now if now is not None else time.time()
        state = self._state_for(agent_id)
        # Evict stale samples.
        cutoff = current - _WINDOW_SECONDS
        while state.tpm and state.tpm[0].timestamp < cutoff:
            state.tpm.popleft()
        window_sum = sum(s.tokens for s in state.tpm)
        if window_sum + projected_tokens > tpm_limit:
            retry_after = 60
            raise RateLimitExceeded(
                code=AIHubErrorCode.RATE_LIMIT_TPM,
                message=(
                    f"agent {agent_id!r} projected TPM ({window_sum + projected_tokens}) "
                    f"exceeds limit ({tpm_limit})"
                ),
                extra={"retry_after_seconds": retry_after},
            )

    def record_tokens(
        self,
        agent_id: str,
        *,
        tokens: int,
        now: float | None = None,
    ) -> None:
        """Record actual token consumption after Bedrock returns.

        Used in the PRD's post-update phase to overwrite the projection
        contribution with real tokens.
        """
        if tokens <= 0:
            return
        current = now if now is not None else time.time()
        state = self._state_for(agent_id)
        state.tpm.append(TPMSample(timestamp=current, tokens=tokens))

    # --- introspection helpers --------------------------------------

    def rpm_usage(self, agent_id: str, *, now: float | None = None) -> int:
        current = now if now is not None else time.time()
        state = self._state_for(agent_id)
        cutoff = current - _WINDOW_SECONDS
        return sum(1 for t in state.rpm if t >= cutoff)

    def tpm_usage(self, agent_id: str, *, now: float | None = None) -> int:
        current = now if now is not None else time.time()
        state = self._state_for(agent_id)
        cutoff = current - _WINDOW_SECONDS
        return sum(s.tokens for s in state.tpm if s.timestamp >= cutoff)


# ---------------------------------------------------------------------
# Spend cap projector
# ---------------------------------------------------------------------


@dataclass
class SpendCapState:
    """Snapshot of a domain's spend accounting."""

    monthly_cap_usd: float
    month_to_date_usd: float = 0.0
    override_additional_usd: float = 0.0
    override_expires_epoch: float | None = None

    def effective_cap(self, *, now: float | None = None) -> float:
        current = now if now is not None else time.time()
        if self.override_expires_epoch is not None and current < self.override_expires_epoch:
            return self.monthly_cap_usd + self.override_additional_usd
        return self.monthly_cap_usd


class SpendCapProjector:
    """In-memory reference implementation of FR-9 spend-cap projection.

    Production deployments swap for a Postgres-backed ledger. The
    interface is intentionally narrow (``snapshot``, ``assert_within``,
    ``record_spend``, ``grant_override``) so the swap is mechanical.
    """

    def __init__(self) -> None:
        self._states: dict[str, SpendCapState] = {}
        self._lock = RLock()

    def register_domain(self, domain_id: str, *, monthly_cap_usd: float) -> None:
        with self._lock:
            self._states[domain_id] = SpendCapState(monthly_cap_usd=monthly_cap_usd)

    def snapshot(self, domain_id: str) -> SpendCapState:
        with self._lock:
            state = self._states.get(domain_id)
            if state is None:
                raise KeyError(f"unknown domain: {domain_id!r}")
            # Return a copy so callers can't mutate internal state.
            return SpendCapState(
                monthly_cap_usd=state.monthly_cap_usd,
                month_to_date_usd=state.month_to_date_usd,
                override_additional_usd=state.override_additional_usd,
                override_expires_epoch=state.override_expires_epoch,
            )

    def assert_within(
        self,
        domain_id: str,
        *,
        projected_cost_usd: float,
        now: float | None = None,
    ) -> None:
        """Raise :class:`SpendCapExceeded` if MTD + projected > effective cap."""
        if projected_cost_usd < 0:
            raise ValueError("projected_cost_usd must be >= 0")
        with self._lock:
            state = self._states.get(domain_id)
            if state is None:
                raise KeyError(f"unknown domain: {domain_id!r}")
            cap = state.effective_cap(now=now)
            if state.month_to_date_usd + projected_cost_usd > cap:
                raise SpendCapExceeded(
                    code=AIHubErrorCode.SPEND_CAP_EXCEEDED,
                    message=(
                        f"domain {domain_id!r} projected spend "
                        f"(${state.month_to_date_usd + projected_cost_usd:.4f}) "
                        f"exceeds effective cap (${cap:.4f})"
                    ),
                    extra={"effective_cap_usd": cap, "month_to_date_usd": state.month_to_date_usd},
                )

    def record_spend(self, domain_id: str, *, actual_cost_usd: float) -> float:
        """Add actual cost to month-to-date. Returns new MTD value."""
        if actual_cost_usd <= 0:
            return self.snapshot(domain_id).month_to_date_usd
        with self._lock:
            state = self._states.get(domain_id)
            if state is None:
                raise KeyError(f"unknown domain: {domain_id!r}")
            state.month_to_date_usd += actual_cost_usd
            return state.month_to_date_usd

    def grant_override(
        self,
        domain_id: str,
        *,
        additional_usd: float,
        expires_epoch: float,
    ) -> None:
        with self._lock:
            state = self._states.get(domain_id)
            if state is None:
                raise KeyError(f"unknown domain: {domain_id!r}")
            state.override_additional_usd = additional_usd
            state.override_expires_epoch = expires_epoch


__all__ = [
    "AgentRateLimiter",
    "RateLimitExceeded",
    "SpendCapExceeded",
    "SpendCapProjector",
    "SpendCapState",
    "TPMSample",
    "TPMWindow",
]
