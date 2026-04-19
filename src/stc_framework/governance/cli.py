"""Operator-facing governance CLI.

Exposes:

- ``stc-governance verify-chain`` — verify the tamper-evident hash chain of an audit directory.
- ``stc-governance dsar <tenant>`` — export a DSAR record for ``tenant``.
- ``stc-governance erase <tenant>`` — execute the right-to-erasure workflow.
- ``stc-governance retention`` — run retention against the spec's ``audit.retention_days``.
- ``stc-governance flags …`` — inspect LaunchDarkly feature-flag state.

Designed to be invoked by runbooks, incident scripts, or scheduled jobs
(cron / Kubernetes CronJob) without requiring the caller to write
boilerplate bootstrap code.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _cmd_verify_chain(args: argparse.Namespace) -> int:
    from stc_framework.adapters.audit_backend.local_file import JSONLAuditBackend
    from stc_framework.observability.audit import verify_chain

    backend = JSONLAuditBackend(args.audit_dir)
    ok, count, why = verify_chain(backend.iter_records())
    payload = {"ok": ok, "records_verified": count, "failure_reason": why or None}
    print(json.dumps(payload, indent=2))
    return 0 if ok else 1


async def _cmd_dsar(args: argparse.Namespace) -> int:
    from stc_framework.system import STCSystem

    system = STCSystem.from_spec(args.spec) if args.spec else STCSystem.from_env()
    await system.astart()
    try:
        record = await system.aexport_tenant(args.tenant)
        out = json.dumps(record, indent=2, default=str)
        if args.output:
            Path(args.output).write_text(out, encoding="utf-8")
        else:
            print(out)
    finally:
        await system.astop()
    return 0


async def _cmd_erase(args: argparse.Namespace) -> int:
    from stc_framework.system import STCSystem

    if not args.yes:
        print(
            f"About to erase ALL records for tenant {args.tenant!r}. " "Re-run with --yes to confirm.",
            file=sys.stderr,
        )
        return 2
    system = STCSystem.from_spec(args.spec) if args.spec else STCSystem.from_env()
    await system.astart()
    try:
        summary = await system.aerase_tenant(args.tenant)
        print(json.dumps(summary, indent=2))
    finally:
        await system.astop()
    return 0


async def _cmd_retention(args: argparse.Namespace) -> int:
    from stc_framework.system import STCSystem

    system = STCSystem.from_spec(args.spec) if args.spec else STCSystem.from_env()
    await system.astart()
    try:
        summary = await system.aapply_retention()
        print(json.dumps(summary, indent=2))
    finally:
        await system.astop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stc-governance",
        description="STC Framework governance operations.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    vc = sub.add_parser("verify-chain", help="Verify audit hash chain integrity.")
    vc.add_argument("audit_dir", help="Path to the audit JSONL directory.")
    vc.set_defaults(func=_cmd_verify_chain, _async=False)

    ds = sub.add_parser("dsar", help="Export a tenant's data (DSAR).")
    ds.add_argument("tenant")
    ds.add_argument("--spec", default=None)
    ds.add_argument("--output", default=None)
    ds.set_defaults(func=_cmd_dsar, _async=True)

    er = sub.add_parser("erase", help="Erase all data for a tenant.")
    er.add_argument("tenant")
    er.add_argument("--spec", default=None)
    er.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation; no prompt is shown.",
    )
    er.set_defaults(func=_cmd_erase, _async=True)

    rt = sub.add_parser("retention", help="Apply retention across all stores.")
    rt.add_argument("--spec", default=None)
    rt.set_defaults(func=_cmd_retention, _async=True)

    # v0.3.1 — LaunchDarkly feature-flag inspection
    from stc_framework.feature_flags.cli import add_flags_subcommand

    add_flags_subcommand(sub)

    args = parser.parse_args(argv)
    # The flags subcommand sets ``_async`` via its own add_flags_subcommand
    # default, but we add a fallback here so older subparsers still work.
    is_async = getattr(args, "_async", False)
    result = asyncio.run(args.func(args)) if is_async else args.func(args)
    return int(result)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
