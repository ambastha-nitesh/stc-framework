"""LiteLLM-backed LLM client (optional extra)."""

from __future__ import annotations

from typing import Any

from stc_framework.adapters.llm.base import ChatMessage, LLMClient, LLMResponse, LLMUsage
from stc_framework.errors import (
    LLMContentFiltered,
    LLMQuotaExceeded,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)


class LiteLLMAdapter(LLMClient):
    """Wraps ``litellm.acompletion`` and maps provider errors to our taxonomy."""

    def __init__(self, *, api_base: str | None = None, default_timeout: float = 30.0) -> None:
        try:
            import litellm
        except ImportError as exc:  # pragma: no cover - optional
            raise ImportError(
                "litellm is not installed; install with `pip install stc-framework[litellm]`"
            ) from exc
        self._litellm = litellm
        if api_base:
            litellm.api_base = api_base
        self._default_timeout = default_timeout

    async def acompletion(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        timeout: float,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        try:
            response = await self._litellm.acompletion(
                model=model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                timeout=timeout or self._default_timeout,
                metadata=metadata or {},
            )
        except Exception as exc:  # pragma: no cover - provider-specific mapping
            message = str(exc)
            lower = message.lower()
            if "timeout" in lower or "timed out" in lower:
                raise LLMTimeout(message=message, downstream="litellm") from exc
            if "rate" in lower and "limit" in lower:
                raise LLMRateLimited(message=message, downstream="litellm") from exc
            if "quota" in lower or "budget" in lower:
                raise LLMQuotaExceeded(message=message, downstream="litellm") from exc
            if "content filter" in lower or "safety" in lower:
                raise LLMContentFiltered(message=message, downstream="litellm") from exc
            raise LLMUnavailable(message=message, downstream="litellm") from exc

        choice = response.choices[0].message
        content = getattr(choice, "content", "") or ""

        usage_obj = getattr(response, "usage", None)
        if usage_obj is not None:
            usage = LLMUsage(
                prompt_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
                total_tokens=getattr(usage_obj, "total_tokens", 0) or 0,
            )
        else:
            usage = LLMUsage()

        cost = 0.0
        try:
            cost = float(self._litellm.completion_cost(completion_response=response) or 0.0)
        except Exception:  # pragma: no cover
            pass

        return LLMResponse(
            content=content,
            model=getattr(response, "model", model),
            usage=usage,
            cost_usd=cost,
        )

    async def healthcheck(self) -> bool:
        # Best-effort: litellm is a library, not a service; consider healthy if importable.
        return True
