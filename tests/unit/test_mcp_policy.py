from stc_framework.adapters.mcp.default_policy import DefaultMCPPolicy


def test_untrusted_persona_denied():
    policy = DefaultMCPPolicy(trusted_agents=["stalwart"])
    decision = policy.evaluate(
        persona="critic", mcp_server="data", tool_name="fetch", data_tier="public"
    )
    assert not decision.allowed


def test_explicit_rule_allows():
    policy = DefaultMCPPolicy(
        trusted_agents=[],
        access_policy=[{"server": "data", "tool": "fetch", "allowed": True}],
    )
    decision = policy.evaluate(
        persona="any", mcp_server="data", tool_name="fetch", data_tier="public"
    )
    assert decision.allowed


def test_tool_risk_tier_below_data_tier_denied():
    policy = DefaultMCPPolicy(
        trusted_agents=["stalwart"], tool_risk_tiers={"fetch": "public"}
    )
    decision = policy.evaluate(
        persona="stalwart", mcp_server="data", tool_name="fetch", data_tier="restricted"
    )
    assert not decision.allowed


def test_default_allow_for_trusted_and_tiered():
    policy = DefaultMCPPolicy(
        trusted_agents=["stalwart"], tool_risk_tiers={"fetch": "restricted"}
    )
    decision = policy.evaluate(
        persona="stalwart", mcp_server="data", tool_name="fetch", data_tier="internal"
    )
    assert decision.allowed
