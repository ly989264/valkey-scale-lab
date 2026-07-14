#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valkey_scale_lab.compat import resolve_phase_alias  # noqa: E402
from valkey_scale_lab.execution import (  # noqa: E402
    PROFILES,
    ExecutionSelectionError,
    resolve_profile,
)

FAULT_MATRIX_CAPABILITY = "fault_matrix"
FAULT_MATRIX_SCENARIO = "fault_matrix"
FAULT_MATRIX_BACKENDS = {"docker_container", "docker_process"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compatibility entry point for the canonical fault matrix gate."
    )
    parser.add_argument("--capability-id")
    parser.add_argument("--scenario", default=FAULT_MATRIX_SCENARIO)
    parser.add_argument("--backend", choices=sorted(FAULT_MATRIX_BACKENDS))
    parser.add_argument("--profile", choices=["small-real", "exact-50", "exact-100", "exact-200"])
    parser.add_argument("--nodes", dest="requested_nodes", type=int)
    parser.add_argument("--min-nodes", dest="requested_nodes", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--config")
    parser.add_argument("--out", required=True)
    parser.add_argument("--failover-report")
    parser.add_argument("--fault-report", required=True)
    parser.add_argument("--workload-window-report")
    parser.add_argument("--cleanup-report")
    parser.add_argument("--phase", dest="legacy_alias_id", help=argparse.SUPPRESS)
    return parser


def _selection(args: argparse.Namespace) -> tuple[str, str, str, str, int]:
    capability_id = args.capability_id or FAULT_MATRIX_CAPABILITY
    scenario = args.scenario
    profile_id = args.profile or "small-real"
    backend = args.backend or (
        "docker_container" if profile_id == "small-real" else "docker_process"
    )
    if args.legacy_alias_id:
        alias = resolve_phase_alias(args.legacy_alias_id, FAULT_MATRIX_SCENARIO)
        capability_id = alias.capability_id
        scenario = alias.scenario_id
        backend = alias.backend_id
        profile_id = alias.profile_id
    if capability_id != FAULT_MATRIX_CAPABILITY or scenario != FAULT_MATRIX_SCENARIO:
        raise ExecutionSelectionError(
            "fault_safety_gate is an alias of the canonical fault_matrix scenario only"
        )
    if backend not in FAULT_MATRIX_BACKENDS:
        raise ExecutionSelectionError(f"unsupported fault matrix backend {backend!r}")
    requested_nodes = args.requested_nodes or PROFILES[profile_id].requested_nodes
    profile = resolve_profile(profile_id, requested_nodes=requested_nodes)
    return capability_id, scenario, backend, profile.profile_id, profile.requested_nodes


def main() -> int:
    args = _parser().parse_args()
    try:
        capability_id, scenario, backend, profile_id, requested_nodes = _selection(args)
    except (ExecutionSelectionError, KeyError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    profile = PROFILES[profile_id]
    config = args.config or profile.config_template
    artifact_dir = Path(args.out).parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(ROOT / "scripts" / "fault_failover_gate.py"),
        "--capability-id",
        capability_id,
        "--scenario",
        scenario,
        "--backend",
        backend,
        "--profile",
        profile_id,
        "--min-nodes",
        str(requested_nodes),
        "--config",
        str(config),
        "--out",
        args.out,
        "--failover-report",
        args.failover_report or str(artifact_dir / "failover_report.json"),
        "--fault-report",
        args.fault_report,
        "--workload-window-report",
        args.workload_window_report or str(artifact_dir / "workload_windows.json"),
        "--cleanup-report",
        args.cleanup_report or str(artifact_dir / "cleanup_report.json"),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}" + env.get(
        "PYTHONPATH", ""
    )
    result = subprocess.run(command, cwd=ROOT, env=env, text=True)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
