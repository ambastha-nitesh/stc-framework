"""Default MCP access policy honoring ``trusted_agents`` and per-tool rules.

Deny-by-default. Allow only when:
- the persona is in ``trusted_agents``, AND
- the tool's declared ``risk_tier`` is compatible with the current ``data_tier``.
"""

from __future__ import annotations

from typing import Any

from stc_framework.adapters.mcp.base import MCPAccessDecision, MCPAccessPolicy

_TIER_ORDER = {"public": 0, "internal": 1, "restricted": 2}


class DefaultMCPPolicy(MCPAccessPolicy):
    def __init__(
        self,
        trusted_agents: list[str],
        access_policy: list[dict[str, Any]] | None = None,
        tool_risk_tiers: dict[str, str] | None = None,
    ) -> None:
        self._trusted = set(trusted_agents)
        self._policy = list(access_policy or [])
        self._tool_tiers = dict(tool_risk_tiers or {})

    def evaluate(
        self,
        *,
        persona: str,
        mcp_server: str,
        tool_name: str,
        data_tier: str,
    ) -> MCPAccessDecision:
        # Explicit policy entries win first.
        for rule in self._policy:
            if rule.get("server") != mcp_server:
                continue
            if rule.get("tool") not in (None, tool_name):
                continue
            allowed = bool(rule.get("allowed", False))
            if not allowed:
                return MCPAccessDecision(allowed=False, reason=f"denied by policy rule for {mcp_server}")
            return MCPAccessDecision(allowed=True, reason="allowed by policy rule")

        if self._trusted and persona not in self._trusted:
            return MCPAccessDecision(allowed=False, reason=f"persona {persona!r} not in trusted_agents")

        tool_tier = self._tool_tiers.get(tool_name, "public")
        if _TIER_ORDER[tool_tier] < _TIER_ORDER.get(data_tier, 1):
            return MCPAccessDecision(
                allowed=False,
                reason=f"tool risk_tier={tool_tier} below data_tier={data_tier}",
            )

        return MCPAccessDecision(allowed=True, reason="default allow")
