"""Tests for :mod:`stc_framework.governance.destruction`."""

from __future__ import annotations

from pathlib import Path

import pytest

from stc_framework.errors import LegalHoldActive
from stc_framework.governance.destruction import (
    DestructionMethod,
    crypto_erase,
    destroy_with_hold_check,
    overwrite_file,
    verify_destruction,
)


def test_overwrite_file_destroys_content_and_removes(tmp_path: Path) -> None:
    target = tmp_path / "secret.txt"
    target.write_bytes(b"top-secret-data" * 100)
    assert target.exists()
    assert overwrite_file(target, passes=2) is True
    assert verify_destruction(target) is True


def test_overwrite_missing_file_returns_false(tmp_path: Path) -> None:
    target = tmp_path / "nope.txt"
    assert overwrite_file(target) is False


def test_crypto_erase_removes_key_from_registry() -> None:
    registry = {"k-1": b"secret-key-material"}
    assert crypto_erase("k-1", key_registry=registry) is True
    assert "k-1" not in registry


def test_crypto_erase_missing_key_returns_false() -> None:
    registry: dict[str, bytes] = {}
    assert crypto_erase("missing", key_registry=registry) is False


@pytest.mark.asyncio
async def test_destroy_with_hold_check_allows_when_not_held(tmp_path: Path) -> None:
    target = tmp_path / "artifact.txt"
    target.write_bytes(b"junk")

    async def destroy_fn() -> bool:
        return overwrite_file(target, passes=1)

    class AllowAll:
        async def check_destruction_allowed(self, **_kwargs):  # type: ignore[no-untyped-def]
            return (True, None)

    record = await destroy_with_hold_check(
        data_store="filesystem",
        artifact=str(target),
        method=DestructionMethod.SECURE_OVERWRITE,
        destroy_fn=destroy_fn,
        legal_hold=AllowAll(),
    )
    assert record.verified is True
    assert not target.exists()


@pytest.mark.asyncio
async def test_destroy_with_hold_check_raises_when_held(tmp_path: Path) -> None:
    target = tmp_path / "held.txt"
    target.write_bytes(b"junk")

    async def destroy_fn() -> bool:  # pragma: no cover - should not be called
        return True

    class DenyAll:
        async def check_destruction_allowed(self, **_kwargs):  # type: ignore[no-untyped-def]
            return (False, "hold-42")

    with pytest.raises(LegalHoldActive) as ei:
        await destroy_with_hold_check(
            data_store="filesystem",
            artifact=str(target),
            method=DestructionMethod.SECURE_OVERWRITE,
            destroy_fn=destroy_fn,
            legal_hold=DenyAll(),
        )
    assert ei.value.hold_id == "hold-42"
    # Destroy function must NOT have run.
    assert target.exists()


@pytest.mark.asyncio
async def test_destroy_with_hold_check_works_without_registry() -> None:
    """When no legal-hold checker is provided, destruction runs directly."""
    called = {"n": 0}

    async def destroy_fn() -> bool:
        called["n"] += 1
        return True

    record = await destroy_with_hold_check(
        data_store="vector_store",
        artifact="collection/doc-1",
        method=DestructionMethod.CRYPTO_ERASE,
        destroy_fn=destroy_fn,
    )
    assert called["n"] == 1
    assert record.verified is True
    assert record.method is DestructionMethod.CRYPTO_ERASE
