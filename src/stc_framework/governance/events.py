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
