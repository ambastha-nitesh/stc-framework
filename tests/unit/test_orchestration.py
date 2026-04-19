"""Tests for :mod:`stc_framework.orchestration`."""

from __future__ import annotations

import pytest

from stc_framework.errors import StalwartDispatchFailed, WorkflowBudgetExhausted
from stc_framework.infrastructure.store import InMemoryStore
from stc_framework.orchestration import (
    SimulationEngine,
    StalwartRegistration,
    StalwartRegistry,
    TaskRequest,
    WorkflowOrchestrator,
)


def test_registry_capability_match_and_pick() -> None:
    reg = StalwartRegistry()
    reg.register(StalwartRegistration(stalwart_id="a", capabilities=("retrieval",), cost_weight=2.0))
    reg.register(StalwartRegistration(stalwart_id="b", capabilities=("retrieval",), cost_weight=0.5))
    picked = reg.pick("retrieval")
    assert picked is not None
    assert picked.stalwart_id == "b"  # lowest cost weight


def test_registry_unmatched_capability_returns_none() -> None:
    reg = StalwartRegistry()
    assert reg.pick("does-not-exist") is None


@pytest.mark.asyncio
async def test_simulation_engine_runs_tasks_in_dependency_order() -> None:
    engine = SimulationEngine()
    executed: list[str] = []

    async def dispatcher(task: dict) -> dict:  # type: ignore[no-untyped-def]
        executed.append(task["task_id"])
        return {"task_id": task["task_id"], "status": "success", "cost": 0.01}

    tasks = [
        {"task_id": "t2", "depends_on": ["t1"], "capability": "x"},
        {"task_id": "t1", "capability": "x"},
    ]
    out = await engine.invoke(tasks=tasks, dispatcher=dispatcher)
    assert out["status"] == "success"
    assert executed == ["t1", "t2"]
    assert out["completed_tasks"] == 2


@pytest.mark.asyncio
async def test_simulation_engine_detects_dependency_cycle() -> None:
    engine = SimulationEngine()

    async def dispatcher(_task: dict) -> dict:  # type: ignore[no-untyped-def]
        return {"status": "success"}

    tasks = [
        {"task_id": "a", "depends_on": ["b"], "capability": "x"},
        {"task_id": "b", "depends_on": ["a"], "capability": "x"},
    ]
    with pytest.raises(ValueError):
        await engine.invoke(tasks=tasks, dispatcher=dispatcher)


@pytest.mark.asyncio
async def test_orchestrator_dispatches_via_registry() -> None:
    reg = StalwartRegistry()
    calls: list[str] = []

    async def retriever(task: dict) -> dict:  # type: ignore[no-untyped-def]
        calls.append(task["task_id"])
        return {"status": "success", "output": "chunks", "cost_usd": 0.01}

    reg.register(StalwartRegistration(stalwart_id="retr", capabilities=("retrieval",), dispatch=retriever))
    orchestrator = WorkflowOrchestrator(registry=reg, max_workflow_cost_usd=1.00)
    state = await orchestrator.run(
        workflow_id="wf-1",
        goal="test",
        tasks=[TaskRequest(task_id="t1", capability="retrieval")],
    )
    assert state.status == "success"
    assert calls == ["t1"]
    assert state.total_cost_usd == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_orchestrator_unmatched_capability_fails() -> None:
    reg = StalwartRegistry()
    orchestrator = WorkflowOrchestrator(registry=reg)
    with pytest.raises(StalwartDispatchFailed):
        await orchestrator.run(
            workflow_id="wf-x",
            goal="g",
            tasks=[TaskRequest(task_id="t1", capability="missing")],
        )


@pytest.mark.asyncio
async def test_orchestrator_budget_cap_enforced() -> None:
    reg = StalwartRegistry()

    async def expensive(_task: dict) -> dict:  # type: ignore[no-untyped-def]
        return {"status": "success", "output": "x", "cost_usd": 5.0}

    reg.register(StalwartRegistration(stalwart_id="a", capabilities=("x",), dispatch=expensive))
    orchestrator = WorkflowOrchestrator(registry=reg, max_workflow_cost_usd=3.0)
    with pytest.raises(WorkflowBudgetExhausted):
        await orchestrator.run(
            workflow_id="wf-1",
            goal="",
            tasks=[
                TaskRequest(task_id="t1", capability="x"),
                TaskRequest(task_id="t2", capability="x", depends_on=["t1"]),
            ],
        )


@pytest.mark.asyncio
async def test_orchestrator_persists_to_store() -> None:
    reg = StalwartRegistry()

    async def disp(_task: dict) -> dict:  # type: ignore[no-untyped-def]
        return {"status": "success", "cost_usd": 0.01}

    reg.register(StalwartRegistration(stalwart_id="x", capabilities=("x",), dispatch=disp))
    store = InMemoryStore()
    orchestrator = WorkflowOrchestrator(registry=reg, store=store)
    await orchestrator.run(
        workflow_id="wf-persist",
        goal="",
        tasks=[TaskRequest(task_id="t1", capability="x")],
    )
    persisted = await store.get("orchestration:workflow:wf-persist")
    assert persisted is not None
    assert persisted["status"] == "success"
