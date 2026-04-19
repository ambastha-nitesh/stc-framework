"""Declarative specification models and loader."""

from stc_framework.spec.loader import load_spec, validate_spec
from stc_framework.spec.models import (
    CriticSpec,
    DataSovereigntySpec,
    SentinelSpec,
    STCSpec,
    StalwartSpec,
    TrainerSpec,
)

__all__ = [
    "CriticSpec",
    "DataSovereigntySpec",
    "STCSpec",
    "SentinelSpec",
    "StalwartSpec",
    "TrainerSpec",
    "load_spec",
    "validate_spec",
]
