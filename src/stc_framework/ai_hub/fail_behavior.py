"""FR-14 fail-behavior contract as runtime-queryable constants.

The PRD's fail-behavior matrix (§4.14.2) is the authoritative
per-dependency contract for how AI Hub responds when a dependency
fails or times out. Encoding it as data (not prose) lets:

* Runbooks pull the values programmatically.
* Chaos tests assert the declared behavior for each row.
* Service code branch on ``FailOnPolicy`` rather than ad-hoc `if`s.

The matrix lives here as a module-level dict so a test failure of
*"contract violated"* has an obvious diff.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from stc_framework.ai_hub.errors import AIHubErrorCode


class FailOnPolicy(str, Enum):
    """What a dependency failure produces."""

    FAIL_CLOSED = "fail_closed"  # reject the request (most common)
    FAIL_OPEN = "fail_open"  # allow the request through (availability > strict enforcement)
    USE_CACHED = "use_cached"  # keep serving from a cached value (Ping JWKS)
    SURFACE = "surface"  # pass the upstream error through (Bedrock)


@dataclass(frozen=True)
class FailBehavior:
    """One row of the PRD §4.14.2 matrix."""

    dependency: str
    timeout_ms: int
    on_timeout: FailOnPolicy
    on_error: FailOnPolicy
    http_code: int | None
    error_code: AIHubErrorCode | None
    rationale: str


# PRD §4.14.2, row-for-row. If the PRD matrix shifts, update here and
# the chaos suite's parametric tests re-verify.
FAIL_BEHAVIOR_MATRIX: dict[str, FailBehavior] = {
    "ping_jwt_validation": FailBehavior(
        dependency="Ping JWT signature validation",
        timeout_ms=500,
        on_timeout=FailOnPolicy.FAIL_CLOSED,
        on_error=FailOnPolicy.FAIL_CLOSED,
        http_code=401,
        error_code=AIHubErrorCode.INVALID_TOKEN,
        rationale="Auth is non-negotiable.",
    ),
    "ping_jwks_refresh": FailBehavior(
        dependency="Ping JWKS endpoint",
        timeout_ms=1000,
        on_timeout=FailOnPolicy.USE_CACHED,
        on_error=FailOnPolicy.USE_CACHED,
        http_code=None,
        error_code=None,
        rationale="Cached for up to 24h; keeps hub operational during Ping maintenance.",
    ),
    "filter_prompt_injection": FailBehavior(
        dependency="prompt_injection input filter",
        timeout_ms=300,
        on_timeout=FailOnPolicy.FAIL_CLOSED,
        on_error=FailOnPolicy.FAIL_CLOSED,
        http_code=503,
        error_code=AIHubErrorCode.GUARDRAIL_TIMEOUT,
        rationale="Safety critical.",
    ),
    "filter_pii_input": FailBehavior(
        dependency="pii_input filter",
        timeout_ms=300,
        on_timeout=FailOnPolicy.FAIL_CLOSED,
        on_error=FailOnPolicy.FAIL_CLOSED,
        http_code=503,
        error_code=AIHubErrorCode.GUARDRAIL_TIMEOUT,
        rationale="Safety critical.",
    ),
    "filter_content_policy_input": FailBehavior(
        dependency="content_policy_input filter",
        timeout_ms=300,
        on_timeout=FailOnPolicy.FAIL_CLOSED,
        on_error=FailOnPolicy.FAIL_CLOSED,
        http_code=503,
        error_code=AIHubErrorCode.GUARDRAIL_TIMEOUT,
        rationale="Safety critical.",
    ),
    "bedrock_invoke": FailBehavior(
        dependency="Bedrock InvokeModel",
        timeout_ms=30_000,
        on_timeout=FailOnPolicy.SURFACE,
        on_error=FailOnPolicy.SURFACE,
        http_code=504,
        error_code=AIHubErrorCode.BEDROCK_TIMEOUT,
        rationale="Upstream surfaced; caller framework is better positioned to retry.",
    ),
    "filter_pii_output": FailBehavior(
        dependency="pii_output filter",
        timeout_ms=300,
        on_timeout=FailOnPolicy.FAIL_CLOSED,
        on_error=FailOnPolicy.FAIL_CLOSED,
        http_code=502,
        error_code=AIHubErrorCode.GUARDRAIL_TIMEOUT,
        rationale="Safety critical.",
    ),
    "filter_harmful_content": FailBehavior(
        dependency="harmful_content filter",
        timeout_ms=300,
        on_timeout=FailOnPolicy.FAIL_CLOSED,
        on_error=FailOnPolicy.FAIL_CLOSED,
        http_code=502,
        error_code=AIHubErrorCode.GUARDRAIL_TIMEOUT,
        rationale="Safety critical.",
    ),
    "filter_policy_compliance_output": FailBehavior(
        dependency="policy_compliance_output filter",
        timeout_ms=300,
        on_timeout=FailOnPolicy.FAIL_CLOSED,
        on_error=FailOnPolicy.FAIL_CLOSED,
        http_code=502,
        error_code=AIHubErrorCode.GUARDRAIL_TIMEOUT,
        rationale="Safety critical.",
    ),
    "audit_write": FailBehavior(
        dependency="Audit ledger write (S3 + OpenSearch)",
        timeout_ms=1000,
        on_timeout=FailOnPolicy.FAIL_CLOSED,
        on_error=FailOnPolicy.FAIL_CLOSED,
        http_code=503,
        error_code=AIHubErrorCode.AUDIT_UNAVAILABLE,
        rationale="Compliance: no unlogged Bedrock calls.",
    ),
    "rate_limit_redis": FailBehavior(
        dependency="Rate-limit counters (Redis)",
        timeout_ms=100,
        on_timeout=FailOnPolicy.FAIL_OPEN,
        on_error=FailOnPolicy.FAIL_OPEN,
        http_code=None,
        error_code=None,
        rationale="Operational protection; spend cap is the Postgres-backed safety net.",
    ),
    "spend_cap_evaluator": FailBehavior(
        dependency="Spend cap evaluator (Postgres)",
        timeout_ms=200,
        on_timeout=FailOnPolicy.FAIL_CLOSED,
        on_error=FailOnPolicy.FAIL_CLOSED,
        http_code=503,
        error_code=AIHubErrorCode.DEPENDENCY_UNAVAILABLE,
        rationale="Financial control.",
    ),
    "postgres_entitlement": FailBehavior(
        dependency="Postgres entitlement read",
        timeout_ms=200,
        on_timeout=FailOnPolicy.FAIL_CLOSED,
        on_error=FailOnPolicy.FAIL_CLOSED,
        http_code=503,
        error_code=AIHubErrorCode.DEPENDENCY_UNAVAILABLE,
        rationale="Cannot verify allowlist without it.",
    ),
}


__all__ = ["FAIL_BEHAVIOR_MATRIX", "FailBehavior", "FailOnPolicy"]
