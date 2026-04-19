from pathlib import Path

import pytest

from stc_framework.adapters.prompts.base import PromptRecord, PromptRegistry
from stc_framework.adapters.prompts.file_registry import FilePromptRegistry


async def _contract(registry: PromptRegistry) -> None:
    await registry.register(PromptRecord(name="p", version="v1", content="hello", active=True))
    rec = await registry.get("p")
    assert rec.content == "hello"
    versions = await registry.list_versions("p")
    assert len(versions) == 1
    assert await registry.healthcheck()


@pytest.mark.asyncio
async def test_file_registry_satisfies_contract(tmp_path: Path):
    await _contract(FilePromptRegistry(tmp_path / "p.json"))
