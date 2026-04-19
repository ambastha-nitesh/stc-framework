"""Reward signal computation.

Ports the signal math from the original ``optimization_manager.py`` but
makes each signal pluggable via a :class:`RewardSignalFn` callable so
callers can add domain-specific rewards without subclassing.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stc_framework.spec.models import STCSpec

RewardSignalFn = Callable[[dict[str, Any]], "RewardSignal"]


_NUMBER_RE = re.compile(r"\$[\d,.]+[BMK]?|\d+\.\d+%|\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?")


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RewardSignal:
    trace_id: str
    signal_type: str
    value: float
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_iso)


class RewardComputer:
    """Computes reward signals from an execution trace."""

    def __init__(self, spec: STCSpec) -> None:
        self._weights = {r.name: r.weight for r in spec.trainer.optimization.reward_signals}
        self._custom: dict[str, RewardSignalFn] = {}

    def register_signal(self, name: str, fn: RewardSignalFn) -> None:
        self._custom[name] = fn

    def compute_retrieval_quality(self, trace: dict[str, Any]) -> RewardSignal:
        scores = list(trace.get("retrieval_scores", []))
        value = sum(scores) / len(scores) if scores else 0.0
        return RewardSignal(
            trace_id=trace.get("trace_id", ""),
            signal_type="retrieval_quality",
            value=float(value),
            metadata={"num_chunks": len(scores), "scores": scores[:10]},
        )

    def compute_factual_accuracy(self, trace: dict[str, Any]) -> RewardSignal:
        response = trace.get("response", "") or ""
        source_chunks = trace.get("retrieved_chunks", []) or []
        resp_nums = set(_NUMBER_RE.findall(response))
        source_text = " ".join(_text_of(c) for c in source_chunks)
        src_nums = set(_NUMBER_RE.findall(source_text))

        if not resp_nums:
            score = 1.0
        elif not src_nums:
            score = 0.5
        else:
            grounded = resp_nums & src_nums
            score = len(grounded) / len(resp_nums)

        return RewardSignal(
            trace_id=trace.get("trace_id", ""),
            signal_type="factual_accuracy",
            value=float(score),
            metadata={
                "response_numbers": list(resp_nums)[:10],
                "source_numbers": list(src_nums)[:10],
            },
        )

    def compute_user_feedback(self, trace_id: str, feedback: str) -> RewardSignal:
        positive = {"thumbs_up", "positive", "correct", "good", "yes"}
        value = 1.0 if feedback.lower() in positive else 0.0
        return RewardSignal(
            trace_id=trace_id,
            signal_type="user_feedback",
            value=value,
            metadata={"raw_feedback": feedback},
        )

    def compute_all(
        self,
        trace: dict[str, Any],
        *,
        include_user_feedback: str | None = None,
    ) -> list[RewardSignal]:
        signals = [
            self.compute_retrieval_quality(trace),
            self.compute_factual_accuracy(trace),
        ]
        for name, fn in self._custom.items():
            try:
                signals.append(fn(trace))
            except Exception as exc:  # pragma: no cover
                signals.append(
                    RewardSignal(
                        trace_id=trace.get("trace_id", ""),
                        signal_type=name,
                        value=0.0,
                        metadata={"error": repr(exc)},
                    )
                )
        if include_user_feedback:
            signals.append(self.compute_user_feedback(trace.get("trace_id", ""), include_user_feedback))
        return signals

    def composite(self, signals: list[RewardSignal]) -> float:
        total = 0.0
        total_weight = 0.0
        for s in signals:
            weight = self._weights.get(s.signal_type, 0.1)
            total += s.value * weight
            total_weight += weight
        return total / total_weight if total_weight else 0.0


def _text_of(chunk: Any) -> str:
    if isinstance(chunk, dict):
        return str(chunk.get("text", ""))
    if hasattr(chunk, "page_content"):
        return str(chunk.page_content)
    return str(chunk)
