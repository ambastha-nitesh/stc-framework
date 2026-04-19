"""Model provenance + geopolitical risk scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OriginRisk(str, Enum):
    TRUSTED = "trusted"
    CAUTIOUS = "cautious"
    RESTRICTED = "restricted"
    SANCTIONED = "sanctioned"


@dataclass
class ModelOriginProfile:
    model_id: str
    developer_org: str = ""
    headquarters_country: str = "US"
    training_data_jurisdiction: str = "US"
    origin_risk: OriginRisk = OriginRisk.TRUSTED
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# Default registry. Keep it small and conservative — operators extend
# via ``register`` rather than us shipping a comprehensive catalog here.
_DEFAULT_REGISTRY: dict[str, ModelOriginProfile] = {
    "gpt-4": ModelOriginProfile(
        model_id="gpt-4",
        developer_org="OpenAI",
        headquarters_country="US",
        training_data_jurisdiction="US",
        origin_risk=OriginRisk.TRUSTED,
    ),
    "claude-3": ModelOriginProfile(
        model_id="claude-3",
        developer_org="Anthropic",
        headquarters_country="US",
        training_data_jurisdiction="US",
        origin_risk=OriginRisk.TRUSTED,
    ),
    "mistral-large": ModelOriginProfile(
        model_id="mistral-large",
        developer_org="Mistral AI",
        headquarters_country="FR",
        training_data_jurisdiction="EU",
        origin_risk=OriginRisk.CAUTIOUS,
    ),
    "local/llama": ModelOriginProfile(
        model_id="local/llama",
        developer_org="Meta",
        headquarters_country="US",
        training_data_jurisdiction="US",
        origin_risk=OriginRisk.TRUSTED,
    ),
}


class ModelOriginPolicy:
    """Evaluate a model against an operator-declared allow-list of risks."""

    def __init__(
        self,
        *,
        allowed_risks: set[OriginRisk] | None = None,
        registry: dict[str, ModelOriginProfile] | None = None,
    ) -> None:
        self._allowed = allowed_risks or {OriginRisk.TRUSTED, OriginRisk.CAUTIOUS}
        self._registry: dict[str, ModelOriginProfile] = dict(_DEFAULT_REGISTRY)
        if registry:
            self._registry.update(registry)

    def register(self, profile: ModelOriginProfile) -> None:
        self._registry[profile.model_id] = profile

    def evaluate(self, model_id: str) -> dict[str, Any]:
        profile = self._registry.get(model_id)
        if profile is None:
            return {
                "allowed": False,
                "reason": "model origin unknown; register it before use",
                "model_id": model_id,
            }
        allowed = profile.origin_risk in self._allowed
        return {
            "allowed": allowed,
            "reason": (
                f"origin_risk={profile.origin_risk.value} not in allowed set" if not allowed else "origin_risk approved"
            ),
            "model_id": model_id,
            "developer_org": profile.developer_org,
            "origin_risk": profile.origin_risk.value,
            "headquarters_country": profile.headquarters_country,
        }


__all__ = ["ModelOriginPolicy", "ModelOriginProfile", "OriginRisk"]
