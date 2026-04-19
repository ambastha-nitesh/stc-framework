"""Agent Lightning bridge.

Transforms traces into the RL transition tuple format and forwards them to
a :class:`LightningRecorder`. The default recorder keeps transitions in an
in-process ring buffer so health checks and analysis still work when
Agent Lightning is not installed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stc_framework.adapters.lightning.base import LightningRecorder, Transition
from stc_framework.adapters.lightning.inmemory_recorder import InMemoryRecorder
from stc_framework.spec.models import STCSpec
from stc_framework.trainer.reward import RewardComputer, RewardSignal


class AgentLightningBridge:
    """Publishes RL transitions from Stalwart traces."""

    def __init__(
        self,
        spec: STCSpec,
        reward_computer: RewardComputer,
        *,
        recorder: LightningRecorder | None = None,
    ) -> None:
        self._spec = spec
        self._rewards = reward_computer
        self._recorder = recorder or InMemoryRecorder()

    @property
    def recorder(self) -> LightningRecorder:
        return self._recorder

    def lightning_config(self) -> dict[str, Any]:
        """Configuration payload suitable for an Agent Lightning server."""
        return {
            "algorithm": self._spec.trainer.optimization.algorithm,
            "reward_functions": [
                {
                    "name": "stc_composite_reward",
                    "signals": [s.model_dump() for s in self._spec.trainer.optimization.reward_signals],
                }
            ],
            "agent_framework": self._spec.stalwart.framework,
            "trace_collection": {
                "method": "opentelemetry_sidecar",
                "endpoint": self._spec.audit.phoenix_host,
            },
            "optimization_targets": [loop.name for loop in self._spec.trainer.optimization.optimization_loops],
        }

    async def process_trace(self, trace: dict[str, Any]) -> Transition:
        signals = self._rewards.compute_all(trace)
        reward = self._rewards.composite(signals)
        transition = Transition(
            trace_id=trace.get("trace_id", ""),
            state={
                "query": trace.get("query", ""),
                "context_length": len(trace.get("context", "") or ""),
                "num_chunks": len(trace.get("retrieved_chunks", []) or []),
            },
            action={
                "model_used": trace.get("model_used"),
                "prompt_version": trace.get("prompt_version"),
            },
            reward=reward,
            signals=[_signal_dict(s) for s in signals],
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await self._recorder.record(transition)
        return transition


def _signal_dict(signal: RewardSignal) -> dict[str, Any]:
    return {"type": signal.signal_type, "value": signal.value}
