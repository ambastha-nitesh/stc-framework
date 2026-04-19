"""Applies model-reorder suggestions to the SentinelGateway."""

from __future__ import annotations

from stc_framework.config.logging import get_logger
from stc_framework.governance.events import AuditEvent
from stc_framework.observability.audit import AuditLogger, AuditRecord
from stc_framework.sentinel.gateway import SentinelGateway
from stc_framework.trainer.optimizer import OptimizationManager

_logger = get_logger(__name__)


class RoutingController:
    def __init__(
        self,
        gateway: SentinelGateway,
        optimizer: OptimizationManager,
        *,
        audit: AuditLogger | None = None,
    ) -> None:
        self._gateway = gateway
        self._optimizer = optimizer
        self._audit = audit

    def apply(self, tiers: list[str] | None = None) -> dict[str, list[str]]:
        """Re-order the routing preference for each tier based on observations."""
        tiers = tiers or ["public", "internal", "restricted"]
        applied: dict[str, list[str]] = {}
        for tier in tiers:
            ordered = self._optimizer.ordered_models_for_tier(tier)
            if ordered:
                self._gateway.set_routing_preference(tier, ordered)
                applied[tier] = ordered
                if self._audit is not None:
                    self._audit.emit_sync(
                        AuditRecord(
                            persona="trainer",
                            event_type=AuditEvent.ROUTING_UPDATED.value,
                            action="reorder",
                            extra={"tier": tier, "models": ordered},
                        )
                    )
        _logger.info("routing.applied", tiers=list(applied.keys()))
        return applied
