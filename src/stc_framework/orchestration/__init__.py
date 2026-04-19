"""Multi-Stalwart orchestration.

A workflow engine coordinates multiple Stalwart agents on a single
goal. Each task is dispatched to a capability-matched Stalwart, run
through the standard Sentinel/Critic pipeline, and the results are
aggregated by a workflow-level Critic.

LangGraph is the preferred backend when installed; a simulation engine
provides identical semantics (minus interrupt-before hooks) for
zero-install development and testing.
"""

from stc_framework.orchestration.registry import StalwartRegistration, StalwartRegistry
from stc_framework.orchestration.simulation import SimulationEngine
from stc_framework.orchestration.workflow import (
    TaskRequest,
    TaskResult,
    WorkflowOrchestrator,
    WorkflowState,
)

__all__ = [
    "SimulationEngine",
    "StalwartRegistration",
    "StalwartRegistry",
    "TaskRequest",
    "TaskResult",
    "WorkflowOrchestrator",
    "WorkflowState",
]
