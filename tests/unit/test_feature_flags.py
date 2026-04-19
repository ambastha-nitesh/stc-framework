"""Tests for :mod:`stc_framework.feature_flags`.

Drives flag state via ``ldclient.integrations.test_data.TestData`` so
no LaunchDarkly endpoint or relay is required. The SDK is installed
into the dev venv because ``launchdarkly-server-sdk`` is in the
``[launchdarkly]`` extra which the CI matrix pulls in.
"""

from __future__ import annotations

import pytest

pytest.importorskip("ldclient", reason="launchdarkly-server-sdk not installed")

from ldclient.integrations.test_data import TestData

from stc_framework.config.settings import STCSettings
from stc_framework.feature_flags.client import (
    LaunchDarklyClient,
)
from stc_framework.feature_flags.flags import FLAG_DEFAULTS, FlagKey
from stc_framework.feature_flags.subsystem_registry import (
    SubsystemRegistry,
)
from stc_framework.observability.metrics import get_metrics


def _settings(**overrides) -> STCSettings:  # type: ignore[no-untyped-def]
    return STCSettings(
        env="dev",
        service_name="stc-framework-test",
        service_version="v0.3.1-test",
        **overrides,
    )


def test_flag_defaults_all_keys_covered() -> None:
    # The defaults table must supply every enum member — a new flag
    # without a default would crash SubsystemRegistry.evaluate().
    assert set(FLAG_DEFAULTS.keys()) == set(FlagKey)


def test_flag_key_string_format() -> None:
    # Dashboard operators rely on the ``stc.<subsystem>.<aspect>`` convention.
    for flag in FlagKey:
        parts = flag.value.split(".")
        assert len(parts) >= 3, flag.value
        assert parts[0] == "stc"


def test_offline_client_returns_defaults() -> None:
    settings = _settings(ld_offline_mode=True)
    client = LaunchDarklyClient(settings=settings)
    client.start()
    from ldclient import Context

    ctx = Context.builder("test").kind("service").build()
    for flag in FlagKey:
        assert client.variation(flag, ctx, FLAG_DEFAULTS[flag]) == FLAG_DEFAULTS[flag]
    client.close()


def test_test_data_source_drives_evaluation() -> None:
    td = TestData.data_source()
    td.update(td.flag(FlagKey.COMPLIANCE_ENABLED.value).variation_for_all(True))
    td.update(td.flag(FlagKey.THREAT_DETECTION_ENABLED.value).variation_for_all(False))

    settings = _settings(ld_offline_mode=False)
    client = LaunchDarklyClient(settings=settings, sdk_key="sdk-test", data_source=td)
    client.start()

    from ldclient import Context

    ctx = Context.builder("test").kind("service").build()
    assert client.variation(FlagKey.COMPLIANCE_ENABLED, ctx, False) is True
    assert client.variation(FlagKey.THREAT_DETECTION_ENABLED, ctx, True) is False
    client.close()


def test_variation_failure_increments_fallback_metric() -> None:
    """The LD SDK may still raise even with fail-open wrappers; count it."""

    class _Broken:
        def variation(self, _key, _ctx, _default):  # type: ignore[no-untyped-def]
            raise RuntimeError("LD is sad")

        def is_initialized(self) -> bool:
            return False

    settings = _settings(ld_offline_mode=True)
    client = LaunchDarklyClient(settings=settings)
    # Inject a broken SDK client directly — no ``start()`` call so we
    # never bring up the real LD client and there is nothing for the
    # real teardown path to close.
    client._client = _Broken()  # type: ignore[attr-defined]
    client._initialised = True  # type: ignore[attr-defined]

    from ldclient import Context

    before = (
        get_metrics()
        .feature_flag_fallback_total.labels(
            flag=FlagKey.COMPLIANCE_ENABLED.value,
        )
        ._value.get()
    )
    ctx = Context.builder("test").kind("service").build()
    assert client.variation(FlagKey.COMPLIANCE_ENABLED, ctx, False) is False
    after = (
        get_metrics()
        .feature_flag_fallback_total.labels(
            flag=FlagKey.COMPLIANCE_ENABLED.value,
        )
        ._value.get()
    )
    assert after == before + 1


def test_subsystem_registry_evaluates_full_flag_set() -> None:
    td = TestData.data_source()
    for flag in FlagKey:
        td.update(td.flag(flag.value).variation_for_all(True))
    settings = _settings()
    client = LaunchDarklyClient(settings=settings, sdk_key="sdk-test", data_source=td)
    client.start()
    reg = SubsystemRegistry(client)
    state = reg.evaluate(settings, deployed_subsystems=["service", "compliance"])
    assert set(state.keys()) == set(FlagKey)
    assert all(v is True for v in state.values())
    # Cached state returned by should_initialize.
    assert reg.should_initialize(FlagKey.COMPLIANCE_ENABLED) is True
    client.close()


def test_should_initialize_falls_back_to_default_if_not_evaluated() -> None:
    settings = _settings(ld_offline_mode=True)
    client = LaunchDarklyClient(settings=settings)
    reg = SubsystemRegistry(client)
    # No evaluate() call — should_initialize returns the hard default.
    assert reg.should_initialize(FlagKey.COMPLIANCE_ENABLED) is FLAG_DEFAULTS[FlagKey.COMPLIANCE_ENABLED]


def test_registry_context_carries_deployed_subsystems() -> None:
    captured: list[object] = []

    class _Capture:
        def variation(self, _key, ctx, _default):  # type: ignore[no-untyped-def]
            captured.append(ctx)
            return False

        def is_initialized(self) -> bool:
            return True

    settings = _settings(ld_offline_mode=True)
    client = LaunchDarklyClient(settings=settings)
    # Skip start()/close() — use the injected _Capture as the SDK stand-in.
    client._client = _Capture()  # type: ignore[attr-defined]
    client._initialised = True  # type: ignore[attr-defined]
    reg = SubsystemRegistry(client)
    reg.evaluate(settings, deployed_subsystems=["service", "launchdarkly"])
    assert captured, "registry did not invoke client.variation"
    ctx = captured[0]
    if isinstance(ctx, dict):
        assert ctx["deployed_subsystems"] == ["service", "launchdarkly"]
    else:
        assert ctx.get("deployed_subsystems") == ["service", "launchdarkly"]
