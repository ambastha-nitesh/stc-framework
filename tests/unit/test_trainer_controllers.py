"""Tests for the Trainer's action-taking controllers."""

from __future__ import annotations

from pathlib import Path

import pytest

from stc_framework.adapters.llm.mock import MockLLMClient
from stc_framework.adapters.prompts.base import PromptRecord
from stc_framework.adapters.prompts.file_registry import FilePromptRegistry
from stc_framework.resilience.degradation import DegradationLevel, DegradationState
from stc_framework.sentinel.classifier import DataClassifier
from stc_framework.sentinel.gateway import SentinelGateway
from stc_framework.sentinel.redaction import PIIRedactor
from stc_framework.trainer.history_store import HistoryRecord, InMemoryHistoryStore
from stc_framework.trainer.maintenance import MaintenanceExecutor
from stc_framework.trainer.optimizer import OptimizationManager
from stc_framework.trainer.prompt_controller import PromptController
from stc_framework.trainer.routing_controller import RoutingController


def _build_gateway(spec) -> SentinelGateway:
    return SentinelGateway(
        spec,
        MockLLMClient(),
        redactor=PIIRedactor(spec, presidio_enabled=False),
        classifier=DataClassifier(spec, presidio_enabled=False),
    )


def test_routing_controller_reorders_tier(minimal_spec):
    gateway = _build_gateway(minimal_spec)
    history = InMemoryHistoryStore()
    for _ in range(4):
        history.add(
            HistoryRecord(
                model_used="mock/local",
                accuracy=0.9,
                cost_usd=0.001,
                latency_ms=100,
                timestamp="2026-04-18T00:00:00+00:00",
            )
        )
        history.add(
            HistoryRecord(
                model_used="mock/public",
                accuracy=0.9,
                cost_usd=0.05,
                latency_ms=100,
                timestamp="2026-04-18T00:00:00+00:00",
            )
        )

    controller = RoutingController(gateway, OptimizationManager(minimal_spec, history))
    applied = controller.apply(tiers=["public"])
    assert applied["public"][0] == "mock/local"
    assert gateway.get_routing("public")[0] == "mock/local"


@pytest.mark.asyncio
async def test_prompt_controller_publish_and_activate(tmp_path: Path):
    registry = FilePromptRegistry(tmp_path / "p.json")
    registry.seed([PromptRecord(name="p", version="v1", content="old", active=True)])
    controller = PromptController(registry)
    await controller.publish(name="p", version="v2", content="new", activate=True)
    active = await registry.get("p")
    assert active.version == "v2"
    assert active.content == "new"


@pytest.mark.asyncio
async def test_maintenance_executor_pauses_on_trigger(minimal_spec):
    # Coerce the spec to the "pause" action to exercise that branch.
    minimal_spec.trainer.maintenance_mode.action = "pause"
    state = DegradationState()
    executor = MaintenanceExecutor(minimal_spec, degradation=state)
    await executor.apply({"triggers": ["accuracy_below_threshold"]})
    assert state.level == DegradationLevel.PAUSED


@pytest.mark.asyncio
async def test_maintenance_executor_degrades(minimal_spec):
    minimal_spec.trainer.maintenance_mode.action = "degrade"
    state = DegradationState()
    executor = MaintenanceExecutor(minimal_spec, degradation=state)
    await executor.apply({"triggers": ["latency_above_threshold"]})
    assert state.level == DegradationLevel.DEGRADED


@pytest.mark.asyncio
async def test_maintenance_executor_noop_when_healthy(minimal_spec):
    state = DegradationState()
    state.set(DegradationLevel.DEGRADED, source="test")
    executor = MaintenanceExecutor(minimal_spec, degradation=state)
    await executor.apply({"triggers": []})
    assert state.level == DegradationLevel.NORMAL
