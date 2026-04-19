"""Outbound notifications (Slack webhook, console).

All outbound payloads are stripped of fields that could plausibly carry
user content (queries, responses, chunks, tenant-identifying PII). Only
operational facts — trace id, rail names, counts, thresholds — are
allowed onto third-party channels.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from stc_framework.config.logging import get_logger

_logger = get_logger(__name__)

# Fields that must never leave the trust boundary in a notification.
_PII_RISK_FIELDS = {
    "query",
    "response",
    "context",
    "retrieved_chunks",
    "citations",
    "prompt",
    "messages",
    "metadata",
    "tenant_id",  # tenant IDs are sometimes emails / account IDs
    "email",
    "user",
    "user_id",
}


def _strip_pii(context: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``context`` with PII-risk fields removed (recursively)."""
    safe: dict[str, Any] = {}
    for k, v in context.items():
        if k in _PII_RISK_FIELDS:
            continue
        if isinstance(v, dict):
            safe[k] = _strip_pii(v)
        else:
            safe[k] = v
    return safe


class Notifier:
    """Fire-and-log notifier with PII scrubbing."""

    def __init__(self, *, slack_webhook_env: str = "SLACK_WEBHOOK_URL") -> None:
        self._slack_env = slack_webhook_env

    async def alert(
        self,
        message: str,
        *,
        channel: str = "trainer_dashboard",
        context: dict[str, Any] | None = None,
    ) -> None:
        """Send an alert via the appropriate channel; never raises."""
        safe_context = _strip_pii(context or {})
        if channel == "slack_webhook":
            url = os.getenv(self._slack_env)
            if not url:
                _logger.info(
                    "notifier.slack_skipped", reason="env unset", message=message
                )
                return
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(url, json={"text": message})
            except httpx.HTTPError as exc:
                _logger.warning("notifier.slack_failed", error=repr(exc))
            return

        # Default: structured log (already safe).
        _logger.warning(
            "notifier.alert", channel=channel, message=message, **safe_context
        )
