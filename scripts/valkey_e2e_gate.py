#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from valkey_probe_lib import endpoints_from_state, execute_cluster_command, load_state, probe_endpoint, wait_for_cluster_ok  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_cmd(cmd: list[str], timeout: int, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}" + merged.get("PYTHONPATH", "")
    if env:
        merged.update(env)
    return subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=merged)


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def cleanup(phase: str, state_path: Path, artifact_dir: Path, timeout: int) -> tuple[str, Path, str, str, int]:
    cleanup_path = artifact_dir / "cleanup_report.json"
    cmd = [
        sys.executable, "-m", "valkey_scale_lab.cli", "gate", "cleanup",
        "--state", str(state_path),
        "--artifacts-dir", str(artifact_dir),
        "--out", str(cleanup_path),
    ]
    try:
        proc = run_cmd(cmd, timeout=timeout)
        status = "PASS" if proc.returncode == 0 else "FAIL"
        if not cleanup_path.exists():
            write_json(cleanup_path, {
                "schema_version": "v1",
                "artifact_type": "cleanup_report",
                "phase_id": phase,
                "run_id": f"phase-{phase}",
                "created_at": utc_now(),
                "producer": {"name": "valkey-scale-lab", "version": "unknown"},
                "status": "FAIL",
                "resources_remaining": [{"type": "unknown", "reason": "cleanup command did not write cleanup_report"}],
                "cleanup_actions": [],
            })
        return status, cleanup_path, proc.stdout, proc.stderr, proc.returncode
    except Exception as exc:  # noqa: BLE001
        write_json(cleanup_path, {
            "schema_version": "v1",
            "artifact_type": "cleanup_report",
            "phase_id": phase,
            "run_id": f"phase-{phase}",
            "created_at": utc_now(),
            "producer": {"name": "valkey-scale-lab", "version": "unknown"},
            "status": "FAIL",
            "resources_remaining": [{"type": "unknown", "reason": repr(exc)}],
            "cleanup_actions": [],
        })
        return "FAIL", cleanup_path, "", repr(exc), 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent real Valkey e2e gate wrapper")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-nodes", type=int, default=1)
    parser.add_argument("--expected-version-prefix", default="9.1.")
    parser.add_argument("--require-data-path", action="store_true")
    parser.add_argument("--setup-timeout", type=int, default=900)
    parser.add_argument("--cleanup-timeout", type=int, default=300)
    parser.add_argument("--probe-timeout", type=float, default=2.0)
    parser.add_argument("--wait-cluster-timeout", type=float, default=90.0)
    args = parser.parse_args()

    out = Path(args.out)
    artifact_dir = out.parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    state_path = artifact_dir / f"state_{args.scenario}.json"
    setup_stdout = artifact_dir / f"{args.scenario}_setup.stdout.log"
    setup_stderr = artifact_dir / f"{args.scenario}_setup.stderr.log"

    setup_cmd = [
        sys.executable, "-m", "valkey_scale_lab.cli", "gate", "scenario",
        "--phase", args.phase,
        "--scenario", args.scenario,
        "--config", args.config,
        "--artifacts-dir", str(artifact_dir),
        "--state-out", str(state_path),
    ]

    started = utc_now()
    setup_status = "FAIL"
    cleanup_status = "FAIL"
    probes: list[dict[str, Any]] = []
    data_path_result = "SKIPPED_WITH_REASON" if not args.require_data_path else "FAIL"
    errors: list[str] = []
    valkey_versions: list[str] = []
    cluster_state = "unknown"

    try:
        proc = run_cmd(setup_cmd, timeout=args.setup_timeout)
        setup_stdout.write_text(proc.stdout, encoding="utf-8", errors="replace")
        setup_stderr.write_text(proc.stderr, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            errors.append(f"setup command failed exit={proc.returncode}")
        elif not state_path.exists():
            errors.append(f"setup did not write state file {state_path}")
        else:
            setup_status = "PASS"
            state = load_state(state_path)
            runtime = state.get("runtime", {})
            if runtime.get("sandbox_network") is not True:
                errors.append("state.runtime.sandbox_network must be true")
            endpoints = endpoints_from_state(state)
            ok, probes = wait_for_cluster_ok(endpoints, min_nodes=args.min_nodes, timeout_seconds=args.wait_cluster_timeout)
            if not ok:
                errors.append("cluster did not reach observable OK state with required node count")
            for p in probes:
                if p.get("status") == "PASS":
                    if p.get("version"):
                        valkey_versions.append(str(p["version"]))
                    if p.get("cluster_state") == "ok":
                        cluster_state = "ok"
            bad_versions = [v for v in valkey_versions if not v.startswith(args.expected_version_prefix)]
            if bad_versions:
                errors.append(f"observed Valkey versions do not match {args.expected_version_prefix}: {bad_versions}")
            if args.require_data_path:
                key = f"{{vslab-probe}}:{args.phase}:{int(time.time())}"
                value = f"value-{args.scenario}"
                try:
                    set_res = execute_cluster_command(endpoints, "SET", key, value, timeout=args.probe_timeout)
                    get_res = execute_cluster_command(endpoints, "GET", key, timeout=args.probe_timeout)
                    if str(set_res).upper() == "OK" and get_res == value:
                        data_path_result = "PASS"
                    else:
                        data_path_result = "FAIL"
                        errors.append(f"SET/GET mismatch set={set_res!r} get={get_res!r}")
                except Exception as exc:  # noqa: BLE001
                    data_path_result = "FAIL"
                    errors.append(f"data path probe failed: {exc!r}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"setup/probe exception: {exc!r}")
    finally:
        if state_path.exists():
            cleanup_status, cleanup_path, cleanup_stdout, cleanup_stderr, cleanup_exit = cleanup(
                args.phase, state_path, artifact_dir, args.cleanup_timeout
            )
            (artifact_dir / f"{args.scenario}_cleanup.stdout.log").write_text(cleanup_stdout, encoding="utf-8", errors="replace")
            (artifact_dir / f"{args.scenario}_cleanup.stderr.log").write_text(cleanup_stderr, encoding="utf-8", errors="replace")
            if cleanup_status != "PASS":
                errors.append(f"cleanup failed exit={cleanup_exit}")
        else:
            cleanup_path = artifact_dir / "cleanup_report.json"
            write_json(cleanup_path, {
                "schema_version": "v1",
                "artifact_type": "cleanup_report",
                "phase_id": args.phase,
                "run_id": f"phase-{args.phase}",
                "created_at": utc_now(),
                "producer": {"name": "valkey-scale-lab", "version": "unknown"},
                "status": "FAIL",
                "resources_remaining": [{"type": "unknown", "reason": "no state file, cleanup could not run"}],
                "cleanup_actions": [],
            })

    status = "PASS" if not errors else "FAIL"
    evidence = {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "phase_id": args.phase,
        "run_id": f"phase-{args.phase}-{args.scenario}",
        "created_at": utc_now(),
        "producer": {"name": "scripts/valkey_e2e_gate.py", "version": "v1"},
        "status": status,
        "real_valkey": True,
        "valkey_version_prefix_required": args.expected_version_prefix,
        "probe_result": "PASS" if not errors else "FAIL",
        "nodes_observed": len([p for p in probes if p.get("status") == "PASS"]),
        "cluster_state_observed": cluster_state,
        "data_path_result": data_path_result,
        "valkey_versions": sorted(set(valkey_versions)),
        "scenario": args.scenario,
        "started_at": started,
        "finished_at": utc_now(),
        "setup": {
            "command": setup_cmd,
            "status": setup_status,
            "stdout_path": str(setup_stdout),
            "stderr_path": str(setup_stderr),
        },
        "probes": probes,
        "cleanup": {
            "status": cleanup_status,
            "path": str(cleanup_path),
        },
        "errors": errors,
    }
    write_json(out, evidence)
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS real_valkey_e2e scenario={args.scenario} nodes={evidence['nodes_observed']} out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
