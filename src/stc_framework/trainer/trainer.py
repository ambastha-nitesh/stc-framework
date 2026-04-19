"""Trainer orchestrator.

Glues reward computation, history persistence, optimization evaluation,
routing control, maintenance, and Agent Lightning into a single object
that the :class:`STCSystem` can consult on every trace.
"""

from __future__ import annotations

from typing import Any

from stc_framework.adapters.lightning.base import LightningRecorder, Transition
from stc_framework.adapters.prompts.base import PromptRegistry
from stc_framework.config.logging import get_logger
from stc_framework.observability.audit import AuditLogger
from stc_framework.sentinel.gateway import SentinelGateway
from stc_framework.spec.models import STCSpec
from stc_framework.trainer.history_store import (
    HistoryStore,
    InMemoryHistoryStore,
    record_from_trace,
)
from stc_framework.trainer.lightning_bridge import AgentLightningBridge
from stc_framework.trainer.maintenance import MaintenanceExecutor
from stc_framework.trainer.optimizer import OptimizationManager
from stc_framework.trainer.prompt_controller import PromptController
from stc_framework.trainer.reward import RewardComputer
from stc_framework.trainer.routing_controller import RoutingController

_logger = get_logger(__name__)


class Trainer:
    def __init__(
        self,
        spec: STCSpec,
        gateway: SentinelGateway,
        prompt_registry: PromptRegistry,
        *,
        history: HistoryStore | None = None,
        lightning_recorder: LightningRecorder | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self._spec = spec
        self._history = history or InMemoryHistoryStore()
        self._rewards = RewardComputer(spec)
        self._optimizer = OptimizationManager(spec, self._history)
        self._routing = RoutingController(gateway, self._optimizer, audit=audit)
        self._prompts = PromptController(prompt_registry, audit=audit)
        self._lightning = AgentLightningBridge(spec, self._rewards, recorder=lightning_recorder)
        self._maintenance = MaintenanceExecutor(spec)

    # --------------------------- trace ingestion ---------------------------

    async def on_trace(self, trace: dict[str, Any]) -> Transition:
        self._history.add(record_from_trace(trace))
        transition = await self._lightning.process_trace(trace)
        _logger.info(
            "trainer.trace",
            trace_id=trace.get("trace_id"),
            model_used=trace.get("model_used"),
            reward=round(transition.reward, 4),
        )
        return transition

    def on_user_feedback(self, trace_id: str, feedback: str) -> None:
        signal = self._rewards.compute_user_feedback(trace_id, feedback)
        _logger.info(
            "trainer.user_feedback",
            trace_id=trace_id,
            feedback=feedback,
            value=signal.value,
        )

    # --------------------------- health / optimization --------------------

    async def run_health_check(self, *, window_hours: int = 24) -> dict[str, Any]:
        report = self._optimizer.evaluate_performance(window_hours=window_hours)
        await self._maintenance.apply(report)
        return report

    def apply_routing_optimization(self) -> dict[str, list[str]]:
        return self._routing.apply()

    async def publish_prompt(self, *, name: str, version: str, content: str, activate: bool = True) -> None:
        await self._prompts.publish(name=name, version=version, content=content, activate=activate)

    # --------------------------- accessors --------------------------------

    @property
    def optimizer(self) -> OptimizationManager:
        return self._optimizer

    @property
    def lightning(self) -> AgentLightningBridge:
        return self._lightning

    @property
    def rewards(self) -> RewardComputer:
        return self._rewards

    @property
    def history(self) -> HistoryStore:
        return self._history
