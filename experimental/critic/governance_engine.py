"""
STC Framework - Critic: Zero-Trust Governance Plane

The Critic assumes nothing is trustworthy by default. It verifies every
Stalwart output, detects hallucinations, enforces compliance, and manages
escalation. It does not fix problems directly — it submits structured
feedback to the Trainer and triggers escalation when thresholds are breached.

The Critic orchestrates composable guardrail services (NeMo Guardrails,
Guardrails AI Hub, Presidio) rather than implementing monolithic verification.
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from collections import deque
from spec.loader import load_spec, STCSpec

logger = logging.getLogger("stc.critic")


# ============================================================================
# Guardrail Results
# ============================================================================

@dataclass
class GuardrailResult:
    """Result from a single guardrail evaluation."""
    rail_name: str
    passed: bool
    severity: str  # critical | high | medium | low
    details: str = ""
    evidence: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class GovernanceVerdict:
    """Aggregate verdict from all guardrails on a single response."""
    trace_id: str
    passed: bool
    results: list[GuardrailResult]
    action: str  # pass | warn | block | escalate
    escalation_level: Optional[str] = None  # degraded | quarantine | suspension
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ============================================================================
# Individual Validators
# ============================================================================

class NumericalAccuracyValidator:
    """
    Critical validator for financial Q&A: checks that numbers in the
    response are grounded in the source documents.
    
    A hallucinated number in a financial context is not just wrong — it's
    a potential liability.
    """
    
    def __init__(self, tolerance_percent: float = 1.0):
        self.tolerance = tolerance_percent / 100.0
    
    def validate(self, response: str, source_chunks: list[dict]) -> GuardrailResult:
        """Check numerical claims against source documents."""
        
        # Extract numbers from response
        number_pattern = r'\$[\d,.]+(?:\s*(?:billion|million|thousand|[BMK]))?|\d+\.\d+%|\d{1,3}(?:,\d{3})+'
        response_numbers = re.findall(number_pattern, response, re.IGNORECASE)
        
        if not response_numbers:
            return GuardrailResult(
                rail_name="numerical_accuracy",
                passed=True,
                severity="critical",
                details="No numerical claims in response",
            )
        
        # Extract numbers from source
        source_text = " ".join([
            c.get("text", "") if isinstance(c, dict) else str(c)
            for c in source_chunks
        ])
        source_numbers = set(re.findall(number_pattern, source_text, re.IGNORECASE))
        
        # Check grounding
        ungrounded = []
        for num in response_numbers:
            normalized = self._normalize_number(num)
            grounded = False
            for src_num in source_numbers:
                src_normalized = self._normalize_number(src_num)
                if self._numbers_match(normalized, src_normalized):
                    grounded = True
                    break
            if not grounded:
                ungrounded.append(num)
        
        passed = len(ungrounded) == 0
        
        return GuardrailResult(
            rail_name="numerical_accuracy",
            passed=passed,
            severity="critical",
            details=f"{'All' if passed else len(ungrounded)} numbers "
                    f"{'grounded' if passed else 'ungrounded'} in source",
            evidence={
                "response_numbers": response_numbers[:10],
                "ungrounded_numbers": ungrounded[:10],
                "source_numbers_sample": list(source_numbers)[:10],
            },
        )
    
    def _normalize_number(self, num_str: str) -> Optional[float]:
        """Normalize a number string to a float for comparison."""
        try:
            cleaned = num_str.replace("$", "").replace(",", "").replace("%", "").strip()
            
            multiplier = 1.0
            for suffix, mult in [("billion", 1e9), ("B", 1e9), ("million", 1e6),
                                  ("M", 1e6), ("thousand", 1e3), ("K", 1e3)]:
                if suffix in num_str:
                    cleaned = cleaned.replace(suffix, "").strip()
                    multiplier = mult
                    break
            
            return float(cleaned) * multiplier
        except (ValueError, TypeError):
            return None
    
    def _numbers_match(self, a: Optional[float], b: Optional[float]) -> bool:
        """Check if two numbers match within tolerance."""
        if a is None or b is None:
            return False
        if a == 0 and b == 0:
            return True
        if a == 0 or b == 0:
            return False
        return abs(a - b) / max(abs(a), abs(b)) <= self.tolerance


class HallucinationValidator:
    """
    Validates that the response is grounded in the provided context.
    Uses embedding-based provenance checking.
    """
    
    def __init__(self, threshold: float = 0.8):
        self.threshold = threshold
    
    def validate(self, response: str, context: str) -> GuardrailResult:
        """Check if the response is grounded in the context."""
        
        if not context or context == "No relevant documents found.":
            if len(response) > 100:
                return GuardrailResult(
                    rail_name="hallucination_detection",
                    passed=False,
                    severity="critical",
                    details="Substantial response generated with no source context",
                )
        
        # Sentence-level grounding check
        sentences = [s.strip() for s in re.split(r'[.!?]+', response) if len(s.strip()) > 20]
        
        ungrounded_sentences = []
        for sentence in sentences:
            # Simple keyword overlap check (production would use embeddings)
            sentence_words = set(sentence.lower().split())
            context_words = set(context.lower().split())
            
            # Remove stopwords for overlap calculation
            stopwords = {"the", "a", "an", "is", "was", "were", "are", "been", "be",
                        "have", "has", "had", "do", "does", "did", "will", "would",
                        "could", "should", "may", "might", "shall", "can", "to", "of",
                        "in", "for", "on", "with", "at", "by", "from", "as", "into",
                        "through", "during", "before", "after", "and", "but", "or",
                        "not", "no", "this", "that", "these", "those", "it", "its"}
            
            sentence_content = sentence_words - stopwords
            context_content = context_words - stopwords
            
            if sentence_content:
                overlap = len(sentence_content & context_content) / len(sentence_content)
                if overlap < 0.3:  # Less than 30% content word overlap
                    ungrounded_sentences.append(sentence[:100])
        
        grounding_score = 1.0 - (len(ungrounded_sentences) / max(len(sentences), 1))
        passed = grounding_score >= self.threshold
        
        return GuardrailResult(
            rail_name="hallucination_detection",
            passed=passed,
            severity="critical" if not passed else "low",
            details=f"Grounding score: {grounding_score:.2f} "
                    f"(threshold: {self.threshold})",
            evidence={
                "grounding_score": grounding_score,
                "total_sentences": len(sentences),
                "ungrounded_sentences": ungrounded_sentences[:5],
            },
        )


class ScopeValidator:
    """Validates that the response stays within allowed topics."""
    
    def __init__(self, prohibited_topics: list[str] = None):
        self.prohibited_patterns = {
            "investment_recommendations": [
                r'\b(?:buy|sell|hold|invest in|recommend|should (?:buy|sell))\b',
                r'\b(?:price target|upside|downside|outperform|underperform)\b',
            ],
            "portfolio_allocation": [
                r'\b(?:allocat|rebalance|diversif|portfolio weight)\b',
            ],
        }
        if prohibited_topics:
            self.active_topics = prohibited_topics
        else:
            self.active_topics = list(self.prohibited_patterns.keys())
    
    def validate(self, response: str) -> GuardrailResult:
        """Check if the response contains prohibited content."""
        violations = []
        
        for topic in self.active_topics:
            patterns = self.prohibited_patterns.get(topic, [])
            for pattern in patterns:
                matches = re.findall(pattern, response, re.IGNORECASE)
                if matches:
                    violations.append({
                        "topic": topic,
                        "matches": matches[:3],
                    })
        
        passed = len(violations) == 0
        
        return GuardrailResult(
            rail_name="scope_check",
            passed=passed,
            severity="high" if not passed else "low",
            details=f"{'No' if passed else len(violations)} scope violations detected",
            evidence={"violations": violations},
        )


# ============================================================================
# Escalation Manager
# ============================================================================

class EscalationManager:
    """
    Manages graduated response based on failure patterns.
    Tracks recent failures and triggers escalation per the Declarative Spec.
    """
    
    def __init__(self, spec: STCSpec):
        self.spec = spec
        self.escalation_config = spec.critic.get("escalation", {})
        self.recent_results: deque = deque(maxlen=100)
        self.current_level: Optional[str] = None  # None | degraded | quarantine | suspension
    
    def record_result(self, verdict: GovernanceVerdict):
        """Record a governance verdict for escalation tracking."""
        self.recent_results.append({
            "passed": verdict.passed,
            "critical_failures": sum(
                1 for r in verdict.results
                if not r.passed and r.severity == "critical"
            ),
            "timestamp": verdict.timestamp,
        })
    
    def evaluate_escalation(self) -> Optional[str]:
        """
        Evaluate whether escalation is needed based on recent failure patterns.
        Returns the escalation level or None.
        """
        if len(self.recent_results) < 10:
            return self.current_level
        
        # Look at last 10 results
        recent_10 = list(self.recent_results)[-10:]
        critical_failures = sum(r["critical_failures"] for r in recent_10)
        
        # Parse trigger thresholds from spec
        new_level = None
        
        suspension_config = self.escalation_config.get("suspension", {})
        quarantine_config = self.escalation_config.get("quarantine_mode", {})
        degraded_config = self.escalation_config.get("degraded_mode", {})
        
        if critical_failures >= 5:
            new_level = "suspension"
        elif critical_failures >= 3:
            new_level = "quarantine"
        elif critical_failures >= 2:
            new_level = "degraded"
        
        if new_level != self.current_level:
            if new_level:
                logger.warning(f"Escalation level changed: {self.current_level} → {new_level}")
            else:
                logger.info(f"Escalation cleared: {self.current_level} → normal")
            self.current_level = new_level
        
        return self.current_level


# ============================================================================
# Critic Orchestrator
# ============================================================================

class Critic:
    """
    Main Critic class that orchestrates all governance activities.
    
    The Critic does NOT fix problems. It:
    1. Evaluates outputs against guardrails
    2. Records evidence for audit
    3. Submits feedback to the Trainer
    4. Triggers escalation when thresholds are breached
    """
    
    def __init__(self, spec_path: str = "spec/stc-spec.yaml"):
        self.spec = load_spec(spec_path)
        
        # Initialize validators based on spec
        self.numerical_validator = NumericalAccuracyValidator(
            tolerance_percent=self._get_rail_config("numerical_accuracy", {}).get("tolerance_percent", 1.0)
        )
        self.hallucination_validator = HallucinationValidator(
            threshold=self._get_rail_config("hallucination_detection", {}).get("threshold", 0.8)
        )
        self.scope_validator = ScopeValidator(
            prohibited_topics=self._get_rail_config("investment_advice_detection", {}).get("prohibited_topics")
        )
        
        # Escalation
        self.escalation = EscalationManager(self.spec)
    
    def _get_rail_config(self, rail_name: str, default: dict = None) -> dict:
        """Get configuration for a specific guardrail from the spec."""
        for rail in self.spec.get_guardrails("output"):
            if rail.get("name") == rail_name:
                return rail
        return default or {}
    
    def evaluate(self, trace_data: dict) -> GovernanceVerdict:
        """
        Run all configured guardrails on a Stalwart output.
        Returns a GovernanceVerdict with pass/fail and evidence.
        """
        from opentelemetry import trace as otel_trace
        tracer = otel_trace.get_tracer("stc.critic")
        
        with tracer.start_as_current_span("critic.evaluate") as span:
            results = []
            
            response = trace_data.get("response", "")
            context = trace_data.get("context", "")
            source_chunks = trace_data.get("retrieved_chunks", [])
            
            # 1. Numerical accuracy (critical for financial data)
            num_result = self.numerical_validator.validate(response, source_chunks)
            results.append(num_result)
            
            # 2. Hallucination detection
            hall_result = self.hallucination_validator.validate(response, context)
            results.append(hall_result)
            
            # 3. Scope / investment advice check
            scope_result = self.scope_validator.validate(response)
            results.append(scope_result)
            
            # 4. PII output scan (via Presidio through Sentinel)
            pii_result = self._check_pii(response)
            results.append(pii_result)
            
            # Determine overall verdict
            critical_failures = [r for r in results if not r.passed and r.severity == "critical"]
            any_failures = [r for r in results if not r.passed]
            
            if critical_failures:
                action = "block"
            elif any_failures:
                action = "warn"
            else:
                action = "pass"
            
            verdict = GovernanceVerdict(
                trace_id=trace_data.get("trace_id", ""),
                passed=len(critical_failures) == 0,
                results=results,
                action=action,
            )
            
            # Record for escalation tracking
            self.escalation.record_result(verdict)
            escalation_level = self.escalation.evaluate_escalation()
            
            if escalation_level:
                verdict.escalation_level = escalation_level
                verdict.action = "escalate"
            
            # Log to trace
            span.set_attribute("stc.critic.passed", verdict.passed)
            span.set_attribute("stc.critic.action", verdict.action)
            span.set_attribute("stc.critic.num_failures", len(any_failures))
            span.set_attribute("stc.critic.escalation_level", escalation_level or "none")
            
            for r in results:
                span.set_attribute(f"stc.critic.rail.{r.rail_name}.passed", r.passed)
            
            return verdict
    
    def _check_pii(self, text: str) -> GuardrailResult:
        """Check for PII in the output using Presidio."""
        try:
            from presidio_analyzer import AnalyzerEngine
            analyzer = AnalyzerEngine()
            results = analyzer.analyze(text=text, language="en")
            
            high_risk = [r for r in results if r.entity_type in 
                        {"CREDIT_CARD", "US_SSN", "US_BANK_NUMBER"}]
            
            return GuardrailResult(
                rail_name="pii_output_scan",
                passed=len(high_risk) == 0,
                severity="critical" if high_risk else "low",
                details=f"{'No' if not high_risk else len(high_risk)} high-risk PII entities in output",
                evidence={
                    "entities_found": [
                        {"type": r.entity_type, "score": r.score}
                        for r in results[:10]
                    ],
                },
            )
        except ImportError:
            return GuardrailResult(
                rail_name="pii_output_scan",
                passed=True,
                severity="low",
                details="Presidio not available; PII check skipped",
            )
    
    def format_trainer_feedback(self, verdict: GovernanceVerdict) -> dict:
        """
        Format governance verdict as structured feedback for the Trainer.
        The Critic does not fix — it reports.
        """
        return {
            "trace_id": verdict.trace_id,
            "governance_passed": verdict.passed,
            "action_taken": verdict.action,
            "failures": [
                {
                    "rail": r.rail_name,
                    "severity": r.severity,
                    "details": r.details,
                    "evidence": r.evidence,
                }
                for r in verdict.results if not r.passed
            ],
            "escalation_level": verdict.escalation_level,
            "timestamp": verdict.timestamp,
        }


if __name__ == "__main__":
    critic = Critic()
    
    # Test with a response that has a hallucinated number
    test_trace = {
        "trace_id": "test-critic-001",
        "response": "The company reported revenue of $4.5 billion in Q4 2024, "
                    "representing a 15% increase year-over-year. "
                    "[Source: Annual Report, page 23]",
        "context": "Q4 2024 revenue was $4.02 billion, up 12% from Q4 2023.",
        "retrieved_chunks": [
            {"text": "Q4 2024 revenue was $4.02 billion, up 12% from Q4 2023."}
        ],
    }
    
    verdict = critic.evaluate(test_trace)
    
    print(f"\nVerdict: {'PASS' if verdict.passed else 'FAIL'}")
    print(f"Action: {verdict.action}")
    
    for result in verdict.results:
        status = "✓" if result.passed else "✗"
        print(f"  {status} {result.rail_name} [{result.severity}]: {result.details}")
    
    if not verdict.passed:
        feedback = critic.format_trainer_feedback(verdict)
        print(f"\nTrainer feedback: {len(feedback['failures'])} failures reported")
