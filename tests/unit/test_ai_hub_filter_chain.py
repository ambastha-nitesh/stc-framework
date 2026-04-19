"""Tests for the FR-3 / FR-5 filter chain orchestrator."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from stc_framework.ai_hub.errors import AIHubErrorCode
from stc_framework.ai_hub.filter_chain import (
    FilterChainBlocked,
    FilterChainError,
    FilterChainOrchestrator,
    FilterDirection,
    FilterInput,
    FilterOutcome,
    FilterVerdict,
)


@dataclass
class StaticFilter:
    """Test double whose ``run`` returns a pre-baked verdict immediately."""

    name: str
    direction: FilterDirection
    outcome: FilterOutcome = FilterOutcome.ALLOW
    reason_code: str | None = None

    async def run(self, input: FilterInput, deadline_ms: int) -> FilterVerdict:
        return FilterVerdict(
            filter_name=self.name,
            direction=self.direction,
            outcome=self.outcome,
            reason_code=self.reason_code,
            latency_ms=5,
        )


@dataclass
class SlowFilter:
    name: str
    direction: FilterDirection
    sleep_seconds: float

    async def run(self, input: FilterInput, deadline_ms: int) -> FilterVerdict:
        await asyncio.sleep(self.sleep_seconds)
        return FilterVerdict(
            filter_name=self.name,
            direction=self.direction,
            outcome=FilterOutcome.ALLOW,
            latency_ms=int(self.sleep_seconds * 1000),
        )


@dataclass
class ExplodingFilter:
    name: str
    direction: FilterDirection

    async def run(self, input: FilterInput, deadline_ms: int) -> FilterVerdict:
        raise RuntimeError("vendor-side blew up")


def _make_input() -> FilterInput:
    return FilterInput(
        request_id="01JABCDEF",
        domain_id="dom-1",
        agent_id="agent-1",
        payload={"messages": [{"role": "user", "content": "hello"}]},
        context={"model_id": "claude-haiku-4-5"},
    )


@pytest.mark.asyncio
async def test_all_allow_chain_runs_each_filter_in_order() -> None:
    chain = FilterChainOrchestrator(
        [
            StaticFilter("prompt_injection", FilterDirection.INPUT),
            StaticFilter("pii_input", FilterDirection.INPUT),
            StaticFilter("content_policy_input", FilterDirection.INPUT),
        ],
        direction=FilterDirection.INPUT,
    )
    verdicts = await chain.run(_make_input())
    assert [v.filter_name for v in verdicts] == [
        "prompt_injection",
        "pii_input",
        "content_policy_input",
    ]
    assert all(v.outcome is FilterOutcome.ALLOW for v in verdicts)


@pytest.mark.asyncio
async def test_first_block_short_circuits_chain() -> None:
    later = StaticFilter("pii_input", FilterDirection.INPUT)
    chain = FilterChainOrchestrator(
        [
            StaticFilter(
                "prompt_injection",
                FilterDirection.INPUT,
                outcome=FilterOutcome.BLOCK,
                reason_code="override_en",
            ),
            later,
        ],
        direction=FilterDirection.INPUT,
    )
    with pytest.raises(FilterChainBlocked) as ei:
        await chain.run(_make_input())
    # The blocking verdict is present; the later filter's verdict is NOT
    # (because the PRD says short-circuit on first non-ALLOW).
    assert [v.filter_name for v in ei.value.verdicts] == ["prompt_injection"]
    assert ei.value.filter_name == "prompt_injection"
    assert ei.value.code is AIHubErrorCode.GUARDRAIL_INPUT_BLOCK
    assert ei.value.reason_code == "override_en"


@pytest.mark.asyncio
async def test_output_block_emits_502_code() -> None:
    chain = FilterChainOrchestrator(
        [
            StaticFilter("pii_output", FilterDirection.OUTPUT, outcome=FilterOutcome.BLOCK),
        ],
        direction=FilterDirection.OUTPUT,
    )
    with pytest.raises(FilterChainBlocked) as ei:
        await chain.run(_make_input())
    assert ei.value.code is AIHubErrorCode.GUARDRAIL_OUTPUT_BLOCK
    assert ei.value.http_status == 502


@pytest.mark.asyncio
async def test_timeout_raises_guardrail_timeout_and_captures_partial_verdicts() -> None:
    chain = FilterChainOrchestrator(
        [
            StaticFilter("prompt_injection", FilterDirection.INPUT),
            SlowFilter("pii_input", FilterDirection.INPUT, sleep_seconds=0.5),
        ],
        direction=FilterDirection.INPUT,
        deadline_ms=50,  # aggressive — forces the second filter to time out
    )
    with pytest.raises(FilterChainError) as ei:
        await chain.run(_make_input())
    assert ei.value.code is AIHubErrorCode.GUARDRAIL_TIMEOUT
    assert ei.value.filter_name == "pii_input"
    # Earlier ALLOW is preserved so audit captures the state at failure.
    names = [v.filter_name for v in ei.value.verdicts]
    assert names == ["prompt_injection", "pii_input"]
    assert ei.value.verdicts[-1].outcome is FilterOutcome.ERROR
    assert ei.value.verdicts[-1].reason_code == "timeout"


@pytest.mark.asyncio
async def test_vendor_exception_raises_guardrail_error() -> None:
    chain = FilterChainOrchestrator(
        [ExplodingFilter("pii_input", FilterDirection.INPUT)],
        direction=FilterDirection.INPUT,
    )
    with pytest.raises(FilterChainError) as ei:
        await chain.run(_make_input())
    assert ei.value.code is AIHubErrorCode.GUARDRAIL_ERROR
    assert ei.value.filter_name == "pii_input"
    assert ei.value.verdicts[-1].outcome is FilterOutcome.ERROR
    assert ei.value.verdicts[-1].reason_code == "RuntimeError"


@pytest.mark.asyncio
async def test_error_self_report_still_produces_guardrail_error() -> None:
    chain = FilterChainOrchestrator(
        [
            StaticFilter(
                "content_policy_input",
                FilterDirection.INPUT,
                outcome=FilterOutcome.ERROR,
                reason_code="self_error",
            )
        ],
        direction=FilterDirection.INPUT,
    )
    with pytest.raises(FilterChainError) as ei:
        await chain.run(_make_input())
    assert ei.value.code is AIHubErrorCode.GUARDRAIL_ERROR


def test_construction_rejects_direction_mismatch() -> None:
    with pytest.raises(ValueError):
        FilterChainOrchestrator(
            [StaticFilter("pii_output", FilterDirection.OUTPUT)],
            direction=FilterDirection.INPUT,
        )


@pytest.mark.asyncio
async def test_empty_chain_returns_no_verdicts() -> None:
    chain = FilterChainOrchestrator([], direction=FilterDirection.INPUT)
    assert await chain.run(_make_input()) == []


@pytest.mark.asyncio
async def test_verdict_list_is_independent_from_orchestrator_state() -> None:
    chain = FilterChainOrchestrator(
        [StaticFilter("f1", FilterDirection.INPUT)],
        direction=FilterDirection.INPUT,
    )
    verdicts_a = await chain.run(_make_input())
    verdicts_b = await chain.run(_make_input())
    # Separate runs produce separate lists (no accumulation across runs).
    assert verdicts_a is not verdicts_b
