"""YAML-backed pattern catalog loader.

Compliance and threat-detection subsystems reference large, change-prone
lists of phrases / regexes (FINRA violation language, trademark catalog,
prompt-injection payloads). We keep the domain data in YAML files shipped
alongside the code, not inside Python source, so legal / security teams
can update them without a full code review cycle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Pattern:
    """A single pattern entry from a catalog.

    ``metadata`` defaults to an empty dict, not None — callers do
    ``pattern.metadata.get("category")`` without a None-check. The
    v0.3.0 staff-review R5 finding caught the original None default
    that would raise ``AttributeError`` for entries without an explicit
    ``metadata:`` block in the YAML.
    """

    name: str
    regex: re.Pattern[str]
    severity: str = "medium"
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def matches(self, text: str) -> bool:
        return bool(self.regex.search(text))


class PatternCatalog:
    """In-memory catalog of compiled patterns keyed by name."""

    def __init__(self, patterns: list[Pattern]):
        self._patterns = {p.name: p for p in patterns}

    def __len__(self) -> int:
        return len(self._patterns)

    def names(self) -> list[str]:
        return sorted(self._patterns.keys())

    def get(self, name: str) -> Pattern:
        return self._patterns[name]

    def scan(self, text: str) -> list[Pattern]:
        return [p for p in self._patterns.values() if p.matches(text)]


def load_pattern_catalog(path: str | Path) -> PatternCatalog:
    r"""Load a YAML pattern file.

    Expected format::

        patterns:
          - name: guarantee
            regex: "(?i)\bguaranteed?\b"
            severity: high
            description: "Forbidden performance guarantee language"
          - name: ...

    Compiles every regex eagerly so load-time failures surface in CI.
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    raw = data.get("patterns", [])
    if not isinstance(raw, list):
        raise ValueError(f"pattern file {path!s}: expected 'patterns' to be a list")
    compiled: list[Pattern] = []
    for entry in raw:
        if not isinstance(entry, dict) or "name" not in entry or "regex" not in entry:
            raise ValueError(f"pattern file {path!s}: entry missing name/regex: {entry!r}")
        compiled.append(
            Pattern(
                name=str(entry["name"]),
                regex=re.compile(str(entry["regex"])),
                severity=str(entry.get("severity", "medium")),
                description=str(entry.get("description", "")),
                metadata=dict(entry.get("metadata", {})),
            )
        )
    return PatternCatalog(compiled)


@lru_cache(maxsize=32)
def cached_catalog(path: str) -> PatternCatalog:
    """Memoised loader for pattern catalogs that rarely change at runtime."""
    return load_pattern_catalog(path)


__all__ = ["Pattern", "PatternCatalog", "cached_catalog", "load_pattern_catalog"]
