"""Guardrails AI Hub adapter (optional)."""

from __future__ import annotations

from typing import Any

from stc_framework.adapters.guardrails.base import ExternalGuardrailClient, GuardrailCheck
from stc_framework.errors import GuardrailError


class GuardrailsAIAdapter(ExternalGuardrailClient):
    """Wraps a Guardrails AI `Guard` object.

    The adapter takes a prebuilt guard keyed by rail name; callers configure
    which validators each rail runs.
    """

    def __init__(self, guards: dict[str, Any]) -> None:
        try:
            import guardrails  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "guardrails-ai is not installed; "
                "`pip install stc-framework[guardrails-ai]`"
            ) from exc
        self._guards = guards

    async def check(self, rail_name: str, text: str, **kwargs: Any) -> GuardrailCheck:
        guard = self._guards.get(rail_name)
        if guard is None:
            raise GuardrailError(
                message=f"No Guardrails AI guard configured for rail {rail_name!r}",
                downstream="guardrails_ai",
            )
        try:
            result = guard.parse(text)
        except Exception as exc:  # pragma: no cover
            raise GuardrailError(
                message=f"Guardrails AI rail {rail_name!r} failed: {exc}",
                downstream="guardrails_ai",
            ) from exc

        passed = getattr(result, "validation_passed", True)
        return GuardrailCheck(
            name=rail_name,
            passed=passed,
            details=str(getattr(result, "validation_summaries", ""))[:200],
            severity="critical" if not passed else "low",
        )

    async def healthcheck(self) -> bool:
        return True
