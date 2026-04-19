"""Presidio-backed PII redaction with graceful no-op fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from stc_framework.config.logging import get_logger
from stc_framework.errors import DataSovereigntyViolation
from stc_framework.observability.metrics import get_metrics
from stc_framework.spec.models import STCSpec

_logger = get_logger(__name__)


@dataclass
class RedactionResult:
    text: str
    redactions: list[dict[str, Any]] = field(default_factory=list)
    entity_counts: dict[str, int] = field(default_factory=dict)


# Minimal regex-based fallback for when Presidio is unavailable.
# Ordering matters: most-specific / highest-risk patterns first so that a
# credit card never gets classified as a phone number.
#
# Each pattern has a hard upper bound on repetition count so an attacker
# cannot drive them into catastrophic backtracking by supplying arbitrarily
# long digit runs. Character classes also avoid overlap between the quantified
# group and any surrounding greedy construct.
_FALLBACK_PATTERNS: dict[str, re.Pattern[str]] = {
    # 13–19 digit groups separated by at most one space/hyphen.
    "CREDIT_CARD": re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
    "US_SSN": re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
    "EMAIL_ADDRESS": re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}\.[\w.-]{1,63}"),
    # Capped URL length prevents a 10 MB URL from ever entering the engine.
    "URL": re.compile(r"https?://[^\s<>\"']{1,2048}"),
    # Phone number with bounded length and no overlapping alternations.
    "PHONE_NUMBER": re.compile(r"(?<!\d)\+?\d[\d\s().-]{6,18}\d(?!\d)"),
}


class PIIRedactor:
    """Stateless redactor; holds Presidio handles so we build them only once."""

    def __init__(self, spec: STCSpec, *, presidio_enabled: bool = True) -> None:
        self._entities_config = spec.sentinel.pii_redaction.entities_config
        self._block = {k for k, v in self._entities_config.items() if v == "BLOCK"}
        self._mask = {k for k, v in self._entities_config.items() if v == "MASK"}
        self._analyzer: Any | None = None
        self._anonymizer: Any | None = None
        if presidio_enabled:
            self._analyzer, self._anonymizer = _try_build_presidio()

    def redact(self, text: str) -> RedactionResult:
        """Return the redacted text along with structured evidence.

        Raises :class:`DataSovereigntyViolation` when a ``BLOCK``-listed
        entity appears in the input.
        """
        if self._analyzer is not None and self._anonymizer is not None:
            return self._redact_presidio(text)
        return self._redact_fallback(text)

    def _redact_presidio(self, text: str) -> RedactionResult:
        analyzer = self._analyzer
        anonymizer = self._anonymizer
        assert analyzer is not None and anonymizer is not None

        results = analyzer.analyze(text=text, language="en")
        if not results:
            return RedactionResult(text=text)

        for r in results:
            if r.entity_type in self._block:
                raise DataSovereigntyViolation(
                    message=f"Blocked entity detected: {r.entity_type}",
                    downstream="sentinel",
                    context={"entity_type": r.entity_type},
                )

        from presidio_anonymizer.entities import OperatorConfig

        operators = {
            "DEFAULT": OperatorConfig("replace", {"new_value": "<REDACTED>"}),
            "PERSON": OperatorConfig("replace", {"new_value": "<PERSON>"}),
            "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "<EMAIL>"}),
            "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "<PHONE>"}),
        }
        anonymized = anonymizer.anonymize(
            text=text, analyzer_results=results, operators=operators
        )

        counts: dict[str, int] = {}
        redactions: list[dict[str, Any]] = []
        for r in results:
            counts[r.entity_type] = counts.get(r.entity_type, 0) + 1
            redactions.append(
                {
                    "entity_type": r.entity_type,
                    "start": r.start,
                    "end": r.end,
                    "score": r.score,
                }
            )

        metrics = get_metrics()
        for etype, count in counts.items():
            metrics.redaction_events_total.labels(entity_type=etype).inc(count)

        return RedactionResult(
            text=anonymized.text, redactions=redactions, entity_counts=counts
        )

    def _redact_fallback(self, text: str) -> RedactionResult:
        redacted = text
        counts: dict[str, int] = {}
        redactions: list[dict[str, Any]] = []
        for etype, pattern in _FALLBACK_PATTERNS.items():
            matches = list(pattern.finditer(redacted))
            if etype in self._block and matches:
                raise DataSovereigntyViolation(
                    message=f"Blocked entity detected: {etype}",
                    downstream="sentinel",
                    context={"entity_type": etype},
                )
            if not matches:
                continue
            counts[etype] = len(matches)
            for m in matches:
                redactions.append(
                    {"entity_type": etype, "start": m.start(), "end": m.end(), "score": 0.6}
                )
            redacted = pattern.sub(f"<{etype}>", redacted)

        if counts:
            metrics = get_metrics()
            for etype, count in counts.items():
                metrics.redaction_events_total.labels(entity_type=etype).inc(count)

        return RedactionResult(text=redacted, redactions=redactions, entity_counts=counts)


def _try_build_presidio() -> tuple[Any | None, Any | None]:
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
    except ImportError:
        _logger.info("redaction.presidio_unavailable")
        return None, None
    return AnalyzerEngine(), AnonymizerEngine()
