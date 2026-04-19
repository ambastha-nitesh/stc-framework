"""MCP access policy protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class MCPAccessDecision:
    allowed: bool
    reason: str = ""


@runtime_checkable
class MCPAccessPolicy(Protocol):
    """Decides whether a persona can call a given MCP server/tool."""

    def evaluate(
        self,
        *,
        persona: str,
        mcp_server: str,
        tool_name: str,
        data_tier: str,
    ) -> MCPAccessDecision: ...
