"""Tests for the v0.3.0 error taxonomy additions."""

from __future__ import annotations

from stc_framework.errors import (
    BehavioralAnomalyDetected,
    ComplianceViolation,
    DDoSDetected,
    DisclosureMissing,
    FINRARuleViolation,
    HoneyTokenTriggered,
    KRIRedVeto,
    LegalHoldActive,
    OrchestrationError,
    RegBIUnsuitable,
    RiskAppetiteBreach,
    RiskAssessmentError,
    RiskOptimizerVeto,
    SessionBackendUnavailable,
    SessionExpired,
    SessionStateError,
    StalwartDispatchFailed,
    STCError,
    ThreatDetected,
    WorkflowBudgetExhausted,
    WorkflowCriticRejected,
    http_status_for,
)


def test_compliance_violations_subclass_stcerror() -> None:
    for cls in (
        ComplianceViolation,
        FINRARuleViolation,
        RegBIUnsuitable,
        DisclosureMissing,
        LegalHoldActive,
    ):
        assert issubclass(cls, STCError)
        # retryable default for compliance violations is False.
        assert cls(message="x").retryable is False


def test_legal_hold_active_carries_hold_id() -> None:
    err = LegalHoldActive(message="blocked", hold_id="hold-123")
    assert err.hold_id == "hold-123"


def test_risk_assessment_errors_hierarchy() -> None:
    assert issubclass(KRIRedVeto, RiskAssessmentError)
    assert issubclass(RiskAppetiteBreach, RiskAssessmentError)
    assert issubclass(RiskOptimizerVeto, RiskAssessmentError)
    kri = KRIRedVeto(message="kri red", kri_id="kri-accuracy")
    assert kri.kri_id == "kri-accuracy"
    assert kri.retryable is False


def test_threat_errors_carry_type_and_severity() -> None:
    assert issubclass(DDoSDetected, ThreatDetected)
    assert issubclass(HoneyTokenTriggered, ThreatDetected)
    assert issubclass(BehavioralAnomalyDetected, ThreatDetected)
    t = ThreatDetected(message="x", threat_type="ddos_volumetric", severity="critical")
    assert t.threat_type == "ddos_volumetric"
    assert t.severity == "critical"


def test_orchestration_error_subclasses() -> None:
    assert issubclass(WorkflowBudgetExhausted, OrchestrationError)
    assert issubclass(StalwartDispatchFailed, OrchestrationError)
    assert issubclass(WorkflowCriticRejected, OrchestrationError)
    err = StalwartDispatchFailed(message="no match", capability="retrieval")
    assert err.capability == "retrieval"


def test_session_errors_retryable_semantics() -> None:
    assert SessionExpired(message="x").retryable is False
    assert SessionBackendUnavailable(message="x").retryable is True
    assert issubclass(SessionExpired, SessionStateError)


def test_http_status_mapping_for_v030_errors() -> None:
    # Compliance → 422 for content-level rejections, 423 for legal hold.
    assert http_status_for(FINRARuleViolation(message="x")) == 422
    assert http_status_for(RegBIUnsuitable(message="x")) == 422
    assert http_status_for(DisclosureMissing(message="x")) == 422
    assert http_status_for(LegalHoldActive(message="x")) == 423

    # Risk — appetite breach is 403; KRI/optimizer vetoes are 503.
    assert http_status_for(RiskAppetiteBreach(message="x")) == 403
    assert http_status_for(KRIRedVeto(message="x")) == 503
    assert http_status_for(RiskOptimizerVeto(message="x")) == 503

    # Threats — DDoS is 429; others 403.
    assert http_status_for(DDoSDetected(message="x")) == 429
    assert http_status_for(HoneyTokenTriggered(message="x")) == 403
    assert http_status_for(BehavioralAnomalyDetected(message="x")) == 403

    # Orchestration.
    assert http_status_for(WorkflowBudgetExhausted(message="x")) == 402
    assert http_status_for(StalwartDispatchFailed(message="x")) == 503
    assert http_status_for(WorkflowCriticRejected(message="x")) == 502

    # Session.
    assert http_status_for(SessionExpired(message="x")) == 440
    assert http_status_for(SessionBackendUnavailable(message="x")) == 503
