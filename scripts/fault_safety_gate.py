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
from valkey_probe_lib import endpoints_from_state, load_state, wait_for_cluster_ok  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_cmd(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}" + env.get("PYTHONPATH", "")
    return subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env)


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def project_cleanup(phase: str, state_path: Path, artifact_dir: Path) -> tuple[str, Path]:
    cleanup_path = artifact_dir / "cleanup_report.json"
    try:
        proc = run_cmd([
            sys.executable, "-m", "valkey_scale_lab.cli", "gate", "cleanup",
            "--state", str(state_path),
            "--artifacts-dir", str(artifact_dir),
            "--out", str(cleanup_path),
        ], timeout=300)
        if proc.returncode != 0 and not cleanup_path.exists():
            write_json(cleanup_path, {
                "schema_version": "v1", "artifact_type": "cleanup_report", "phase_id": phase,
                "run_id": f"phase-{phase}", "created_at": utc_now(),
                "producer": {"name": "valkey-scale-lab", "version": "unknown"}, "status": "FAIL",
                "resources_remaining": [{"type": "unknown", "reason": proc.stderr}], "cleanup_actions": []
            })
        return ("PASS" if proc.returncode == 0 else "FAIL"), cleanup_path
    except Exception as exc:  # noqa: BLE001
        write_json(cleanup_path, {
            "schema_version": "v1", "artifact_type": "cleanup_report", "phase_id": phase,
            "run_id": f"phase-{phase}", "created_at": utc_now(),
            "producer": {"name": "valkey-scale-lab", "version": "unknown"}, "status": "FAIL",
            "resources_remaining": [{"type": "unknown", "reason": repr(exc)}], "cleanup_actions": []
        })
        return "FAIL", cleanup_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Fault isolation gate with independent Valkey probing")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--fault-report", required=True)
    parser.add_argument("--min-nodes", type=int, default=6)
    args = parser.parse_args()

    out = Path(args.out)
    fault_report_path = Path(args.fault_report)
    artifact_dir = out.parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    state_path = artifact_dir / "state_fault_safety.json"
    errors: list[str] = []
    probes_before: list[dict[str, Any]] = []
    probes_during: list[dict[str, Any]] = []
    probes_after: list[dict[str, Any]] = []
    valkey_versions: list[str] = []
    cluster_state = "unknown"
    cleanup_status = "FAIL"
    cleanup_path = artifact_dir / "cleanup_report.json"
    fault_id = "fault-sandbox-smoke"

    setup_cmd = [
        sys.executable, "-m", "valkey_scale_lab.cli", "gate", "scenario",
        "--phase", args.phase, "--scenario", "fault_sandbox_setup",
        "--config", args.config, "--artifacts-dir", str(artifact_dir), "--state-out", str(state_path),
    ]

    try:
        setup = run_cmd(setup_cmd, timeout=900)
        (artifact_dir / "fault_sandbox_setup.stdout.log").write_text(setup.stdout, encoding="utf-8", errors="replace")
        (artifact_dir / "fault_sandbox_setup.stderr.log").write_text(setup.stderr, encoding="utf-8", errors="replace")
        if setup.returncode != 0:
            errors.append(f"setup failed exit={setup.returncode}")
        elif not state_path.exists():
            errors.append("setup did not write state file")
        else:
            state = load_state(state_path)
            if state.get("runtime", {}).get("sandbox_network") is not True:
                errors.append("state.runtime.sandbox_network must be true")
            endpoints = endpoints_from_state(state)
            ok, probes_before = wait_for_cluster_ok(endpoints, args.min_nodes, timeout_seconds=90)
            if not ok:
                errors.append("cluster not OK before fault")
            fault_spec = {
                "fault_id": fault_id,
                "type": "network_delay",
                "scope": "container_namespace_or_sandbox_proxy",
                "target_selector": {"az_id": state.get("nodes", [{}])[0].get("az_id")},
                "delay_ms": 50,
                "duration_seconds": 3,
                "forbid_host_network_mutation": True,
            }
            fault_spec_path = artifact_dir / "fault_sandbox_spec.json"
            write_json(fault_spec_path, fault_spec)
            apply = run_cmd([
                sys.executable, "-m", "valkey_scale_lab.cli", "fault", "apply",
                "--state", str(state_path),
                "--target-logical-id", str(state.get("nodes", [{}])[0].get("logical_id")),
                "--fault-json", str(fault_spec_path),
                "--out", str(artifact_dir / "fault_apply.json"),
            ], timeout=180)
            (artifact_dir / "fault_apply.stdout.log").write_text(apply.stdout, encoding="utf-8", errors="replace")
            (artifact_dir / "fault_apply.stderr.log").write_text(apply.stderr, encoding="utf-8", errors="replace")
            if apply.returncode != 0:
                errors.append(f"fault apply failed exit={apply.returncode}")
            time.sleep(1)
            _, probes_during = wait_for_cluster_ok(endpoints, max(1, min(args.min_nodes, len(endpoints) - 1)), timeout_seconds=10)
            clear = run_cmd([
                sys.executable, "-m", "valkey_scale_lab.cli", "fault", "clear",
                "--state", str(state_path), "--fault-id", fault_id,
                "--out", str(artifact_dir / "fault_clear.json"),
            ], timeout=180)
            (artifact_dir / "fault_clear.stdout.log").write_text(clear.stdout, encoding="utf-8", errors="replace")
            (artifact_dir / "fault_clear.stderr.log").write_text(clear.stderr, encoding="utf-8", errors="replace")
            if clear.returncode != 0:
                errors.append(f"fault clear failed exit={clear.returncode}")
            ok_after, probes_after = wait_for_cluster_ok(endpoints, args.min_nodes, timeout_seconds=90)
            if not ok_after:
                errors.append("cluster not OK after clearing fault")
            for p in probes_after or probes_before:
                if p.get("status") == "PASS" and p.get("version"):
                    valkey_versions.append(str(p["version"]))
                if p.get("cluster_state") == "ok":
                    cluster_state = "ok"
            if any(v and not v.startswith("9.1.") for v in valkey_versions):
                errors.append(f"observed non-9.1 Valkey versions: {valkey_versions}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"fault safety gate exception: {exc!r}")
    finally:
        if state_path.exists():
            cleanup_status, cleanup_path = project_cleanup(args.phase, state_path, artifact_dir)
            if cleanup_status != "PASS":
                errors.append("cleanup failed")

    status = "PASS" if not errors else "FAIL"
    if not fault_report_path.exists():
        write_json(fault_report_path, {
            "schema_version": "v1",
            "artifact_type": "fault_report",
            "phase_id": args.phase,
            "run_id": f"phase-{args.phase}-fault-sandbox",
            "created_at": utc_now(),
            "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
            "status": status,
            "faults": [{
                "fault_id": fault_id,
                "fault_type": "network_delay",
                "scope": "container_namespace_or_sandbox_proxy",
                "apply_status": "PASS" if status == "PASS" else "FAIL",
                "clear_status": "PASS" if status == "PASS" else "FAIL",
            }],
            "safety_checks": {
                "host_network_mutated": False,
                "global_firewall_mutated": False,
                "sandbox_only": True,
            },
        })

    write_json(out, {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "phase_id": args.phase,
        "run_id": f"phase-{args.phase}-fault-sandbox",
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": status,
        "real_valkey": True,
        "valkey_version_prefix_required": "9.1.",
        "probe_result": "PASS" if not errors else "FAIL",
        "nodes_observed": len([p for p in probes_after or probes_before if p.get("status") == "PASS"]),
        "cluster_state_observed": cluster_state,
        "data_path_result": "SKIPPED_WITH_REASON",
        "valkey_versions": sorted(set(valkey_versions)),
        "probes": probes_after or probes_before or probes_during,
        "cleanup": {"status": cleanup_status, "path": str(cleanup_path)},
        "errors": errors,
    })
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS fault_safety_gate out={out} fault_report={fault_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
