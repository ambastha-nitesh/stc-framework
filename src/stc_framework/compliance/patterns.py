"""Shared helpers for the compliance modules' pattern-matching core.

Re-exports the Phase-0 :class:`PatternCatalog` and resolves the
bundled default catalog paths. Keeping a single public surface here
means legal / compliance teams only need to point their deployment at
one kind of YAML file, and every compliance engine in the framework
consumes the same format.
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

DEFAULT_FINRA_PATTERNS_PATH = _DATA / "finra_patterns.yaml"
DEFAULT_IP_TRADEMARKS_PATH = _DATA / "ip_trademarks.yaml"


def default_finra_catalog() -> PatternCatalog:
    return cached_catalog(str(DEFAULT_FINRA_PATTERNS_PATH))


def default_ip_catalog() -> PatternCatalog:
    return cached_catalog(str(DEFAULT_IP_TRADEMARKS_PATH))


__all__ = [
    "DEFAULT_FINRA_PATTERNS_PATH",
    "DEFAULT_IP_TRADEMARKS_PATH",
    "Pattern",
    "PatternCatalog",
    "cached_catalog",
    "default_finra_catalog",
    "default_ip_catalog",
    "load_pattern_catalog",
]
