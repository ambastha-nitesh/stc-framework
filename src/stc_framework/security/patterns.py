"""Shared security payload catalogs for pen testing + threat detection.

Both ``security/pen_testing.py`` and ``security/threat_detection.py``
consume these catalogs. Keeping them in one place means a new
jailbreak pattern added to the YAML is immediately visible to both the
active test suite and the runtime detector — and legal-sensitive
payloads aren't shipped hardcoded in source.

This module is distinct from :mod:`stc_framework.security.injection`,
which carries the hot-path Critic input-rail rules; those must stay
inline for performance.
"""

from __future__ import annotations

from pathlib import Path

from stc_framework._internal.patterns import (
    Pattern,
    PatternCatalog,
    cached_catalog,
    load_pattern_catalog,
)

_DATA = Path(__file__).parent / "data"
DEFAULT_THREAT_PATTERNS_PATH = _DATA / "threat_patterns.yaml"
DEFAULT_PEN_PAYLOADS_PATH = _DATA / "pen_payloads.yaml"


def default_threat_catalog() -> PatternCatalog:
    return cached_catalog(str(DEFAULT_THREAT_PATTERNS_PATH))


def default_pen_catalog() -> PatternCatalog:
    return cached_catalog(str(DEFAULT_PEN_PAYLOADS_PATH))


__all__ = [
    "DEFAULT_PEN_PAYLOADS_PATH",
    "DEFAULT_THREAT_PATTERNS_PATH",
    "Pattern",
    "PatternCatalog",
    "cached_catalog",
    "default_pen_catalog",
    "default_threat_catalog",
    "load_pattern_catalog",
]
