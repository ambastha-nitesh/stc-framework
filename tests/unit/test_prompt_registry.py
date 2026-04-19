from pathlib import Path

import pytest

from stc_framework.adapters.prompts.base import PromptRecord
from stc_framework.adapters.prompts.file_registry import FilePromptRegistry
from stc_framework.errors import PromptRegistryError


@pytest.mark.asyncio
async def test_register_and_get(tmp_path: Path):
    reg = FilePromptRegistry(tmp_path / "p.json")
    await reg.register(
        PromptRecord(name="p1", version="v1", content="hello", active=True)
    )
    record = await reg.get("p1")
    assert record.content == "hello"


@pytest.mark.asyncio
async def test_set_active_flips_pointer(tmp_path: Path):
    reg = FilePromptRegistry(tmp_path / "p.json")
    await reg.register(PromptRecord(name="p1", version="v1", content="hello", active=True))
    await reg.register(PromptRecord(name="p1", version="v2", content="world", active=False))
    await reg.set_active("p1", "v2")
    record = await reg.get("p1")
    assert record.version == "v2"


@pytest.mark.asyncio
async def test_register_duplicate_raises(tmp_path: Path):
    reg = FilePromptRegistry(tmp_path / "p.json")
    await reg.register(PromptRecord(name="p1", version="v1", content="hello", active=True))
    with pytest.raises(PromptRegistryError):
        await reg.register(
            PromptRecord(name="p1", version="v1", content="dup", active=False)
        )


@pytest.mark.asyncio
async def test_get_unknown_prompt_raises(tmp_path: Path):
    reg = FilePromptRegistry(tmp_path / "p.json")
    with pytest.raises(PromptRegistryError):
        await reg.get("does_not_exist")
