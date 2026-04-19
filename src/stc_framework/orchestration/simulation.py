"""Pure-Python simulation engine for multi-task workflows.

Used when LangGraph is not installed. Runs the task list sequentially
(respecting declared dependencies) and emits the same final state dict
LangGraph would.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stc_framework.errors import OrchestrationError


@dataclass
class SimulationConfig:
    max_tasks: int = 20
    fail_fast: bool = True


class SimulationEngine:
    """Minimal task runner: resolves dependencies + executes via registry."""

    def __init__(self, config: SimulationConfig | None = None) -> None:
        self._cfg = config or SimulationConfig()

    async def invoke(
        self,
        *,
        tasks: list[dict[str, Any]],
        dispatcher: Any,
    ) -> dict[str, Any]:
        """Dispatcher is async: ``dispatcher(task_dict) -> result_dict``."""
        if len(tasks) > self._cfg.max_tasks:
            raise ValueError(f"task count {len(tasks)} exceeds cap {self._cfg.max_tasks}")
        results: list[dict[str, Any]] = []
        total_cost = 0.0
        # Simple topo sort using task.task_id + task.depends_on.
        completed: set[str] = set()
        remaining = list(tasks)
        rounds = 0
        while remaining:
            rounds += 1
            if rounds > len(tasks) + 1:
                # Dependency cycle — fail fast.
                raise ValueError("dependency cycle detected in tasks")
            to_run = [t for t in remaining if all(d in completed for d in t.get("depends_on", []))]
            if not to_run:
                raise ValueError("no runnable tasks — check dependency declarations")
            for task in to_run:
                try:
                    r = await dispatcher(task)
                except OrchestrationError:
                    # Typed framework errors (dispatch failures, budget
                    # exhaustion) propagate so the caller can translate
                    # them into HTTP responses / fallbacks directly.
                    raise
                except Exception as exc:
                    results.append(
                        {
                            "task_id": task["task_id"],
                            "status": "error",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    if self._cfg.fail_fast:
                        return {
                            "status": "error",
                            "results": results,
                            "total_cost": total_cost,
                            "completed_tasks": len(completed),
                        }
                    completed.add(task["task_id"])
                    continue
                results.append(r)
                completed.add(task["task_id"])
                total_cost += float(r.get("cost", 0.0))
            remaining = [t for t in remaining if t["task_id"] not in completed]
        return {
            "status": "success",
            "results": results,
            "total_cost": total_cost,
            "completed_tasks": len(completed),
        }


__all__ = ["SimulationConfig", "SimulationEngine"]
