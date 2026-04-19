from datetime import datetime, timezone

from stc_framework.trainer.history_store import HistoryRecord, InMemoryHistoryStore
from stc_framework.trainer.optimizer import OptimizationManager


def _rec(model: str, accuracy: float, cost: float) -> HistoryRecord:
    return HistoryRecord(
        model_used=model,
        accuracy=accuracy,
        cost_usd=cost,
        latency_ms=100,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def test_performance_flags_accuracy_below(minimal_spec):
    store = InMemoryHistoryStore()
    for _ in range(5):
        store.add(_rec("mock/public", 0.5, 0.01))
    opt = OptimizationManager(minimal_spec, store)
    report = opt.evaluate_performance(window_hours=1)
    assert report["status"] == "maintenance_recommended"
    assert "accuracy_below_threshold" in report["triggers"]


def test_routing_suggestions_ranks_by_cost_adjusted_accuracy(minimal_spec):
    store = InMemoryHistoryStore()
    for _ in range(5):
        store.add(_rec("mock/public", 0.9, 0.05))  # expensive
        store.add(_rec("mock/local", 0.9, 0.0001))  # cheap
    opt = OptimizationManager(minimal_spec, store)
    ordered = opt.ordered_models_for_tier("public")
    assert ordered[0] == "mock/local"


def test_insufficient_data_returns_status(minimal_spec):
    opt = OptimizationManager(minimal_spec, InMemoryHistoryStore())
    report = opt.evaluate_performance()
    assert report["status"] == "insufficient_data"
