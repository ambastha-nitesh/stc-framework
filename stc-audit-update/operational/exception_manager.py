"""
STC Framework — Exception Management
operational/exception_manager.py

Manages the full lifecycle of control exceptions:
  Detection → Registration → Assessment → Remediation → Verification → Closure

Each exception has:
  - Unique ID, severity, category
  - Owner and SLA tracking
  - Root cause analysis record
  - Remediation plan with timeline
  - Verification evidence
  - Full audit trail

Integrates with the Control Testing Framework (exceptions auto-created
when control tests fail) and the audit trail for compliance evidence.

Part of the Operational Control layer.
"""

import json
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("stc.operational.exceptions")


# ── Enums ───────────────────────────────────────────────────────────────────

class Severity(Enum):
    SEV1 = "sev-1"  # Critical: active breach, regulatory violation
    SEV2 = "sev-2"  # High: governance failure requiring intervention
    SEV3 = "sev-3"  # Medium: degraded operation, elevated risk
    SEV4 = "sev-4"  # Low: anomaly, monitoring required


class ExceptionCategory(Enum):
    SECURITY_CONTROL_FAILURE = "security_control_failure"
    GOVERNANCE_FAILURE = "governance_failure"
    OPERATIONAL_ANOMALY = "operational_anomaly"
    POLICY_DEVIATION = "policy_deviation"
    VENDOR_ISSUE = "vendor_issue"
    AUDIT_FINDING = "audit_finding"


class ExceptionState(Enum):
    DETECTED = "detected"
    REGISTERED = "registered"
    ASSESSING = "assessing"
    REMEDIATION_PLANNED = "remediation_planned"
    REMEDIATION_APPROVED = "remediation_approved"
    REMEDIATING = "remediating"
    VERIFYING = "verifying"
    CLOSED = "closed"
    OVERDUE = "overdue"


# ── SLA Definitions ─────────────────────────────────────────────────────────

SLA_HOURS = {
    # (severity, stage) → max hours
    (Severity.SEV1, "registration"): 1,
    (Severity.SEV1, "assessment"): 24,
    (Severity.SEV1, "approval"): 24,
    (Severity.SEV1, "remediation"): 72,
    (Severity.SEV1, "verification"): 48,

    (Severity.SEV2, "registration"): 4,
    (Severity.SEV2, "assessment"): 120,  # 5 days
    (Severity.SEV2, "approval"): 24,
    (Severity.SEV2, "remediation"): 240,  # 10 days
    (Severity.SEV2, "verification"): 48,

    (Severity.SEV3, "registration"): 4,
    (Severity.SEV3, "assessment"): 120,
    (Severity.SEV3, "approval"): 48,
    (Severity.SEV3, "remediation"): 480,  # 20 days
    (Severity.SEV3, "verification"): 96,

    (Severity.SEV4, "registration"): 24,
    (Severity.SEV4, "assessment"): 240,
    (Severity.SEV4, "approval"): 72,
    (Severity.SEV4, "remediation"): 720,  # 30 days
    (Severity.SEV4, "verification"): 120,
}


# ── Data Classes ────────────────────────────────────────────────────────────

@dataclass
class StateTransition:
    """Records a state change in the exception lifecycle."""
    from_state: str
    to_state: str
    timestamp: str
    actor: str
    notes: str = ""


@dataclass
class RemediationPlan:
    """Corrective action plan for an exception."""
    plan_id: str
    description: str
    actions: List[str]
    owner: str
    target_date: str
    approved_by: str = ""
    approved_at: str = ""


@dataclass
class Exception_:
    """An exception in the STC control framework."""
    exception_id: str
    title: str
    description: str
    severity: Severity
    category: ExceptionCategory
    state: ExceptionState
    control_id: str = ""           # Control ID that triggered exception
    detected_at: str = ""
    registered_at: str = ""
    owner: str = ""
    root_cause: str = ""
    impact_assessment: str = ""
    remediation_plan: Optional[RemediationPlan] = None
    resolution_notes: str = ""
    closed_at: str = ""
    lessons_learned: str = ""
    transitions: List[StateTransition] = field(default_factory=list)
    sla_violations: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exception_id": self.exception_id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity.value,
            "category": self.category.value,
            "state": self.state.value,
            "control_id": self.control_id,
            "detected_at": self.detected_at,
            "registered_at": self.registered_at,
            "owner": self.owner,
            "root_cause": self.root_cause,
            "impact_assessment": self.impact_assessment,
            "remediation_plan": {
                "plan_id": self.remediation_plan.plan_id,
                "description": self.remediation_plan.description,
                "actions": self.remediation_plan.actions,
                "owner": self.remediation_plan.owner,
                "target_date": self.remediation_plan.target_date,
                "approved_by": self.remediation_plan.approved_by,
            } if self.remediation_plan else None,
            "resolution_notes": self.resolution_notes,
            "closed_at": self.closed_at,
            "lessons_learned": self.lessons_learned,
            "transitions": [
                {"from": t.from_state, "to": t.to_state,
                 "timestamp": t.timestamp, "actor": t.actor, "notes": t.notes}
                for t in self.transitions
            ],
            "sla_violations": self.sla_violations,
        }


# ── Exception Manager ──────────────────────────────────────────────────────

class ExceptionManager:
    """
    Manages the full lifecycle of STC control exceptions.

    Usage:
        mgr = ExceptionManager(audit_callback=audit_store.append)

        # Auto-create from failed control test
        exc = mgr.create_from_test_failure(test_evidence)

        # Manual lifecycle
        exc_id = mgr.register("Firewall bypass detected", ...)
        mgr.assign(exc_id, "security-team")
        mgr.assess(exc_id, root_cause="...", impact="...")
        mgr.plan_remediation(exc_id, plan=RemediationPlan(...))
        mgr.approve_plan(exc_id, approver="ciso")
        mgr.start_remediation(exc_id)
        mgr.verify(exc_id, evidence="...")
        mgr.close(exc_id, resolution="...", lessons="...")

        # Reporting
        report = mgr.status_report()
        overdue = mgr.check_sla_compliance()
    """

    def __init__(self, audit_callback: Optional[Callable] = None):
        self._exceptions: Dict[str, Exception_] = {}
        self._audit_callback = audit_callback
        self._counter = 0

    def _gen_id(self) -> str:
        self._counter += 1
        ts = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"EXC-{ts}-{self._counter:04d}"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _transition(self, exc: Exception_, new_state: ExceptionState,
                    actor: str, notes: str = ""):
        old_state = exc.state
        exc.transitions.append(StateTransition(
            from_state=old_state.value,
            to_state=new_state.value,
            timestamp=self._now(),
            actor=actor,
            notes=notes,
        ))
        exc.state = new_state
        self._emit_audit("exception_state_change", exc.exception_id, {
            "from": old_state.value, "to": new_state.value, "actor": actor, "notes": notes,
        })

    # ── Lifecycle Methods ───────────────────────────────────────────────

    def register(self, title: str, description: str, severity: Severity,
                 category: ExceptionCategory, control_id: str = "",
                 actor: str = "system") -> str:
        """Register a new exception. Returns exception ID."""
        exc_id = self._gen_id()
        now = self._now()

        exc = Exception_(
            exception_id=exc_id,
            title=title,
            description=description,
            severity=severity,
            category=category,
            state=ExceptionState.DETECTED,
            control_id=control_id,
            detected_at=now,
        )
        self._exceptions[exc_id] = exc
        self._transition(exc, ExceptionState.REGISTERED, actor, "Exception registered")
        exc.registered_at = now

        self._emit_audit("exception_registered", exc_id, {
            "title": title, "severity": severity.value, "category": category.value,
            "control_id": control_id,
        })
        return exc_id

    def create_from_test_failure(self, test_evidence: Dict[str, Any],
                                 actor: str = "control_testing") -> str:
        """Auto-create an exception from a failed control test."""
        control_id = test_evidence.get("control_id", "")
        control_name = test_evidence.get("control_name", "Unknown")
        details = test_evidence.get("details", {})
        remediation = test_evidence.get("remediation", "")

        # Map control category to exception category
        cat_map = {
            "security": ExceptionCategory.SECURITY_CONTROL_FAILURE,
            "governance": ExceptionCategory.GOVERNANCE_FAILURE,
            "operational": ExceptionCategory.OPERATIONAL_ANOMALY,
        }
        category = cat_map.get(
            test_evidence.get("category", ""),
            ExceptionCategory.SECURITY_CONTROL_FAILURE
        )

        # Default severity based on category
        sev_map = {
            ExceptionCategory.SECURITY_CONTROL_FAILURE: Severity.SEV2,
            ExceptionCategory.GOVERNANCE_FAILURE: Severity.SEV2,
            ExceptionCategory.OPERATIONAL_ANOMALY: Severity.SEV3,
        }
        severity = sev_map.get(category, Severity.SEV3)

        exc_id = self.register(
            title=f"Control test failure: {control_name} ({control_id})",
            description=test_evidence.get("evidence_description", ""),
            severity=severity,
            category=category,
            control_id=control_id,
            actor=actor,
        )

        # Auto-populate initial assessment if remediation guidance exists
        if remediation:
            exc = self._exceptions[exc_id]
            exc.impact_assessment = f"Control {control_id} ({control_name}) failed automated testing."
            exc.root_cause = "Pending investigation — auto-created from test failure."

        return exc_id

    def assign(self, exc_id: str, owner: str, actor: str = "system"):
        """Assign an exception to an owner."""
        exc = self._get(exc_id)
        exc.owner = owner
        self._emit_audit("exception_assigned", exc_id, {"owner": owner, "actor": actor})

    def assess(self, exc_id: str, root_cause: str, impact: str,
               actor: str = "security-team"):
        """Record root cause analysis and impact assessment."""
        exc = self._get(exc_id)
        exc.root_cause = root_cause
        exc.impact_assessment = impact
        self._transition(exc, ExceptionState.ASSESSING, actor, "Assessment in progress")
        self._emit_audit("exception_assessed", exc_id, {
            "root_cause": root_cause[:200], "impact": impact[:200],
        })

    def plan_remediation(self, exc_id: str, plan: RemediationPlan,
                         actor: str = "engineering"):
        """Attach a remediation plan to the exception."""
        exc = self._get(exc_id)
        exc.remediation_plan = plan
        self._transition(exc, ExceptionState.REMEDIATION_PLANNED, actor,
                         f"Remediation plan: {plan.description[:100]}")

    def approve_plan(self, exc_id: str, approver: str):
        """Approve the remediation plan."""
        exc = self._get(exc_id)
        if not exc.remediation_plan:
            raise ValueError(f"No remediation plan to approve for {exc_id}")
        exc.remediation_plan.approved_by = approver
        exc.remediation_plan.approved_at = self._now()
        self._transition(exc, ExceptionState.REMEDIATION_APPROVED, approver,
                         "Remediation plan approved")

    def start_remediation(self, exc_id: str, actor: str = "engineering"):
        """Mark remediation as in progress."""
        exc = self._get(exc_id)
        self._transition(exc, ExceptionState.REMEDIATING, actor,
                         "Remediation implementation started")

    def verify(self, exc_id: str, evidence: str, actor: str = "security-team"):
        """Verify that remediation was effective."""
        exc = self._get(exc_id)
        self._transition(exc, ExceptionState.VERIFYING, actor,
                         f"Verification: {evidence[:200]}")

    def close(self, exc_id: str, resolution: str, lessons: str = "",
              actor: str = "security-team"):
        """Close the exception with resolution notes and lessons learned."""
        exc = self._get(exc_id)
        exc.resolution_notes = resolution
        exc.lessons_learned = lessons
        exc.closed_at = self._now()
        self._transition(exc, ExceptionState.CLOSED, actor,
                         f"Closed: {resolution[:100]}")

    def reopen(self, exc_id: str, reason: str, actor: str = "audit"):
        """Reopen a closed exception."""
        exc = self._get(exc_id)
        exc.closed_at = ""
        self._transition(exc, ExceptionState.REGISTERED, actor,
                         f"Reopened: {reason}")

    # ── SLA Compliance ──────────────────────────────────────────────────

    def check_sla_compliance(self) -> List[Dict[str, Any]]:
        """Check all open exceptions for SLA violations."""
        now = datetime.now(timezone.utc)
        violations = []

        for exc_id, exc in self._exceptions.items():
            if exc.state == ExceptionState.CLOSED:
                continue

            # Check registration SLA
            if exc.state == ExceptionState.DETECTED:
                detected = datetime.fromisoformat(exc.detected_at)
                sla_hours = SLA_HOURS.get((exc.severity, "registration"), 24)
                if (now - detected).total_seconds() / 3600 > sla_hours:
                    violation = {
                        "exception_id": exc_id,
                        "severity": exc.severity.value,
                        "sla_stage": "registration",
                        "sla_hours": sla_hours,
                        "elapsed_hours": round((now - detected).total_seconds() / 3600, 1),
                    }
                    violations.append(violation)
                    exc.sla_violations.append(violation)

            # Check assessment SLA (if registered but not assessed)
            if exc.state == ExceptionState.REGISTERED and exc.registered_at:
                registered = datetime.fromisoformat(exc.registered_at)
                sla_hours = SLA_HOURS.get((exc.severity, "assessment"), 120)
                if (now - registered).total_seconds() / 3600 > sla_hours:
                    violation = {
                        "exception_id": exc_id,
                        "severity": exc.severity.value,
                        "sla_stage": "assessment",
                        "sla_hours": sla_hours,
                        "elapsed_hours": round((now - registered).total_seconds() / 3600, 1),
                    }
                    violations.append(violation)
                    exc.sla_violations.append(violation)

            # Mark overdue
            if exc.sla_violations and exc.state != ExceptionState.OVERDUE:
                if exc.state not in (ExceptionState.VERIFYING, ExceptionState.CLOSED):
                    self._transition(exc, ExceptionState.OVERDUE, "sla_monitor",
                                     f"SLA violated: {len(exc.sla_violations)} violations")

        return violations

    # ── Reporting ───────────────────────────────────────────────────────

    def status_report(self) -> Dict[str, Any]:
        """Generate a status report for all exceptions."""
        by_state = {}
        by_severity = {}
        by_category = {}
        open_count = 0
        closed_count = 0
        overdue_count = 0

        for exc in self._exceptions.values():
            by_state[exc.state.value] = by_state.get(exc.state.value, 0) + 1
            by_severity[exc.severity.value] = by_severity.get(exc.severity.value, 0) + 1
            by_category[exc.category.value] = by_category.get(exc.category.value, 0) + 1
            if exc.state == ExceptionState.CLOSED:
                closed_count += 1
            else:
                open_count += 1
            if exc.state == ExceptionState.OVERDUE:
                overdue_count += 1

        # Calculate mean time to resolution (for closed exceptions)
        resolution_times = []
        for exc in self._exceptions.values():
            if exc.state == ExceptionState.CLOSED and exc.detected_at and exc.closed_at:
                detected = datetime.fromisoformat(exc.detected_at)
                closed = datetime.fromisoformat(exc.closed_at)
                resolution_times.append((closed - detected).total_seconds() / 3600)

        mttr = sum(resolution_times) / len(resolution_times) if resolution_times else None

        return {
            "report_generated": self._now(),
            "total_exceptions": len(self._exceptions),
            "open": open_count,
            "closed": closed_count,
            "overdue": overdue_count,
            "by_state": by_state,
            "by_severity": by_severity,
            "by_category": by_category,
            "mean_time_to_resolution_hours": round(mttr, 1) if mttr else None,
            "sla_compliance_rate": (
                1 - overdue_count / open_count if open_count > 0 else 1.0
            ),
        }

    def export_register(self) -> List[Dict[str, Any]]:
        """Export the full exception register for audit review."""
        return [exc.to_dict() for exc in self._exceptions.values()]

    def get(self, exc_id: str) -> Optional[Dict[str, Any]]:
        """Get a single exception by ID."""
        exc = self._exceptions.get(exc_id)
        return exc.to_dict() if exc else None

    # ── Internal ────────────────────────────────────────────────────────

    def _get(self, exc_id: str) -> Exception_:
        if exc_id not in self._exceptions:
            raise KeyError(f"Exception not found: {exc_id}")
        return self._exceptions[exc_id]

    def _emit_audit(self, event_type: str, exc_id: str, details: Dict):
        event = {
            "timestamp": self._now(),
            "component": "operational.exception_manager",
            "event_type": event_type,
            "exception_id": exc_id,
            "details": details,
        }
        if self._audit_callback:
            self._audit_callback(event)


# ── Demo ────────────────────────────────────────────────────────────────────

def demo():
    print("=" * 70)
    print("STC Exception Management — Demo")
    print("=" * 70)

    audit_log = []
    mgr = ExceptionManager(audit_callback=lambda e: audit_log.append(e))

    # Scenario 1: Auto-create from failed control test
    print("\n▸ Scenario 1: Auto-create from failed control test")
    test_failure = {
        "control_id": "SEC-001",
        "control_name": "Runtime AI Firewall",
        "category": "security",
        "result": "fail",
        "evidence_description": "Firewall detected only 3/5 probes (60%)",
        "remediation": "Review firewall rules. Retrain PromptGuard.",
    }
    exc1 = mgr.create_from_test_failure(test_failure)
    print(f"  Created: {exc1}")

    # Assign
    mgr.assign(exc1, "security-team")
    print(f"  Assigned to: security-team")

    # Assess
    mgr.assess(exc1,
               root_cause="PromptGuard model not detecting encoding-based bypass attacks",
               impact="Medium: encoding bypass could allow indirect prompt injection")
    print(f"  Assessment recorded")

    # Plan remediation
    plan = RemediationPlan(
        plan_id="REM-001",
        description="Upgrade PromptGuard model and add regex fallback for encoding patterns",
        actions=[
            "Update PromptGuard to latest version",
            "Add regex patterns for base64/hex encoding attempts",
            "Re-run adversarial test suite",
            "Update firewall configuration in spec",
        ],
        owner="security-team",
        target_date=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    )
    mgr.plan_remediation(exc1, plan)
    print(f"  Remediation planned: {plan.description[:60]}...")

    # Approve
    mgr.approve_plan(exc1, approver="ciso")
    print(f"  Plan approved by CISO")

    # Remediate
    mgr.start_remediation(exc1)
    print(f"  Remediation started")

    # Verify
    mgr.verify(exc1,
               evidence="Re-ran adversarial test suite: 5/5 probes detected (100%)",
               actor="security-team")
    print(f"  Verification: tests passed")

    # Close
    mgr.close(exc1,
              resolution="Upgraded PromptGuard and added encoding pattern detection",
              lessons="Need to include encoding bypass in standard test suite",
              actor="security-team")
    print(f"  Exception closed")

    # Scenario 2: Manual governance exception
    print("\n▸ Scenario 2: Manual governance exception")
    exc2 = mgr.register(
        title="Hallucination rate exceeded threshold",
        description="Hallucination rate reached 8% (threshold: 5%) on 2026-03-08",
        severity=Severity.SEV2,
        category=ExceptionCategory.GOVERNANCE_FAILURE,
        control_id="GOV-002",
        actor="monitoring",
    )
    mgr.assign(exc2, "ai-engineering")
    print(f"  Created & assigned: {exc2}")

    # Scenario 3: Vendor issue
    print("\n▸ Scenario 3: Vendor issue")
    exc3 = mgr.register(
        title="OpenAI API intermittent 503 errors",
        description="OpenAI returning 503 at ~2% rate since 2026-03-09 14:00 UTC",
        severity=Severity.SEV3,
        category=ExceptionCategory.VENDOR_ISSUE,
        actor="monitoring",
    )
    mgr.assign(exc3, "platform-engineering")
    print(f"  Created & assigned: {exc3}")

    # Check SLA compliance
    print("\n▸ Checking SLA compliance...")
    violations = mgr.check_sla_compliance()
    print(f"  SLA violations: {len(violations)}")
    for v in violations:
        print(f"    {v['exception_id']}: {v['sla_stage']} SLA "
              f"({v['sla_hours']}h limit, {v['elapsed_hours']}h elapsed)")

    # Status report
    print("\n▸ Status report:")
    report = mgr.status_report()
    print(f"  Total exceptions: {report['total_exceptions']}")
    print(f"  Open: {report['open']}  |  Closed: {report['closed']}  |  Overdue: {report['overdue']}")
    print(f"  By severity: {report['by_severity']}")
    print(f"  By category: {report['by_category']}")
    print(f"  SLA compliance rate: {report['sla_compliance_rate']:.0%}")
    if report['mean_time_to_resolution_hours']:
        print(f"  Mean time to resolution: {report['mean_time_to_resolution_hours']}h")

    # Export register
    print("\n▸ Exception register export:")
    register = mgr.export_register()
    for exc in register:
        print(f"  [{exc['exception_id']}] {exc['title'][:50]}... "
              f"| {exc['severity']} | {exc['state']} | owner={exc['owner']}")
        print(f"    Transitions: {len(exc['transitions'])} state changes recorded")

    print(f"\n▸ Audit events: {len(audit_log)}")

    print("\n" + "=" * 70)
    print("✓ Exception management demo complete")
    print("=" * 70)


if __name__ == "__main__":
    demo()
