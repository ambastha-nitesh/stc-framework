"""LLM adapter protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    cost_usd: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLMClient(Protocol):
    """Async LLM client.

    Concrete adapters must raise subclasses of
    :class:`stc_framework.errors.LLMError` for provider failures.
    """

    async def acompletion(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        timeout: float,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse: ...

    async def healthcheck(self) -> bool: ...
