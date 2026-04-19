"""Contract tests that every LLMClient implementation must pass."""

import pytest

from stc_framework.adapters.llm.base import ChatMessage, LLMClient
from stc_framework.adapters.llm.mock import MockLLMClient


async def _contract(client: LLMClient) -> None:
    assert await client.healthcheck()
    response = await client.acompletion(
        model="mock/test",
        messages=[ChatMessage(role="user", content="hello")],
        timeout=5.0,
    )
    assert isinstance(response.content, str)
    assert response.model


@pytest.mark.asyncio
async def test_mock_client_satisfies_contract():
    await _contract(MockLLMClient())
