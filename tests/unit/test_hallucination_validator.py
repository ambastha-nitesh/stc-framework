import pytest

from stc_framework.critic.validators.base import ValidationContext
from stc_framework.critic.validators.hallucination import HallucinationValidator


@pytest.mark.asyncio
async def test_grounded_response_passes():
    v = HallucinationValidator(threshold=0.5, min_sentence_overlap=0.2)
    ctx = ValidationContext(
        query="revenue",
        response="Revenue was four billion in fiscal year 2024.",
        context="The company reported revenue of four billion in fiscal year 2024.",
    )
    r = await v.avalidate(ctx)
    assert r.passed


@pytest.mark.asyncio
async def test_ungrounded_response_fails():
    v = HallucinationValidator(threshold=0.9, min_sentence_overlap=0.5)
    ctx = ValidationContext(
        query="q",
        response=(
            "The moon landing in 1969 was a major historical event that "
            "changed space exploration forever."
        ),
        context="This document discusses corporate revenue for fiscal year 2024.",
    )
    r = await v.avalidate(ctx)
    assert not r.passed


@pytest.mark.asyncio
async def test_empty_context_large_response_blocks():
    v = HallucinationValidator()
    ctx = ValidationContext(
        query="q",
        response="This is a very long fabricated response " * 10,
        context="",
    )
    r = await v.avalidate(ctx)
    assert not r.passed
