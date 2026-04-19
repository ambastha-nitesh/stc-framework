"""Pydantic v2 models for every section of the STC declarative specification.

The goal is to turn the YAML into a typed, validated object at load time so
that downstream code never has to ``dict.get("...")`` with silent defaults.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Stalwart
# ---------------------------------------------------------------------------


class PermittedTool(BaseModel):
    name: str
    description: str = ""
    risk_tier: Literal["public", "internal", "restricted"] = "public"


class StalwartMemory(BaseModel):
    type: Literal["conversation", "stateless"] = "conversation"
    max_turns: int = 20
    persistence: Literal["session_only", "persistent"] = "session_only"


class PersonaAuth(BaseModel):
    key_scope: str
    permissions: list[str] = Field(default_factory=list)


class StalwartSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    framework: str = "langgraph"
    workflow: str | None = None
    permitted_tools: list[PermittedTool] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    memory: StalwartMemory = Field(default_factory=StalwartMemory)
    auth: PersonaAuth = Field(default_factory=lambda: PersonaAuth(key_scope="stalwart-exec"))


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------


class RewardSignalSpec(BaseModel):
    name: str
    type: Literal["explicit", "automated"]
    weight: float = Field(ge=0.0)
    description: str = ""


class OptimizationLoopSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    frequency: Literal["daily", "weekly", "monthly", "hourly", "manual"]
    targets: list[str] = Field(default_factory=list)
    metric: str
    engine: str | None = None


class OptimizationSpec(BaseModel):
    engine: str = "agent_lightning"
    algorithm: str = "grpo"
    reward_signals: list[RewardSignalSpec] = Field(default_factory=list)
    optimization_loops: list[OptimizationLoopSpec] = Field(default_factory=list)


class CostThresholds(BaseModel):
    max_per_task_usd: float = 0.10
    daily_budget_usd: float = 100.0
    monthly_budget_usd: float = 2000.0
    alert_at_percent: float = 80


class MaintenanceTriggers(BaseModel):
    accuracy_below: float = 0.85
    cost_above_per_task_usd: float = 0.10
    hallucination_rate_above: float = 0.05
    latency_p95_above_ms: float = 5000


class MaintenanceMode(BaseModel):
    action: Literal["degrade", "pause", "alert_only"] = "alert_only"
    notification: list[str] = Field(default_factory=list)


class TrainerSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    optimization: OptimizationSpec = Field(default_factory=OptimizationSpec)
    cost_thresholds: CostThresholds = Field(default_factory=CostThresholds)
    maintenance_triggers: MaintenanceTriggers = Field(default_factory=MaintenanceTriggers)
    maintenance_mode: MaintenanceMode = Field(default_factory=MaintenanceMode)
    auth: PersonaAuth = Field(default_factory=lambda: PersonaAuth(key_scope="trainer-control"))


# ---------------------------------------------------------------------------
# Critic
# ---------------------------------------------------------------------------


class GuardrailRailSpec(BaseModel):
    """A single rail entry under ``critic.guardrails.{input,output}_rails``.

    ``extra = "allow"`` so rail-specific fields (``tolerance_percent``,
    ``prohibited_topics`` etc.) are preserved without forcing the schema to
    enumerate them.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    engine: str = "custom"
    action: Literal["block", "warn", "redact", "escalate"] = "warn"
    severity: Literal["critical", "high", "medium", "low"] = "medium"
    validator: str | None = None
    threshold: float | None = None
    entities: list[str] = Field(default_factory=list)
    prohibited_topics: list[str] = Field(default_factory=list)
    allowed_topics: list[str] = Field(default_factory=list)
    tolerance_percent: float | None = None
    model: str | None = None
    description: str = ""


class GuardrailsBlock(BaseModel):
    orchestrator: str = "nemo_guardrails"
    input_rails: list[GuardrailRailSpec] = Field(default_factory=list)
    output_rails: list[GuardrailRailSpec] = Field(default_factory=list)


class EscalationLevelSpec(BaseModel):
    trigger: str = ""
    action: str = ""


class CircuitBreakerSpec(BaseModel):
    trigger: str = "3 consecutive failures"
    cooldown_seconds: int = 300
    auto_retry: bool = True


class EscalationSpec(BaseModel):
    degraded_mode: EscalationLevelSpec = Field(default_factory=EscalationLevelSpec)
    quarantine_mode: EscalationLevelSpec = Field(default_factory=EscalationLevelSpec)
    suspension: EscalationLevelSpec = Field(default_factory=EscalationLevelSpec)
    circuit_breaker: CircuitBreakerSpec = Field(default_factory=CircuitBreakerSpec)


class CriticSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    guardrails: GuardrailsBlock = Field(default_factory=GuardrailsBlock)
    escalation: EscalationSpec = Field(default_factory=EscalationSpec)
    auth: PersonaAuth = Field(default_factory=lambda: PersonaAuth(key_scope="critic-governance"))


# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------


class GatewayConfig(BaseModel):
    engine: str = "litellm"
    host: str = "http://localhost:4000"


class CustomRecognizer(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    regex: str | None = None
    keywords: list[str] = Field(default_factory=list)
    context_words: list[str] = Field(default_factory=list)
    tier: Literal["public", "internal", "restricted"] = "internal"


class PIIRedactionConfig(BaseModel):
    engine: str = "presidio"
    mode: Literal["pre_call", "during_call", "post_call"] = "during_call"
    entities_config: dict[str, Literal["MASK", "BLOCK", "ALLOW"]] = Field(default_factory=dict)
    custom_recognizers: list[CustomRecognizer] = Field(default_factory=list)


class TokenizationConfig(BaseModel):
    enabled: bool = False
    strategy: Literal["surrogate"] = "surrogate"
    reversible: bool = True
    token_map_storage: Literal["local_encrypted", "memory"] = "local_encrypted"


class SentinelAuthConfig(BaseModel):
    virtual_keys: bool = True
    key_rotation_days: int = 90
    persona_keys: dict[str, str] = Field(default_factory=dict)


class SentinelSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    pii_redaction: PIIRedactionConfig = Field(default_factory=PIIRedactionConfig)
    tokenization: TokenizationConfig = Field(default_factory=TokenizationConfig)
    auth: SentinelAuthConfig = Field(default_factory=SentinelAuthConfig)
    trusted_agents: list[str] = Field(default_factory=list)
    mcp_access_policy: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Data sovereignty
# ---------------------------------------------------------------------------


class EmbeddingModelConfig(BaseModel):
    provider: Literal["local", "openai", "bedrock", "mock"] = "local"
    model: str = "bge-large-en-v1.5"
    endpoint: str = "http://localhost:11434"


class CollectionPolicy(BaseModel):
    tier: Literal["public", "internal", "restricted"] = "internal"
    ttl_days: int = 365


class VectorStoreConfig(BaseModel):
    provider: str = "qdrant"
    location: Literal["local", "cloud"] = "local"
    host: str = "http://localhost:6333"
    collection_policies: dict[str, CollectionPolicy] = Field(default_factory=dict)


class ClassificationConfig(BaseModel):
    engines: list[str] = Field(default_factory=lambda: ["presidio", "custom_patterns"])
    custom_patterns: list[CustomRecognizer] = Field(default_factory=list)


class BoundaryAuditConfig(BaseModel):
    log_all_crossings: bool = True
    alert_on_tier_violation: bool = True


class DataSovereigntySpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    default_routing: Literal["vpc_only", "cloud_ok", "local_only"] = "vpc_only"
    embedding_model: EmbeddingModelConfig = Field(default_factory=EmbeddingModelConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    classification: ClassificationConfig = Field(default_factory=ClassificationConfig)
    routing_policy: dict[str, list[str]] = Field(default_factory=dict)
    boundary_audit: BoundaryAuditConfig = Field(default_factory=BoundaryAuditConfig)

    @field_validator("routing_policy")
    @classmethod
    def _validate_routing_tiers(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        required = {"public", "internal", "restricted"}
        missing = required - set(v.keys())
        if missing:
            raise ValueError(f"routing_policy missing required tiers: {sorted(missing)}")
        for tier, models in v.items():
            if not models:
                raise ValueError(f"routing_policy[{tier}] must list at least one model")

        # Data-sovereignty invariant: restricted-tier data MUST only be
        # routed to local / VPC-bound models. Any cloud provider prefix in
        # the restricted list is a critical misconfiguration.
        from stc_framework.spec.routing_guard import (  # local import to avoid cycle
            is_local_model,
        )

        bad = [m for m in v["restricted"] if not is_local_model(m)]
        if bad:
            raise ValueError(
                "routing_policy.restricted must only contain local/VPC models; " f"found external targets: {bad}"
            )
        return v


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class PromptRegistryConfig(BaseModel):
    engine: str = "langfuse"
    host: str = "http://localhost:3000"
    link_prompts_to_traces: bool = True


class AuditExportConfig(BaseModel):
    enabled: bool = True
    destination: str = "local://audit-logs/"
    format: Literal["parquet", "jsonl"] = "parquet"
    schedule: Literal["hourly", "daily", "weekly"] = "daily"


class TraceEnrichment(BaseModel):
    include_spec_version: bool = True
    include_prompt_version: bool = True
    include_model_id: bool = True
    include_cost: bool = True
    include_data_tier: bool = True


class RetentionPolicy(BaseModel):
    """Per-event-class retention windows in days.

    ``default`` applies to any event type not explicitly listed.
    Entries set to ``-1`` are kept forever. Regulated record classes
    (erasure receipts, boundary crossings, escalation transitions)
    default to a generous minimum so a naive ``retention_days``
    override cannot accidentally delete compliance evidence.
    """

    model_config = ConfigDict(extra="allow")

    default: int = 365
    erasure: int = 2190  # 6 years — GDPR compliance evidence
    dsar_export: int = 2190
    retention_sweep: int = 2190
    boundary_crossing: int = 2190
    data_sovereignty_violation: int = 2190
    escalation_transition: int = 2190
    system_start: int = 730
    system_stop: int = 730
    audit_rotation_seal: int = -1  # forever — chain glue
    retention_prune_seal: int = -1  # forever — chain glue

    def days_for(self, event_type: str) -> int:
        return int(getattr(self, event_type, self.default))


class AuditSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    trace_backend: str = "arize_phoenix"
    phoenix_host: str = "http://localhost:6006"
    prompt_registry: PromptRegistryConfig = Field(default_factory=PromptRegistryConfig)
    retention_days: int = 365  # legacy single-value fallback
    retention_policies: RetentionPolicy = Field(default_factory=RetentionPolicy)
    export: AuditExportConfig = Field(default_factory=AuditExportConfig)
    immutable: bool = True
    trace_enrichment: TraceEnrichment = Field(default_factory=TraceEnrichment)


# ---------------------------------------------------------------------------
# v0.3.0 — Compliance profile
# ---------------------------------------------------------------------------


class PrincipalApprovalConfig(BaseModel):
    enabled: bool = False
    queue_backend: Literal["memory", "store"] = "store"
    auto_approve_below_severity: Literal["critical", "high", "medium", "low"] = "low"
    sla_hours: int = 24


class ComplianceRuleSpec(BaseModel):
    """A single compliance rule's activation state + thresholds."""

    model_config = ConfigDict(extra="allow")

    name: str
    enabled: bool = True
    severity: Literal["critical", "high", "medium", "low"] = "high"
    threshold: float | None = None
    patterns_file: str | None = None


class CompliancePolicySpec(BaseModel):
    """Top-level compliance configuration.

    References the rule catalog. Individual engines read their
    entry via ``rule_by_name``.
    """

    model_config = ConfigDict(extra="allow")

    rules: list[ComplianceRuleSpec] = Field(default_factory=list)
    principal_approval: PrincipalApprovalConfig = Field(default_factory=PrincipalApprovalConfig)
    legal_hold_enabled: bool = True
    consent_required_for_tiers: list[str] = Field(default_factory=lambda: ["restricted"])

    def rule_by_name(self, name: str) -> ComplianceRuleSpec | None:
        return next((r for r in self.rules if r.name == name), None)


# ---------------------------------------------------------------------------
# v0.3.0 — Sovereignty
# ---------------------------------------------------------------------------


class StateLawProfile(BaseModel):
    state: str
    law_name: str
    effective_date: str = ""
    key_requirements: list[str] = Field(default_factory=list)


class SovereigntySpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    allowed_origin_risks: list[Literal["trusted", "cautious", "restricted", "sanctioned"]] = Field(
        default_factory=lambda: cast(
            list[Literal["trusted", "cautious", "restricted", "sanctioned"]],
            ["trusted", "cautious"],
        )
    )
    require_fips_for_restricted: bool = True
    allowed_inference_jurisdictions: list[str] = Field(default_factory=lambda: ["US"])
    state_profiles: list[StateLawProfile] = Field(default_factory=list)
    model_origins_file: str | None = None


# ---------------------------------------------------------------------------
# v0.3.0 — Risk appetite
# ---------------------------------------------------------------------------


class KRIDefinitionSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    kri_id: str
    name: str
    direction: Literal["higher_is_worse", "lower_is_worse"] = "higher_is_worse"
    amber_threshold: float
    red_threshold: float
    linked_risks: list[str] = Field(default_factory=list)


class RiskAppetiteSpec(BaseModel):
    """Five-by-five rating thresholds plus per-decision weighting."""

    model_config = ConfigDict(extra="allow")

    max_acceptable_rating: Literal["low", "medium", "high", "critical"] = "high"
    decision_weights: dict[str, float] = Field(default_factory=lambda: {"accuracy": 0.4, "cost": 0.2, "risk": 0.4})
    kris: list[KRIDefinitionSpec] = Field(default_factory=list)
    veto_on_kri_red: bool = True
    max_vendor_share: float = 0.75  # single vendor at most 75% of traffic


# ---------------------------------------------------------------------------
# v0.3.0 — Orchestration
# ---------------------------------------------------------------------------


class StalwartRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    stalwart_id: str
    type_name: str = "generic"
    capabilities: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    model_id: str | None = None
    prompt_template: str | None = None
    cost_weight: float = 1.0


class OrchestrationSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    stalwart_registry: list[StalwartRegistryEntry] = Field(default_factory=list)
    max_workflow_cost_usd: float = 5.00
    max_tasks_per_workflow: int = 20
    checkpointing: bool = True
    langgraph_required: bool = False


# ---------------------------------------------------------------------------
# v0.3.0 — Threat detection
# ---------------------------------------------------------------------------


class RateLimitSpec(BaseModel):
    per_minute: int = 60
    per_hour: int = 1000
    cost_exhaustion_usd_per_minute: float = 5.0


class BehavioralThresholdsSpec(BaseModel):
    firewall_block_rate_red: float = 0.5
    critic_failure_rate_red: float = 0.3
    session_query_count_extraction: int = 30


class DeceptionSpec(BaseModel):
    honey_docs: list[str] = Field(default_factory=list)
    honey_tokens: list[str] = Field(default_factory=list)
    canary_queries: list[str] = Field(default_factory=list)


class ThreatDetectionSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    rate_limits: RateLimitSpec = Field(default_factory=RateLimitSpec)
    behavioral: BehavioralThresholdsSpec = Field(default_factory=BehavioralThresholdsSpec)
    deception: DeceptionSpec = Field(default_factory=DeceptionSpec)
    ip_block_duration_seconds: int = 900


# ---------------------------------------------------------------------------
# v0.3.0 — Session state
# ---------------------------------------------------------------------------


class SessionStateSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    backend: Literal["memory", "redis"] = "memory"
    redis_url: str | None = None
    default_ttl_seconds: int = 3600
    key_namespace: str = "session"


# ---------------------------------------------------------------------------
# v0.3.0 — Performance SLOs
# ---------------------------------------------------------------------------


class SLOSpec(BaseModel):
    name: str
    sli_description: str = ""
    target: float
    unit: str = "ms"
    measurement: str = "p95"
    error_budget_period_days: int = 30


class LoadProfileSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: Literal["baseline", "peak", "stress", "soak"] = "baseline"
    rps: float = 10.0
    duration_seconds: int = 60
    ramp_seconds: int = 10


class PerfSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    slos: list[SLOSpec] = Field(default_factory=list)
    load_profiles: list[LoadProfileSpec] = Field(default_factory=list)
    regression_threshold_percent: float = 10.0


# ---------------------------------------------------------------------------
# Top-level spec
# ---------------------------------------------------------------------------


class STCSpec(BaseModel):
    """Fully parsed STC declarative specification."""

    model_config = ConfigDict(extra="allow")

    version: str
    name: str
    description: str = ""
    created: str | None = None
    author: str | None = None

    stalwart: StalwartSpec = Field(default_factory=StalwartSpec)
    trainer: TrainerSpec = Field(default_factory=TrainerSpec)
    critic: CriticSpec = Field(default_factory=CriticSpec)
    sentinel: SentinelSpec = Field(default_factory=SentinelSpec)
    data_sovereignty: DataSovereigntySpec = Field(default_factory=DataSovereigntySpec)
    audit: AuditSpec = Field(default_factory=AuditSpec)
    risk_taxonomy: dict[str, Any] = Field(default_factory=dict)
    compliance: dict[str, Any] = Field(default_factory=dict)

    # v0.3.0 optional sections — each one is disabled until populated.
    compliance_profile: CompliancePolicySpec = Field(default_factory=CompliancePolicySpec)
    sovereignty: SovereigntySpec = Field(default_factory=SovereigntySpec)
    risk_appetite: RiskAppetiteSpec = Field(default_factory=RiskAppetiteSpec)
    orchestration: OrchestrationSpec = Field(default_factory=OrchestrationSpec)
    threat_detection: ThreatDetectionSpec = Field(default_factory=ThreatDetectionSpec)
    session_state: SessionStateSpec = Field(default_factory=SessionStateSpec)
    perf: PerfSpec = Field(default_factory=PerfSpec)

    # -- Convenience helpers used across the codebase ---------------------

    def routing_for(self, data_tier: str) -> list[str]:
        """Return the ordered model list for a tier, falling back to public."""
        policy = self.data_sovereignty.routing_policy
        return list(policy.get(data_tier, policy.get("public", [])))

    def output_rails(self) -> list[GuardrailRailSpec]:
        return list(self.critic.guardrails.output_rails)

    def input_rails(self) -> list[GuardrailRailSpec]:
        return list(self.critic.guardrails.input_rails)

    def rail_by_name(self, name: str) -> GuardrailRailSpec | None:
        # Cached lookup — rails are fixed for the lifetime of a spec,
        # and this is on the hot path of every Critic evaluation. Build
        # the index lazily on first call, invalidation is via spec
        # reload (which creates a new STCSpec anyway).
        index = getattr(self, "_rail_index", None)
        if index is None:
            index = {
                rail.name: rail for rail in self.critic.guardrails.input_rails + self.critic.guardrails.output_rails
            }
            object.__setattr__(self, "_rail_index", index)
        return index.get(name)
