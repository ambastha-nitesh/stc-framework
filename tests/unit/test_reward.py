import pytest

from stc_framework.trainer.reward import RewardComputer


def test_factual_accuracy_all_grounded(minimal_spec):
    r = RewardComputer(minimal_spec)
    sig = r.compute_factual_accuracy(
        {
            "trace_id": "t",
            "response": "Revenue was $4.2 billion.",
            "retrieved_chunks": [{"text": "Revenue was $4.2 billion YoY"}],
        }
    )
    assert sig.value > 0.0


def test_factual_accuracy_no_numbers(minimal_spec):
    r = RewardComputer(minimal_spec)
    sig = r.compute_factual_accuracy(
        {"trace_id": "t", "response": "Uncertain.", "retrieved_chunks": [{"text": "blah"}]}
    )
    assert sig.value == 1.0


def test_retrieval_quality_averages(minimal_spec):
    r = RewardComputer(minimal_spec)
    sig = r.compute_retrieval_quality({"trace_id": "t", "retrieval_scores": [0.8, 0.9, 0.7]})
    assert sig.value == pytest.approx(0.8, abs=1e-6)


def test_composite_weighted(minimal_spec):
    r = RewardComputer(minimal_spec)
    signals = r.compute_all({"trace_id": "t", "retrieval_scores": [1.0]})
    score = r.composite(signals)
    assert 0.0 <= score <= 1.0


