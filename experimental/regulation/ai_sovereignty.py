"""
STC Framework — AI Sovereignty Module
compliance/ai_sovereignty.py

US-focused AI sovereignty enforcement for financial services:

1. Model Origin Policy — geopolitical risk scoring for model selection;
   blocks or flags models from sanctioned/adversarial origins.
2. Query Pattern Protection — detects and mitigates metadata leakage
   through inference query patterns to external LLM providers.
3. State AI Compliance Matrix — tracks requirements across US states
   (Colorado AI Act, California TFAIA, Texas RAIGA, Illinois BIPA, etc.)
   with per-state compliance status.
4. Software Bill of Materials (SBOM) — dependency provenance tracking
   with country-of-origin risk flags.
5. Inference Jurisdiction Enforcement — ensures inference runs on
   hardware in approved US jurisdictions when required.

Addresses gaps: model sovereignty, training data sovereignty, inference
sovereignty, regulatory sovereignty, supply chain sovereignty.
"""

import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("stc.compliance.sovereignty")


# ═══════════════════════════════════════════════════════════════════════════
# 1. MODEL ORIGIN POLICY
# ═══════════════════════════════════════════════════════════════════════════

class OriginRisk(Enum):
    TRUSTED = "trusted"           # US, UK, EU — allied nations
    CAUTIOUS = "cautious"         # Requires review but not blocked
    RESTRICTED = "restricted"     # Blocked unless explicit exception
    SANCTIONED = "sanctioned"     # Always blocked — sanctioned entity

@dataclass
class ModelOriginProfile:
    model_id: str
    developer_org: str
    headquarters_country: str
    training_data_jurisdiction: str  # known | unknown | mixed
    open_source: bool
    origin_risk: OriginRisk
    notes: str = ""

# Known model provenance database
MODEL_ORIGINS = {
    "anthropic/claude": ModelOriginProfile("anthropic/claude", "Anthropic", "US", "known", False, OriginRisk.TRUSTED),
    "openai/gpt": ModelOriginProfile("openai/gpt", "OpenAI", "US", "known", False, OriginRisk.TRUSTED),
    "google/gemini": ModelOriginProfile("google/gemini", "Google DeepMind", "US/UK", "known", False, OriginRisk.TRUSTED),
    "meta/llama": ModelOriginProfile("meta/llama", "Meta", "US", "known", True, OriginRisk.TRUSTED),
    "mistral/mistral": ModelOriginProfile("mistral/mistral", "Mistral AI", "France", "known", True, OriginRisk.TRUSTED),
    "cohere/command": ModelOriginProfile("cohere/command", "Cohere", "Canada", "known", False, OriginRisk.TRUSTED),
    "deepseek/deepseek": ModelOriginProfile("deepseek/deepseek", "DeepSeek", "China", "unknown", True, OriginRisk.RESTRICTED,
                                             "PRC-headquartered; training data provenance unknown; potential state influence"),
    "alibaba/qwen": ModelOriginProfile("alibaba/qwen", "Alibaba Cloud", "China", "unknown", True, OriginRisk.RESTRICTED,
                                        "PRC state-adjacent enterprise; unclear training data governance"),
    "baichuan/baichuan": ModelOriginProfile("baichuan/baichuan", "Baichuan Inc", "China", "unknown", True, OriginRisk.RESTRICTED),
    "01ai/yi": ModelOriginProfile("01ai/yi", "01.AI", "China", "unknown", True, OriginRisk.CAUTIOUS,
                                   "Founded by Kai-Fu Lee; Singapore HQ but PRC R&D operations"),
}


class ModelOriginPolicy:
    """
    Enforces model origin restrictions based on geopolitical risk.
    Integrates with the risk-adjusted optimizer to add origin risk
    as a factor in model selection.
    """

    def __init__(self, blocked_countries: Optional[Set[str]] = None,
                 require_known_training_data: bool = True,
                 audit_callback: Optional[Callable] = None):
        self.blocked_countries = blocked_countries or {"China", "Russia", "Iran", "North Korea"}
        self.require_known_training = require_known_training_data
        self._origins = dict(MODEL_ORIGINS)
        self._audit_cb = audit_callback
        self._decisions: List[Dict] = []

    def register_model(self, profile: ModelOriginProfile):
        self._origins[profile.model_id] = profile

    def evaluate(self, model_id: str) -> Dict[str, Any]:
        """Evaluate a model's origin risk. Returns risk assessment."""
        # Match by prefix (e.g., "anthropic/claude-sonnet-4" matches "anthropic/claude")
        profile = None
        for key, p in self._origins.items():
            if model_id.startswith(key) or key in model_id.lower():
                profile = p
                break

        if not profile:
            # Unknown model — flag for review
            result = {
                "model_id": model_id, "origin_risk": "unknown",
                "allowed": False, "reason": "Model not in origin database — requires manual review",
                "flags": ["UNKNOWN_ORIGIN"],
            }
        elif profile.origin_risk == OriginRisk.SANCTIONED:
            result = {
                "model_id": model_id, "origin_risk": "sanctioned",
                "allowed": False, "reason": f"Sanctioned entity: {profile.developer_org} ({profile.headquarters_country})",
                "flags": ["SANCTIONED"],
            }
        elif profile.origin_risk == OriginRisk.RESTRICTED:
            result = {
                "model_id": model_id, "origin_risk": "restricted",
                "allowed": False,
                "reason": f"Restricted origin: {profile.developer_org} ({profile.headquarters_country}). {profile.notes}",
                "flags": ["RESTRICTED_ORIGIN", "GEOPOLITICAL_RISK"],
            }
        elif profile.origin_risk == OriginRisk.CAUTIOUS:
            result = {
                "model_id": model_id, "origin_risk": "cautious",
                "allowed": True,  # Allowed but flagged
                "reason": f"Cautious: {profile.developer_org} ({profile.headquarters_country}). {profile.notes}",
                "flags": ["REVIEW_RECOMMENDED"],
            }
        else:
            flags = []
            if self.require_known_training and profile.training_data_jurisdiction == "unknown":
                flags.append("UNKNOWN_TRAINING_DATA")
            result = {
                "model_id": model_id, "origin_risk": "trusted",
                "allowed": True, "reason": f"Trusted: {profile.developer_org} ({profile.headquarters_country})",
                "flags": flags,
            }

        result["profile"] = profile.__dict__ if profile else None
        self._decisions.append(result)

        if self._audit_cb:
            self._audit_cb({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "component": "compliance.sovereignty.model_origin",
                "event_type": "model_origin_evaluated",
                "details": {"model_id": model_id, "risk": result["origin_risk"],
                            "allowed": result["allowed"], "flags": result["flags"]},
            })

        return result


# ═══════════════════════════════════════════════════════════════════════════
# 2. QUERY PATTERN PROTECTION
# ═══════════════════════════════════════════════════════════════════════════

class QueryPatternProtector:
    """
    Detects and mitigates metadata leakage through inference patterns.
    Even with PII masked, the PATTERN of queries reveals intelligence:
    - Querying about a specific company = potential M&A interest
    - Querying about regulations = potential compliance issue
    - Volume spikes about a sector = strategic repositioning
    """

    def __init__(self, sensitivity_window_hours: int = 24,
                 entity_threshold: int = 10,
                 audit_callback: Optional[Callable] = None):
        self.window_hours = sensitivity_window_hours
        self.entity_threshold = entity_threshold
        self._entity_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._audit_cb = audit_callback

    def record_query(self, provider: str, query: str, entities_mentioned: List[str]):
        """Record a query and check for pattern concentration."""
        for entity in entities_mentioned:
            self._entity_counts[provider][entity.lower()] += 1

    def check_pattern_risk(self, provider: str) -> List[Dict[str, Any]]:
        """Check if query patterns to a provider reveal strategic intelligence."""
        risks = []
        counts = self._entity_counts.get(provider, {})
        for entity, count in counts.items():
            if count >= self.entity_threshold:
                risks.append({
                    "provider": provider, "entity": entity, "query_count": count,
                    "risk": "PATTERN_CONCENTRATION",
                    "description": f"Entity '{entity}' queried {count} times to {provider} — "
                                   f"may reveal strategic interest to provider",
                    "mitigation": "Distribute queries across providers or use local model for concentrated research",
                })

        if self._audit_cb and risks:
            self._audit_cb({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "component": "compliance.sovereignty.query_pattern",
                "event_type": "pattern_risk_detected",
                "details": {"provider": provider, "risks": len(risks)},
            })
        return risks

    def recommend_routing(self, query: str, entities: List[str],
                          available_providers: List[str]) -> Dict[str, Any]:
        """Recommend which provider should handle this query based on pattern risk."""
        # Check if any entity is already concentrated at a specific provider
        for provider in available_providers:
            for entity in entities:
                count = self._entity_counts.get(provider, {}).get(entity.lower(), 0)
                if count >= self.entity_threshold:
                    alt = [p for p in available_providers if p != provider]
                    return {
                        "recommended_provider": alt[0] if alt else "local",
                        "reason": f"Entity '{entity}' concentrated at {provider} ({count} queries). Routing to alternate.",
                        "pattern_risk": True,
                    }
        return {"recommended_provider": available_providers[0], "reason": "No pattern concentration", "pattern_risk": False}


# ═══════════════════════════════════════════════════════════════════════════
# 3. STATE AI COMPLIANCE MATRIX
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class StateAILaw:
    state: str
    law_name: str
    effective_date: str
    status: str           # active | delayed | challenged | preempted
    key_requirements: List[str]
    stc_coverage: str     # covered | partial | gap
    notes: str = ""

STATE_AI_LAWS = [
    StateAILaw("Colorado", "Colorado AI Act (SB 24-205)", "2026-06-30", "delayed",
               ["Algorithmic discrimination prevention", "Impact assessments for high-risk AI",
                "Consumer disclosures", "Developer/deployer reasonable care"],
               "partial", "Delayed to June 2026; federal preemption challenge pending. Critic bias detection provides partial coverage."),
    StateAILaw("California", "CA AI Transparency Act (SB 942)", "2026-08-02", "active",
               ["AI content watermarking", "Detection tools for AI-generated content",
                "Manifest and latent disclosures"],
               "gap", "Requires AI output watermarking — STC does not currently embed watermarks in responses."),
    StateAILaw("California", "CA Companion Chatbots Act (SB 243)", "2026-01-01", "active",
               ["Chatbot disclosure requirements", "Safety protocols for harmful content",
                "Minor protections"],
               "covered", "Critic blocks harmful content; scope validator enforces boundaries; session isolation protects minors."),
    StateAILaw("Texas", "TX Responsible AI Governance Act (RAIGA)", "2026-01-01", "active",
               ["AI governance framework", "Risk assessment", "Transparency requirements"],
               "covered", "STC's governance framework, risk assessment methodology, and audit trail exceed RAIGA requirements."),
    StateAILaw("Illinois", "IL AI Video Interview Act (HB 3773)", "active", "active",
               ["Consent before AI analysis in hiring", "Data destruction requirements",
                "Anti-discrimination provisions"],
               "not_applicable", "STC is not used in hiring context. If deployed for HR, additional module needed."),
    StateAILaw("New York City", "NYC Local Law 144", "active", "active",
               ["Bias audit for automated employment decision tools", "Public disclosure of audit results"],
               "not_applicable", "STC is not used in employment decisions."),
    StateAILaw("Utah", "UT AI Policy Act", "active", "active",
               ["AI disclosure requirements", "Consumer protection", "Safe harbor provisions"],
               "covered", "Critic + audit trail provide disclosure capability and documentation."),
    StateAILaw("Federal", "EO 14365 (Dec 2025): National AI Policy Framework", "2025-12-11", "active",
               ["Federal preemption of state AI laws", "AI Litigation Task Force",
                "Commerce Dept evaluation of state laws (due March 2026)", "FTC AI policy statement"],
               "monitoring", "No direct compliance requirement; STC monitors for federal preemption outcomes."),
]


class StateComplianceMatrix:
    """Tracks state-by-state AI law compliance for multi-state operations."""

    def __init__(self):
        self._laws = list(STATE_AI_LAWS)
        self._overrides: Dict[str, str] = {}

    def get_applicable(self, states: List[str]) -> List[Dict[str, Any]]:
        """Get applicable laws for states where the firm operates."""
        applicable = []
        for law in self._laws:
            if law.state in states or law.state == "Federal":
                applicable.append({
                    "state": law.state, "law": law.law_name,
                    "effective": law.effective_date, "status": law.status,
                    "requirements": law.key_requirements,
                    "stc_coverage": law.stc_coverage, "notes": law.notes,
                })
        return applicable

    def compliance_summary(self, states: List[str]) -> Dict[str, Any]:
        applicable = self.get_applicable(states)
        by_coverage = defaultdict(int)
        for a in applicable:
            by_coverage[a["stc_coverage"]] += 1
        return {
            "states_assessed": states,
            "applicable_laws": len(applicable),
            "coverage": dict(by_coverage),
            "gaps": [a for a in applicable if a["stc_coverage"] == "gap"],
            "partial": [a for a in applicable if a["stc_coverage"] == "partial"],
        }


# ═══════════════════════════════════════════════════════════════════════════
# 4. INFERENCE JURISDICTION ENFORCEMENT
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class InferenceEndpoint:
    endpoint_id: str
    provider: str
    region: str               # aws:us-east-1, local:on-prem, etc.
    country: str
    jurisdiction: str         # US_CONUS | US_GOVCLOUD | EU | OTHER
    fips_compliant: bool
    fedramp_authorized: bool

APPROVED_JURISDICTIONS = {"US_CONUS", "US_GOVCLOUD"}

class InferenceJurisdictionEnforcer:
    """Ensures inference runs in approved US jurisdictions."""

    def __init__(self, approved: Optional[Set[str]] = None,
                 audit_callback: Optional[Callable] = None):
        self.approved = approved or APPROVED_JURISDICTIONS
        self._endpoints: Dict[str, InferenceEndpoint] = {}
        self._audit_cb = audit_callback

    def register_endpoint(self, ep: InferenceEndpoint):
        self._endpoints[ep.endpoint_id] = ep

    def check(self, endpoint_id: str) -> Dict[str, Any]:
        ep = self._endpoints.get(endpoint_id)
        if not ep:
            return {"endpoint_id": endpoint_id, "allowed": False, "reason": "Unknown endpoint"}

        allowed = ep.jurisdiction in self.approved
        return {
            "endpoint_id": endpoint_id, "provider": ep.provider,
            "region": ep.region, "jurisdiction": ep.jurisdiction,
            "allowed": allowed,
            "fips": ep.fips_compliant, "fedramp": ep.fedramp_authorized,
            "reason": "Approved jurisdiction" if allowed else f"Jurisdiction {ep.jurisdiction} not in approved list",
        }

    def filter_endpoints(self, endpoint_ids: List[str]) -> List[str]:
        """Return only endpoints in approved jurisdictions."""
        return [eid for eid in endpoint_ids
                if self.check(eid).get("allowed", False)]


# ═══════════════════════════════════════════════════════════════════════════
# DEMO
# ═══════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("STC AI Sovereignty Module — Demo")
    print("=" * 70)

    audit_log = []
    cb = lambda e: audit_log.append(e)

    # ── 1. Model Origin Policy ──
    print("\n" + "=" * 70)
    print("1. MODEL ORIGIN POLICY")
    print("=" * 70)

    policy = ModelOriginPolicy(audit_callback=cb)

    models = [
        "anthropic/claude-sonnet-4",
        "openai/gpt-4o",
        "meta/llama-3.1-8b",
        "mistral/mistral-large",
        "deepseek/deepseek-v3",
        "alibaba/qwen-2.5-72b",
        "unknown-org/mystery-model",
    ]

    for model in models:
        result = policy.evaluate(model)
        icon = "✓" if result["allowed"] else "✗"
        print(f"  {icon} {model}: {result['origin_risk']} — {result['reason'][:70]}")
        if result["flags"]:
            print(f"    Flags: {result['flags']}")

    # ── 2. Query Pattern Protection ──
    print("\n" + "=" * 70)
    print("2. QUERY PATTERN PROTECTION")
    print("=" * 70)

    protector = QueryPatternProtector(entity_threshold=5, audit_callback=cb)

    # Simulate concentrated querying about a company to one provider
    for i in range(12):
        protector.record_query("anthropic", f"What is ACME Corp revenue Q{i%4+1}?", ["ACME Corp"])
    for i in range(3):
        protector.record_query("anthropic", f"What is XYZ Inc revenue?", ["XYZ Inc"])

    risks = protector.check_pattern_risk("anthropic")
    for r in risks:
        print(f"  ⚠ {r['risk']}: {r['description']}")
        print(f"    Mitigation: {r['mitigation']}")

    # Routing recommendation
    rec = protector.recommend_routing(
        "What is ACME Corp's latest filing?", ["ACME Corp"],
        ["anthropic", "bedrock", "local"])
    print(f"\n  Routing recommendation: {rec['recommended_provider']} — {rec['reason']}")

    # ── 3. State Compliance Matrix ──
    print("\n" + "=" * 70)
    print("3. STATE AI COMPLIANCE MATRIX")
    print("=" * 70)

    matrix = StateComplianceMatrix()
    # LPL operates across all US states but key ones:
    states = ["California", "Colorado", "Texas", "New York City", "Utah", "Illinois"]
    summary = matrix.compliance_summary(states)

    print(f"  States assessed: {summary['states_assessed']}")
    print(f"  Applicable laws: {summary['applicable_laws']}")
    print(f"  Coverage: {summary['coverage']}")

    if summary["gaps"]:
        print(f"\n  GAPS:")
        for g in summary["gaps"]:
            print(f"    ✗ {g['state']} — {g['law']}: {g['notes'][:70]}...")

    if summary["partial"]:
        print(f"\n  PARTIAL:")
        for p in summary["partial"]:
            print(f"    ⚠ {p['state']} — {p['law']}: {p['notes'][:70]}...")

    laws = matrix.get_applicable(states)
    print(f"\n  All applicable laws:")
    for l in laws:
        icon = {"covered":"✓","partial":"⚠","gap":"✗","not_applicable":"—","monitoring":"👁"}[l["stc_coverage"]]
        print(f"    {icon} [{l['status']}] {l['state']}: {l['law']} (eff: {l['effective']})")

    # ── 4. Inference Jurisdiction ──
    print("\n" + "=" * 70)
    print("4. INFERENCE JURISDICTION ENFORCEMENT")
    print("=" * 70)

    enforcer = InferenceJurisdictionEnforcer(audit_callback=cb)
    endpoints = [
        InferenceEndpoint("bedrock-us-east-1", "AWS Bedrock", "us-east-1", "US", "US_CONUS", True, True),
        InferenceEndpoint("bedrock-eu-west-1", "AWS Bedrock", "eu-west-1", "Ireland", "EU", True, False),
        InferenceEndpoint("local-dc1", "Ollama", "on-prem-dc1", "US", "US_CONUS", True, False),
        InferenceEndpoint("openai-global", "OpenAI", "global", "US", "US_CONUS", False, False),
        InferenceEndpoint("azure-usgov", "Azure OpenAI", "usgovvirginia", "US", "US_GOVCLOUD", True, True),
    ]
    for ep in endpoints:
        enforcer.register_endpoint(ep)

    for ep in endpoints:
        result = enforcer.check(ep.endpoint_id)
        icon = "✓" if result["allowed"] else "✗"
        fips = " FIPS" if result["fips"] else ""
        fedramp = " FedRAMP" if result["fedramp"] else ""
        print(f"  {icon} {ep.endpoint_id}: {ep.jurisdiction}{fips}{fedramp} — {result['reason']}")

    approved = enforcer.filter_endpoints([ep.endpoint_id for ep in endpoints])
    print(f"\n  Approved for inference: {approved}")
    blocked = [ep.endpoint_id for ep in endpoints if ep.endpoint_id not in approved]
    print(f"  Blocked: {blocked}")

    print(f"\n▸ Audit events: {len(audit_log)}")

    print("\n" + "=" * 70)
    print("✓ AI sovereignty module demo complete")
    print("=" * 70)


if __name__ == "__main__":
    demo()
