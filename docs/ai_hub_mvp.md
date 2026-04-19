# AI Hub MVP — enforcement-layer implementation

This document maps the AI Hub PRD (`ai-hub-prd.md`) to the
`src/stc_framework/ai_hub/` package and documents what the Python
library implements versus what lives elsewhere (Kong, Ping, Terraform,
dashboards).

## Why these boundaries

The PRD describes an AI Control Plane that spans:

* **Kong AI Gateway** (data plane) — TLS, JWT validation, RPM edge
  limiting, routing.
* **AI Hub Core** (control plane) — entitlement, filter chain,
  Bedrock invocation, audit capture.
* **Registration Service** — domain + agent onboarding workflows.
* **Dashboard API + UIs** — platform + domain-owner dashboards.
* **Storage** — S3 Object Lock audit payloads, OpenSearch metadata,
  Aurora operational data, ElastiCache Redis counters.
* **Ping Identity** — the sole OAuth 2.0 / OIDC provider.

The STC Framework is the reference implementation of the
**enforcement-layer** pieces of AI Hub Core: allowlist, filter-chain
orchestration, RPM / TPM / spend-cap checks, the PRD error-code
catalogue, and the PRD-shaped audit record. It does **not** implement
Kong config, the Ping admin-API dance, the dashboards, or the
registration workflow — those live in sibling services or in the
Terraform stack at `infra/terraform/`.

## PRD-to-code map

| PRD FR | `src/stc_framework/ai_hub/` module | Notes |
|---|---|---|
| FR-1 model access | `allowlist.py` (`ModelCatalogEntry`) + `errors.py` | Catalogue matches PRD §4.1.10; request/response schema enforced by the service layer (not in this package). |
| FR-2 edge auth | — | Kong's responsibility. |
| FR-3 input filter chain | `filter_chain.FilterChainOrchestrator(direction=INPUT)` | Sequential, 300 ms per filter, fail-closed. Short-circuits on first non-ALLOW. |
| FR-4 M2M auth | — | Ping client-credentials; library consumes the resulting JWT claims but does not implement the flow. |
| FR-5 output filter chain | `filter_chain.FilterChainOrchestrator(direction=OUTPUT)` | Same orchestrator; output BLOCK maps to HTTP 502 per Appendix A. |
| FR-6 RBAC | — | Scope validation is Kong; partition enforcement is in the Dashboard API. |
| FR-7 domain onboarding | — | Registration Service. |
| FR-8 agent onboarding | `allowlist.register_agent` defaults to exactly `claude-haiku-4-5` (AC-10.1). | Starter-kit ZIP generation is the Registration Service. |
| FR-9 rate limits + caps | `rate_limits.AgentRateLimiter` + `rate_limits.SpendCapProjector` | RPM + TPM minute-windowed; spend cap projection with override support. |
| FR-10 per-agent allowlist | `allowlist.AgentAllowlist` | Default deny; `assert_allowed` raises PRD errors. |
| FR-11 platform dashboard | — | Separate service. |
| FR-12 domain dashboard | — | Separate service. |
| FR-13 audit ledger | `audit_record.AIHubAuditRecord` + `audit_record.compose_audit_record` | PRD Appendix C shape. S3 + OpenSearch writes happen at the service edge; Object Lock is Terraform-managed. |
| FR-14 fail-behavior | `fail_behavior.FAIL_BEHAVIOR_MATRIX` | 13-row matrix encoded as data; chaos tests parametrise over it. |

## Quick reference — wiring a request

Pseudocode for a FastAPI handler that stitches the primitives together:

```python
from stc_framework.ai_hub import (
    AIHubError,
    AIHubErrorCode,
    AgentAllowlist,
    AgentRateLimiter,
    AuditOutcome,
    FilterChainBlocked,
    FilterChainError,
    FilterChainOrchestrator,
    FilterDirection,
    FilterInput,
    SpendCapProjector,
    compose_audit_record,
)

async def invoke(request, *, agent_ctx, allowlist, rate_limiter, cap, input_chain, output_chain, bedrock, audit_writer):
    # FR-1: validate model and allowlist
    model = allowlist.assert_allowed(agent_ctx.agent_id, request.model_id)
    allowlist.assert_agent_active(agent_ctx)
    allowlist.assert_restricted_tier_eligible(request.model_id, agent_ctx)

    # FR-9: projection pre-check
    projected_tokens = estimate_tokens(request) + request.inference_params.max_tokens
    rate_limiter.check_rpm(agent_ctx.agent_id, rpm_limit=agent_ctx.rpm_limit)
    rate_limiter.check_tpm_projection(agent_ctx.agent_id, projected_tokens=projected_tokens, tpm_limit=agent_ctx.tpm_limit)
    cap.assert_within(agent_ctx.domain_id, projected_cost_usd=projected_tokens * price_per_token(model))

    # FR-3: input filter chain (fail-closed, 300 ms per filter)
    filter_input = FilterInput(request_id=request.request_id, domain_id=agent_ctx.domain_id, agent_id=agent_ctx.agent_id, payload={"system": request.system, "messages": request.messages})
    try:
        input_verdicts = await input_chain.run(filter_input)
    except FilterChainBlocked as e:
        return audit_and_raise(AuditOutcome.REJECTED_INPUT, e.verdicts, e)
    except FilterChainError as e:
        return audit_and_raise(AuditOutcome.ERROR, e.verdicts, e)

    # FR-1: invoke Bedrock
    bedrock_response = await bedrock.invoke(model.bedrock_identifier, request)

    # FR-5: output filter chain
    try:
        output_verdicts = await output_chain.run(
            FilterInput(request_id=request.request_id, domain_id=agent_ctx.domain_id, agent_id=agent_ctx.agent_id, payload={"completion": bedrock_response.completion})
        )
    except FilterChainBlocked as e:
        # Tokens ARE charged; see FR-5 §4.5.5
        rate_limiter.record_tokens(agent_ctx.agent_id, tokens=bedrock_response.total_tokens)
        cap.record_spend(agent_ctx.domain_id, actual_cost_usd=bedrock_response.cost_usd)
        return audit_and_raise(AuditOutcome.REJECTED_OUTPUT, input_verdicts + e.verdicts, e)

    # FR-9: post-update — record actual tokens + cost
    rate_limiter.record_request(agent_ctx.agent_id)
    rate_limiter.record_tokens(agent_ctx.agent_id, tokens=bedrock_response.total_tokens)
    cap.record_spend(agent_ctx.domain_id, actual_cost_usd=bedrock_response.cost_usd)

    # FR-13: compose + persist PRD-shaped audit record
    record = compose_audit_record(
        request_id=request.request_id,
        domain_id=agent_ctx.domain_id,
        agent_id=agent_ctx.agent_id,
        model_id=request.model_id,
        model_arn=model.bedrock_identifier,
        outcome=AuditOutcome.ALLOWED,
        verdicts=input_verdicts + output_verdicts,
        latency_ms_hub=...,
        latency_ms_total=...,
        latency_ms_bedrock=bedrock_response.latency_ms,
        payload_s3_key=...,
        input_tokens=bedrock_response.input_tokens,
        output_tokens=bedrock_response.output_tokens,
        cost_usd=bedrock_response.cost_usd,
    )
    await audit_writer.write(record)
    return bedrock_response
```

The snippet deliberately omits retries, metrics, OpenTelemetry spans,
and the `request_id` header wiring — those belong in the HTTP layer,
not in the enforcement primitives.

## What's still out of the Python library's scope

* **Request / response schema enforcement** for `/v1/inference` — a
  FastAPI pydantic model at the service edge. The library does not
  parse HTTP request bodies.
* **Token estimator** — `tiktoken` or Anthropic's tokenizer plugged in
  at the service edge with per-model selection. The rate-limit APIs
  take a pre-computed `projected_tokens` integer.
* **S3 + OpenSearch writes** — `AuditWriter` wrapping
  `AIHubAuditRecord`; implemented alongside the HTTP service.
* **Ping JWKS validation** — Kong plugin or FastAPI middleware.
* **Dashboard aggregation queries** — separate services.
* **Starter-kit generator** — Registration Service owns this.
* **Threshold alert emails** (80/95/100 % of cap) — a scheduled task
  that reads the spend projector's state and dispatches via SES /
  SMTP.

## See also

* `docs/deployment/feature_flags.md` — LaunchDarkly MVP flag catalogue.
* `docs/deployment/aws.md` — AWS / Terraform runbook.
* `ai-hub-prd.md` — the authoritative PRD.
