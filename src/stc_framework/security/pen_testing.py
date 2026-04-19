"""Pen-test runner for AI + infra attacks.

A small, parameterised runner that walks every payload in the shared
pen-test catalog and records PASS/FAIL/ERROR per test. Categories are
tagged with MITRE ATLAS + OWASP LLM Top 10 identifiers via the
catalog's ``metadata`` so the report is directly reusable as
compliance evidence.

The runner is intentionally a *simulator* — it invokes a caller-
supplied ``probe_fn`` for each payload and classifies the response.
Integrations with live LLM / API / network layers plug in by providing
a ``probe_fn`` that actually sends the payload. Simulation-only runs
still exercise the catalog and generate a report.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from stc_framework.security.patterns import Pattern, PatternCatalog, default_pen_catalog


class TestResult(str, Enum):
    __test__ = False

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


@dataclass
class PenTestResult:
    test_id: str
    test_name: str
    category: str
    result: TestResult
    severity: str
    evidence: str = ""
    mitre: str = ""
    owasp: str = ""
    remediation: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# Probe function type: async. Takes a payload string, returns "blocked"
# (defence succeeded, FAIL the test as attack) vs "allowed" (defence
# failed, test PASSED the attack — highlights a gap). A real probe
# evaluates model output / API response for the attacker's objective.
ProbeFn = Callable[[Pattern], Awaitable[str]]


class PenTestRunner:
    """Iterates every pattern in the catalog against a probe function."""

    def __init__(
        self,
        probe_fn: ProbeFn,
        *,
        catalog: PatternCatalog | None = None,
    ) -> None:
        self._probe = probe_fn
        self._catalog = catalog or default_pen_catalog()

    async def run_all(self) -> list[PenTestResult]:
        return await self.run_by_category(None)

    async def run_by_category(self, category: str | None) -> list[PenTestResult]:
        results: list[PenTestResult] = []
        for pattern in self._catalog.scan("") + [
            self._catalog.get(name) for name in self._catalog.names()
        ]:  # ensure each pattern runs regardless of scan match
            meta = pattern.metadata or {}
            pattern_category = str(meta.get("category", "ai_adversarial"))
            if category is not None and category != pattern_category:
                continue
            try:
                verdict = await self._probe(pattern)
            except Exception as exc:  # pragma: no cover - defensive
                results.append(
                    PenTestResult(
                        test_id=pattern.name,
                        test_name=pattern.name,
                        category=pattern_category,
                        result=TestResult.ERROR,
                        severity=pattern.severity,
                        evidence=f"probe raised {type(exc).__name__}: {exc}",
                        mitre=str(meta.get("mitre", "")),
                        owasp=str(meta.get("owasp", "")),
                    )
                )
                continue
            # "blocked" = defence worked (FAIL as attack), "allowed" = gap (PASS as attack).
            test_result = TestResult.PASS if verdict == "allowed" else TestResult.FAIL
            results.append(
                PenTestResult(
                    test_id=pattern.name,
                    test_name=pattern.name,
                    category=pattern_category,
                    result=test_result,
                    severity=pattern.severity,
                    evidence=verdict,
                    mitre=str(meta.get("mitre", "")),
                    owasp=str(meta.get("owasp", "")),
                )
            )
        # De-duplicate — each pattern is iterated twice above.
        seen: set[str] = set()
        unique: list[PenTestResult] = []
        for r in results:
            if r.test_id not in seen:
                seen.add(r.test_id)
                unique.append(r)
        return unique

    @staticmethod
    def summarise(results: list[PenTestResult]) -> dict[str, Any]:
        counts: dict[str, int] = {r.value: 0 for r in TestResult}
        mitre: dict[str, int] = {}
        owasp: dict[str, int] = {}
        for r in results:
            counts[r.result.value] += 1
            if r.mitre:
                mitre[r.mitre] = mitre.get(r.mitre, 0) + 1
            if r.owasp:
                owasp[r.owasp] = owasp.get(r.owasp, 0) + 1
        return {
            "total": len(results),
            "counts": counts,
            "mitre_coverage": mitre,
            "owasp_coverage": owasp,
        }


__all__ = ["PenTestResult", "PenTestRunner", "TestResult"]
