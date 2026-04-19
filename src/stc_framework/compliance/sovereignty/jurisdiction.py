"""Inference-location enforcement.

Operators declare which jurisdictions are acceptable for running
inference (e.g. "US-only, FIPS-compliant for restricted tier"). The
enforcer checks registered endpoints against that policy and filters
the ones that qualify.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InferenceEndpoint:
    endpoint_id: str
    jurisdiction: str  # "US", "EU", ...
    fips_compliant: bool = False
    fedramp_status: str = "none"  # none | low | moderate | high
    provider: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class InferenceJurisdictionEnforcer:
    def __init__(
        self,
        *,
        allowed_jurisdictions: set[str] | None = None,
        require_fips_for_restricted: bool = True,
    ) -> None:
        self._allowed = allowed_jurisdictions or {"US"}
        self._fips_for_restricted = require_fips_for_restricted
        self._endpoints: dict[str, InferenceEndpoint] = {}

    def register_endpoint(self, endpoint: InferenceEndpoint) -> None:
        self._endpoints[endpoint.endpoint_id] = endpoint

    def check(
        self,
        *,
        endpoint_id: str,
        data_tier: str = "public",
    ) -> dict[str, Any]:
        endpoint = self._endpoints.get(endpoint_id)
        if endpoint is None:
            return {"allowed": False, "reason": "endpoint not registered"}
        if endpoint.jurisdiction not in self._allowed:
            return {
                "allowed": False,
                "reason": f"jurisdiction {endpoint.jurisdiction} not in allowed set",
            }
        if data_tier == "restricted" and self._fips_for_restricted and not endpoint.fips_compliant:
            return {
                "allowed": False,
                "reason": "restricted tier requires FIPS-compliant endpoint",
            }
        return {
            "allowed": True,
            "endpoint_id": endpoint_id,
            "jurisdiction": endpoint.jurisdiction,
            "fips": endpoint.fips_compliant,
        }

    def filter_endpoints(self, *, data_tier: str = "public") -> list[str]:
        return [eid for eid in self._endpoints if self.check(endpoint_id=eid, data_tier=data_tier)["allowed"]]


__all__ = ["InferenceEndpoint", "InferenceJurisdictionEnforcer"]
