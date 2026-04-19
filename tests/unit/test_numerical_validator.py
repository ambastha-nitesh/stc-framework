import pytest

from stc_framework.critic.validators.base import ValidationContext
from stc_framework.critic.validators.numerical import NumericalAccuracyValidator


@pytest.mark.asyncio
async def test_passes_when_numbers_grounded():
    v = NumericalAccuracyValidator(tolerance_percent=1.0)
    ctx = ValidationContext(
        query="revenue?",
        response="Revenue was $4.02 billion.",
        source_chunks=[{"text": "Q4 revenue was $4.02 billion."}],
    )
    result = await v.avalidate(ctx)
    assert result.passed


@pytest.mark.asyncio
async def test_fails_on_hallucinated_number():
    v = NumericalAccuracyValidator(tolerance_percent=1.0)
    ctx = ValidationContext(
        query="revenue?",
        response="Revenue was $4.5 billion.",
        source_chunks=[{"text": "Q4 revenue was $4.02 billion."}],
    )
    result = await v.avalidate(ctx)
    assert not result.passed
    assert "4.5 billion" in " ".join(result.evidence["ungrounded_numbers"])


@pytest.mark.asyncio
async def test_no_numbers_passes():
    v = NumericalAccuracyValidator()
    ctx = ValidationContext(query="hi", response="The answer is unclear.", source_chunks=[])
    result = await v.avalidate(ctx)
    assert result.passed


@pytest.mark.asyncio
async def test_tolerance_applies():
    v = NumericalAccuracyValidator(tolerance_percent=5.0)
    ctx = ValidationContext(
        query="revenue?",
        response="Revenue was $4.05 billion.",
        source_chunks=[{"text": "Revenue was $4.02 billion."}],
    )
    result = await v.avalidate(ctx)
    assert result.passed
