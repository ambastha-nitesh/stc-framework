"""Tests for the AI Hub per-agent allowlist + model catalogue (FR-1/10)."""

from __future__ import annotations

import pytest

from stc_framework.ai_hub.allowlist import (
    DEFAULT_AGENT_ALLOWLIST,
    AgentAllowlist,
    AgentContext,
    ModelAllowlistError,
    ModelTier,
    default_catalog,
)
from stc_framework.ai_hub.errors import AIHubError, AIHubErrorCode


def test_mvp_catalog_contains_expected_models() -> None:
    cat = default_catalog()
    assert set(cat.keys()) == {
        "claude-haiku-4-5",
        "claude-sonnet-4-6",
        "claude-opus-4-7",
        "titan-embed-text-v2",
    }
    assert cat["claude-opus-4-7"].tier is ModelTier.RESTRICTED
    assert cat["claude-haiku-4-5"].tier is ModelTier.STANDARD
    # PRD §4.1.10 — 200k context for Claude family.
    assert cat["claude-sonnet-4-6"].context_window_tokens == 200_000


def test_default_agent_allowlist_is_exactly_claude_haiku() -> None:
    # PRD AC-10.1 pins this to one model.
    assert DEFAULT_AGENT_ALLOWLIST == ("claude-haiku-4-5",)


def test_register_agent_gets_default_allowlist() -> None:
    al = AgentAllowlist()
    al.register_agent("agent-1")
    assert al.for_agent("agent-1") == ["claude-haiku-4-5"]


def test_add_model_to_allowlist() -> None:
    al = AgentAllowlist()
    al.register_agent("agent-1")
    al.add_model("agent-1", "claude-sonnet-4-6")
    assert al.for_agent("agent-1") == ["claude-haiku-4-5", "claude-sonnet-4-6"]


def test_add_unknown_model_raises() -> None:
    al = AgentAllowlist()
    al.register_agent("agent-1")
    with pytest.raises(ModelAllowlistError):
        al.add_model("agent-1", "mistery-model")


def test_add_model_to_unknown_agent_raises() -> None:
    al = AgentAllowlist()
    with pytest.raises(ModelAllowlistError):
        al.add_model("never-registered", "claude-haiku-4-5")


def test_remove_model() -> None:
    al = AgentAllowlist()
    al.register_agent("agent-1")
    al.add_model("agent-1", "claude-sonnet-4-6")
    al.remove_model("agent-1", "claude-haiku-4-5")
    assert al.for_agent("agent-1") == ["claude-sonnet-4-6"]


def test_assert_allowed_success_returns_catalog_entry() -> None:
    al = AgentAllowlist()
    al.register_agent("agent-1")
    entry = al.assert_allowed("agent-1", "claude-haiku-4-5")
    assert entry.bedrock_identifier == "anthropic.claude-haiku-4-5-v1:0"


def test_assert_allowed_unknown_model_returns_invalid_model_id() -> None:
    al = AgentAllowlist()
    al.register_agent("agent-1")
    with pytest.raises(AIHubError) as ei:
        al.assert_allowed("agent-1", "mystery-model")
    assert ei.value.code is AIHubErrorCode.INVALID_MODEL_ID


def test_assert_allowed_known_model_not_in_allowlist_returns_model_not_allowed() -> None:
    al = AgentAllowlist()
    al.register_agent("agent-1")
    # Catalog-valid but not on this agent's allowlist.
    with pytest.raises(AIHubError) as ei:
        al.assert_allowed("agent-1", "claude-sonnet-4-6")
    assert ei.value.code is AIHubErrorCode.MODEL_NOT_ALLOWED


def test_assert_agent_active_rejects_suspended_agent() -> None:
    al = AgentAllowlist()
    ctx = AgentContext(
        agent_id="a",
        domain_id="d",
        domain_state="ACTIVE",
        agent_state="SUSPENDED",
        data_classification_tier=3,
        rpm_limit=60,
        tpm_limit=100_000,
    )
    with pytest.raises(AIHubError) as ei:
        al.assert_agent_active(ctx)
    assert ei.value.code is AIHubErrorCode.AGENT_SUSPENDED


def test_assert_agent_active_rejects_suspended_domain() -> None:
    al = AgentAllowlist()
    ctx = AgentContext(
        agent_id="a",
        domain_id="d",
        domain_state="SUSPENDED",
        agent_state="ACTIVE",
        data_classification_tier=3,
        rpm_limit=60,
        tpm_limit=100_000,
    )
    with pytest.raises(AIHubError) as ei:
        al.assert_agent_active(ctx)
    assert ei.value.code is AIHubErrorCode.DOMAIN_SUSPENDED


def test_restricted_model_rejected_under_tier_2_domain() -> None:
    al = AgentAllowlist()
    ctx = AgentContext(
        agent_id="a",
        domain_id="d",
        domain_state="ACTIVE",
        agent_state="ACTIVE",
        data_classification_tier=2,  # low tier
        rpm_limit=60,
        tpm_limit=100_000,
    )
    with pytest.raises(AIHubError) as ei:
        al.assert_restricted_tier_eligible("claude-opus-4-7", ctx)
    assert ei.value.code is AIHubErrorCode.RESTRICTED_MODEL_NOT_ELIGIBLE


def test_restricted_model_allowed_under_tier_3() -> None:
    al = AgentAllowlist()
    ctx = AgentContext(
        agent_id="a",
        domain_id="d",
        domain_state="ACTIVE",
        agent_state="ACTIVE",
        data_classification_tier=3,
        rpm_limit=60,
        tpm_limit=100_000,
    )
    # No exception — tier 3 is allowed to run Restricted models.
    al.assert_restricted_tier_eligible("claude-opus-4-7", ctx)


def test_standard_model_always_passes_tier_gate() -> None:
    al = AgentAllowlist()
    ctx = AgentContext(
        agent_id="a",
        domain_id="d",
        domain_state="ACTIVE",
        agent_state="ACTIVE",
        data_classification_tier=1,  # lowest tier
        rpm_limit=60,
        tpm_limit=100_000,
    )
    al.assert_restricted_tier_eligible("claude-haiku-4-5", ctx)


def test_for_agent_empty_for_unknown_agent() -> None:
    al = AgentAllowlist()
    assert al.for_agent("never-registered") == []
