"""Thin wrapper around ``ldclient.LDClient``.

Keeps the rest of the codebase decoupled from the LaunchDarkly SDK
symbol hierarchy (so a future flag vendor swap lands in this file
only), enforces fail-open semantics, and publishes fallback metrics.

The SDK itself is imported lazily: the ``launchdarkly-server-sdk``
package is installed only when the ``[launchdarkly]`` extra is present
in the image. Code paths that never construct
:class:`LaunchDarklyClient` do not import it, so an image built without
the extra still boots.
"""

from __future__ import annotations

import os
from typing import Any

from stc_framework._internal.metrics_safe import safe_inc
from stc_framework.config.logging import get_logger
from stc_framework.config.settings import STCSettings
from stc_framework.feature_flags.flags import FLAG_DEFAULTS, FlagKey
from stc_framework.observability.metrics import get_metrics

_logger = get_logger(__name__)


class LaunchDarklyUnavailable(Exception):
    """Raised when :class:`LaunchDarklyClient` is constructed without the SDK installed."""


class LaunchDarklyClient:
    """Fail-open wrapper around ``ldclient.LDClient``.

    ``variation(flag, context, default)`` never raises; any SDK error is
    caught, logged once, and the provided ``default`` is returned. Every
    fallback increments ``stc_feature_flag_fallback_total{flag}`` so
    dashboards can surface a "LD relay is flaky" signal before it hides
    real configuration changes.

    The underlying SDK client is cached per-process. Tests drive flag
    state via ``ldclient.integrations.test_data.TestData`` and inject
    the resulting ``data_source`` through :meth:`with_test_data`.
    """

    def __init__(
        self,
        settings: STCSettings,
        *,
        sdk_key: str | None = None,
        data_source: Any | None = None,
    ) -> None:
        self._settings = settings
        self._client: Any | None = None
        self._sdk_key = sdk_key or os.environ.get(settings.ld_sdk_key_env, "")
        self._data_source = data_source
        self._initialised = False

    # ------------------------------------------------------------------
    # Construction / teardown
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the LD SDK client. Idempotent.

        Uses the ``LDClient(config)`` direct constructor rather than
        ``ldclient.set_config()`` / ``ldclient.get()`` so multiple
        clients in the same process (e.g. tests) do not share the
        singleton. This matches LD SDK guidance for multi-instance
        embedding.
        """
        if self._initialised:
            return
        try:
            from ldclient import LDClient
            from ldclient.config import Config
        except ImportError as exc:
            raise LaunchDarklyUnavailable(
                "launchdarkly-server-sdk is not installed; "
                "rebuild the image with 'launchdarkly' in DEPLOYED_SUBSYSTEMS"
            ) from exc

        if self._settings.ld_offline_mode or not self._sdk_key:
            # Offline mode: serve only defaults / data_source. No
            # network traffic. Used in tests + air-gapped smokes.
            config_kwargs: dict[str, Any] = {"offline": True}
        else:
            config_kwargs = {"diagnostic_opt_out": True}
            if self._settings.ld_relay_url:
                config_kwargs["base_uri"] = self._settings.ld_relay_url
                config_kwargs["stream_uri"] = self._settings.ld_relay_url
                config_kwargs["events_uri"] = self._settings.ld_relay_url

        if self._data_source is not None:
            config_kwargs["update_processor_class"] = self._data_source

        config = Config(sdk_key=self._sdk_key or "offline", **config_kwargs)
        self._client = LDClient(config=config, start_wait=self._settings.ld_startup_timeout_sec)
        self._initialised = True

    def close(self) -> None:
        """Close the SDK client (flushes events)."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception as exc:  # pragma: no cover - defensive
                _logger.warning("feature_flags.close_failed", error=str(exc))
            self._client = None
            self._initialised = False

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def variation(
        self,
        flag: FlagKey,
        context: Any,
        default: bool | None = None,
    ) -> bool:
        """Evaluate ``flag`` for ``context``; fall back to the hard default on error.

        Never raises. Any SDK-level failure increments
        ``stc_feature_flag_fallback_total{flag}`` so a silent relay
        outage is visible.
        """
        fallback = default if default is not None else FLAG_DEFAULTS.get(flag, False)
        if not self._initialised:
            self.start()
        assert self._client is not None
        try:
            return bool(self._client.variation(flag.value, context, fallback))
        except Exception as exc:
            _logger.warning(
                "feature_flags.variation_failed",
                flag=flag.value,
                error=str(exc),
            )
            safe_inc(get_metrics().feature_flag_fallback_total, flag=flag.value)
            return fallback

    def is_initialized(self) -> bool:
        """Return True if the SDK has received its first flag payload.

        Used by ``/readyz`` and the ``stc-governance flags status`` CLI
        to surface LD health independently of application readiness.
        """
        if self._client is None:
            return False
        checker = getattr(self._client, "is_initialized", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return True


__all__ = ["LaunchDarklyClient", "LaunchDarklyUnavailable"]
