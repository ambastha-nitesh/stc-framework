"""Tests for :mod:`stc_framework.risk.optimizer`."""

from __future__ import annotations

import pytest

from stc_framework.errors import RiskOptimizerVeto
from stc_framework.infrastructure.store import InMemoryStore
from stc_framework.risk.kri import KRIDefinition, KRIEngine
from stc_framework.risk.optimizer import (
    ConcentrationEvaluator,
    KRIEvaluator,
    OptimizationCandidate,
    OptimizerConfig,
    ProvenanceEvaluator,
    RiskAdjustedOptimizer,
    SovereigntyEvaluator,
    VetoReason,
)


def _build_optimizer(
    *,
    allowed_origins: set[str] | None = None,
    allowed_jurisdictions: set[str] | None = None,
    max_share: float = 0.75,
    current_shares: dict[str, float] | None = None,
    kri_engine: KRIEngine | None = None,
    config: OptimizerConfig | None = None,
) -> RiskAdjustedOptimizer:
    return RiskAdjustedOptimizer(
        provenance=ProvenanceEvaluator(allowed_origin_risks=allowed_origins or {"trusted", "cautious"}),
        sovereignty=SovereigntyEvaluator(allowed_jurisdictions=allowed_jurisdictions or {"US"}),
        concentration=ConcentrationEvaluator(max_share=max_share, current_shares=current_shares or {}),
        kri=KRIEvaluator(kri_engine=kri_engine) if kri_engine else None,
        config=config,
    )


def _make_candidate(
    candidate_id: str,
    *,
    origin: str = "trusted",
    jurisdiction: str = "US",
    vendor: str = "acme",
    accuracy: float = 0.9,
    cost: float = 0.5,
    linked_kris: list[str] | None = None,
) -> OptimizationCandidate:
    return OptimizationCandidate(
        candidate_id=candidate_id,
        accuracy_score=accuracy,
        cost_score=cost,
        metadata={
            "origin_risk": origin,
            "jurisdiction": jurisdiction,
            "vendor": vendor,
            "linked_kris": linked_kris or [],
        },
    )


@pytest.mark.asyncio
async def test_selects_best_composite() -> None:
    opt = _build_optimizer()
    c1 = _make_candidate("a", accuracy=0.9, cost=0.5)
    c2 = _make_candidate("b", accuracy=0.5, cost=0.9)
    decision = await opt.optimize("llm_route", [c1, c2])
    assert decision.selected is not None
    assert decision.selected.candidate_id == "a"  # accuracy weight dominates


@pytest.mark.asyncio
async def test_vetoes_provenance_sanctioned() -> None:
    opt = _build_optimizer(allowed_origins={"trusted"})
    c = _make_candidate("untrusted", origin="sanctioned")
    good = _make_candidate("good", origin="trusted")
    decision = await opt.optimize("llm_route", [c, good])
    assert decision.selected is not None
    assert decision.selected.candidate_id == "good"
    assert c.risk_assessment is not None
    assert VetoReason.PROVENANCE_UNTRUSTED in c.risk_assessment.veto_reasons


@pytest.mark.asyncio
async def test_vetoes_sovereignty_out_of_jurisdiction() -> None:
    opt = _build_optimizer(allowed_jurisdictions={"US"})
    out = _make_candidate("foreign", jurisdiction="CN")
    local = _make_candidate("local", jurisdiction="US")
    decision = await opt.optimize("llm_route", [out, local])
    assert decision.selected is not None
    assert decision.selected.candidate_id == "local"
    assert out.risk_assessment is not None
    assert VetoReason.SOVEREIGNTY_VIOLATION in out.risk_assessment.veto_reasons


@pytest.mark.asyncio
async def test_vetoes_concentration_over_cap() -> None:
    opt = _build_optimizer(current_shares={"acme": 0.95}, max_share=0.75)
    over = _make_candidate("over", vendor="acme")
    other = _make_candidate("other", vendor="beta")
    decision = await opt.optimize("llm_route", [over, other])
    assert decision.selected is not None
    assert decision.selected.candidate_id == "other"
    assert over.risk_assessment is not None
    assert VetoReason.CONCENTRATION_RISK in over.risk_assessment.veto_reasons


@pytest.mark.asyncio
async def test_all_vetoed_raises() -> None:
    opt = _build_optimizer(allowed_origins={"trusted"})
    c1 = _make_candidate("c1", origin="sanctioned")
    c2 = _make_candidate("c2", origin="restricted")
    with pytest.raises(RiskOptimizerVeto):
        await opt.optimize("llm_route", [c1, c2])


@pytest.mark.asyncio
async def test_empty_candidates_raises() -> None:
    opt = _build_optimizer()
    with pytest.raises(RiskOptimizerVeto):
        await opt.optimize("llm_route", [])


@pytest.mark.asyncio
async def test_kri_red_vetoes_linked_candidate() -> None:
    engine = KRIEngine(store=InMemoryStore())
    await engine.register(KRIDefinition(kri_id="drift", name="drift", direction="higher_is_worse", amber=0.2, red=0.4))
    await engine.record("drift", 0.9)  # RED
    opt = _build_optimizer(kri_engine=engine)
    risky = _make_candidate("risky", linked_kris=["drift"])
    safe = _make_candidate("safe", linked_kris=[])
    decision = await opt.optimize("llm_route", [risky, safe])
    assert decision.selected is not None
    assert decision.selected.candidate_id == "safe"
    assert risky.risk_assessment is not None
    assert VetoReason.KRI_RED in risky.risk_assessment.veto_reasons


@pytest.mark.asyncio
async def test_cost_weight_can_shift_selection() -> None:
    cfg = OptimizerConfig(accuracy_weight=0.1, cost_weight=0.8, risk_weight=0.1)
    opt = _build_optimizer(config=cfg)
    cheap = _make_candidate("cheap", accuracy=0.6, cost=0.95)
    accurate = _make_candidate("accurate", accuracy=0.95, cost=0.3)
    decision = await opt.optimize("llm_route", [cheap, accurate])
    assert decision.selected is not None
    assert decision.selected.candidate_id == "cheap"
