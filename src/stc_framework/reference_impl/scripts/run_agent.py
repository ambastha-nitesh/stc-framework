"""Interactive CLI for the financial Q&A reference implementation."""

from __future__ import annotations

import argparse
import asyncio
import sys

from stc_framework.system import STCSystem


async def _repl(system: STCSystem) -> None:
    print("STC Framework - Financial Q&A (type /quit to exit)\n")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line == "/quit":
            return
        if line == "/health":
            report = await system.ahealth_check()
            print(report)
            continue
        if line.startswith("/feedback "):
            parts = line.split()
            if len(parts) == 3:
                system.submit_feedback(parts[1], parts[2])
                print("ok")
            else:
                print("usage: /feedback <trace_id> <thumbs_up|thumbs_down>")
            continue

        result = await system.aquery(line)
        print(f"[{result.trace_id}] {result.response}")
        for rail in result.governance.get("rail_results", []):
            status = "OK" if rail["passed"] else "FAIL"
            print(f"  - {rail['name']} [{rail['severity']}] {status}: {rail['details']}")
        print(f"  reward={result.optimization['reward']:.3f}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the STC Financial Q&A agent.")
    parser.add_argument("--spec", default=None, help="Path to the spec YAML.")
    args = parser.parse_args()

    system = STCSystem.from_spec(args.spec) if args.spec else STCSystem.from_env()
    try:
        asyncio.run(_repl(system))
    finally:
        asyncio.run(system.astop())


if __name__ == "__main__":
    sys.exit(main())
