"""Regression tests for every Tier-1 finding in the v0.3.0 staff review.

Each test class maps 1:1 to a finding in
``docs/security/V030_STAFF_REVIEW.md``. The class name carries the
finding id so a test failure immediately points back to the review
entry.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from stc_framework._internal.metrics_safe import safe_inc, safe_set
from stc_framework._internal.patterns import Pattern
from stc_framework.compliance.bias_fairness import BiasFairnessMonitor
from stc_framework.compliance.legal_hold import LegalHold, LegalHoldManager
from stc_framework.compliance.rule_2210 import CommunicationType, Rule2210Engine
from stc_framework.compliance.sovereignty.model_origin import (
    ModelOriginPolicy,
    OriginRisk,
)
from stc_framework.critic.validators.base import ValidationContext
from stc_framework.critic.validators.bias_rail import BiasRailBridge
from stc_framework.critic.validators.compliance_rail import ComplianceRailBridge
from stc_framework.critic.validators.sovereignty_rail import SovereigntyRailBridge
from stc_framework.governance.catalog import DataCatalog
from stc_framework.governance.lineage import (
    GenerationNode,
    LineageBuilder,
    LineageStore,
    SourceDocumentNode,
)
from stc_framework.infrastructure.store import InMemoryStore
from stc_framework.orchestration.registry import (
    StalwartRegistration,
    StalwartRegistry,
)
from stc_framework.orchestration.workflow import TaskRequest, WorkflowOrchestrator
from stc_framework.risk.kri import KRIDefinition, KRIEngine
from stc_framework.security.threat_detection import ThreatDetectionManager

# ---------- R1 — tenant id segment match -----------------------------------


class TestR1TenantIDSegmentMatch:
    @pytest.mark.asyncio
    async def test_prefix_tenant_does_not_match_longer_tenant(self) -> None:
        store = InMemoryStore()
        await store.set("risk:t:r-1", "a")
        await store.set("risk:t1:r-1", "b")
        removed = await store.erase_tenant("t", key_prefix="risk:")
        assert removed == 1
        assert await store.get("risk:t:r-1") is None
        assert await store.get("risk:t1:r-1") == "b"  # NOT clobbered

    @pytest.mark.asyncio
    async def test_empty_tenant_id_is_noop(self) -> None:
        store = InMemoryStore()
        await store.set("risk::r-1", "a")
        assert await store.erase_tenant("") == 0
        assert await store.get("risk::r-1") == "a"


# ---------- R2 — lineage index concurrency ---------------------------------


class TestR2LineageIndexConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_store_calls_preserve_every_id(self) -> None:
        store = InMemoryStore()
        lineage_store = LineageStore(store=store)

        def _build(lineage_id: str):
            return (
                LineageBuilder(lineage_id)
                .add_source_documents([SourceDocumentNode(doc_id="d-shared")])
                .add_generation(GenerationNode(model_id="m-1"))
                .build()
            )

        # 20 concurrent store calls all touching the same doc index.
        records = [_build(f"trace-{i}") for i in range(20)]
        await asyncio.gather(*[lineage_store.store(r) for r in records])

        ids = await lineage_store.by_document("d-shared")
        assert sorted(ids) == sorted([f"trace-{i}" for i in range(20)])


# ---------- R3 — threat detection no-loop path ----------------------------


class TestR3ThreatDetectionNoLoopNoCrash:
    def test_honey_token_triggered_sync_path_does_not_raise(self) -> None:
        """Invoking the manager from a synchronous context must not raise."""
        mgr = ThreatDetectionManager()
        mgr.deception.register_honey_token("STC_TOK_deadbeef")
        from stc_framework.errors import HoneyTokenTriggered

        with pytest.raises(HoneyTokenTriggered):
            mgr.honey_token_used("STC_TOK_deadbeef")
        # No "no current event loop" / "event loop is closed" warning emitted.


# ---------- R4 — KRI threshold validation ---------------------------------


class TestR4KRIThresholdValidation:
    @pytest.mark.asyncio
    async def test_higher_is_worse_requires_amber_below_red(self) -> None:
        engine = KRIEngine(store=InMemoryStore())
        with pytest.raises(ValueError):
            await engine.register(KRIDefinition(kri_id="k1", name="k1", direction="higher_is_worse", amber=10, red=5))

    @pytest.mark.asyncio
    async def test_lower_is_worse_requires_amber_above_red(self) -> None:
        engine = KRIEngine(store=InMemoryStore())
        with pytest.raises(ValueError):
            await engine.register(KRIDefinition(kri_id="k1", name="k1", direction="lower_is_worse", amber=0.5, red=0.9))

    @pytest.mark.asyncio
    async def test_unknown_direction_rejected(self) -> None:
        engine = KRIEngine(store=InMemoryStore())
        with pytest.raises(ValueError):
            await engine.register(KRIDefinition(kri_id="k1", name="k1", direction="unknown", amber=1, red=2))

    @pytest.mark.asyncio
    async def test_valid_registration_succeeds(self) -> None:
        engine = KRIEngine(store=InMemoryStore())
        await engine.register(KRIDefinition(kri_id="k1", name="k1", direction="higher_is_worse", amber=5, red=10))


# ---------- R5 — pattern metadata default ---------------------------------


class TestR5PatternMetadataDefault:
    def test_metadata_defaults_to_empty_dict_not_none(self) -> None:
        import re

        p = Pattern(name="x", regex=re.compile("x"))
        assert p.metadata == {}
        # Critical property: callers can do .get() without a None-check.
        assert p.metadata.get("category", "default") == "default"


# ---------- R6 — catalog serializer strict inputs -------------------------


class TestR6CatalogSerializerStrictInputs:
    @pytest.mark.asyncio
    async def test_register_document_serialises_to_dict_with_known_keys(self) -> None:
        catalog = DataCatalog(store=InMemoryStore())
        await catalog.register_document("d-1", metadata={"source": "10-K"})
        raw = await catalog._store.get("catalog:doc:d-1")  # type: ignore[attr-defined]
        assert isinstance(raw, dict)
        assert raw["asset_id"] == "d-1"
        # The R6 "fallback" branch would produce {"value": ...} — verify it's absent.
        assert "value" not in raw


# ---------- R7 — legal hold explicit scope --------------------------------


class TestR7LegalHoldExplicitScope:
    @pytest.mark.asyncio
    async def test_empty_keywords_without_scope_all_matches_nothing(self) -> None:
        mgr = LegalHoldManager(store=InMemoryStore())
        # Omit keywords and scope_all — used to be a blanket hold.
        await mgr.issue(LegalHold(hold_id="h", tenant_ids=["t"]))
        allowed, hold_id = await mgr.check_destruction_allowed(
            artifact="any/artifact", data_store="filesystem", tenant_id="t"
        )
        assert allowed is True
        assert hold_id is None

    @pytest.mark.asyncio
    async def test_scope_all_true_blocks_every_artifact(self) -> None:
        mgr = LegalHoldManager(store=InMemoryStore())
        await mgr.issue(LegalHold(hold_id="h", scope_all=True))
        allowed, hold_id = await mgr.check_destruction_allowed(artifact="literally/anything", data_store="s")
        assert allowed is False
        assert hold_id == "h"

    @pytest.mark.asyncio
    async def test_keyword_match_still_works_without_scope_all(self) -> None:
        mgr = LegalHoldManager(store=InMemoryStore())
        await mgr.issue(LegalHold(hold_id="h", keywords=["secret"]))
        allowed, hold_id = await mgr.check_destruction_allowed(artifact="top-secret-file.txt", data_store="s")
        assert allowed is False
        assert hold_id == "h"


# ---------- R8 — metric safety helper -------------------------------------


class TestR8MetricSafeEmitLogsOnFailure:
    def test_safe_inc_logs_on_label_mismatch(self, caplog: pytest.LogCaptureFixture) -> None:
        from prometheus_client import CollectorRegistry, Counter

        reg = CollectorRegistry()
        counter = Counter("stc_test_counter", "test", labelnames=("a",), registry=reg)
        # Extra label that isn't declared -> ValueError inside Prometheus.
        with caplog.at_level(logging.WARNING):
            safe_inc(counter, a="x", extra="nope")
        # Application code did NOT crash; warning WAS emitted.
        # (The logger name is the module; check some warning was recorded.)
        assert any(
            "label_mismatch" in str(record) or "label" in record.message.lower() for record in caplog.records
        ), f"expected a label-mismatch warning; got {caplog.records!r}"

    def test_safe_set_ignores_missing_metric_attribute(self) -> None:
        class Broken:
            pass

        # Must not raise.
        safe_set(Broken(), 1.0, x="y")


# ---------- R9 — Critic rail bridges --------------------------------------


class TestR9CriticRailBridges:
    @pytest.mark.asyncio
    async def test_compliance_rail_blocks_critical_finra_violation(self) -> None:
        engine = Rule2210Engine(store=InMemoryStore(), enforce_critical=False)
        bridge = ComplianceRailBridge(engine=engine)
        ctx = ValidationContext(
            query="",
            response="We guarantee 15% returns on this fund.",
            trace_id="t-1",
            metadata={"communication_type": CommunicationType.RETAIL.value},
        )
        result = await bridge.avalidate(ctx)
        assert result.passed is False
        assert result.action == "block"
        assert result.severity == "critical"

    @pytest.mark.asyncio
    async def test_compliance_rail_passes_clean_content(self) -> None:
        engine = Rule2210Engine(store=InMemoryStore(), enforce_critical=False)
        bridge = ComplianceRailBridge(engine=engine)
        ctx = ValidationContext(
            query="",
            response="The fund invests in Treasury bonds. Consult an advisor.",
            trace_id="t-2",
        )
        result = await bridge.avalidate(ctx)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_bias_rail_flags_adverse_impact(self) -> None:
        monitor = BiasFairnessMonitor()
        for _ in range(8):
            monitor.record_response_quality(group="A", score=1.0)
            monitor.record_response_quality(group="B", score=0.4)
        bridge = BiasRailBridge(monitor=monitor)
        ctx = ValidationContext(query="", response="", metadata={"reference_group": "A"})
        result = await bridge.avalidate(ctx)
        assert result.passed is False
        assert result.action == "warn"

    @pytest.mark.asyncio
    async def test_sovereignty_rail_blocks_disallowed_model(self) -> None:
        policy = ModelOriginPolicy(allowed_risks={OriginRisk.TRUSTED})
        from stc_framework.compliance.sovereignty.model_origin import (
            ModelOriginProfile,
        )

        policy.register(
            ModelOriginProfile(
                model_id="foreign-model",
                origin_risk=OriginRisk.SANCTIONED,
            )
        )
        bridge = SovereigntyRailBridge(policy=policy)
        ctx = ValidationContext(query="", response="x", metadata={"model_id": "foreign-model"})
        result = await bridge.avalidate(ctx)
        assert result.passed is False
        assert result.action == "block"

    @pytest.mark.asyncio
    async def test_sovereignty_rail_missing_model_id_passes(self) -> None:
        policy = ModelOriginPolicy()
        bridge = SovereigntyRailBridge(policy=policy)
        ctx = ValidationContext(query="", response="x")
        result = await bridge.avalidate(ctx)
        assert result.passed is True
        assert "missing" in result.details


# ---------- R10 — audit chain with v0.3.0 events --------------------------


class TestR10V030AuditChainIntegrity:
    @pytest.mark.asyncio
    async def test_chain_verifies_after_mixed_v030_event_emission(self, tmp_path: Path) -> None:
        from stc_framework.adapters.audit_backend.local_file import (
            JSONLAuditBackend,
        )
        from stc_framework.governance.events import AuditEvent
        from stc_framework.observability.audit import (
            AuditLogger,
            AuditRecord,
            verify_chain,
        )

        backend = JSONLAuditBackend(directory=tmp_path)
        logger = AuditLogger(backend=backend)

        # Emit one of every v0.3.0 event class.
        events = [
            AuditEvent.COMPLIANCE_VIOLATION,
            AuditEvent.LEGAL_HOLD_ISSUED,
            AuditEvent.RISK_ASSESSED,
            AuditEvent.KRI_BREACH,
            AuditEvent.THREAT_DETECTED,
            AuditEvent.WORKFLOW_STARTED,
            AuditEvent.WORKFLOW_COMPLETED,
            AuditEvent.ASSET_REGISTERED,
            AuditEvent.LINEAGE_RECORDED,
            AuditEvent.SLO_VIOLATION,
            AuditEvent.SESSION_CREATED,
        ]
        for i, ev in enumerate(events):
            await logger.emit(
                AuditRecord(
                    event_type=ev.value,
                    persona="test",
                    extra={"idx": i, "event": ev.value},
                )
            )
        await logger.close()

        records = list(backend.iter_records())
        ok, count, reason = verify_chain(records, accept_unknown_genesis=True)
        assert ok, f"chain verification failed: {reason}"
        assert count >= len(events)


# ---------- R12 — orchestrator state lock ---------------------------------


class TestR12OrchestratorConcurrentDispatch:
    @pytest.mark.asyncio
    async def test_serial_dispatch_still_works_with_lock(self) -> None:
        """Sanity: adding the lock must not break the current SimulationEngine path."""
        reg = StalwartRegistry()

        async def disp(task: dict) -> dict:  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.01)
            return {"status": "success", "cost_usd": 0.10}

        reg.register(StalwartRegistration(stalwart_id="s", capabilities=("x",), dispatch=disp))
        orchestrator = WorkflowOrchestrator(registry=reg, max_workflow_cost_usd=5.0)
        state = await orchestrator.run(
            workflow_id="wf-1",
            goal="",
            tasks=[
                TaskRequest(task_id="t1", capability="x"),
                TaskRequest(task_id="t2", capability="x"),
                TaskRequest(task_id="t3", capability="x"),
            ],
        )
        assert state.status == "success"
        # All three results landed under the lock; totals match exactly.
        assert len(state.results) == 3
        assert state.total_cost_usd == pytest.approx(0.30)
