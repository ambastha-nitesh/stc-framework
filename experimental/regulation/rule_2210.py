"""
STC Framework — FINRA Rule 2210 Compliance Module
compliance/rule_2210.py

Validates AI-generated communications against FINRA Rule 2210
(Communications with the Public) requirements:
  - Content classification (retail, correspondence, institutional)
  - Fair and balanced content check (no misleading claims)
  - Required disclosure verification (risks alongside benefits)
  - Prohibited content detection (guarantees, predictions, cherry-picking)
  - Principal pre-approval queue for retail communications
  - Recordkeeping integration (SEA 17a-4(b)(4))

Rule 2210 applies to ALL AI-generated content that reaches investors,
regardless of whether a human or technology tool produced it.

Integrates with: Critic (as an additional guardrail), Prompt Logger
(records review decisions), Audit Trail (compliance evidence).

Closes GAP-01 from the FINRA/NYDFS pressure test.
"""

import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("stc.compliance.rule_2210")


# ── Communication Types ─────────────────────────────────────────────────────

class CommunicationType(Enum):
    RETAIL = "retail"             # Distributed to > 25 retail investors in 30 days
    CORRESPONDENCE = "correspondence"  # Written comm to ≤ 25 retail investors in 30 days
    INSTITUTIONAL = "institutional"     # Only to institutional investors
    INTERNAL = "internal"              # Internal only — not subject to 2210

class ReviewDecision(Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"
    RETURNED_FOR_REVISION = "returned"
    AUTO_APPROVED = "auto_approved"    # Low-risk correspondence per firm procedures


# ── Violation Types ─────────────────────────────────────────────────────────

class ViolationType(Enum):
    GUARANTEE = "guarantee_of_results"
    PREDICTION = "market_prediction"
    CHERRY_PICK = "cherry_picked_performance"
    MISSING_RISK = "missing_risk_disclosure"
    MISLEADING = "misleading_statement"
    UNBALANCED = "unbalanced_presentation"
    PROMISSORY = "promissory_claim"
    TESTIMONIAL_NONCOMPLIANT = "testimonial_without_disclosure"
    MISSING_SOURCE = "missing_data_source"
    INVESTMENT_ADVICE = "investment_recommendation"


@dataclass
class ContentViolation:
    violation_type: ViolationType
    severity: str          # critical | high | medium
    description: str
    offending_text: str    # Excerpt triggering the violation
    rule_reference: str    # Specific 2210 subsection
    suggested_fix: str


@dataclass
class ReviewResult:
    communication_id: str
    timestamp: str
    communication_type: CommunicationType
    # Content analysis
    violations: List[ContentViolation]
    disclosure_check: Dict[str, bool]
    fair_balance_score: float        # 0.0 (one-sided) to 1.0 (balanced)
    # Verdict
    auto_approved: bool
    requires_principal: bool
    verdict: str                     # pass | fail | needs_review
    # Principal review
    principal_queue_id: Optional[str] = None
    principal_decision: Optional[ReviewDecision] = None
    principal_reviewer: str = ""
    principal_reviewed_at: str = ""
    # Metadata
    source_template: str = ""
    model_id: str = ""


# ── Content Analyzer ────────────────────────────────────────────────────────

class ContentAnalyzer:
    """
    Analyzes AI-generated content for Rule 2210 compliance.
    Uses pattern matching + heuristics. In production, augment with
    an LLM-based analyzer for nuanced detection.
    """

    # Prohibited patterns (case-insensitive)
    GUARANTEE_PATTERNS = [
        "guaranteed", "guarantee", "risk-free", "no risk", "certain to",
        "will definitely", "assured return", "cannot lose", "zero risk",
    ]

    PREDICTION_PATTERNS = [
        "will rise", "will fall", "will increase", "will decrease",
        "expect the stock to", "the market will", "prices will",
        "predicted to reach", "forecasted to hit",
    ]

    PROMISSORY_PATTERNS = [
        "you will earn", "you will receive", "returns of at least",
        "minimum return", "expected return of", "projected gains",
    ]

    ADVICE_PATTERNS = [
        "you should buy", "you should sell", "i recommend",
        "we recommend", "consider purchasing", "consider selling",
        "buy this", "sell this", "invest in",
    ]

    POSITIVE_INDICATORS = [
        "growth", "increase", "profit", "gain", "outperform",
        "strong", "excellent", "impressive", "robust", "exceeded",
    ]

    RISK_INDICATORS = [
        "risk", "loss", "decline", "volatility", "uncertainty",
        "downturn", "exposure", "caution", "may lose", "no guarantee",
    ]

    REQUIRED_DISCLOSURES = {
        "past_performance": "Past performance is not indicative of future results",
        "risk_warning": "Investing involves risk, including possible loss of principal",
        "source_citation": "Source or basis for claims must be identified",
    }

    def analyze(self, content: str, comm_type: CommunicationType,
                metadata: Optional[Dict] = None) -> ReviewResult:
        """Analyze content for Rule 2210 compliance."""
        now = datetime.now(timezone.utc).isoformat()
        comm_id = f"comm-{hashlib.sha256(f'{content[:100]}{now}'.encode()).hexdigest()[:12]}"
        content_lower = content.lower()

        violations = []

        # Check 1: Guarantees (Rule 2210(d)(1)(B))
        for pattern in self.GUARANTEE_PATTERNS:
            if pattern in content_lower:
                idx = content_lower.index(pattern)
                excerpt = content[max(0,idx-20):idx+len(pattern)+20]
                violations.append(ContentViolation(
                    ViolationType.GUARANTEE, "critical",
                    f"Guarantee language detected: '{pattern}'",
                    excerpt, "Rule 2210(d)(1)(B)",
                    "Remove guarantee language; add risk disclosure"))

        # Check 2: Predictions (Rule 2210(d)(1)(B))
        for pattern in self.PREDICTION_PATTERNS:
            if pattern in content_lower:
                idx = content_lower.index(pattern)
                excerpt = content[max(0,idx-20):idx+len(pattern)+20]
                violations.append(ContentViolation(
                    ViolationType.PREDICTION, "high",
                    f"Predictive language detected: '{pattern}'",
                    excerpt, "Rule 2210(d)(1)(B)",
                    "Replace prediction with conditional language ('may', 'could')"))

        # Check 3: Promissory claims (Rule 2210(d)(1)(F))
        for pattern in self.PROMISSORY_PATTERNS:
            if pattern in content_lower:
                idx = content_lower.index(pattern)
                excerpt = content[max(0,idx-20):idx+len(pattern)+20]
                violations.append(ContentViolation(
                    ViolationType.PROMISSORY, "critical",
                    f"Promissory claim detected: '{pattern}'",
                    excerpt, "Rule 2210(d)(1)(F)",
                    "Remove promissory language; cite historical data with disclaimers"))

        # Check 4: Investment advice (scope violation — should be caught by Critic too)
        for pattern in self.ADVICE_PATTERNS:
            if pattern in content_lower:
                idx = content_lower.index(pattern)
                excerpt = content[max(0,idx-20):idx+len(pattern)+20]
                violations.append(ContentViolation(
                    ViolationType.INVESTMENT_ADVICE, "critical",
                    f"Investment recommendation detected: '{pattern}'",
                    excerpt, "Rule 2210(d)(1)(A), Reg BI",
                    "Remove recommendation; present factual data only"))

        # Check 5: Fair and balanced (Rule 2210(d)(1)(A))
        positive_count = sum(1 for p in self.POSITIVE_INDICATORS if p in content_lower)
        risk_count = sum(1 for r in self.RISK_INDICATORS if r in content_lower)
        total = positive_count + risk_count
        balance_score = 1.0 if total == 0 else min(positive_count, risk_count) / max(positive_count, risk_count) if max(positive_count, risk_count) > 0 else 1.0

        if positive_count > 3 and risk_count == 0:
            violations.append(ContentViolation(
                ViolationType.UNBALANCED, "high",
                f"Content mentions {positive_count} positive terms but 0 risk terms",
                "", "Rule 2210(d)(1)(A)",
                "Add balanced risk language alongside benefits"))

        if positive_count > 2 * risk_count and total > 4:
            violations.append(ContentViolation(
                ViolationType.MISSING_RISK, "medium",
                f"Positive/risk ratio: {positive_count}:{risk_count} — may be unbalanced",
                "", "Rule 2210(d)(1)(A)",
                "Ensure risks and limitations are given comparable prominence to benefits"))

        # Check 6: Required disclosures
        disclosure_check = {}
        if any(p in content_lower for p in ["performance", "return", "growth rate"]):
            has_past_perf = any(d in content_lower for d in
                               ["past performance", "not indicative", "not a guarantee of future"])
            disclosure_check["past_performance"] = has_past_perf
            if not has_past_perf:
                violations.append(ContentViolation(
                    ViolationType.MISSING_SOURCE, "medium",
                    "Performance data referenced without past performance disclaimer",
                    "", "Rule 2210(d)(1)(D)",
                    "Add: 'Past performance is not indicative of future results'"))

        if any(p in content_lower for p in ["invest", "portfolio", "securities"]):
            has_risk_warn = any(d in content_lower for d in
                                ["risk", "loss of principal", "may lose"])
            disclosure_check["risk_warning"] = has_risk_warn

        # Determine verdict and routing
        critical_violations = [v for v in violations if v.severity == "critical"]
        high_violations = [v for v in violations if v.severity == "high"]

        if critical_violations:
            verdict = "fail"
            auto_approved = False
        elif high_violations:
            verdict = "needs_review"
            auto_approved = False
        elif violations:
            verdict = "needs_review" if comm_type == CommunicationType.RETAIL else "pass"
            auto_approved = comm_type != CommunicationType.RETAIL
        else:
            verdict = "pass"
            auto_approved = comm_type != CommunicationType.RETAIL

        # Retail communications always require principal pre-approval per 2210(b)(1)(A)
        requires_principal = comm_type == CommunicationType.RETAIL

        return ReviewResult(
            communication_id=comm_id, timestamp=now,
            communication_type=comm_type, violations=violations,
            disclosure_check=disclosure_check,
            fair_balance_score=round(balance_score, 2),
            auto_approved=auto_approved, requires_principal=requires_principal,
            verdict=verdict,
            source_template=metadata.get("template", "") if metadata else "",
            model_id=metadata.get("model", "") if metadata else "",
        )


# ── Principal Approval Queue ────────────────────────────────────────────────

class PrincipalApprovalQueue:
    """
    Queue for communications requiring principal review and approval.
    FINRA Rule 2210(b)(1)(A): retail communications must be approved
    by a registered principal before first use.
    """

    def __init__(self, audit_callback: Optional[Callable] = None):
        self._queue: Dict[str, ReviewResult] = {}
        self._audit_cb = audit_callback

    def submit(self, review: ReviewResult) -> str:
        """Submit a communication for principal review. Returns queue ID."""
        queue_id = f"pq-{review.communication_id}"
        review.principal_queue_id = queue_id
        review.principal_decision = ReviewDecision.PENDING
        self._queue[queue_id] = review

        if self._audit_cb:
            self._audit_cb({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "component": "compliance.rule_2210",
                "event_type": "principal_review_queued",
                "details": {
                    "queue_id": queue_id, "comm_id": review.communication_id,
                    "comm_type": review.communication_type.value,
                    "violations": len(review.violations),
                    "verdict": review.verdict,
                },
            })
        return queue_id

    def approve(self, queue_id: str, principal: str, notes: str = "") -> ReviewResult:
        """Principal approves the communication."""
        review = self._queue.get(queue_id)
        if not review:
            raise KeyError(f"Queue item not found: {queue_id}")
        review.principal_decision = ReviewDecision.APPROVED
        review.principal_reviewer = principal
        review.principal_reviewed_at = datetime.now(timezone.utc).isoformat()
        self._emit("principal_approved", queue_id, principal)
        return review

    def reject(self, queue_id: str, principal: str, reason: str) -> ReviewResult:
        """Principal rejects the communication."""
        review = self._queue.get(queue_id)
        if not review:
            raise KeyError(f"Queue item not found: {queue_id}")
        review.principal_decision = ReviewDecision.REJECTED
        review.principal_reviewer = principal
        review.principal_reviewed_at = datetime.now(timezone.utc).isoformat()
        self._emit("principal_rejected", queue_id, principal)
        return review

    def return_for_revision(self, queue_id: str, principal: str, feedback: str) -> ReviewResult:
        review = self._queue.get(queue_id)
        if not review:
            raise KeyError(f"Queue item not found: {queue_id}")
        review.principal_decision = ReviewDecision.RETURNED_FOR_REVISION
        review.principal_reviewer = principal
        review.principal_reviewed_at = datetime.now(timezone.utc).isoformat()
        self._emit("principal_returned", queue_id, principal)
        return review

    def pending_count(self) -> int:
        return sum(1 for r in self._queue.values()
                   if r.principal_decision == ReviewDecision.PENDING)

    def pending_items(self) -> List[Dict[str, Any]]:
        return [
            {"queue_id": r.principal_queue_id, "comm_id": r.communication_id,
             "type": r.communication_type.value, "violations": len(r.violations),
             "verdict": r.verdict, "submitted": r.timestamp}
            for r in self._queue.values()
            if r.principal_decision == ReviewDecision.PENDING
        ]

    def _emit(self, event_type, queue_id, principal):
        if self._audit_cb:
            self._audit_cb({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "component": "compliance.rule_2210",
                "event_type": event_type,
                "details": {"queue_id": queue_id, "principal": principal},
            })


# ── Rule 2210 Compliance Engine ─────────────────────────────────────────────

class Rule2210Engine:
    """
    Full Rule 2210 compliance engine for AI-generated communications.

    Usage:
        engine = Rule2210Engine()

        # Every AI response that may reach investors:
        result = engine.review(content, CommunicationType.RETAIL, metadata)

        if result.verdict == "fail":
            # Block content — violations must be fixed
        elif result.requires_principal:
            # Route to principal approval queue
            queue_id = engine.submit_for_approval(result)
        else:
            # Content may be delivered
    """

    def __init__(self, audit_callback: Optional[Callable] = None):
        self.analyzer = ContentAnalyzer()
        self.approval_queue = PrincipalApprovalQueue(audit_callback)
        self._audit_cb = audit_callback
        self._reviews: List[ReviewResult] = []

    def review(self, content: str, comm_type: CommunicationType,
               metadata: Optional[Dict] = None) -> ReviewResult:
        """Review content for Rule 2210 compliance."""
        result = self.analyzer.analyze(content, comm_type, metadata)
        self._reviews.append(result)
        return result

    def submit_for_approval(self, result: ReviewResult) -> str:
        """Submit a reviewed communication for principal approval."""
        return self.approval_queue.submit(result)

    def compliance_report(self) -> Dict[str, Any]:
        """Generate compliance report for regulatory examination."""
        total = len(self._reviews)
        by_verdict = defaultdict(int)
        by_type = defaultdict(int)
        by_violation = defaultdict(int)

        for r in self._reviews:
            by_verdict[r.verdict] += 1
            by_type[r.communication_type.value] += 1
            for v in r.violations:
                by_violation[v.violation_type.value] += 1

        return {
            "generated": datetime.now(timezone.utc).isoformat(),
            "total_reviews": total,
            "by_verdict": dict(by_verdict),
            "by_communication_type": dict(by_type),
            "violation_summary": dict(by_violation),
            "principal_queue_pending": self.approval_queue.pending_count(),
            "avg_balance_score": round(sum(r.fair_balance_score for r in self._reviews) / total, 2) if total else 0,
        }


# ── Demo ────────────────────────────────────────────────────────────────────

def demo():
    print("=" * 70)
    print("STC FINRA Rule 2210 Compliance Engine — Demo")
    print("=" * 70)

    audit_log = []
    engine = Rule2210Engine(audit_callback=lambda e: audit_log.append(e))

    test_cases = [
        ("Good response (compliant)",
         CommunicationType.CORRESPONDENCE,
         "Based on ACME Corp's 10-K filing, the company reported revenue of $5.2 billion in FY2024, "
         "representing a 12% year-over-year increase. The company noted risks including market volatility "
         "and regulatory uncertainty. Past performance is not indicative of future results."),

        ("Retail with guarantee language (violation)",
         CommunicationType.RETAIL,
         "ACME Corp has shown incredible growth with guaranteed returns for investors. "
         "The stock is risk-free and will definitely outperform the market. "
         "You will earn at least 15% returns by investing now."),

        ("Unbalanced presentation (violation)",
         CommunicationType.RETAIL,
         "ACME Corp demonstrated extraordinary growth, excellent performance, impressive revenue gains, "
         "strong profitability, and robust market position. The company outperformed all peers with "
         "record-breaking results across every metric."),

        ("Investment advice (violation)",
         CommunicationType.CORRESPONDENCE,
         "Based on the financial analysis, I recommend purchasing ACME shares. "
         "You should buy at least 100 shares while the price is favorable. "
         "Consider selling your existing holdings in XYZ Corp."),

        ("Institutional (lower bar)",
         CommunicationType.INSTITUTIONAL,
         "ACME Corp revenue growth of 12% exceeded analyst consensus of 8%. "
         "The company's operating margin expansion was driven by cost efficiencies."),
    ]

    for name, comm_type, content in test_cases:
        print(f"\n▸ Test: {name} ({comm_type.value})")
        result = engine.review(content, comm_type, {"template": "financial_qa_v3.1", "model": "claude-sonnet-4"})

        icon = {"pass": "✓", "fail": "✗", "needs_review": "⚠"}[result.verdict]
        print(f"  {icon} Verdict: {result.verdict}")
        print(f"  Balance score: {result.fair_balance_score}")
        print(f"  Violations: {len(result.violations)}")
        for v in result.violations:
            print(f"    [{v.severity}] {v.violation_type.value}: {v.description}")
            print(f"      Rule: {v.rule_reference} | Fix: {v.suggested_fix[:60]}...")
        print(f"  Disclosures: {result.disclosure_check}")
        print(f"  Requires principal: {result.requires_principal}")

        if result.requires_principal and result.verdict != "fail":
            queue_id = engine.submit_for_approval(result)
            print(f"  Queued for principal: {queue_id}")

    # Principal approval
    print("\n▸ Principal review queue:")
    print(f"  Pending: {engine.approval_queue.pending_count()}")
    for item in engine.approval_queue.pending_items():
        print(f"  [{item['queue_id']}] {item['type']}: {item['violations']} violations, verdict={item['verdict']}")

    # Approve the unbalanced one after revision
    pending = engine.approval_queue.pending_items()
    if pending:
        engine.approval_queue.reject(pending[0]["queue_id"], "Jane Smith (Principal)", "Contains guarantee language")
        print(f"\n  Principal rejected: {pending[0]['queue_id']}")

    # Compliance report
    print("\n▸ Compliance report:")
    report = engine.compliance_report()
    print(f"  Total reviews: {report['total_reviews']}")
    print(f"  By verdict: {report['by_verdict']}")
    print(f"  By type: {report['by_communication_type']}")
    print(f"  Violations: {report['violation_summary']}")
    print(f"  Avg balance: {report['avg_balance_score']}")

    print(f"\n▸ Audit events: {len(audit_log)}")
    print("\n" + "=" * 70)
    print("✓ Rule 2210 compliance engine demo complete")
    print("=" * 70)


if __name__ == "__main__":
    demo()
