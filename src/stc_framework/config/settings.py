"""Runtime settings resolved from environment variables.

All settings use the ``STC_`` prefix. Values are loaded lazily and cached.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class STCSettings(BaseSettings):
    """Environment-driven runtime settings.

    Every field below is overridable via ``STC_<UPPER_NAME>`` (e.g.
    ``STC_LOG_FORMAT=json``).
    """

    model_config = SettingsConfigDict(
        env_prefix="STC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Deployment env --------------------------------------------------
    env: Literal["dev", "staging", "prod"] = Field(default="dev")
    service_name: str = Field(default="stc-framework")
    service_version: str = Field(default="0.2.0")

    # -- Spec ------------------------------------------------------------
    spec_path: str = Field(default="spec-examples/financial_qa.yaml")
    default_tenant: str = Field(default="default")

    # -- Logging ---------------------------------------------------------
    log_level: str = Field(default="INFO")
    log_format: Literal["json", "text"] = Field(default="json")
    log_content: bool = Field(
        default=False,
        description="If true, log request/response content. Off by default to avoid PII leakage.",
    )

    # -- Observability ---------------------------------------------------
    otlp_endpoint: str | None = Field(default=None)
    metrics_port: int = Field(default=9090)
    metrics_enabled: bool = Field(default=True)

    # -- Adapter selection ----------------------------------------------
    llm_adapter: Literal["mock", "litellm"] = Field(default="mock")
    vector_adapter: Literal["in_memory", "qdrant"] = Field(default="in_memory")
    embedding_adapter: Literal["hash", "ollama", "openai"] = Field(default="hash")
    prompt_registry_adapter: Literal["file", "langfuse"] = Field(default="file")
    audit_backend: Literal["jsonl", "parquet", "phoenix", "worm"] = Field(default="jsonl")
    history_store: Literal["memory", "sqlite"] = Field(default="memory")
    escalation_store: Literal["memory", "sqlite"] = Field(default="memory")

    # -- Sentinel --------------------------------------------------------
    presidio_enabled: bool = Field(default=True)
    token_store_path: str = Field(default=".stc/token_store.bin")
    token_store_key_env: str = Field(default="STC_TOKEN_STORE_KEY")

    # -- Resilience defaults ---------------------------------------------
    llm_timeout_sec: float = Field(default=30.0)
    vector_timeout_sec: float = Field(default=5.0)
    embedding_timeout_sec: float = Field(default=10.0)
    guardrail_timeout_sec: float = Field(default=5.0)

    llm_bulkhead: int = Field(default=64)
    vector_bulkhead: int = Field(default=64)
    embedding_bulkhead: int = Field(default=64)
    guardrail_bulkhead: int = Field(default=128)

    llm_retry_max_attempts: int = Field(default=3)
    llm_circuit_fail_max: int = Field(default=5)
    llm_circuit_reset_sec: float = Field(default=30.0)

    # -- Audit -----------------------------------------------------------
    audit_path: str = Field(default=".stc/audit")
    audit_rotate_mb: int = Field(default=64)

    # -- Rate limit ------------------------------------------------------
    tenant_rps: float = Field(
        default=0.0,
        description="Per-tenant requests/sec. 0 disables the limiter.",
    )
    tenant_burst: float = Field(
        default=0.0,
        description="Token-bucket burst capacity. 0 defaults to tenant_rps.",
    )

    # -- History store ---------------------------------------------------
    history_dsn: str = Field(default="sqlite:///.stc/history.db")

    # -- LaunchDarkly (v0.3.1) -------------------------------------------
    # Runtime subsystem gating. ``ld_sdk_key_env`` names the environment
    # variable that holds the actual SDK key — the key is NEVER placed in
    # a config file. ``ld_relay_url`` points at a LaunchDarkly Relay
    # Proxy in the same VPC; ``ld_offline_mode`` forces the SDK to serve
    # only defaults (useful in tests and air-gapped smoke runs).
    ld_sdk_key_env: str = Field(default="LD_SDK_KEY")
    ld_relay_url: str | None = Field(default=None)
    ld_offline_mode: bool = Field(default=False)
    ld_cache_path: str = Field(default="/var/cache/ld/flags.json")
    ld_startup_timeout_sec: float = Field(default=5.0)

    # -- Redis-backed KeyValueStore (v0.3.1) -----------------------------
    # When ``redis_url`` is set, budget/rate-limit/idempotency state moves
    # from in-memory to Redis so multiple replicas share one view.
    # TLS is mandatory when ``STC_ENV=prod`` (scheme must be ``rediss://``).
    redis_url: str | None = Field(default=None)
    redis_tls_ca_path: str | None = Field(default=None)


@lru_cache(maxsize=1)
def get_settings() -> STCSettings:
    """Return the process-wide :class:`STCSettings`, cached."""
    return STCSettings()


def reset_settings_cache() -> None:
    """Clear the cached settings (test hook)."""
    get_settings.cache_clear()
