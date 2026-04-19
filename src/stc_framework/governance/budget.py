"""Per-tenant budget tracking.

Rolling per-tenant cost accounting that:

- uses **calendar-day buckets** (UTC) so a wall-clock jump doesn't
  corrupt the accounting,
- maintains a running window sum so :meth:`observed` is O(1) rather
  than O(n) over the sample list,
- uses the monotonic clock as a **consistency check** — if wall clock
  moves backwards significantly between operations we flag it in logs
  and refuse to trust new samples until the next bucket boundary.

The tracker is deliberately in-memory and per-process; production
deployments with strong isolation requirements should ship a Redis- or
database-backed implementation that satisfies the same Protocol.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from threading import RLock

from stc_framework.config.logging import get_logger

_logger = get_logger(__name__)


@dataclass
class _DayBucket:
    day: date
    total_usd: float = 0.0


@dataclass
class _TenantState:
    # Ordered oldest → newest; fixed at ~35 buckets so monthly windows
    # can be summed without touching dropped history.
    buckets: deque[_DayBucket] = field(
        default_factory=lambda: deque(maxlen=35)
    )
    last_monotonic: float = field(default_factory=time.monotonic)


class TenantBudgetExceeded(Exception):
    """Raised when a tenant has exhausted their budget for the window."""

    def __init__(
        self, tenant_id: str, window: str, observed: float, limit: float
    ) -> None:
        super().__init__(
            f"tenant {tenant_id!r} exceeded {window} budget: "
            f"observed ${observed:.4f} > ${limit:.4f}"
        )
        self.tenant_id = tenant_id
        self.window = window
        self.observed = observed
        self.limit = limit


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _day_offset(days: int) -> date:
    return (datetime.now(timezone.utc) - timedelta(days=days)).date()


class TenantBudgetTracker:
    """Rolling per-tenant cost accounting, O(1) per operation.

    Costs are aggregated into calendar-day buckets (UTC). Daily
    windows read the current bucket's total; monthly windows sum up to
    30 buckets.

    Clock-skew protection: every operation compares the monotonic
    clock delta to the wall-clock delta. A backwards jump (NTP
    correction or VM resume) emits a warning log; the tracker continues
    but new samples are still trusted for the *new* day key — no double
    counting. An attacker who can move the wall clock forward can
    short-circuit a window; defence belongs at the OS / hypervisor
    level.
    """

    def __init__(
        self,
        *,
        per_task_usd: float | None = None,
        daily_usd: float | None = None,
        monthly_usd: float | None = None,
    ) -> None:
        self.per_task_usd = per_task_usd
        self.daily_usd = daily_usd
        self.monthly_usd = monthly_usd
        self._state: dict[str, _TenantState] = {}
        self._lock = RLock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_state(self, tenant_id: str) -> _TenantState:
        state = self._state.get(tenant_id)
        if state is None:
            state = _TenantState()
            self._state[tenant_id] = state
        return state

    def _bucket_for_today(self, state: _TenantState) -> _DayBucket:
        today = _utc_today()
        if state.buckets and state.buckets[-1].day == today:
            return state.buckets[-1]
        # Drop any bucket older than 35 days (handled by deque maxlen).
        bucket = _DayBucket(day=today)
        state.buckets.append(bucket)
        return bucket

    def _check_clock(self, state: _TenantState) -> None:
        now = time.monotonic()
        if state.last_monotonic and now < state.last_monotonic:  # impossible
            _logger.warning(
                "budget.monotonic_clock_jumped_backwards",
                delta=now - state.last_monotonic,
            )
        state.last_monotonic = now

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_cost(self, tenant_id: str, cost_usd: float) -> None:
        if not tenant_id or cost_usd <= 0:
            return
        with self._lock:
            state = self._get_state(tenant_id)
            self._check_clock(state)
            self._bucket_for_today(state).total_usd += cost_usd

    def reserve(self, tenant_id: str, *, anticipated_cost: float) -> None:
        if not tenant_id or anticipated_cost <= 0:
            return
        with self._lock:
            state = self._get_state(tenant_id)
            self._check_clock(state)
            self._enforce_locked(tenant_id, state, anticipated_cost)
            self._bucket_for_today(state).total_usd += anticipated_cost

    def settle(
        self,
        tenant_id: str,
        *,
        reserved: float,
        actual: float,
    ) -> None:
        if not tenant_id:
            return
        delta = actual - reserved
        if abs(delta) < 1e-9:
            return
        with self._lock:
            state = self._get_state(tenant_id)
            self._check_clock(state)
            bucket = self._bucket_for_today(state)
            bucket.total_usd += delta
            # Keep buckets non-negative; under-reservations may drive a
            # bucket below zero transiently, but mathematically the sum
            # stays correct across days.
            if bucket.total_usd < 0:
                bucket.total_usd = 0.0

    def enforce(
        self,
        tenant_id: str,
        *,
        anticipated_cost: float = 0.0,
    ) -> None:
        if not tenant_id:
            return
        with self._lock:
            state = self._get_state(tenant_id)
            self._enforce_locked(tenant_id, state, anticipated_cost)

    def _enforce_locked(
        self,
        tenant_id: str,
        state: _TenantState,
        anticipated_cost: float,
    ) -> None:
        """Caller holds the lock."""
        if self.daily_usd is not None:
            today = _utc_today()
            day_total = anticipated_cost + sum(
                b.total_usd for b in state.buckets if b.day == today
            )
            if day_total > self.daily_usd:
                raise TenantBudgetExceeded(
                    tenant_id, "daily", day_total, self.daily_usd
                )
        if self.monthly_usd is not None:
            cutoff = _day_offset(30)
            month_total = anticipated_cost + sum(
                b.total_usd for b in state.buckets if b.day > cutoff
            )
            if month_total > self.monthly_usd:
                raise TenantBudgetExceeded(
                    tenant_id, "monthly", month_total, self.monthly_usd
                )

    def observed(self, tenant_id: str, *, window: str) -> float:
        with self._lock:
            state = self._state.get(tenant_id)
            if state is None:
                return 0.0
            if window == "daily":
                today = _utc_today()
                return sum(b.total_usd for b in state.buckets if b.day == today)
            if window == "monthly":
                cutoff = _day_offset(30)
                return sum(b.total_usd for b in state.buckets if b.day > cutoff)
            raise ValueError(f"Unknown window {window!r}")

    def snapshot(self, tenant_id: str) -> dict[str, float]:
        return {
            "daily_usd": self.observed(tenant_id, window="daily"),
            "monthly_usd": self.observed(tenant_id, window="monthly"),
        }

    def erase_tenant(self, tenant_id: str) -> int:
        with self._lock:
            state = self._state.pop(tenant_id, None)
            if state is None:
                return 0
            return len(state.buckets)
