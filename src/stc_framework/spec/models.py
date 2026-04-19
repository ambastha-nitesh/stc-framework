"""Pydantic v2 models for every section of the STC declarative specification.

The goal is to turn the YAML into a typed, validated object at load time so
that downstream code never has to ``dict.get("...")`` with silent defaults.
"""

from __future__ import annotations

from typing import Any, Literal

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
