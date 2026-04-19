# Feature flags

The STC Framework uses LaunchDarkly to gate which v0.3.0 subsystems
initialise at runtime. This page is the operator reference — what
each flag controls, what happens when evaluation falls back, and how
the two-layer gate (Dockerfile extras + LD flag) fits together.

## Two-layer model

1. **Deploy-time gate** — the Dockerfile's `ARG DEPLOYED_SUBSYSTEMS`
   decides which `pyproject.toml` extras are installed into the image.
   A subsystem not in the extras list has no code in the image;
   LaunchDarkly cannot enable it.
2. **Runtime gate** — the Python SDK evaluates feature flags in
   `STCSystem.astart()`. Only subsystems whose flag evaluates to
   `True` have their warmup + route registration performed.

Both gates must agree for a subsystem to actually run. The deploy gate
is the hard boundary; LaunchDarkly is the soft boundary that lets you
kill-switch a deployed subsystem without redeploying.

## Flag catalogue

| FlagKey | LD key | Default | Controls |
|---|---|---|---|
| `COMPLIANCE_ENABLED` | `stc.compliance.enabled` | `false` | FINRA Rule 2210, Reg BI, NYDFS, Part 500, bias, IP risk, etc. — entire `stc_framework.compliance` surface. |
| `THREAT_DETECTION_ENABLED` | `stc.threat_detection.enabled` | `false` | `stc_framework.security.threat_detection.ThreatDetectionManager`. |
| `ORCHESTRATION_ENABLED` | `stc.orchestration.enabled` | `false` | Multi-Stalwart `WorkflowOrchestrator`. |
| `RISK_OPTIMIZER_ENABLED` | `stc.risk_optimizer.enabled` | `false` | Trainer-side `RiskAdjustedOptimizer` veto layer. |
| `CATALOG_ENABLED` | `stc.catalog.enabled` | `false` | `DataCatalog` registrations on the request path. |
| `LINEAGE_ENABLED` | `stc.lineage.enabled` | `false` | `LineageBuilder`/`LineageStore` per-request emission. |
| `TOKENIZATION_STRICT` | `stc.tokenization.strict` | `true` | Runtime companion to the env-var invariant; toggle off during an incident to drop strict mode without a restart. |
| `AUDIT_WORM` | `stc.audit.worm` | `true` | Kill-switch to downgrade the audit backend to JSONL. Use only when WORM is blocking recovery. |
| `DEGRADATION_AUTO_PAUSE` | `stc.degradation.auto_pause` | `true` | When off, `DegradationState` alerts but does not auto-pause traffic. |

## Fallback behaviour

Evaluation order when a call to `LaunchDarklyClient.variation()` fires:

1. If the SDK is initialised and the relay is reachable, return the LD
   decision.
2. If the relay is unreachable but the on-disk cache at
   `$STC_LD_CACHE_PATH` is populated (the SDK refreshes it on every
   successful poll), return the last cached decision.
3. Otherwise, return the hard default from `FLAG_DEFAULTS`.

Every step 2 or 3 fallback increments
`stc_feature_flag_fallback_total{flag}`. A sustained fallback rate
signals a relay outage or a mis-seeded SDK key — don't let it hide
real flag changes.

## Operator tasks

- **List flags + defaults**: `stc-governance flags list`
- **Evaluate a single flag**: `stc-governance flags eval --flag stc.compliance.enabled`
- **Check SDK health**: `stc-governance flags status`
- **Flip a flag** without a deploy: LaunchDarkly dashboard →
  toggle → changes propagate via the relay within ~1s (relay polls LD
  every 30s by default; SDK-to-relay uses SSE streaming).

## Incident playbook — disable a subsystem mid-incident

Example: compliance engine is emitting a storm of false-positive
FINRARuleViolations.

1. LaunchDarkly dashboard → `stc.compliance.enabled` → target rule:
   off for everyone.
2. Watch `stc_compliance_checks_total` fall to zero within seconds.
3. File the incident post-mortem. Patch the engine. Re-enable.

No deploy. No restart. Metrics trail the whole thing so the audit
record is complete.

## Adding a new flag

1. Append a new `FlagKey` member in
   `src/stc_framework/feature_flags/flags.py` + its default in
   `FLAG_DEFAULTS`.
2. Add the gate in the subsystem's warmup (or route registration)
   path, consulting `self._flag_state[FlagKey.NEW_THING]`.
3. Add a unit test in `tests/unit/test_feature_flags.py`.
4. Add the flag in the LaunchDarkly dashboard. Keep the dashboard
   default in sync with `FLAG_DEFAULTS` so a fresh environment starts
   in the intended state.
5. Document the flag in the table above.

Flag keys are structured as `stc.<subsystem>.<aspect>`; sticking to
that convention keeps the dashboard groupings useful.
