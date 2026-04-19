"""
STC Framework — Regulatory Compliance Modules
compliance/regulatory_ops.py

Three modules closing the remaining regulatory gaps:

1. Reg BI Suitability Checkpoint (GAP-02)
   Validates AI outputs used in advisory context against customer profile
   and product suitability requirements.

2. NYDFS 72-Hour Notification Workflow (GAP-03)
   Automated incident notification with template generation, CISO approval
   routing, and deadline tracking.

3. Part 500 Annual Certification Assembly (GAP-04)
   Collects all control evidence into a structured compliance report
   aligned with Part 500 sections for annual DFS certification.
"""

import json
import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("stc.compliance.regulatory_ops")


# ═══════════════════════════════════════════════════════════════════════════
# GAP-02: REG BI SUITABILITY CHECKPOINT
# ═══════════════════════════════════════════════════════════════════════════

class SuitabilityResult(Enum):
    SUITABLE = "suitable"
    UNSUITABLE = "unsuitable"
    NEEDS_REVIEW = "needs_review"
    NOT_APPLICABLE = "not_applicable"  # Content is informational, not advisory

@dataclass
class CustomerProfile:
    """Customer investment profile for Reg BI suitability."""
    customer_id: str
    risk_tolerance: str       # conservative | moderate | aggressive
    investment_objectives: List[str]  # growth | income | preservation | speculation
    time_horizon: str         # short | medium | long
    annual_income: str        # bracket
    net_worth: str            # bracket
    investment_experience: str  # none | limited | moderate | extensive
    age_bracket: str          # under_30 | 30_50 | 50_65 | over_65
    tax_status: str           # taxable | tax_deferred | tax_exempt

@dataclass
class SuitabilityCheckResult:
    check_id: str
    timestamp: str
    customer_id: str
    content_summary: str
    is_advisory: bool
    result: SuitabilityResult
    flags: List[str]
    recommendations: List[str]

class RegBICheckpoint:
    """
    Validates AI-generated content against Reg BI suitability requirements
    when the content is used in an advisory context.

    Usage:
        checkpoint = RegBICheckpoint()
        result = checkpoint.check(
            content="Based on the analysis, the aggressive growth fund...",
            customer=CustomerProfile(...),
            context="advisor_meeting_prep")
    """

    # Patterns that indicate advisory context (not just informational)
    ADVISORY_INDICATORS = [
        "recommend", "suggest", "consider", "appropriate for",
        "suitable for", "aligned with your", "given your goals",
        "based on your profile", "for your portfolio",
    ]

    # Risk-level keywords
    HIGH_RISK_INDICATORS = [
        "aggressive", "leveraged", "speculative", "options",
        "margin", "concentrated", "illiquid", "complex",
        "alternative", "high-yield", "emerging market",
    ]

    LOW_RISK_INDICATORS = [
        "conservative", "treasury", "money market", "stable value",
        "investment-grade", "diversified", "index fund",
    ]

    def __init__(self, audit_callback: Optional[Callable] = None):
        self._checks: List[SuitabilityCheckResult] = []
        self._audit_cb = audit_callback

    def check(self, content: str, customer: CustomerProfile,
              context: str = "general") -> SuitabilityCheckResult:
        """Check if AI content is suitable for the customer's profile."""
        now = datetime.now(timezone.utc).isoformat()
        check_id = f"rbi-{hashlib.sha256(f'{content[:50]}{now}'.encode()).hexdigest()[:10]}"
        content_lower = content.lower()

        # Step 1: Is this advisory content?
        is_advisory = any(ind in content_lower for ind in self.ADVISORY_INDICATORS)
        is_advisory = is_advisory or context in ("advisor_meeting_prep", "recommendation", "proposal")

        if not is_advisory:
            result = SuitabilityCheckResult(
                check_id=check_id, timestamp=now, customer_id=customer.customer_id,
                content_summary=content[:100], is_advisory=False,
                result=SuitabilityResult.NOT_APPLICABLE, flags=[], recommendations=[])
            self._checks.append(result)
            return result

        # Step 2: Assess content risk level
        high_risk_count = sum(1 for p in self.HIGH_RISK_INDICATORS if p in content_lower)
        low_risk_count = sum(1 for p in self.LOW_RISK_INDICATORS if p in content_lower)
        content_risk = "high" if high_risk_count > low_risk_count else "low" if low_risk_count > high_risk_count else "moderate"

        # Step 3: Check against customer profile
        flags = []
        recommendations = []

        # Risk tolerance mismatch
        if content_risk == "high" and customer.risk_tolerance == "conservative":
            flags.append("RISK_MISMATCH: High-risk content for conservative investor")
            recommendations.append("Ensure advisor discusses risks; document customer acknowledgment")

        if content_risk == "high" and customer.age_bracket == "over_65":
            flags.append("AGE_CONCERN: High-risk content for investor over 65")
            recommendations.append("Verify time horizon justifies risk level")

        # Time horizon mismatch
        if any(t in content_lower for t in ["long-term", "10-year", "multi-year"]) and customer.time_horizon == "short":
            flags.append("HORIZON_MISMATCH: Long-term strategy for short time horizon")
            recommendations.append("Align product suggestions with customer's time horizon")

        # Experience mismatch
        if content_risk == "high" and customer.investment_experience in ("none", "limited"):
            flags.append("EXPERIENCE_MISMATCH: Complex products for inexperienced investor")
            recommendations.append("Ensure adequate disclosure of product complexity and risks")

        # Concentration risk
        if "concentrated" in content_lower or "single stock" in content_lower:
            flags.append("CONCENTRATION_RISK: Concentrated position referenced")
            recommendations.append("Discuss diversification; document rationale if concentrated")

        # Determine result
        critical_flags = [f for f in flags if "RISK_MISMATCH" in f or "AGE_CONCERN" in f]
        if critical_flags:
            result_val = SuitabilityResult.NEEDS_REVIEW
        elif flags:
            result_val = SuitabilityResult.NEEDS_REVIEW
        else:
            result_val = SuitabilityResult.SUITABLE

        result = SuitabilityCheckResult(
            check_id=check_id, timestamp=now, customer_id=customer.customer_id,
            content_summary=content[:100], is_advisory=is_advisory,
            result=result_val, flags=flags, recommendations=recommendations)

        self._checks.append(result)

        if self._audit_cb:
            self._audit_cb({
                "timestamp": now, "component": "compliance.reg_bi",
                "event_type": "suitability_check",
                "details": {"check_id": check_id, "customer": customer.customer_id,
                            "is_advisory": is_advisory, "result": result_val.value,
                            "flags": len(flags)},
            })

        return result

    def report(self) -> Dict[str, Any]:
        total = len(self._checks)
        advisory = [c for c in self._checks if c.is_advisory]
        flagged = [c for c in advisory if c.flags]
        return {
            "total_checks": total,
            "advisory_content": len(advisory),
            "informational_content": total - len(advisory),
            "flagged_for_review": len(flagged),
            "suitable": sum(1 for c in advisory if c.result == SuitabilityResult.SUITABLE),
            "needs_review": sum(1 for c in advisory if c.result == SuitabilityResult.NEEDS_REVIEW),
        }


# ═══════════════════════════════════════════════════════════════════════════
# GAP-03: NYDFS 72-HOUR NOTIFICATION WORKFLOW
# ═══════════════════════════════════════════════════════════════════════════

class NotificationStatus(Enum):
    DRAFTED = "drafted"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    OVERDUE = "overdue"

@dataclass
class IncidentNotification:
    """DFS cybersecurity event notification per Part 500.17."""
    notification_id: str
    incident_id: str
    incident_type: str
    incident_severity: str
    discovered_at: str
    deadline: str              # 72 hours from discovery
    status: NotificationStatus
    # Content
    description: str
    affected_systems: List[str]
    affected_individuals: int
    npi_exposed: bool
    remediation_steps: str
    # Approval
    drafted_by: str = ""
    approved_by: str = ""
    approved_at: str = ""
    submitted_at: str = ""
    # Tracking
    hours_remaining: float = 72.0

class NYDFSNotificationEngine:
    """
    Automated 72-hour cybersecurity event notification per NYDFS Part 500.17.

    When a SEV-1/SEV-2 incident is classified:
    1. Auto-generates DFS notification draft with pre-populated fields
    2. Routes to CISO for review and approval
    3. Tracks 72-hour deadline with escalating alerts
    4. Records submission in audit trail

    Usage:
        engine = NYDFSNotificationEngine()
        notif = engine.create_notification(incident_id, severity, description, ...)
        engine.approve(notif.notification_id, "CISO Name")
        engine.submit(notif.notification_id)
    """

    def __init__(self, audit_callback: Optional[Callable] = None):
        self._notifications: Dict[str, IncidentNotification] = {}
        self._audit_cb = audit_callback

    def create_notification(self, incident_id: str, incident_type: str,
                            severity: str, description: str,
                            affected_systems: List[str],
                            affected_individuals: int = 0,
                            npi_exposed: bool = False,
                            remediation_steps: str = "") -> IncidentNotification:
        """Create a DFS notification draft. Starts the 72-hour clock."""
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(hours=72)
        notif_id = f"dfs-{incident_id}-{now.strftime('%Y%m%d')}"

        notif = IncidentNotification(
            notification_id=notif_id, incident_id=incident_id,
            incident_type=incident_type, incident_severity=severity,
            discovered_at=now.isoformat(), deadline=deadline.isoformat(),
            status=NotificationStatus.DRAFTED,
            description=description, affected_systems=affected_systems,
            affected_individuals=affected_individuals,
            npi_exposed=npi_exposed, remediation_steps=remediation_steps,
            drafted_by="system", hours_remaining=72.0,
        )

        self._notifications[notif_id] = notif
        self._emit("notification_drafted", notif)
        return notif

    def approve(self, notification_id: str, approver: str) -> IncidentNotification:
        """CISO approves the notification for submission."""
        notif = self._get(notification_id)
        notif.status = NotificationStatus.APPROVED
        notif.approved_by = approver
        notif.approved_at = datetime.now(timezone.utc).isoformat()
        self._update_hours(notif)
        self._emit("notification_approved", notif)
        return notif

    def submit(self, notification_id: str) -> IncidentNotification:
        """Submit the notification to DFS."""
        notif = self._get(notification_id)
        notif.status = NotificationStatus.SUBMITTED
        notif.submitted_at = datetime.now(timezone.utc).isoformat()
        self._update_hours(notif)
        self._emit("notification_submitted", notif)
        return notif

    def check_deadlines(self) -> List[Dict[str, Any]]:
        """Check all pending notifications against 72-hour deadline."""
        alerts = []
        now = datetime.now(timezone.utc)
        for notif in self._notifications.values():
            if notif.status in (NotificationStatus.SUBMITTED, NotificationStatus.ACKNOWLEDGED):
                continue
            self._update_hours(notif)
            if notif.hours_remaining <= 0:
                notif.status = NotificationStatus.OVERDUE
                alerts.append({"notification_id": notif.notification_id,
                               "status": "OVERDUE", "hours_past": abs(notif.hours_remaining)})
            elif notif.hours_remaining <= 12:
                alerts.append({"notification_id": notif.notification_id,
                               "status": "URGENT", "hours_remaining": notif.hours_remaining})
            elif notif.hours_remaining <= 24:
                alerts.append({"notification_id": notif.notification_id,
                               "status": "WARNING", "hours_remaining": notif.hours_remaining})
        return alerts

    def dashboard(self) -> Dict[str, Any]:
        by_status = defaultdict(int)
        for n in self._notifications.values():
            by_status[n.status.value] += 1
        return {
            "total_notifications": len(self._notifications),
            "by_status": dict(by_status),
            "overdue": sum(1 for n in self._notifications.values() if n.status == NotificationStatus.OVERDUE),
        }

    def _get(self, nid: str) -> IncidentNotification:
        if nid not in self._notifications:
            raise KeyError(f"Notification not found: {nid}")
        return self._notifications[nid]

    def _update_hours(self, notif: IncidentNotification):
        deadline = datetime.fromisoformat(notif.deadline)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        remaining = (deadline - datetime.now(timezone.utc)).total_seconds() / 3600
        notif.hours_remaining = round(remaining, 1)

    def _emit(self, event_type, notif):
        if self._audit_cb:
            self._audit_cb({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "component": "compliance.nydfs_notification",
                "event_type": event_type,
                "details": {
                    "notification_id": notif.notification_id,
                    "incident_id": notif.incident_id,
                    "severity": notif.incident_severity,
                    "status": notif.status.value,
                    "hours_remaining": notif.hours_remaining,
                    "npi_exposed": notif.npi_exposed,
                },
            })


# ═══════════════════════════════════════════════════════════════════════════
# GAP-04: PART 500 ANNUAL CERTIFICATION ASSEMBLY
# ═══════════════════════════════════════════════════════════════════════════

class Part500CertificationAssembler:
    """
    Assembles evidence from all STC modules into a structured compliance
    report aligned with Part 500 sections for annual DFS certification.

    Collects: control test results, policy review dates, risk assessment
    dates, training records, pen test results, incident reports, and
    vendor assessment records.

    Usage:
        assembler = Part500CertificationAssembler()
        assembler.add_evidence("500.2", "Cybersecurity program documentation", ...)
        report = assembler.assemble(certification_year=2025)
    """

    PART_500_SECTIONS = {
        "500.2": "Cybersecurity Program",
        "500.3": "Cybersecurity Policy",
        "500.4": "CISO & Board Reporting",
        "500.5": "Penetration Testing",
        "500.7": "Access Privileges & MFA",
        "500.8": "Application Security (SDL)",
        "500.9": "Risk Assessment",
        "500.10": "Cybersecurity Personnel & Training",
        "500.11": "Third-Party Service Provider Policy",
        "500.12": "Multi-Factor Authentication",
        "500.13": "Asset Inventory",
        "500.14": "Training & Monitoring",
        "500.15": "Encryption",
        "500.16": "Incident Response Plan",
        "500.17": "Notices to Superintendent",
    }

    def __init__(self):
        self._evidence: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._gaps: List[Dict[str, Any]] = []

    def add_evidence(self, section: str, description: str,
                     evidence_type: str, evidence_date: str,
                     status: str = "compliant", notes: str = ""):
        """Add a piece of compliance evidence for a Part 500 section."""
        self._evidence[section].append({
            "description": description,
            "evidence_type": evidence_type,  # policy | test_result | report | training | assessment
            "date": evidence_date,
            "status": status,  # compliant | partial | non_compliant | remediation_planned
            "notes": notes,
        })

    def add_gap(self, section: str, description: str,
                remediation_plan: str, target_date: str):
        """Record a compliance gap with remediation plan."""
        self._gaps.append({
            "section": section, "description": description,
            "remediation_plan": remediation_plan, "target_date": target_date,
        })

    def assemble(self, certification_year: int) -> Dict[str, Any]:
        """Assemble the full certification report."""
        sections = {}
        for section_id, section_name in self.PART_500_SECTIONS.items():
            evidence = self._evidence.get(section_id, [])
            section_gaps = [g for g in self._gaps if g["section"] == section_id]

            if not evidence and not section_gaps:
                status = "no_evidence"
            elif section_gaps:
                status = "remediation_in_progress"
            elif all(e["status"] == "compliant" for e in evidence):
                status = "compliant"
            else:
                status = "partial"

            sections[section_id] = {
                "name": section_name,
                "status": status,
                "evidence_count": len(evidence),
                "evidence": evidence,
                "gaps": section_gaps,
            }

        total = len(self.PART_500_SECTIONS)
        compliant = sum(1 for s in sections.values() if s["status"] == "compliant")
        partial = sum(1 for s in sections.values() if s["status"] == "partial")
        gaps = sum(1 for s in sections.values() if s["status"] in ("remediation_in_progress", "no_evidence"))

        return {
            "certification_year": certification_year,
            "generated": datetime.now(timezone.utc).isoformat(),
            "deadline": f"{certification_year + 1}-04-15",
            "summary": {
                "total_sections": total, "compliant": compliant,
                "partial": partial, "gaps": gaps,
                "compliance_rate": round(compliant / total * 100, 1),
            },
            "sections": sections,
            "open_gaps": self._gaps,
            "can_certify": gaps == 0 and partial == 0,
            "certification_statement": (
                f"The undersigned certifies that, to the best of their knowledge, "
                f"the covered entity's cybersecurity program for calendar year {certification_year} "
                f"complied with Part 500 of 23 NYCRR." if gaps == 0
                else f"Certification requires remediation of {gaps} section(s). See open gaps."
            ),
        }


# ═══════════════════════════════════════════════════════════════════════════
# DEMO
# ═══════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("STC Regulatory Gap Fixes — Demo")
    print("=" * 70)

    audit_log = []
    cb = lambda e: audit_log.append(e)

    # ── GAP-02: Reg BI ──
    print("\n" + "=" * 70)
    print("GAP-02: Reg BI Suitability Checkpoint")
    print("=" * 70)

    checkpoint = RegBICheckpoint(audit_callback=cb)

    # Conservative elderly customer
    customer = CustomerProfile(
        "CUST-001", "conservative", ["preservation", "income"],
        "short", "$50K-$100K", "$250K-$500K", "limited", "over_65", "taxable")

    tests = [
        ("Informational (not advisory)",
         "ACME Corp reported $5.2 billion revenue in FY2024.",
         "general"),
        ("Advisory: suitable",
         "Based on your conservative profile, the diversified treasury bond fund may be appropriate for your income goals.",
         "advisor_meeting_prep"),
        ("Advisory: risk mismatch",
         "Given your goals, consider the aggressive leveraged emerging market growth fund for your portfolio.",
         "recommendation"),
    ]

    for name, content, ctx in tests:
        result = checkpoint.check(content, customer, ctx)
        print(f"\n  ▸ {name}")
        print(f"    Advisory: {result.is_advisory} | Result: {result.result.value}")
        for f in result.flags:
            print(f"    ⚠ {f}")
        for r in result.recommendations:
            print(f"    → {r}")

    print(f"\n  Report: {checkpoint.report()}")

    # ── GAP-03: NYDFS 72-hour ──
    print("\n" + "=" * 70)
    print("GAP-03: NYDFS 72-Hour Notification Workflow")
    print("=" * 70)

    nydfs = NYDFSNotificationEngine(audit_callback=cb)

    notif = nydfs.create_notification(
        incident_id="INC-2026-001",
        incident_type="data_breach",
        severity="SEV-1",
        description="Unauthorized access to vector store containing masked client data detected via honey document trigger.",
        affected_systems=["qdrant-cluster", "stc-system namespace"],
        affected_individuals=0,
        npi_exposed=False,
        remediation_steps="1. Isolated affected namespace. 2. Rotated all access credentials. 3. Forensic analysis initiated.")

    print(f"\n  Notification created: {notif.notification_id}")
    print(f"  Deadline: {notif.deadline}")
    print(f"  Hours remaining: {notif.hours_remaining}")
    print(f"  Status: {notif.status.value}")

    # CISO approves
    nydfs.approve(notif.notification_id, "CISO - Global CIO")
    print(f"  → Approved by CISO")

    # Submit
    nydfs.submit(notif.notification_id)
    print(f"  → Submitted to DFS")
    print(f"  Status: {notif.status.value}")

    # Check deadlines
    alerts = nydfs.check_deadlines()
    print(f"  Deadline alerts: {len(alerts)} (none expected after submission)")

    # ── GAP-04: Part 500 Certification ──
    print("\n" + "=" * 70)
    print("GAP-04: Part 500 Annual Certification Assembly")
    print("=" * 70)

    assembler = Part500CertificationAssembler()

    # Add evidence from STC modules
    evidence = [
        ("500.2", "Cybersecurity program documented in Security Architecture", "policy", "2026-01-15"),
        ("500.3", "9 policies in Audit Readiness Package, reviewed annually", "policy", "2026-01-20"),
        ("500.4", "AI Governance Committee charter, quarterly CISO reporting", "report", "2026-03-01"),
        ("500.5", "12 AI pen tests + infrastructure tests, quarterly cadence", "test_result", "2026-02-15"),
        ("500.7", "Casbin RBAC, Vault secrets, K8s NetworkPolicy", "test_result", "2026-02-15"),
        ("500.8", "SDL (7 phases) documented, CI/CD with SAST/SCA/DAST", "policy", "2026-01-20"),
        ("500.9", "25-risk taxonomy, 5x5 matrix, annual assessment + quarterly reviews", "assessment", "2026-02-01"),
        ("500.10", "Operator training matrix (4 roles), annual awareness training", "training", "2026-02-28"),
        ("500.11", "Vendor risk framework (6-area), data contracts, provider assessments", "assessment", "2026-01-30"),
        ("500.12", "Auth module supports MFA; deployment guide requires IdP MFA", "policy", "2026-01-15"),
        ("500.13", "Data Catalog with full asset inventory; K8s deployment inventory", "report", "2026-02-01"),
        ("500.14", "Security awareness training completed, documented in LMS", "training", "2026-02-28"),
        ("500.15", "Encryption at rest (AES-256) and in transit (TLS 1.3) documented", "test_result", "2026-02-15"),
        ("500.16", "6-phase IR playbook, 4 tabletop exercises, quarterly DR tests", "test_result", "2026-03-01"),
        ("500.17", "NYDFS notification engine with 72-hour deadline tracking", "policy", "2026-03-10"),
    ]

    for section, desc, etype, date in evidence:
        assembler.add_evidence(section, desc, etype, date)

    report = assembler.assemble(certification_year=2025)

    print(f"\n  Certification year: {report['certification_year']}")
    print(f"  Deadline: {report['deadline']}")
    print(f"  Summary: {report['summary']}")
    print(f"  Can certify: {report['can_certify']}")
    print(f"\n  Sections:")
    for sid, sec in report["sections"].items():
        icon = "✓" if sec["status"] == "compliant" else "⚠" if sec["status"] == "partial" else "✗"
        print(f"    {icon} {sid} {sec['name']}: {sec['status']} ({sec['evidence_count']} evidence)")

    print(f"\n  Certification statement: {report['certification_statement'][:80]}...")

    print(f"\n▸ Audit events: {len(audit_log)}")
    print("\n" + "=" * 70)
    print("✓ All 4 regulatory gaps fixed")
    print("=" * 70)


if __name__ == "__main__":
    demo()
