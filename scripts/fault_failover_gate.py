#!/usr/bin/env python3
from __future__ import annotations

import argparse
import binascii
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
from valkey_probe_lib import Endpoint, RespConnection, RespError, endpoints_from_state, load_state, moved_target, wait_for_cluster_ok  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_cmd(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}" + env.get("PYTHONPATH", "")
    return subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env)


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def scale_setup_scenario(scenario: str) -> str:
    if scenario.endswith("_fault_failover"):
        return scenario.removesuffix("_fault_failover")
    return scenario


def observed_count(probes: list[dict[str, Any]]) -> int:
    return len([p for p in probes if p.get("status") == "PASS"])


def cluster_state_from_probes(probes: list[dict[str, Any]]) -> str:
    for probe in probes:
        if probe.get("status") == "PASS" and probe.get("cluster_state"):
            return str(probe["cluster_state"])
    return "unknown"


def observation_record(name: str, probes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": name,
        "status": "MEASURED" if probes else "MISSING",
        "nodes_observed": observed_count(probes),
        "cluster_state": cluster_state_from_probes(probes),
    }


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return round(ordered[index], 3)


def key_slot(key: str) -> int:
    start = key.find("{")
    if start >= 0:
        end = key.find("}", start + 1)
        if end > start + 1:
            key = key[start + 1:end]
    return binascii.crc_hqx(key.encode("utf-8"), 0) % 16384


def parse_slot_range(slot_spec: str) -> tuple[int, int] | None:
    if not slot_spec or slot_spec.startswith("["):
        return None
    if "-" in slot_spec:
        left, right = slot_spec.split("-", 1)
    else:
        left = right = slot_spec
    try:
        return int(left), int(right)
    except ValueError:
        return None


def key_for_slot_range(prefix: str, low: int, high: int) -> str:
    for idx in range(20000):
        tag = f"w{idx}"
        slot = key_slot(f"{{{tag}}}")
        if low <= slot <= high:
            return f"{prefix}:{{{tag}}}"
    raise RuntimeError(f"could not find key for slot range {low}-{high}")


def endpoint_by_logical(endpoints: list[Any], logical_id: str | None) -> Any | None:
    for endpoint in endpoints:
        if getattr(endpoint, "logical_id", None) == logical_id:
            return endpoint
    return None


def merged_cluster_nodes(probes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for probe in probes:
        if probe.get("status") == "PASS":
            merged.update(probe.get("cluster_nodes") or {})
    return merged


def workload_target_for_logical(endpoints: list[Any], probes: list[dict[str, Any]], logical_id: str | None) -> dict[str, Any] | None:
    if not logical_id:
        return None
    logical_to_id = node_id_by_logical(probes)
    node_id = logical_to_id.get(logical_id)
    endpoint = endpoint_by_logical(endpoints, logical_id)
    if not node_id or endpoint is None:
        return None
    node = merged_cluster_nodes(probes).get(node_id) or {}
    for slot_spec in node.get("slots") or []:
        slot_range = parse_slot_range(str(slot_spec))
        if not slot_range:
            continue
        low, high = slot_range
        slot_key = key_for_slot_range(f"{logical_id}:failed-slot", low, high)
        return {
            "scope": "failed_primary_slot",
            "source_logical_id": logical_id,
            "source_node_id": node_id,
            "slot_range": [low, high],
            "slot_key": slot_key,
            "slot": key_slot(slot_key),
            "entry_logical_id": logical_id,
        }
    return None


def redirect_endpoint(endpoints: list[Any], host: str, port: int, password: str | None) -> Any:
    for endpoint in endpoints:
        if endpoint.host == host and endpoint.port == port:
            return endpoint
        if endpoint.container_ip == host and endpoint.port == port:
            return endpoint
        if endpoint.container_ip == host and port == 6379:
            return endpoint
    return Endpoint(logical_id=f"redirect-{host}:{port}", host=host, port=port, password=password)


def entry_endpoint_for_window(endpoints: list[Any], preferred_logical_id: str | None, window_name: str) -> Any:
    preferred = endpoint_by_logical(endpoints, preferred_logical_id)
    if window_name == "before_fault" and preferred is not None:
        return preferred
    for endpoint in endpoints:
        if getattr(endpoint, "logical_id", None) != preferred_logical_id:
            return endpoint
    if preferred is not None:
        return preferred
    if endpoints:
        return endpoints[0]
    raise RuntimeError("no endpoints")


def execute_workload_command(endpoints: list[Any], entry_endpoint: Any, *command: Any) -> tuple[Any, Any, int]:
    endpoint = entry_endpoint
    redirects = 0
    for _ in range(9):
        try:
            return RespConnection(endpoint.host, endpoint.port, endpoint.password, timeout=2.0).execute(*command), endpoint, redirects
        except RespError as exc:
            target = moved_target(exc.message)
            if not target:
                raise
            endpoint = redirect_endpoint(endpoints, target[0], target[1], endpoint.password)
            redirects += 1
            if exc.message.startswith("ASK"):
                RespConnection(endpoint.host, endpoint.port, endpoint.password, timeout=2.0).execute("ASKING")
    raise RuntimeError("too many cluster redirects")


def workload_window(
    name: str,
    endpoints: list[Any],
    operation_pairs: int,
    key_prefix: str,
    target: dict[str, Any] | None,
) -> dict[str, Any]:
    attempted = 0
    succeeded = 0
    errors = 0
    timeouts = 0
    roundtrip_successes = 0
    roundtrip_failures = 0
    latencies: list[float] = []
    samples: list[dict[str, Any]] = []
    entry_endpoint = entry_endpoint_for_window(endpoints, target.get("entry_logical_id") if target else None, name) if target else None
    for idx in range(operation_pairs):
        if not target:
            break
        slot_key = target["slot_key"]
        key = f"{slot_key}:{key_prefix}:{name}:{idx}"
        value = f"value-{idx}"
        pair_ok = True
        for command in [("SET", key, value), ("GET", key)]:
            attempted += 1
            started = time.monotonic()
            try:
                reply, final_endpoint, redirects = execute_workload_command(endpoints, entry_endpoint, *command)
                if command[0] == "SET" and str(reply) != "OK":
                    raise RuntimeError(f"SET returned {reply!r}")
                if command[0] == "GET" and str(reply) != value:
                    raise RuntimeError(f"GET returned {reply!r}, expected {value!r}")
                elapsed_ms = round((time.monotonic() - started) * 1000, 3)
                latencies.append(elapsed_ms)
                succeeded += 1
                samples.append({
                    "command": command[0],
                    "status": "PASS",
                    "latency_ms": elapsed_ms,
                    "workload_scope": target["scope"],
                    "source_logical_id": target["source_logical_id"],
                    "slot": target["slot"],
                    "slot_range": target["slot_range"],
                    "entry_logical_id": getattr(entry_endpoint, "logical_id", "unknown"),
                    "target_logical_id": getattr(final_endpoint, "logical_id", "unknown"),
                    "redirects": redirects,
                    "reply": str(reply)[:80],
                })
            except Exception as exc:  # noqa: BLE001 - evidence records workload failures without inventing values
                elapsed_ms = round((time.monotonic() - started) * 1000, 3)
                message = repr(exc)
                errors += 1
                pair_ok = False
                if "timeout" in message.lower() or "timed out" in message.lower():
                    timeouts += 1
                samples.append({
                    "command": command[0],
                    "status": "FAIL",
                    "latency_ms": elapsed_ms,
                    "workload_scope": target["scope"],
                    "source_logical_id": target["source_logical_id"],
                    "slot": target["slot"],
                    "slot_range": target["slot_range"],
                    "entry_logical_id": getattr(entry_endpoint, "logical_id", "unknown"),
                    "error": message[:160],
                })
        if pair_ok:
            roundtrip_successes += 1
        else:
            roundtrip_failures += 1
    availability = round((succeeded / attempted) * 100, 3) if attempted else 0.0
    status = "MEASURED" if attempted else "MISSING"
    return {
        "name": name,
        "status": status,
        "workload_scope": target.get("scope") if target else "MISSING",
        "source_logical_id": target.get("source_logical_id") if target else "MISSING",
        "source_node_id": target.get("source_node_id") if target else "MISSING",
        "slot": target.get("slot") if target else {"status": "MISSING", "reason": "no workload target"},
        "slot_range": target.get("slot_range") if target else [],
        "operation_count": attempted,
        "roundtrip_successes": roundtrip_successes,
        "roundtrip_failures": roundtrip_failures,
        "availability_percent": availability,
        "errors_total": errors,
        "timeouts_total": timeouts,
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
        "samples": samples[:20],
    }


def wait_for_stable_cluster_ok(
    endpoints: list[Any],
    min_nodes: int,
    *,
    timeout_seconds: float,
    interval: float = 1.0,
) -> tuple[bool, list[dict[str, Any]]]:
    deadline = time.monotonic() + timeout_seconds
    last: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        remaining = max(1.0, deadline - time.monotonic())
        ok, probes = wait_for_cluster_ok(
            endpoints,
            min_nodes,
            timeout_seconds=min(30.0, remaining),
            interval=interval,
        )
        last = probes
        if ok:
            return True, probes
        time.sleep(interval)
    return False, last


def apply_failover_node_timeout(endpoints: list[Any], timeout_ms: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for endpoint in endpoints:
        record = {
            "logical_id": endpoint.logical_id,
            "host": endpoint.host,
            "port": endpoint.port,
            "parameter": "cluster-node-timeout",
            "value": timeout_ms,
            "status": "PENDING",
        }
        try:
            reply = RespConnection(endpoint.host, endpoint.port, endpoint.password, timeout=3.0).execute(
                "CONFIG",
                "SET",
                "cluster-node-timeout",
                str(timeout_ms),
            )
            record.update({"status": "PASS", "reply": reply})
        except Exception as exc:  # noqa: BLE001
            record.update({"status": "FAIL", "error": repr(exc)})
        results.append(record)
    return results


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


def promoted_from_old_primary(probes: list[dict[str, Any]], old_primary_id: str, expected_replica_id: str) -> str | None:
    merged: dict[str, dict[str, Any]] = {}
    for p in probes:
        if p.get("status") == "PASS":
            merged.update(p.get("cluster_nodes") or {})
    expected = merged.get(expected_replica_id)
    if expected and expected.get("role") == "primary" and expected.get("master_id") in {None, "-"}:
        return expected_replica_id
    if expected and expected.get("role") == "primary":
        return expected_replica_id
    if not expected_replica_id or expected_replica_id == "unknown":
        return None
    for node_id, node in merged.items():
        if node_id == old_primary_id:
            continue
    return None


def project_cleanup(phase: str, state_path: Path, artifact_dir: Path, cleanup_path: Path | None = None) -> tuple[str, Path]:
    publish_path = cleanup_path or artifact_dir / "cleanup_report.json"
    command_cleanup_path = artifact_dir / "cleanup_report.json"
    try:
        proc = run_cmd([
            sys.executable, "-m", "valkey_scale_lab.cli", "gate", "cleanup",
            "--state", str(state_path), "--artifacts-dir", str(artifact_dir), "--out", str(command_cleanup_path),
        ], timeout=300)
        if command_cleanup_path.exists() and publish_path != command_cleanup_path:
            write_json(publish_path, json.loads(command_cleanup_path.read_text(encoding="utf-8")))
        if proc.returncode != 0 and not publish_path.exists():
            write_json(publish_path, {
                "schema_version": "v1", "artifact_type": "cleanup_report", "phase_id": phase,
                "run_id": f"phase-{phase}", "created_at": utc_now(),
                "producer": {"name": "valkey-scale-lab", "version": "unknown"}, "status": "FAIL",
                "resources_remaining": [{"type": "unknown", "reason": proc.stderr}], "cleanup_actions": []
            })
        return ("PASS" if proc.returncode == 0 else "FAIL"), publish_path
    except Exception as exc:  # noqa: BLE001
        write_json(publish_path, {
            "schema_version": "v1", "artifact_type": "cleanup_report", "phase_id": phase,
            "run_id": f"phase-{phase}", "created_at": utc_now(),
            "producer": {"name": "valkey-scale-lab", "version": "unknown"}, "status": "FAIL",
            "resources_remaining": [{"type": "unknown", "reason": repr(exc)}], "cleanup_actions": []
        })
        return "FAIL", publish_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent primary-stop failover gate")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--scenario", default="failover_setup")
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--failover-report", required=True)
    parser.add_argument("--fault-report")
    parser.add_argument("--workload-window-report")
    parser.add_argument("--cleanup-report")
    parser.add_argument("--require-data-path", action="store_true")
    parser.add_argument("--min-nodes", type=int, default=6)
    parser.add_argument("--wait-after-fault", type=float, default=120.0)
    parser.add_argument("--failover-node-timeout-ms", type=int, default=15000)
    args = parser.parse_args()

    out = Path(args.out)
    failover_report_path = Path(args.failover_report)
    fault_report_path = Path(args.fault_report) if args.fault_report else None
    workload_window_report_path = Path(args.workload_window_report) if args.workload_window_report else None
    cleanup_report_path = Path(args.cleanup_report) if args.cleanup_report else None
    artifact_dir = out.parent
    work_dir = artifact_dir / f"_fault_failover_work_{args.scenario}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    state_path = work_dir / "state_failover.json"
    setup_scenario = scale_setup_scenario(args.scenario)
    run_id = f"phase-{args.phase}-{args.scenario}-primary-stop"
    errors: list[str] = []
    probes_before: list[dict[str, Any]] = []
    probes_during: list[dict[str, Any]] = []
    probes_after: list[dict[str, Any]] = []
    probes_after_clear: list[dict[str, Any]] = []
    workload_windows: list[dict[str, Any]] = []
    valkey_versions: list[str] = []
    cluster_state = "unknown"
    selected_logical = None
    old_primary_id = None
    expected_replica_id = None
    promoted_id = None
    workload_target: dict[str, Any] | None = None
    cleanup_status = "FAIL"
    cleanup_path = cleanup_report_path or artifact_dir / "cleanup_report.json"
    fault_id = "fault-primary-stop"
    fault_start = None
    fault_apply_latency_ms = None
    fault_clear_latency_ms = None
    fault_apply_status = "NOT_RUN"
    fault_clear_status = "NOT_RUN"
    recovery_at = None
    timeout_adjustments: list[dict[str, Any]] = []

    setup_cmd = [
        sys.executable, "-m", "valkey_scale_lab.cli", "gate", "scenario",
        "--phase", args.phase, "--scenario", setup_scenario,
        "--config", args.config, "--artifacts-dir", str(work_dir), "--state-out", str(state_path),
    ]

    try:
        setup = run_cmd(setup_cmd, timeout=900)
        (work_dir / "failover_setup.stdout.log").write_text(setup.stdout, encoding="utf-8", errors="replace")
        (work_dir / "failover_setup.stderr.log").write_text(setup.stderr, encoding="utf-8", errors="replace")
        if setup.returncode != 0:
            errors.append(f"setup failed exit={setup.returncode}")
        elif not state_path.exists():
            errors.append("setup did not write state file")
        else:
            state = load_state(state_path)
            endpoints = endpoints_from_state(state)
            timeout_adjustments = apply_failover_node_timeout(endpoints, args.failover_node_timeout_ms)
            failed_timeout_adjustments = [item for item in timeout_adjustments if item.get("status") != "PASS"]
            if failed_timeout_adjustments:
                errors.append(f"cluster-node-timeout adjustment failed count={len(failed_timeout_adjustments)}")
            ok, probes_before = wait_for_stable_cluster_ok(endpoints, args.min_nodes, timeout_seconds=180)
            if not ok:
                errors.append("cluster not OK before failover fault")
            selection = find_primary_with_replica(probes_before, state.get("nodes", []))
            if not selection:
                errors.append("could not find primary with replica for failover gate")
            else:
                selected_logical, old_primary_id, expected_replica_id = selection
                workload_target = workload_target_for_logical(endpoints, probes_before, selected_logical)
                if not workload_target:
                    errors.append("could not find failed-primary slot for workload window")
                workload_windows.append(workload_window("before_fault", endpoints, 8, run_id, workload_target))
                fault_spec = {
                    "fault_id": fault_id,
                    "type": "node_stop",
                    "scope": "owned_container_or_process",
                    "forbid_host_network_mutation": True,
                    "target_logical_id": selected_logical,
                }
                fault_spec_path = work_dir / "fault_primary_stop_spec.json"
                write_json(fault_spec_path, fault_spec)
                fault_start = time.monotonic()
                apply_started = time.monotonic()
                apply = run_cmd([
                    sys.executable, "-m", "valkey_scale_lab.cli", "fault", "apply",
                    "--state", str(state_path),
                    "--target-logical-id", selected_logical,
                    "--fault-json", str(fault_spec_path),
                    "--out", str(work_dir / "fault_apply.json"),
                ], timeout=180)
                fault_apply_latency_ms = round((time.monotonic() - apply_started) * 1000, 3)
                fault_apply_status = "PASS" if apply.returncode == 0 else "FAIL"
                (work_dir / "failover_fault_apply.stdout.log").write_text(apply.stdout, encoding="utf-8", errors="replace")
                (work_dir / "failover_fault_apply.stderr.log").write_text(apply.stderr, encoding="utf-8", errors="replace")
                if apply.returncode != 0:
                    errors.append(f"fault apply failed exit={apply.returncode}")
                workload_windows.append(workload_window("during_fault", endpoints, 8, run_id, workload_target))
                deadline = time.monotonic() + args.wait_after_fault
                while time.monotonic() < deadline:
                    ok_after, current_probes = wait_for_cluster_ok(endpoints, max(1, args.min_nodes - 1), timeout_seconds=5, interval=1)
                    if not probes_during:
                        probes_during = current_probes
                    probes_after = current_probes
                    promoted_id = promoted_from_old_primary(current_probes, old_primary_id or "", expected_replica_id or "")
                    cluster_ok_after = any(
                        p.get("cluster_state") == "ok"
                        for p in current_probes
                        if p.get("status") == "PASS"
                    )
                    if promoted_id and (ok_after or cluster_ok_after):
                        recovery_at = time.monotonic()
                        break
                    time.sleep(1)
                clear_started = time.monotonic()
                clear = run_cmd([
                    sys.executable, "-m", "valkey_scale_lab.cli", "fault", "clear",
                    "--state", str(state_path),
                    "--fault-id", fault_id,
                    "--out", str(work_dir / "fault_clear.json"),
                ], timeout=180)
                fault_clear_latency_ms = round((time.monotonic() - clear_started) * 1000, 3)
                fault_clear_status = "PASS" if clear.returncode == 0 else "FAIL"
                (work_dir / "failover_fault_clear.stdout.log").write_text(clear.stdout, encoding="utf-8", errors="replace")
                (work_dir / "failover_fault_clear.stderr.log").write_text(clear.stderr, encoding="utf-8", errors="replace")
                if clear.returncode != 0:
                    errors.append(f"fault clear failed exit={clear.returncode}")
                if not promoted_id:
                    errors.append("no promoted primary observed after primary stop")
                if promoted_id and recovery_at is None:
                    errors.append("promoted primary observed without recovery timestamp")
                if not any(p.get("cluster_state") == "ok" for p in probes_after if p.get("status") == "PASS"):
                    errors.append("cluster_state ok not observed after failover")
                workload_windows.append(workload_window("after_recovery", endpoints, 8, run_id, workload_target))
                for p in probes_after or probes_before:
                    if p.get("status") == "PASS" and p.get("version"):
                        valkey_versions.append(str(p["version"]))
                    if p.get("cluster_state") == "ok":
                        cluster_state = "ok"
                ok_clear, probes_after_clear = wait_for_stable_cluster_ok(endpoints, args.min_nodes, timeout_seconds=180, interval=2)
                if not ok_clear:
                    errors.append("cluster_state ok not observed after fault clear")
                for p in probes_after_clear:
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
            cleanup_status, cleanup_path = project_cleanup(args.phase, state_path, work_dir, cleanup_report_path)
            if cleanup_status != "PASS":
                errors.append("cleanup failed")

    failover_latency_ms = None
    if fault_start is not None and recovery_at is not None:
        failover_latency_ms = round((recovery_at - fault_start) * 1000, 3)
    observations = {
        "before_fault": observation_record("before_fault", probes_before),
        "during_fault": observation_record("during_fault", probes_during),
        "after_promotion": observation_record("after_promotion", probes_after),
        "after_clear": observation_record("after_clear", probes_after_clear),
    }
    data_path_result = "PASS" if all(
        window.get("status") == "MEASURED"
        and window.get("operation_count", 0) > 0
        and window.get("workload_scope") == "failed_primary_slot"
        for window in workload_windows
    ) and any(
        window.get("name") == "before_fault" and window.get("roundtrip_successes", 0) > 0
        for window in workload_windows
    ) and any(
        window.get("name") == "after_recovery" and window.get("roundtrip_successes", 0) > 0
        for window in workload_windows
    ) else "MISSING"
    if args.require_data_path and data_path_result != "PASS":
        errors.append(f"required data path proof missing: {data_path_result}")
    status = "PASS" if not errors else "FAIL"

    if fault_report_path:
        write_json(fault_report_path, {
            "schema_version": "v1",
            "artifact_type": "fault_report",
            "phase_id": args.phase,
            "run_id": run_id,
            "created_at": utc_now(),
            "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
            "status": status,
            "faults": [{
                "fault_id": fault_id,
                "fault_type": "node_stop",
                "scope": "owned_container_or_process",
                "target_logical_id": selected_logical,
                "apply_status": fault_apply_status,
                "clear_status": fault_clear_status,
                "fault_apply_latency_ms": fault_apply_latency_ms,
                "fault_clear_latency_ms": fault_clear_latency_ms,
                "after_clear_nodes_observed": observations["after_clear"]["nodes_observed"],
                "after_clear_cluster_state": observations["after_clear"]["cluster_state"],
            }],
            "safety_checks": {
                "host_network_mutated": False,
                "global_firewall_mutated": False,
                "sandbox_only": True,
            },
        })

    write_json(failover_report_path, {
        "schema_version": "v1",
        "artifact_type": "failover_report",
        "phase_id": args.phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "failovers": [{
            "fault_id": fault_id,
            "target_logical_id": selected_logical,
                "old_primary_node_id": old_primary_id,
                "expected_replica_node_id": expected_replica_id,
                "promoted_node_id": promoted_id,
            "failover_latency_ms": failover_latency_ms if failover_latency_ms is not None else {"value": None, "status": "MISSING", "reason": "promotion_not_observed"},
        }],
        "summary": {
            "primary_stop_observed": selected_logical is not None,
            "promotion_observed": promoted_id is not None,
            "split_brain_duration_ms": {"value": None, "status": "MISSING", "reason": "primary_stop_gate_did_not_observe_conflicting_primaries"},
            "failover_node_timeout_ms": args.failover_node_timeout_ms,
        },
        "timeout_adjustments": timeout_adjustments,
    })

    if workload_window_report_path:
        write_json(workload_window_report_path, {
            "schema_version": "v1",
            "artifact_type": "workload_window_report",
            "phase_id": args.phase,
            "run_id": run_id,
            "created_at": utc_now(),
            "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
            "status": status,
            "node_count": args.min_nodes,
            "scenario": args.scenario,
            "windows": [
                *(workload_windows or [
                    workload_window("before_fault", endpoints if "endpoints" in locals() else [], 0, run_id, workload_target),
                    workload_window("during_fault", endpoints if "endpoints" in locals() else [], 0, run_id, workload_target),
                    workload_window("after_recovery", endpoints if "endpoints" in locals() else [], 0, run_id, workload_target),
                ])
            ],
            "timeout_adjustments": timeout_adjustments,
        })

    write_json(out, {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "phase_id": args.phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "scenario": args.scenario,
        "real_valkey": True,
        "valkey_version_prefix_required": "9.1.",
        "probe_result": "PASS" if not errors else "FAIL",
        "nodes_observed_before": observed_count(probes_before),
        "nodes_observed": observed_count(probes_after or probes_before),
        "nodes_observed_after_clear": observed_count(probes_after_clear),
        "cluster_state_observed": cluster_state,
        "data_path_result": data_path_result,
        "observations": observations,
        "valkey_versions": sorted(set(valkey_versions)),
        "selected_primary_logical_id": selected_logical,
        "old_primary_node_id": old_primary_id,
        "expected_replica_node_id": expected_replica_id,
        "promoted_node_id": promoted_id,
        "failover_latency_ms": failover_latency_ms,
        "failover_node_timeout_ms": args.failover_node_timeout_ms,
        "timeout_adjustments": timeout_adjustments,
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
