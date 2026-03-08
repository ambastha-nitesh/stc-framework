"""
STC Framework - Trainer: Optimization & Control Plane

The Trainer makes the Stalwart better over time. It observes execution traces,
evaluates performance against the Declarative Specification contract, and
applies optimization strategies: model routing, prompt tuning, retrieval
parameter adjustment, and cost optimization.

The Trainer does NOT perform business tasks. It does NOT override governance.
It operates through the Sentinel Layer (LiteLLM) as its control surface.
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from spec.loader import load_spec, STCSpec

logger = logging.getLogger("stc.trainer")


# ============================================================================
# Reward Functions
# ============================================================================

@dataclass
class RewardSignal:
    """A reward signal from a Stalwart execution trace."""
    trace_id: str
    signal_type: str  # user_feedback | factual_accuracy | retrieval_quality
    value: float  # 0.0 to 1.0
    metadata: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class RewardComputer:
    """
    Computes reward signals from Stalwart execution traces.
    These rewards feed into Agent Lightning's RL optimization loop.
    """
    
    def __init__(self, spec: STCSpec):
        self.spec = spec
        self.reward_config = spec.trainer.get("optimization", {}).get("reward_signals", [])
        self.weights = {r["name"]: r["weight"] for r in self.reward_config}
    
    def compute_retrieval_quality(self, trace_data: dict) -> RewardSignal:
        """
        Score how relevant the retrieved chunks were to the query.
        Uses semantic similarity between query and retrieved chunks.
        """
        retrieval_scores = trace_data.get("retrieval_scores", [])
        
        if not retrieval_scores:
            score = 0.0
        else:
            # Average retrieval score, normalized to 0-1
            import numpy as np
            score = float(np.mean(retrieval_scores))
        
        return RewardSignal(
            trace_id=trace_data.get("trace_id", ""),
            signal_type="retrieval_quality",
            value=score,
            metadata={"num_chunks": len(retrieval_scores), "scores": retrieval_scores},
        )
    
    def compute_factual_accuracy(self, trace_data: dict) -> RewardSignal:
        """
        Score factual accuracy by comparing numbers in the response
        against numbers in the source documents.
        """
        response = trace_data.get("response", "")
        source_chunks = trace_data.get("retrieved_chunks", [])
        
        import re
        
        # Extract numbers from response
        response_numbers = set(re.findall(r'\$[\d,.]+[BMK]?|\d+\.\d+%|\d{1,3}(?:,\d{3})+', response))
        
        # Extract numbers from source chunks
        source_text = " ".join([c.get("text", "") if isinstance(c, dict) else str(c) for c in source_chunks])
        source_numbers = set(re.findall(r'\$[\d,.]+[BMK]?|\d+\.\d+%|\d{1,3}(?:,\d{3})+', source_text))
        
        if not response_numbers:
            score = 1.0  # No numbers claimed = no numerical error
        elif not source_numbers:
            score = 0.5  # Can't verify; neutral
        else:
            # What fraction of response numbers are grounded in source?
            grounded = response_numbers & source_numbers
            score = len(grounded) / len(response_numbers) if response_numbers else 1.0
        
        return RewardSignal(
            trace_id=trace_data.get("trace_id", ""),
            signal_type="factual_accuracy",
            value=score,
            metadata={
                "response_numbers": list(response_numbers),
                "source_numbers": list(source_numbers)[:20],
                "grounded_count": len(response_numbers & source_numbers) if source_numbers else 0,
            },
        )
    
    def compute_user_feedback(self, trace_id: str, feedback: str) -> RewardSignal:
        """Convert explicit user feedback to a reward signal."""
        score = 1.0 if feedback in ("thumbs_up", "positive", "correct") else 0.0
        
        return RewardSignal(
            trace_id=trace_id,
            signal_type="user_feedback",
            value=score,
            metadata={"raw_feedback": feedback},
        )
    
    def compute_composite_reward(self, signals: list[RewardSignal]) -> float:
        """Compute weighted composite reward from multiple signals."""
        total = 0.0
        total_weight = 0.0
        
        for signal in signals:
            weight = self.weights.get(signal.signal_type, 0.1)
            total += signal.value * weight
            total_weight += weight
        
        return total / total_weight if total_weight > 0 else 0.0


# ============================================================================
# Optimization Manager
# ============================================================================

class OptimizationManager:
    """
    Manages the Trainer's optimization loops:
    1. Retrieval optimization (chunk size, top-k, reranking)
    2. Prompt optimization (via Agent Lightning APO)
    3. Model routing (cost vs accuracy tradeoffs)
    """
    
    def __init__(self, spec: STCSpec):
        self.spec = spec
        self.optimization_config = spec.trainer.get("optimization", {})
        self.cost_thresholds = spec.trainer.get("cost_thresholds", {})
        self.maintenance_triggers = spec.trainer.get("maintenance_triggers", {})
        
        # Performance tracking
        self.performance_history: list[dict] = []
        self.cost_history: list[dict] = []
    
    def evaluate_performance(self, window_hours: int = 24) -> dict:
        """
        Evaluate recent performance against spec thresholds.
        Returns a health report.
        """
        cutoff = datetime.utcnow() - timedelta(hours=window_hours)
        recent = [p for p in self.performance_history 
                  if datetime.fromisoformat(p["timestamp"]) > cutoff]
        
        if not recent:
            return {"status": "insufficient_data", "samples": 0}
        
        import numpy as np
        
        accuracies = [p.get("accuracy", 0) for p in recent]
        costs = [p.get("cost_usd", 0) for p in recent]
        latencies = [p.get("latency_ms", 0) for p in recent]
        hallucination_flags = [p.get("hallucination_detected", False) for p in recent]
        
        report = {
            "status": "healthy",
            "samples": len(recent),
            "window_hours": window_hours,
            "accuracy": {
                "mean": float(np.mean(accuracies)),
                "p50": float(np.percentile(accuracies, 50)),
                "threshold": self.maintenance_triggers.get("accuracy_below", 0.85),
            },
            "cost": {
                "mean_per_task": float(np.mean(costs)),
                "total": float(np.sum(costs)),
                "threshold": self.maintenance_triggers.get("cost_above_per_task_usd", 0.10),
            },
            "latency": {
                "p50_ms": float(np.percentile(latencies, 50)),
                "p95_ms": float(np.percentile(latencies, 95)),
                "threshold_p95": self.maintenance_triggers.get("latency_p95_above_ms", 5000),
            },
            "hallucination_rate": {
                "rate": sum(hallucination_flags) / len(hallucination_flags),
                "threshold": self.maintenance_triggers.get("hallucination_rate_above", 0.05),
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Check for maintenance triggers
        triggers = []
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
    
    def suggest_model_routing(self) -> dict:
        """
        Analyze cost vs accuracy per model and suggest routing changes.
        This is where the Trainer discovers that a local model handles
        simple queries as well as the frontier model.
        """
        model_stats = {}
        
        for record in self.performance_history[-500:]:
            model = record.get("model_used", "unknown")
            if model not in model_stats:
                model_stats[model] = {"accuracies": [], "costs": [], "latencies": []}
            
            model_stats[model]["accuracies"].append(record.get("accuracy", 0))
            model_stats[model]["costs"].append(record.get("cost_usd", 0))
            model_stats[model]["latencies"].append(record.get("latency_ms", 0))
        
        import numpy as np
        
        suggestions = {}
        for model, stats in model_stats.items():
            suggestions[model] = {
                "accuracy_mean": float(np.mean(stats["accuracies"])),
                "cost_mean": float(np.mean(stats["costs"])),
                "latency_p95": float(np.percentile(stats["latencies"], 95)),
                "cost_normalized_accuracy": (
                    float(np.mean(stats["accuracies"])) / max(float(np.mean(stats["costs"])), 0.001)
                ),
                "sample_count": len(stats["accuracies"]),
            }
        
        return suggestions
    
    def record_performance(self, trace_data: dict):
        """Record a performance data point from a Stalwart execution."""
        self.performance_history.append({
            "trace_id": trace_data.get("trace_id"),
            "model_used": trace_data.get("model_used"),
            "accuracy": trace_data.get("accuracy", 0),
            "cost_usd": trace_data.get("cost_usd", 0),
            "latency_ms": trace_data.get("latency_ms", 0),
            "hallucination_detected": trace_data.get("hallucination_detected", False),
            "data_tier": trace_data.get("data_tier"),
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        # Trim history to last 10000 records
        if len(self.performance_history) > 10000:
            self.performance_history = self.performance_history[-10000:]


# ============================================================================
# Agent Lightning Integration
# ============================================================================

class AgentLightningBridge:
    """
    Bridge to Microsoft Agent Lightning for RL-based optimization.
    
    Agent Lightning's sidecar design collects traces from the Stalwart
    without modifying the agent code. The Trainer configures the
    Lightning Server with reward functions and optimization targets.
    """
    
    def __init__(self, spec: STCSpec):
        self.spec = spec
        self.reward_computer = RewardComputer(spec)
    
    def configure_lightning_server(self) -> dict:
        """
        Generate configuration for Agent Lightning server.
        This would be used to initialize the Lightning Server
        with STC-specific reward functions and training parameters.
        """
        return {
            "algorithm": self.spec.trainer.get("optimization", {}).get("algorithm", "grpo"),
            "reward_functions": [
                {
                    "name": "stc_composite_reward",
                    "signals": self.spec.trainer.get("optimization", {}).get("reward_signals", []),
                },
            ],
            "agent_framework": self.spec.stalwart.get("framework", "langgraph"),
            "trace_collection": {
                "method": "opentelemetry_sidecar",
                "endpoint": self.spec.audit.get("phoenix_host", "http://localhost:6006"),
            },
            "optimization_targets": [
                loop["name"]
                for loop in self.spec.trainer.get("optimization", {}).get("optimization_loops", [])
            ],
        }
    
    def process_trace(self, trace_data: dict) -> dict:
        """
        Process a Stalwart execution trace into Agent Lightning format.
        Returns transition tuple: (state, action, reward, next_state)
        """
        # Compute reward signals
        signals = [
            self.reward_computer.compute_retrieval_quality(trace_data),
            self.reward_computer.compute_factual_accuracy(trace_data),
        ]
        
        composite_reward = self.reward_computer.compute_composite_reward(signals)
        
        return {
            "trace_id": trace_data.get("trace_id"),
            "state": {
                "query": trace_data.get("query"),
                "context_length": len(trace_data.get("context", "")),
                "num_chunks": len(trace_data.get("retrieved_chunks", [])),
            },
            "action": {
                "model_used": trace_data.get("model_used"),
                "prompt_version": trace_data.get("prompt_version"),
            },
            "reward": composite_reward,
            "signals": [
                {"type": s.signal_type, "value": s.value} for s in signals
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }


# ============================================================================
# Trainer Orchestrator
# ============================================================================

class Trainer:
    """
    Main Trainer class that orchestrates all optimization activities.
    """
    
    def __init__(self, spec_path: str = "spec/stc-spec.yaml"):
        self.spec = load_spec(spec_path)
        self.optimizer = OptimizationManager(self.spec)
        self.lightning = AgentLightningBridge(self.spec)
        self.reward_computer = RewardComputer(self.spec)
    
    def on_trace_received(self, trace_data: dict):
        """Called when a new Stalwart execution trace is available."""
        # Record performance metrics
        self.optimizer.record_performance(trace_data)
        
        # Process for Agent Lightning
        transition = self.lightning.process_trace(trace_data)
        
        logger.info(
            f"Trace {trace_data.get('trace_id')}: "
            f"reward={transition['reward']:.3f}, "
            f"model={trace_data.get('model_used')}"
        )
        
        return transition
    
    def on_user_feedback(self, trace_id: str, feedback: str):
        """Called when explicit user feedback is received."""
        signal = self.reward_computer.compute_user_feedback(trace_id, feedback)
        logger.info(f"User feedback for {trace_id}: {feedback} → {signal.value}")
    
    def run_health_check(self) -> dict:
        """Run a health check and return a performance report."""
        report = self.optimizer.evaluate_performance()
        
        if report["status"] == "maintenance_recommended":
            logger.warning(f"Maintenance recommended: {report.get('triggers')}")
            self._handle_maintenance(report)
        
        return report
    
    def run_routing_optimization(self) -> dict:
        """Analyze and suggest model routing changes."""
        suggestions = self.optimizer.suggest_model_routing()
        logger.info(f"Routing suggestions: {json.dumps(suggestions, indent=2)}")
        return suggestions
    
    def _handle_maintenance(self, report: dict):
        """Handle maintenance mode based on spec configuration."""
        maintenance_config = self.spec.trainer.get("maintenance_mode", {})
        action = maintenance_config.get("action", "alert_only")
        
        if action == "degrade":
            logger.warning("Entering degraded mode per spec configuration")
        elif action == "pause":
            logger.warning("Pausing Stalwart per spec configuration")
        else:
            logger.info("Maintenance alert sent (alert_only mode)")


if __name__ == "__main__":
    trainer = Trainer()
    
    # Simulate a trace
    sample_trace = {
        "trace_id": "test-001",
        "query": "What was Q4 revenue?",
        "response": "Q4 revenue was $4.2 billion",
        "retrieved_chunks": [{"text": "Q4 revenue was $4.2 billion, up 12% YoY"}],
        "retrieval_scores": [0.92, 0.87, 0.75],
        "model_used": "anthropic/claude-sonnet",
        "cost_usd": 0.003,
        "latency_ms": 1200,
        "accuracy": 0.95,
        "data_tier": "internal",
        "prompt_version": "v1.0",
    }
    
    transition = trainer.on_trace_received(sample_trace)
    print(f"Composite reward: {transition['reward']:.3f}")
    
    report = trainer.run_health_check()
    print(f"Health status: {report['status']}")
