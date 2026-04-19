"""Trainer: optimization and control plane."""

from stc_framework.trainer.history_store import (
    HistoryRecord,
    HistoryStore,
    InMemoryHistoryStore,
    SQLiteHistoryStore,
)
from stc_framework.trainer.lightning_bridge import AgentLightningBridge
from stc_framework.trainer.maintenance import MaintenanceExecutor
from stc_framework.trainer.notifications import Notifier
from stc_framework.trainer.optimizer import OptimizationManager
from stc_framework.trainer.prompt_controller import PromptController
from stc_framework.trainer.reward import RewardComputer, RewardSignal
from stc_framework.trainer.routing_controller import RoutingController
from stc_framework.trainer.trainer import Trainer

__all__ = [
    "AgentLightningBridge",
    "HistoryRecord",
    "HistoryStore",
    "InMemoryHistoryStore",
    "MaintenanceExecutor",
    "Notifier",
    "OptimizationManager",
    "PromptController",
    "RewardComputer",
    "RewardSignal",
    "RoutingController",
    "SQLiteHistoryStore",
    "Trainer",
]
