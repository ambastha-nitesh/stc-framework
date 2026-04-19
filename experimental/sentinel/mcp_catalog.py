"""
STC Framework - MCP Catalog Integration

Connects STC to enterprise MCP registries for runtime tool discovery,
health monitoring, and governance validation.

STC does NOT implement its own MCP registry — it integrates with whatever
registry the enterprise operates:
  - Official MCP Registry (Linux Foundation AAIF, open-source)
  - Kong MCP Registry (Kong Konnect)
  - Bifrost Tool Registry
  - Custom/self-hosted registries

This module provides:

1. TOOL DISCOVERY
   - Query available MCP servers from the registry
   - Match against permitted_tools in the Declarative Specification
   - Surface newly approved tools to the Stalwart

2. HEALTH MONITORING
   - Periodic health checks on registered MCP servers
   - Mark unhealthy tools as degraded (Stalwart skips them)
   - Alert when a permitted tool becomes unavailable

3. GOVERNANCE VALIDATION
   - Verify that every tool the Stalwart calls is in the registry
   - Detect shadow tools (called but not registered)
   - Enforce the mcp_access_policy from the spec at runtime

4. TRAINER INTEGRATION
   - Expose tool metadata (latency, reliability, cost) to the Trainer
   - Enable the Trainer to optimize tool selection

Usage:
    from sentinel.mcp_catalog import MCPCatalogClient
    catalog = MCPCatalogClient(spec)
    
    # Discover available tools
    tools = catalog.discover_tools()
    
    # Validate a tool call before execution
    valid = catalog.validate_tool_call("document_retriever", persona="stalwart")
    
    # Get tool health
    health = catalog.get_tool_health("document_retriever")
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

from spec.loader import STCSpec

logger = logging.getLogger("stc.mcp_catalog")


# ============================================================================
# Data Types
# ============================================================================

@dataclass
class MCPToolEntry:
    """A tool registered in the MCP catalog."""
    name: str
    description: str
    server_url: str
    transport: str          # stdio | http | sse | streamable_http
    status: str             # active | degraded | inactive | deprecated
    owner: str              # Team or service that owns this tool
    data_tier: str          # public | internal | restricted
    version: str
    last_health_check: Optional[str] = None
    avg_latency_ms: Optional[float] = None
    reliability_percent: Optional[float] = None
    tags: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)


@dataclass
class ToolCallValidation:
    """Result of validating a tool call against the catalog."""
    allowed: bool
    reason: str
    tool: Optional[MCPToolEntry] = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class CatalogSyncResult:
    """Result of syncing the catalog with the spec."""
    total_registered: int
    total_permitted: int
    matched: int
    new_tools: list[str]        # In registry but not in spec (newly available)
    missing_tools: list[str]    # In spec but not in registry (possibly removed)
    shadow_tools: list[str]     # Called recently but not registered
    unhealthy_tools: list[str]


# ============================================================================
# Registry Adapters
# ============================================================================

class RegistryAdapter:
    """Base interface for MCP registry backends."""

    def list_tools(self) -> list[MCPToolEntry]:
        raise NotImplementedError

    def get_tool(self, name: str) -> Optional[MCPToolEntry]:
        raise NotImplementedError

    def health_check_tool(self, name: str) -> dict:
        raise NotImplementedError


class SpecBasedRegistry(RegistryAdapter):
    """
    Default: uses the Declarative Specification as the tool registry.
    No external registry needed. Suitable for development and simple deployments.
    """

    def __init__(self, spec: STCSpec):
        self.spec = spec

    def list_tools(self) -> list[MCPToolEntry]:
        tools = []
        for tool_def in self.spec.stalwart.get("permitted_tools", []):
            tools.append(MCPToolEntry(
                name=tool_def["name"],
                description=tool_def.get("description", ""),
                server_url="local",
                transport="stdio",
                status="active",
                owner="spec-defined",
                data_tier=tool_def.get("risk_tier", "internal"),
                version="1.0",
                tags=tool_def.get("tags", []),
                capabilities=[tool_def["name"]],
            ))
        return tools

    def get_tool(self, name: str) -> Optional[MCPToolEntry]:
        for tool in self.list_tools():
            if tool.name == name:
                return tool
        return None

    def health_check_tool(self, name: str) -> dict:
        tool = self.get_tool(name)
        return {"name": name, "healthy": tool is not None, "source": "spec"}


class KongRegistryAdapter(RegistryAdapter):
    """Connects to Kong MCP Registry via Kong Admin API."""

    def __init__(self, spec: STCSpec):
        self.spec = spec
        self.admin_host = spec.sentinel.get("gateway", {}).get("admin_host", "http://localhost:8001")
        import requests
        self.session = requests.Session()

    def list_tools(self) -> list[MCPToolEntry]:
        try:
            resp = self.session.get(f"{self.admin_host}/mcp-servers", timeout=10)
            if resp.status_code == 200:
                servers = resp.json().get("data", [])
                return [
                    MCPToolEntry(
                        name=s.get("name", ""),
                        description=s.get("description", ""),
                        server_url=s.get("url", ""),
                        transport=s.get("transport", "http"),
                        status=s.get("status", "active"),
                        owner=s.get("owner", ""),
                        data_tier=s.get("data_tier", "internal"),
                        version=s.get("version", ""),
                        tags=s.get("tags", []),
                        capabilities=s.get("capabilities", []),
                    )
                    for s in servers
                ]
        except Exception as e:
            logger.warning(f"Kong MCP Registry unavailable: {e}")
        return []

    def get_tool(self, name: str) -> Optional[MCPToolEntry]:
        tools = self.list_tools()
        return next((t for t in tools if t.name == name), None)

    def health_check_tool(self, name: str) -> dict:
        try:
            resp = self.session.get(f"{self.admin_host}/mcp-servers/{name}/health", timeout=5)
            return resp.json() if resp.status_code == 200 else {"name": name, "healthy": False}
        except Exception:
            return {"name": name, "healthy": False, "source": "kong"}


class BifrostRegistryAdapter(RegistryAdapter):
    """Connects to Bifrost's centralized tool registry."""

    def __init__(self, spec: STCSpec):
        self.spec = spec
        self.host = spec.sentinel.get("gateway", {}).get("host", "http://localhost:8080")
        import requests
        self.session = requests.Session()

    def list_tools(self) -> list[MCPToolEntry]:
        try:
            resp = self.session.get(f"{self.host}/v1/mcp/tools", timeout=10)
            if resp.status_code == 200:
                tools_data = resp.json().get("tools", [])
                return [
                    MCPToolEntry(
                        name=t.get("name", ""),
                        description=t.get("description", ""),
                        server_url=t.get("url", ""),
                        transport=t.get("transport", "http"),
                        status=t.get("status", "active"),
                        owner=t.get("owner", ""),
                        data_tier=t.get("data_tier", "internal"),
                        version=t.get("version", ""),
                        tags=t.get("tags", []),
                        capabilities=t.get("capabilities", []),
                    )
                    for t in tools_data
                ]
        except Exception as e:
            logger.warning(f"Bifrost tool registry unavailable: {e}")
        return []

    def get_tool(self, name: str) -> Optional[MCPToolEntry]:
        tools = self.list_tools()
        return next((t for t in tools if t.name == name), None)

    def health_check_tool(self, name: str) -> dict:
        try:
            resp = self.session.get(f"{self.host}/v1/mcp/tools/{name}/health", timeout=5)
            return resp.json() if resp.status_code == 200 else {"name": name, "healthy": False}
        except Exception:
            return {"name": name, "healthy": False, "source": "bifrost"}


# ============================================================================
# MCP Catalog Client
# ============================================================================

class MCPCatalogClient:
    """
    Main interface for MCP catalog operations in STC.
    
    Bridges the enterprise MCP registry with STC's Declarative Specification,
    providing tool discovery, validation, health monitoring, and Trainer insights.
    """

    def __init__(self, spec: STCSpec):
        self.spec = spec
        self.registry = self._create_registry_adapter(spec)

        # Cache
        self._tool_cache: dict[str, MCPToolEntry] = {}
        self._cache_expiry: Optional[float] = None
        self._cache_ttl_seconds = 300  # 5 minutes

        # Usage tracking (for shadow tool detection)
        self._tool_call_log: list[dict] = []

        # Health tracking
        self._health_status: dict[str, dict] = {}

        logger.info(f"MCP Catalog initialized with {type(self.registry).__name__}")

    def _create_registry_adapter(self, spec: STCSpec) -> RegistryAdapter:
        """Select registry adapter based on gateway engine."""
        engine = spec.sentinel.get("gateway", {}).get("engine", "litellm")

        if engine == "kong":
            try:
                return KongRegistryAdapter(spec)
            except Exception:
                logger.warning("Kong registry unavailable, falling back to spec-based")

        elif engine == "bifrost":
            try:
                return BifrostRegistryAdapter(spec)
            except Exception:
                logger.warning("Bifrost registry unavailable, falling back to spec-based")

        return SpecBasedRegistry(spec)

    # ── Tool Discovery ────────────────────────────────────────────────

    def discover_tools(self, force_refresh: bool = False) -> list[MCPToolEntry]:
        """
        Discover available MCP tools from the registry.
        Results are cached for performance.
        """
        now = time.time()
        if not force_refresh and self._cache_expiry and now < self._cache_expiry:
            return list(self._tool_cache.values())

        tools = self.registry.list_tools()
        self._tool_cache = {t.name: t for t in tools}
        self._cache_expiry = now + self._cache_ttl_seconds

        logger.info(f"Discovered {len(tools)} MCP tools from registry")
        return tools

    def get_tool(self, name: str) -> Optional[MCPToolEntry]:
        """Get a specific tool by name."""
        if name not in self._tool_cache:
            self.discover_tools()
        return self._tool_cache.get(name)

    # ── Governance Validation ─────────────────────────────────────────

    def validate_tool_call(self, tool_name: str, persona: str = "stalwart",
                            data_tier: Optional[str] = None) -> ToolCallValidation:
        """
        Validate a tool call against the catalog and access policy.
        
        Checks:
        1. Tool exists in registry
        2. Tool is healthy/active
        3. Persona is authorized (mcp_access_policy)
        4. Data tier is compatible
        """
        warnings = []

        # 1. Check registry
        tool = self.get_tool(tool_name)
        if not tool:
            # Check if it's in the spec but not the registry
            spec_tools = [t["name"] for t in self.spec.stalwart.get("permitted_tools", [])]
            if tool_name in spec_tools:
                return ToolCallValidation(
                    allowed=False,
                    reason=f"Tool '{tool_name}' is in spec but not found in MCP registry (may be offline)",
                    warnings=["Tool declared in spec but missing from registry — possible outage"],
                )
            return ToolCallValidation(
                allowed=False,
                reason=f"Tool '{tool_name}' not found in MCP registry or spec",
            )

        # 2. Check health
        if tool.status == "inactive":
            return ToolCallValidation(
                allowed=False, reason=f"Tool '{tool_name}' is inactive",
                tool=tool,
            )
        if tool.status == "deprecated":
            warnings.append(f"Tool '{tool_name}' is deprecated — consider migration")
        if tool.status == "degraded":
            warnings.append(f"Tool '{tool_name}' is degraded — results may be unreliable")

        # 3. Check access policy
        access_policies = self.spec.sentinel.get("mcp_access_policy", [])
        policy_match = None
        for policy in access_policies:
            if policy.get("tool") == tool_name:
                policy_match = policy
                break

        if policy_match:
            allowed_personas = policy_match.get("allowed_personas", [])
            if persona not in allowed_personas:
                return ToolCallValidation(
                    allowed=False,
                    reason=f"Persona '{persona}' not authorized for tool '{tool_name}' (allowed: {allowed_personas})",
                    tool=tool,
                )

        # 4. Check data tier compatibility
        if data_tier and tool.data_tier:
            tier_order = {"public": 0, "internal": 1, "restricted": 2}
            request_level = tier_order.get(data_tier, 1)
            tool_level = tier_order.get(tool.data_tier, 1)
            if request_level > tool_level:
                return ToolCallValidation(
                    allowed=False,
                    reason=f"Data tier mismatch: request is '{data_tier}' but tool handles '{tool.data_tier}'",
                    tool=tool,
                )

        # Record the call for tracking
        self._tool_call_log.append({
            "tool": tool_name, "persona": persona,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return ToolCallValidation(
            allowed=True,
            reason="Tool call approved",
            tool=tool,
            warnings=warnings,
        )

    # ── Health Monitoring ─────────────────────────────────────────────

    def check_all_health(self) -> dict[str, dict]:
        """Run health checks on all registered tools."""
        tools = self.discover_tools(force_refresh=True)
        results = {}

        for tool in tools:
            health = self.registry.health_check_tool(tool.name)
            healthy = health.get("healthy", False)

            results[tool.name] = {
                "healthy": healthy,
                "status": tool.status,
                "last_check": datetime.now(timezone.utc).isoformat(),
                "details": health,
            }

            # Update tool status based on health
            if not healthy and tool.status == "active":
                tool.status = "degraded"
                logger.warning(f"Tool '{tool.name}' marked as degraded (health check failed)")

        self._health_status = results
        return results

    def get_tool_health(self, tool_name: str) -> dict:
        """Get health status for a specific tool."""
        if tool_name in self._health_status:
            return self._health_status[tool_name]
        health = self.registry.health_check_tool(tool_name)
        return {"name": tool_name, "details": health}

    # ── Catalog Sync (compare registry vs spec) ───────────────────────

    def sync_with_spec(self) -> CatalogSyncResult:
        """
        Compare the MCP registry against the Declarative Specification.
        Identifies gaps, new tools, and shadow tools.
        """
        registry_tools = {t.name for t in self.discover_tools(force_refresh=True)}
        spec_tools = {t["name"] for t in self.spec.stalwart.get("permitted_tools", [])}

        # Tools called recently but not in registry (shadow tools)
        recent_cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        called_tools = {
            log["tool"] for log in self._tool_call_log
            if log["timestamp"] > recent_cutoff
        }
        shadow = called_tools - registry_tools - spec_tools

        # New in registry but not in spec
        new_tools = registry_tools - spec_tools

        # In spec but not in registry
        missing = spec_tools - registry_tools

        # Unhealthy
        unhealthy = [
            name for name, health in self._health_status.items()
            if not health.get("healthy", True)
        ]

        result = CatalogSyncResult(
            total_registered=len(registry_tools),
            total_permitted=len(spec_tools),
            matched=len(registry_tools & spec_tools),
            new_tools=sorted(new_tools),
            missing_tools=sorted(missing),
            shadow_tools=sorted(shadow),
            unhealthy_tools=sorted(unhealthy),
        )

        if result.shadow_tools:
            logger.warning(f"Shadow tools detected (called but not registered): {result.shadow_tools}")
        if result.missing_tools:
            logger.warning(f"Tools in spec but not in registry: {result.missing_tools}")

        return result

    # ── Trainer Integration ───────────────────────────────────────────

    def get_tool_metrics(self) -> dict[str, dict]:
        """
        Get tool performance metrics for the Trainer.
        Enables the Trainer to optimize tool selection.
        """
        tools = self.discover_tools()
        metrics = {}

        for tool in tools:
            # Count recent calls
            recent_calls = sum(
                1 for log in self._tool_call_log
                if log["tool"] == tool.name
            )

            metrics[tool.name] = {
                "status": tool.status,
                "data_tier": tool.data_tier,
                "avg_latency_ms": tool.avg_latency_ms,
                "reliability_percent": tool.reliability_percent,
                "recent_calls": recent_calls,
                "healthy": self._health_status.get(tool.name, {}).get("healthy", True),
            }

        return metrics


# ============================================================================
# Demo
# ============================================================================

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from spec.loader import load_spec

    spec = load_spec("spec/stc-spec.yaml")
    catalog = MCPCatalogClient(spec)

    print("=" * 65)
    print("  STC MCP Catalog Integration — Demo")
    print(f"  Registry: {type(catalog.registry).__name__}")
    print("=" * 65)

    # Discover tools
    print("\n  TOOL DISCOVERY:")
    tools = catalog.discover_tools()
    for tool in tools:
        print(f"    📦 {tool.name:25s} [{tool.status}] tier={tool.data_tier}")

    # Validate tool calls
    print("\n  TOOL CALL VALIDATION:")
    validations = [
        ("stalwart", "document_retriever", "restricted"),
        ("stalwart", "calculator", "public"),
        ("stalwart", "unauthorized_tool", None),
        ("trainer", "document_retriever", "restricted"),
        ("critic", "calculator", "public"),
    ]

    for persona, tool_name, tier in validations:
        result = catalog.validate_tool_call(tool_name, persona=persona, data_tier=tier)
        icon = "✅" if result.allowed else "🚫"
        print(f"    {icon} {persona:10s} → {tool_name:25s} {result.reason}")
        for w in result.warnings:
            print(f"       ⚠️ {w}")

    # Health check
    print("\n  HEALTH MONITORING:")
    health = catalog.check_all_health()
    for name, status in health.items():
        icon = "💚" if status["healthy"] else "🔴"
        print(f"    {icon} {name:25s} status={status['status']}")

    # Sync with spec
    print("\n  CATALOG SYNC (registry vs spec):")
    sync = catalog.sync_with_spec()
    print(f"    Registry tools: {sync.total_registered}")
    print(f"    Spec tools:     {sync.total_permitted}")
    print(f"    Matched:        {sync.matched}")
    if sync.new_tools:
        print(f"    🆕 New (in registry, not spec): {sync.new_tools}")
    if sync.missing_tools:
        print(f"    ⚠️ Missing (in spec, not registry): {sync.missing_tools}")
    if sync.shadow_tools:
        print(f"    🚨 Shadow (called but not registered): {sync.shadow_tools}")

    # Trainer metrics
    print("\n  TOOL METRICS (for Trainer):")
    metrics = catalog.get_tool_metrics()
    for name, data in metrics.items():
        print(f"    {name:25s} calls={data['recent_calls']}, healthy={data['healthy']}")
