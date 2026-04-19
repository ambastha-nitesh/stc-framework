"""Numerical-accuracy validator.

Ports the normalized-number-matching logic from the original
``governance_engine.py`` and adds:
- spec-driven tolerance,
- compiled regex caching,
- early-exit for responses without numbers,
- evidence payload sized for audit logs (first 10 values each).
"""

from __future__ import annotations

import re
from typing import Any

from stc_framework.critic.validators.base import (
    GuardrailResult,
    ValidationContext,
    Validator,
)

_NUMBER_RE = re.compile(
    r"\$[\d,.]+(?:\s*(?:billion|million|thousand|[BMK]))?"
    r"|\d+\.\d+%"
    r"|\d{1,3}(?:,\d{3})+"
    r"|\d+(?:\.\d+)?",
    flags=re.IGNORECASE,
)

_SUFFIX_MULTIPLIERS: list[tuple[str, float]] = [
    ("billion", 1e9),
    ("million", 1e6),
    ("thousand", 1e3),
    ("B", 1e9),
    ("M", 1e6),
    ("K", 1e3),
]


class NumericalAccuracyValidator(Validator):
    """Reject responses whose numbers are not grounded in source text."""

    rail_name = "numerical_accuracy"
    severity = "critical"

    def __init__(self, tolerance_percent: float = 1.0) -> None:
        self._tolerance = tolerance_percent / 100.0

    async def avalidate(self, ctx: ValidationContext) -> GuardrailResult:
        response_numbers = _NUMBER_RE.findall(ctx.response)
        if not response_numbers:
            return GuardrailResult(
                rail_name=self.rail_name,
                passed=True,
                severity=self.severity,
                action="pass",
                details="No numerical claims in response",
            )

        source_text = " ".join(_chunk_text(c) for c in ctx.source_chunks) + " " + ctx.context
        source_numbers = set(_NUMBER_RE.findall(source_text))

        ungrounded: list[str] = []
        for num in response_numbers:
            rn = _normalize(num)
            grounded = any(_match(rn, _normalize(s), self._tolerance) for s in source_numbers)
            if not grounded:
                ungrounded.append(num)

        passed = len(ungrounded) == 0
        return GuardrailResult(
            rail_name=self.rail_name,
            passed=passed,
            severity=self.severity,
            action="pass" if passed else "block",
            details=(
                f"All {len(response_numbers)} numbers grounded"
                if passed
                else f"{len(ungrounded)} numbers ungrounded in source"
            ),
            evidence={
                "response_numbers": response_numbers[:10],
                "ungrounded_numbers": ungrounded[:10],
                "source_numbers_sample": list(source_numbers)[:10],
            },
        )


def _chunk_text(chunk: Any) -> str:
    if isinstance(chunk, dict):
        return str(chunk.get("text", ""))
    if hasattr(chunk, "page_content"):
        return str(getattr(chunk, "page_content"))
    return str(chunk)


def _normalize(value: str) -> float | None:
    try:
        cleaned = value.replace("$", "").replace(",", "").replace("%", "").strip()
        multiplier = 1.0
        for suffix, mult in _SUFFIX_MULTIPLIERS:
            if suffix in value:
                cleaned = cleaned.replace(suffix, "").strip()
                multiplier = mult
                break
        return float(cleaned) * multiplier
    except (ValueError, TypeError):
        return None


def _match(a: float | None, b: float | None, tolerance: float) -> bool:
    if a is None or b is None:
        return False
    if a == 0 and b == 0:
        return True
    if a == 0 or b == 0:
        return False
    return abs(a - b) / max(abs(a), abs(b)) <= tolerance
