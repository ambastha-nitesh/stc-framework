"""Per-agent model allowlist + model catalogue (FR-1 + FR-10).

FR-10 mandates **default deny** — a freshly registered agent is
permitted to call exactly one model (``claude-haiku-4-5``). Additional
models must be added via an explicit approval workflow (out of this
library's scope — handled by the Registration Service dashboards).

This module owns:

* :class:`ModelCatalogEntry` — the MVP catalogue (PRD §4.1.10).
* :class:`ModelTier` — ``Standard`` vs. ``Restricted`` with approval
  semantics documented in the PRD.
* :class:`AgentAllowlist` — in-memory allowlist keyed by ``agent_id``
  with ``assert_allowed`` helper that raises the correct
  :class:`AIHubError` (``invalid_model_id`` or ``model_not_allowed``)
  per PRD Appendix A.

The in-memory implementation is the reference. A production
deployment would pair this with a Postgres-backed persistence layer
(the PRD's ``agent_model_allowlist`` table); the API stays identical
so swapping the store is a small change at ``STCSystem`` boot.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import RLock

from stc_framework.ai_hub.errors import AIHubError, AIHubErrorCode


class ModelTier(str, Enum):
    """Approval-tier labels per PRD §4.1.10.

    * ``STANDARD`` — Domain Admin may approve without escalation.
    * ``RESTRICTED`` — also requires Platform Admin approval AND the
      parent domain must be data-classification tier 3 or 4.
    """

    STANDARD = "standard"
    RESTRICTED = "restricted"


@dataclass(frozen=True)
class ModelCatalogEntry:
    """One row of the MVP model catalogue."""

    model_id: str
    bedrock_identifier: str
    tier: ModelTier
    context_window_tokens: int


# MVP catalogue (PRD §4.1.10). Extending the catalogue is a policy-
# store change in production; here we keep it importable as a baseline.
_MVP_CATALOG: dict[str, ModelCatalogEntry] = {
    "claude-haiku-4-5": ModelCatalogEntry(
        model_id="claude-haiku-4-5",
        bedrock_identifier="anthropic.claude-haiku-4-5-v1:0",
        tier=ModelTier.STANDARD,
        context_window_tokens=200_000,
    ),
    "claude-sonnet-4-6": ModelCatalogEntry(
        model_id="claude-sonnet-4-6",
        bedrock_identifier="anthropic.claude-sonnet-4-6-v1:0",
        tier=ModelTier.STANDARD,
        context_window_tokens=200_000,
    ),
    "claude-opus-4-7": ModelCatalogEntry(
        model_id="claude-opus-4-7",
        bedrock_identifier="anthropic.claude-opus-4-7-v1:0",
        tier=ModelTier.RESTRICTED,
        context_window_tokens=200_000,
    ),
    "titan-embed-text-v2": ModelCatalogEntry(
        model_id="titan-embed-text-v2",
        bedrock_identifier="amazon.titan-embed-text-v2:0",
        tier=ModelTier.STANDARD,
        context_window_tokens=8_192,
    ),
}

# Default allowlist for a brand-new agent. PRD §4.10 acceptance criteria
# AC-10.1 pins this to exactly ``claude-haiku-4-5``.
DEFAULT_AGENT_ALLOWLIST: tuple[str, ...] = ("claude-haiku-4-5",)


def default_catalog() -> dict[str, ModelCatalogEntry]:
    """Return a copy of the MVP catalogue."""
    return dict(_MVP_CATALOG)


class ModelAllowlistError(Exception):
    """Raised for invalid allowlist mutations (unknown model, etc.).

    Distinct from :class:`AIHubError` — allowlist management is
    out-of-band from request-path enforcement. The service layer
    translates these to the appropriate PRD envelope if they surface
    over HTTP.
    """


@dataclass
class AgentContext:
    """Subset of agent fields relevant to FR-1 / FR-10 enforcement.

    The full agent record (owner, runtime_environment, etc.) lives in
    the Registration Service's Postgres; this is the minimum Core needs
    on the request path.
    """

    agent_id: str
    domain_id: str
    domain_state: str  # 'ACTIVE', 'SUSPENDED', ...
    agent_state: str  # 'ACTIVE', 'SUSPENDED', ...
    data_classification_tier: int
    rpm_limit: int
    tpm_limit: int


class AgentAllowlist:
    """Per-agent allowlist with default-deny semantics.

    Thread-safe. In-memory; production deployments plug in a
    Postgres-backed implementation at the same call surface.
    """

    def __init__(
        self,
        *,
        catalog: dict[str, ModelCatalogEntry] | None = None,
    ) -> None:
        self._catalog = dict(catalog or _MVP_CATALOG)
        self._by_agent: dict[str, set[str]] = {}
        self._lock = RLock()

    # --- agent provisioning helpers ----------------------------------

    def register_agent(self, agent_id: str) -> None:
        """Register a brand-new agent with the default allowlist.

        PRD AC-10.1: defaults to exactly ``claude-haiku-4-5``.
        """
        with self._lock:
            self._by_agent[agent_id] = set(DEFAULT_AGENT_ALLOWLIST)

    def add_model(self, agent_id: str, model_id: str) -> None:
        """Add a model to an agent's allowlist.

        Raises :class:`ModelAllowlistError` if the model is not in the
        catalogue or the agent is not registered.
        """
        if model_id not in self._catalog:
            raise ModelAllowlistError(f"unknown model: {model_id!r}")
        with self._lock:
            if agent_id not in self._by_agent:
                raise ModelAllowlistError(f"unknown agent: {agent_id!r}")
            self._by_agent[agent_id].add(model_id)

    def remove_model(self, agent_id: str, model_id: str) -> None:
        with self._lock:
            if agent_id not in self._by_agent:
                return
            self._by_agent[agent_id].discard(model_id)

    def for_agent(self, agent_id: str) -> list[str]:
        """Return the sorted allowlist for an agent. Empty list if unknown."""
        with self._lock:
            return sorted(self._by_agent.get(agent_id, set()))

    # --- request-path enforcement ------------------------------------

    def assert_allowed(self, agent_id: str, model_id: str) -> ModelCatalogEntry:
        """Check ``model_id`` against the catalogue AND the agent's allowlist.

        Returns the :class:`ModelCatalogEntry` on success; raises
        :class:`AIHubError` with the PRD-appropriate code otherwise.
        """
        entry = self._catalog.get(model_id)
        if entry is None:
            raise AIHubError(
                code=AIHubErrorCode.INVALID_MODEL_ID,
                message=f"{model_id!r} is not in the model catalogue",
            )
        with self._lock:
            allowlist = self._by_agent.get(agent_id, set())
        if model_id not in allowlist:
            raise AIHubError(
                code=AIHubErrorCode.MODEL_NOT_ALLOWED,
                message=(
                    f"agent {agent_id!r} is not allowed to invoke model "
                    f"{model_id!r}; contact your Domain Admin to update the allowlist"
                ),
            )
        return entry

    def assert_agent_active(self, ctx: AgentContext) -> None:
        """Verify agent + domain are both ACTIVE (FR-1 §4.1.2 preconditions)."""
        if ctx.domain_state != "ACTIVE":
            raise AIHubError(code=AIHubErrorCode.DOMAIN_SUSPENDED)
        if ctx.agent_state != "ACTIVE":
            raise AIHubError(code=AIHubErrorCode.AGENT_SUSPENDED)

    def assert_restricted_tier_eligible(
        self,
        model_id: str,
        ctx: AgentContext,
    ) -> None:
        """Guard the PRD rule: tier-1/2 domains cannot use Restricted models.

        PRD §4.8.4 rejects Restricted-tier requests from low-classification
        domains at submission time. This helper replays the same check at
        request-path enforcement so a policy-store drift (an allowlist
        entry that slipped through) still fails closed.
        """
        entry = self._catalog.get(model_id)
        if entry is None:
            return
        if entry.tier is ModelTier.RESTRICTED and ctx.data_classification_tier < 3:
            raise AIHubError(
                code=AIHubErrorCode.RESTRICTED_MODEL_NOT_ELIGIBLE,
                message=(
                    f"model {model_id!r} is restricted-tier; parent domain " f"must be data-classification tier 3 or 4"
                ),
            )


__all__ = [
    "DEFAULT_AGENT_ALLOWLIST",
    "AgentAllowlist",
    "AgentContext",
    "ModelAllowlistError",
    "ModelCatalogEntry",
    "ModelTier",
    "default_catalog",
]
