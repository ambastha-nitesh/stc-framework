"""Tests for the PRD-shaped audit record + fail-behavior matrix."""

from __future__ import annotations

from datetime import datetime, timezone

from stc_framework.ai_hub.audit_record import (
    AIHubAuditRecord,
    AuditOutcome,
    compose_audit_record,
)
from stc_framework.ai_hub.errors import AIHubErrorCode
from stc_framework.ai_hub.fail_behavior import (
    FAIL_BEHAVIOR_MATRIX,
    FailOnPolicy,
)
from stc_framework.ai_hub.filter_chain import (
    FilterDirection,
    FilterOutcome,
    FilterVerdict,
)

# ---------- Audit record -------------------------------------------------


def test_audit_record_happy_path() -> None:
    ts = datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)
    verdicts = [
        FilterVerdict(
            filter_name="prompt_injection",
            direction=FilterDirection.INPUT,
            outcome=FilterOutcome.ALLOW,
            latency_ms=180,
        ),
        FilterVerdict(
            filter_name="pii_input",
            direction=FilterDirection.INPUT,
            outcome=FilterOutcome.ALLOW,
            latency_ms=95,
        ),
    ]
    record = compose_audit_record(
        request_id="01JABCDEF0123456789ABCDEFGH",
        domain_id="d-1",
        agent_id="a-1",
        model_id="claude-haiku-4-5",
        model_arn="anthropic.claude-haiku-4-5-v1:0",
        outcome=AuditOutcome.ALLOWED,
        verdicts=verdicts,
        latency_ms_hub=412,
        latency_ms_total=2252,
        latency_ms_bedrock=1840,
        payload_s3_key="audit/v1/domain=d-1/date=2026-04-19/request_id=...json.enc",
        timestamp_request=ts,
        timestamp_response=ts,
        input_tokens=482,
        output_tokens=1021,
        cost_usd=1.67,
        client_id="client-abc",
    )
    assert record.outcome is AuditOutcome.ALLOWED
    assert record.total_tokens == 482 + 1021
    serialised = record.to_json_serialisable()
    # Schema sanity: every Appendix-C required field is present.
    for k in (
        "schema_version",
        "request_id",
        "domain_id",
        "agent_id",
        "timestamp_request",
        "timestamp_response",
        "model_id",
        "outcome",
        "filter_verdicts",
        "latency_ms_hub",
        "latency_ms_total",
        "payload_s3_key",
    ):
        assert k in serialised
    assert serialised["schema_version"] == "1.0"
    assert serialised["outcome"] == "allowed"
    # Filter verdicts serialise as dicts with the Appendix-C shape.
    assert serialised["filter_verdicts"][0]["direction"] == "input"
    assert serialised["filter_verdicts"][0]["outcome"] == "ALLOW"


def test_audit_record_rejected_input_has_no_tokens() -> None:
    record = compose_audit_record(
        request_id="01J",
        domain_id="d-1",
        agent_id="a-1",
        model_id="claude-haiku-4-5",
        outcome=AuditOutcome.REJECTED_INPUT,
        verdicts=[
            FilterVerdict(
                filter_name="prompt_injection",
                direction=FilterDirection.INPUT,
                outcome=FilterOutcome.BLOCK,
                latency_ms=180,
            ),
        ],
        latency_ms_hub=200,
        latency_ms_total=200,
        payload_s3_key="audit/...enc",
        error_code=AIHubErrorCode.GUARDRAIL_INPUT_BLOCK.value,
    )
    assert record.total_tokens is None
    assert record.latency_ms_bedrock is None
    assert record.error_code == "guardrail_input_block"


def test_audit_record_accepts_none_metadata() -> None:
    record = compose_audit_record(
        request_id="x",
        domain_id="d",
        agent_id="a",
        model_id="m",
        outcome=AuditOutcome.ERROR,
        verdicts=[],
        latency_ms_hub=0,
        latency_ms_total=0,
        payload_s3_key="k",
        metadata=None,
    )
    # metadata defaults to {} when None supplied — mirrors PRD "optional".
    assert record.metadata == {}


def test_audit_record_is_dataclass_immutable_enough() -> None:
    r = AIHubAuditRecord(
        request_id="x",
        domain_id="d",
        agent_id="a",
        timestamp_request="ts",
        timestamp_response="ts",
        model_id="m",
        outcome=AuditOutcome.ALLOWED,
        filter_verdicts=[],
        latency_ms_hub=0,
        latency_ms_total=0,
        payload_s3_key="k",
    )
    # Mutating via setattr is allowed (dataclass is not frozen), but the
    # expected usage is the composer helper.
    assert r.schema_version == "1.0"


# ---------- Fail-behavior matrix (FR-14) --------------------------------


def test_matrix_covers_every_prd_row() -> None:
    expected = {
        "ping_jwt_validation",
        "ping_jwks_refresh",
        "filter_prompt_injection",
        "filter_pii_input",
        "filter_content_policy_input",
        "bedrock_invoke",
        "filter_pii_output",
        "filter_harmful_content",
        "filter_policy_compliance_output",
        "audit_write",
        "rate_limit_redis",
        "spend_cap_evaluator",
        "postgres_entitlement",
    }
    assert expected.issubset(FAIL_BEHAVIOR_MATRIX.keys())


def test_every_filter_row_is_fail_closed_503_or_502() -> None:
    for name, row in FAIL_BEHAVIOR_MATRIX.items():
        if not name.startswith("filter_"):
            continue
        assert row.on_timeout is FailOnPolicy.FAIL_CLOSED, name
        assert row.on_error is FailOnPolicy.FAIL_CLOSED, name
        # Input filters map to 503; output filters map to 502 (PRD Appendix A).
        if name in {
            "filter_pii_output",
            "filter_harmful_content",
            "filter_policy_compliance_output",
        }:
            # PRD §4.5.4 exception paths — guardrail timeout on the OUTPUT
            # side is still 503 in the matrix row (filter_timeout itself);
            # it's the BLOCK that's 502. Allow either.
            assert row.http_code in (502, 503)
        else:
            assert row.http_code == 503


def test_rate_limit_row_is_the_only_fail_open() -> None:
    fail_open_rows = [name for name, row in FAIL_BEHAVIOR_MATRIX.items() if row.on_timeout is FailOnPolicy.FAIL_OPEN]
    assert fail_open_rows == ["rate_limit_redis"]


def test_audit_write_row_commits_to_fail_closed() -> None:
    row = FAIL_BEHAVIOR_MATRIX["audit_write"]
    assert row.on_timeout is FailOnPolicy.FAIL_CLOSED
    assert row.on_error is FailOnPolicy.FAIL_CLOSED
    assert row.http_code == 503
    assert row.error_code is AIHubErrorCode.AUDIT_UNAVAILABLE


def test_ping_jwks_row_uses_cached_on_failure() -> None:
    row = FAIL_BEHAVIOR_MATRIX["ping_jwks_refresh"]
    assert row.on_timeout is FailOnPolicy.USE_CACHED
    assert row.on_error is FailOnPolicy.USE_CACHED
    assert row.http_code is None  # no caller-visible status


def test_bedrock_row_surfaces_upstream() -> None:
    row = FAIL_BEHAVIOR_MATRIX["bedrock_invoke"]
    assert row.on_timeout is FailOnPolicy.SURFACE
    assert row.on_error is FailOnPolicy.SURFACE
