"""Spec-driven rail runner.

Walks the ``critic.guardrails.input_rails`` / ``output_rails`` declarations
and dispatches to the right validator. Unknown rail names are logged once
and skipped.
"""

from __future__ import annotations

from collections.abc import Iterable

from stc_framework.config.logging import get_logger
from stc_framework.critic.validators.base import (
    GuardrailResult,
    ValidationContext,
    Validator,
)
from stc_framework.resilience.bulkhead import Bulkhead
from stc_framework.resilience.timeout import atimeout
from stc_framework.spec.models import GuardrailRailSpec

_logger = get_logger(__name__)


class RailRunner:
    """Runs a set of validators under per-call timeout + bulkhead."""

    def __init__(
        self,
        validators: dict[str, Validator],
        *,
        timeout_sec: float = 5.0,
        bulkhead_limit: int = 128,
    ) -> None:
        self._validators = dict(validators)
        self._timeout = timeout_sec
        self._bulkhead = Bulkhead("guardrails", bulkhead_limit)
        self._warned_unknown: set[str] = set()

    def register(self, validator: Validator) -> None:
        self._validators[validator.rail_name] = validator

    async def run(self, rails: Iterable[GuardrailRailSpec], ctx: ValidationContext) -> list[GuardrailResult]:
        results: list[GuardrailResult] = []
        for rail in rails:
            validator = self._validators.get(rail.name)
            if validator is None:
                if rail.name not in self._warned_unknown:
                    _logger.warning("rails.unknown", rail=rail.name)
                    self._warned_unknown.add(rail.name)
                continue
            async with self._bulkhead.acquire():
                try:
                    async with atimeout(self._timeout):
                        result = await validator.avalidate(ctx)
                except Exception as exc:
                    _logger.exception("rails.validator_error", rail=rail.name)
                    result = GuardrailResult(
                        rail_name=rail.name,
                        passed=False,
                        severity="high",
                        action="warn",
                        details=f"validator error: {exc!r}",
                    )
            results.append(result)
        return results
