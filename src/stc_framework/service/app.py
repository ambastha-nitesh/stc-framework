"""Flask app factory for the STC reference service."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

try:
    from flask import Flask, Response, g, jsonify, request
except ImportError as exc:  # pragma: no cover - optional extra
    raise ImportError(
        "Flask not installed; install with `pip install stc-framework[service]`"
    ) from exc

from stc_framework.config.logging import get_logger
from stc_framework.errors import STCError, http_status_for
from stc_framework.observability.correlation import bind_correlation, new_request_id
from stc_framework.resilience.degradation import get_degradation_state
from stc_framework.security.limits import get_security_limits
from stc_framework.security.sanitize import sanitize_header_value
from stc_framework.service.middleware import register_error_handlers, register_rate_limiter
from stc_framework.service.routes import register_routes
from stc_framework.system import STCSystem

_logger = get_logger(__name__)


class _SystemRunner:
    """Owns a single :class:`STCSystem` and a dedicated event loop thread.

    The loop is reused across requests so every call is non-blocking for the
    Flask worker thread. Calls are submitted via
    :func:`asyncio.run_coroutine_threadsafe` and blocked on until complete.
    """

    def __init__(self, system: STCSystem) -> None:
        self.system = system
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="stc-loop", daemon=True)
        self._thread.start()
        self._ready = threading.Event()
        asyncio.run_coroutine_threadsafe(
            self._startup(), self._loop
        ).result(timeout=30)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _startup(self) -> None:
        await self.system.astart()

    def submit(self, coro: Any, *, timeout: float = 60.0) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def shutdown(self, *, drain_timeout: float = 30.0) -> None:
        """Graceful shutdown.

        Submits ``astop(drain_timeout)`` to the event loop and waits long
        enough for the drain to complete (``drain_timeout`` + a small
        grace margin) before stopping the loop.
        """
        try:
            self.submit(
                self.system.astop(drain_timeout=drain_timeout),
                timeout=drain_timeout + 5.0,
            )
        except Exception:
            # Even if drain timed out, tear the loop down — better to lose
            # a few in-flight requests than to hang the process.
            pass
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)


def create_app(
    system: STCSystem | None = None,
    *,
    enable_rate_limit: bool = True,
) -> Flask:
    """Build a Flask app bound to an :class:`STCSystem` instance."""
    limits = get_security_limits()

    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    # Hard request-body cap; Werkzeug returns 413 before our code is invoked
    # if the client streams more bytes than this.
    app.config["MAX_CONTENT_LENGTH"] = limits.max_request_bytes

    sys_instance = system or STCSystem.from_env()
    runner = _SystemRunner(sys_instance)
    app.extensions["stc_runner"] = runner

    @app.before_request
    def _bind_request() -> None:
        # Reject wildly oversized Content-Length before reading the body.
        length = request.content_length
        if length is not None and length > limits.max_request_bytes:
            from flask import abort

            abort(413)

        # Sanitize incoming header values so an attacker cannot smuggle
        # CR/LF into logs or forge correlation IDs.
        incoming_req_id = sanitize_header_value(
            request.headers.get("X-Request-Id"),
            limit=limits.max_header_value_chars,
        )
        g.request_id = incoming_req_id or new_request_id()
        g.tenant_id = sanitize_header_value(
            request.headers.get("X-Tenant-Id"),
            limit=limits.max_header_value_chars,
        )

    @app.after_request
    def _security_headers(response: Response) -> Response:
        response.headers["X-Request-Id"] = g.get("request_id", "")
        # Harden responses — these apply even for JSON endpoints; they are
        # cheap and future-proof the service against being embedded in a
        # browser context by mistake.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Cache-Control", "no-store, no-cache, must-revalidate, private"
        )
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
        )
        return response

    register_error_handlers(app)
    if enable_rate_limit:
        register_rate_limiter(app)
    register_routes(app, runner)

    # Register SIGTERM / SIGINT handlers so Kubernetes / systemd / gunicorn
    # pre-stop hooks trigger a clean drain instead of killing in-flight
    # requests. Registration is best-effort — in some WSGI servers signal
    # handlers are owned by the master process.
    import signal

    def _graceful_exit(signum, _frame):
        _logger.warning("service.signal", signal=signum)
        runner.shutdown(drain_timeout=30.0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _graceful_exit)
        except (ValueError, OSError):  # pragma: no cover - non-main thread
            pass

    @app.teardown_appcontext
    def _teardown(_: BaseException | None) -> None:
        # no-op; the runner persists for the app lifetime
        return None

    return app
