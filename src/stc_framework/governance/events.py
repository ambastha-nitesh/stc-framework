"""Canonical audit event names.

Using a single enum keeps audit record ``event_type`` values consistent
across the codebase and makes it trivial to ensure we audit every action
that a regulator might need to trace.
"""

from __future__ import annotations

from enum import Enum


class AuditEvent(str, Enum):
    # ----- Request lifecycle ------------------------------------------------
    QUERY_ACCEPTED = "query_accepted"
    QUERY_COMPLETED = "query_completed"
    QUERY_REJECTED = "query_rejected"  # boundary rejection (size, type, injection)
    FEEDBACK_SUBMITTED = "feedback_submitted"

    # ----- Sentinel ---------------------------------------------------------
    LLM_CALL = "llm_call"
    BOUNDARY_CROSSING = "boundary_crossing"
    REDACTION = "redaction"
    TOKENIZATION = "tokenization"
    DATA_SOVEREIGNTY_VIOLATION = "data_sovereignty_violation"

    # ----- Critic -----------------------------------------------------------
    RAIL_EVALUATED = "rail_evaluated"
    RAIL_FAILED = "rail_failed"
    ESCALATION_TRANSITION = "escalation_transition"

    # ----- Trainer ----------------------------------------------------------
    ROUTING_UPDATED = "routing_updated"
    PROMPT_REGISTERED = "prompt_registered"
    PROMPT_ACTIVATED = "prompt_activated"
    MAINTENANCE_TRIGGERED = "maintenance_triggered"

    # ----- Governance -------------------------------------------------------
    DSAR_EXPORT = "dsar_export"
    ERASURE = "erasure"
    RETENTION_SWEEP = "retention_sweep"

    # ----- System -----------------------------------------------------------
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"

    # ----- v0.3.0: Compliance -----------------------------------------------
    COMPLIANCE_CHECK_EVALUATED = "compliance_check_evaluated"
    COMPLIANCE_VIOLATION = "compliance_violation"
    PRINCIPAL_APPROVAL_SUBMITTED = "principal_approval_submitted"
    PRINCIPAL_APPROVED = "principal_approved"
    PRINCIPAL_REJECTED = "principal_rejected"
    DISCLOSURE_APPLIED = "disclosure_applied"
    CONSENT_RECORDED = "consent_recorded"
    LEGAL_HOLD_ISSUED = "legal_hold_issued"
    LEGAL_HOLD_RELEASED = "legal_hold_released"
    DESTRUCTION_BLOCKED_BY_HOLD = "destruction_blocked_by_hold"

    # ----- v0.3.0: Risk -----------------------------------------------------
    RISK_IDENTIFIED = "risk_identified"
    RISK_ASSESSED = "risk_assessed"
    RISK_TREATED = "risk_treated"
    RISK_ESCALATED = "risk_escalated"
    KRI_RECORDED = "kri_recorded"
    KRI_BREACH = "kri_breach"
    OPTIMIZER_DECISION = "optimizer_decision"
    OPTIMIZER_VETO = "optimizer_veto"

    # ----- v0.3.0: Threats --------------------------------------------------
    THREAT_DETECTED = "threat_detected"
    IP_BLOCKED = "ip_blocked"
    HONEY_TOKEN_TRIGGERED = "honey_token_triggered"
    CANARY_DRIFT = "canary_drift"
    BEHAVIORAL_ANOMALY = "behavioral_anomaly"

    # ----- v0.3.0: Orchestration --------------------------------------------
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_TASK_COMPLETED = "workflow_task_completed"
    WORKFLOW_CRITIC_VERDICT = "workflow_critic_verdict"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_BUDGET_EXHAUSTED = "workflow_budget_exhausted"

    # ----- v0.3.0: Catalog & lineage ----------------------------------------
    ASSET_REGISTERED = "asset_registered"
    ASSET_QUARANTINED = "asset_quarantined"
    ASSET_DEPRECATED = "asset_deprecated"
    LINEAGE_RECORDED = "lineage_recorded"
    FRESHNESS_VIOLATION = "freshness_violation"

    # ----- v0.3.0: Perf & session -------------------------------------------
    SLO_VIOLATION = "slo_violation"
    LOAD_TEST_COMPLETED = "load_test_completed"
    SESSION_CREATED = "session_created"
    SESSION_DESTROYED = "session_destroyed"
