"""``stc-governance flags …`` subcommand helpers.

Thin CLI glue — the real logic lives in
:class:`~stc_framework.feature_flags.client.LaunchDarklyClient` and
:class:`~stc_framework.feature_flags.subsystem_registry.SubsystemRegistry`.
"""

from __future__ import annotations

import argparse
import json
import sys

from stc_framework.config.settings import get_settings
from stc_framework.feature_flags.client import (
    LaunchDarklyClient,
    LaunchDarklyUnavailable,
)
from stc_framework.feature_flags.flags import FLAG_DEFAULTS, FlagKey
from stc_framework.feature_flags.subsystem_registry import SubsystemRegistry


def add_flags_subcommand(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Attach the ``flags`` group to an ``stc-governance`` argparse tree."""
    parser = sub.add_parser("flags", help="Inspect LaunchDarkly feature-flag state.")
    group = parser.add_subparsers(dest="flag_action", required=True)

    group.add_parser("list", help="Print every FlagKey and its hard default.")

    eval_cmd = group.add_parser("eval", help="Evaluate a single flag for this service.")
    eval_cmd.add_argument("--flag", required=True, help="FlagKey value, e.g. stc.compliance.enabled")
    eval_cmd.add_argument(
        "--deployed-subsystems",
        default="",
        help="Comma-separated subsystem list (matches Dockerfile DEPLOYED_SUBSYSTEMS).",
    )

    group.add_parser("status", help="Report LD SDK health + cache state.")

    parser.set_defaults(func=_run, _async=False)


def _run(args: argparse.Namespace) -> int:
    action = args.flag_action
    if action == "list":
        return _cmd_list()
    if action == "eval":
        return _cmd_eval(args)
    if action == "status":
        return _cmd_status()
    return 1


def _cmd_list() -> int:
    rows = [{"flag": flag.value, "default": FLAG_DEFAULTS[flag]} for flag in FlagKey]
    json.dump(rows, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    try:
        flag = FlagKey(args.flag)
    except ValueError:
        sys.stderr.write(f"unknown flag: {args.flag!r}\n")
        return 2
    settings = get_settings()
    try:
        client = LaunchDarklyClient(settings)
        client.start()
    except LaunchDarklyUnavailable as exc:
        sys.stderr.write(f"{exc}\n")
        return 3
    registry = SubsystemRegistry(client)
    deployed = [s.strip() for s in (args.deployed_subsystems or "").split(",") if s.strip()]
    state = registry.evaluate(settings, deployed_subsystems=deployed)
    result = {
        "flag": flag.value,
        "value": state[flag],
        "default": FLAG_DEFAULTS[flag],
        "sdk_initialised": client.is_initialized(),
    }
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    client.close()
    return 0


def _cmd_status() -> int:
    settings = get_settings()
    try:
        client = LaunchDarklyClient(settings)
        client.start()
    except LaunchDarklyUnavailable as exc:
        sys.stderr.write(f"{exc}\n")
        return 3
    status = {
        "relay_url": settings.ld_relay_url,
        "offline": settings.ld_offline_mode,
        "cache_path": settings.ld_cache_path,
        "sdk_initialised": client.is_initialized(),
    }
    json.dump(status, sys.stdout, indent=2)
    sys.stdout.write("\n")
    client.close()
    return 0


__all__ = ["add_flags_subcommand"]
