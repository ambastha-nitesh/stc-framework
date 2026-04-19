"""US state AI law compliance matrix."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StateAILaw:
    state: str
    law_name: str
    effective_date: str
    key_requirements: tuple[str, ...]
    stc_coverage: str = "pending"  # pending | partial | covered


_DEFAULT_LAWS: tuple[StateAILaw, ...] = (
    StateAILaw(
        state="CO",
        law_name="Colorado AI Act (SB24-205)",
        effective_date="2026-02-01",
        key_requirements=(
            "High-risk AI impact assessment",
            "Consumer notification of AI use",
            "Adverse-decision explanation right",
        ),
    ),
    StateAILaw(
        state="CA",
        law_name="California TFAIA",
        effective_date="2025-01-01",
        key_requirements=(
            "AI training-data provenance disclosure",
            "AI-generated content watermarking",
        ),
    ),
    StateAILaw(
        state="TX",
        law_name="Texas RAIGA",
        effective_date="2026-01-01",
        key_requirements=(
            "Government AI use disclosure",
            "Biometric-match accuracy reporting",
        ),
    ),
    StateAILaw(
        state="IL",
        law_name="Illinois BIPA",
        effective_date="2008-10-03",
        key_requirements=(
            "Biometric data written consent",
            "Biometric retention schedule",
        ),
    ),
    StateAILaw(
        state="NY",
        law_name="NYC Local Law 144 (AEDT)",
        effective_date="2023-07-05",
        key_requirements=(
            "Automated Employment Decision Tool bias audit",
            "Candidate notification",
        ),
    ),
    StateAILaw(
        state="UT",
        law_name="Utah AI Policy Act",
        effective_date="2024-05-01",
        key_requirements=(
            "Generative AI disclosure",
            "Regulated-occupation AI tool disclosure",
        ),
    ),
)


@dataclass
class StateComplianceMatrix:
    laws: list[StateAILaw] = field(default_factory=lambda: list(_DEFAULT_LAWS))

    def register(self, law: StateAILaw) -> None:
        self.laws.append(law)

    def get_applicable(self, states: list[str]) -> list[StateAILaw]:
        states_upper = {s.upper() for s in states}
        return [law for law in self.laws if law.state in states_upper]

    def compliance_summary(self, states: list[str]) -> dict[str, Any]:
        applicable = self.get_applicable(states)
        coverage_counts: dict[str, int] = {}
        for law in applicable:
            coverage_counts[law.stc_coverage] = coverage_counts.get(law.stc_coverage, 0) + 1
        return {
            "states": sorted({s.upper() for s in states}),
            "applicable_law_count": len(applicable),
            "coverage": coverage_counts,
            "laws": [
                {
                    "state": law.state,
                    "law_name": law.law_name,
                    "effective_date": law.effective_date,
                    "stc_coverage": law.stc_coverage,
                }
                for law in applicable
            ],
        }


__all__ = ["StateAILaw", "StateComplianceMatrix"]
