# Sentinel Layer

The Sentinel Layer is the STC Framework's infrastructure enforcement surface. It is **not an agent** — it does not learn, evolve, or make judgments. It enforces policies defined in the Declarative Specification.

## Responsibilities

- Route LLM requests based on data classification tier
- Redact PII before data crosses trust boundaries (via Presidio)
- Authenticate and authorize each persona's access scope
- Govern MCP tool access (who can call which tools)
- Log every boundary crossing for audit

## Gateway Options

The Sentinel is **gateway-agnostic**. Switch between gateways by changing one line in the Declarative Specification:

```yaml
sentinel:
  gateway:
    engine: litellm  # litellm | kong | bifrost
```

### Choosing a Gateway

```
┌─────────────────────────┬──────────┬──────────┬──────────┐
│ Capability              │ LiteLLM  │ Kong     │ Bifrost  │
├─────────────────────────┼──────────┼──────────┼──────────┤
│ LLM Routing             │ ✅ 100+  │ ✅ 10+   │ ✅ 20+   │
│ Cost Tracking           │ ✅       │ ✅       │ ✅       │
│ MCP Tool Governance     │ ❌       │ ✅       │ ✅       │
│ MCP Server Registry     │ ❌       │ ✅       │ ✅       │
│ A2A Protocol Support    │ ❌       │ ✅       │ ❌       │
│ Tool Access Control     │ ❌       │ ✅       │ ✅       │
│ PII Redaction           │ ✅       │ plugin   │ via STC  │
│ Overhead Latency        │ ~8ms     │ 2-5ms    │ ~11µs    │
│ License                 │ Apache   │ Apache   │ Apache   │
├─────────────────────────┼──────────┼──────────┼──────────┤
│ Best For                │ Dev/Eval │ Enterprise│ Perf.   │
└─────────────────────────┴──────────┴──────────┴──────────┘
```

**LiteLLM (Default)** — Start here. Broadest LLM provider support, easiest setup, Python-native. Use for development, evaluation, and deployments that don't require MCP tool governance.

```bash
docker-compose up -d
```

**Kong AI Gateway (Enterprise Recommended)** — Use when you need MCP tool governance, A2A agent communication, OAuth 2.1 for MCP servers, and enterprise-grade access control. Ideal for regulated industries (financial services, healthcare).

```bash
docker-compose -f docker-compose.yaml -f docker-compose.kong.yaml up -d
```

**Bifrost (High Performance)** — Use when latency matters. 11µs gateway overhead, native MCP support, hierarchical budget management. Self-hosted, Apache 2.0.

```bash
docker-compose -f docker-compose.yaml -f docker-compose.bifrost.yaml up -d
```

## Architecture

```
                    ┌───────────────┐
                    │   Stalwart    │
                    └───────┬───────┘
                            │
                    ┌───────▼───────┐
                    │   Sentinel    │
                    │   Adapters    │
                    │  (interface)  │
                    └───┬───┬───┬───┘
                        │   │   │
              ┌─────────┘   │   └─────────┐
              │             │             │
      ┌───────▼──┐  ┌──────▼─────┐  ┌────▼─────┐
      │ LiteLLM  │  │   Kong AI  │  │ Bifrost  │
      │ Adapter  │  │  Adapter   │  │ Adapter  │
      └──────────┘  └────────────┘  └──────────┘
              │             │             │
      ┌───────▼──┐  ┌──────▼─────┐  ┌────▼─────┐
      │ LiteLLM  │  │   Kong     │  │ Bifrost  │
      │  Proxy   │  │  Gateway   │  │ Gateway  │
      │          │  │ + MCP Proxy│  │ + MCP    │
      └──────────┘  └────────────┘  └──────────┘
```

All three adapters implement the same `GatewayAdapter` interface. Your Stalwart, Trainer, and Critic code never changes — only the infrastructure underneath.

## Usage in Code

```python
from sentinel.adapters import create_gateway
from spec.loader import load_spec

spec = load_spec("spec/stc-spec.yaml")
gateway = create_gateway(spec)  # Reads sentinel.gateway.engine from spec

# LLM completion (same API regardless of gateway)
response = gateway.completion(
    messages=[{"role": "user", "content": "What was Q4 revenue?"}],
    data_tier="internal",
    metadata={"stc_persona": "stalwart"},
)

# Tool access validation (enforced by Kong/Bifrost, advisory for LiteLLM)
allowed = gateway.validate_tool_access("document_retriever", persona="stalwart")

# Spend tracking
spend = gateway.get_spend_report(persona="stalwart")
```

## MCP Governance (Kong and Bifrost only)

When using Kong or Bifrost, the Declarative Specification's MCP policies are enforced at the gateway level:

```yaml
stalwart:
  permitted_tools:
    - name: document_retriever
      risk_tier: restricted
    - name: calculator
      risk_tier: public

sentinel:
  gateway:
    engine: kong  # or bifrost
  mcp_access_policy:
    - tool: document_retriever
      allowed_personas: [stalwart]
      data_tier: restricted
    - tool: calculator
      allowed_personas: [stalwart, trainer]
      data_tier: public
  trusted_agents: []  # A2A trust list (Kong only)
```

With LiteLLM, these policies are validated in-process (advisory) but not enforced at the gateway. The framework logs a warning recommending an upgrade to Kong or Bifrost.
