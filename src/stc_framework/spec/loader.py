"""Load and validate :class:`STCSpec` from YAML or dict with ``${ENV}`` interpolation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from stc_framework.errors import SpecValidationError
from stc_framework.spec.models import STCSpec

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _interpolate(value: Any) -> Any:
    """Recursively replace ``${VAR}`` in string leaves with env values."""
    if isinstance(value, str):
        def sub(match: re.Match[str]) -> str:
            return os.getenv(match.group(1), match.group(0))

        return _ENV_RE.sub(sub, value)
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    return value


def load_spec(path: str | os.PathLike[str]) -> STCSpec:
    """Load a spec YAML from ``path`` and return a validated :class:`STCSpec`.

    Raises
    ------
    FileNotFoundError
        When the path does not exist.
    SpecValidationError
        When pydantic validation fails. The ``context['errors']`` attribute
        contains the structured pydantic error list.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"STC specification not found at {p}")

    with p.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    return spec_from_dict(_interpolate(raw))


def spec_from_dict(data: dict[str, Any]) -> STCSpec:
    """Validate an already-loaded dict into :class:`STCSpec`."""
    try:
        return STCSpec.model_validate(data)
    except ValidationError as exc:
        raise SpecValidationError(
            message="STC specification failed validation",
            context={"errors": exc.errors()},
        ) from exc


def validate_spec(spec: STCSpec) -> list[str]:
    """Return a list of human-readable warnings/errors beyond schema validation.

    The schema-level checks already happened at load time. This function runs
    *semantic* checks (e.g. cost thresholds align, reward weights sum
    reasonably).
    """
    warnings: list[str] = []

    total_weight = sum(r.weight for r in spec.trainer.optimization.reward_signals)
    if spec.trainer.optimization.reward_signals and not (0.9 <= total_weight <= 1.1):
        warnings.append(
            f"Reward signal weights sum to {total_weight:.2f}; expected ~1.0"
        )

    triggers = spec.trainer.maintenance_triggers
    if triggers.cost_above_per_task_usd < spec.trainer.cost_thresholds.max_per_task_usd:
        warnings.append(
            "maintenance_triggers.cost_above_per_task_usd is less than "
            "cost_thresholds.max_per_task_usd; alerts will fire before budget"
        )

    for persona_name, persona in (
        ("stalwart", spec.stalwart),
        ("trainer", spec.trainer),
        ("critic", spec.critic),
    ):
        if not persona.auth.key_scope:
            warnings.append(f"{persona_name}.auth.key_scope is empty")

    return warnings
