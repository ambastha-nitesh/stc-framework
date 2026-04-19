"""Data-sovereignty tier classifier.

Two-stage:
1. Custom spec-declared patterns (regex / keyword list) — these win first
   because they encode domain rules (account numbers, internal-strategy
   keywords etc.).
2. Presidio PII analyzer — any high-risk PII (SSN / credit card / bank
   number) upgrades the tier to ``restricted``, lesser PII to ``internal``.

Presidio is loaded **once** and its custom recognizers come from the spec's
``sentinel.pii_redaction.custom_recognizers`` block.
"""

from __future__ import annotations

import re
from typing import Any

from stc_framework.config.logging import get_logger
from stc_framework.spec.models import CustomRecognizer, STCSpec

_logger = get_logger(__name__)

_HIGH_RISK = {"CREDIT_CARD", "US_SSN", "US_BANK_NUMBER"}


class DataClassifier:
    """Classifies text into ``public`` / ``internal`` / ``restricted`` tiers."""

    def __init__(self, spec: STCSpec, *, presidio_enabled: bool = True) -> None:
        self._spec = spec
        self._patterns = self._collect_patterns()
        self._presidio: Any | None = None
        if presidio_enabled:
            self._presidio = _try_build_presidio(spec.sentinel.pii_redaction.custom_recognizers)

    def _collect_patterns(self) -> list[tuple[CustomRecognizer, re.Pattern[str] | None]]:
        patterns: list[tuple[CustomRecognizer, re.Pattern[str] | None]] = []
        for rec in self._spec.data_sovereignty.classification.custom_patterns:
            compiled = re.compile(rec.regex) if rec.regex else None
            patterns.append((rec, compiled))
        for rec in self._spec.sentinel.pii_redaction.custom_recognizers:
            compiled = re.compile(rec.regex) if rec.regex else None
            patterns.append((rec, compiled))
        return patterns

    def classify(self, text: str) -> str:
        lower = text.lower()

        for rec, compiled in self._patterns:
            if compiled is not None and compiled.search(text):
                return rec.tier
            for keyword in rec.keywords:
                if keyword.lower() in lower:
                    return rec.tier

        if self._presidio is None:
            return "public"

        try:
            results = self._presidio.analyze(text=text, language="en")
        except Exception:  # pragma: no cover - presidio failure
            _logger.warning("classifier.presidio_failed")
            return "public"

        if not results:
            return "public"
        detected = {r.entity_type for r in results}
        if detected & _HIGH_RISK:
            return "restricted"
        return "internal"


def _try_build_presidio(custom_recognizers: list[CustomRecognizer]) -> Any | None:
    try:
        from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
    except ImportError:
        _logger.info("classifier.presidio_unavailable")
        return None

    engine = AnalyzerEngine()
    for rec in custom_recognizers:
        if rec.regex:
            pattern = Pattern(name=rec.name, regex=rec.regex, score=0.8)
            engine.registry.add_recognizer(
                PatternRecognizer(
                    supported_entity=rec.name.upper(),
                    patterns=[pattern],
                    context=rec.context_words or None,
                )
            )
    return engine
