"""PRD Appendix C audit record shape.

The base framework's :class:`~stc_framework.observability.audit.AuditLogger`
writes its own record shape (HMAC-chained, STC-flavoured fields). The
AI Hub PRD calls for a different schema — documented in Appendix C —
with fields like ``outcome``, ``filter_verdicts``, ``payload_s3_key``,
``latency_ms_hub`` etc. This module provides a view layer that
produces the PRD shape from the request context + filter verdicts
without disturbing the base audit chain.

A production deployment layers these records on top of the existing
AuditLogger: the chain-sealed STC audit record remains as the tamper-
evident primary, while the PRD-shaped record is emitted into the
per-domain S3 + OpenSearch partition that dashboards query.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from stc_framework.ai_hub.filter_chain import FilterVerdict


class AuditOutcome(str, Enum):
    """Outcomes recognised by the PRD audit record (§4.13.4)."""

    ALLOWED = "allowed"
    REJECTED_INPUT = "rejected_input"
    REJECTED_OUTPUT = "rejected_output"
    REJECTED_RATE = "rejected_rate"
    REJECTED_CAP = "rejected_cap"
    REJECTED_AUTH = "rejected_auth"
    ERROR = "error"


@dataclass
class AIHubAuditRecord:
    """Canonical audit record matching PRD Appendix C.

    Field names are PRD-verbatim. Optional fields default to ``None``
    to match the JSON-schema ``type: [..., null]`` semantics. A record
    is typically composed via :func:`compose_audit_record` and then
    serialised to JSON for persistence.
    """

    request_id: str
    domain_id: str
    agent_id: str
    timestamp_request: str
    timestamp_response: str
    model_id: str
    outcome: AuditOutcome
    filter_verdicts: list[dict[str, Any]]
    latency_ms_hub: int
    latency_ms_total: int
    payload_s3_key: str

    schema_version: str = "1.0"
    user_sub: str | None = None
    client_id: str | None = None
    model_arn: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms_bedrock: int | None = None
    error_code: str | None = None
    metadata: dict[str, Any] | None = field(default_factory=dict)

    def to_json_serialisable(self) -> dict[str, Any]:
        """Dict form suitable for ``json.dumps`` — matches Appendix C schema."""
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "domain_id": self.domain_id,
            "agent_id": self.agent_id,
            "user_sub": self.user_sub,
            "client_id": self.client_id,
            "timestamp_request": self.timestamp_request,
            "timestamp_response": self.timestamp_response,
            "model_id": self.model_id,
            "model_arn": self.model_arn,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms_hub": self.latency_ms_hub,
            "latency_ms_bedrock": self.latency_ms_bedrock,
            "latency_ms_total": self.latency_ms_total,
            "outcome": self.outcome.value,
            "error_code": self.error_code,
            "payload_s3_key": self.payload_s3_key,
            "filter_verdicts": list(self.filter_verdicts),
            "metadata": self.metadata if self.metadata is not None else None,
        }


def compose_audit_record(
    *,
    request_id: str,
    domain_id: str,
    agent_id: str,
    model_id: str,
    outcome: AuditOutcome,
    verdicts: list[FilterVerdict],
    latency_ms_hub: int,
    latency_ms_total: int,
    payload_s3_key: str,
    timestamp_request: datetime | None = None,
    timestamp_response: datetime | None = None,
    model_arn: str | None = None,
    user_sub: str | None = None,
    client_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
    latency_ms_bedrock: int | None = None,
    error_code: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AIHubAuditRecord:
    """Assemble a PRD-shaped record from the pieces Core has in hand.

    All the composition rules live here so call sites don't reinvent
    e.g. how ``total_tokens`` is computed or how the filter verdict
    list is serialised.
    """
    req_ts = (timestamp_request or datetime.now(timezone.utc)).isoformat()
    resp_ts = (timestamp_response or datetime.now(timezone.utc)).isoformat()
    total_tokens = None
    if input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return AIHubAuditRecord(
        request_id=request_id,
        domain_id=domain_id,
        agent_id=agent_id,
        timestamp_request=req_ts,
        timestamp_response=resp_ts,
        model_id=model_id,
        outcome=outcome,
        filter_verdicts=[v.as_audit_entry() for v in verdicts],
        latency_ms_hub=latency_ms_hub,
        latency_ms_total=latency_ms_total,
        payload_s3_key=payload_s3_key,
        model_arn=model_arn,
        user_sub=user_sub,
        client_id=client_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        latency_ms_bedrock=latency_ms_bedrock,
        error_code=error_code,
        metadata=metadata or {},
    )


__all__ = ["AIHubAuditRecord", "AuditOutcome", "compose_audit_record"]
