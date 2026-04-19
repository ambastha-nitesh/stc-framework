"""Native async-aware circuit breaker.

Pybreaker is synchronous; wrapping it around async callables lets coroutines
return successfully while the underlying await would have failed. This
implementation tracks state natively so it actually works for ``await``.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from enum import Enum
from threading import RLock
from typing import TypeVar

from stc_framework.config.logging import get_logger
from stc_framework.errors import CircuitBreakerOpen
from stc_framework.observability.metrics import get_metrics

T = TypeVar("T")

_logger = get_logger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


def _state_to_gauge(state: CircuitState) -> int:
    return {CircuitState.CLOSED: 0, CircuitState.HALF_OPEN: 1, CircuitState.OPEN: 2}[state]


class Circuit:
    """Async circuit breaker."""

    def __init__(
        self,
        downstream: str,
        *,
        fail_max: int = 5,
        reset_timeout: float = 30.0,
    ) -> None:
        self.downstream = downstream
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout

        self._state = CircuitState.CLOSED
        self._fail_count = 0
        self._last_failure: float | None = None
        self._lock = RLock()
        get_metrics().circuit_breaker_state.labels(downstream=downstream).set(
            _state_to_gauge(self._state)
        )

    @property
    def state(self) -> str:
        return self._state.value

    def _transition(self, new_state: CircuitState) -> None:
        if new_state == self._state:
            return
        previous = self._state
        self._state = new_state
        get_metrics().circuit_breaker_state.labels(downstream=self.downstream).set(
            _state_to_gauge(new_state)
        )
        _logger.warning(
            "circuit.state_change",
            downstream=self.downstream,
            from_state=previous.value,
            to_state=new_state.value,
        )

    def _check_reset(self) -> None:
        if self._state == CircuitState.OPEN and self._last_failure is not None:
            if time.monotonic() - self._last_failure >= self.reset_timeout:
                self._transition(CircuitState.HALF_OPEN)

    def _record_failure(self) -> None:
        with self._lock:
            self._fail_count += 1
            self._last_failure = time.monotonic()
            if self._fail_count >= self.fail_max:
                self._transition(CircuitState.OPEN)
            elif self._state == CircuitState.HALF_OPEN:
                # A failure in half-open state re-opens the breaker.
                self._transition(CircuitState.OPEN)

    def _record_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.CLOSED)
            self._fail_count = 0
            self._last_failure = None

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        with self._lock:
            self._check_reset()
            if self._state == CircuitState.OPEN:
                raise CircuitBreakerOpen(
                    message=f"Circuit open for {self.downstream}",
                    downstream=self.downstream,
                )

        try:
            result = await fn()
        except BaseException:
            self._record_failure()
            raise
        else:
            self._record_success()
            return result


_circuits: dict[str, Circuit] = {}
_lock = RLock()


def get_circuit(
    downstream: str, fail_max: int = 5, reset_timeout: float = 30.0
) -> Circuit:
    with _lock:
        circuit = _circuits.get(downstream)
        if circuit is None:
            circuit = Circuit(downstream, fail_max=fail_max, reset_timeout=reset_timeout)
            _circuits[downstream] = circuit
        return circuit


def reset_circuits_for_tests() -> None:
    with _lock:
        _circuits.clear()
