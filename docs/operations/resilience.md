# Resilience

## Timeouts, retries, bulkheads, circuit breakers

Every external call flows through this pattern:

```
bulkhead.acquire → timeout → circuit.call → retry_with_jitter → adapter
```

**Timeouts** are hard (`asyncio.timeout`) and configured per downstream:

| Setting | Default | Scope |
|---|---|---|
| `STC_LLM_TIMEOUT_SEC` | 30 | Each LLM call |
| `STC_VECTOR_TIMEOUT_SEC` | 5 | Each vector search |
| `STC_EMBEDDING_TIMEOUT_SEC` | 10 | Each embedding call |
| `STC_GUARDRAIL_TIMEOUT_SEC` | 5 | Each rail evaluation |

**Retries** use full-jitter exponential backoff with `base_delay=0.25s`,
`max_delay=8s`. Only errors with `retryable=True` are retried —
`LLMQuotaExceeded` and `LLMContentFiltered` are not.

**Bulkheads** cap concurrent calls per downstream
(`STC_LLM_BULKHEAD`, `STC_VECTOR_BULKHEAD`, ...). Overflow returns
`BulkheadFull` (HTTP 503) so the caller can shed load gracefully.

**Circuit breakers** open after `fail_max` consecutive failures and
reset after `reset_timeout`. State transitions emit OTel events and
update `stc_circuit_breaker_state`.

## Fallback chains

- **LLM routing** — the Sentinel walks `routing_policy[tier]` in order.
  If the primary model times out, rate-limits, or 5xx's, the next is
  tried. `TierRoutingError` is raised only when the list is exhausted.
- **Retrieval** — embedding-based search falls back to keyword search if
  the embedder or vector search errors out or the circuit breaker opens.

## Degradation modes

| Level | Trigger | Effect |
|---|---|---|
| `DEGRADED` | 2 critical guardrail failures in 10 tasks | Responses carry disclaimers |
| `QUARANTINE` | 3 critical in 10 tasks | Responses held for human review |
| `PAUSED` | 5 critical in 10 tasks **or** 3 consecutive failures | `/readyz` returns 503 |

`PAUSED` stays active until the Critic's `circuit_breaker.cooldown_seconds`
elapses with `auto_retry=true`.

## Runbook

1. `stc_circuit_breaker_state{downstream="..."}` stuck at 2 →
   upstream outage. Check the adapter's health, wait for `reset_timeout`.
2. `stc_bulkhead_rejections_total{bulkhead="llm"}` spiking →
   concurrency cap reached. Raise `STC_LLM_BULKHEAD` or scale workers.
3. `stc_escalation_level >= 1` → governance failures. Inspect the
   audit log for rails-failing requests; check if Trainer applied an
   unexpected prompt or routing change.
4. `/readyz` returns 503 → `DegradationState.PAUSED`. Check
   `GET /readyz` JSON body for `reasons`.
