"""OpenTelemetry tracing setup.

Idempotent initializer that installs a TracerProvider with service-name
resource attributes and an optional OTLP exporter. If no endpoint is
configured, spans are simply recorded in a noop processor — calls to
``get_tracer`` always succeed.
"""

from __future__ import annotations

from threading import Lock
from typing import Any

from opentelemetry import trace as otel_trace

_lock = Lock()
_initialized = False


def init_tracing(
    *,
    service_name: str = "stc-framework",
    service_version: str = "0.2.0",
    otlp_endpoint: str | None = None,
    spec_version: str | None = None,
    extra_resource: dict[str, Any] | None = None,
) -> None:
    """Configure the global :class:`TracerProvider` if not already set.

    Safe to call multiple times; only the first call installs the provider.
    """
    global _initialized
    with _lock:
        if _initialized:
            return

        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import (
                BatchSpanProcessor,
                ConsoleSpanExporter,
                SimpleSpanProcessor,
            )
        except ImportError:  # pragma: no cover - sdk is a core dep
            _initialized = True
            return

        attrs: dict[str, Any] = {
            "service.name": service_name,
            "service.version": service_version,
        }
        if spec_version:
            attrs["stc.spec_version"] = spec_version
        if extra_resource:
            attrs.update(extra_resource)

        provider = TracerProvider(resource=Resource.create(attrs))

        if otlp_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter,
                )

                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
            except ImportError:  # pragma: no cover - optional extra
                # Fall back to console exporter so spans don't vanish silently.
                provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

        otel_trace.set_tracer_provider(provider)
        _initialized = True


def get_tracer(name: str) -> otel_trace.Tracer:
    """Return a tracer; works even if :func:`init_tracing` was never called."""
    return otel_trace.get_tracer(name)


def reset_tracing_for_tests() -> None:
    """Allow tests to re-initialize tracing."""
    global _initialized
    with _lock:
        _initialized = False
