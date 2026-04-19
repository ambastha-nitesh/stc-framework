# Architecture

The STC Framework separates three concerns into first-class system roles:

- **Stalwart** — execution plane, performs the business task.
- **Trainer** — optimization plane, makes the Stalwart better over time.
- **Critic** — zero-trust governance plane, verifies every output.

Two supporting layers exist as infrastructure, **not** agents:

- **Sentinel Layer** — trust boundaries, data classification, PII redaction,
  tokenization, routing, authentication.
- **Declarative Specification** — versioned YAML contract parsed into
  pydantic models at load time.

## Runtime topology

```
              ┌──────────────────────────────────────────────┐
              │                STCSystem                     │
              │  ┌────────────┐ ┌──────────┐ ┌─────────────┐ │
  query ─────▶│  │  Stalwart  │→│ Sentinel │→│  LLM client │ │──▶ Provider
              │  └────────────┘ │ gateway  │ └─────────────┘ │
              │        │        └──────────┘         ▲       │
              │        ▼                             │       │
              │  ┌──────────┐      trace      ┌──────┴─────┐ │
              │  │  Critic  │ ◀────────────── │  Trainer   │ │
              │  └──────────┘                 └────────────┘ │
              └──────────────────────────────────────────────┘
                          │         │
                          ▼         ▼
                   Audit log   Prometheus
```

## Async-first with bulkheads

Every external call (LLM, vector store, embeddings, guardrails) is:

1. Wrapped in a per-downstream **bulkhead** (`asyncio.Semaphore`) so one
   slow dependency cannot consume the whole event loop.
2. Guarded by an async **circuit breaker** that opens after repeated
   failures and half-opens after `reset_timeout`.
3. Retried with **full-jitter exponential backoff** — and only for
   errors flagged as `retryable` in the typed error taxonomy.
4. Given a hard **timeout** (`asyncio.timeout`).
5. Offered a **fallback chain** — cloud LLM → local LLM, vector store →
   keyword search, embedding → hash embedder.

## Degradation state machine

```
    NORMAL ──(2 critical in window)──▶ DEGRADED
       ▲                                   │
       │                            (3 critical)
       │                                   ▼
    (cooldown elapsed)                QUARANTINE
       │                                   │
       │                            (5 critical / 3 consecutive)
       │                                   ▼
       └──────────────────── PAUSED ◀──────┘
```

Transitions are driven by the Critic's escalation manager and the
Trainer's maintenance triggers. `/readyz` reports the current level.

## Where everything lives

| Concern | Module |
|---|---|
| Typed errors | `stc_framework.errors` |
| Settings & structured logging | `stc_framework.config` |
| Tracing, metrics, audit, correlation | `stc_framework.observability` |
| Retries, circuit breakers, timeouts, bulkheads, fallbacks | `stc_framework.resilience` |
| Spec models & loader | `stc_framework.spec` |
| LLM / vector / embedding / prompt / guardrail adapters | `stc_framework.adapters` |
| Classifier, redactor, tokenizer, gateway, auth | `stc_framework.sentinel` |
| Validators, rails, escalation, Critic | `stc_framework.critic` |
| Reward, optimizer, routing, prompt controllers, Trainer | `stc_framework.trainer` |
| Generic Stalwart agent | `stc_framework.stalwart` |
| Financial Q&A reference | `stc_framework.reference_impl.financial_qa` |
| Optional Flask service | `stc_framework.service` |
| Adversarial suite | `stc_framework.adversarial` |
