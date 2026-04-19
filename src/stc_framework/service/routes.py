"""HTTP routes for the Flask service."""

from __future__ import annotations

from flask import Flask, Response, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from stc_framework.config.logging import get_logger
from stc_framework.observability.correlation import bind_correlation
from stc_framework.security.limits import get_security_limits
from stc_framework.security.sanitize import sanitize_header_value

_logger = get_logger(__name__)


def register_routes(app: Flask, runner) -> None:
    system = runner.system

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"}), 200

    @app.get("/readyz")
    def readyz():
        # Actually probe every adapter rather than returning a stale
        # "degradation is normal" answer. Kubernetes / ALB readiness
        # checks rely on this to mark an unhealthy pod out-of-service.
        try:
            report = runner.submit(system.ahealth_probe(timeout=2.0), timeout=5.0)
        except Exception as exc:
            return (
                jsonify({"status": "unhealthy", "error": type(exc).__name__}),
                503,
            )
        payload = {
            "status": "ready" if report.ok else "unhealthy",
            "checked_at": report.checked_at,
            "degradation_level": report.degradation_level,
            "inflight_requests": report.inflight_requests,
            "adapters": [{"name": a.name, "ok": a.ok, "detail": a.detail} for a in report.adapters],
        }
        return jsonify(payload), (200 if report.ok else 503)

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    @app.get("/v1/spec")
    def spec():
        return jsonify(
            {
                "name": system.spec.name,
                "version": system.spec.version,
                "description": system.spec.description,
            }
        )

    limits = get_security_limits()

    @app.post("/v1/query")
    def query():
        data = request.get_json(silent=True) or {}
        user_query = data.get("query")
        if not isinstance(user_query, str) or not user_query.strip():
            return jsonify({"error": "BadRequest", "message": "query is required"}), 400
        if len(user_query) > limits.max_query_chars:
            return (
                jsonify(
                    {
                        "error": "PayloadTooLarge",
                        "message": f"query exceeds {limits.max_query_chars} chars",
                    }
                ),
                413,
            )
        # Prefer the sanitized header-bound tenant; only accept the body
        # field as a fallback (also sanitized) so request body cannot
        # forge a tenant id past the header-level sanitizer.
        tenant_id = g.get("tenant_id") or sanitize_header_value(
            data.get("tenant_id"), limit=limits.max_header_value_chars
        )
        with bind_correlation(request_id=g.request_id, tenant_id=tenant_id):
            result = runner.submit(system.aquery(user_query, tenant_id=tenant_id))
        return jsonify(
            {
                "trace_id": result.trace_id,
                "response": result.response,
                "governance": result.governance,
                "optimization": result.optimization,
                "metadata": result.metadata,
            }
        )

    @app.post("/v1/feedback")
    def feedback():
        data = request.get_json(silent=True) or {}
        trace_id = data.get("trace_id")
        value = data.get("feedback")
        if not isinstance(trace_id, str) or not isinstance(value, str):
            return (
                jsonify(
                    {
                        "error": "BadRequest",
                        "message": "trace_id and feedback are required strings",
                    }
                ),
                400,
            )
        # Feedback values are constrained to a small vocabulary so a
        # malicious caller cannot dump arbitrary text into the Trainer's
        # signal metadata (which ultimately lands in audit logs).
        allowed_feedback = {
            "thumbs_up",
            "thumbs_down",
            "positive",
            "negative",
            "correct",
            "incorrect",
            "good",
            "bad",
            "yes",
            "no",
        }
        if value.lower() not in allowed_feedback:
            return (
                jsonify(
                    {
                        "error": "BadRequest",
                        "message": "feedback must be one of " + ", ".join(sorted(allowed_feedback)),
                    }
                ),
                400,
            )
        # Defensive bounds on trace_id length — the system mints short ids.
        if len(trace_id) > 128:
            return (
                jsonify({"error": "BadRequest", "message": "trace_id too long"}),
                400,
            )
        system.submit_feedback(trace_id, value)
        return jsonify({"status": "recorded"})
