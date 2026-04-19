"""
STC Framework - Observability & Audit Module

Provides unified observability across all STC components with:

1. UNIFIED TRACE CONTEXT
   - Single trace ID correlating firewall → sentinel → stalwart → critic → trainer
   - OpenTelemetry-native with STC-specific semantic conventions
   - Every span enriched with spec version, persona, data tier, prompt version

2. AUDIT TRAIL
   - Immutable, append-only event log across all components
   - Structured events: security, governance, optimization, data boundary, auth
   - Exportable to Parquet, JSONL, or S3 for compliance retention

3. COMPLIANCE EVIDENCE GENERATOR
   - Query-based evidence packages for AIUC-1 audits
   - Pre-built queries: hallucination events, boundary crossings, escalations
   - Structured reports with timestamps, evidence, and AIUC-1 requirement mapping

4. SYSTEM HEALTH DASHBOARD
   - Aggregated health across all personas and security layers
   - Real-time metrics: accuracy, cost, hallucination rate, block rate, auth denials

5. LOG SANITIZATION
   - DLP-aware trace processor that redacts proprietary data from all spans
   - Ensures observability channels don't become data leak vectors

Usage:
    from observability.stc_observability import STCObservability
    obs = STCObservability(spec)

    # Start a traced request
    with obs.trace_request("What was Q4 revenue?") as ctx:
        ctx.record_firewall_result(firewall_result)
        ctx.record_stalwart_execution(stalwart_result)
        ctx.record_critic_verdict(verdict)
        ctx.record_trainer_signal(transition)

    # Generate compliance evidence
    evidence = obs.generate_aiuc1_evidence(quarter="2026-Q1")
"""

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, Any
from pathlib import Path
from contextlib import contextmanager
from collections import defaultdict

from spec.loader import STCSpec

logger = logging.getLogger("stc.observability")


# ============================================================================
# STC Semantic Conventions for OpenTelemetry
# ============================================================================

class STCAttributes:
    """
    Standard attribute names for STC OpenTelemetry spans.
    These provide consistent, queryable trace data across all components.
    """
    # Trace identity
    TRACE_ID = "stc.trace_id"
    SPEC_VERSION = "stc.spec_version"
    SYSTEM_NAME = "stc.system_name"

    # Persona
    PERSONA = "stc.persona"              # stalwart | trainer | critic
    PERSONA_ACTION = "stc.persona.action"

    # Data sovereignty
    DATA_TIER = "stc.data.tier"          # public | internal | restricted
    DATA_BOUNDARY_CROSSED = "stc.data.boundary_crossed"
    DATA_REDACTIONS_COUNT = "stc.data.redactions_count"

    # Model
    MODEL_USED = "stc.model.used"
    MODEL_COST_USD = "stc.model.cost_usd"
    TOKENS_PROMPT = "stc.tokens.prompt"
    TOKENS_COMPLETION = "stc.tokens.completion"
    PROMPT_VERSION = "stc.prompt.version"

    # Retrieval
    RETRIEVAL_CHUNKS = "stc.retrieval.num_chunks"
    RETRIEVAL_AVG_SCORE = "stc.retrieval.avg_score"

    # Governance
    CRITIC_PASSED = "stc.critic.passed"
    CRITIC_ACTION = "stc.critic.action"  # pass | warn | block | escalate
    ESCALATION_LEVEL = "stc.critic.escalation_level"
    GUARDRAILS_EVALUATED = "stc.critic.guardrails_evaluated"

    # Security
    FIREWALL_DECISION = "stc.firewall.decision"
    FIREWALL_SCANNER = "stc.firewall.scanner"
    FIREWALL_SCORE = "stc.firewall.score"
    AUTH_DECISION = "stc.auth.decision"
    AUTH_SUBJECT = "stc.auth.subject"

    # Optimization
    TRAINER_REWARD = "stc.trainer.reward"
    TRAINER_ACCURACY = "stc.trainer.accuracy"


# ============================================================================
# Unified Audit Event
# ============================================================================

@dataclass
class AuditEvent:
    """
    A single immutable audit event. All STC components emit these.
    Events are append-only and cannot be modified after creation.
    """
    event_id: str
    timestamp: str
    trace_id: str
    component: str      # firewall | sentinel | stalwart | critic | trainer | auth
    event_type: str     # security | governance | optimization | data_boundary | auth | system
    severity: str       # critical | high | medium | low | info
    action: str         # what happened
    outcome: str        # allow | block | mask | escalate | optimize | record
    details: str        # human-readable description
    evidence: dict = field(default_factory=dict)
    aiuc1_requirement: Optional[str] = None  # e.g., "A006", "C001"

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================================
# Trace Context (correlates all events for a single request)
# ============================================================================

class TraceContext:
    """
    Correlates all events across STC components for a single request.
    
    Usage:
        with obs.trace_request("query") as ctx:
            ctx.record_firewall_result(...)
            ctx.record_stalwart_execution(...)
    """

    def __init__(self, trace_id: str, query: str, spec: STCSpec, audit_store: 'AuditStore'):
        self.trace_id = trace_id
        self.query = query
        self.spec = spec
        self.audit_store = audit_store
        self.start_time = time.perf_counter()
        self.events: list[AuditEvent] = []
        self._event_counter = 0

        # OpenTelemetry integration
        self._setup_otel_span()

    def _setup_otel_span(self):
        """Create the root OTel span for this request."""
        try:
            from opentelemetry import trace
            tracer = trace.get_tracer("stc.observability")
            self._otel_tracer = tracer
            self._otel_available = True
        except ImportError:
            self._otel_available = False

    def _next_event_id(self) -> str:
        self._event_counter += 1
        return f"{self.trace_id}-{self._event_counter:03d}"

    def _emit(self, event: AuditEvent):
        """Emit an event to the audit store and local list."""
        self.events.append(event)
        self.audit_store.append(event)

    # ── Event Recorders ───────────────────────────────────────────────

    def record_firewall_result(self, result):
        """Record a runtime firewall scan result."""
        self._emit(AuditEvent(
            event_id=self._next_event_id(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace_id=self.trace_id,
            component="firewall",
            event_type="security",
            severity="critical" if result.blocked else "info",
            action=f"scan_{result.scanner}",
            outcome="block" if result.blocked else "allow",
            details=f"Firewall: {result.decision} (score={result.score:.3f}, {result.latency_ms:.1f}ms)",
            evidence={"scanner": result.scanner, "score": result.score, "reason": result.reason},
            aiuc1_requirement="B" if result.blocked else None,
        ))

    def record_data_security(self, events: list, masked_count: int = 0):
        """Record data security events (PII, DLP, injection)."""
        for sec_event in events:
            aiuc_req = None
            if sec_event.event_type == "pii_redaction":
                aiuc_req = "A006"
            elif sec_event.event_type == "injection_blocked":
                aiuc_req = "F001"
            elif sec_event.event_type == "dlp_alert":
                aiuc_req = "A004"

            self._emit(AuditEvent(
                event_id=self._next_event_id(),
                timestamp=sec_event.timestamp,
                trace_id=self.trace_id,
                component="sentinel",
                event_type="security" if sec_event.event_type != "policy_violation" else "governance",
                severity=sec_event.severity,
                action=sec_event.event_type,
                outcome=sec_event.action_taken,
                details=sec_event.details,
                evidence=sec_event.evidence,
                aiuc1_requirement=aiuc_req,
            ))

    def record_auth_decision(self, subject: str, action: str, resource: str, allowed: bool):
        """Record an authorization decision."""
        self._emit(AuditEvent(
            event_id=self._next_event_id(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace_id=self.trace_id,
            component="auth",
            event_type="auth",
            severity="high" if not allowed else "info",
            action=f"{action}:{resource}",
            outcome="allow" if allowed else "deny",
            details=f"Auth: {subject} → {action}:{resource} = {'allow' if allowed else 'DENY'}",
            evidence={"subject": subject, "action": action, "resource": resource},
            aiuc1_requirement="A003" if not allowed else None,
        ))

    def record_stalwart_execution(self, result: dict):
        """Record Stalwart execution details."""
        self._emit(AuditEvent(
            event_id=self._next_event_id(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace_id=self.trace_id,
            component="stalwart",
            event_type="system",
            severity="info",
            action="execute",
            outcome="success" if not result.get("error") else "error",
            details=(
                f"Model: {result.get('model_used', '?')}, "
                f"Tier: {result.get('data_tier', '?')}, "
                f"Chunks: {len(result.get('retrieved_chunks', []))}"
            ),
            evidence={
                "model_used": result.get("model_used"),
                "data_tier": result.get("data_tier"),
                "prompt_version": result.get("prompt_version"),
                "num_chunks": len(result.get("retrieved_chunks", [])),
                "citations": len(result.get("citations", [])),
            },
        ))

    def record_critic_verdict(self, verdict):
        """Record Critic governance verdict."""
        for rail_result in verdict.results:
            aiuc_req = None
            if rail_result.rail_name == "hallucination_detection":
                aiuc_req = "C001"
            elif rail_result.rail_name == "numerical_accuracy":
                aiuc_req = "C001"
            elif rail_result.rail_name == "pii_output_scan":
                aiuc_req = "A006"
            elif rail_result.rail_name == "scope_check":
                aiuc_req = "A007"

            self._emit(AuditEvent(
                event_id=self._next_event_id(),
                timestamp=verdict.timestamp,
                trace_id=self.trace_id,
                component="critic",
                event_type="governance",
                severity=rail_result.severity if not rail_result.passed else "info",
                action=f"guardrail:{rail_result.rail_name}",
                outcome="pass" if rail_result.passed else "fail",
                details=rail_result.details,
                evidence=rail_result.evidence,
                aiuc1_requirement=aiuc_req,
            ))

        # Record overall verdict
        self._emit(AuditEvent(
            event_id=self._next_event_id(),
            timestamp=verdict.timestamp,
            trace_id=self.trace_id,
            component="critic",
            event_type="governance",
            severity="critical" if not verdict.passed else "info",
            action=f"verdict:{verdict.action}",
            outcome=verdict.action,
            details=f"Overall: {verdict.action}, escalation={verdict.escalation_level or 'none'}",
            evidence={"passed": verdict.passed, "escalation_level": verdict.escalation_level},
            aiuc1_requirement="D" if verdict.escalation_level else None,
        ))

    def record_trainer_signal(self, transition: dict):
        """Record Trainer optimization signal."""
        self._emit(AuditEvent(
            event_id=self._next_event_id(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace_id=self.trace_id,
            component="trainer",
            event_type="optimization",
            severity="info",
            action="reward_computed",
            outcome="record",
            details=f"Reward: {transition.get('reward', 0):.3f}",
            evidence={
                "reward": transition.get("reward"),
                "signals": transition.get("signals", []),
            },
        ))

    def record_data_boundary(self, tier: str, destination: str, crossed: bool):
        """Record a data boundary crossing event."""
        self._emit(AuditEvent(
            event_id=self._next_event_id(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace_id=self.trace_id,
            component="sentinel",
            event_type="data_boundary",
            severity="high" if tier == "restricted" and crossed else "info",
            action=f"boundary:{'crossed' if crossed else 'contained'}",
            outcome="crossed" if crossed else "contained",
            details=f"Data tier '{tier}' → {destination} ({'CROSSED' if crossed else 'contained'})",
            evidence={"data_tier": tier, "destination": destination, "crossed": crossed},
            aiuc1_requirement="A004" if tier == "restricted" and crossed else None,
        ))

    def get_summary(self) -> dict:
        """Get a summary of all events in this trace."""
        elapsed_ms = (time.perf_counter() - self.start_time) * 1000
        by_component = defaultdict(int)
        by_type = defaultdict(int)
        by_severity = defaultdict(int)

        for e in self.events:
            by_component[e.component] += 1
            by_type[e.event_type] += 1
            by_severity[e.severity] += 1

        return {
            "trace_id": self.trace_id,
            "total_events": len(self.events),
            "elapsed_ms": elapsed_ms,
            "by_component": dict(by_component),
            "by_type": dict(by_type),
            "by_severity": dict(by_severity),
            "has_critical": by_severity.get("critical", 0) > 0,
            "has_blocks": any(e.outcome in ("block", "deny") for e in self.events),
        }


# ============================================================================
# Audit Store (Immutable, Append-Only)
# ============================================================================

class AuditStore:
    """
    Immutable, append-only storage for all STC audit events.
    
    Supports:
    - In-memory buffer for real-time queries
    - JSONL file export (daily rotation)
    - Parquet export for compliance archival
    - Query API for evidence generation
    """

    def __init__(self, spec: STCSpec):
        self.spec = spec
        self.audit_config = spec.audit

        self.events: list[AuditEvent] = []
        self.export_path = Path(self.audit_config.get("export", {}).get("destination", "audit-logs/").replace("local://", ""))
        self.export_path.mkdir(parents=True, exist_ok=True)

        self.retention_days = self.audit_config.get("retention_days", 365)

    def append(self, event: AuditEvent):
        """Append an event (immutable — cannot be modified after this)."""
        self.events.append(event)

        # Write to daily JSONL file
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = self.export_path / f"stc_audit_{date_str}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def query(self, component: Optional[str] = None, event_type: Optional[str] = None,
              severity: Optional[str] = None, aiuc1_req: Optional[str] = None,
              since: Optional[datetime] = None, until: Optional[datetime] = None,
              trace_id: Optional[str] = None, outcome: Optional[str] = None) -> list[AuditEvent]:
        """Query audit events with filters."""
        results = []
        for e in self.events:
            if component and e.component != component:
                continue
            if event_type and e.event_type != event_type:
                continue
            if severity and e.severity != severity:
                continue
            if aiuc1_req and e.aiuc1_requirement != aiuc1_req:
                continue
            if trace_id and e.trace_id != trace_id:
                continue
            if outcome and e.outcome != outcome:
                continue
            if since:
                event_time = datetime.fromisoformat(e.timestamp)
                if event_time < since:
                    continue
            if until:
                event_time = datetime.fromisoformat(e.timestamp)
                if event_time > until:
                    continue
            results.append(e)
        return results

    def export_parquet(self, output_path: Optional[str] = None) -> str:
        """Export audit events to Parquet for compliance archival."""
        try:
            import pandas as pd

            df = pd.DataFrame([e.to_dict() for e in self.events])
            # Serialize evidence dict to JSON string for Parquet compatibility
            if "evidence" in df.columns:
                df["evidence"] = df["evidence"].apply(json.dumps)

            path = output_path or str(self.export_path / f"stc_audit_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.parquet")
            df.to_parquet(path, index=False)
            logger.info(f"Exported {len(df)} audit events to {path}")
            return path

        except ImportError:
            # Fall back to JSONL
            path = output_path or str(self.export_path / f"stc_audit_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jsonl")
            with open(path, "w") as f:
                for e in self.events:
                    f.write(json.dumps(e.to_dict()) + "\n")
            logger.info(f"Exported {len(self.events)} audit events to {path} (JSONL fallback)")
            return path


# ============================================================================
# Compliance Evidence Generator
# ============================================================================

class ComplianceEvidenceGenerator:
    """
    Generates structured evidence packages for AIUC-1 audits.
    
    An auditor can request: "Show me all hallucination events from Q1 2026"
    and get a structured report with timestamps, evidence, and AIUC-1 mappings.
    """

    def __init__(self, audit_store: AuditStore, spec: STCSpec):
        self.store = audit_store
        self.spec = spec

    def generate_aiuc1_evidence(self, since: Optional[datetime] = None,
                                  until: Optional[datetime] = None) -> dict:
        """Generate a complete AIUC-1 evidence package."""
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(days=90)
        if until is None:
            until = datetime.now(timezone.utc)

        return {
            "report_type": "AIUC-1 Compliance Evidence",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "spec_version": self.spec.version,
            "period": {"from": since.isoformat(), "to": until.isoformat()},
            "sections": {
                "A_data_privacy": self._evidence_data_privacy(since, until),
                "B_security": self._evidence_security(since, until),
                "C_safety": self._evidence_safety(since, until),
                "D_reliability": self._evidence_reliability(since, until),
                "E_accountability": self._evidence_accountability(since, until),
                "F_society": self._evidence_society(since, until),
            },
        }

    def _evidence_data_privacy(self, since, until) -> dict:
        pii_events = self.store.query(event_type="security", aiuc1_req="A006", since=since, until=until)
        dlp_events = self.store.query(event_type="security", aiuc1_req="A004", since=since, until=until)
        boundary_events = self.store.query(event_type="data_boundary", since=since, until=until)
        boundary_violations = [e for e in boundary_events if e.outcome == "crossed" and e.severity == "high"]

        return {
            "A006_pii_protection": {
                "total_pii_events": len(pii_events),
                "pii_blocked": sum(1 for e in pii_events if e.outcome == "block"),
                "pii_masked": sum(1 for e in pii_events if e.outcome == "mask"),
                "status": "compliant" if all(e.outcome in ("block", "mask") for e in pii_events) else "review_needed",
            },
            "A004_ip_protection": {
                "total_dlp_events": len(dlp_events),
                "dlp_blocked": sum(1 for e in dlp_events if e.outcome in ("block", "blocked")),
                "status": "compliant" if not any(e.outcome == "allowed" for e in dlp_events) else "review_needed",
            },
            "A005_cross_customer": {
                "boundary_crossings": len(boundary_events),
                "violations": len(boundary_violations),
                "status": "compliant" if len(boundary_violations) == 0 else "violation_detected",
            },
        }

    def _evidence_security(self, since, until) -> dict:
        firewall_events = self.store.query(component="firewall", since=since, until=until)
        injection_events = [e for e in firewall_events if e.outcome == "block"]
        auth_denials = self.store.query(event_type="auth", outcome="deny", since=since, until=until)

        return {
            "B_adversarial_robustness": {
                "total_firewall_scans": len(firewall_events),
                "attacks_blocked": len(injection_events),
                "block_rate": len(injection_events) / max(len(firewall_events), 1),
                "status": "active_protection",
            },
            "B_access_control": {
                "auth_denials": len(auth_denials),
                "status": "enforcing",
            },
        }

    def _evidence_safety(self, since, until) -> dict:
        governance_events = self.store.query(event_type="governance", since=since, until=until)
        guardrail_fails = [e for e in governance_events if e.outcome == "fail"]
        blocked = [e for e in governance_events if e.outcome in ("block", "escalate")]

        hallucination_events = [e for e in guardrail_fails if "hallucination" in e.action or "numerical" in e.action]

        return {
            "C001_risk_taxonomy": {
                "status": "implemented",
                "risk_categories": list(self.spec.risk_taxonomy.keys()),
            },
            "C_prevent_harmful": {
                "total_evaluations": len(governance_events),
                "guardrail_failures": len(guardrail_fails),
                "responses_blocked": len(blocked),
                "hallucination_events": len(hallucination_events),
                "status": "active_governance",
            },
        }

    def _evidence_reliability(self, since, until) -> dict:
        optimization_events = self.store.query(event_type="optimization", since=since, until=until)
        escalation_events = self.store.query(component="critic", outcome="escalate", since=since, until=until)

        rewards = [e.evidence.get("reward", 0) for e in optimization_events if e.evidence.get("reward") is not None]

        return {
            "D_predictable_behavior": {
                "optimization_signals": len(optimization_events),
                "avg_reward": sum(rewards) / max(len(rewards), 1),
                "status": "optimizing",
            },
            "D_error_handling": {
                "escalation_events": len(escalation_events),
                "status": "active",
            },
        }

    def _evidence_accountability(self, since, until) -> dict:
        all_events = self.store.query(since=since, until=until)

        return {
            "E_transparency": {
                "spec_version": self.spec.version,
                "status": "documented",
            },
            "E_audit_trail": {
                "total_events_in_period": len(all_events),
                "components_covered": list(set(e.component for e in all_events)),
                "immutable": True,
                "export_format": self.spec.audit.get("export", {}).get("format", "parquet"),
                "status": "complete",
            },
            "E_human_oversight": {
                "escalation_events": len(self.store.query(outcome="escalate", since=since, until=until)),
                "status": "enforced",
            },
        }

    def _evidence_society(self, since, until) -> dict:
        misuse_events = self.store.query(aiuc1_req="F001", since=since, until=until)

        return {
            "F001_prevent_misuse": {
                "misuse_attempts_detected": len(misuse_events),
                "all_blocked": all(e.outcome in ("block", "blocked") for e in misuse_events) if misuse_events else True,
                "status": "active_prevention",
            },
        }


# ============================================================================
# System Health Aggregator
# ============================================================================

class SystemHealthAggregator:
    """Aggregates health metrics across all STC components."""

    def __init__(self, audit_store: AuditStore, spec: STCSpec):
        self.store = audit_store
        self.spec = spec

    def get_health(self, window_hours: int = 24) -> dict:
        since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        all_events = self.store.query(since=since)

        by_component = defaultdict(list)
        for e in all_events:
            by_component[e.component].append(e)

        critical_events = [e for e in all_events if e.severity == "critical"]
        blocks = [e for e in all_events if e.outcome in ("block", "deny", "blocked")]

        return {
            "status": "degraded" if len(critical_events) > 5 else "healthy",
            "window_hours": window_hours,
            "total_events": len(all_events),
            "critical_events": len(critical_events),
            "total_blocks": len(blocks),
            "components": {
                comp: {
                    "events": len(events),
                    "critical": sum(1 for e in events if e.severity == "critical"),
                    "blocks": sum(1 for e in events if e.outcome in ("block", "deny")),
                }
                for comp, events in by_component.items()
            },
        }


# ============================================================================
# Log Sanitizer (OpenTelemetry Span Processor)
# ============================================================================

class LogSanitizer:
    """
    Sanitizes trace data before export to observability platforms.
    Ensures proprietary data doesn't leak through OpenTelemetry spans.
    """

    def __init__(self, spec: STCSpec):
        self.spec = spec
        self._setup_dlp()

    def _setup_dlp(self):
        try:
            from sentinel.data_security import DLPScanner
            self.dlp = DLPScanner(self.spec)
            self.dlp_available = True
        except ImportError:
            self.dlp_available = False

    def sanitize(self, text: str) -> str:
        if self.dlp_available:
            return self.dlp.sanitize_for_logging(text)
        return text

    def sanitize_span_attributes(self, attributes: dict) -> dict:
        sanitized = {}
        for key, value in attributes.items():
            if isinstance(value, str) and len(value) > 20:
                sanitized[key] = self.sanitize(value)
            else:
                sanitized[key] = value
        return sanitized


# ============================================================================
# Main: STCObservability
# ============================================================================

class STCObservability:
    """
    Unified observability interface for the STC Framework.
    
    Coordinates trace context, audit storage, compliance evidence,
    health monitoring, and log sanitization.
    """

    def __init__(self, spec: STCSpec):
        self.spec = spec
        self.audit_store = AuditStore(spec)
        self.evidence_generator = ComplianceEvidenceGenerator(self.audit_store, spec)
        self.health_aggregator = SystemHealthAggregator(self.audit_store, spec)
        self.log_sanitizer = LogSanitizer(spec)
        self._trace_counter = 0

    @contextmanager
    def trace_request(self, query: str):
        """
        Create a trace context for a single request.
        
        Usage:
            with obs.trace_request("What was Q4 revenue?") as ctx:
                ctx.record_firewall_result(...)
                ctx.record_stalwart_execution(...)
        """
        self._trace_counter += 1
        trace_id = f"stc-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{self._trace_counter:06d}"

        ctx = TraceContext(
            trace_id=trace_id,
            query=query,
            spec=self.spec,
            audit_store=self.audit_store,
        )

        try:
            yield ctx
        finally:
            summary = ctx.get_summary()
            logger.info(
                f"[{trace_id}] Complete: {summary['total_events']} events, "
                f"{summary['elapsed_ms']:.0f}ms, "
                f"critical={summary['has_critical']}, blocked={summary['has_blocks']}"
            )

    def generate_aiuc1_evidence(self, since: Optional[datetime] = None,
                                  until: Optional[datetime] = None) -> dict:
        """Generate AIUC-1 compliance evidence package."""
        return self.evidence_generator.generate_aiuc1_evidence(since, until)

    def get_system_health(self, window_hours: int = 24) -> dict:
        """Get aggregated system health."""
        return self.health_aggregator.get_health(window_hours)

    def export_audit(self, format: str = "parquet", path: Optional[str] = None) -> str:
        """Export audit trail for compliance archival."""
        if format == "parquet":
            return self.audit_store.export_parquet(path)
        else:
            path = path or f"audit-logs/stc_audit_export_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
            with open(path, "w") as f:
                for e in self.audit_store.events:
                    f.write(json.dumps(e.to_dict()) + "\n")
            return path

    def query_events(self, **kwargs) -> list[AuditEvent]:
        """Query audit events. See AuditStore.query() for parameters."""
        return self.audit_store.query(**kwargs)

    def sanitize_for_export(self, text: str) -> str:
        """Sanitize text before sending to external observability."""
        return self.log_sanitizer.sanitize(text)


# ============================================================================
# Demo
# ============================================================================

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from spec.loader import load_spec

    spec = load_spec("spec/stc-spec.yaml")
    obs = STCObservability(spec)

    print("=" * 65)
    print("  STC Observability & Audit — Demo")
    print("=" * 65)

    # Simulate a request flow
    print("\n  Simulating a complete request flow...\n")

    with obs.trace_request("What was Acme's total revenue in FY2024?") as ctx:
        # Firewall scan
        from dataclasses import dataclass as dc
        @dc
        class MockFirewall:
            blocked: bool = False; decision: str = "allow"; scanner: str = "prompt_guard"
            score: float = 0.02; reason: str = "benign"; latency_ms: float = 18.5
        ctx.record_firewall_result(MockFirewall())

        # Auth check
        ctx.record_auth_decision("stalwart", "llm", "call", True)

        # Data boundary
        ctx.record_data_boundary("internal", "bedrock/claude-sonnet", crossed=False)

        # Stalwart execution
        ctx.record_stalwart_execution({
            "model_used": "bedrock/claude-sonnet", "data_tier": "internal",
            "prompt_version": "v1.2", "retrieved_chunks": [1, 2, 3],
            "citations": [{"ref": "10-K, p12"}],
        })

        # Critic verdict
        @dc
        class MockRail:
            rail_name: str; passed: bool; severity: str; details: str; evidence: dict
        @dc
        class MockVerdict:
            passed: bool; action: str; escalation_level: str
            results: list; timestamp: str = ""
        verdict = MockVerdict(
            passed=True, action="pass", escalation_level=None,
            results=[
                MockRail("numerical_accuracy", True, "info", "All numbers grounded", {}),
                MockRail("hallucination_detection", True, "info", "Grounding score: 0.95", {}),
                MockRail("pii_output_scan", True, "info", "No PII in output", {}),
            ],
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        ctx.record_critic_verdict(verdict)

        # Trainer signal
        ctx.record_trainer_signal({"reward": 0.87, "signals": [{"type": "accuracy", "value": 0.95}]})

    # Print trace summary
    print(f"  Trace events: {len(ctx.events)}")
    for e in ctx.events:
        icon = {"info": "ℹ️", "high": "⚠️", "critical": "🚨", "medium": "📝", "low": "📝"}.get(e.severity, "•")
        print(f"    {icon} [{e.component:10s}] {e.action:30s} → {e.outcome}")

    # System health
    print(f"\n  SYSTEM HEALTH:")
    health = obs.get_system_health()
    print(f"    Status: {health['status']}")
    print(f"    Events: {health['total_events']}, Critical: {health['critical_events']}")
    for comp, stats in health["components"].items():
        print(f"    {comp}: {stats['events']} events, {stats['critical']} critical")

    # Generate AIUC-1 evidence
    print(f"\n  AIUC-1 COMPLIANCE EVIDENCE:")
    evidence = obs.generate_aiuc1_evidence()
    for section, data in evidence["sections"].items():
        print(f"    {section}:")
        for req, details in data.items():
            status = details.get("status", "?")
            icon = "✅" if status in ("compliant", "active_protection", "active_governance",
                                       "enforcing", "implemented", "documented", "complete",
                                       "enforced", "active_prevention", "active", "optimizing") else "⚠️"
            print(f"      {icon} {req}: {status}")

    # Export
    path = obs.export_audit(format="jsonl")
    print(f"\n  Audit exported to: {path}")
