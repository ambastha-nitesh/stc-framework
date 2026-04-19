"""NeMo Guardrails adapter (optional).

When the ``[nemo]`` extra is installed this wraps ``nemoguardrails`` rails.
Without it, importing this module raises ``ImportError`` so callers can
detect absence.
"""

from __future__ import annotations

from typing import Any

from stc_framework.adapters.guardrails.base import ExternalGuardrailClient, GuardrailCheck
from stc_framework.errors import GuardrailError


class NemoGuardrailsAdapter(ExternalGuardrailClient):
    def __init__(self, config_path: str) -> None:
        try:
            from nemoguardrails import LLMRails, RailsConfig
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "nemoguardrails is not installed; `pip install stc-framework[nemo]`"
            ) from exc
        self._config = RailsConfig.from_path(config_path)
        self._rails = LLMRails(self._config)

    async def check(self, rail_name: str, text: str, **kwargs: Any) -> GuardrailCheck:
        try:
            result = await self._rails.generate_async(messages=[{"role": "user", "content": text}])
        except Exception as exc:  # pragma: no cover
            raise GuardrailError(
                message=f"NeMo rail {rail_name!r} failed: {exc}",
                downstream="nemo_guardrails",
            ) from exc
        content = result.get("content", "") if isinstance(result, dict) else str(result)
        blocked = "I'm sorry" in content or "can't assist" in content.lower()
        return GuardrailCheck(
            name=rail_name,
            passed=not blocked,
            details=content[:200],
            severity="high" if blocked else "low",
        )

    async def healthcheck(self) -> bool:
        return True
