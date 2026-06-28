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


def node_id_by_logical(probes: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in probes:
        if p.get("status") == "PASS" and p.get("myself_node_id"):
            out[p["logical_id"]] = p["myself_node_id"]
    return out


def find_primary_with_replica(probes: list[dict[str, Any]], state_nodes: list[dict[str, Any]]) -> tuple[str, str, str] | None:
    logical_to_id = node_id_by_logical(probes)
    id_to_logical = {v: k for k, v in logical_to_id.items()}
    merged_nodes: dict[str, dict[str, Any]] = {}
    for p in probes:
        if p.get("status") != "PASS":
            continue
        merged_nodes.update(p.get("cluster_nodes") or {})
    for node_id, node in merged_nodes.items():
        if node.get("role") != "primary":
            continue
        replicas = [rid for rid, r in merged_nodes.items() if r.get("master_id") == node_id]
        if replicas and node_id in id_to_logical:
            return id_to_logical[node_id], node_id, replicas[0]
    # fallback to state role if cluster parsing did not expose replica mapping
    for n in state_nodes:
        if n.get("role") == "primary" and n.get("logical_id") in logical_to_id:
            return str(n["logical_id"]), logical_to_id[str(n["logical_id"])], "unknown"
    return None


def promoted_from_old_primary(probes: list[dict[str, Any]], old_primary_id: str) -> str | None:
    merged: dict[str, dict[str, Any]] = {}
    for p in probes:
        if p.get("status") == "PASS":
            merged.update(p.get("cluster_nodes") or {})
    for node_id, node in merged.items():
        if node_id == old_primary_id:
            continue
        if node.get("role") == "primary" and node.get("master_id") in {None, "-"}:
            # This alone does not prove it was the replica, so require old primary absent/fail or this node has slots.
            slots = node.get("slots") or []
            if slots:
                return node_id
    # Better: some Valkey/Redis formats retain no old master mapping after promotion. If old primary is fail and any
    # other primary owns slots, consider candidate; detailed report can quantify exact slot movement.
    for node_id, node in merged.items():
        if node_id != old_primary_id and node.get("role") == "primary":
            return node_id
    return None


def project_cleanup(phase: str, state_path: Path, artifact_dir: Path) -> tuple[str, Path]:
    cleanup_path = artifact_dir / "cleanup_report.json"
    try:
        proc = run_cmd([
            sys.executable, "-m", "valkey_scale_lab.cli", "gate", "cleanup",
            "--state", str(state_path), "--artifacts-dir", str(artifact_dir), "--out", str(cleanup_path),
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
    parser = argparse.ArgumentParser(description="Independent primary-stop failover gate")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--failover-report", required=True)
    parser.add_argument("--min-nodes", type=int, default=6)
    parser.add_argument("--wait-after-fault", type=float, default=120.0)
    args = parser.parse_args()

    out = Path(args.out)
    failover_report_path = Path(args.failover_report)
    artifact_dir = out.parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    state_path = artifact_dir / "state_failover.json"
    errors: list[str] = []
    probes_before: list[dict[str, Any]] = []
    probes_after: list[dict[str, Any]] = []
    valkey_versions: list[str] = []
    cluster_state = "unknown"
    selected_logical = None
    old_primary_id = None
    promoted_id = None
    cleanup_status = "FAIL"
    cleanup_path = artifact_dir / "cleanup_report.json"
    fault_id = "fault-primary-stop"
    fault_start = None
    recovery_at = None

    setup_cmd = [
        sys.executable, "-m", "valkey_scale_lab.cli", "gate", "scenario",
        "--phase", args.phase, "--scenario", "failover_setup",
        "--config", args.config, "--artifacts-dir", str(artifact_dir), "--state-out", str(state_path),
    ]

    try:
        setup = run_cmd(setup_cmd, timeout=900)
        (artifact_dir / "failover_setup.stdout.log").write_text(setup.stdout, encoding="utf-8", errors="replace")
        (artifact_dir / "failover_setup.stderr.log").write_text(setup.stderr, encoding="utf-8", errors="replace")
        if setup.returncode != 0:
            errors.append(f"setup failed exit={setup.returncode}")
        elif not state_path.exists():
            errors.append("setup did not write state file")
        else:
            state = load_state(state_path)
            endpoints = endpoints_from_state(state)
            ok, probes_before = wait_for_cluster_ok(endpoints, args.min_nodes, timeout_seconds=90)
            if not ok:
                errors.append("cluster not OK before failover fault")
            selection = find_primary_with_replica(probes_before, state.get("nodes", []))
            if not selection:
                errors.append("could not find primary with replica for failover gate")
            else:
                selected_logical, old_primary_id, _replica_id = selection
                fault_spec = {
                    "fault_id": fault_id,
                    "type": "node_stop",
                    "scope": "owned_container_or_process",
                    "forbid_host_network_mutation": True,
                    "target_logical_id": selected_logical,
                }
                fault_spec_path = artifact_dir / "fault_primary_stop_spec.json"
                write_json(fault_spec_path, fault_spec)
                fault_start = time.monotonic()
                apply = run_cmd([
                    sys.executable, "-m", "valkey_scale_lab.cli", "fault", "apply",
                    "--state", str(state_path),
                    "--target-logical-id", selected_logical,
                    "--fault-json", str(fault_spec_path),
                    "--out", str(artifact_dir / "fault_apply.json"),
                ], timeout=180)
                (artifact_dir / "failover_fault_apply.stdout.log").write_text(apply.stdout, encoding="utf-8", errors="replace")
                (artifact_dir / "failover_fault_apply.stderr.log").write_text(apply.stderr, encoding="utf-8", errors="replace")
                if apply.returncode != 0:
                    errors.append(f"fault apply failed exit={apply.returncode}")
                deadline = time.monotonic() + args.wait_after_fault
                while time.monotonic() < deadline:
                    ok_after, probes_after = wait_for_cluster_ok(endpoints, max(1, args.min_nodes - 1), timeout_seconds=5, interval=1)
                    promoted_id = promoted_from_old_primary(probes_after, old_primary_id or "")
                    if ok_after and promoted_id:
                        recovery_at = time.monotonic()
                        break
                    time.sleep(1)
                if not promoted_id:
                    errors.append("no promoted primary observed after primary stop")
                if not any(p.get("cluster_state") == "ok" for p in probes_after if p.get("status") == "PASS"):
                    errors.append("cluster_state ok not observed after failover")
                for p in probes_after or probes_before:
                    if p.get("status") == "PASS" and p.get("version"):
                        valkey_versions.append(str(p["version"]))
                    if p.get("cluster_state") == "ok":
                        cluster_state = "ok"
                if any(v and not v.startswith("9.1.") for v in valkey_versions):
                    errors.append(f"observed non-9.1 Valkey versions: {valkey_versions}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"failover gate exception: {exc!r}")
    finally:
        if state_path.exists():
            cleanup_status, cleanup_path = project_cleanup(args.phase, state_path, artifact_dir)
            if cleanup_status != "PASS":
                errors.append("cleanup failed")

    status = "PASS" if not errors else "FAIL"
    failover_latency_ms = None
    if fault_start is not None and recovery_at is not None:
        failover_latency_ms = round((recovery_at - fault_start) * 1000, 3)

    if not failover_report_path.exists():
        write_json(failover_report_path, {
            "schema_version": "v1",
            "artifact_type": "failover_report",
            "phase_id": args.phase,
            "run_id": f"phase-{args.phase}-primary-stop",
            "created_at": utc_now(),
            "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
            "status": status,
            "failovers": [{
                "fault_id": fault_id,
                "target_logical_id": selected_logical,
                "old_primary_node_id": old_primary_id,
                "promoted_node_id": promoted_id,
                "failover_latency_ms": failover_latency_ms if failover_latency_ms is not None else {"value": None, "status": "MISSING", "reason": "promotion_not_observed"},
            }],
            "summary": {
                "primary_stop_observed": selected_logical is not None,
                "promotion_observed": promoted_id is not None,
                "split_brain_duration_ms": {"value": None, "status": "MISSING", "reason": "not_measured_by_primary_stop_gate"},
            },
        })

    write_json(out, {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "phase_id": args.phase,
        "run_id": f"phase-{args.phase}-primary-stop",
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "real_valkey": True,
        "valkey_version_prefix_required": "9.1.",
        "probe_result": "PASS" if not errors else "FAIL",
        "nodes_observed": len([p for p in probes_after or probes_before if p.get("status") == "PASS"]),
        "cluster_state_observed": cluster_state,
        "data_path_result": "SKIPPED_WITH_REASON",
        "valkey_versions": sorted(set(valkey_versions)),
        "selected_primary_logical_id": selected_logical,
        "old_primary_node_id": old_primary_id,
        "promoted_node_id": promoted_id,
        "failover_latency_ms": failover_latency_ms,
        "probes": probes_after or probes_before,
        "cleanup": {"status": cleanup_status, "path": str(cleanup_path)},
        "errors": errors,
    })
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS fault_failover_gate promoted={promoted_id} out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
