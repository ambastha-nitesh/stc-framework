"""PRD error-code catalogue (Appendix A of ``docs/ai-hub-prd.md``).

Every error response from an MVP AI Hub endpoint must use one of these
codes in ``error.code``. Rendering the code to an HTTP status is done
by :func:`http_status_for_code`; the mapping matches the PRD row-for-row.

This catalogue is intentionally separate from
:mod:`stc_framework.errors`. The base STC library has its own, wider
error taxonomy (retryable / downstream / persona / etc.) and we do
not force AI Hub consumers to learn the whole library's vocabulary
just to parse an error envelope. Library-level errors are translated
to AI Hub codes at the service edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AIHubErrorCode(str, Enum):
    """Every ``error.code`` string that appears in the MVP error envelope."""

    # 400 — client schema + eligibility errors
    INVALID_REQUEST = "invalid_request"
    INVALID_MODEL_ID = "invalid_model_id"
    STREAMING_NOT_SUPPORTED = "streaming_not_supported"
    CONTENT_BLOCK_NOT_SUPPORTED = "content_block_not_supported"
    CONTEXT_WINDOW_EXCEEDED = "context_window_exceeded"
    USER_NOT_FOUND = "user_not_found"
    RESTRICTED_MODEL_NOT_ELIGIBLE = "restricted_model_not_eligible"
    LIMIT_ABOVE_CEILING = "limit_above_ceiling"
    QUERY_RANGE_TOO_LARGE = "query_range_too_large"

    # 401 — authentication
    MISSING_TOKEN = "missing_token"
    MALFORMED_AUTHORIZATION_HEADER = "malformed_authorization_header"
    INVALID_TOKEN = "invalid_token"
    INVALID_ISSUER = "invalid_issuer"
    INVALID_AUDIENCE = "invalid_audience"
    TOKEN_EXPIRED = "token_expired"
    TOKEN_NOT_YET_VALID = "token_not_yet_valid"

    # 403 — authorisation
    INSUFFICIENT_SCOPE = "insufficient_scope"
    MODEL_NOT_ALLOWED = "model_not_allowed"
    AGENT_SUSPENDED = "agent_suspended"
    DOMAIN_SUSPENDED = "domain_suspended"
    DOMAIN_NOT_ACTIVE = "domain_not_active"
    OUT_OF_SCOPE_PARTITION = "out_of_scope_partition"

    # 409 — conflict / onboarding
    DOMAIN_NAME_CONFLICT = "domain_name_conflict"
    AGENT_NAME_CONFLICT = "agent_name_conflict"
    DOMAIN_HAS_ACTIVE_AGENTS = "domain_has_active_agents"
    AGENT_RECENTLY_ACTIVE = "agent_recently_active"
    REQUEST_ALREADY_DECIDED = "request_already_decided"

    # 410 — gone
    STARTER_KIT_ALREADY_DOWNLOADED = "starter_kit_already_downloaded"

    # 413 — payload too large
    REQUEST_TOO_LARGE = "request_too_large"

    # 422 — guardrail input block
    GUARDRAIL_INPUT_BLOCK = "guardrail_input_block"

    # 429 — throttling + spend
    RATE_LIMIT_RPM = "rate_limit_rpm"
    RATE_LIMIT_TPM = "rate_limit_tpm"
    SPEND_CAP_EXCEEDED = "spend_cap_exceeded"
    BEDROCK_THROTTLED = "bedrock_throttled"

    # 502 — output block / upstream
    GUARDRAIL_OUTPUT_BLOCK = "guardrail_output_block"
    BEDROCK_ERROR = "bedrock_error"

    # 503 — fail-closed
    GUARDRAIL_TIMEOUT = "guardrail_timeout"
    GUARDRAIL_ERROR = "guardrail_error"
    AUDIT_UNAVAILABLE = "audit_unavailable"
    AUTH_UNAVAILABLE = "auth_unavailable"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    IDP_UNAVAILABLE = "idp_unavailable"

    # 504 — upstream timeout
    BEDROCK_TIMEOUT = "bedrock_timeout"


# Authoritative mapping from error code to HTTP status. Mirrors
# Appendix A of the PRD row-for-row. When the PRD shifts, this is the
# only place to update.
_HTTP_STATUS: dict[AIHubErrorCode, int] = {
    AIHubErrorCode.INVALID_REQUEST: 400,
    AIHubErrorCode.INVALID_MODEL_ID: 400,
    AIHubErrorCode.STREAMING_NOT_SUPPORTED: 400,
    AIHubErrorCode.CONTENT_BLOCK_NOT_SUPPORTED: 400,
    AIHubErrorCode.CONTEXT_WINDOW_EXCEEDED: 400,
    AIHubErrorCode.USER_NOT_FOUND: 400,
    AIHubErrorCode.RESTRICTED_MODEL_NOT_ELIGIBLE: 400,
    AIHubErrorCode.LIMIT_ABOVE_CEILING: 400,
    AIHubErrorCode.QUERY_RANGE_TOO_LARGE: 400,
    AIHubErrorCode.MISSING_TOKEN: 401,
    AIHubErrorCode.MALFORMED_AUTHORIZATION_HEADER: 401,
    AIHubErrorCode.INVALID_TOKEN: 401,
    AIHubErrorCode.INVALID_ISSUER: 401,
    AIHubErrorCode.INVALID_AUDIENCE: 401,
    AIHubErrorCode.TOKEN_EXPIRED: 401,
    AIHubErrorCode.TOKEN_NOT_YET_VALID: 401,
    AIHubErrorCode.INSUFFICIENT_SCOPE: 403,
    AIHubErrorCode.MODEL_NOT_ALLOWED: 403,
    AIHubErrorCode.AGENT_SUSPENDED: 403,
    AIHubErrorCode.DOMAIN_SUSPENDED: 403,
    AIHubErrorCode.DOMAIN_NOT_ACTIVE: 403,
    AIHubErrorCode.OUT_OF_SCOPE_PARTITION: 403,
    AIHubErrorCode.DOMAIN_NAME_CONFLICT: 409,
    AIHubErrorCode.AGENT_NAME_CONFLICT: 409,
    AIHubErrorCode.DOMAIN_HAS_ACTIVE_AGENTS: 409,
    AIHubErrorCode.AGENT_RECENTLY_ACTIVE: 409,
    AIHubErrorCode.REQUEST_ALREADY_DECIDED: 409,
    AIHubErrorCode.STARTER_KIT_ALREADY_DOWNLOADED: 410,
    AIHubErrorCode.REQUEST_TOO_LARGE: 413,
    AIHubErrorCode.GUARDRAIL_INPUT_BLOCK: 422,
    AIHubErrorCode.RATE_LIMIT_RPM: 429,
    AIHubErrorCode.RATE_LIMIT_TPM: 429,
    AIHubErrorCode.SPEND_CAP_EXCEEDED: 429,
    AIHubErrorCode.BEDROCK_THROTTLED: 429,
    AIHubErrorCode.GUARDRAIL_OUTPUT_BLOCK: 502,
    AIHubErrorCode.BEDROCK_ERROR: 502,
    AIHubErrorCode.GUARDRAIL_TIMEOUT: 503,
    AIHubErrorCode.GUARDRAIL_ERROR: 503,
    AIHubErrorCode.AUDIT_UNAVAILABLE: 503,
    AIHubErrorCode.AUTH_UNAVAILABLE: 503,
    AIHubErrorCode.DEPENDENCY_UNAVAILABLE: 503,
    AIHubErrorCode.IDP_UNAVAILABLE: 503,
    AIHubErrorCode.BEDROCK_TIMEOUT: 504,
}


def http_status_for_code(code: AIHubErrorCode) -> int:
    """Return the HTTP status for a PRD error code (Appendix A)."""
    return _HTTP_STATUS[code]


@dataclass
class AIHubError(Exception):
    """Exception carrying a PRD error code + optional sub-fields.

    Thrown inside AI Hub code paths; the service edge renders the
    envelope ``{"error": {"code", "message", "filter", "field",
    "request_id"}}`` from the fields here.
    """

    code: AIHubErrorCode
    message: str = ""
    filter_name: str | None = None
    field_pointer: str | None = None
    request_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        parts = [self.code.value]
        if self.message:
            parts.append(self.message)
        if self.filter_name:
            parts.append(f"filter={self.filter_name}")
        if self.field_pointer:
            parts.append(f"field={self.field_pointer}")
        return " | ".join(parts)

    @property
    def http_status(self) -> int:
        return http_status_for_code(self.code)

    def to_envelope(self) -> dict[str, Any]:
        """Render the JSON envelope described in PRD section 4.1.7."""
        payload: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message or self.code.value,
        }
        if self.filter_name is not None:
            payload["filter"] = self.filter_name
        if self.field_pointer is not None:
            payload["field"] = self.field_pointer
        if self.request_id is not None:
            payload["request_id"] = self.request_id
        if self.extra:
            payload.update(self.extra)
        return {"error": payload}


__all__ = ["AIHubError", "AIHubErrorCode", "http_status_for_code"]
