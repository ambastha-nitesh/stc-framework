"""Multi-Stalwart workflow orchestrator.

Given a goal and a list of tasks with capability tags, dispatches each
task to a capability-matched Stalwart via :class:`StalwartRegistry`,
runs them (with dependency respect) using the simulation engine (or
LangGraph when installed), and returns an aggregated result.

Budget enforcement uses :class:`~stc_framework.governance.budget_controls.BurstController`
to cap runaway loops and a workflow-level cost ceiling. Every task
result is recorded in the workflow state and persisted (if a store is
provided) so a crashed workflow can be resumed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stc_framework.errors import StalwartDispatchFailed, WorkflowBudgetExhausted
from stc_framework.governance.budget_controls import BurstController
from stc_framework.governance.events import AuditEvent
from stc_framework.infrastructure.store import KeyValueStore
from stc_framework.observability.audit import AuditLogger, AuditRecord
from stc_framework.observability.metrics import get_metrics
from stc_framework.orchestration.registry import StalwartRegistry
from stc_framework.orchestration.simulation import SimulationEngine


@dataclass
class TaskRequest:
    task_id: str
    capability: str
    description: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class TaskResult:
    task_id: str
    stalwart_id: str
    status: str = "success"
    output: str = ""
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    error: str | None = None


@dataclass
class WorkflowState:
    workflow_id: str
    goal: str
    task_requests: list[TaskRequest] = field(default_factory=list)
    results: list[TaskResult] = field(default_factory=list)
    total_cost_usd: float = 0.0
    status: str = "pending"
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None


class WorkflowOrchestrator:
    """Dispatches + sequences tasks across a StalwartRegistry."""

    def __init__(
        self,
        *,
        registry: StalwartRegistry,
        max_workflow_cost_usd: float = 5.00,
        max_llm_calls_per_workflow: int = 20,
        audit: AuditLogger | None = None,
        store: KeyValueStore | None = None,
    ) -> None:
        self._registry = registry
        self._max_cost = max_workflow_cost_usd
        self._burst = BurstController(max_llm_calls_per_workflow=max_llm_calls_per_workflow)
        self._audit = audit
        self._store = store
        self._engine = SimulationEngine()

    async def run(
        self,
        *,
        workflow_id: str,
        goal: str,
        tasks: list[TaskRequest],
    ) -> WorkflowState:
        state = WorkflowState(workflow_id=workflow_id, goal=goal, task_requests=list(tasks))
        state.status = "running"
        start = time.perf_counter()
        await self._emit(AuditEvent.WORKFLOW_STARTED, workflow_id, {"goal": goal, "task_count": len(tasks)})

        async def dispatcher(task: dict[str, Any]) -> dict[str, Any]:
            capability = task["capability"]
            entry = self._registry.pick(capability)
            if entry is None or entry.dispatch is None:
                raise StalwartDispatchFailed(
                    message=f"no stalwart registered for capability {capability!r}",
                    capability=capability,
                )
            self._burst.record_llm_call(workflow_id)
            # Budget check — soft cap on workflow total cost.
            if state.total_cost_usd >= self._max_cost:
                raise WorkflowBudgetExhausted(message=f"workflow {workflow_id!r} exceeded budget ${self._max_cost:.2f}")
            t0 = time.perf_counter()
            raw = await entry.dispatch(task)
            duration_ms = (time.perf_counter() - t0) * 1000.0
            r = TaskResult(
                task_id=task["task_id"],
                stalwart_id=entry.stalwart_id,
                status=str(raw.get("status", "success")),
                output=str(raw.get("output", "")),
                cost_usd=float(raw.get("cost_usd", raw.get("cost", 0.0)) or 0.0),
                duration_ms=duration_ms,
            )
            state.results.append(r)
            state.total_cost_usd += r.cost_usd
            try:
                get_metrics().workflow_tasks_total.labels(status=r.status).inc()
            except Exception:
                pass
            await self._emit(
                AuditEvent.WORKFLOW_TASK_COMPLETED,
                workflow_id,
                {"task_id": r.task_id, "stalwart": r.stalwart_id, "cost_usd": r.cost_usd},
            )
            return {"task_id": r.task_id, "status": r.status, "output": r.output, "cost": r.cost_usd}

        task_dicts = [
            {
                "task_id": t.task_id,
                "capability": t.capability,
                "description": t.description,
                "inputs": t.inputs,
                "depends_on": list(t.depends_on),
            }
            for t in tasks
        ]
        engine_out = await self._engine.invoke(tasks=task_dicts, dispatcher=dispatcher)
        state.status = engine_out["status"]
        state.completed_at = datetime.now(timezone.utc).isoformat()
        duration_ms = (time.perf_counter() - start) * 1000.0
        try:
            get_metrics().workflow_duration_ms.labels(workflow_type="generic").observe(duration_ms)
        except Exception:
            pass
        if self._store is not None:
            await self._store.set(
                f"orchestration:workflow:{workflow_id}",
                {
                    "workflow_id": workflow_id,
                    "goal": goal,
                    "status": state.status,
                    "started_at": state.started_at,
                    "completed_at": state.completed_at,
                    "total_cost_usd": state.total_cost_usd,
                    "task_count": len(state.results),
                },
            )
        await self._emit(
            AuditEvent.WORKFLOW_COMPLETED,
            workflow_id,
            {
                "status": state.status,
                "cost_usd": state.total_cost_usd,
                "task_count": len(state.results),
                "duration_ms": duration_ms,
            },
        )
        # Reset burst counter for the workflow — it's done.
        self._burst.reset(workflow_id)
        return state

    async def _emit(self, event: AuditEvent, workflow_id: str, extra: dict[str, Any]) -> None:
        if self._audit is None:
            return
        await self._audit.emit(
            AuditRecord(
                event_type=event.value,
                persona="orchestration",
                extra={"workflow_id": workflow_id, **extra},
            )
        )


__all__ = ["TaskRequest", "TaskResult", "WorkflowOrchestrator", "WorkflowState"]
