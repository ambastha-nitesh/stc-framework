"""AI Hub MVP — enforcement primitives aligned with ``docs/ai-hub-prd.md``.

This subpackage implements the Python-side enforcement surface of the
AI Hub MVP. It is deliberately narrow:

* The *infrastructure* pieces (Kong edge, Ping Identity OAuth flows,
  dashboards, domain / agent onboarding workflows, starter-kit
  generation, S3 Object Lock + per-domain KMS keys) live outside this
  package — Kong is a separate data-plane, Ping is an external SaaS,
  and the object-store / KMS wiring lives in the Terraform stack at
  ``infra/terraform/``.
* The *policy / enforcement* pieces — per-agent model allowlists, the
  FR-3 / FR-5 filter-chain orchestrator, RPM + TPM rate limiting, the
  PRD error-code catalogue, and the PRD-shaped audit record — belong
  to this library and are implemented here.

Every module in this subpackage cross-references the FR it satisfies
so an engineer reading the PRD can navigate to the code and back.
"""

from stc_framework.ai_hub.allowlist import (
    AgentAllowlist,
    AgentContext,
    ModelAllowlistError,
    ModelCatalogEntry,
    ModelTier,
    default_catalog,
)
from stc_framework.ai_hub.audit_record import (
    AIHubAuditRecord,
    AuditOutcome,
    compose_audit_record,
)
from stc_framework.ai_hub.errors import (
    AIHubError,
    AIHubErrorCode,
    http_status_for_code,
)
from stc_framework.ai_hub.fail_behavior import (
    FAIL_BEHAVIOR_MATRIX,
    FailBehavior,
    FailOnPolicy,
)
from stc_framework.ai_hub.filter_chain import (
    Filter,
    FilterChainBlocked,
    FilterChainError,
    FilterChainOrchestrator,
    FilterDirection,
    FilterInput,
    FilterOutcome,
    FilterVerdict,
)
from stc_framework.ai_hub.rate_limits import (
    AgentRateLimiter,
    RateLimitExceeded,
    SpendCapExceeded,
    SpendCapProjector,
    TPMWindow,
)

__all__ = [
    "FAIL_BEHAVIOR_MATRIX",
    "AIHubAuditRecord",
    "AIHubError",
    "AIHubErrorCode",
    "AgentAllowlist",
    "AgentContext",
    "AgentRateLimiter",
    "AuditOutcome",
    "FailBehavior",
    "FailOnPolicy",
    "Filter",
    "FilterChainBlocked",
    "FilterChainError",
    "FilterChainOrchestrator",
    "FilterDirection",
    "FilterInput",
    "FilterOutcome",
    "FilterVerdict",
    "ModelAllowlistError",
    "ModelCatalogEntry",
    "ModelTier",
    "RateLimitExceeded",
    "SpendCapExceeded",
    "SpendCapProjector",
    "TPMWindow",
    "compose_audit_record",
    "default_catalog",
    "http_status_for_code",
]
