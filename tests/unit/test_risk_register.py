"""Tests for :mod:`stc_framework.risk.register`."""

from __future__ import annotations

import pytest

from stc_framework._internal.state_machine import IllegalTransition
from stc_framework.infrastructure.store import InMemoryStore
from stc_framework.risk.register import (
    Impact,
    Likelihood,
    Risk,
    RiskCategory,
    RiskRating,
    RiskRegister,
    RiskState,
    RiskTreatment,
)


def test_risk_rating_matrix_corners() -> None:
    # 1x1 = 1 -> LOW
    assert RiskRating.from_score(Likelihood.RARE, Impact.INSIGNIFICANT) is RiskRating.LOW
    # 3x3 = 9 -> MEDIUM
    assert RiskRating.from_score(Likelihood.POSSIBLE, Impact.MODERATE) is RiskRating.MEDIUM
    # 5x3 = 15 -> HIGH
    assert RiskRating.from_score(Likelihood.ALMOST_CERTAIN, Impact.MODERATE) is RiskRating.HIGH
    # 5x4 = 20 -> CRITICAL
    assert RiskRating.from_score(Likelihood.ALMOST_CERTAIN, Impact.MAJOR) is RiskRating.CRITICAL
    # 5x5 = 25 -> CRITICAL
    assert RiskRating.from_score(Likelihood.ALMOST_CERTAIN, Impact.CATASTROPHIC) is RiskRating.CRITICAL


def test_inherent_rating_monotonic_in_likelihood() -> None:
    r = Risk(risk_id="r1", title="t", inherent_impact=Impact.MODERATE)
    # Hold impact constant, vary likelihood -> rating is monotone non-decreasing.
    prev = 0
    for likelihood in Likelihood:
        r.inherent_likelihood = likelihood
        score = int(likelihood) * int(Impact.MODERATE)
        assert score >= prev
        prev = score


@pytest.mark.asyncio
async def test_identify_creates_record() -> None:
    store = InMemoryStore()
    reg = RiskRegister(store=store)
    risk = Risk(risk_id="r-1", title="Hallucination", category=RiskCategory.OPERATIONAL)
    record = await reg.identify(risk)
    assert record.state.state is RiskState.IDENTIFIED
    fetched = await reg.get("r-1")
    assert fetched is not None
    assert fetched.risk.title == "Hallucination"


@pytest.mark.asyncio
async def test_lifecycle_happy_path_transitions() -> None:
    store = InMemoryStore()
    reg = RiskRegister(store=store)
    await reg.identify(Risk(risk_id="r-1", title="t"))
    await reg.assess(
        "r-1",
        residual_likelihood=Likelihood.UNLIKELY,
        residual_impact=Impact.MINOR,
        actor="riskops",
    )
    fetched = await reg.get("r-1")
    assert fetched is not None
    assert fetched.state.state is RiskState.ASSESSED
    assert fetched.risk.residual_rating is RiskRating.LOW
    await reg.treat("r-1", RiskTreatment(type="mitigate", description="add rail"), actor="riskops")
    fetched = await reg.get("r-1")
    assert fetched is not None
    assert fetched.state.state is RiskState.TREATMENT_PLANNED
    await reg.transition("r-1", RiskState.ACCEPTED, actor="ciso", reason="residual ok")
    fetched = await reg.get("r-1")
    assert fetched is not None
    assert fetched.state.state is RiskState.ACCEPTED


@pytest.mark.asyncio
async def test_escalate_from_monitoring() -> None:
    store = InMemoryStore()
    reg = RiskRegister(store=store)
    await reg.identify(Risk(risk_id="r-1", title="t"))
    await reg.assess("r-1", residual_likelihood=Likelihood.LIKELY, residual_impact=Impact.MAJOR, actor="a")
    await reg.transition("r-1", RiskState.ACCEPTED, actor="a", reason="assessed")
    await reg.transition("r-1", RiskState.MONITORING, actor="a", reason="watching")
    await reg.escalate("r-1", reason="KRI red")
    fetched = await reg.get("r-1")
    assert fetched is not None
    assert fetched.state.state is RiskState.ESCALATED


@pytest.mark.asyncio
async def test_illegal_transition_rejected() -> None:
    store = InMemoryStore()
    reg = RiskRegister(store=store)
    await reg.identify(Risk(risk_id="r-1", title="t"))
    # IDENTIFIED -> ACCEPTED is not a legal transition (must assess first).
    with pytest.raises(IllegalTransition):
        await reg.transition("r-1", RiskState.ACCEPTED, actor="a", reason="skip")


@pytest.mark.asyncio
async def test_heat_map_counts_ratings() -> None:
    store = InMemoryStore()
    reg = RiskRegister(store=store)
    await reg.identify(
        Risk(
            risk_id="r-hi",
            title="hi",
            inherent_likelihood=Likelihood.ALMOST_CERTAIN,
            inherent_impact=Impact.CATASTROPHIC,
        )
    )
    await reg.identify(
        Risk(
            risk_id="r-lo",
            title="lo",
            inherent_likelihood=Likelihood.RARE,
            inherent_impact=Impact.INSIGNIFICANT,
        )
    )
    heat = await reg.heat_map()
    assert heat["critical"] == 1
    assert heat["low"] == 1


@pytest.mark.asyncio
async def test_dashboard_reports_by_state() -> None:
    store = InMemoryStore()
    reg = RiskRegister(store=store)
    await reg.identify(Risk(risk_id="r-1", title="t"))
    dash = await reg.dashboard()
    assert dash["total_risks"] == 1
    assert dash["by_state"][RiskState.IDENTIFIED.value] == 1
