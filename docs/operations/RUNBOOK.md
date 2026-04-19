# Production Runbook

What this service does in prod, what alerts fire, what each alert
means, and the first three things to check when it pages.

## What the service does

- Accepts a natural-language query + tenant id at `POST /v1/query`.
- Runs an input-rail / Stalwart / output-rail pipeline.
- Returns a governed, cited response.
- Writes an HMAC-chained audit record for every meaningful event.
- Exposes `/healthz`, `/readyz`, `/metrics`, `/v1/spec`, `/v1/feedback`.

## Deploy

See `docs/operations/deployment.md` for worker sizing.

In regulated environments:

1. `STC_ENV=prod` — mandatory.
2. `STC_AUDIT_HMAC_KEY` — mandatory, 32+ bytes base64-urlsafe.
3. `STC_SPEC_PUBLIC_KEY` — mandatory.
4. `STC_TOKENIZATION_STRICT=1` — mandatory.
5. `STC_TOKENIZATION_KEY` — mandatory (per-deployment HMAC key).
6. `STC_TOKEN_STORE_KEY` — mandatory (32-byte AES-GCM key for
   the encrypted token store).
7. `STC_AUDIT_BACKEND=worm` — mandatory (WORM audit backend).
8. `STC_LOG_CONTENT=false` — mandatory (enforced; setting it `true`
   in prod is rejected at startup).
9. A signed `spec.yaml.sig` sidecar file must exist alongside the
   spec and verify against `STC_SPEC_PUBLIC_KEY`.
10. `terminationGracePeriodSeconds: 60` or higher.

Any missing variable causes `STCSystem.astart()` to raise `STCError`
and the Kubernetes `startupProbe` to fail. This is the point.

## Rollback

All rollbacks are image-level. There is no live-migration of:

- the audit log (chain is append-only),
- the spec (old processes can't verify new signatures),
- the prompt registry (versions are additive, not mutative).

Steps:

1. Roll the image back.
2. Verify `/readyz` returns 200 on the new pods.
3. Verify `stc_adapter_healthcheck{adapter="..."} == 1` for all four
   adapters.
4. Run `stc-governance verify-chain /mnt/audit` on a sample node to
   confirm chain integrity.

## Alerts

### Critical (page immediately)

| Alert | Meaning | First 3 checks |
|---|---|---|
| `stc_circuit_breaker_state{downstream=*} == 2 for 1m` | An upstream (LLM, vector, embedding) has tripped open. Traffic for that adapter is short-circuited. | `/readyz` → which adapter is `ok: false` → provider status page → recent deploys |
| `stc_escalation_level >= 3` | Critic has paused traffic. Every new query returns 503. | Audit `rail_failed` events for the last 10 minutes; look for a spike in one rail (likely a bad prompt rollout or a model change) → roll back last prompt → observe |
| `stc_inflight_requests > bulkhead_limit for 2m` | Saturation. Pod can't drain; eventual timeouts will cascade. | Check event-loop wedge: `py-spy dump` on the pod → are we stuck in a validator? → is Presidio loaded? → consider restart |
| Audit chain verification failed | Someone tampered (or retention broke) | Isolate node; run `stc-governance verify-chain --strict` vs `--accept-unknown-genesis`; if strict-only fails after recent prune, it's OK; if accept-unknown fails too, escalate to security on-call |
| Spec signature mismatch at startup | Tampered or corrupted spec | Do NOT start. Check image SHA vs expected; check `spec.yaml.sig` sidecar is present; check `STC_SPEC_PUBLIC_KEY` is the right deployment's key |

### Warning (notify within 15 min)

| Alert | Meaning | First 3 checks |
|---|---|---|
| `stc_queries_total{action="block_input"} / stc_queries_total > 5%` | Injection-like traffic spike | Is a tenant under attack? Is there a recent rail rule that's too aggressive? Check `rail_failed` details |
| `stc_tenant_budget_rejections_total > 0` on a tenant | Budget exhausted | Is the cost reasonable? Runaway client loop? `stc_cost_usd_total{tenant=...}` trend |
| `stc_bulkhead_rejections_total > 0` | Concurrency cap hit | Raise `STC_LLM_BULKHEAD` or scale out |
| p95 latency > 2s | SLO risk | Drill into `stc_stage_latency_ms{stage=...}` to isolate which stage |
| Presidio cold-start warnings in logs | First query per process pays 1s penalty | Confirm `_warm_adapters()` runs on startup; if consistently slow, pre-load a larger dictionary at image build time |

### Informational

| Alert | Meaning | Action |
|---|---|---|
| `stc_escalation_level == 1` (DEGRADED) | Two critical rail failures in last 10 | Review latest failures in audit; often resolves automatically on the next good response |
| `stc_redaction_events_total{entity_type="US_SSN"} > 0` | SSN redacted in a query | Normal; alerts auditors that the protection fired |
| `stc_boundary_crossings_total` rate change | More/less internal-tier traffic than baseline | Tenancy drift; review |

## What to do on each escalation level

### DEGRADED

- Responses continue but carry a disclaimer.
- Confirm via `stc_escalation_level == 1` and `/readyz` body's
  `degradation_level`.
- Action: none automatic. Audit `rail_failed` events; if a pattern
  (same rail, same tenant) emerges, investigate.

### QUARANTINE

- Responses are held; client sees "under review".
- Action: human review. On-call reviews the held traces (pulled from
  audit with `action=escalate`). Approves/rejects manually while the
  underlying issue is root-caused.

### PAUSED

- `/readyz` returns 503. Kubernetes evicts the pod.
- Action: do not force re-enable. Let the Critic's cooldown
  (`circuit_breaker.cooldown_seconds` in the spec, default 300s)
  expire. If the failures persist, the cause is structural — roll back
  to last known good.

## Incident response: suspected audit tampering

1. **Stop writes** — scale the deployment to 0.
2. **Snapshot** — copy the entire audit directory to a forensic store
   (keep the `.worm-marker` file).
3. **Verify strict** — `stc-governance verify-chain /path/to/audit`.
   Note the first failing record.
4. **Diff against replica** — if the audit is replicated (S3 Object
   Lock, Immudb), compare the divergent record on both sides.
5. **Rotate keys** — generate a new `STC_AUDIT_HMAC_KEY`, redeploy.
   Old records remain verifiable under their original `key_id`.
6. **Fire the disclosure** — SOX 404, NYDFS Part 500 §500.17, and the
   tenant-facing DPA may require notification within hours.

## Incident response: data subject access / erasure request

1. `stc-governance dsar <tenant_id> --output /tmp/dsar.json` — runs
   `aexport_tenant`, emits a `dsar_export` audit record.
2. Review the output, then hand to the data-subject (CCPA / GDPR
   Art. 15 deadlines apply — 30 days).
3. For erasure: `stc-governance erase <tenant_id> --yes` — requires
   the flag so no one runs it by mistake. Emits an `erasure` receipt
   under `tenant_id=None` so a second call doesn't delete the receipt.
4. If the audit backend is WORM, erasure is a *tombstone* — the
   receipt remains, the regulated record is not physically deleted.
   GDPR-Art. 17 compliance for WORM-regulated customers requires a
   contractual addendum (we disclose the SEC 17a-4 conflict up front).

## Capacity planning shorthand

- 1 gunicorn worker with 16 threads supports ~100 req/sec on a 2-vCPU
  node with `STC_LLM_BULKHEAD=64` (assumes ~500ms LLM tails). Validate
  on your infra.
- Audit writes are ~500 µs each (JSONL, local SSD). The WORM backend
  adds `fsync` per write (~5ms on a good SSD). Plan accordingly.
- Presidio's first `redact` call takes ~1s (spaCy load). We warm it
  at startup but plan for the first customer request to still be
  slower than p50.

## Things that look like incidents but aren't

- **Chain "breaks" after retention**: expected after any `prune_before`.
  Use `verify_chain(..., accept_unknown_genesis=True)` for day-to-day;
  strict is for full compliance audits.
- **Ephemeral-key warning at startup in dev**: expected when
  `STC_AUDIT_HMAC_KEY` is unset. Prod refuses to start under this
  condition, so seeing it in prod is an alert.
- **`stc_queries_total{action="block_input"}` spikes briefly**: often a
  test suite run, a scanner, or a bot. Check the `tenant` label
  before escalating.

## Contacts

- On-call: your pager rotation of choice.
- Security response: the address in `SECURITY.md`.
- Compliance liaison: the person whose name is on the last AIUC-1
  certificate.

Keep this runbook checked into the repo, not in a wiki that goes
stale. Any new alert added to the Prometheus rules should come with
an entry here in the same PR.
