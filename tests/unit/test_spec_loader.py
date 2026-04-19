
import pytest

from stc_framework.errors import SpecValidationError
from stc_framework.spec.loader import load_spec, spec_from_dict, validate_spec


def test_load_minimal_spec_parses(minimal_spec):
    assert minimal_spec.version == "1.0.0"
    assert minimal_spec.critic.guardrails.output_rails
    assert minimal_spec.routing_for("restricted") == ["mock/local"]


def test_load_example_spec_parses(financial_spec):
    assert financial_spec.name == "financial-doc-qa"
    assert financial_spec.routing_for("restricted")
    assert financial_spec.trainer.optimization.reward_signals


def test_missing_routing_tier_raises():
    data = {
        "version": "1.0.0",
        "name": "bad",
        "data_sovereignty": {"routing_policy": {"public": ["x"]}},
    }
    with pytest.raises(SpecValidationError):
        spec_from_dict(data)


def test_empty_routing_list_raises():
    data = {
        "version": "1.0.0",
        "name": "bad",
        "data_sovereignty": {
            "routing_policy": {
                "public": [],
                "internal": ["x"],
                "restricted": ["y"],
            }
        },
    }
    with pytest.raises(SpecValidationError):
        spec_from_dict(data)


def test_validate_spec_reports_reward_weight_drift(minimal_spec):
    # Craft a spec whose reward weights sum to 2.0
    minimal_spec.trainer.optimization.reward_signals[0].weight = 1.0
    minimal_spec.trainer.optimization.reward_signals[1].weight = 1.0
    warnings = validate_spec(minimal_spec)
    assert any("weights sum" in w.lower() for w in warnings)


def test_env_interpolation(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MODEL", "mock/abc")
    path = tmp_path / "spec.yaml"
    path.write_text(
        """
version: "1.0.0"
name: "interp"
data_sovereignty:
  routing_policy:
    public: ["${TEST_MODEL}"]
    internal: ["mock/internal"]
    restricted: ["mock/local"]
""",
        encoding="utf-8",
    )
    spec = load_spec(path)
    assert spec.routing_for("public") == ["mock/abc"]
