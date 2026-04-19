"""Scope validator.

This version honours the spec correctly:

- ``prohibited_topics`` — the response must **not** match any prohibited
  topic's pattern set.
- ``allowed_topics`` — when non-empty, responses must match **at least one**
  allowed topic, otherwise they are flagged as out of scope.

The validator ships a mapping from topic names (as declared in
``spec-examples/financial_qa.yaml``) to regex patterns so that spec-only
topic labels work out of the box. Unknown topics are skipped but logged.
"""

from __future__ import annotations

import re

from stc_framework.config.logging import get_logger
from stc_framework.critic.validators.base import (
    GuardrailResult,
    ValidationContext,
    Validator,
)

_logger = get_logger(__name__)


_TOPIC_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "investment_recommendations": [
        re.compile(r"\b(?:buy|sell|hold|invest in|recommend)\b", re.IGNORECASE),
        re.compile(r"\b(?:price target|upside|downside|outperform|underperform)\b", re.IGNORECASE),
    ],
    "buy_sell_hold": [
        re.compile(r"\b(?:buy|sell|hold)\b\s+(?:the|this|that)?\s*(?:stock|share|position)", re.IGNORECASE),
    ],
    "portfolio_allocation": [
        re.compile(r"\b(?:allocat|rebalance|diversif|portfolio weight)\b", re.IGNORECASE),
    ],
    "financial_data": [
        re.compile(r"\b(?:revenue|earnings|profit|margin|ebitda|cash flow|assets|liabilities)\b", re.IGNORECASE),
        re.compile(r"\$\d|\d+\s*%"),
    ],
    "document_content": [
        re.compile(r"\[Source:|\[Document:|page\s+\d+|section", re.IGNORECASE),
    ],
    "calculations": [
        re.compile(r"\d+\s*[+\-*/]\s*\d+|percentage|ratio"),
    ],
    "comparisons": [
        re.compile(r"\b(?:compared|versus|vs\.|year-over-year|quarter-over-quarter|growth)\b", re.IGNORECASE),
    ],
}


class ScopeValidator(Validator):
    rail_name = "scope_check"
    severity = "high"

    def __init__(
        self,
        *,
        prohibited_topics: list[str] | None = None,
        allowed_topics: list[str] | None = None,
        action_on_prohibited: str = "block",
        action_on_out_of_scope: str = "warn",
    ) -> None:
        self._prohibited = list(prohibited_topics or [])
        self._allowed = list(allowed_topics or [])
        self._prohibited_action = action_on_prohibited
        self._allowed_action = action_on_out_of_scope

    async def avalidate(self, ctx: ValidationContext) -> GuardrailResult:
        violations: list[dict[str, object]] = []

        for topic in self._prohibited:
            patterns = _TOPIC_PATTERNS.get(topic)
            if patterns is None:
                _logger.debug("scope.unknown_topic", topic=topic)
                continue
            for pattern in patterns:
                matches = pattern.findall(ctx.response)
                if matches:
                    violations.append({"topic": topic, "matches": matches[:3]})
                    break

        if violations:
            return GuardrailResult(
                rail_name=self.rail_name,
                passed=False,
                severity="high",
                action=self._prohibited_action,
                details=f"{len(violations)} prohibited topic violations detected",
                evidence={"violations": violations},
            )

        if self._allowed and not any(
            any(p.search(ctx.response) for p in _TOPIC_PATTERNS.get(topic, [])) for topic in self._allowed
        ):
            return GuardrailResult(
                rail_name=self.rail_name,
                passed=False,
                severity="low",
                action=self._allowed_action,
                details="Response did not match any allowed_topics pattern",
                evidence={"allowed_topics": self._allowed},
            )

        return GuardrailResult(
            rail_name=self.rail_name,
            passed=True,
            severity="low",
            action="pass",
            details="No scope violations",
        )
