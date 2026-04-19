# Redis operations

`stc_framework.infrastructure.redis_store.RedisStore` backs the
multi-replica budget tracker, rate limiter, idempotency cache, and
session manager. This page is the ops reference — sizing,
failover drills, and the one operational detail everyone gets wrong
(segment-exact `erase_tenant`).

## When Redis is in use

A deployment uses Redis when `STCSettings.redis_url` is populated.
The default `STC_REDIS_URL` env var is empty, which makes `STCSystem`
fall back to the in-memory `InMemoryStore`. ECS task definitions for
staging/prod populate it from Secrets Manager; dev leaves it empty.

## Sizing

| Tier | Node type | Replicas | Throughput ceiling |
|---|---|---|---|
| dev | `cache.t4g.small` | 0 | ~20k ops/s; no HA |
| staging | `cache.t4g.medium` | 1 | ~50k ops/s; multi-AZ |
| prod | `cache.r7g.large` | 2 | ~200k ops/s; multi-AZ |

Budget/rate-limit/idempotency each issue roughly 3-5 Redis ops per
API request. An instance sized for the throughput of the ECS service
is almost always over-provisioned for Redis — scale on sustained CPU
at 70% rather than raw ops.

## Connection string format

```
rediss://:<auth_token>@<primary_endpoint>:6379/0
```

`rediss://` (TLS) is mandatory in staging and prod; `RedisStore.from_url`
refuses `redis://` when `require_tls=True`. The auth token lives in
Secrets Manager as `<name_prefix>-redis_auth_token`; the full URL
lives in `<name_prefix>-redis_url` (composed post-`apply` per the
deployment runbook).

## Key-scheme contract

`KeyValueStore` callers store keys with colon-delimited segments:

```
budget:<tenant_id>:<day>       → integer micro-dollars
rate:<tenant_id>:<minute>      → integer request count
idemp:<tenant_id>:<idemp_key>  → JSON result envelope
session:<session_id>:context   → JSON conversation state
session:<session_id>:tokens    → base64 encrypted blob
```

**`erase_tenant` matches segments EXACTLY, not as substrings.**
`erase_tenant("t")` will NOT delete keys for `t1`. This was the
v0.3.0 staff-review R1 finding; the regression test lives in
`tests/unit/test_redis_store_unit.py::test_erase_tenant_segment_exact_match`.
Violating the key scheme (e.g. embedding tenant id as a substring of
another segment) breaks this guarantee.

## Monitoring

Key CloudWatch metrics (all `AWS/ElastiCache`, per
`ReplicationGroupId`):

- `EngineCPUUtilization` — alarm at 75% for 10 min (Terraform already
  provisions this).
- `DatabaseMemoryUsagePercentage` — alarm at 85%.
- `Evictions` — any non-zero rate indicates memory pressure.
- `NewConnections` — spikes correlate with ECS rollouts.
- `ReplicationLag` — alarm at > 5s for prod HA.

## Failover drill

ElastiCache promotes a replica automatically on primary failure. The
STC service reconnects on the next Redis op (redis-py retries on
`ConnectionError` and `TimeoutError`). Drill it:

```bash
aws elasticache test-failover \
  --replication-group-id stc-framework-prod-redis \
  --node-group-id 0001
```

Expect ~15-30s of elevated `stc_rate_limit_exceeded_total` errors as
the in-flight client connections reconnect. Budget/rate counters do
not reset — the data is replicated before the failover completes.

## Tenant erasure under Redis

DSAR/right-to-erasure calls `STCSystem.aerase_tenant` which in turn
calls `RedisStore.erase_tenant(tenant_id, key_prefix="")`. Under the
hood that's a `SCAN`-and-batch-`DEL`:

- Time: ~500 keys per batch; a tenant with 50k records completes in
  < 5s.
- Blast radius: limited to keys where the tenant id appears as an
  exact colon-delimited segment. No substring matching, no prefix
  matching.
- Atomicity: not all-or-nothing. A crash mid-sweep leaves some keys
  deleted and some present. Callers should loop on
  `erase_tenant` until it returns 0 to confirm idempotent cleanup.

## Recovery

If the cluster is lost entirely:

1. Terraform `apply` re-creates it in ~10 minutes.
2. Budget/rate counters start at zero — this is intentional and safe;
   no tenant will be over-billed, some may briefly under-rate-limit.
3. Idempotency cache starts empty; in-flight retries will re-execute.
   Bound this window by setting a short cache TTL (default 24h).
4. Session state is lost — callers should treat sessions as
   invalidated. The `SessionExpired` error is already surfaced by
   `SessionManager.assert_active`.
