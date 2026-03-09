"""
STC Framework - Sentinel Layer: Gateway Adapters

The Sentinel Layer is gateway-agnostic. It defines a common interface that
all gateway adapters implement, and the Declarative Specification's
`sentinel.gateway.engine` field selects which adapter to use.

Three adapters are provided:

  litellm  — Default. Best for rapid development, 100+ LLM providers,
             Python-native. No MCP governance.

  kong     — Enterprise recommended. Unified LLM + MCP + A2A gateway.
             MCP Registry, OAuth 2.1, tool-level access control.
             Requires Kong Gateway deployment.

  bifrost  — High-performance alternative. Go-based, 11µs overhead,
             native MCP support, centralized tool registry,
             hierarchical budget management. Self-hosted, Apache 2.0.

Usage:
    from sentinel.adapters import create_gateway
    gateway = create_gateway(spec)
    response = gateway.completion(messages, data_tier="internal")
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional
from spec.loader import STCSpec

logger = logging.getLogger("stc.sentinel")


# ============================================================================
# Gateway Adapter Interface
# ============================================================================

class GatewayAdapter(ABC):
    """
    Abstract interface that all gateway adapters implement.
    
    The STC framework interacts with the Sentinel exclusively through
    this interface. The underlying gateway (LiteLLM, Kong, Bifrost)
    handles the actual routing, auth, PII redaction, and MCP governance.
    """

    @abstractmethod
    def completion(self, messages: list[dict], data_tier: str = "public",
                   metadata: Optional[dict] = None):
        """Route an LLM completion request through the gateway."""
        pass

    @abstractmethod
    def validate_tool_access(self, tool_name: str, persona: str) -> bool:
        """Check if a persona is authorized to call a specific tool/MCP server."""
        pass

    @abstractmethod
    def log_boundary_crossing(self, data_tier: str, destination: str,
                               redactions: list[dict]):
        """Log a data boundary crossing event for audit."""
        pass

    @abstractmethod
    def get_spend_report(self, persona: Optional[str] = None) -> dict:
        """Get current spend tracking data, optionally filtered by persona."""
        pass

    @abstractmethod
    def health_check(self) -> dict:
        """Check gateway health and connectivity."""
        pass


# ============================================================================
# LiteLLM Adapter (Default)
# ============================================================================

class LiteLLMAdapter(GatewayAdapter):
    """
    Default gateway adapter using LiteLLM.

    Best for:
      - Rapid development and evaluation
      - 100+ LLM provider support
      - Python-native workflows
      - Teams that don't need MCP tool governance

    Limitations:
      - No native MCP governance
      - No tool-level access control
      - Python performance ceiling at high throughput
      - MCP access policies from spec are logged but not enforced

    Setup:
      pip install litellm
      # Configure in stc-spec.yaml:
      # sentinel.gateway.engine: litellm
      # sentinel.gateway.host: http://localhost:4000
    """

    def __init__(self, spec: STCSpec):
        self.spec = spec
        self.gateway_config = spec.sentinel.get("gateway", {})

        try:
            import litellm
            self.litellm = litellm

            host = self.gateway_config.get("host")
            if host:
                litellm.api_base = host

            self.available = True
            logger.info(f"LiteLLM adapter initialized (host: {host or 'direct'})")
        except ImportError:
            self.available = False
            logger.error("LiteLLM not installed. Run: pip install litellm")

    def completion(self, messages: list[dict], data_tier: str = "public",
                   metadata: Optional[dict] = None):
        if not self.available:
            raise RuntimeError("LiteLLM not available")

        allowed_models = self.spec.get_routing_policy(data_tier)
        model = allowed_models[0] if allowed_models else "openai/gpt-4o"

        return self.litellm.completion(
            model=model,
            messages=messages,
            metadata=metadata or {},
        )

    def validate_tool_access(self, tool_name: str, persona: str) -> bool:
        """
        LiteLLM does not enforce MCP tool access.
        Validates against the spec's permitted_tools list (advisory only).
        """
        permitted = [t["name"] for t in self.spec.stalwart.get("permitted_tools", [])]
        allowed = tool_name in permitted

        if not allowed:
            logger.warning(
                f"Tool access ADVISORY: '{tool_name}' not in permitted_tools "
                f"for persona '{persona}'. LiteLLM does not enforce this — "
                f"upgrade to Kong or Bifrost for tool-level access control."
            )
        return allowed

    def log_boundary_crossing(self, data_tier: str, destination: str,
                               redactions: list[dict]):
        logger.info(
            f"Boundary crossing: tier={data_tier}, dest={destination}, "
            f"redactions={len(redactions)}"
        )

    def get_spend_report(self, persona: Optional[str] = None) -> dict:
        """LiteLLM tracks spend via its proxy; returns basic info."""
        return {"engine": "litellm", "note": "Use LiteLLM proxy dashboard for detailed spend"}

    def health_check(self) -> dict:
        return {"engine": "litellm", "available": self.available}


# ============================================================================
# Kong AI Gateway Adapter (Enterprise Recommended)
# ============================================================================

class KongAdapter(GatewayAdapter):
    """
    Enterprise-grade gateway adapter using Kong AI Gateway.

    Best for:
      - Production deployments requiring MCP tool governance
      - Unified LLM + MCP + A2A traffic management
      - Organizations already using Kong for API management
      - Regulatory environments (FINRA, HIPAA, SOX)

    Capabilities:
      - LLM routing via AI Proxy plugin
      - MCP governance via AI MCP Proxy plugin
      - MCP server registry and discovery
      - OAuth 2.1 authentication for MCP servers
      - Tool-level access control per consumer/persona
      - Prometheus metrics + OpenTelemetry export
      - PII detection and prompt governance

    Setup:
      # Deploy Kong Gateway (open-source or Konnect)
      # Configure in stc-spec.yaml:
      # sentinel.gateway.engine: kong
      # sentinel.gateway.host: http://localhost:8000
      # sentinel.gateway.admin_host: http://localhost:8001
    """

    def __init__(self, spec: STCSpec):
        self.spec = spec
        self.gateway_config = spec.sentinel.get("gateway", {})
        self.host = self.gateway_config.get("host", "http://localhost:8000")
        self.admin_host = self.gateway_config.get("admin_host", "http://localhost:8001")

        import requests
        self.session = requests.Session()

        # Verify Kong connectivity
        try:
            resp = self.session.get(f"{self.admin_host}/status", timeout=5)
            self.available = resp.status_code == 200
            logger.info(f"Kong adapter initialized (proxy: {self.host}, admin: {self.admin_host})")
        except Exception as e:
            self.available = False
            logger.error(f"Kong not reachable at {self.admin_host}: {e}")

    def completion(self, messages: list[dict], data_tier: str = "public",
                   metadata: Optional[dict] = None):
        """
        Route LLM request through Kong AI Proxy plugin.
        Kong handles model selection, auth, PII scanning, and rate limiting.
        """
        allowed_models = self.spec.get_routing_policy(data_tier)
        model = allowed_models[0] if allowed_models else "openai/gpt-4o"

        # Kong AI Proxy expects OpenAI-compatible format
        payload = {
            "model": model,
            "messages": messages,
            "metadata": metadata or {},
        }

        # Route through Kong's AI Proxy service
        persona = (metadata or {}).get("stc_persona", "stalwart")
        headers = {
            "Content-Type": "application/json",
            "X-STC-Persona": persona,
            "X-STC-Data-Tier": data_tier,
        }

        # Add persona API key for Kong consumer auth
        persona_keys = self.spec.sentinel.get("auth", {}).get("persona_keys", {})
        api_key = persona_keys.get(persona)
        if api_key:
            headers["apikey"] = api_key

        response = self.session.post(
            f"{self.host}/ai/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return _to_completion_response(response.json())

    def validate_tool_access(self, tool_name: str, persona: str) -> bool:
        """
        Validate tool access via Kong's MCP Registry and consumer ACLs.
        Kong enforces this at the gateway level — this is a pre-check.
        """
        permitted = [t["name"] for t in self.spec.stalwart.get("permitted_tools", [])]
        if tool_name not in permitted:
            logger.warning(f"Tool '{tool_name}' not in spec permitted_tools")
            return False

        # Optionally verify against Kong's MCP Registry
        try:
            resp = self.session.get(
                f"{self.admin_host}/mcp-servers",
                params={"name": tool_name},
                timeout=5,
            )
            if resp.status_code == 200:
                servers = resp.json().get("data", [])
                registered = any(s.get("name") == tool_name for s in servers)
                if not registered:
                    logger.warning(f"Tool '{tool_name}' not registered in Kong MCP Registry")
                    return False
        except Exception as e:
            logger.warning(f"Could not verify tool in Kong MCP Registry: {e}")

        return True

    def log_boundary_crossing(self, data_tier: str, destination: str,
                               redactions: list[dict]):
        """Kong logs this automatically via its logging plugins."""
        logger.info(
            f"Boundary crossing [Kong]: tier={data_tier}, dest={destination}, "
            f"redactions={len(redactions)}"
        )

    def get_spend_report(self, persona: Optional[str] = None) -> dict:
        """Query Kong's analytics for spend data."""
        try:
            params = {}
            if persona:
                params["consumer"] = persona

            resp = self.session.get(
                f"{self.admin_host}/ai/analytics/spend",
                params=params,
                timeout=10,
            )
            if resp.status_code == 200:
                return {"engine": "kong", "data": resp.json()}
        except Exception as e:
            logger.warning(f"Could not fetch Kong spend data: {e}")

        return {"engine": "kong", "note": "Use Kong Manager dashboard for detailed analytics"}

    def health_check(self) -> dict:
        try:
            resp = self.session.get(f"{self.admin_host}/status", timeout=5)
            status = resp.json() if resp.status_code == 200 else {}
            return {
                "engine": "kong",
                "available": resp.status_code == 200,
                "status": status,
            }
        except Exception as e:
            return {"engine": "kong", "available": False, "error": str(e)}


# ============================================================================
# Bifrost Adapter (High-Performance Open Source)
# ============================================================================

class BifrostAdapter(GatewayAdapter):
    """
    High-performance gateway adapter using Bifrost (Maxim AI).

    Best for:
      - Performance-critical deployments (11µs gateway overhead)
      - Teams needing unified LLM + MCP in a single control plane
      - Self-hosted environments with data sovereignty requirements
      - Hierarchical budget management (customer → team → key → provider)

    Capabilities:
      - LLM routing with 20+ providers
      - Native MCP integration (STDIO, HTTP, SSE, Streamable HTTP)
      - Centralized tool registry with per-team access controls
      - Four-tier budget hierarchy with automatic enforcement
      - Virtual keys with per-key rate limits and model restrictions
      - Semantic caching for cost reduction
      - OpenTelemetry-native observability

    Setup:
      npx -y @maximhq/bifrost
      # Or: docker run -p 8080:8080 maximhq/bifrost
      # Configure in stc-spec.yaml:
      # sentinel.gateway.engine: bifrost
      # sentinel.gateway.host: http://localhost:8080
    """

    def __init__(self, spec: STCSpec):
        self.spec = spec
        self.gateway_config = spec.sentinel.get("gateway", {})
        self.host = self.gateway_config.get("host", "http://localhost:8080")

        import requests
        self.session = requests.Session()

        # Verify Bifrost connectivity
        try:
            resp = self.session.get(f"{self.host}/health", timeout=5)
            self.available = resp.status_code == 200
            logger.info(f"Bifrost adapter initialized (host: {self.host})")
        except Exception as e:
            self.available = False
            logger.error(f"Bifrost not reachable at {self.host}: {e}")

    def completion(self, messages: list[dict], data_tier: str = "public",
                   metadata: Optional[dict] = None):
        """
        Route LLM request through Bifrost.
        Bifrost provides OpenAI-compatible API with built-in governance.
        """
        allowed_models = self.spec.get_routing_policy(data_tier)
        model = allowed_models[0] if allowed_models else "openai/gpt-4o"

        persona = (metadata or {}).get("stc_persona", "stalwart")

        # Bifrost uses virtual keys for per-persona governance
        persona_keys = self.spec.sentinel.get("auth", {}).get("persona_keys", {})
        api_key = persona_keys.get(persona, "")

        payload = {
            "model": model,
            "messages": messages,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-STC-Data-Tier": data_tier,
        }

        response = self.session.post(
            f"{self.host}/v1/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return _to_completion_response(response.json())

    def validate_tool_access(self, tool_name: str, persona: str) -> bool:
        """
        Validate tool access via Bifrost's centralized tool registry.
        Bifrost enforces per-team access controls on MCP tools.
        """
        permitted = [t["name"] for t in self.spec.stalwart.get("permitted_tools", [])]
        if tool_name not in permitted:
            logger.warning(f"Tool '{tool_name}' not in spec permitted_tools")
            return False

        # Verify against Bifrost's MCP tool registry
        try:
            resp = self.session.get(
                f"{self.host}/v1/mcp/tools",
                params={"name": tool_name},
                timeout=5,
            )
            if resp.status_code == 200:
                tools = resp.json().get("tools", [])
                registered = any(t.get("name") == tool_name for t in tools)
                if not registered:
                    logger.warning(f"Tool '{tool_name}' not in Bifrost tool registry")
                    return False
        except Exception as e:
            logger.warning(f"Could not verify tool in Bifrost registry: {e}")

        return True

    def log_boundary_crossing(self, data_tier: str, destination: str,
                               redactions: list[dict]):
        """Bifrost logs via OpenTelemetry; this adds STC-specific context."""
        logger.info(
            f"Boundary crossing [Bifrost]: tier={data_tier}, dest={destination}, "
            f"redactions={len(redactions)}"
        )

    def get_spend_report(self, persona: Optional[str] = None) -> dict:
        """Query Bifrost's budget management API."""
        try:
            endpoint = f"{self.host}/v1/budgets"
            if persona:
                endpoint += f"?virtual_key={persona}"

            resp = self.session.get(endpoint, timeout=10)
            if resp.status_code == 200:
                return {"engine": "bifrost", "data": resp.json()}
        except Exception as e:
            logger.warning(f"Could not fetch Bifrost spend data: {e}")

        return {"engine": "bifrost", "note": "Use Bifrost dashboard for detailed budget data"}

    def health_check(self) -> dict:
        try:
            resp = self.session.get(f"{self.host}/health", timeout=5)
            return {
                "engine": "bifrost",
                "available": resp.status_code == 200,
            }
        except Exception as e:
            return {"engine": "bifrost", "available": False, "error": str(e)}


# ============================================================================
# Helper
# ============================================================================

class _CompletionResponse:
    """Minimal response wrapper for non-LiteLLM gateways."""
    def __init__(self, data: dict):
        self.model = data.get("model", "unknown")
        self.choices = [type("Choice", (), {
            "message": type("Message", (), {
                "content": c.get("message", {}).get("content", "")
            })()
        })() for c in data.get("choices", [])]
        self.usage = type("Usage", (), {
            "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
            "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
        })()


def _to_completion_response(data: dict):
    return _CompletionResponse(data)


# ============================================================================
# Factory
# ============================================================================

GATEWAY_ADAPTERS = {
    "litellm": LiteLLMAdapter,
    "kong": KongAdapter,
    "bifrost": BifrostAdapter,
}


def create_gateway(spec: STCSpec) -> GatewayAdapter:
    """
    Factory: create the appropriate gateway adapter based on the spec.

    Reads sentinel.gateway.engine from the Declarative Specification
    and instantiates the corresponding adapter.
    """
    engine = spec.sentinel.get("gateway", {}).get("engine", "litellm")

    if engine not in GATEWAY_ADAPTERS:
        raise ValueError(
            f"Unknown gateway engine: '{engine}'. "
            f"Supported: {list(GATEWAY_ADAPTERS.keys())}"
        )

    adapter_class = GATEWAY_ADAPTERS[engine]
    logger.info(f"Creating gateway adapter: {engine}")

    adapter = adapter_class(spec)

    # Log capability summary
    if engine == "litellm":
        logger.info(
            "  ℹ️  LiteLLM: LLM routing ✓ | MCP governance ✗ | Tool access control ✗\n"
            "     For MCP/tool governance, set gateway.engine to 'kong' or 'bifrost'"
        )
    elif engine == "kong":
        logger.info(
            "  ✅ Kong: LLM routing ✓ | MCP governance ✓ | Tool access control ✓ | A2A ✓"
        )
    elif engine == "bifrost":
        logger.info(
            "  ✅ Bifrost: LLM routing ✓ | MCP governance ✓ | Tool access control ✓ | Budget hierarchy ✓"
        )

    return adapter


# ============================================================================
# Gateway Comparison (for documentation / CLI)
# ============================================================================

def print_gateway_comparison():
    """Print a comparison table of gateway capabilities."""
    print("""
┌─────────────────────────────┬──────────┬──────────┬──────────┐
│ Capability                  │ LiteLLM  │ Kong     │ Bifrost  │
├─────────────────────────────┼──────────┼──────────┼──────────┤
│ LLM Routing                 │ ✅ 100+  │ ✅ 10+   │ ✅ 20+   │
│ Cost Tracking               │ ✅       │ ✅       │ ✅       │
│ Budget Enforcement          │ ✅       │ ✅       │ ✅ 4-tier│
│ MCP Tool Governance         │ ❌       │ ✅       │ ✅       │
│ MCP Server Registry         │ ❌       │ ✅       │ ✅       │
│ MCP OAuth 2.1               │ ❌       │ ✅       │ ❌       │
│ A2A Protocol Support        │ ❌       │ ✅       │ ❌       │
│ Tool-Level Access Control   │ ❌       │ ✅       │ ✅       │
│ PII Redaction (Presidio)    │ ✅       │ plugin   │ ❌*      │
│ Semantic Caching            │ ❌       │ ✅ ent.  │ ✅       │
│ Overhead Latency            │ ~8ms     │ 2-5ms    │ ~11µs    │
│ Language                    │ Python   │ Lua/C    │ Go       │
│ License                     │ Apache   │ Apache   │ Apache   │
│ Self-Hosted                 │ ✅       │ ✅       │ ✅       │
├─────────────────────────────┼──────────┼──────────┼──────────┤
│ RECOMMENDED FOR             │ Dev/Eval │ Enterprise│ Perf.   │
└─────────────────────────────┴──────────┴──────────┴──────────┘

* Bifrost: PII redaction handled by STC's Presidio layer before gateway

When to use which:
  litellm  → Getting started, prototyping, evaluation, broadest LLM support
  kong     → Production with MCP governance, A2A, regulatory compliance
  bifrost  → Performance-critical production, self-hosted, hierarchical budgets
""")


if __name__ == "__main__":
    print_gateway_comparison()
