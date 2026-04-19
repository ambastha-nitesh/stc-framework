"""Load sample documents into the STC vector store."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from stc_framework.reference_impl.financial_qa.loader import load_text_document
from stc_framework.system import STCSystem


async def _run(spec: str | None, paths: list[str]) -> None:
    system = STCSystem.from_spec(spec) if spec else STCSystem.from_env()
    await system.astart()
    total = 0
    for p in paths:
        count = await load_text_document(
            source=Path(p),
            vector_store=system.vector_store,
            embeddings=system.embeddings,
        )
        total += count
        print(f"loaded {count} chunks from {p}")
    print(f"total chunks loaded: {total}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", default=None)
    parser.add_argument("paths", nargs="+", help="Text files to load")
    args = parser.parse_args()
    asyncio.run(_run(args.spec, args.paths))


if __name__ == "__main__":
    main()
