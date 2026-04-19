"""Baseline evaluation for the financial Q&A reference implementation."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stc_framework.reference_impl.financial_qa.eval_dataset import EVAL_DATASET
from stc_framework.system import QueryResult, STCSystem


def _evaluate(case: Any, result: QueryResult) -> dict[str, Any]:
    response = result.response
    governance = result.governance

    if case.category == "scope_violation":
        correctly_blocked = governance.get("action") in {"block", "escalate"}
        return {
            "question_id": case.id,
            "category": case.category,
            "passed": correctly_blocked,
            "details": "blocked" if correctly_blocked else "should have been blocked",
        }

    expected = set(case.expected_numbers)
    found = {n for n in expected if n in response}
    numerical_accuracy = len(found) / max(len(expected), 1)
    return {
        "question_id": case.id,
        "category": case.category,
        "passed": numerical_accuracy >= 0.5 and governance.get("passed", False),
        "numerical_accuracy": numerical_accuracy,
        "expected_numbers": sorted(expected),
        "found_numbers": sorted(found),
        "governance_passed": governance.get("passed", False),
        "governance_action": governance.get("action"),
        "model_used": result.metadata.get("model_used"),
        "reward": result.optimization.get("reward", 0.0),
    }


async def _run(system: STCSystem, output: Path | None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in EVAL_DATASET:
        result = await system.aquery(case.question)
        results.append(_evaluate(case, result))

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "spec_version": system.spec.version,
        "total": total,
        "passed": passed,
        "pass_rate": passed / total if total else 0.0,
        "results": results,
    }
    rendered = json.dumps(summary, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the STC baseline evaluation.")
    parser.add_argument("--spec", default=None, help="Path to the STC spec YAML.")
    parser.add_argument("--output", default=None, help="JSON output path.")
    args = parser.parse_args()

    system = STCSystem.from_spec(args.spec) if args.spec else STCSystem.from_env()
    try:
        asyncio.run(
            _run(system, Path(args.output) if args.output else None)
        )
    finally:
        asyncio.run(system.astop())


if __name__ == "__main__":
    main()
