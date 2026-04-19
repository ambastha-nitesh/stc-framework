"""Deterministic mock LLM client used as the zero-install default and in tests.

Its response strategy is *intentionally* grounding-friendly: it echoes numeric
facts it finds in the most recent user message and cites sources if
``[Document: ...]`` headers appear in the context, so that the Critic's
grounding and numerical-accuracy rails can exercise the system without a
real model.
"""

from __future__ import annotations

import re
from typing import Any

from stc_framework.adapters.llm.base import ChatMessage, LLMClient, LLMResponse, LLMUsage


_NUMBER_RE = re.compile(r"\$[\d,.]+(?:\s*(?:billion|million|thousand|[BMK]))?|\d+\.\d+%|\d{1,3}(?:,\d{3})+")
_DOC_RE = re.compile(r"\[Document:\s*([^\],]+)(?:,\s*Page\s+([^\]]+))?\]")


class MockLLMClient(LLMClient):
    """In-memory deterministic LLM."""

    def __init__(self, *, model_name: str = "mock/stc-mock", cost_per_call: float = 0.0) -> None:
        self.model_name = model_name
        self.cost_per_call = cost_per_call

    async def acompletion(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        timeout: float,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        # Split the user message into its CONTEXT and QUESTION sections
        # as assembled by the Stalwart prompt. We deliberately look for
        # numbers and citations **only inside the CONTEXT** — pulling
        # them from the QUESTION would let a misconfigured
        # STC_LLM_ADAPTER=mock produce responses that appear grounded
        # but are actually echoing user input.
        user_content = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )

        context_block = user_content
        if "CONTEXT:" in user_content:
            after_ctx = user_content.split("CONTEXT:", 1)[1]
            context_block = after_ctx.split("QUESTION:", 1)[0]

        numbers = _NUMBER_RE.findall(context_block)
        docs = _DOC_RE.findall(context_block)

        parts: list[str] = []
        if numbers:
            parts.append(
                f"Based on the provided context, the relevant figure is {numbers[0]}."
            )
        else:
            parts.append("Based on the provided context, here is a grounded summary.")

        if docs:
            source, page = docs[0]
            parts.append(f"[Source: {source.strip()}, page {page.strip() or '?'}]")

        # Label the response as mock so audit reviewers cannot confuse
        # a mock-adapter response with a production one after the fact.
        parts.append("[mock-llm]")
        content = " ".join(parts)

        prompt_tokens = sum(len(m.content.split()) for m in messages)
        completion_tokens = len(content.split())
        usage = LLMUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )
        return LLMResponse(
            content=content,
            model=model or self.model_name,
            usage=usage,
            cost_usd=self.cost_per_call,
            extra={"mock": True},
        )

    async def healthcheck(self) -> bool:
        return True
