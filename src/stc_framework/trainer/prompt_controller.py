"""Prompt controller: registers new prompt versions and flips active pointer."""

from __future__ import annotations

from stc_framework.adapters.prompts.base import PromptRecord, PromptRegistry
from stc_framework.config.logging import get_logger
from stc_framework.governance.events import AuditEvent
from stc_framework.observability.audit import AuditLogger, AuditRecord

_logger = get_logger(__name__)


class PromptController:
    def __init__(
        self,
        registry: PromptRegistry,
        *,
        audit: AuditLogger | None = None,
    ) -> None:
        self._registry = registry
        self._audit = audit

    async def publish(
        self,
        *,
        name: str,
        version: str,
        content: str,
        activate: bool = True,
        metadata: dict[str, str] | None = None,
    ) -> PromptRecord:
        record = PromptRecord(
            name=name,
            version=version,
            content=content,
            active=activate,
            metadata=dict(metadata or {}),
        )
        await self._registry.register(record)
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    persona="trainer",
                    event_type=AuditEvent.PROMPT_REGISTERED.value,
                    action="register",
                    extra={"name": name, "version": version, "content_len": len(content)},
                )
            )
        if activate:
            await self._registry.set_active(name, version)
            if self._audit is not None:
                await self._audit.emit(
                    AuditRecord(
                        persona="trainer",
                        event_type=AuditEvent.PROMPT_ACTIVATED.value,
                        action="activate",
                        extra={"name": name, "version": version},
                    )
                )
        _logger.info("prompt.published", name=name, version=version, active=activate)
        return record
