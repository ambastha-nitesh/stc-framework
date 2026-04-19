"""Adversarial suite tests using the mock LLM."""

from __future__ import annotations

from pathlib import Path

import pytest

from stc_framework.adapters.embeddings.hash_embedder import HashEmbedder
from stc_framework.adapters.llm.mock import MockLLMClient
from stc_framework.adapters.vector_store.in_memory import InMemoryVectorStore
from stc_framework.adversarial.runner import run_adversarial_suite
from stc_framework.config.settings import STCSettings
from stc_framework.system import STCSystem


@pytest.mark.asyncio
async def test_adversarial_suite_reports_critical_block_rate(tmp_path: Path, fixture_dir: Path):
    settings = STCSettings(
        presidio_enabled=False,
        metrics_enabled=False,
        log_format="text",
        audit_path=str(tmp_path / "audit"),
    )
    system = STCSystem.from_spec(
        fixture_dir / "minimal_spec.yaml",
        settings=settings,
        llm=MockLLMClient(),
        vector_store=InMemoryVectorStore(),
        embeddings=HashEmbedder(vector_size=64),
    )
    try:
        report = await run_adversarial_suite(system)
        assert report["total_probes"] >= 1
        assert "aiuc_1_compliance" in report
        # Critical pass rate should be high since input-rail injection blocker fires.
        assert report["critical_pass_rate"] >= 0.5
    finally:
        await system.astop()
