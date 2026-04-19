"""Optimization manager: evaluates health and proposes routing changes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from stc_framework.spec.models import STCSpec
from stc_framework.trainer.history_store import HistoryStore


class OptimizationManager:
    def __init__(self, spec: STCSpec, history: HistoryStore) -> None:
        self._spec = spec
        self._history = history
        self._triggers = spec.trainer.maintenance_triggers

    def evaluate_performance(self, *, window_hours: int = 24) -> dict[str, Any]:
        """Summarize recent performance against spec thresholds."""
        since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        recent = self._history.recent(since=since)
        if not recent:
            return {"status": "insufficient_data", "samples": 0}

        accuracies = np.array([r.accuracy for r in recent], dtype=np.float64)
        costs = np.array([r.cost_usd for r in recent], dtype=np.float64)
        latencies = np.array([r.latency_ms for r in recent], dtype=np.float64)
        halls = np.array([r.hallucination_detected for r in recent], dtype=np.bool_)

        report = {
            "status": "healthy",
            "samples": len(recent),
            "window_hours": window_hours,
            "accuracy": {
                "mean": float(accuracies.mean()),
                "p50": float(np.percentile(accuracies, 50)),
                "threshold": self._triggers.accuracy_below,
            },
            "cost": {
                "mean_per_task": float(costs.mean()),
                "total": float(costs.sum()),
                "threshold": self._triggers.cost_above_per_task_usd,
            },
            "latency": {
                "p50_ms": float(np.percentile(latencies, 50)),
                "p95_ms": float(np.percentile(latencies, 95)),
                "threshold_p95": self._triggers.latency_p95_above_ms,
            },
            "hallucination_rate": {
                "rate": float(halls.mean()),
                "threshold": self._triggers.hallucination_rate_above,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        triggers: list[str] = []
        if report["accuracy"]["mean"] < report["accuracy"]["threshold"]:
            triggers.append("accuracy_below_threshold")
        if report["cost"]["mean_per_task"] > report["cost"]["threshold"]:
            triggers.append("cost_above_threshold")
        if report["latency"]["p95_ms"] > report["latency"]["threshold_p95"]:
            triggers.append("latency_above_threshold")
        if report["hallucination_rate"]["rate"] > report["hallucination_rate"]["threshold"]:
            triggers.append("hallucination_rate_above_threshold")

        if triggers:
            report["status"] = "maintenance_recommended"
            report["triggers"] = triggers

        return report

    def suggest_model_routing(self, *, limit: int = 500) -> dict[str, dict[str, float]]:
        """Rank observed models by cost-normalized accuracy."""
        recent = self._history.recent(limit=limit)
        if not recent:
            return {}

        by_model: dict[str, dict[str, list[float]]] = {}
        for r in recent:
            if not r.model_used:
                continue
            bucket = by_model.setdefault(
                r.model_used, {"accuracies": [], "costs": [], "latencies": []}
            )
            bucket["accuracies"].append(r.accuracy)
            bucket["costs"].append(r.cost_usd)
            bucket["latencies"].append(r.latency_ms)

        out: dict[str, dict[str, float]] = {}
        for model, stats in by_model.items():
            acc_mean = float(np.mean(stats["accuracies"])) if stats["accuracies"] else 0.0
            cost_mean = float(np.mean(stats["costs"])) if stats["costs"] else 0.0
            lat_p95 = (
                float(np.percentile(stats["latencies"], 95)) if stats["latencies"] else 0.0
            )
            out[model] = {
                "accuracy_mean": acc_mean,
                "cost_mean": cost_mean,
                "latency_p95_ms": lat_p95,
                "cost_normalized_accuracy": acc_mean / max(cost_mean, 1e-6),
                "sample_count": float(len(stats["accuracies"])),
            }
        return out

    def ordered_models_for_tier(self, tier: str) -> list[str]:
        """Return tier's allowed models ordered by observed cost-normalized accuracy.

        Models with no observations preserve their spec order after the observed ones.
        """
        allowed = self._spec.routing_for(tier)
        if not allowed:
            return []
        suggestions = self.suggest_model_routing()
        scored: list[tuple[str, float]] = []
        unscored: list[str] = []
        for model in allowed:
            stats = suggestions.get(model)
            if stats:
                scored.append((model, stats["cost_normalized_accuracy"]))
            else:
                unscored.append(model)
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [m for m, _ in scored] + unscored
