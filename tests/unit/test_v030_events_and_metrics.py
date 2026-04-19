"""Tests for v0.3.0 audit event names and metric additions."""

from __future__ import annotations

from stc_framework.governance.events import AuditEvent
from stc_framework.observability.metrics import get_metrics


def test_v030_audit_events_are_present() -> None:
    # Compliance
    assert AuditEvent.COMPLIANCE_VIOLATION.value == "compliance_violation"
    assert AuditEvent.LEGAL_HOLD_ISSUED.value == "legal_hold_issued"
    assert AuditEvent.DESTRUCTION_BLOCKED_BY_HOLD.value == "destruction_blocked_by_hold"
    # Risk
    assert AuditEvent.KRI_BREACH.value == "kri_breach"
    assert AuditEvent.OPTIMIZER_VETO.value == "optimizer_veto"
    # Threats
    assert AuditEvent.THREAT_DETECTED.value == "threat_detected"
    assert AuditEvent.HONEY_TOKEN_TRIGGERED.value == "honey_token_triggered"
    # Orchestration
    assert AuditEvent.WORKFLOW_STARTED.value == "workflow_started"
    assert AuditEvent.WORKFLOW_COMPLETED.value == "workflow_completed"
    # Catalog / lineage
    assert AuditEvent.ASSET_REGISTERED.value == "asset_registered"
    assert AuditEvent.LINEAGE_RECORDED.value == "lineage_recorded"
    # Perf / session
    assert AuditEvent.SLO_VIOLATION.value == "slo_violation"
    assert AuditEvent.SESSION_CREATED.value == "session_created"


def test_event_values_are_unique() -> None:
    values = [e.value for e in AuditEvent]
    assert len(values) == len(set(values)), "duplicate AuditEvent values"


def test_metrics_container_exposes_v030_fields() -> None:
    metrics = get_metrics()
    # Compliance
    assert metrics.compliance_checks_total is not None
    assert metrics.compliance_violations_total is not None
    # Risk
    assert metrics.risk_score is not None
    assert metrics.kri_status is not None
    # Threats
    assert metrics.threats_detected_total is not None
    assert metrics.ip_blocks_total is not None
    # Orchestration
    assert metrics.workflow_duration_ms is not None
    assert metrics.workflow_tasks_total is not None
    # Session & perf
    assert metrics.session_active is not None
    assert metrics.session_cost_usd_total is not None
    assert metrics.slo_violations_total is not None
    assert metrics.asset_quality_score is not None


def test_compliance_checks_counter_accepts_expected_labels() -> None:
    metrics = get_metrics()
    # Should not raise — labels match declared names.
    metrics.compliance_checks_total.labels(rule="finra_2210", outcome="pass").inc()
    metrics.compliance_violations_total.labels(rule="finra_2210", severity="high").inc()


def test_threats_counter_accepts_expected_labels() -> None:
    metrics = get_metrics()
    metrics.threats_detected_total.labels(threat_type="ddos_volumetric", severity="high").inc()
