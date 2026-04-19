"""Attorney-client privilege-aware routing.

When a query mentions legal counsel, litigation, or protected matter,
this module routes the request to local / on-prem models only — never
to third-party cloud LLMs — to preserve privilege.

Returns a routing decision that the SentinelGateway consumes alongside
its standard data-tier routing.
"""

from __future__ import annotations

from dataclasses import dataclass

PRIVILEGE_KEYWORDS: tuple[str, ...] = (
    "attorney",
    "counsel",
    "legal advice",
    "litigation",
    "privileged",
    "work product",
    "confidential legal",
    "law firm",
    "general counsel",
    "solicitor",
)


@dataclass
class PrivilegeDecision:
    privileged: bool
    reason: str = ""
    required_routing: str = "normal"  # normal | local_only


class PrivilegeRouter:
    def __init__(self, *, extra_keywords: list[str] | None = None) -> None:
        extras = tuple(k.lower() for k in (extra_keywords or []))
        self._keywords = PRIVILEGE_KEYWORDS + extras

    def evaluate(self, *, query: str, context: str = "") -> PrivilegeDecision:
        blob = (query + "\n" + context).lower()
        for kw in self._keywords:
            if kw in blob:
                return PrivilegeDecision(
                    privileged=True,
                    reason=f"matched keyword {kw!r}",
                    required_routing="local_only",
                )
        return PrivilegeDecision(privileged=False)


__all__ = ["PRIVILEGE_KEYWORDS", "PrivilegeDecision", "PrivilegeRouter"]
