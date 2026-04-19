"""Hard limits that protect against DoS-style abuse.

These are intentionally generous for legitimate use (tens of KB per field)
but bounded enough that a pathological input cannot exhaust memory or
trigger quadratic algorithms downstream (e.g. regex backtracking).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SecurityLimits:
    """Upper bounds enforced at the system boundary."""

    max_query_chars: int = 8_000
    """Longest user query we will accept. Must fit in a typical LLM context
    with room for retrieved content and prompt overhead."""

    max_response_chars: int = 40_000
    """Longest model response we will evaluate / return."""

    max_context_chars: int = 120_000
    """Longest assembled context window."""

    max_chunk_chars: int = 8_000
    """Longest individual retrieved chunk."""

    max_chunks: int = 50
    """Hard cap on retrieved-chunk count regardless of top_k."""

    max_header_value_chars: int = 256
    """Longest accepted value for X-Tenant-Id / X-Request-Id."""

    max_request_bytes: int = 64 * 1024
    """Longest accepted HTTP request body."""


_LIMITS = SecurityLimits()


def get_security_limits() -> SecurityLimits:
    return _LIMITS


def enforce_string_limit(value: str, *, limit: int, name: str) -> str:
    """Raise if ``value`` exceeds the limit.

    Raised error type is :class:`ValueError` so callers can translate it to
    the appropriate boundary error (HTTP 413, STCError, etc.) without
    coupling this module to the errors package.
    """
    if len(value) > limit:
        raise ValueError(f"{name} exceeds maximum allowed length ({len(value)} > {limit})")
    return value
