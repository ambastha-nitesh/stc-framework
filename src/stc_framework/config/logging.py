"""Structured logging via structlog with PII-safe defaults."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

_REDACTED = "<redacted>"
_PII_KEYS = {"query", "response", "content", "prompt", "user_input"}

_configured = False


def _drop_pii_keys(
    _: Any, __: str, event_dict: EventDict
) -> EventDict:  # pragma: no cover - trivial
    """Drop or redact keys likely to contain user content when log_content is off."""
    for key in list(event_dict.keys()):
        if key in _PII_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def _bind_otel_context(_: Any, __: str, event_dict: EventDict) -> EventDict:
    """Bind the current OpenTelemetry trace/span id into every log record."""
    try:
        from opentelemetry import trace as otel_trace

        span = otel_trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx is not None and ctx.is_valid:
            event_dict.setdefault("trace_id", format(ctx.trace_id, "032x"))
            event_dict.setdefault("span_id", format(ctx.span_id, "016x"))
    except Exception:  # pragma: no cover - never let logging break
        pass
    return event_dict


def _bind_correlation(_: Any, __: str, event_dict: EventDict) -> EventDict:
    """Attach correlation fields (tenant_id, persona, request_id)."""
    from stc_framework.observability.correlation import current_correlation

    corr = current_correlation()
    for key, value in corr.items():
        if value is not None:
            event_dict.setdefault(key, value)
    return event_dict


def configure_logging(
    *,
    level: str = "INFO",
    fmt: str = "json",
    log_content: bool = False,
) -> None:
    """Idempotently configure structlog + stdlib logging.

    Call once near process startup. Safe to call repeatedly; subsequent calls
    only mutate the level/format.
    """
    global _configured

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
        force=True,
    )

    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _bind_otel_context,
        _bind_correlation,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if not log_content:
        processors.append(_drop_pii_keys)

    if fmt == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger, configuring defaults on first use."""
    if not _configured:
        configure_logging()
    return structlog.get_logger(name) if name else structlog.get_logger()
