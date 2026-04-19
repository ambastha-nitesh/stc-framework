"""Query-pattern protection — detects inference-metadata leakage.

If many queries to the same external provider repeatedly reference the
same entity (client id, deal code, product name), that pattern itself
leaks business intelligence even when the query body is redacted.

This protector counts per-provider, per-entity queries via the
KeyValueStore and flags patterns that exceed a concentration threshold.
"""

from __future__ import annotations

from dataclasses import dataclass

from stc_framework.infrastructure.store import KeyValueStore


@dataclass
class PatternRiskReport:
    provider: str
    total_queries: int
    top_entities: list[tuple[str, int]]
    concentrated: bool


_KEY = "compliance:query_pattern:{provider}:{entity}"


class QueryPatternProtector:
    """Increment per-(provider, entity) counters; flag concentration."""

    def __init__(
        self,
        store: KeyValueStore,
        *,
        concentration_threshold: float = 0.4,
    ) -> None:
        self._store = store
        self._threshold = concentration_threshold

    async def record_query(self, *, provider: str, entity: str) -> None:
        await self._store.incr(_KEY.format(provider=provider, entity=entity.lower()))

    async def check_pattern_risk(self, *, provider: str) -> PatternRiskReport:
        keys = await self._store.keys(f"compliance:query_pattern:{provider}:*")
        counts: list[tuple[str, int]] = []
        total = 0
        for k in keys:
            n = await self._store.get(k)
            if isinstance(n, int):
                entity = k.rsplit(":", 1)[-1]
                counts.append((entity, n))
                total += n
        counts.sort(key=lambda t: -t[1])
        top = counts[:10]
        concentrated = False
        if total > 0 and counts:
            # If the most-queried entity exceeds the threshold share, flag.
            if counts[0][1] / total >= self._threshold:
                concentrated = True
        return PatternRiskReport(
            provider=provider,
            total_queries=total,
            top_entities=top,
            concentrated=concentrated,
        )

    def recommend_routing(self, report: PatternRiskReport) -> str:
        """Advise local-only routing when concentration exceeds the threshold."""
        return "local_only" if report.concentrated else "normal"


__all__ = ["PatternRiskReport", "QueryPatternProtector"]
