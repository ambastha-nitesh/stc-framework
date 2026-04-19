"""Intellectual-property risk scanner.

Detects potential copyright / trademark infringement in AI output by
matching against a configurable :class:`PatternCatalog`. The default
catalog ships empty — deployments populate it with their owned marks
and the competitor / licensor marks they must not republish.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from stc_framework.compliance.patterns import PatternCatalog, default_ip_catalog
from stc_framework.governance.events import AuditEvent
from stc_framework.observability.audit import AuditLogger, AuditRecord


@dataclass
class IPRiskFlag:
    name: str
    severity: str
    description: str
    matched_text: str
    suggested_action: str = "review"


@dataclass
class IPRiskResult:
    flags: list[IPRiskFlag] = field(default_factory=list)

    @property
    def any_critical(self) -> bool:
        return any(f.severity == "critical" for f in self.flags)


class IPRiskScanner:
    def __init__(self, catalog: PatternCatalog | None = None, *, audit: AuditLogger | None = None) -> None:
        self._catalog = catalog or default_ip_catalog()
        self._audit = audit

    async def scan(self, content: str) -> IPRiskResult:
        result = IPRiskResult()
        for pattern in self._catalog.scan(content):
            match = pattern.regex.search(content)
            result.flags.append(
                IPRiskFlag(
                    name=pattern.name,
                    severity=pattern.severity,
                    description=pattern.description,
                    matched_text=(match.group(0)[:120] if match else ""),
                )
            )
        if result.flags and self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    event_type=AuditEvent.COMPLIANCE_CHECK_EVALUATED.value,
                    persona="compliance",
                    extra={
                        "rule": "ip_risk",
                        "flags": [f.name for f in result.flags],
                    },
                )
            )
        return result


__all__ = ["IPRiskFlag", "IPRiskResult", "IPRiskScanner"]
