# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | Yes       |

## Reporting a Vulnerability

Please report security vulnerabilities privately. Do **not** open public GitHub
issues for security problems.

Email: security@stc-framework.invalid

Provide:
- A description of the issue
- Steps to reproduce
- Affected versions
- Any proof-of-concept if available

You will receive an acknowledgement within 3 business days. We aim to release a
fix within 30 days of confirmed reports, coordinated with responsible disclosure.

## Security Properties

STC Framework is designed to enforce the following properties by default:

1. **Data sovereignty** — restricted-tier data is routed only to local
   inference endpoints (see `data_sovereignty.routing_policy`).
2. **PII redaction** — Presidio-based redaction runs at the Sentinel gateway
   before any outbound LLM call. Blocked entities raise
   `DataSovereigntyViolation`.
3. **Zero-trust governance** — every Stalwart output is independently
   evaluated by the Critic against configurable rails.
4. **Immutable audit trail** — all boundary crossings, guardrail failures,
   and escalation events are appended to an immutable audit log.
5. **Scoped virtual keys** — each persona (Stalwart, Trainer, Critic)
   operates with a dedicated key whose scope is enforced at the gateway.

Deviations from these defaults (e.g. disabling Presidio via
`STC_PRESIDIO_ENABLED=false`) are audited.

## Audit reports

- Cybersecurity review: [`docs/security/SECURITY_AUDIT.md`](docs/security/SECURITY_AUDIT.md) — regressions in `tests/unit/test_security.py`.
- Data privacy, PII, hallucination, auditability, GDPR / CCPA / HIPAA /
  SOC 2 / AIUC-1 crosswalk: [`docs/security/GOVERNANCE_AUDIT.md`](docs/security/GOVERNANCE_AUDIT.md) — regressions in `tests/unit/test_privacy.py`.
- Enterprise readiness & observability: [`docs/operations/ENTERPRISE_READINESS.md`](docs/operations/ENTERPRISE_READINESS.md) — regressions in `tests/unit/test_observability.py` and `tests/unit/test_enterprise.py`.
- Senior code review (bugs, concurrency, supply chain, CLI, roadmap,
  plus pre-deployment regulated-environment round):
  [`docs/security/STAFF_REVIEW.md`](docs/security/STAFF_REVIEW.md) — regressions in
  `tests/unit/test_staff_review.py` and
  `tests/unit/test_staff_review_round2.py`.

All six test files must be green before a release:
`test_security.py`, `test_privacy.py`, `test_observability.py`,
`test_enterprise.py`, `test_staff_review.py`, and
`test_staff_review_round2.py`.
