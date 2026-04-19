"""
STC Framework — Ethical & Legal Risk Module
compliance/ethical_legal.py

Addresses ethical and legal risks for AI in financial services:

1. Bias & Fairness Monitor — disparate impact analysis across protected
   classes; fairness metrics tracked over time; structured bias testing.
2. IP Risk Scanner — detects potential copyright/trademark infringement
   in AI outputs before delivery.
3. AI Transparency & Consent — auto-attaches disclosure language to
   client-facing outputs; tracks consent status.
4. Privilege-Aware Routing — sends legal/privileged queries exclusively
   to local models to protect attorney-client privilege.
5. Fiduciary Fairness — ensures model quality doesn't vary by account
   size; prevents tiered service that breaches fiduciary duty.
6. Legal Hold Manager — freezes retention destruction for targeted
   records during litigation or regulatory investigation.
7. Legal Explainability — transforms lineage traces into plain-language
   narratives for legal proceedings.

Closes gaps identified in the ethical/legal risk assessment.
"""

import hashlib
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("stc.compliance.ethical_legal")


# ═══════════════════════════════════════════════════════════════════════════
# 1. BIAS & FAIRNESS MONITOR
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class FairnessMetric:
    metric_name: str
    group_a: str
    group_b: str
    value_a: float
    value_b: float
    ratio: float          # min/max — 1.0 is perfectly fair
    threshold: float      # Below this = potential disparate impact
    passed: bool

class BiasFairnessMonitor:
    """
    Monitors AI outputs for disparate impact across protected classes.
    Tracks fairness metrics over time for regulatory reporting.

    Protected classes (ECOA / Fair Housing / Title VII):
    Race, color, religion, national origin, sex, marital status,
    age, disability, familial status.
    """

    def __init__(self, disparate_impact_threshold: float = 0.80,
                 audit_callback: Optional[Callable] = None):
        self.threshold = disparate_impact_threshold  # 4/5ths rule
        self._metrics: List[FairnessMetric] = []
        self._response_quality: Dict[str, List[float]] = defaultdict(list)
        self._audit_cb = audit_callback

    def record_response_quality(self, query_context: str, quality_score: float,
                                 demographic_group: str = "unknown"):
        """Record response quality for a demographic group."""
        self._response_quality[demographic_group].append(quality_score)

    def evaluate_fairness(self) -> List[FairnessMetric]:
        """Evaluate fairness across all tracked demographic groups."""
        groups = list(self._response_quality.keys())
        metrics = []

        for i, g1 in enumerate(groups):
            for g2 in groups[i+1:]:
                scores_a = self._response_quality[g1]
                scores_b = self._response_quality[g2]
                if not scores_a or not scores_b:
                    continue

                avg_a = sum(scores_a) / len(scores_a)
                avg_b = sum(scores_b) / len(scores_b)
                ratio = min(avg_a, avg_b) / max(avg_a, avg_b) if max(avg_a, avg_b) > 0 else 1.0

                metric = FairnessMetric(
                    metric_name="response_quality_parity",
                    group_a=g1, group_b=g2,
                    value_a=round(avg_a, 4), value_b=round(avg_b, 4),
                    ratio=round(ratio, 4), threshold=self.threshold,
                    passed=ratio >= self.threshold,
                )
                metrics.append(metric)

        self._metrics.extend(metrics)
        return metrics

    def report(self) -> Dict[str, Any]:
        groups = dict(self._response_quality)
        return {
            "groups_tracked": len(groups),
            "total_observations": sum(len(v) for v in groups.values()),
            "fairness_evaluations": len(self._metrics),
            "disparate_impact_detected": sum(1 for m in self._metrics if not m.passed),
            "metrics": [
                {"groups": f"{m.group_a} vs {m.group_b}", "ratio": m.ratio,
                 "passed": m.passed}
                for m in self._metrics
            ],
        }


# ═══════════════════════════════════════════════════════════════════════════
# 2. IP RISK SCANNER
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class IPRiskFlag:
    risk_type: str       # copyright | trademark | trade_secret
    severity: str        # high | medium | low
    description: str
    offending_text: str
    recommendation: str

class IPRiskScanner:
    """
    Scans AI-generated output for potential IP infringement.
    Checks for: verbatim reproduction of copyrighted text,
    trademark usage, proprietary methodology references.
    """

    # Common trademarks in financial services
    TRADEMARKS = [
        "S&P 500", "Dow Jones", "MSCI", "Bloomberg", "Morningstar",
        "Russell 2000", "FTSE", "Lipper", "Moody's", "Fitch",
    ]

    PROPRIETARY_INDICATORS = [
        "proprietary model", "proprietary methodology", "confidential",
        "trade secret", "internal use only", "not for redistribution",
        "licensed data", "under license", "all rights reserved",
    ]

    def __init__(self, audit_callback: Optional[Callable] = None):
        self._flags: List[IPRiskFlag] = []
        self._audit_cb = audit_callback

    def scan(self, content: str) -> List[IPRiskFlag]:
        """Scan content for IP risk indicators."""
        flags = []
        content_lower = content.lower()

        # Check trademark usage without attribution
        for tm in self.TRADEMARKS:
            if tm.lower() in content_lower:
                # Check if there's an attribution nearby
                has_attribution = any(attr in content_lower for attr in
                                     ["®", "™", "source:", "according to", "per " + tm.lower()])
                if not has_attribution:
                    flags.append(IPRiskFlag(
                        "trademark", "low",
                        f"Trademark '{tm}' used without attribution",
                        tm, f"Add source attribution: 'Source: {tm}®'"))

        # Check proprietary content indicators
        for indicator in self.PROPRIETARY_INDICATORS:
            if indicator in content_lower:
                idx = content_lower.index(indicator)
                excerpt = content[max(0, idx-30):idx+len(indicator)+30]
                flags.append(IPRiskFlag(
                    "trade_secret", "high",
                    f"Proprietary content indicator: '{indicator}'",
                    excerpt, "Remove or replace with publicly available equivalent"))

        # Check for suspiciously long direct quotes (potential copyright)
        sentences = re.split(r'[.!?]', content)
        for sent in sentences:
            sent = sent.strip()
            if len(sent) > 200:  # Very long sentence may be verbatim copy
                flags.append(IPRiskFlag(
                    "copyright", "medium",
                    "Unusually long passage — may be verbatim reproduction",
                    sent[:100] + "...",
                    "Verify this is original analysis, not copied from source material"))

        self._flags.extend(flags)
        return flags


# ═══════════════════════════════════════════════════════════════════════════
# 3. AI TRANSPARENCY & CONSENT
# ═══════════════════════════════════════════════════════════════════════════

class TransparencyManager:
    """
    Manages AI disclosure requirements for client-facing outputs.
    Auto-attaches disclosure language based on output type and jurisdiction.
    """

    DISCLOSURES = {
        "general": "This content was generated with the assistance of artificial intelligence. It should be reviewed by a qualified professional before use.",
        "financial": "This analysis was prepared using AI-assisted tools. It is based on available data and should not be considered investment advice. Please consult with your financial advisor.",
        "regulatory": "AI-generated content. Subject to human review and supervisory oversight per FINRA Rule 3110.",
        "california": "This response was generated in whole or in part by an artificial intelligence system, as required by California law.",
    }

    def __init__(self):
        self._consent_registry: Dict[str, Dict] = {}
        self._disclosures_applied: int = 0

    def apply_disclosure(self, content: str, output_type: str = "general",
                         jurisdictions: Optional[List[str]] = None) -> str:
        """Attach appropriate disclosure language to content."""
        disclosures = [self.DISCLOSURES.get(output_type, self.DISCLOSURES["general"])]

        # Add jurisdiction-specific disclosures
        for j in (jurisdictions or []):
            if j.lower() in self.DISCLOSURES:
                disclosures.append(self.DISCLOSURES[j.lower()])

        # Deduplicate
        unique = list(dict.fromkeys(disclosures))
        disclosure_text = "\n".join(f"⚠️ {d}" for d in unique)

        self._disclosures_applied += 1
        return f"{content}\n\n---\n{disclosure_text}"

    def record_consent(self, client_id: str, consented: bool,
                       consent_type: str = "ai_assisted_advice",
                       consent_date: str = ""):
        """Record client consent for AI-assisted services."""
        self._consent_registry[client_id] = {
            "consented": consented,
            "type": consent_type,
            "date": consent_date or datetime.now(timezone.utc).isoformat(),
        }

    def check_consent(self, client_id: str) -> bool:
        """Check if client has consented to AI-assisted services."""
        entry = self._consent_registry.get(client_id)
        return entry["consented"] if entry else False

    def report(self) -> Dict[str, Any]:
        total = len(self._consent_registry)
        consented = sum(1 for v in self._consent_registry.values() if v["consented"])
        return {
            "total_clients": total, "consented": consented,
            "not_consented": total - consented,
            "disclosures_applied": self._disclosures_applied,
        }


# ═══════════════════════════════════════════════════════════════════════════
# 4. PRIVILEGE-AWARE ROUTING
# ═══════════════════════════════════════════════════════════════════════════

class PrivilegeRouter:
    """
    Routes queries involving attorney-client privilege or work product
    exclusively to local models to prevent privilege waiver.
    """

    PRIVILEGE_INDICATORS = [
        "attorney", "counsel", "legal advice", "privileged",
        "work product", "litigation", "lawsuit", "regulatory inquiry",
        "enforcement action", "subpoena", "discovery", "settlement",
        "legal strategy", "legal opinion", "outside counsel",
    ]

    def __init__(self, local_endpoint: str = "local/llama-3.1-70b"):
        self.local_endpoint = local_endpoint

    def evaluate(self, query: str, context: str = "") -> Dict[str, Any]:
        """Evaluate if query involves privileged content."""
        combined = f"{query} {context}".lower()
        triggers = [p for p in self.PRIVILEGE_INDICATORS if p in combined]

        if triggers:
            return {
                "privileged": True,
                "triggers": triggers,
                "routing": self.local_endpoint,
                "reason": f"Privilege indicators detected: {triggers[:3]}. "
                          f"Routing to local model to protect attorney-client privilege.",
            }
        return {"privileged": False, "triggers": [], "routing": None, "reason": "No privilege indicators"}


# ═══════════════════════════════════════════════════════════════════════════
# 5. FIDUCIARY FAIRNESS
# ═══════════════════════════════════════════════════════════════════════════

class FiduciaryFairnessChecker:
    """
    Ensures AI service quality doesn't vary by account size.
    Prevents tiered model quality that could breach fiduciary duty.
    """

    def __init__(self, audit_callback: Optional[Callable] = None):
        self._model_usage: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._audit_cb = audit_callback

    def record(self, account_tier: str, model_used: str):
        """Record which model was used for which account tier."""
        self._model_usage[account_tier][model_used] += 1

    def check_fairness(self) -> Dict[str, Any]:
        """Check if model quality is equitable across account tiers."""
        MODEL_QUALITY = {
            "claude-sonnet-4": 95, "gpt-4o": 93, "llama-3.1-70b": 85,
            "llama-3.1-8b": 75, "mistral-large": 88,
        }

        tier_quality = {}
        for tier, models in self._model_usage.items():
            total_queries = sum(models.values())
            weighted = sum(MODEL_QUALITY.get(m, 80) * count
                          for m, count in models.items())
            tier_quality[tier] = round(weighted / total_queries, 1) if total_queries else 0

        # Check for systematic quality differences
        if len(tier_quality) < 2:
            return {"fair": True, "tier_quality": tier_quality, "flags": []}

        min_q = min(tier_quality.values())
        max_q = max(tier_quality.values())
        gap = max_q - min_q

        flags = []
        if gap > 10:
            worst_tier = min(tier_quality, key=tier_quality.get)
            best_tier = max(tier_quality, key=tier_quality.get)
            flags.append(
                f"Quality gap: {best_tier}={max_q} vs {worst_tier}={min_q} "
                f"(gap={gap}). May indicate fiduciary fairness issue.")

        return {
            "fair": gap <= 10,
            "tier_quality": tier_quality,
            "quality_gap": gap,
            "flags": flags,
            "model_usage": {t: dict(m) for t, m in self._model_usage.items()},
        }


# ═══════════════════════════════════════════════════════════════════════════
# 6. LEGAL HOLD MANAGER
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class LegalHold:
    hold_id: str
    matter: str             # Litigation/investigation name
    scope: Dict[str, Any]   # {client_ids, date_range, topics, keywords}
    issued_by: str
    issued_at: str
    status: str = "active"  # active | released
    released_at: str = ""
    released_by: str = ""

class LegalHoldManager:
    """
    Manages litigation holds that freeze data destruction.
    When active, the retention manager must check holds before
    destroying any records.
    """

    def __init__(self, audit_callback: Optional[Callable] = None):
        self._holds: Dict[str, LegalHold] = {}
        self._audit_cb = audit_callback

    def issue_hold(self, matter: str, scope: Dict[str, Any],
                   issued_by: str) -> LegalHold:
        """Issue a legal hold. Freezes all matching record destruction."""
        hold_id = f"lh-{hashlib.sha256(f'{matter}{time.time()}'.encode()).hexdigest()[:10]}"
        hold = LegalHold(
            hold_id=hold_id, matter=matter, scope=scope,
            issued_by=issued_by,
            issued_at=datetime.now(timezone.utc).isoformat(),
        )
        self._holds[hold_id] = hold

        if self._audit_cb:
            self._audit_cb({
                "timestamp": hold.issued_at,
                "component": "compliance.legal_hold",
                "event_type": "legal_hold_issued",
                "details": {"hold_id": hold_id, "matter": matter,
                            "scope": scope, "issued_by": issued_by},
            })
        return hold

    def release_hold(self, hold_id: str, released_by: str):
        hold = self._holds.get(hold_id)
        if hold:
            hold.status = "released"
            hold.released_at = datetime.now(timezone.utc).isoformat()
            hold.released_by = released_by

    def check_destruction_allowed(self, record_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Check if a record can be destroyed (not covered by any hold)."""
        blocking_holds = []
        for hold in self._holds.values():
            if hold.status != "active":
                continue
            scope = hold.scope
            # Check client_id match
            if "client_ids" in scope and record_metadata.get("client_id") in scope["client_ids"]:
                blocking_holds.append(hold.hold_id)
                continue
            # Check date range
            if "date_range" in scope:
                rec_date = record_metadata.get("date", "")
                dr = scope["date_range"]
                if dr.get("start", "") <= rec_date <= dr.get("end", "9999"):
                    blocking_holds.append(hold.hold_id)
                    continue
            # Check keywords
            if "keywords" in scope:
                content = record_metadata.get("content", "").lower()
                if any(kw.lower() in content for kw in scope["keywords"]):
                    blocking_holds.append(hold.hold_id)

        return {
            "destruction_allowed": len(blocking_holds) == 0,
            "blocking_holds": blocking_holds,
            "active_holds": sum(1 for h in self._holds.values() if h.status == "active"),
        }

    def active_holds(self) -> List[Dict]:
        return [{"hold_id": h.hold_id, "matter": h.matter, "issued": h.issued_at,
                 "scope": h.scope}
                for h in self._holds.values() if h.status == "active"]


# ═══════════════════════════════════════════════════════════════════════════
# 7. LEGAL EXPLAINABILITY
# ═══════════════════════════════════════════════════════════════════════════

class LegalExplainabilityEngine:
    """
    Transforms technical lineage traces into plain-language narratives
    suitable for legal proceedings, regulatory examinations, or arbitration.
    """

    def explain(self, lineage: Dict[str, Any],
                prompt_execution: Optional[Dict] = None) -> str:
        """Generate a plain-language explanation of how an AI response was produced."""
        parts = []
        parts.append("EXPLANATION OF AI-GENERATED OUTPUT")
        parts.append("=" * 40)

        # Step 1: What was asked
        query = lineage.get("query", prompt_execution.get("variables_used", {}).get("query", "Unknown query") if prompt_execution else "Unknown query")
        parts.append(f"\n1. USER QUERY: A user submitted the following question to the AI system: \"{query}\"")

        # Step 2: What documents were used
        docs = lineage.get("source_documents", [])
        if docs:
            doc_names = [d.get("title", d.get("doc_id", "unknown")) for d in docs]
            parts.append(f"\n2. SOURCE DOCUMENTS: The system retrieved {len(docs)} document(s) "
                        f"to answer this question: {', '.join(doc_names)}. "
                        f"These documents were selected by similarity search against a database "
                        f"of {lineage.get('total_docs', 'pre-indexed')} financial documents.")

        # Step 3: What model was used
        gen = lineage.get("generation", {})
        model = gen.get("model_id", prompt_execution.get("model_id", "unknown") if prompt_execution else "unknown")
        provider = gen.get("provider", prompt_execution.get("provider", "unknown") if prompt_execution else "unknown")
        parts.append(f"\n3. AI MODEL: The question and retrieved documents were processed by "
                    f"the AI model '{model}' provided by {provider}. "
                    f"The model was instructed via a pre-approved prompt template "
                    f"(version: {gen.get('prompt_version', 'unknown')}) that explicitly prohibits "
                    f"investment advice and requires citation of sources.")

        # Step 4: What governance was applied
        val = lineage.get("validation", {})
        validators = val.get("validators_applied", [])
        verdict = val.get("verdict", "unknown")
        parts.append(f"\n4. GOVERNANCE CHECKS: Before delivery, the AI output was validated by "
                    f"{len(validators)} automated governance check(s): {', '.join(validators)}. "
                    f"The governance verdict was: {verdict.upper()}.")

        if val.get("violations"):
            parts.append(f"   Violations detected: {val['violations']}")

        # Step 5: Cost and performance
        if prompt_execution:
            parts.append(f"\n5. EXECUTION DETAILS: "
                        f"The AI used {prompt_execution.get('total_tokens', 'N/A')} tokens, "
                        f"cost approximately ${prompt_execution.get('estimated_cost', 0):.4f}, "
                        f"and completed in {prompt_execution.get('latency_ms', 'N/A')}ms. "
                        f"The execution is recorded under ID {prompt_execution.get('execution_id', 'N/A')} "
                        f"and can be fully reconstructed from the audit trail.")

        # Step 6: Limitations
        parts.append(f"\n6. LIMITATIONS: This AI system is designed to retrieve and summarize "
                    f"information from financial documents. It does not provide investment advice, "
                    f"make predictions, or guarantee accuracy. All outputs are subject to human "
                    f"supervisory review per the firm's compliance procedures.")

        return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# DEMO
# ═══════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("STC Ethical & Legal Risk Module — Demo")
    print("=" * 70)

    audit_log = []
    cb = lambda e: audit_log.append(e)

    # ── 1. Bias & Fairness ──
    print("\n" + "=" * 70)
    print("1. BIAS & FAIRNESS MONITOR")
    print("=" * 70)

    monitor = BiasFairnessMonitor()
    # Simulate response quality across demographic groups
    import random
    random.seed(42)
    for _ in range(50):
        monitor.record_response_quality("query", random.gauss(0.92, 0.03), "group_A")
        monitor.record_response_quality("query", random.gauss(0.91, 0.04), "group_B")
        monitor.record_response_quality("query", random.gauss(0.78, 0.05), "group_C")

    metrics = monitor.evaluate_fairness()
    for m in metrics:
        icon = "✓" if m.passed else "✗"
        print(f"  {icon} {m.group_a} vs {m.group_b}: ratio={m.ratio} (threshold={m.threshold}) {'PASS' if m.passed else 'DISPARATE IMPACT'}")

    # ── 2. IP Risk ──
    print("\n" + "=" * 70)
    print("2. IP RISK SCANNER")
    print("=" * 70)

    scanner = IPRiskScanner()
    content = ("ACME Corp outperformed the S&P 500 index, according to our proprietary model. "
               "The Dow Jones Industrial Average also showed strength. "
               "Based on licensed data from Bloomberg, revenue exceeded expectations.")
    flags = scanner.scan(content)
    for f in flags:
        print(f"  [{f.severity}] {f.risk_type}: {f.description}")
        print(f"    → {f.recommendation}")

    # ── 3. Transparency ──
    print("\n" + "=" * 70)
    print("3. AI TRANSPARENCY & CONSENT")
    print("=" * 70)

    transparency = TransparencyManager()
    output = "ACME Corp reported $5.2 billion in revenue for FY2024."
    disclosed = transparency.apply_disclosure(output, "financial", ["california"])
    print(f"  Original: {output}")
    print(f"  With disclosure:\n{disclosed}")

    transparency.record_consent("CLIENT-001", True)
    transparency.record_consent("CLIENT-002", False)
    print(f"\n  Consent check CLIENT-001: {transparency.check_consent('CLIENT-001')}")
    print(f"  Consent check CLIENT-002: {transparency.check_consent('CLIENT-002')}")

    # ── 4. Privilege Routing ──
    print("\n" + "=" * 70)
    print("4. PRIVILEGE-AWARE ROUTING")
    print("=" * 70)

    router = PrivilegeRouter()
    queries = [
        "What was ACME's revenue last quarter?",
        "Summarize outside counsel's legal opinion on the SEC inquiry.",
        "What are the litigation risks for our AI deployment?",
    ]
    for q in queries:
        result = router.evaluate(q)
        icon = "🔒" if result["privileged"] else "✓"
        routing = result["routing"] or "standard"
        print(f"  {icon} \"{q[:55]}...\"")
        print(f"    Privileged: {result['privileged']} | Route: {routing}")
        if result["triggers"]:
            print(f"    Triggers: {result['triggers']}")

    # ── 5. Fiduciary Fairness ──
    print("\n" + "=" * 70)
    print("5. FIDUCIARY FAIRNESS CHECK")
    print("=" * 70)

    checker = FiduciaryFairnessChecker()
    # Simulate: big accounts get premium model, small accounts get cheap model
    for _ in range(20):
        checker.record("tier_platinum_5M+", "claude-sonnet-4")
    for _ in range(30):
        checker.record("tier_gold_1M", "claude-sonnet-4")
    for _ in range(50):
        checker.record("tier_standard_50K", "llama-3.1-8b")

    fairness = checker.check_fairness()
    icon = "✓" if fairness["fair"] else "✗"
    print(f"  {icon} Fair: {fairness['fair']} | Quality gap: {fairness['quality_gap']}")
    print(f"  Tier quality: {fairness['tier_quality']}")
    for f in fairness["flags"]:
        print(f"  ⚠ {f}")
    print(f"  Model usage: {fairness['model_usage']}")

    # ── 6. Legal Hold ──
    print("\n" + "=" * 70)
    print("6. LEGAL HOLD MANAGER")
    print("=" * 70)

    hold_mgr = LegalHoldManager(audit_callback=cb)
    hold = hold_mgr.issue_hold(
        matter="SEC v. FirmName — Investigation 2026-001",
        scope={"client_ids": ["CLIENT-042", "CLIENT-099"],
               "date_range": {"start": "2025-01-01", "end": "2026-03-31"},
               "keywords": ["ACME", "insider", "material non-public"]},
        issued_by="General Counsel")
    print(f"  Hold issued: {hold.hold_id} | Matter: {hold.matter}")

    # Check if records can be destroyed
    allowed = hold_mgr.check_destruction_allowed(
        {"client_id": "CLIENT-042", "date": "2025-06-15", "content": "ACME quarterly review"})
    print(f"  Can destroy CLIENT-042 record? {allowed['destruction_allowed']} (blocked by: {allowed['blocking_holds']})")

    allowed2 = hold_mgr.check_destruction_allowed(
        {"client_id": "CLIENT-100", "date": "2025-06-15", "content": "General portfolio review"})
    print(f"  Can destroy CLIENT-100 record? {allowed2['destruction_allowed']}")

    # ── 7. Legal Explainability ──
    print("\n" + "=" * 70)
    print("7. LEGAL EXPLAINABILITY")
    print("=" * 70)

    explainer = LegalExplainabilityEngine()
    explanation = explainer.explain(
        lineage={
            "query": "What was ACME Corp's revenue in FY2024?",
            "source_documents": [{"title": "ACME Corp 10-K FY2024", "doc_id": "acme-10k"}],
            "generation": {"model_id": "claude-sonnet-4", "provider": "Anthropic",
                          "prompt_version": "financial_qa_v3.1"},
            "validation": {"validators_applied": ["numerical_accuracy", "hallucination_check", "scope_validator"],
                          "verdict": "pass", "violations": []},
        },
        prompt_execution={
            "execution_id": "pex-20260310-000147",
            "total_tokens": 2200, "estimated_cost": 0.0092, "latency_ms": 2100,
            "model_id": "claude-sonnet-4", "provider": "Anthropic",
            "variables_used": {"query": "What was ACME Corp's revenue in FY2024?"},
        }
    )
    print(explanation)

    print(f"\n▸ Audit events: {len(audit_log)}")
    print("\n" + "=" * 70)
    print("✓ Ethical & legal risk module demo complete")
    print("=" * 70)


if __name__ == "__main__":
    demo()
