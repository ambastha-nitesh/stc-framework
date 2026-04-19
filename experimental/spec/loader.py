"""
STC Framework - Declarative Specification Loader

Loads and validates the STC specification YAML file,
providing typed access to all configuration sections.
"""

import yaml
from dataclasses import dataclass, field
from typing import Any, Optional
from pathlib import Path


@dataclass
class STCSpec:
    """Parsed STC Declarative Specification."""
    
    version: str
    name: str
    description: str
    raw: dict  # Full parsed YAML for component-specific access
    
    @property
    def stalwart(self) -> dict:
        return self.raw.get("stalwart", {})
    
    @property
    def trainer(self) -> dict:
        return self.raw.get("trainer", {})
    
    @property
    def critic(self) -> dict:
        return self.raw.get("critic", {})
    
    @property
    def sentinel(self) -> dict:
        return self.raw.get("sentinel", {})
    
    @property
    def data_sovereignty(self) -> dict:
        return self.raw.get("data_sovereignty", {})
    
    @property
    def audit(self) -> dict:
        return self.raw.get("audit", {})
    
    @property
    def risk_taxonomy(self) -> dict:
        return self.raw.get("risk_taxonomy", {})
    
    @property
    def compliance(self) -> dict:
        return self.raw.get("compliance", {})
    
    def get_routing_policy(self, data_tier: str) -> list[str]:
        """Get allowed model endpoints for a data classification tier."""
        routing = self.data_sovereignty.get("routing_policy", {})
        return routing.get(data_tier, routing.get("public", []))
    
    def get_guardrails(self, rail_type: str = "output") -> list[dict]:
        """Get guardrail configurations by type (input/output)."""
        rails_key = f"{rail_type}_rails"
        return self.critic.get("guardrails", {}).get(rails_key, [])
    
    def get_cost_threshold(self, metric: str) -> Optional[float]:
        """Get a cost threshold value."""
        return self.trainer.get("cost_thresholds", {}).get(metric)
    
    def get_escalation_config(self, level: str) -> Optional[dict]:
        """Get escalation configuration for a given level."""
        return self.critic.get("escalation", {}).get(level)


def load_spec(path: str = "spec/stc-spec.yaml") -> STCSpec:
    """Load and parse the STC Declarative Specification."""
    spec_path = Path(path)
    
    if not spec_path.exists():
        raise FileNotFoundError(f"STC specification not found at {spec_path}")
    
    with open(spec_path, "r") as f:
        raw = yaml.safe_load(f)
    
    return STCSpec(
        version=raw.get("version", "0.0.0"),
        name=raw.get("name", "unnamed"),
        description=raw.get("description", ""),
        raw=raw,
    )


def validate_spec(spec: STCSpec) -> list[str]:
    """Validate the specification for required fields and consistency."""
    errors = []
    
    # Required top-level sections
    for section in ["stalwart", "trainer", "critic", "sentinel", "data_sovereignty", "audit"]:
        if section not in spec.raw:
            errors.append(f"Missing required section: {section}")
    
    # Stalwart must have a framework
    if not spec.stalwart.get("framework"):
        errors.append("stalwart.framework is required")
    
    # Trainer must have cost thresholds
    if not spec.trainer.get("cost_thresholds"):
        errors.append("trainer.cost_thresholds is required")
    
    # Critic must have guardrails
    if not spec.critic.get("guardrails"):
        errors.append("critic.guardrails is required")
    
    # Critic must have escalation
    if not spec.critic.get("escalation"):
        errors.append("critic.escalation is required")
    
    # Data sovereignty must have routing policy
    if not spec.data_sovereignty.get("routing_policy"):
        errors.append("data_sovereignty.routing_policy is required")
    
    # Auth keys must be defined for each persona
    for persona in ["stalwart", "trainer", "critic"]:
        section = spec.raw.get(persona, {})
        if not section.get("auth", {}).get("key_scope"):
            errors.append(f"{persona}.auth.key_scope is required")
    
    return errors


if __name__ == "__main__":
    spec = load_spec()
    errors = validate_spec(spec)
    
    if errors:
        print("Specification validation errors:")
        for e in errors:
            print(f"  - {e}")
    else:
        print(f"Specification valid: {spec.name} v{spec.version}")
        print(f"  Stalwart framework: {spec.stalwart.get('framework')}")
        print(f"  Trainer algorithm: {spec.trainer.get('optimization', {}).get('algorithm')}")
        print(f"  Critic guardrails: {len(spec.get_guardrails('output'))} output rails")
        print(f"  Data sovereignty: {spec.data_sovereignty.get('default_routing')}")
