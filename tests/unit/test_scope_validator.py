import pytest

from stc_framework.critic.validators.base import ValidationContext
from stc_framework.critic.validators.scope import ScopeValidator


@pytest.mark.asyncio
async def test_blocks_investment_recommendation():
    v = ScopeValidator(prohibited_topics=["investment_recommendations"])
    ctx = ValidationContext(
        query="should i buy?",
        response="I recommend you buy ACME stock at this price target.",
    )
    r = await v.avalidate(ctx)
    assert not r.passed
    assert r.action == "block"


@pytest.mark.asyncio
async def test_allows_financial_question():
    v = ScopeValidator(prohibited_topics=["investment_recommendations"])
    ctx = ValidationContext(
        query="revenue?",
        response="Revenue was $100M in FY2024.",
    )
    r = await v.avalidate(ctx)
    assert r.passed


@pytest.mark.asyncio
async def test_allowed_topics_warns_when_off_topic():
    v = ScopeValidator(allowed_topics=["financial_data", "document_content"])
    ctx = ValidationContext(
        query="weather?",
        response="It is raining today in New York.",
    )
    r = await v.avalidate(ctx)
    assert r.action == "warn"
    assert not r.passed
