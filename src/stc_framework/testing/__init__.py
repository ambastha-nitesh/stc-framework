"""Test-only hooks for resetting process-global state.

These helpers are dangerous in production — they wipe Prometheus
counters, circuit-breaker state, the global degradation flag, and the
cached audit HMAC key. They live in a dedicated module so reviewers can
trivially grep for `stc_framework.testing` usage in production code.

Accidentally using these in prod raises at import time when
``STC_ENV=prod`` — refuse to mutate global state outside tests.
"""

from __future__ import annotations

import os

from stc_framework.observability.audit import _KeyManager as _AuditKeyManager
from stc_framework.observability.metrics import reset_metrics_for_tests as _reset_metrics
from stc_framework.resilience.circuit import reset_circuits_for_tests as _reset_circuits
from stc_framework.resilience.degradation import (
    reset_degradation_for_tests as _reset_degradation,
)


def _guard() -> None:
    if os.getenv("STC_ENV", "").lower() == "prod":
        raise RuntimeError(
            "stc_framework.testing helpers are not allowed when STC_ENV=prod"
        )


def reset_metrics(*args, **kwargs):
    _guard()
    return _reset_metrics(*args, **kwargs)


def reset_circuits() -> None:
    _guard()
    _reset_circuits()


def reset_degradation() -> None:
    _guard()
    _reset_degradation()


def reset_audit_hmac_key() -> None:
    _guard()
    _AuditKeyManager.reset_for_tests()


def reset_all() -> None:
    """Reset every global piece of state — convenient conftest helper."""
    reset_metrics()
    reset_circuits()
    reset_degradation()
    reset_audit_hmac_key()


__all__ = [
    "reset_all",
    "reset_audit_hmac_key",
    "reset_circuits",
    "reset_degradation",
    "reset_metrics",
]
