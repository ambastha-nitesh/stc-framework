"""Tests for the smaller compliance modules.

Bias fairness, IP risk, transparency, privilege routing, fiduciary,
legal hold, explainability, Reg BI, NYDFS, Part 500, sovereignty
submodules.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from stc_framework._internal.patterns import Pattern
from stc_framework.compliance.bias_fairness import (
    ADVERSE_IMPACT_RATIO,
    BiasFairnessMonitor,
)
from stc_framework.compliance.explainability import LegalExplainabilityEngine
from stc_framework.compliance.fiduciary import FiduciaryFairnessChecker
from stc_framework.compliance.ip_risk import IPRiskScanner
from stc_framework.compliance.legal_hold import LegalHold, LegalHoldManager
from stc_framework.compliance.nydfs_notification import (
    NotificationStatus,
    NYDFSNotificationEngine,
)
from stc_framework.compliance.part_500_cert import (
    PART_500_SECTIONS,
    EvidenceItem,
    GapRecord,
    Part500CertificationAssembler,
)
from stc_framework.compliance.patterns import PatternCatalog
from stc_framework.compliance.privilege_routing import PrivilegeRouter
from stc_framework.compliance.reg_bi import (
    CustomerProfile,
    RegBICheckpoint,
    SuitabilityResult,
)
from stc_framework.compliance.sovereignty import (
    InferenceEndpoint,
    InferenceJurisdictionEnforcer,
    ModelOriginPolicy,
    ModelOriginProfile,
    OriginRisk,
    QueryPatternProtector,
    StateComplianceMatrix,
)
from stc_framework.compliance.transparency import (
    DEFAULT_DISCLOSURE,
    TransparencyManager,
)
from stc_framework.errors import LegalHoldActive, RegBIUnsuitable
from stc_framework.governance.lineage import (
    GenerationNode,
    LineageBuilder,
    ResponseNode,
    SourceDocumentNode,
    ValidationNode,
)
from stc_framework.infrastructure.store import InMemoryStore

# ---- Bias ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_bias_monitor_no_adverse_impact_when_parity() -> None:
    m = BiasFairnessMonitor()
    for _ in range(10):
        m.record_response_quality(group="A", score=0.9)
        m.record_response_quality(group="B", score=0.9)
    report = await m.evaluate_fairness()
    assert all(not f.adverse_impact for f in report.findings)


@pytest.mark.asyncio
async def test_bias_monitor_flags_adverse_impact() -> None:
    m = BiasFairnessMonitor()
    for _ in range(10):
        m.record_response_quality(group="A", score=1.0)
        m.record_response_quality(group="B", score=0.4)
    report = await m.evaluate_fairness(reference_group="A")
    flag = next((f for f in report.findings if f.group == "B"), None)
    assert flag is not None
    assert flag.adverse_impact is True
    assert flag.ratio < ADVERSE_IMPACT_RATIO


def test_bias_monitor_score_bounds() -> None:
    m = BiasFairnessMonitor()
    with pytest.raises(ValueError):
        m.record_response_quality(group="A", score=1.5)


# ---- IP ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_ip_scanner_with_custom_catalog_matches() -> None:
    catalog = PatternCatalog(
        [
            Pattern(
                name="brand_x",
                regex=re.compile(r"(?i)\bBrandX\b"),
                severity="high",
                description="BrandX trademark",
            )
        ]
    )
    scanner = IPRiskScanner(catalog=catalog)
    result = await scanner.scan("We compared our product to BrandX on performance.")
    assert len(result.flags) == 1
    assert result.flags[0].name == "brand_x"


@pytest.mark.asyncio
async def test_ip_scanner_empty_catalog_returns_no_flags() -> None:
    scanner = IPRiskScanner()
    result = await scanner.scan("Any text.")
    assert result.flags == []


# ---- Transparency ------------------------------------------------------


def test_disclosure_appended_once() -> None:
    mgr = TransparencyManager(store=InMemoryStore())
    out = mgr.apply_disclosure("Hello.")
    assert DEFAULT_DISCLOSURE in out
    # Idempotent — applying twice does not double-stamp.
    again = mgr.apply_disclosure(out)
    assert again.count(DEFAULT_DISCLOSURE) == 1


@pytest.mark.asyncio
async def test_consent_record_and_check() -> None:
    mgr = TransparencyManager(store=InMemoryStore())
    await mgr.record_consent(tenant_id="t1", customer_id="c1", consented=True)
    assert await mgr.check_consent(tenant_id="t1", customer_id="c1") is True
    await mgr.record_consent(tenant_id="t1", customer_id="c1", consented=False)
    assert await mgr.check_consent(tenant_id="t1", customer_id="c1") is False


# ---- Privilege routing --------------------------------------------------


def test_privilege_router_detects_attorney() -> None:
    r = PrivilegeRouter()
    d = r.evaluate(query="Please draft a memo to our attorney about the case.")
    assert d.privileged is True
    assert d.required_routing == "local_only"


def test_privilege_router_clean_query() -> None:
    r = PrivilegeRouter()
    assert r.evaluate(query="What is the Q3 revenue?").privileged is False


# ---- Fiduciary ---------------------------------------------------------


def test_fiduciary_single_tier_no_concern() -> None:
    f = FiduciaryFairnessChecker()
    f.record(tier="retail", model="gpt-4")
    result = f.check_fairness()
    assert result.concern is False


def test_fiduciary_two_tiers_same_top_model_no_concern() -> None:
    f = FiduciaryFairnessChecker()
    for _ in range(10):
        f.record(tier="retail", model="gpt-4")
        f.record(tier="hnw", model="gpt-4")
    result = f.check_fairness()
    assert result.concern is False


def test_fiduciary_divergent_top_models_flagged() -> None:
    f = FiduciaryFairnessChecker(material_gap_threshold=0.2)
    for _ in range(10):
        f.record(tier="retail", model="cheap-model")
        f.record(tier="hnw", model="premium-model")
    result = f.check_fairness()
    assert result.concern is True


# ---- Legal hold --------------------------------------------------------


@pytest.mark.asyncio
async def test_legal_hold_blocks_destruction() -> None:
    mgr = LegalHoldManager(store=InMemoryStore())
    await mgr.issue(
        LegalHold(
            hold_id="h-1",
            matter_id="m-1",
            tenant_ids=["t-a"],
            keywords=["doc-secret"],
            issued_by="counsel",
        )
    )
    allowed, hold_id = await mgr.check_destruction_allowed(
        artifact="path/to/doc-secret.txt",
        data_store="filesystem",
        tenant_id="t-a",
    )
    assert allowed is False
    assert hold_id == "h-1"


@pytest.mark.asyncio
async def test_legal_hold_released_allows_destruction() -> None:
    mgr = LegalHoldManager(store=InMemoryStore())
    await mgr.issue(LegalHold(hold_id="h-1", scope_all=True))
    await mgr.release("h-1", actor="counsel")
    allowed, _ = await mgr.check_destruction_allowed(artifact="x", data_store="s", tenant_id="t")
    assert allowed is True


@pytest.mark.asyncio
async def test_legal_hold_scope_different_tenant_unaffected() -> None:
    mgr = LegalHoldManager(store=InMemoryStore())
    await mgr.issue(LegalHold(hold_id="h-1", tenant_ids=["t-a"], keywords=["secret"]))
    # Different tenant — destruction should be allowed.
    allowed, _ = await mgr.check_destruction_allowed(artifact="secret.txt", data_store="s", tenant_id="t-b")
    assert allowed is True


# ---- Explainability ----------------------------------------------------


def test_explainability_produces_narrative() -> None:
    lineage = (
        LineageBuilder("trace-xyz", tenant_id="t-1", session_id="s-1")
        .add_source_documents([SourceDocumentNode(doc_id="d-1")])
        .add_generation(GenerationNode(model_id="gpt-4", prompt_version="v2"))
        .add_validation(ValidationNode(rails=[{"name": "pii_scan"}], action="pass"))
        .add_response(ResponseNode(status="delivered", char_count=1000))
        .build()
    )
    narrative = LegalExplainabilityEngine().explain(lineage)
    assert "trace-xyz" in narrative
    assert "gpt-4" in narrative
    assert "pii_scan" in narrative


# ---- Reg BI ------------------------------------------------------------


@pytest.mark.asyncio
async def test_reg_bi_conservative_customer_high_risk_content_unsuitable() -> None:
    checker = RegBICheckpoint()
    result = await checker.check(
        content="Consider leveraged ETF positions with penny stock exposure.",
        customer=CustomerProfile(customer_id="c-1", risk_tolerance="conservative"),
    )
    assert result.result is SuitabilityResult.UNSUITABLE


@pytest.mark.asyncio
async def test_reg_bi_enforce_mode_raises() -> None:
    checker = RegBICheckpoint(enforce=True)
    with pytest.raises(RegBIUnsuitable):
        await checker.check(
            content="Leveraged ETF futures.",
            customer=CustomerProfile(customer_id="c-1", risk_tolerance="conservative"),
        )


@pytest.mark.asyncio
async def test_reg_bi_moderate_customer_low_risk_content_suitable() -> None:
    checker = RegBICheckpoint()
    result = await checker.check(
        content="Treasury bond with long time horizon.",
        customer=CustomerProfile(customer_id="c-1", risk_tolerance="moderate"),
    )
    assert result.result is SuitabilityResult.SUITABLE


# ---- NYDFS notification ------------------------------------------------


@pytest.mark.asyncio
async def test_nydfs_notification_creation_sets_72h_deadline() -> None:
    engine = NYDFSNotificationEngine(store=InMemoryStore())
    notif = await engine.create_notification(notification_id="n-1", incident_id="i-1")
    hours = notif.hours_remaining()
    # Should be close to 72h (minus scheduling slop)
    assert 71.0 <= hours <= 72.1


@pytest.mark.asyncio
async def test_nydfs_approve_and_submit_flow() -> None:
    engine = NYDFSNotificationEngine(store=InMemoryStore())
    await engine.create_notification(notification_id="n-1", incident_id="i-1")
    approved = await engine.approve("n-1", approver="ciso-alice")
    assert approved.status is NotificationStatus.APPROVED
    submitted = await engine.submit("n-1")
    assert submitted.status is NotificationStatus.SUBMITTED


@pytest.mark.asyncio
async def test_nydfs_deadline_check_marks_overdue() -> None:
    engine = NYDFSNotificationEngine(store=InMemoryStore())
    await engine.create_notification(notification_id="n-1", incident_id="i-1")
    # Simulate 80 hours into the future — well past deadline.
    future = datetime.now(timezone.utc) + timedelta(hours=80)
    items = await engine.check_deadlines(now=future)
    assert any(i["status"] == NotificationStatus.OVERDUE.value for i in items)


# ---- Part 500 ---------------------------------------------------------


@pytest.mark.asyncio
async def test_part_500_rejects_unknown_section() -> None:
    assembler = Part500CertificationAssembler(store=InMemoryStore())
    with pytest.raises(ValueError):
        await assembler.add_evidence(
            "500.99_fake",
            "ev-1",
            EvidenceItem(section_id="500.99_fake", title="x"),
        )


@pytest.mark.asyncio
async def test_part_500_assemble_counts_evidence() -> None:
    assembler = Part500CertificationAssembler(store=InMemoryStore())
    section = PART_500_SECTIONS[0]
    await assembler.add_evidence(
        section,
        "ev-1",
        EvidenceItem(section_id=section, title="Program doc"),
    )
    await assembler.add_gap("g-1", GapRecord(section_id=section, description="missing review"))
    snap = await assembler.assemble(2026)
    assert snap["section_count"] == len(PART_500_SECTIONS)
    assert len(snap["sections"][section]["evidence"]) == 1
    assert snap["total_gaps"] == 1


# ---- Sovereignty ------------------------------------------------------


def test_model_origin_allows_trusted() -> None:
    policy = ModelOriginPolicy()
    decision = policy.evaluate("gpt-4")
    assert decision["allowed"] is True


def test_model_origin_rejects_unknown() -> None:
    policy = ModelOriginPolicy()
    decision = policy.evaluate("mystery-model")
    assert decision["allowed"] is False


def test_model_origin_register_and_evaluate() -> None:
    policy = ModelOriginPolicy(allowed_risks={OriginRisk.TRUSTED})
    policy.register(
        ModelOriginProfile(
            model_id="new-model",
            developer_org="SomeOrg",
            origin_risk=OriginRisk.RESTRICTED,
        )
    )
    decision = policy.evaluate("new-model")
    assert decision["allowed"] is False


def test_state_compliance_matrix_filters_by_states() -> None:
    m = StateComplianceMatrix()
    summary = m.compliance_summary(states=["CO", "CA"])
    assert summary["applicable_law_count"] >= 2
    assert set(summary["states"]) == {"CO", "CA"}


def test_jurisdiction_enforcer_blocks_foreign() -> None:
    enforcer = InferenceJurisdictionEnforcer(allowed_jurisdictions={"US"})
    enforcer.register_endpoint(InferenceEndpoint(endpoint_id="us-1", jurisdiction="US"))
    enforcer.register_endpoint(InferenceEndpoint(endpoint_id="eu-1", jurisdiction="EU"))
    assert enforcer.check(endpoint_id="us-1")["allowed"] is True
    assert enforcer.check(endpoint_id="eu-1")["allowed"] is False
    allowed = enforcer.filter_endpoints()
    assert allowed == ["us-1"]


def test_jurisdiction_enforcer_restricted_requires_fips() -> None:
    enforcer = InferenceJurisdictionEnforcer(allowed_jurisdictions={"US"}, require_fips_for_restricted=True)
    enforcer.register_endpoint(InferenceEndpoint(endpoint_id="us-nofips", jurisdiction="US", fips_compliant=False))
    enforcer.register_endpoint(InferenceEndpoint(endpoint_id="us-fips", jurisdiction="US", fips_compliant=True))
    assert enforcer.check(endpoint_id="us-nofips", data_tier="restricted")["allowed"] is False
    assert enforcer.check(endpoint_id="us-fips", data_tier="restricted")["allowed"] is True
    assert enforcer.check(endpoint_id="us-nofips", data_tier="public")["allowed"] is True


@pytest.mark.asyncio
async def test_query_pattern_concentration_flag() -> None:
    p = QueryPatternProtector(store=InMemoryStore(), concentration_threshold=0.5)
    for _ in range(8):
        await p.record_query(provider="openai", entity="client_acme")
    for _ in range(2):
        await p.record_query(provider="openai", entity="client_beta")
    report = await p.check_pattern_risk(provider="openai")
    assert report.concentrated is True
    assert p.recommend_routing(report) == "local_only"


# Helper to suppress unused-import warnings for LegalHoldActive.
def test_legal_hold_active_error_symbol_importable() -> None:
    assert LegalHoldActive is not None
