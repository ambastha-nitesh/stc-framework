import pytest
from hypothesis import given, strategies as st

from stc_framework.critic.validators.base import ValidationContext
from stc_framework.critic.validators.numerical import NumericalAccuracyValidator


@pytest.mark.asyncio
@given(amount=st.floats(min_value=0.01, max_value=1e6))
async def test_response_numbers_present_in_source_always_pass(amount: float):
    v = NumericalAccuracyValidator(tolerance_percent=0.0)
    formatted = f"{amount:.2f}"
    ctx = ValidationContext(
        query="q",
        response=f"The value is {formatted}.",
        source_chunks=[{"text": f"Reported {formatted} in source."}],
    )
    result = await v.avalidate(ctx)
    assert result.passed
