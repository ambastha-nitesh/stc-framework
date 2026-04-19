"""Stalwart state / result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StalwartResult:
    """The output of a single Stalwart run."""

    query: str = ""
    response: str = ""
    retrieved_chunks: list[dict[str, Any]] = field(default_factory=list)
    retrieval_scores: list[float] = field(default_factory=list)
    context: str = ""
    citations: list[dict[str, str]] = field(default_factory=list)
    data_tier: str = "public"
    model_used: str = ""
    spec_version: str = ""
    prompt_version: str = ""
    cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    trace_id: str = ""
    error: str | None = None

    def as_trainer_trace(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "query": self.query,
            "response": self.response,
            "context": self.context,
            "retrieved_chunks": self.retrieved_chunks,
            "retrieval_scores": self.retrieval_scores,
            "model_used": self.model_used,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "data_tier": self.data_tier,
            "prompt_version": self.prompt_version,
        }
