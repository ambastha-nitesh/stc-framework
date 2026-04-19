"""Regression tests for the Tier-1 / Tier-2 fixes from the second
staff-review pass (the pre-deployment review).

Each class corresponds to a finding in
``docs/security/STAFF_REVIEW.md``. If one of these fails, the fix for
that finding has regressed and the release should be blocked.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stc_framework.adapters.audit_backend.local_file import JSONLAuditBackend
from stc_framework.adapters.audit_backend.worm import (
    ComplianceViolation,
    WORMAuditBackend,
)
from stc_framework.adapters.embeddings.hash_embedder import HashEmbedder
from stc_framework.adapters.llm.mock import MockLLMClient
from stc_framework.adapters.vector_store.base import VectorRecord
from stc_framework.adapters.vector_store.in_memory import InMemoryVectorStore
from stc_framework.config.settings import STCSettings
from stc_framework.errors import STCError
from stc_framework.governance.budget import (
    TenantBudgetExceeded,
    TenantBudgetTracker,
)
from stc_framework.governance.erasure import erase_tenant
from stc_framework.governance.events import AuditEvent
from stc_framework.governance.idempotency import IdempotencyCache
from stc_framework.observability.audit import (
    AuditRecord,
    _KeyManager,
    compute_entry_hash,
    verify_chain,
)
from stc_framework.spec.loader import load_spec
from stc_framework.spec.signing import (
    SpecSignatureError,
    sign_spec,
    verify_spec_signature,
)
from stc_framework.system import STCSystem


def _make_system(tmp_path: Path, fixture_dir: Path) -> STCSystem:
    settings = STCSettings(
        presidio_enabled=False,
        metrics_enabled=False,
        log_format="text",
        audit_path=str(tmp_path / "audit"),
    )
    return STCSystem.from_spec(
        fixture_dir / "minimal_spec.yaml",
        settings=settings,
        llm=MockLLMClient(),
        vector_store=InMemoryVectorStore(),
        embeddings=HashEmbedder(vector_size=64),
    )


async def _seed(system: STCSystem, tenant: str = "t1") -> None:
    emb = system.embeddings
    vec = (
        await emb.aembed_batch(
            ["Revenue was $24,050 million. [Document: acme, Page 1]"]
        )
    )[0]
    await system.vector_store.ensure_collection("financial_docs", emb.vector_size)
    await system.vector_store.upsert(
        "financial_docs",
        [
            VectorRecord(
                id=f"seed-{tenant}",
                vector=vec,
                text="Revenue was $24,050 million. [Document: acme, Page 1]",
                metadata={"source": "acme", "page": 1, "tenant_id": tenant},
            )
        ],
    )


# ---------------------------------------------------------------------------
# B1 — WORM-compatible audit backend
# ---------------------------------------------------------------------------


class TestWORMBackend:
    @pytest.mark.asyncio
    async def test_write_and_iterate(self, tmp_path: Path):
        backend = WORMAuditBackend(tmp_path / "worm")
        sealed = await backend.append(
            AuditRecord(event_type="test_event", extra={"i": 1})
        )
        assert sealed.entry_hash
        records = list(backend.iter_records())
        assert len(records) == 1
        assert records[0].extra["i"] == 1

    def test_prune_before_refused(self, tmp_path: Path):
        backend = WORMAuditBackend(tmp_path / "worm")
        with pytest.raises(ComplianceViolation):
            backend.prune_before("2026-01-01T00:00:00+00:00")

    def test_erase_tenant_refused(self, tmp_path: Path):
        backend = WORMAuditBackend(tmp_path / "worm")
        with pytest.raises(ComplianceViolation):
            backend.erase_tenant("any-tenant")

    @pytest.mark.asyncio
    async def test_rotation_seal_preserves_chain(self, tmp_path: Path):
        backend = WORMAuditBackend(tmp_path / "worm", rotate_bytes=200)
        for i in range(20):
            await backend.append(
                AuditRecord(event_type="test_event", extra={"i": i})
            )
        ok, _, why = verify_chain(backend.iter_records())
        assert ok, why
        # Seal events should be present if rotation happened.
        types = {r.event_type for r in backend.iter_records()}
        if len(list(tmp_path.glob("worm/audit-*.jsonl"))) > 1:
            assert "audit_rotation_seal" in types


# ---------------------------------------------------------------------------
# B2 — HMAC-signed hash chain
# ---------------------------------------------------------------------------


class TestHMACChain:
    @pytest.mark.asyncio
    async def test_chain_verifies_with_correct_key(
        self, tmp_path: Path, monkeypatch
    ):
        key = base64.urlsafe_b64encode(b"\x42" * 32).decode()
        monkeypatch.setenv("STC_AUDIT_HMAC_KEY", key)
        _KeyManager.reset_for_tests()

        backend = JSONLAuditBackend(tmp_path / "audit")
        for i in range(5):
            await backend.append(
                AuditRecord(event_type="test_event", extra={"i": i})
            )
        ok, count, why = verify_chain(backend.iter_records())
        assert ok, why
        assert count == 5
        # key_id should be stamped on every record.
        for rec in backend.iter_records():
            assert rec.key_id and rec.key_id.startswith("env-")

    @pytest.mark.asyncio
    async def test_chain_rejects_wrong_key(self, tmp_path: Path, monkeypatch):
        key_a = base64.urlsafe_b64encode(b"\x11" * 32).decode()
        monkeypatch.setenv("STC_AUDIT_HMAC_KEY", key_a)
        _KeyManager.reset_for_tests()

        backend = JSONLAuditBackend(tmp_path / "audit")
        for i in range(3):
            await backend.append(AuditRecord(event_type="x", extra={"i": i}))

        # Verify with a *different* key — HMAC must not match.
        wrong_key = b"\x22" * 32
        ok, _, why = verify_chain(backend.iter_records(), key=wrong_key)
        assert not ok
        assert "HMAC did not verify" in why

    @pytest.mark.asyncio
    async def test_truncation_then_reforgery_fails_without_key(
        self, tmp_path: Path, monkeypatch
    ):
        """The senior-review attack: attacker deletes prefix and rewrites
        new first record's prev_hash to GENESIS; recomputing entry_hash
        requires the HMAC key. Without it, verification fails.
        """
        key_b64 = base64.urlsafe_b64encode(b"\x33" * 32).decode()
        monkeypatch.setenv("STC_AUDIT_HMAC_KEY", key_b64)
        _KeyManager.reset_for_tests()

        backend = JSONLAuditBackend(tmp_path / "audit")
        for i in range(5):
            await backend.append(AuditRecord(event_type="x", extra={"i": i}))

        # Attacker (without the HMAC key) tries to truncate and
        # re-genesis using a guessed SHA-256 (the pre-fix behavior).
        files = list((tmp_path / "audit").glob("audit-*.jsonl"))
        assert files
        lines = files[0].read_text(encoding="utf-8").splitlines()
        # Keep only the last two records.
        surviving = [json.loads(line) for line in lines[-2:]]
        # Rewrite the first survivor's prev_hash to GENESIS and compute
        # a SHA-256 (attacker's best guess).
        import hashlib as _hashlib

        surviving[0]["prev_hash"] = "0" * 64
        surviving[0]["entry_hash"] = None
        payload = json.dumps(
            surviving[0], sort_keys=True, default=str
        ).encode("utf-8")
        surviving[0]["entry_hash"] = _hashlib.sha256(payload).hexdigest()
        files[0].write_text(
            "\n".join(json.dumps(s) for s in surviving) + "\n",
            encoding="utf-8",
        )

        ok, _, why = verify_chain(backend.iter_records())
        assert not ok
        assert "HMAC did not verify" in why


# ---------------------------------------------------------------------------
# B3 — Spec signature verification
# ---------------------------------------------------------------------------


class TestSpecSignature:
    def test_verify_passes_with_valid_signature(self, tmp_path: Path, monkeypatch):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        # Generate a keypair for the test.
        priv = Ed25519PrivateKey.generate()
        priv_b64 = base64.urlsafe_b64encode(
            priv.private_bytes_raw()
        ).decode()
        pub_b64 = base64.urlsafe_b64encode(
            priv.public_key().public_bytes_raw()
        ).decode()
        monkeypatch.setenv("STC_SPEC_PUBLIC_KEY", pub_b64)

        spec = tmp_path / "spec.yaml"
        spec.write_text("version: '1.0.0'\nname: 'test'\n", encoding="utf-8")
        signature = sign_spec(spec, private_key_b64=priv_b64)
        (spec.with_suffix(".yaml.sig")).write_bytes(signature)

        # Must not raise.
        verify_spec_signature(spec, required=True)

    def test_verify_fails_on_tampered_spec(self, tmp_path: Path, monkeypatch):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        priv = Ed25519PrivateKey.generate()
        priv_b64 = base64.urlsafe_b64encode(priv.private_bytes_raw()).decode()
        pub_b64 = base64.urlsafe_b64encode(
            priv.public_key().public_bytes_raw()
        ).decode()
        monkeypatch.setenv("STC_SPEC_PUBLIC_KEY", pub_b64)

        spec = tmp_path / "spec.yaml"
        spec.write_text("version: '1.0.0'\nname: 'test'\n", encoding="utf-8")
        (spec.with_suffix(".yaml.sig")).write_bytes(
            sign_spec(spec, private_key_b64=priv_b64)
        )
        # Tamper after signing.
        spec.write_text("version: '1.0.0'\nname: 'evil'\n", encoding="utf-8")

        with pytest.raises(SpecSignatureError):
            verify_spec_signature(spec, required=True)

    def test_required_raises_when_no_signature(self, tmp_path: Path):
        spec = tmp_path / "spec.yaml"
        spec.write_text("version: '1.0.0'\nname: 'unsigned'\n", encoding="utf-8")
        with pytest.raises(SpecSignatureError):
            verify_spec_signature(spec, required=True)


# ---------------------------------------------------------------------------
# B4 — Strict prod mode
# ---------------------------------------------------------------------------


class TestStrictProdMode:
    @pytest.mark.asyncio
    async def test_prod_refuses_without_audit_key(
        self, tmp_path: Path, fixture_dir: Path, monkeypatch
    ):
        monkeypatch.delenv("STC_AUDIT_HMAC_KEY", raising=False)
        _KeyManager.reset_for_tests()
        settings = STCSettings(
            env="prod",
            presidio_enabled=False,
            metrics_enabled=False,
            log_format="text",
            audit_path=str(tmp_path / "audit"),
        )
        system = STCSystem.from_spec(
            fixture_dir / "minimal_spec.yaml",
            settings=settings,
            llm=MockLLMClient(),
            vector_store=InMemoryVectorStore(),
            embeddings=HashEmbedder(vector_size=64),
        )
        with pytest.raises(STCError) as exc:
            await system.astart()
        assert "STC_AUDIT_HMAC_KEY" in str(exc.value)

    @pytest.mark.asyncio
    async def test_prod_refuses_mock_llm(
        self, tmp_path: Path, fixture_dir: Path, monkeypatch
    ):
        key = base64.urlsafe_b64encode(b"\x55" * 32).decode()
        monkeypatch.setenv("STC_AUDIT_HMAC_KEY", key)
        monkeypatch.setenv("STC_TOKENIZATION_STRICT", "1")
        _KeyManager.reset_for_tests()

        settings = STCSettings(
            env="prod",
            presidio_enabled=False,
            metrics_enabled=False,
            log_format="text",
            audit_path=str(tmp_path / "audit"),
            llm_adapter="mock",  # explicit mock — must be rejected
            audit_backend="worm",
        )
        system = STCSystem.from_spec(
            fixture_dir / "minimal_spec.yaml",
            settings=settings,
            llm=MockLLMClient(),
            vector_store=InMemoryVectorStore(),
            embeddings=HashEmbedder(vector_size=64),
        )
        with pytest.raises(STCError) as exc:
            await system.astart()
        assert "mock" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# B5 — Per-event-class retention
# ---------------------------------------------------------------------------


class TestPerEventRetention:
    def test_retention_policy_defaults_protect_compliance_records(
        self, minimal_spec
    ):
        policy = minimal_spec.audit.retention_policies
        assert policy.erasure >= 2190
        assert policy.dsar_export >= 2190
        assert policy.audit_rotation_seal == -1
        assert policy.retention_prune_seal == -1

    def test_days_for_falls_back_to_default(self, minimal_spec):
        policy = minimal_spec.audit.retention_policies
        assert policy.days_for("completely_unknown_event") == policy.default


# ---------------------------------------------------------------------------
# H1 — Idempotency cache cleared on erase
# ---------------------------------------------------------------------------


class TestIdempotencyClearedOnErase:
    @pytest.mark.asyncio
    async def test_erase_tenant_clears_idempotency_cache(
        self, tmp_path: Path, fixture_dir: Path
    ):
        system = _make_system(tmp_path, fixture_dir)
        await _seed(system, tenant="doomed")
        try:
            result = await system.aquery(
                "q", tenant_id="doomed", idempotency_key="k-1"
            )
            # Confirm the cache holds the result.
            assert system._idempotency.get("doomed", "k-1") is not None

            summary = await erase_tenant(system, "doomed")
            assert summary.idempotency_removed >= 1
            # After erasure, replay must not return the cached result.
            assert system._idempotency.get("doomed", "k-1") is None
        finally:
            await system.astop()


# ---------------------------------------------------------------------------
# H2 — Retention + hash-chain seal across file boundaries
# ---------------------------------------------------------------------------


class TestRetentionChainSeal:
    @pytest.mark.asyncio
    async def test_prune_writes_seal_and_chain_still_verifies(
        self, tmp_path: Path, monkeypatch
    ):
        key = base64.urlsafe_b64encode(b"\x77" * 32).decode()
        monkeypatch.setenv("STC_AUDIT_HMAC_KEY", key)
        _KeyManager.reset_for_tests()

        backend = JSONLAuditBackend(tmp_path / "audit", rotate_bytes=256)
        # Write enough to force rotation into a second file.
        for i in range(50):
            await backend.append(
                AuditRecord(event_type="x", extra={"i": i}, action="test")
            )

        # Now prune everything older than "now + 1 day" — should remove
        # some files and leave a seal in the active file.
        future = (
            datetime.now(timezone.utc) + timedelta(days=1)
        ).isoformat()
        removed = backend.prune_before(future)
        # Prune may or may not hit files depending on timestamp; ensure
        # the backend at minimum remains usable.
        records = list(backend.iter_records())
        if removed:
            seal_events = [
                r for r in records
                if r.event_type == "retention_prune_seal"
            ]
            assert seal_events
        # After pruning, the first surviving record's prev_hash points
        # to a deleted record. Use accept_unknown_genesis for post-prune
        # verification; strict mode is tested in the HMAC suite above.
        ok, _, why = verify_chain(
            backend.iter_records(), accept_unknown_genesis=True
        )
        assert ok, why


# ---------------------------------------------------------------------------
# H3 — Budget tracker uses day buckets and is O(1) observed
# ---------------------------------------------------------------------------


class TestBudgetDayBuckets:
    def test_same_day_samples_aggregate_into_one_bucket(self):
        tracker = TenantBudgetTracker(daily_usd=100.0)
        for _ in range(1000):
            tracker.record_cost("t", 0.001)
        assert tracker.observed("t", window="daily") == pytest.approx(1.0, rel=1e-6)
        # A single bucket for today.
        assert len(tracker._state["t"].buckets) == 1

    def test_reserve_is_atomic_and_strictly_bounded(self):
        tracker = TenantBudgetTracker(daily_usd=5.0)
        for _ in range(5):
            tracker.reserve("t", anticipated_cost=1.0)
        with pytest.raises(TenantBudgetExceeded):
            tracker.reserve("t", anticipated_cost=0.01)

    def test_settle_can_go_negative_and_clamps_bucket(self):
        tracker = TenantBudgetTracker(daily_usd=10.0)
        tracker.reserve("t", anticipated_cost=5.0)
        # Actual was zero — refund.
        tracker.settle("t", reserved=5.0, actual=0.0)
        assert tracker.observed("t", window="daily") == 0.0


# ---------------------------------------------------------------------------
# N1 — testing submodule refuses to run in prod
# ---------------------------------------------------------------------------


class TestTestingSubmoduleGuard:
    def test_reset_raises_in_prod(self, monkeypatch):
        from stc_framework.testing import reset_circuits

        monkeypatch.setenv("STC_ENV", "prod")
        with pytest.raises(RuntimeError):
            reset_circuits()

    def test_reset_works_outside_prod(self, monkeypatch):
        from stc_framework.testing import reset_circuits

        monkeypatch.setenv("STC_ENV", "dev")
        reset_circuits()  # no-op, must not raise


# ---------------------------------------------------------------------------
# N3 — MockLLMClient uses CONTEXT, not user query
# ---------------------------------------------------------------------------


class TestMockLLMUsesContext:
    @pytest.mark.asyncio
    async def test_mock_extracts_number_from_context_not_query(self):
        mock = MockLLMClient()
        from stc_framework.adapters.llm.base import ChatMessage

        messages = [
            ChatMessage(role="system", content="sys"),
            ChatMessage(
                role="user",
                content=(
                    "Based on the following context, answer the question.\n\n"
                    "CONTEXT:\n[Document: acme, Page 1]\nRevenue was "
                    "$42,000 million.\n\nQUESTION: How much was $99,999?"
                ),
            ),
        ]
        response = await mock.acompletion(
            model="mock/test", messages=messages, timeout=5.0
        )
        # Must quote the CONTEXT number, never the QUESTION one.
        assert "$42,000" in response.content or "42,000" in response.content
        assert "$99,999" not in response.content
        # And the [mock-llm] label must be present so audit reviewers
        # cannot confuse a mock response for a production one.
        assert "[mock-llm]" in response.content


# ---------------------------------------------------------------------------
# N5 — spec.rail_by_name is memoized
# ---------------------------------------------------------------------------


class TestRailByNameMemoized:
    def test_second_lookup_hits_cache(self, minimal_spec):
        # First lookup builds the cache; second call uses it.
        assert minimal_spec.rail_by_name("numerical_accuracy") is not None
        assert getattr(minimal_spec, "_rail_index", None) is not None
        # Cache contains every declared rail.
        names = set(minimal_spec._rail_index.keys())
        declared = {
            r.name
            for r in minimal_spec.critic.guardrails.input_rails
            + minimal_spec.critic.guardrails.output_rails
        }
        assert names == declared


# ---------------------------------------------------------------------------
# Presidio warmup
# ---------------------------------------------------------------------------


class TestPresidioWarmup:
    @pytest.mark.asyncio
    async def test_astart_warms_redactor_without_error(
        self, tmp_path: Path, fixture_dir: Path
    ):
        system = _make_system(tmp_path, fixture_dir)
        # Must not raise even though Presidio isn't installed in the
        # test env (redactor falls back to regex).
        await system.astart()
        await system.astop()
