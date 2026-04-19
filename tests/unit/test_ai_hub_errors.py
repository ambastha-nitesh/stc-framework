"""PRD Appendix A round-trip tests for the AI Hub error code catalogue."""

from __future__ import annotations

import pytest

from stc_framework.ai_hub.errors import (
    AIHubError,
    AIHubErrorCode,
    http_status_for_code,
)


def test_every_code_has_http_status() -> None:
    for code in AIHubErrorCode:
        assert isinstance(http_status_for_code(code), int), code


def test_selected_status_mappings_match_prd() -> None:
    # Spot-checks against PRD Appendix A so any code-to-status drift
    # fails loud rather than silently miscategorising errors.
    assert http_status_for_code(AIHubErrorCode.INVALID_MODEL_ID) == 400
    assert http_status_for_code(AIHubErrorCode.MISSING_TOKEN) == 401
    assert http_status_for_code(AIHubErrorCode.MODEL_NOT_ALLOWED) == 403
    assert http_status_for_code(AIHubErrorCode.AGENT_NAME_CONFLICT) == 409
    assert http_status_for_code(AIHubErrorCode.STARTER_KIT_ALREADY_DOWNLOADED) == 410
    assert http_status_for_code(AIHubErrorCode.REQUEST_TOO_LARGE) == 413
    assert http_status_for_code(AIHubErrorCode.GUARDRAIL_INPUT_BLOCK) == 422
    assert http_status_for_code(AIHubErrorCode.RATE_LIMIT_RPM) == 429
    assert http_status_for_code(AIHubErrorCode.SPEND_CAP_EXCEEDED) == 429
    assert http_status_for_code(AIHubErrorCode.GUARDRAIL_OUTPUT_BLOCK) == 502
    assert http_status_for_code(AIHubErrorCode.GUARDRAIL_TIMEOUT) == 503
    assert http_status_for_code(AIHubErrorCode.AUDIT_UNAVAILABLE) == 503
    assert http_status_for_code(AIHubErrorCode.BEDROCK_TIMEOUT) == 504


def test_envelope_round_trip() -> None:
    err = AIHubError(
        code=AIHubErrorCode.GUARDRAIL_INPUT_BLOCK,
        message="prompt rejected",
        filter_name="prompt_injection",
        request_id="01JABC",
    )
    env = err.to_envelope()
    assert env == {
        "error": {
            "code": "guardrail_input_block",
            "message": "prompt rejected",
            "filter": "prompt_injection",
            "request_id": "01JABC",
        }
    }


def test_envelope_includes_field_pointer_on_schema_errors() -> None:
    err = AIHubError(
        code=AIHubErrorCode.INVALID_REQUEST,
        message="max_tokens too large",
        field_pointer="/inference_params/max_tokens",
    )
    env = err.to_envelope()["error"]
    assert env["field"] == "/inference_params/max_tokens"
    assert "filter" not in env


def test_envelope_extra_fields_pass_through() -> None:
    err = AIHubError(
        code=AIHubErrorCode.RATE_LIMIT_RPM,
        message="too many requests",
        extra={"retry_after_seconds": 12},
    )
    env = err.to_envelope()["error"]
    assert env["retry_after_seconds"] == 12


def test_http_status_property() -> None:
    err = AIHubError(code=AIHubErrorCode.DOMAIN_SUSPENDED)
    assert err.http_status == 403


def test_code_values_are_unique() -> None:
    values = [c.value for c in AIHubErrorCode]
    assert len(values) == len(set(values))


def test_raise_preserves_code_on_aihub_error() -> None:
    with pytest.raises(AIHubError) as ei:
        raise AIHubError(code=AIHubErrorCode.MODEL_NOT_ALLOWED)
    assert ei.value.code is AIHubErrorCode.MODEL_NOT_ALLOWED
