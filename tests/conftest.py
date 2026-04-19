"""Pytest fixtures shared across the STC Framework test suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry

from stc_framework.observability import metrics as metrics_module
from stc_framework.observability.audit import _KeyManager as _AuditKeyManager
from stc_framework.resilience import circuit as circuit_module
from stc_framework.resilience import degradation as degradation_module
from stc_framework.spec.loader import load_spec
from stc_framework.spec.models import STCSpec

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _fresh_metrics():
    """Reset the Prometheus registry for each test so counters start at zero."""
    registry = CollectorRegistry()
    metrics_module.reset_metrics_for_tests(registry)
    yield
    metrics_module.reset_metrics_for_tests(CollectorRegistry())


@pytest.fixture(autouse=True)
def _fresh_circuits():
    circuit_module.reset_circuits_for_tests()
    yield
    circuit_module.reset_circuits_for_tests()


@pytest.fixture(autouse=True)
def _fresh_degradation():
    degradation_module.reset_degradation_for_tests()
    yield
    degradation_module.reset_degradation_for_tests()


@pytest.fixture(autouse=True)
def _fresh_audit_key():
    # The audit HMAC key is a process-wide singleton. Reset between
    # tests so tests that install a known key don't leak into tests
    # that want the ephemeral fallback.
    _AuditKeyManager.reset_for_tests()
    yield
    _AuditKeyManager.reset_for_tests()


@pytest.fixture()
def fixture_dir() -> Path:
    return _FIXTURE_DIR


@pytest.fixture()
def minimal_spec(fixture_dir: Path) -> STCSpec:
    return load_spec(fixture_dir / "minimal_spec.yaml")


@pytest.fixture()
def financial_spec() -> STCSpec:
    # Use the real example spec so tests catch schema drift.
    return load_spec(Path(__file__).parents[1] / "spec-examples" / "financial_qa.yaml")
