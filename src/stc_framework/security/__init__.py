"""Security primitives: input limits, sanitizers, injection detection."""

from stc_framework.security.limits import (
    SecurityLimits,
    enforce_string_limit,
    get_security_limits,
)
from stc_framework.security.sanitize import (
    safe_log_value,
    sanitize_context_chunk,
    sanitize_header_value,
    strip_zero_width,
)
from stc_framework.security.injection import (
    INJECTION_RULES,
    InjectionMatch,
    detect_injection,
)

__all__ = [
    "INJECTION_RULES",
    "InjectionMatch",
    "SecurityLimits",
    "detect_injection",
    "enforce_string_limit",
    "get_security_limits",
    "safe_log_value",
    "sanitize_context_chunk",
    "sanitize_header_value",
    "strip_zero_width",
]
