"""
STC Framework - Sentinel Layer: Gateway & Data Classification

The Sentinel is infrastructure, not intelligence. It enforces trust boundaries,
routes based on data classification, redacts PII, and manages authentication.
It does not learn. It does not evolve. It executes policies defined in the
Declarative Specification.
"""

import os
import re
import logging
from typing import Optional
from spec.loader import STCSpec

logger = logging.getLogger("stc.sentinel")


# ============================================================================
# Data Classifier
# ============================================================================

class DataClassifier:
    """
    Classifies data sensitivity tier based on content analysis.
    Uses Presidio for PII detection and custom patterns from the spec.
    Routes decisions to the appropriate inference endpoint.
    """
    
    def __init__(self, spec: STCSpec):
        self.spec = spec
        self.custom_patterns = self._load_custom_patterns()
        self._setup_presidio()
    
    def _load_custom_patterns(self) -> list[dict]:
        """Load custom classification patterns from the spec."""
        classification = self.spec.data_sovereignty.get("classification", {})
        return classification.get("custom_patterns", [])
    
    def _setup_presidio(self):
        """Initialize Presidio analyzer for PII detection."""
        try:
            from presidio_analyzer import AnalyzerEngine
            self.analyzer = AnalyzerEngine()
            self.presidio_available = True
        except ImportError:
            logger.warning("Presidio not available; using pattern-only classification")
            self.presidio_available = False
    
    def classify(self, text: str) -> str:
        """
        Classify text into a data sovereignty tier.
        
        Returns: 'restricted', 'internal', or 'public'
        """
        # Check custom patterns first (highest priority)
        for pattern in self.custom_patterns:
            if pattern.get("regex"):
                if re.search(pattern["regex"], text):
                    return pattern.get("tier", "restricted")
            if pattern.get("keywords"):
                text_lower = text.lower()
                for keyword in pattern["keywords"]:
                    if keyword.lower() in text_lower:
                        return pattern.get("tier", "restricted")
        
        # Check for PII using Presidio
        if self.presidio_available:
            results = self.analyzer.analyze(text=text, language="en")
            if results:
                # Any PII detected → at minimum internal tier
                high_risk_entities = {"CREDIT_CARD", "US_SSN", "US_BANK_NUMBER"}
                detected_entities = {r.entity_type for r in results}
                
                if detected_entities & high_risk_entities:
                    return "restricted"
                return "internal"
        
        return "public"


# ============================================================================
# Sentinel Gateway
# ============================================================================

class SentinelGateway:
    """
    LLM Gateway that enforces data sovereignty, PII redaction, and
    authentication. Wraps LiteLLM for model routing.
    
    The Sentinel does not decide WHAT to route — the Trainer configures
    routing policies. The Sentinel ENFORCES those policies.
    """
    
    def __init__(self, spec: STCSpec):
        self.spec = spec
        self.classifier = DataClassifier(spec)
        self._setup_litellm()
        self._setup_redaction()
    
    def _setup_litellm(self):
        """Configure LiteLLM for multi-model routing."""
        try:
            import litellm
            self.litellm = litellm
            
            gateway_config = self.spec.sentinel.get("gateway", {})
            proxy_host = gateway_config.get("host")
            
            if proxy_host:
                litellm.api_base = proxy_host
            
            self.litellm_available = True
        except ImportError:
            logger.warning("LiteLLM not available; using direct API calls")
            self.litellm_available = False
    
    def _setup_redaction(self):
        """Initialize Presidio for PII redaction."""
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine
            from presidio_anonymizer.entities import OperatorConfig
            
            self.pii_analyzer = AnalyzerEngine()
            self.pii_anonymizer = AnonymizerEngine()
            self.redaction_available = True
            
            # Load entity configs from spec
            entities_config = self.spec.sentinel.get("pii_redaction", {}).get("entities_config", {})
            self.block_entities = [k for k, v in entities_config.items() if v == "BLOCK"]
            self.mask_entities = [k for k, v in entities_config.items() if v == "MASK"]
            
        except ImportError:
            logger.warning("Presidio not available; PII redaction disabled")
            self.redaction_available = False
    
    def redact_pii(self, text: str) -> tuple[str, list[dict]]:
        """
        Redact PII from text before sending to LLM.
        Returns (redacted_text, list_of_redactions_for_audit).
        """
        if not self.redaction_available:
            return text, []
        
        # Analyze for PII
        results = self.pii_analyzer.analyze(text=text, language="en")
        
        if not results:
            return text, []
        
        # Check for blocked entities
        for result in results:
            if result.entity_type in self.block_entities:
                logger.warning(f"Blocked entity detected: {result.entity_type}")
                raise DataSovereigntyViolation(
                    f"Blocked PII entity detected: {result.entity_type}. "
                    "This data cannot be sent to any LLM."
                )
        
        # Anonymize maskable entities
        from presidio_anonymizer.entities import OperatorConfig
        
        anonymized = self.pii_anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators={
                "DEFAULT": OperatorConfig("replace", {"new_value": "<REDACTED>"}),
                "PERSON": OperatorConfig("replace", {"new_value": "<PERSON>"}),
                "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "<EMAIL>"}),
                "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "<PHONE>"}),
            }
        )
        
        # Build audit record of redactions
        redactions = [
            {
                "entity_type": r.entity_type,
                "start": r.start,
                "end": r.end,
                "score": r.score,
            }
            for r in results
        ]
        
        return anonymized.text, redactions
    
    def completion(
        self,
        messages: list[dict],
        data_tier: str = "public",
        metadata: Optional[dict] = None,
    ):
        """
        Route an LLM completion request through the Sentinel.
        
        1. Classify data tier (or use provided tier)
        2. Redact PII from messages
        3. Select model based on routing policy
        4. Execute via LiteLLM
        5. Log boundary crossing for audit
        """
        from opentelemetry import trace
        tracer = trace.get_tracer("stc.sentinel")
        
        with tracer.start_as_current_span("sentinel.completion") as span:
            span.set_attribute("stc.data_tier", data_tier)
            
            # Step 1: Redact PII from user messages
            redacted_messages = []
            all_redactions = []
            
            for msg in messages:
                if msg["role"] == "user":
                    redacted_content, redactions = self.redact_pii(msg["content"])
                    redacted_messages.append({**msg, "content": redacted_content})
                    all_redactions.extend(redactions)
                else:
                    redacted_messages.append(msg)
            
            span.set_attribute("stc.redactions.count", len(all_redactions))
            
            # Step 2: Select model based on data tier routing policy
            allowed_models = self.spec.get_routing_policy(data_tier)
            if not allowed_models:
                raise DataSovereigntyViolation(
                    f"No models configured for data tier: {data_tier}"
                )
            
            model = allowed_models[0]  # Trainer may reorder this list
            span.set_attribute("stc.model_selected", model)
            span.set_attribute("stc.boundary_crossing", data_tier != "restricted")
            
            # Step 3: Execute via LiteLLM
            if self.litellm_available:
                response = self.litellm.completion(
                    model=model,
                    messages=redacted_messages,
                    metadata=metadata or {},
                )
            else:
                raise RuntimeError("No LLM backend available")
            
            return response


class DataSovereigntyViolation(Exception):
    """Raised when a data sovereignty policy would be violated."""
    pass
