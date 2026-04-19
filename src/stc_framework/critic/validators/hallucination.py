"""Hallucination / grounding validator.

Default implementation uses a content-word overlap heuristic (deterministic,
dependency-free). When an :class:`EmbeddingsClient` is supplied, grounding
is computed via cosine similarity against context sentences — stronger
signal but still provider-free.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from stc_framework.critic.validators.base import (
    GuardrailResult,
    ValidationContext,
    Validator,
)

if TYPE_CHECKING:
    from stc_framework.adapters.embeddings.base import EmbeddingsClient


_STOPWORDS = frozenset(
    {
        "the", "a", "an", "is", "was", "were", "are", "been", "be",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "shall", "can", "to", "of",
        "in", "for", "on", "with", "at", "by", "from", "as", "into",
        "through", "during", "before", "after", "and", "but", "or",
        "not", "no", "this", "that", "these", "those", "it", "its",
    }
)
_SENTENCE_SPLIT = re.compile(r"[.!?]+")


class HallucinationValidator(Validator):
    rail_name = "hallucination_detection"
    severity = "critical"

    def __init__(
        self,
        threshold: float = 0.8,
        *,
        embeddings: "EmbeddingsClient | None" = None,
        min_sentence_overlap: float = 0.3,
    ) -> None:
        self._threshold = threshold
        self._embeddings = embeddings
        self._min_overlap = min_sentence_overlap

    async def avalidate(self, ctx: ValidationContext) -> GuardrailResult:
        if not ctx.context or ctx.context == "No relevant documents found.":
            if len(ctx.response) > 100:
                return GuardrailResult(
                    rail_name=self.rail_name,
                    passed=False,
                    severity=self.severity,
                    action="block",
                    details="Substantial response generated with no source context",
                )

        sentences = [
            s.strip()
            for s in _SENTENCE_SPLIT.split(ctx.response)
            if len(s.strip()) > 20
        ]
        if not sentences:
            return GuardrailResult(
                rail_name=self.rail_name,
                passed=True,
                severity=self.severity,
                details="Response too short to evaluate",
            )

        if self._embeddings is not None:
            return await self._validate_embedding(ctx, sentences)
        return self._validate_overlap(ctx, sentences)

    def _validate_overlap(
        self, ctx: ValidationContext, sentences: list[str]
    ) -> GuardrailResult:
        context_words = {w for w in ctx.context.lower().split() if w not in _STOPWORDS}
        ungrounded: list[str] = []
        for sentence in sentences:
            sentence_words = {
                w for w in sentence.lower().split() if w not in _STOPWORDS
            }
            if not sentence_words:
                continue
            overlap = len(sentence_words & context_words) / len(sentence_words)
            if overlap < self._min_overlap:
                ungrounded.append(sentence[:120])
        grounding_score = 1.0 - (len(ungrounded) / len(sentences))
        passed = grounding_score >= self._threshold
        return GuardrailResult(
            rail_name=self.rail_name,
            passed=passed,
            severity=self.severity if not passed else "low",
            action="pass" if passed else "block",
            details=(
                f"Grounding score: {grounding_score:.2f} "
                f"(threshold: {self._threshold})"
            ),
            evidence={
                "grounding_score": grounding_score,
                "total_sentences": len(sentences),
                "ungrounded_sentences": ungrounded[:5],
            },
        )

    async def _validate_embedding(
        self, ctx: ValidationContext, sentences: list[str]
    ) -> GuardrailResult:
        import math

        embeddings = self._embeddings
        assert embeddings is not None

        ctx_sentences = [
            s.strip() for s in _SENTENCE_SPLIT.split(ctx.context) if len(s.strip()) > 20
        ] or [ctx.context.strip()]

        ctx_vecs = await embeddings.aembed_batch(ctx_sentences)
        resp_vecs = await embeddings.aembed_batch(sentences)

        def cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a)) or 1.0
            nb = math.sqrt(sum(x * x for x in b)) or 1.0
            return dot / (na * nb)

        ungrounded: list[str] = []
        sims: list[float] = []
        for sentence, vec in zip(sentences, resp_vecs):
            best = max(cosine(vec, cv) for cv in ctx_vecs)
            sims.append(best)
            if best < self._min_overlap:
                ungrounded.append(sentence[:120])

        grounding_score = sum(sims) / len(sims)
        passed = grounding_score >= self._threshold
        return GuardrailResult(
            rail_name=self.rail_name,
            passed=passed,
            severity=self.severity if not passed else "low",
            action="pass" if passed else "block",
            details=(
                f"Embedding grounding score: {grounding_score:.2f} "
                f"(threshold: {self._threshold})"
            ),
            evidence={
                "grounding_score": grounding_score,
                "total_sentences": len(sentences),
                "ungrounded_sentences": ungrounded[:5],
            },
        )
