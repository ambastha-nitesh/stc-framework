"""Tests for the v0.3.0 optional spec sections.

Every new section has sensible defaults so existing specs keep loading,
and the new fields round-trip through pydantic.
"""

from __future__ import annotations

from stc_framework.spec.models import (
    CompliancePolicySpec,
    ComplianceRuleSpec,
    KRIDefinitionSpec,
    OrchestrationSpec,
    PerfSpec,
    PrincipalApprovalConfig,
    RateLimitSpec,
    RiskAppetiteSpec,
    SessionStateSpec,
    SLOSpec,
    SovereigntySpec,
    StalwartRegistryEntry,
    STCSpec,
    ThreatDetectionSpec,
)


def test_stcspec_defaults_include_v030_sections() -> None:
    spec = STCSpec(
        version="1.0.0",
        name="test",
        data_sovereignty={
            "routing_policy": {
                "public": ["gpt-4"],
                "internal": ["gpt-4"],
                "restricted": ["local/llama"],
            }
        },
    )
    # Every v0.3.0 section is present and disabled by default so existing
    # workloads are unaffected.
    assert spec.compliance_profile.rules == []
    assert spec.compliance_profile.legal_hold_enabled is True  # default on
    assert spec.orchestration.enabled is False
    assert spec.threat_detection.enabled is False
    assert spec.session_state.enabled is False
    assert spec.perf.enabled is False
    assert spec.risk_appetite.veto_on_kri_red is True


def test_compliance_policy_rule_lookup() -> None:
    policy = CompliancePolicySpec(
        rules=[
            ComplianceRuleSpec(name="finra_2210", severity="high"),
            ComplianceRuleSpec(name="reg_bi", severity="critical"),
        ]
    )
    assert policy.rule_by_name("finra_2210") is not None
    assert policy.rule_by_name("finra_2210").severity == "high"
    assert policy.rule_by_name("missing") is None


def test_principal_approval_defaults() -> None:
    cfg = PrincipalApprovalConfig()
    assert cfg.enabled is False
    assert cfg.sla_hours == 24
    assert cfg.auto_approve_below_severity == "low"


def test_sovereignty_defaults_allow_only_trusted_and_cautious() -> None:
    s = SovereigntySpec()
    assert set(s.allowed_origin_risks) == {"trusted", "cautious"}
    assert s.allowed_inference_jurisdictions == ["US"]
    assert s.require_fips_for_restricted is True


def test_risk_appetite_weights_sum_to_one_by_default() -> None:
    r = RiskAppetiteSpec()
    assert round(sum(r.decision_weights.values()), 6) == 1.0


def test_kri_definition_round_trip() -> None:
    k = KRIDefinitionSpec(
        kri_id="kri-1",
        name="Accuracy",
        direction="lower_is_worse",
        amber_threshold=0.9,
        red_threshold=0.8,
        linked_risks=["r-1", "r-2"],
    )
    assert k.linked_risks == ["r-1", "r-2"]
    assert k.direction == "lower_is_worse"


def test_orchestration_stalwart_registry() -> None:
    o = OrchestrationSpec(
        enabled=True,
        stalwart_registry=[
            StalwartRegistryEntry(
                stalwart_id="s-retriever",
                capabilities=["retrieval", "summarisation"],
                cost_weight=0.5,
            )
        ],
    )
    assert o.stalwart_registry[0].capabilities == ["retrieval", "summarisation"]
    assert o.max_workflow_cost_usd == 5.0


def test_threat_detection_defaults() -> None:
    t = ThreatDetectionSpec()
    assert isinstance(t.rate_limits, RateLimitSpec)
    assert t.rate_limits.per_minute == 60
    assert t.behavioral.critic_failure_rate_red == 0.3
    assert t.ip_block_duration_seconds == 900
    assert t.deception.honey_docs == []


def test_session_state_redis_optional() -> None:
    s = SessionStateSpec(enabled=True, backend="redis", redis_url="redis://localhost:6379/0")
    assert s.backend == "redis"
    assert s.redis_url == "redis://localhost:6379/0"


def test_perf_slo_and_load_profile() -> None:
    p = PerfSpec(
        enabled=True,
        slos=[SLOSpec(name="p95", target=500.0, unit="ms", measurement="p95")],
    )
    assert p.slos[0].name == "p95"
    assert p.slos[0].target == 500.0
    assert p.regression_threshold_percent == 10.0
