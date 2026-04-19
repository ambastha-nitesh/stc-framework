"""Tests for FINRA Rule 2210 engine."""

from __future__ import annotations

import pytest

from stc_framework.compliance.rule_2210 import (
    CommunicationType,
    ContentAnalyzer,
    PrincipalApprovalQueue,
    ReviewDecision,
    Rule2210Engine,
)
from stc_framework.errors import FINRARuleViolation
from stc_framework.infrastructure.store import InMemoryStore


def test_analyzer_auto_approves_clean_content() -> None:
    analyzer = ContentAnalyzer()
    result = analyzer.analyze(content="Here are some educational bond facts.")
    assert result.verdict is ReviewDecision.AUTO_APPROVED
    assert result.violations == []


def test_analyzer_flags_guarantee_as_critical() -> None:
    analyzer = ContentAnalyzer()
    result = analyzer.analyze(
        content="We guarantee returns of 10% annually on this fund.",
        communication_type=CommunicationType.RETAIL,
    )
    assert any(v.severity == "critical" for v in result.violations)
    assert result.verdict is ReviewDecision.REJECTED
    assert result.requires_principal is True


def test_analyzer_flags_no_risk_claim() -> None:
    analyzer = ContentAnalyzer()
    result = analyzer.analyze(content="This is a risk-free opportunity.")
    assert any(v.violation_type == "no_risk" for v in result.violations)


def test_analyzer_fair_balance_fails_on_retail() -> None:
    analyzer = ContentAnalyzer()
    # Lots of positive language, no risk mentions — fair-balance should fail.
    result = analyzer.analyze(
        content="Profit, gain, growth, opportunity, outperform the market.",
        communication_type=CommunicationType.RETAIL,
    )
    assert any(v.violation_type == "fair_balance_failure" for v in result.violations)


def test_analyzer_missing_disclosure_flagged() -> None:
    analyzer = ContentAnalyzer()
    result = analyzer.analyze(
        content="See our fund performance.",
        required_disclosures=["FINRA disclosure"],
    )
    assert any(v.violation_type == "missing_disclosure" for v in result.violations)
    assert result.disclosure_check == {"FINRA disclosure": False}


@pytest.mark.asyncio
async def test_engine_enforces_critical_by_default() -> None:
    engine = Rule2210Engine(store=InMemoryStore())
    with pytest.raises(FINRARuleViolation):
        await engine.review(content="This investment has guaranteed returns of 20%.")


@pytest.mark.asyncio
async def test_engine_non_enforcing_mode_returns_result() -> None:
    engine = Rule2210Engine(store=InMemoryStore(), enforce_critical=False)
    result = await engine.review(content="This investment has guaranteed returns of 20%.")
    assert result.verdict is ReviewDecision.REJECTED
    assert result.critical_count >= 1


@pytest.mark.asyncio
async def test_engine_submits_to_principal_queue() -> None:
    engine = Rule2210Engine(store=InMemoryStore(), enforce_critical=False)
    await engine.review(
        content="We guarantee 10% returns. Past performance is not indicative.",
        communication_type=CommunicationType.RETAIL,
        communication_id="comm-1",
    )
    pending = await engine.approval_queue.pending()
    assert len(pending) == 1
    assert pending[0]["item_id"] == "comm-1"


@pytest.mark.asyncio
async def test_approval_queue_approve_moves_out_of_pending() -> None:
    store = InMemoryStore()
    queue = PrincipalApprovalQueue(store=store)
    from stc_framework.compliance.rule_2210 import ContentAnalyzer

    result = ContentAnalyzer().analyze(content="We guarantee returns.")
    await queue.submit("c-1", result, content="We guarantee returns.")
    assert len(await queue.pending()) == 1
    await queue.approve("c-1", actor="principal-1")
    assert len(await queue.pending()) == 0


@pytest.mark.asyncio
async def test_approval_queue_approve_missing_raises() -> None:
    queue = PrincipalApprovalQueue(store=InMemoryStore())
    with pytest.raises(KeyError):
        await queue.approve("does-not-exist", actor="x")
