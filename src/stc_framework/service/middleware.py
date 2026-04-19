"""Error handlers and rate-limiter for the Flask service."""

from __future__ import annotations

from typing import Any

from flask import Flask, g, jsonify, request

from stc_framework.config.logging import get_logger
from stc_framework.errors import STCError, http_status_for

_logger = get_logger(__name__)


def register_error_handlers(app: Flask) -> None:
    from werkzeug.exceptions import HTTPException

    @app.errorhandler(STCError)
    def _handle_stc_error(err: STCError) -> Any:
        status = http_status_for(err)
        _logger.warning(
            "service.error",
            error_type=type(err).__name__,
            status=status,
            downstream=err.downstream,
            retryable=err.retryable,
            details=err.message,
        )
        return (
            jsonify(
                {
                    "error": type(err).__name__,
                    "message": err.message or str(err),
                    "retryable": err.retryable,
                    "request_id": g.get("request_id"),
                }
            ),
            status,
        )

    @app.errorhandler(HTTPException)
    def _handle_http_exception(err: HTTPException) -> Any:
        # Werkzeug already knows the correct status (e.g. 413, 404, 405);
        # preserve it instead of masking as 500. Never leak the default
        # HTML error page since this is a JSON API.
        status = err.code or 500
        _logger.info("service.http_exception", status=status, name=err.name)
        return (
            jsonify(
                {
                    "error": err.name.replace(" ", ""),
                    "message": err.description or err.name,
                    "request_id": g.get("request_id"),
                }
            ),
            status,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception) -> Any:
        _logger.exception("service.unhandled", error_type=type(err).__name__)
        # Never leak internal error class names / stack traces to clients.
        return (
            jsonify(
                {
                    "error": "InternalServerError",
                    "message": "An unexpected error occurred.",
                    "request_id": g.get("request_id"),
                }
            ),
            500,
        )


def register_rate_limiter(app: Flask) -> None:
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address
    except ImportError:  # pragma: no cover
        _logger.info("service.flask_limiter_unavailable")
        return

    def key_func() -> str:
        return request.headers.get("X-Tenant-Id") or get_remote_address()

    limiter = Limiter(
        key_func=key_func,
        app=app,
        default_limits=["1000 per minute"],
        storage_uri="memory://",
    )
    app.extensions["stc_limiter"] = limiter
