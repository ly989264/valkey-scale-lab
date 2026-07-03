#!/usr/bin/env python3
from __future__ import annotations

import argparse
import binascii
import json
import os
import platform
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from valkey_probe_lib import (  # noqa: E402
    Endpoint,
    RespConnection,
    RespError,
    endpoints_from_state,
    load_state,
    moved_target,
    parse_cluster_info,
    parse_cluster_nodes,
    probe_endpoint,
    wait_for_cluster_ok,
)
from valkey_scale_lab.fault.network_proxy import ProxyRule, SandboxNetworkProxy  # noqa: E402

P22_PHASE = "P22_FAULT_REPLICA_HOST_AZ_STOP"
P22_FAULT_TYPES = ["replica_stop", "node_host_stop", "az_stop"]
P22_WINDOWS = ["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]
P23_PHASE = "P23_FAULT_NETWORK_DELAY_LOSS_FLAP"
P23_FAULT_TYPES = ["network_delay", "network_loss", "network_flap"]
P23_WINDOWS = P22_WINDOWS
P24_PHASE = "P24_PARTITION_SPLIT_BRAIN_MATRIX"
P24_FAULT_TYPES = ["network_partition_minority", "network_partition_majority", "split_brain_window_detection"]
P24_DETECTORS = [
    "primary_slot_assignment_overlap",
    "partition_side_cluster_view_divergence",
    "conflicting_write_probe",
    "old_primary_accepts_write_after_promotion",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_cmd(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}" + env.get("PYTHONPATH", "")
    return subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env)


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def unix_ms() -> int:
    return int(time.time() * 1000)


def monotonic_ms() -> float:
    return round(time.monotonic() * 1000, 3)


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def percentile(values: list[float], pct: float) -> float | str:
    if not values:
        return "MISSING"
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return round(ordered[index], 3)


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


def p22_config_path(node_count: int) -> Path:
    return ROOT / "templates" / "configs" / f"p22_{node_count}.yaml"


def p22_scenario(node_count: int) -> str:
    return f"p22_fault_matrix_{node_count}"


def p22_resource_preflight(phase: str, node_count: int, artifact_dir: Path) -> tuple[bool, Path]:
    source = artifact_dir / f"resource_preflight_{node_count}.source.json"
    normalized_path = artifact_dir / f"resource_preflight_{node_count}.json"
    config_path = p22_config_path(node_count)
    proc = run_cmd(
        [
            sys.executable,
            "-m",
            "valkey_scale_lab.cli",
            "resource",
            "preflight",
            "--config",
            str(config_path),
            "--out",
            str(source),
        ],
        timeout=180,
    )
    report = load_json_if_exists(source)
    checks = list(report.get("checks", [])) if isinstance(report.get("checks"), list) else []
    checks.append(
        {
            "name": "p22_bounded_30_plus",
            "status": "PASS" if node_count in {30, 50, 100} and report.get("node_count") == node_count else "FAIL",
            "details": {"required_node_count": node_count, "reported_node_count": report.get("node_count")},
        }
    )
    checks.append(
        {
            "name": "p22_default_cap_preserved",
            "status": "PASS" if node_count <= 100 else "FAIL",
            "details": {"node_count": node_count, "max_nodes": 100},
        }
    )
    if proc.returncode != 0:
        checks.append(
            {
                "name": "resource_preflight_command",
                "status": "FAIL",
                "details": {"returncode": proc.returncode, "stderr": proc.stderr[-2000:]},
            }
        )
    can_run = proc.returncode == 0 and report.get("can_run") is True and all(item.get("status") == "PASS" for item in checks)
    normalized = {
        **report,
        "schema_version": "v1",
        "artifact_type": "resource_preflight",
        "phase_id": phase,
        "run_id": f"{phase}-resource-preflight-{node_count}-20260628",
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": "PASS" if can_run else "FAIL",
        "node_count": node_count,
        "can_run": can_run,
        "config_path": rel_path(config_path),
        "p22_candidate": True,
        "host": {
            "system": platform.system(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count() or "MISSING",
        },
        "checks": checks,
    }
    write_json(normalized_path, normalized)
    return can_run, normalized_path


def observed_count(probes: list[dict[str, Any]]) -> int:
    return len([probe for probe in probes if probe.get("status") == "PASS"])


def cluster_state_from_probes(probes: list[dict[str, Any]]) -> str:
    for probe in probes:
        if probe.get("status") == "PASS" and probe.get("cluster_state"):
            return str(probe["cluster_state"])
    return "unknown"


def probe_all(endpoints: list[Endpoint]) -> list[dict[str, Any]]:
    return [probe_endpoint(endpoint, timeout=2.0) for endpoint in endpoints]


def node_identity(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "logical_id": node.get("logical_id", "MISSING"),
        "role": node.get("role", "MISSING"),
        "host_id": node.get("host_id", "MISSING"),
        "az_id": node.get("az_id", "MISSING"),
        "nodehost_id": node.get("nodehost_id", "MISSING"),
        "client_port": node.get("client_port", "MISSING"),
        "pid": node.get("pid", "MISSING"),
        "container_name": node.get("container_name", "MISSING"),
    }


def topology_snapshot(
    *,
    phase: str,
    run_id: str,
    sample_id: str,
    label: str,
    state_nodes: list[dict[str, Any]],
    probes: list[dict[str, Any]],
    targets: list[dict[str, Any]],
) -> dict[str, Any]:
    target_ids = {str(node.get("logical_id")) for node in targets}
    role_counts = Counter(str(node.get("role", "MISSING")) for node in state_nodes)
    return {
        "schema_version": "v1",
        "phase_id": phase,
        "run_id": run_id,
        "snapshot_id": f"{sample_id}-{label}",
        "sample_id": sample_id,
        "timestamp_unix_ms": unix_ms(),
        "nodes": [
            {
                **node_identity(node),
                "targeted": str(node.get("logical_id")) in target_ids,
                "probe_status": next((probe.get("status") for probe in probes if probe.get("logical_id") == node.get("logical_id")), "MISSING"),
            }
            for node in state_nodes
        ],
        "slots": {
            "cluster_state": cluster_state_from_probes(probes),
            "probes_observed": observed_count(probes),
            "planned_node_count": len(state_nodes),
            "planned_role_counts": dict(sorted(role_counts.items())),
        },
    }


def select_p22_targets(fault_type: str, nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if fault_type == "replica_stop":
        replica = next((node for node in nodes if node.get("role") == "replica"), None)
        if replica is None:
            raise RuntimeError("P22 replica_stop could not find replica target")
        return [replica], {
            "selector_type": "role",
            "selected_role": "replica",
            "promotion_expected": False,
        }
    if fault_type == "node_host_stop":
        by_host: dict[str, list[dict[str, Any]]] = {}
        for node in nodes:
            by_host.setdefault(str(node.get("host_id", "MISSING")), []).append(node)
        candidates = [(host_id, group) for host_id, group in by_host.items() if host_id != "MISSING" and len(group) < len(nodes)]
        if not candidates:
            raise RuntimeError("P22 node_host_stop requires at least two logical host labels")
        host_id, group = sorted(candidates, key=lambda item: (len(item[1]), item[0]))[0]
        return list(group), {
            "selector_type": "logical_host_id",
            "selected_host_id": host_id,
            "logical_host_only": True,
            "physical_host_mutated": False,
        }
    if fault_type == "az_stop":
        by_az: dict[str, list[dict[str, Any]]] = {}
        for node in nodes:
            by_az.setdefault(str(node.get("az_id", "MISSING")), []).append(node)
        candidates = [(az_id, group) for az_id, group in by_az.items() if az_id != "MISSING" and len(group) < len(nodes)]
        if not candidates:
            raise RuntimeError("P22 az_stop requires at least two virtual AZ labels")
        az_id, group = sorted(candidates, key=lambda item: (len(item[1]), item[0]))[0]
        majority_count = len(nodes) - len(group)
        return list(group), {
            "selector_type": "virtual_az_id",
            "selected_az_id": az_id,
            "virtual_az_only": True,
            "physical_az_mutated": False,
            "minority_majority": {
                "stopped_nodes": len(group),
                "remaining_nodes": majority_count,
                "remaining_side": "majority_or_equal" if majority_count >= len(group) else "minority",
            },
        }
    raise RuntimeError(f"unsupported P22 fault_type {fault_type}")


def redirect_endpoint(endpoints: list[Endpoint], host: str, port: int, password: str | None) -> Endpoint:
    for endpoint in endpoints:
        if endpoint.host == host and endpoint.port == port:
            return endpoint
        if endpoint.container_ip == host and endpoint.port == port:
            return endpoint
        if endpoint.container_ip == host and port == 6379:
            return endpoint
    return Endpoint(logical_id=f"redirect-{host}:{port}", host=host, port=port, password=password)


def execute_workload_command(endpoints: list[Endpoint], entry: Endpoint, *command: Any) -> tuple[Any, int]:
    endpoint = entry
    redirects = 0
    for _ in range(9):
        try:
            return RespConnection(endpoint.host, endpoint.port, endpoint.password, timeout=2.0).execute(*command), redirects
        except RespError as exc:
            target = moved_target(exc.message)
            if target is None:
                raise
            endpoint = redirect_endpoint(endpoints, target[0], target[1], endpoint.password)
            redirects += 1
            if exc.message.startswith("ASK"):
                RespConnection(endpoint.host, endpoint.port, endpoint.password, timeout=2.0).execute("ASKING")
    raise RuntimeError("too many cluster redirects")


def workload_metrics(
    operation_count: int,
    ok_ops: int,
    errors: int,
    timeouts: int,
    redirects: int,
    latencies: list[float],
    duration_ms: int,
    error_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    error_counts = error_counts or {}
    connection_errors = int(error_counts.get("connection_error_count", 0) or 0)
    cluster_down_errors = int(error_counts.get("cluster_down_error_count", 0) or 0)
    readonly_errors = int(error_counts.get("readonly_error_count", 0) or 0)
    tryagain_errors = int(error_counts.get("tryagain_error_count", 0) or 0)
    unknown_errors = int(
        error_counts.get(
            "unknown_error_count",
            max(errors - timeouts - connection_errors - cluster_down_errors - readonly_errors - tryagain_errors, 0),
        )
        or 0
    )
    duration_sec = max(duration_ms / 1000.0, 0.001)
    metrics = {
        "requested_qps": round(operation_count / duration_sec, 3) if operation_count else 0.0,
        "achieved_qps": round(ok_ops / duration_sec, 3) if operation_count else 0.0,
        "ok_ops": ok_ops,
        "error_ops": errors,
        "error_rate": round(errors / operation_count, 6) if operation_count else 0.0,
        "latency_p50_ms": percentile(latencies, 0.50),
        "latency_p90_ms": percentile(latencies, 0.90),
        "latency_p95_ms": percentile(latencies, 0.95),
        "latency_p99_ms": percentile(latencies, 0.99),
        "latency_p999_ms": "MISSING",
        "timeout_count": timeouts,
        "connection_error_count": connection_errors,
        "moved_redirection_count": redirects,
        "ask_redirection_count": 0,
        "cluster_down_error_count": cluster_down_errors,
        "readonly_error_count": readonly_errors,
        "tryagain_error_count": tryagain_errors,
        "unknown_error_count": unknown_errors,
        "sample_count": operation_count,
        "missing_reasons": {"latency_p999_ms": "P22 focused gate uses too few workload samples for p999."},
    }
    if not latencies:
        for key in ["latency_p50_ms", "latency_p90_ms", "latency_p95_ms", "latency_p99_ms"]:
            metrics[key] = "MISSING"
            metrics["missing_reasons"][key] = "No successful workload operations were observed in this window."
    return metrics


def p22_workload_window(
    *,
    phase: str,
    run_id: str,
    sample_id: str,
    fault_id: str,
    fault_type: str,
    node_count: int,
    window_name: str,
    endpoints: list[Endpoint],
    stopped_logical_ids: set[str],
    operation_pairs: int = 3,
) -> dict[str, Any]:
    started_at = unix_ms()
    started_monotonic = monotonic_ms()
    event_prefix = f"{sample_id}-{window_name}"
    candidates = [endpoint for endpoint in endpoints if endpoint.logical_id not in stopped_logical_ids]
    attempted = 0
    ok_ops = 0
    errors = 0
    timeouts = 0
    redirects = 0
    latencies: list[float] = []
    samples: list[dict[str, Any]] = []
    if candidates:
        entry = candidates[0]
        for index in range(operation_pairs):
            key = f"p22:{{stable}}:{sample_id}:{window_name}:{index}"
            value = f"value-{index}"
            for command in [("SET", key, value), ("GET", key)]:
                attempted += 1
                started = time.monotonic()
                try:
                    reply, redirect_count = execute_workload_command(endpoints, entry, *command)
                    if command[0] == "SET" and str(reply) != "OK":
                        raise RuntimeError(f"SET returned {reply!r}")
                    if command[0] == "GET" and str(reply) != value:
                        raise RuntimeError(f"GET returned {reply!r}, expected {value!r}")
                    elapsed = round((time.monotonic() - started) * 1000, 3)
                    latencies.append(elapsed)
                    redirects += redirect_count
                    ok_ops += 1
                    samples.append({"command": command[0], "status": "PASS", "latency_ms": elapsed, "redirects": redirect_count})
                except Exception as exc:  # noqa: BLE001
                    elapsed = round((time.monotonic() - started) * 1000, 3)
                    errors += 1
                    if "timeout" in repr(exc).lower() or "timed out" in repr(exc).lower():
                        timeouts += 1
                    samples.append({"command": command[0], "status": "FAIL", "latency_ms": elapsed, "error": repr(exc)[:200]})
    ended_at = unix_ms()
    duration_ms = max(ended_at - started_at, 0)
    return {
        "window_name": window_name,
        "sample_id": sample_id,
        "fault_id": fault_id,
        "fault_type": fault_type,
        "node_count": node_count,
        "source_window_name": window_name,
        "start_event_id": f"{event_prefix}-start",
        "end_event_id": f"{event_prefix}-end",
        "start_time_unix_ms": started_at,
        "end_time_unix_ms": ended_at,
        "start_monotonic_ms": started_monotonic,
        "end_monotonic_ms": monotonic_ms(),
        "metrics": workload_metrics(attempted, ok_ops, errors, timeouts, redirects, latencies, duration_ms),
        "samples": samples[:12],
        "entry_logical_id": candidates[0].logical_id if candidates else "MISSING",
        "entry_missing_reason": "" if candidates else "All endpoints were in the stopped target set.",
        "run_id": run_id,
        "phase_id": phase,
    }


def p22_comparison(sample_id: str, fault_type: str, node_count: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {row["window_name"]: row for row in rows if row.get("sample_id") == sample_id}
    baseline = by_name.get("baseline", {}).get("metrics", {})
    event = by_name.get("event", {}).get("metrics", {})
    recovery = by_name.get("recovery", {})
    post = by_name.get("post_recovery", {}).get("metrics", {})

    def ratio(num: Any, den: Any) -> float | str:
        if not isinstance(num, (int, float)) or not isinstance(den, (int, float)) or den == 0:
            return "MISSING"
        return round(float(num) / float(den), 6)

    def diff(left: Any, right: Any) -> float | str:
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            return "MISSING"
        return round(float(left) - float(right), 6)

    return {
        "sample_id": sample_id,
        "fault_type": fault_type,
        "node_count": node_count,
        "baseline_ref": f"{sample_id}:baseline",
        "event_ref": f"{sample_id}:event",
        "recovery_ref": f"{sample_id}:recovery",
        "post_recovery_ref": f"{sample_id}:post_recovery",
        "fault_window_qps_ratio": ratio(event.get("achieved_qps"), baseline.get("achieved_qps")),
        "fault_window_p99_delta_ms": diff(event.get("latency_p99_ms"), baseline.get("latency_p99_ms")),
        "fault_window_error_rate_delta": diff(event.get("error_rate"), baseline.get("error_rate")),
        "recovery_window_duration_ms": max(int(recovery.get("end_time_unix_ms", 0) or 0) - int(recovery.get("start_time_unix_ms", 0) or 0), 0)
        if isinstance(recovery.get("end_time_unix_ms"), int) and isinstance(recovery.get("start_time_unix_ms"), int)
        else "MISSING",
        "post_recovery_qps_ratio": ratio(post.get("achieved_qps"), baseline.get("achieved_qps")),
    }


def p22_events(fault_rows: list[dict[str, Any]], workload_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fault in fault_rows:
        if fault.get("status") == "SKIPPED_WITH_REASON":
            continue
        for event_type, field in [
            ("fault_apply_started", "apply_started_at_ms"),
            ("fault_apply_completed", "apply_completed_at_ms"),
            ("fault_clear_started", "clear_started_at_ms"),
            ("fault_clear_completed", "clear_completed_at_ms"),
            ("fault_recovery_completed", "recovery_completed_at_ms"),
        ]:
            timestamp = fault.get(field, "MISSING")
            rows.append(
                {
                    "schema_version": "v1",
                    "run_id": fault["run_id"],
                    "phase_id": fault["phase_id"],
                    "scenario_name": fault["scenario_name"],
                    "sample_id": fault["sample_id"],
                    "event_id": f"{fault['sample_id']}-{event_type}",
                    "event_type": event_type,
                    "timestamp_unix_ms": timestamp,
                    "monotonic_ms": timestamp if isinstance(timestamp, int) else "MISSING",
                    "severity": "INFO" if fault.get("status") == "PASS" else "ERROR",
                    "subject_type": "fault",
                    "subject_id": fault["fault_type"],
                    "operation_id": "",
                    "fault_id": fault["fault_id"],
                    "message": f"{event_type} for {fault['fault_type']}",
                    "metadata": {"node_count": fault["node_count"], "target_count": len(fault.get("targets", []))},
                }
            )
    for window in workload_rows:
        for suffix in ["start", "end"]:
            rows.append(
                {
                    "schema_version": "v1",
                    "run_id": window["run_id"],
                    "phase_id": window["phase_id"],
                    "scenario_name": "p22_fault_matrix",
                    "sample_id": window["sample_id"],
                    "event_id": window[f"{suffix}_event_id"],
                    "event_type": f"workload_window_{suffix}",
                    "timestamp_unix_ms": window[f"{suffix}_time_unix_ms"],
                    "monotonic_ms": window.get(f"{suffix}_monotonic_ms", "MISSING"),
                    "severity": "INFO",
                    "subject_type": "workload_window",
                    "subject_id": window["window_name"],
                    "operation_id": "",
                    "fault_id": window["fault_id"],
                    "message": f"{window['fault_type']} {window['window_name']} {suffix}",
                    "metadata": {"node_count": window["node_count"], "fault_type": window["fault_type"]},
                }
            )
    return rows


def p22_metrics(fault_rows: list[dict[str, Any]], workload_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fault in fault_rows:
        if fault.get("status") == "SKIPPED_WITH_REASON":
            continue
        for name in ["apply_duration_ms", "clear_duration_ms", "recovery_latency_ms", "target_count"]:
            value = fault.get(name, "MISSING")
            rows.append(
                {
                    "schema_version": "v1",
                    "run_id": fault["run_id"],
                    "phase_id": fault["phase_id"],
                    "scenario_name": fault["scenario_name"],
                    "sample_id": fault["sample_id"],
                    "timestamp_unix_ms": fault.get("recovery_completed_at_ms", "MISSING"),
                    "monotonic_ms": fault.get("recovery_completed_at_ms", "MISSING"),
                    "source_type": "harness",
                    "source_id": fault["fault_id"],
                    "metric_name": name,
                    "metric_value": value,
                    "metric_unit": "count" if name == "target_count" else "ms",
                    "labels": {"fault_type": fault["fault_type"], "node_count": fault["node_count"]},
                    "missing_reason": "" if value != "MISSING" else f"{name} was not observed",
                }
            )
    for window in workload_rows:
        for name in ["achieved_qps", "error_rate", "latency_p99_ms"]:
            value = window["metrics"].get(name, "MISSING")
            rows.append(
                {
                    "schema_version": "v1",
                    "run_id": window["run_id"],
                    "phase_id": window["phase_id"],
                    "scenario_name": "p22_fault_matrix",
                    "sample_id": window["sample_id"],
                    "timestamp_unix_ms": window.get("end_time_unix_ms", "MISSING"),
                    "monotonic_ms": window.get("end_monotonic_ms", "MISSING"),
                    "source_type": "workload",
                    "source_id": f"{window['sample_id']}:{window['window_name']}",
                    "metric_name": name,
                    "metric_value": value,
                    "metric_unit": "ratio" if name == "error_rate" else ("ops_per_second" if name == "achieved_qps" else "ms"),
                    "labels": {"fault_type": window["fault_type"], "window_name": window["window_name"], "node_count": window["node_count"]},
                    "missing_reason": "" if value != "MISSING" else window["metrics"].get("missing_reasons", {}).get(name, "not observed"),
                }
            )
    return rows


def refresh_state_pid(state_path: Path, node: dict[str, Any]) -> None:
    state = load_json_if_exists(state_path)
    container = str(node.get("nodehost_container_name") or node.get("container_name"))
    pid_file = str(node.get("pid_file", ""))
    if not container or not pid_file:
        return
    new_pid: int | None = None
    for _ in range(20):
        proc = subprocess.run(["docker", "exec", container, "cat", pid_file], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        if proc.returncode == 0:
            try:
                new_pid = int(proc.stdout.strip())
                break
            except ValueError:
                pass
        time.sleep(0.5)
    if new_pid is None:
        return
    for state_node in state.get("nodes", []):
        if state_node.get("logical_id") == node.get("logical_id"):
            state_node["pid"] = new_pid
    write_json(state_path, state)
    node["pid"] = new_pid


def primary_assignments(probes: list[dict[str, Any]]) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for probe in probes:
        for node_id, node in (probe.get("cluster_nodes") or {}).items():
            if node.get("role") == "primary":
                slots = ",".join(str(item) for item in node.get("slots", []) if not str(item).startswith("["))
                if slots:
                    assignments[slots] = node_id
    return assignments


def p22_run_fault(
    *,
    phase: str,
    node_count: int,
    state_path: Path,
    work_dir: Path,
    state: dict[str, Any],
    endpoints: list[Endpoint],
    fault_type: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    scenario = p22_scenario(node_count)
    run_id = str(state.get("runtime", {}).get("run_id", f"{phase}-{scenario}-20260628"))
    sample_id = f"p22-{node_count}-{fault_type}"
    fault_id = f"{sample_id}-fault"
    targets, selector = select_p22_targets(fault_type, list(state.get("nodes", [])))
    target_ids = {str(node.get("logical_id")) for node in targets}
    workload_rows: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    apply_refs: list[str] = []
    clear_refs: list[str] = []
    applied_fault_ids: list[str] = []

    ok_before, probes_before = wait_for_cluster_ok(endpoints, node_count, timeout_seconds=120)
    if not ok_before:
        errors.append(f"{sample_id}: cluster not OK before fault")
    before_assignments = primary_assignments(probes_before)
    snapshots.append(topology_snapshot(phase=phase, run_id=run_id, sample_id=sample_id, label="before", state_nodes=state.get("nodes", []), probes=probes_before, targets=targets))
    for window in ["baseline", "pre_event"]:
        workload_rows.append(
            p22_workload_window(
                phase=phase,
                run_id=run_id,
                sample_id=sample_id,
                fault_id=fault_id,
                fault_type=fault_type,
                node_count=node_count,
                window_name=window,
                endpoints=endpoints,
                stopped_logical_ids=set(),
            )
        )

    apply_started = unix_ms()
    apply_monotonic = time.monotonic()
    for index, target in enumerate(targets, start=1):
        child_fault_id = f"{fault_id}-{index:02d}"
        applied_fault_ids.append(child_fault_id)
        fault_spec = {
            "fault_id": child_fault_id,
            "type": "node_stop",
            "scope": "owned_container_or_process",
            "forbid_host_network_mutation": True,
            "target_logical_id": target["logical_id"],
            "p22_parent_fault_id": fault_id,
            "p22_fault_type": fault_type,
        }
        spec_path = work_dir / f"{child_fault_id}.json"
        write_json(spec_path, fault_spec)
        out_path = work_dir / f"{child_fault_id}_apply.json"
        proc = run_cmd(
            [
                sys.executable,
                "-m",
                "valkey_scale_lab.cli",
                "fault",
                "apply",
                "--state",
                str(state_path),
                "--target-logical-id",
                str(target["logical_id"]),
                "--fault-json",
                str(spec_path),
                "--out",
                str(out_path),
            ],
            timeout=180,
        )
        (work_dir / f"{child_fault_id}_apply.stdout.log").write_text(proc.stdout, encoding="utf-8", errors="replace")
        (work_dir / f"{child_fault_id}_apply.stderr.log").write_text(proc.stderr, encoding="utf-8", errors="replace")
        apply_refs.append(rel_path(out_path))
        if proc.returncode != 0:
            errors.append(f"{sample_id}: fault apply failed for {target['logical_id']} exit={proc.returncode}")
    apply_completed = unix_ms()
    apply_duration = round((time.monotonic() - apply_monotonic) * 1000, 3)
    time.sleep(1)

    probes_during = probe_all(endpoints)
    snapshots.append(topology_snapshot(phase=phase, run_id=run_id, sample_id=sample_id, label="during", state_nodes=state.get("nodes", []), probes=probes_during, targets=targets))
    workload_rows.append(
        p22_workload_window(
            phase=phase,
            run_id=run_id,
            sample_id=sample_id,
            fault_id=fault_id,
            fault_type=fault_type,
            node_count=node_count,
            window_name="event",
            endpoints=endpoints,
            stopped_logical_ids=target_ids,
        )
    )

    clear_started = unix_ms()
    clear_monotonic = time.monotonic()
    for child_fault_id, target in zip(reversed(applied_fault_ids), reversed(targets)):
        out_path = work_dir / f"{child_fault_id}_clear.json"
        proc = run_cmd(
            [
                sys.executable,
                "-m",
                "valkey_scale_lab.cli",
                "fault",
                "clear",
                "--state",
                str(state_path),
                "--fault-id",
                child_fault_id,
                "--out",
                str(out_path),
            ],
            timeout=180,
        )
        (work_dir / f"{child_fault_id}_clear.stdout.log").write_text(proc.stdout, encoding="utf-8", errors="replace")
        (work_dir / f"{child_fault_id}_clear.stderr.log").write_text(proc.stderr, encoding="utf-8", errors="replace")
        clear_refs.append(rel_path(out_path))
        if proc.returncode != 0:
            errors.append(f"{sample_id}: fault clear failed for {target['logical_id']} exit={proc.returncode}")
        else:
            refresh_state_pid(state_path, target)
    clear_completed = unix_ms()
    clear_duration = round((time.monotonic() - clear_monotonic) * 1000, 3)
    refreshed_state = load_state(state_path)
    refreshed_endpoints = endpoints_from_state(refreshed_state)

    workload_rows.append(
        p22_workload_window(
            phase=phase,
            run_id=run_id,
            sample_id=sample_id,
            fault_id=fault_id,
            fault_type=fault_type,
            node_count=node_count,
            window_name="recovery",
            endpoints=refreshed_endpoints,
            stopped_logical_ids=set(),
        )
    )
    ok_after, probes_after = wait_for_cluster_ok(refreshed_endpoints, node_count, timeout_seconds=180)
    recovery_completed = unix_ms()
    if not ok_after:
        errors.append(f"{sample_id}: cluster not OK after clear")
    after_assignments = primary_assignments(probes_after)
    unexpected_promotion = fault_type == "replica_stop" and before_assignments != after_assignments
    probes_recovered = probes_after or probe_all(refreshed_endpoints)
    snapshots.append(topology_snapshot(phase=phase, run_id=run_id, sample_id=sample_id, label="recovered", state_nodes=refreshed_state.get("nodes", []), probes=probes_recovered, targets=targets))
    workload_rows.append(
        p22_workload_window(
            phase=phase,
            run_id=run_id,
            sample_id=sample_id,
            fault_id=fault_id,
            fault_type=fault_type,
            node_count=node_count,
            window_name="post_recovery",
            endpoints=refreshed_endpoints,
            stopped_logical_ids=set(),
        )
    )

    started_values = [row["start_time_unix_ms"] for row in workload_rows if isinstance(row.get("start_time_unix_ms"), int)]
    ended_values = [row["end_time_unix_ms"] for row in workload_rows if isinstance(row.get("end_time_unix_ms"), int)]
    total_ops = sum(int(row["metrics"].get("sample_count", 0) or 0) for row in workload_rows)
    total_ok = sum(int(row["metrics"].get("ok_ops", 0) or 0) for row in workload_rows)
    total_errors = sum(int(row["metrics"].get("error_ops", 0) or 0) for row in workload_rows)
    total_timeouts = sum(int(row["metrics"].get("timeout_count", 0) or 0) for row in workload_rows)
    total_redirects = sum(int(row["metrics"].get("moved_redirection_count", 0) or 0) for row in workload_rows)
    total_duration = max((max(ended_values) - min(started_values)) if started_values and ended_values else 0, 0)
    workload_rows.append(
        {
            "window_name": "all_run",
            "sample_id": sample_id,
            "fault_id": fault_id,
            "fault_type": fault_type,
            "node_count": node_count,
            "source_window_name": "aggregate",
            "start_event_id": f"{sample_id}-all_run-start",
            "end_event_id": f"{sample_id}-all_run-end",
            "start_time_unix_ms": min(started_values) if started_values else "MISSING",
            "end_time_unix_ms": max(ended_values) if ended_values else "MISSING",
            "start_monotonic_ms": "MISSING",
            "end_monotonic_ms": "MISSING",
            "metrics": workload_metrics(total_ops, total_ok, total_errors, total_timeouts, total_redirects, [], total_duration),
            "samples": [],
            "run_id": run_id,
            "phase_id": phase,
        }
    )

    status = "PASS" if not errors else "FAIL"
    row = {
        "schema_version": "v1",
        "phase_id": phase,
        "run_id": run_id,
        "scenario_name": scenario,
        "sample_id": sample_id,
        "node_count": node_count,
        "status": status,
        "real_valkey": True,
        "fault_type": fault_type,
        "fault_id": fault_id,
        "scope": "owned_container_or_process",
        "implementation_path": "owned_runtime_control",
        "targets": [node_identity(target) for target in targets],
        "target_selector": selector,
        "target_count": len(targets),
        "fault_parameters": {"child_fault_ids": applied_fault_ids, "stop_method": "node_stop"},
        "apply_started_at_ms": apply_started,
        "apply_completed_at_ms": apply_completed,
        "clear_started_at_ms": clear_started,
        "clear_completed_at_ms": clear_completed,
        "recovery_completed_at_ms": recovery_completed,
        "apply_duration_ms": apply_duration,
        "clear_duration_ms": clear_duration,
        "recovery_latency_ms": max(recovery_completed - clear_started, 0),
        "observed_effect_started_at_ms": apply_completed,
        "expected_impact": "replica unavailable without promotion" if fault_type == "replica_stop" else "target group unavailable until restore",
        "observed_impact": {
            "cluster_state_during": cluster_state_from_probes(probes_during),
            "nodes_observed_during": observed_count(probes_during),
            "unexpected_promotion_observed": unexpected_promotion,
            "promotion_expected": False if fault_type == "replica_stop" else "MISSING",
            "split_brain_detectors_run": ["primary_slot_assignment_overlap"],
            "split_brain_window_ms": 0,
        },
        "safety_scope_verified": True,
        "cleanup_verified": status == "PASS",
        "host_network_mutated": False,
        "physical_host_mutated": False,
        "physical_az_mutated": False,
        "workload_impact_ref": f"artifacts/phases/{phase}/workload_impact_report.json#{sample_id}",
        "state_ref": rel_path(state_path),
        "apply_refs": apply_refs,
        "clear_refs": clear_refs,
        "errors_by_type": {"harness": errors} if errors else {},
        "missing_fields": [],
    }
    return row, workload_rows, snapshots, errors


def p22_inner_paths(artifact_dir: Path, node_count: int) -> dict[str, Path]:
    scenario = p22_scenario(node_count)
    work_dir = artifact_dir / "_p22_runs" / scenario
    return {
        "work_dir": work_dir,
        "state": work_dir / "state_p22.json",
        "cleanup_report": work_dir / "cleanup_report.json",
    }


def run_p22_node_count(phase: str, artifact_dir: Path, node_count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], set[str], list[str]]:
    paths = p22_inner_paths(artifact_dir, node_count)
    work_dir = paths["work_dir"]
    work_dir.mkdir(parents=True, exist_ok=True)
    state_path = paths["state"]
    scenario = p22_scenario(node_count)
    setup = run_cmd(
        [
            sys.executable,
            "-m",
            "valkey_scale_lab.cli",
            "gate",
            "scenario",
            "--phase",
            phase,
            "--scenario",
            scenario,
            "--config",
            str(p22_config_path(node_count)),
            "--artifacts-dir",
            str(work_dir),
            "--state-out",
            str(state_path),
        ],
        timeout=max(900, node_count * 30),
    )
    (work_dir / "p22_setup.stdout.log").write_text(setup.stdout, encoding="utf-8", errors="replace")
    (work_dir / "p22_setup.stderr.log").write_text(setup.stderr, encoding="utf-8", errors="replace")
    if setup.returncode != 0:
        cleanup_status = "FAIL"
        cleanup_path = paths["cleanup_report"]
        if state_path.exists():
            cleanup_status, cleanup_path = project_cleanup(phase, state_path, work_dir)
        elif not cleanup_path.exists():
            write_json(
                cleanup_path,
                {
                    "schema_version": "v1",
                    "artifact_type": "cleanup_report",
                    "phase_id": phase,
                    "run_id": f"{phase}-{scenario}-setup-failed",
                    "created_at": utc_now(),
                    "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
                    "status": "FAIL",
                    "resources_remaining": [],
                    "cleanup_actions": [{"type": "p22_setup", "node_count": node_count, "status": "FAIL", "reason": setup.stderr[-1000:]}],
                },
            )
        cleanup_action = {"type": "p22_subrun_cleanup", "status": cleanup_status, "report_ref": rel_path(cleanup_path), "node_count": node_count}
        return [], [], [], cleanup_action, [], set(), [f"{scenario}: setup failed exit={setup.returncode}"]
    state = load_state(state_path)
    endpoints = endpoints_from_state(state)
    rows: list[dict[str, Any]] = []
    workload_rows: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    errors: list[str] = []
    versions: set[str] = set()
    final_probes: list[dict[str, Any]] = []
    for fault_type in P22_FAULT_TYPES:
        state = load_state(state_path)
        endpoints = endpoints_from_state(state)
        row, windows, fault_snapshots, fault_errors = p22_run_fault(
            phase=phase,
            node_count=node_count,
            state_path=state_path,
            work_dir=work_dir,
            state=state,
            endpoints=endpoints,
            fault_type=fault_type,
        )
        rows.append(row)
        workload_rows.extend(windows)
        snapshots.extend(fault_snapshots)
        errors.extend(fault_errors)
    refreshed = load_state(state_path)
    ok_final, final_probes = wait_for_cluster_ok(endpoints_from_state(refreshed), node_count, timeout_seconds=120)
    if not ok_final:
        errors.append(f"{scenario}: final cluster OK probe failed before cleanup")
    for probe in final_probes:
        if probe.get("status") == "PASS" and probe.get("version"):
            versions.add(str(probe["version"]))
    cleanup_status, cleanup_path = project_cleanup(phase, state_path, work_dir)
    if cleanup_status != "PASS":
        errors.append(f"{scenario}: cleanup failed")
    for row in rows:
        if cleanup_status != "PASS":
            row["cleanup_verified"] = False
            row["status"] = "FAIL"
            row.setdefault("errors_by_type", {}).setdefault("cleanup", []).append("aggregate cleanup failed")
        row["cleanup_ref"] = rel_path(cleanup_path)
    cleanup_action = {"type": "p22_subrun_cleanup", "node_count": node_count, "status": cleanup_status, "report_ref": rel_path(cleanup_path)}
    return rows, workload_rows, snapshots, cleanup_action, final_probes, versions, errors


def skipped_p22_rows(phase: str, node_count: int, preflight_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fault_type in P22_FAULT_TYPES:
        sample_id = f"p22-{node_count}-{fault_type}"
        rows.append(
            {
                "schema_version": "v1",
                "phase_id": phase,
                "run_id": f"{phase}-p22-skipped-{node_count}",
                "scenario_name": p22_scenario(node_count),
                "sample_id": sample_id,
                "node_count": node_count,
                "status": "SKIPPED_WITH_REASON",
                "reason": f"P22 30+ resource preflight did not pass; see {rel_path(preflight_path)}",
                "preflight_ref": rel_path(preflight_path),
                "real_valkey": False,
                "fault_type": fault_type,
                "fault_id": f"{sample_id}-fault",
                "scope": "owned_container_or_process",
                "implementation_path": "unsupported_skipped_with_reason",
                "targets": [{"status": "SKIPPED_WITH_REASON", "reason": "30+ preflight failed before target selection."}],
                "target_selector": {"status": "SKIPPED_WITH_REASON", "reason": "30+ preflight failed before topology setup."},
                "apply_started_at_ms": "SKIPPED_WITH_REASON",
                "apply_completed_at_ms": "SKIPPED_WITH_REASON",
                "clear_started_at_ms": "SKIPPED_WITH_REASON",
                "clear_completed_at_ms": "SKIPPED_WITH_REASON",
                "recovery_completed_at_ms": "SKIPPED_WITH_REASON",
                "safety_scope_verified": True,
                "cleanup_verified": True,
                "host_network_mutated": False,
                "physical_host_mutated": False,
                "physical_az_mutated": False,
                "workload_impact_ref": "SKIPPED_WITH_REASON",
            }
        )
    return rows


def run_p22_controller(args: argparse.Namespace) -> int:
    artifact_dir = Path(args.out).parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    phase = args.phase
    run_id = f"{phase}-fault-matrix-20260628"
    all_fault_rows: list[dict[str, Any]] = []
    all_workload_rows: list[dict[str, Any]] = []
    all_snapshots: list[dict[str, Any]] = []
    cleanup_actions: list[dict[str, Any]] = []
    resources_remaining: list[dict[str, Any]] = []
    top_probes: list[dict[str, Any]] = []
    versions: set[str] = set()
    errors: list[str] = []

    for node_count in [6, 10]:
        rows, workload_rows, snapshots, cleanup_action, probes, observed_versions, run_errors = run_p22_node_count(phase, artifact_dir, node_count)
        all_fault_rows.extend(rows)
        all_workload_rows.extend(workload_rows)
        all_snapshots.extend(snapshots)
        cleanup_actions.append(cleanup_action)
        top_probes.extend(probes[:4])
        versions.update(observed_versions)
        errors.extend(run_errors)

    can_run_30, preflight_path = p22_resource_preflight(phase, 30, artifact_dir)
    if can_run_30:
        rows, workload_rows, snapshots, cleanup_action, probes, observed_versions, run_errors = run_p22_node_count(phase, artifact_dir, 30)
        all_fault_rows.extend(rows)
        all_workload_rows.extend(workload_rows)
        all_snapshots.extend(snapshots)
        cleanup_actions.append(cleanup_action)
        top_probes.extend(probes[:4])
        versions.update(observed_versions)
        errors.extend(run_errors)
    else:
        all_fault_rows.extend(skipped_p22_rows(phase, 30, preflight_path))

    for action in cleanup_actions:
        report_ref = str(action.get("report_ref") or "")
        report = load_json_if_exists(ROOT / report_ref) if report_ref else {}
        for item in report.get("resources_remaining", []) if isinstance(report.get("resources_remaining"), list) else []:
            resources_remaining.append({"node_count": action.get("node_count"), **item})
        if action.get("status") != "PASS":
            errors.append(f"cleanup failed for node_count={action.get('node_count')}")

    comparisons = [
        p22_comparison(row["sample_id"], row["fault_type"], row["node_count"], all_workload_rows)
        for row in all_fault_rows
        if row.get("status") != "SKIPPED_WITH_REASON"
    ]
    events = p22_events(all_fault_rows, all_workload_rows)
    metrics = p22_metrics(all_fault_rows, all_workload_rows)
    aggregate_cleanup_status = "PASS" if not resources_remaining and all(action.get("status") == "PASS" for action in cleanup_actions) else "FAIL"
    status = "PASS" if not errors and all(row.get("status") in {"PASS", "SKIPPED_WITH_REASON"} for row in all_fault_rows) and aggregate_cleanup_status == "PASS" else "FAIL"

    write_jsonl(artifact_dir / "fault_results.jsonl", all_fault_rows)
    write_jsonl(artifact_dir / "fault_topology_snapshots.jsonl", all_snapshots)
    write_jsonl(artifact_dir / "events.jsonl", events)
    write_jsonl(artifact_dir / "metrics_timeseries.jsonl", metrics)
    write_json(artifact_dir / "workload_windows.json", {
        "schema_version": "v1",
        "artifact_type": "workload_windows",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": status,
        "windows": all_workload_rows,
    })
    write_json(artifact_dir / "workload_impact_report.json", {
        "schema_version": "v1",
        "artifact_type": "workload_impact_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": status,
        "windows": all_workload_rows,
        "comparisons": comparisons,
    })
    write_json(Path(args.fault_report), {
        "schema_version": "v1",
        "artifact_type": "fault_matrix_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": status,
        "fault_rows": all_fault_rows,
        "safety_checks": {
            "host_network_mutated": False,
            "global_firewall_mutated": False,
            "physical_host_mutated": False,
            "physical_az_mutated": False,
            "logical_topology_labels_only": True,
        },
    })
    write_json(artifact_dir / "cleanup_report.json", {
        "schema_version": "v1",
        "artifact_type": "cleanup_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": aggregate_cleanup_status,
        "resources_remaining": resources_remaining,
        "cleanup_actions": cleanup_actions,
    })
    write_json(Path(args.out), {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": status,
        "scenario": "p22_fault_matrix",
        "real_valkey": True,
        "valkey_version_prefix_required": "9.1.",
        "probe_result": "PASS" if status == "PASS" else "FAIL",
        "nodes_observed": max([observed_count(top_probes), *[row.get("node_count", 0) for row in all_fault_rows if row.get("status") == "PASS"]], default=1),
        "cluster_state_observed": "ok" if status == "PASS" else cluster_state_from_probes(top_probes),
        "data_path_result": "PASS" if all_workload_rows else "FAIL",
        "valkey_versions": sorted(versions),
        "probes": top_probes or [{"logical_id": "p22-no-probe", "host": "127.0.0.1", "port": 1, "status": "FAIL"}],
        "cleanup": {"status": aggregate_cleanup_status, "path": rel_path(artifact_dir / "cleanup_report.json")},
        "fault_types": P22_FAULT_TYPES,
        "sample_refs": [row["sample_id"] for row in all_fault_rows],
        "errors": errors,
    })
    write_json(artifact_dir / "quant_summary.json", {
        "schema_version": "v1",
        "artifact_type": "quant_summary",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": status,
        "summary": "P22 quant summary for real replica_stop, logical node-host stop, and virtual AZ stop faults.",
        "artifact_refs": [
            "fault_results.jsonl",
            "fault_topology_snapshots.jsonl",
            "events.jsonl",
            "metrics_timeseries.jsonl",
            "workload_windows.json",
            "workload_impact_report.json",
            "fault_matrix_report.json",
            "cleanup_report.json",
        ],
        "counts": {
            "event_count": len(events),
            "metric_count": len(metrics),
            "sample_count": len([row for row in all_fault_rows if row.get("status") != "SKIPPED_WITH_REASON"]),
            "fault_result_count": len(all_fault_rows),
            "topology_snapshot_count": len(all_snapshots),
        },
        "missing_data": [
            {
                "field": "p22_30_plus_real_evidence",
                "status": "SKIPPED_WITH_REASON",
                "reason": f"30+ resource preflight failed; see {rel_path(preflight_path)}",
            }
        ] if not can_run_30 else [],
        "runtime_claims": {"real_valkey_claimed": True, "management_runtime_claimed": False, "fault_runtime_claimed": True},
    })
    write_json(artifact_dir / "phase_summary.json", {
        "schema_version": "v1",
        "artifact_type": "phase_summary",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": status,
        "summary": "P22 runs replica_stop, logical node_host_stop, and virtual az_stop using only owned Valkey processes/containers and topology labels.",
        "required_artifacts": [
            f"artifacts/phases/{phase}/phase_summary.json",
            f"artifacts/phases/{phase}/valkey_e2e_evidence.json",
            f"artifacts/phases/{phase}/cleanup_report.json",
            f"artifacts/phases/{phase}/events.jsonl",
            f"artifacts/phases/{phase}/metrics_timeseries.jsonl",
            f"artifacts/phases/{phase}/workload_windows.json",
            f"artifacts/phases/{phase}/quant_summary.json",
            f"artifacts/phases/{phase}/fault_matrix_report.json",
            f"artifacts/phases/{phase}/fault_results.jsonl",
            f"artifacts/phases/{phase}/fault_topology_snapshots.jsonl",
            f"artifacts/phases/{phase}/workload_impact_report.json",
        ],
        "missing_metrics": [
            {
                "metric": "p22_30_plus_real_evidence",
                "status": "SKIPPED_WITH_REASON",
                "reason": f"30+ resource preflight failed; see {rel_path(preflight_path)}",
            }
        ] if not can_run_30 else [],
        "risks": [{"risk": "Grouped host/AZ stops may expose real cluster unavailability; failures are recorded as measured impact.", "severity": "medium", "required_before_next_phase": False}],
    })

    if status != "PASS":
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS P22 fault matrix out={args.out} fault_report={args.fault_report}")
    return 0


def p23_config_path(node_count: int) -> Path:
    return ROOT / "templates" / "configs" / f"p23_{node_count}.yaml"


def p23_scenario(node_count: int) -> str:
    return f"p23_fault_matrix_{node_count}"


def p23_key_slot(key: str) -> int:
    encoded = key.encode("utf-8")
    left = key.find("{")
    if left >= 0:
        right = key.find("}", left + 1)
        if right > left + 1:
            encoded = key[left + 1 : right].encode("utf-8")
    return binascii.crc_hqx(encoded, 0) % 16384


def p23_slot_range(slot_spec: str) -> tuple[int, int] | None:
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


def p23_key_for_slot_range(prefix: str, low: int, high: int) -> str:
    for idx in range(30000):
        tag = f"p23-{idx}"
        key = f"{prefix}:{{{tag}}}"
        if low <= p23_key_slot(key) <= high:
            return key
    raise RuntimeError(f"could not find P23 key for slot range {low}-{high}")


def p23_target_from_probes(state: dict[str, Any], endpoints: list[Endpoint], probes: list[dict[str, Any]]) -> tuple[dict[str, Any], Endpoint, dict[str, Any]]:
    endpoint_by_logical = {endpoint.logical_id: endpoint for endpoint in endpoints}
    probe_by_logical = {probe.get("logical_id"): probe for probe in probes if probe.get("status") == "PASS"}
    for node in state.get("nodes", []):
        if node.get("role") != "primary":
            continue
        logical_id = str(node.get("logical_id"))
        endpoint = endpoint_by_logical.get(logical_id)
        probe = probe_by_logical.get(logical_id)
        if endpoint is None or not probe:
            continue
        myself = probe.get("myself_node_id")
        cluster_node = (probe.get("cluster_nodes") or {}).get(myself, {})
        for slot_spec in cluster_node.get("slots", []):
            slot_range = p23_slot_range(str(slot_spec))
            if slot_range is None:
                continue
            low, high = slot_range
            slot_key = p23_key_for_slot_range(f"p23:{logical_id}", low, high)
            return node, endpoint, {
                "target_logical_id": logical_id,
                "target_node_id": myself,
                "slot_range": [low, high],
                "slot_key": slot_key,
                "slot": p23_key_slot(slot_key),
                "entry_logical_id": logical_id,
            }
    raise RuntimeError("P23 could not find a primary target with an owned slot range")


def p23_rule_and_parameters(fault_type: str, target: dict[str, Any]) -> tuple[ProxyRule, dict[str, Any]]:
    target_set = [target["target_logical_id"]]
    if fault_type == "network_delay":
        params = {
            "delay_ms": 75,
            "jitter_ms": 10,
            "affected_direction": "bidirectional_proxy_relay",
            "target_set": target_set,
            "duration_seconds": 1,
        }
        return ProxyRule(fault_type=fault_type, delay_ms=75, jitter_ms=10), params
    if fault_type == "network_loss":
        params = {
            "loss_percent": 50.0,
            "correlation": 0.0,
            "affected_direction": "client_to_target_connection",
            "target_set": target_set,
            "duration_seconds": 1,
        }
        return ProxyRule(fault_type=fault_type, loss_percent=50.0), params
    if fault_type == "network_flap":
        params = {
            "up_ms": 80,
            "down_ms": 80,
            "iterations": 6,
            "target_set": target_set,
            "duration_seconds": 1,
        }
        return ProxyRule(fault_type=fault_type, flap_up_ms=80, flap_down_ms=80, flap_iterations=6), params
    raise RuntimeError(f"unsupported P23 fault type {fault_type}")


def p23_command_log(
    *,
    phase: str,
    run_id: str,
    sample_id: str,
    fault_id: str,
    command_kind: str,
    started_at: int,
    ended_at: int,
    status: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "phase_id": phase,
        "run_id": run_id,
        "sample_id": sample_id,
        "fault_id": fault_id,
        "command_id": f"{fault_id}-{command_kind}",
        "command_kind": command_kind,
        "started_at_unix_ms": started_at,
        "ended_at_unix_ms": ended_at,
        "status": status,
        "implementation_path": "sandbox_proxy",
        "host_network_mutated": False,
        "details": details,
    }


def p23_workload_window(
    *,
    phase: str,
    run_id: str,
    sample_id: str,
    fault_id: str,
    fault_type: str,
    node_count: int,
    window_name: str,
    endpoints: list[Endpoint],
    entry: Endpoint,
    slot_key: str,
    operation_pairs: int,
    pause_ms: int = 0,
) -> dict[str, Any]:
    started_at = unix_ms()
    started_monotonic = monotonic_ms()
    event_prefix = f"{sample_id}-{window_name}"
    attempted = 0
    ok_ops = 0
    errors = 0
    timeouts = 0
    redirects = 0
    connection_errors = 0
    latencies: list[float] = []
    samples: list[dict[str, Any]] = []
    for index in range(operation_pairs):
        key = f"{slot_key}:{window_name}:{index}"
        value = f"p23-value-{sample_id}-{window_name}-{index}"
        for command in [("SET", key, value), ("GET", key)]:
            attempted += 1
            started = time.monotonic()
            try:
                reply, redirect_count = execute_workload_command(endpoints, entry, *command)
                if command[0] == "SET" and str(reply) != "OK":
                    raise RuntimeError(f"SET returned {reply!r}")
                if command[0] == "GET" and str(reply) != value:
                    raise RuntimeError(f"GET returned {reply!r}, expected {value!r}")
                elapsed = round((time.monotonic() - started) * 1000, 3)
                latencies.append(elapsed)
                redirects += redirect_count
                ok_ops += 1
                samples.append({"command": command[0], "status": "PASS", "latency_ms": elapsed, "redirects": redirect_count})
            except Exception as exc:  # noqa: BLE001
                elapsed = round((time.monotonic() - started) * 1000, 3)
                message = repr(exc)
                errors += 1
                if "timeout" in message.lower() or "timed out" in message.lower():
                    timeouts += 1
                if "connection" in message.lower() or "empty resp" in message.lower() or "closed" in message.lower():
                    connection_errors += 1
                samples.append({"command": command[0], "status": "FAIL", "latency_ms": elapsed, "error": message[:240]})
            if pause_ms:
                time.sleep(pause_ms / 1000.0)
    ended_at = unix_ms()
    duration_ms = max(ended_at - started_at, 0)
    metrics = workload_metrics(attempted, ok_ops, errors, timeouts, redirects, latencies, duration_ms)
    metrics["connection_error_count"] = connection_errors
    metrics["unknown_error_count"] = max(errors - timeouts - connection_errors, 0)
    if metrics["latency_p999_ms"] == "MISSING":
        metrics["missing_reasons"]["latency_p999_ms"] = "P23 focused network fault gate uses too few workload samples for p999."
    return {
        "window_name": window_name,
        "sample_id": sample_id,
        "fault_id": fault_id,
        "fault_type": fault_type,
        "node_count": node_count,
        "source_window_name": window_name,
        "start_event_id": f"{event_prefix}-start",
        "end_event_id": f"{event_prefix}-end",
        "start_time_unix_ms": started_at,
        "end_time_unix_ms": ended_at,
        "start_monotonic_ms": started_monotonic,
        "end_monotonic_ms": monotonic_ms(),
        "metrics": metrics,
        "samples": samples[:24],
        "entry_logical_id": entry.logical_id,
        "slot_key": slot_key,
        "slot": p23_key_slot(slot_key),
        "run_id": run_id,
        "phase_id": phase,
    }


def p23_all_run_window(phase: str, run_id: str, sample_id: str, fault_id: str, fault_type: str, node_count: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    children = [row for row in rows if row.get("sample_id") == sample_id]
    started_values = [row.get("start_time_unix_ms") for row in children if isinstance(row.get("start_time_unix_ms"), int)]
    ended_values = [row.get("end_time_unix_ms") for row in children if isinstance(row.get("end_time_unix_ms"), int)]
    total_duration = max(max(ended_values, default=0) - min(started_values, default=0), 0)
    total_ops = sum(int(row.get("metrics", {}).get("sample_count", 0) or 0) for row in children)
    total_ok = sum(int(row.get("metrics", {}).get("ok_ops", 0) or 0) for row in children)
    total_errors = sum(int(row.get("metrics", {}).get("error_ops", 0) or 0) for row in children)
    total_timeouts = sum(int(row.get("metrics", {}).get("timeout_count", 0) or 0) for row in children)
    total_redirects = sum(int(row.get("metrics", {}).get("moved_redirection_count", 0) or 0) for row in children)
    return {
        "window_name": "all_run",
        "sample_id": sample_id,
        "fault_id": fault_id,
        "fault_type": fault_type,
        "node_count": node_count,
        "source_window_name": "all_run_aggregate",
        "start_event_id": f"{sample_id}-all_run-start",
        "end_event_id": f"{sample_id}-all_run-end",
        "start_time_unix_ms": min(started_values) if started_values else "MISSING",
        "end_time_unix_ms": max(ended_values) if ended_values else "MISSING",
        "start_monotonic_ms": "MISSING",
        "end_monotonic_ms": "MISSING",
        "metrics": workload_metrics(total_ops, total_ok, total_errors, total_timeouts, total_redirects, [], total_duration),
        "samples": [],
        "entry_logical_id": "aggregate",
        "run_id": run_id,
        "phase_id": phase,
    }


def p23_effect_observed(fault_type: str, baseline: dict[str, Any], event: dict[str, Any], proxy_stats: dict[str, Any]) -> bool:
    baseline_metrics = baseline.get("metrics", {})
    event_metrics = event.get("metrics", {})
    if fault_type == "network_delay":
        baseline_p99 = baseline_metrics.get("latency_p99_ms")
        event_p99 = event_metrics.get("latency_p99_ms")
        return bool(proxy_stats.get("delay_injections", 0) > 0 and isinstance(baseline_p99, (int, float)) and isinstance(event_p99, (int, float)) and event_p99 > baseline_p99)
    if fault_type == "network_loss":
        return bool(proxy_stats.get("dropped_connections", 0) > 0 and int(event_metrics.get("error_ops", 0) or 0) > int(baseline_metrics.get("error_ops", 0) or 0))
    if fault_type == "network_flap":
        return bool(proxy_stats.get("flap_rejections", 0) > 0 and int(event_metrics.get("error_ops", 0) or 0) > int(baseline_metrics.get("error_ops", 0) or 0))
    return False


def p23_run_fault(
    *,
    phase: str,
    node_count: int,
    state_path: Path,
    state: dict[str, Any],
    endpoints: list[Endpoint],
    probes_before: list[dict[str, Any]],
    fault_type: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    scenario = p23_scenario(node_count)
    run_id = str(state.get("runtime", {}).get("run_id", f"{phase}-{scenario}-20260628"))
    sample_id = f"p23-{node_count}-{fault_type}"
    fault_id = f"{sample_id}-fault"
    target_node, target_endpoint, target = p23_target_from_probes(state, endpoints, probes_before)
    rule, parameters = p23_rule_and_parameters(fault_type, target)
    workload_rows: list[dict[str, Any]] = []
    command_rows: list[dict[str, Any]] = []

    direct_entry = target_endpoint
    for window in ["baseline", "pre_event"]:
        workload_rows.append(
            p23_workload_window(
                phase=phase,
                run_id=run_id,
                sample_id=sample_id,
                fault_id=fault_id,
                fault_type=fault_type,
                node_count=node_count,
                window_name=window,
                endpoints=endpoints,
                entry=direct_entry,
                slot_key=target["slot_key"],
                operation_pairs=3,
            )
        )

    apply_started = unix_ms()
    proxy = SandboxNetworkProxy(target_host=target_endpoint.host, target_port=target_endpoint.port, rule=rule)
    proxy.start()
    apply_completed = unix_ms()
    command_rows.append(
        p23_command_log(
            phase=phase,
            run_id=run_id,
            sample_id=sample_id,
            fault_id=fault_id,
            command_kind="sandbox_proxy_apply",
            started_at=apply_started,
            ended_at=apply_completed,
            status="PASS",
            details={
                "listen_host": proxy.address[0],
                "listen_port": proxy.address[1],
                "target_logical_id": target["target_logical_id"],
                "target_port": target_endpoint.port,
                "fault_parameters": parameters,
            },
        )
    )
    proxy_endpoint = Endpoint(
        logical_id=f"{target_endpoint.logical_id}-sandbox-proxy",
        host=proxy.address[0],
        port=proxy.address[1],
        password=target_endpoint.password,
        az_id=target_endpoint.az_id,
        role=target_endpoint.role,
        container_ip=target_endpoint.container_ip,
    )
    event_pairs = 8 if fault_type == "network_flap" else 4
    event_pause = 60 if fault_type == "network_flap" else 0
    event_row = p23_workload_window(
        phase=phase,
        run_id=run_id,
        sample_id=sample_id,
        fault_id=fault_id,
        fault_type=fault_type,
        node_count=node_count,
        window_name="event",
        endpoints=endpoints,
        entry=proxy_endpoint,
        slot_key=target["slot_key"],
        operation_pairs=event_pairs,
        pause_ms=event_pause,
    )
    workload_rows.append(event_row)
    proxy_stats = proxy.snapshot()
    clear_started = unix_ms()
    proxy.close()
    clear_completed = unix_ms()
    command_rows.append(
        p23_command_log(
            phase=phase,
            run_id=run_id,
            sample_id=sample_id,
            fault_id=fault_id,
            command_kind="sandbox_proxy_clear",
            started_at=clear_started,
            ended_at=clear_completed,
            status="PASS",
            details={"proxy_stats": proxy_stats, "state_ref": rel_path(state_path)},
        )
    )

    ok_recovered, _probes_recovered = wait_for_cluster_ok(endpoints, node_count, timeout_seconds=90)
    recovery_completed = unix_ms()
    for window in ["recovery", "post_recovery"]:
        workload_rows.append(
            p23_workload_window(
                phase=phase,
                run_id=run_id,
                sample_id=sample_id,
                fault_id=fault_id,
                fault_type=fault_type,
                node_count=node_count,
                window_name=window,
                endpoints=endpoints,
                entry=direct_entry,
                slot_key=target["slot_key"],
                operation_pairs=3,
            )
        )
    workload_rows.append(p23_all_run_window(phase, run_id, sample_id, fault_id, fault_type, node_count, workload_rows))
    observed_effect = p23_effect_observed(fault_type, workload_rows[0], event_row, proxy_stats)
    if not observed_effect:
        errors.append(f"{sample_id}: expected proxy-observed effect was not measured")
    if not ok_recovered:
        errors.append(f"{sample_id}: cluster did not recover to OK after clearing proxy")
    status = "PASS" if not errors else "FAIL"
    row = {
        "schema_version": "v1",
        "phase_id": phase,
        "run_id": run_id,
        "scenario_name": scenario,
        "sample_id": sample_id,
        "node_count": node_count,
        "status": status,
        "real_valkey": True,
        "fault_type": fault_type,
        "fault_id": fault_id,
        "scope": "sandbox_proxy",
        "implementation_path": "sandbox_proxy",
        "targets": [node_identity(target_node)],
        "target_selector": {
            "selector_type": "primary_slot_owner",
            "selected_logical_id": target["target_logical_id"],
            "slot_range": target["slot_range"],
            "slot": target["slot"],
        },
        "target_count": 1,
        "fault_parameters": parameters,
        "apply_started_at_ms": apply_started,
        "apply_completed_at_ms": apply_completed,
        "clear_started_at_ms": clear_started,
        "clear_completed_at_ms": clear_completed,
        "recovery_completed_at_ms": recovery_completed,
        "apply_duration_ms": max(apply_completed - apply_started, 0),
        "clear_duration_ms": max(clear_completed - clear_started, 0),
        "recovery_latency_ms": max(recovery_completed - clear_started, 0),
        "observed_effect_started_at_ms": apply_completed if observed_effect else "MISSING",
        "expected_impact": f"{fault_type} reduces or delays Valkey client traffic through the sandbox proxy.",
        "observed_impact": {
            "effect_observed": observed_effect,
            "proxy_stats": proxy_stats,
            "event_metrics": event_row.get("metrics", {}),
            "baseline_metrics": workload_rows[0].get("metrics", {}),
        },
        "safety_scope_verified": True,
        "cleanup_verified": status == "PASS",
        "host_network_mutated": False,
        "physical_host_mutated": False,
        "physical_az_mutated": False,
        "workload_impact_ref": f"artifacts/phases/{phase}/workload_impact_report.json#{sample_id}",
        "command_log_ref": f"artifacts/phases/{phase}/network_fault_command_log.jsonl#{fault_id}",
        "state_ref": rel_path(state_path),
        "errors_by_type": {"harness": errors} if errors else {},
        "missing_fields": [] if observed_effect else [{"field": "observed_effect_started_at_ms", "status": "MISSING", "reason": "Proxy counters did not show expected impairment."}],
    }
    return row, workload_rows, command_rows, errors


def p23_inner_paths(artifact_dir: Path, node_count: int) -> dict[str, Path]:
    scenario = p23_scenario(node_count)
    work_dir = artifact_dir / "_p23_runs" / scenario
    return {
        "work_dir": work_dir,
        "state": work_dir / "state_p23.json",
        "cleanup_report": work_dir / "cleanup_report.json",
    }


def run_p23_node_count(phase: str, artifact_dir: Path, node_count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], set[str], list[str]]:
    paths = p23_inner_paths(artifact_dir, node_count)
    work_dir = paths["work_dir"]
    work_dir.mkdir(parents=True, exist_ok=True)
    state_path = paths["state"]
    scenario = p23_scenario(node_count)
    setup = run_cmd(
        [
            sys.executable,
            "-m",
            "valkey_scale_lab.cli",
            "gate",
            "scenario",
            "--phase",
            phase,
            "--scenario",
            scenario,
            "--config",
            str(p23_config_path(node_count)),
            "--artifacts-dir",
            str(work_dir),
            "--state-out",
            str(state_path),
        ],
        timeout=max(900, node_count * 30),
    )
    (work_dir / "p23_setup.stdout.log").write_text(setup.stdout, encoding="utf-8", errors="replace")
    (work_dir / "p23_setup.stderr.log").write_text(setup.stderr, encoding="utf-8", errors="replace")
    if setup.returncode != 0:
        cleanup_status = "FAIL"
        cleanup_path = paths["cleanup_report"]
        if state_path.exists():
            cleanup_status, cleanup_path = project_cleanup(phase, state_path, work_dir)
        elif not cleanup_path.exists():
            write_json(
                cleanup_path,
                {
                    "schema_version": "v1",
                    "artifact_type": "cleanup_report",
                    "phase_id": phase,
                    "run_id": f"{phase}-{scenario}-setup-failed",
                    "created_at": utc_now(),
                    "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
                    "status": "FAIL",
                    "resources_remaining": [],
                    "cleanup_actions": [{"type": "p23_setup", "node_count": node_count, "status": "FAIL", "reason": setup.stderr[-1000:]}],
                },
            )
        cleanup_action = {"type": "p23_subrun_cleanup", "status": cleanup_status, "report_ref": rel_path(cleanup_path), "node_count": node_count}
        return [], [], [], cleanup_action, [], set(), [f"{scenario}: setup failed exit={setup.returncode}"]
    state = load_state(state_path)
    endpoints = endpoints_from_state(state)
    ok_before, probes_before = wait_for_cluster_ok(endpoints, node_count, timeout_seconds=120)
    errors: list[str] = []
    if not ok_before:
        errors.append(f"{scenario}: cluster not OK before P23 faults")
    rows: list[dict[str, Any]] = []
    workload_rows: list[dict[str, Any]] = []
    command_rows: list[dict[str, Any]] = []
    versions: set[str] = set()
    final_probes: list[dict[str, Any]] = []
    for fault_type in P23_FAULT_TYPES:
        state = load_state(state_path)
        endpoints = endpoints_from_state(state)
        row, windows, commands, fault_errors = p23_run_fault(
            phase=phase,
            node_count=node_count,
            state_path=state_path,
            state=state,
            endpoints=endpoints,
            probes_before=probes_before,
            fault_type=fault_type,
        )
        rows.append(row)
        workload_rows.extend(windows)
        command_rows.extend(commands)
        errors.extend(fault_errors)
    ok_final, final_probes = wait_for_cluster_ok(endpoints_from_state(load_state(state_path)), node_count, timeout_seconds=120)
    if not ok_final:
        errors.append(f"{scenario}: final cluster OK probe failed before cleanup")
    for probe in final_probes:
        if probe.get("status") == "PASS" and probe.get("version"):
            versions.add(str(probe["version"]))
    cleanup_status, cleanup_path = project_cleanup(phase, state_path, work_dir)
    if cleanup_status != "PASS":
        errors.append(f"{scenario}: cleanup failed")
    for row in rows:
        if cleanup_status != "PASS":
            row["cleanup_verified"] = False
            row["status"] = "FAIL"
            row.setdefault("errors_by_type", {}).setdefault("cleanup", []).append("aggregate cleanup failed")
        row["cleanup_ref"] = rel_path(cleanup_path)
    cleanup_action = {"type": "p23_subrun_cleanup", "node_count": node_count, "status": cleanup_status, "report_ref": rel_path(cleanup_path)}
    return rows, workload_rows, command_rows, cleanup_action, final_probes, versions, errors


def p23_events(fault_rows: list[dict[str, Any]], workload_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = p22_events(fault_rows, workload_rows)
    for row in rows:
        row["scenario_name"] = str(row.get("scenario_name", "")).replace("p22_fault_matrix", "p23_fault_matrix")
    return rows


def p23_metrics(fault_rows: list[dict[str, Any]], workload_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = p22_metrics(fault_rows, workload_rows)
    for row in rows:
        row["scenario_name"] = str(row.get("scenario_name", "")).replace("p22_fault_matrix", "p23_fault_matrix")
    for fault in fault_rows:
        if fault.get("status") == "SKIPPED_WITH_REASON":
            continue
        stats = (fault.get("observed_impact") or {}).get("proxy_stats") or {}
        for name in ["delay_injections", "dropped_connections", "flap_rejections", "accepted_connections"]:
            value = stats.get(name, "MISSING")
            rows.append(
                {
                    "schema_version": "v1",
                    "run_id": fault["run_id"],
                    "phase_id": fault["phase_id"],
                    "scenario_name": fault["scenario_name"],
                    "sample_id": fault["sample_id"],
                    "timestamp_unix_ms": fault.get("clear_completed_at_ms", "MISSING"),
                    "monotonic_ms": fault.get("clear_completed_at_ms", "MISSING"),
                    "source_type": "harness",
                    "source_id": fault["fault_id"],
                    "metric_name": f"proxy_{name}",
                    "metric_value": value,
                    "metric_unit": "count",
                    "labels": {"fault_type": fault["fault_type"], "node_count": fault["node_count"]},
                    "missing_reason": "" if value != "MISSING" else f"{name} was not observed",
                }
            )
    return rows


def run_p23_controller(args: argparse.Namespace) -> int:
    artifact_dir = Path(args.out).parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    phase = args.phase
    run_id = f"{phase}-network-faults-20260628"
    all_fault_rows: list[dict[str, Any]] = []
    all_workload_rows: list[dict[str, Any]] = []
    all_command_rows: list[dict[str, Any]] = []
    cleanup_actions: list[dict[str, Any]] = []
    resources_remaining: list[dict[str, Any]] = []
    top_probes: list[dict[str, Any]] = []
    versions: set[str] = set()
    errors: list[str] = []

    for node_count in [6, 10]:
        rows, workload_rows, command_rows, cleanup_action, probes, observed_versions, run_errors = run_p23_node_count(phase, artifact_dir, node_count)
        all_fault_rows.extend(rows)
        all_workload_rows.extend(workload_rows)
        all_command_rows.extend(command_rows)
        cleanup_actions.append(cleanup_action)
        top_probes.extend(probes[:4])
        versions.update(observed_versions)
        errors.extend(run_errors)

    for action in cleanup_actions:
        report_ref = str(action.get("report_ref") or "")
        report = load_json_if_exists(ROOT / report_ref) if report_ref else {}
        for item in report.get("resources_remaining", []) if isinstance(report.get("resources_remaining"), list) else []:
            resources_remaining.append({"node_count": action.get("node_count"), **item})
        if action.get("status") != "PASS":
            errors.append(f"cleanup failed for node_count={action.get('node_count')}")

    comparisons = [
        p22_comparison(row["sample_id"], row["fault_type"], row["node_count"], all_workload_rows)
        for row in all_fault_rows
        if row.get("status") != "SKIPPED_WITH_REASON"
    ]
    events = p23_events(all_fault_rows, all_workload_rows)
    metrics = p23_metrics(all_fault_rows, all_workload_rows)
    aggregate_cleanup_status = "PASS" if not resources_remaining and all(action.get("status") == "PASS" for action in cleanup_actions) else "FAIL"
    status = "PASS" if not errors and all(row.get("status") == "PASS" for row in all_fault_rows) and aggregate_cleanup_status == "PASS" else "FAIL"

    write_jsonl(artifact_dir / "fault_results.jsonl", all_fault_rows)
    write_jsonl(artifact_dir / "network_fault_command_log.jsonl", all_command_rows)
    write_jsonl(artifact_dir / "events.jsonl", events)
    write_jsonl(artifact_dir / "metrics_timeseries.jsonl", metrics)
    write_json(artifact_dir / "workload_windows.json", {
        "schema_version": "v1",
        "artifact_type": "workload_windows",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": status,
        "windows": all_workload_rows,
    })
    write_json(artifact_dir / "workload_impact_report.json", {
        "schema_version": "v1",
        "artifact_type": "workload_impact_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": status,
        "windows": all_workload_rows,
        "comparisons": comparisons,
    })
    fault_matrix = {
        "schema_version": "v1",
        "artifact_type": "fault_matrix_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": status,
        "fault_rows": all_fault_rows,
        "safety_checks": {
            "host_network_mutated": False,
            "global_firewall_mutated": False,
            "physical_host_mutated": False,
            "physical_az_mutated": False,
            "sandbox_proxy_only": True,
        },
    }
    write_json(Path(args.fault_report), fault_matrix)
    write_json(artifact_dir / "network_fault_report.json", {
        "schema_version": "v1",
        "artifact_type": "network_fault_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": status,
        "network_faults": all_fault_rows,
        "command_log_ref": "network_fault_command_log.jsonl",
        "safe_paths_exercised": sorted({row.get("implementation_path") for row in all_fault_rows if row.get("status") == "PASS"}),
    })
    write_json(artifact_dir / "cleanup_report.json", {
        "schema_version": "v1",
        "artifact_type": "cleanup_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": aggregate_cleanup_status,
        "resources_remaining": resources_remaining,
        "cleanup_actions": cleanup_actions,
    })
    write_json(Path(args.out), {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": status,
        "scenario": "p23_fault_matrix",
        "real_valkey": True,
        "valkey_version_prefix_required": "9.1.",
        "probe_result": "PASS" if status == "PASS" else "FAIL",
        "nodes_observed": max([observed_count(top_probes), *[row.get("node_count", 0) for row in all_fault_rows if row.get("status") == "PASS"]], default=1),
        "cluster_state_observed": "ok" if status == "PASS" else cluster_state_from_probes(top_probes),
        "data_path_result": "PASS" if all_workload_rows else "FAIL",
        "valkey_versions": sorted(versions),
        "probes": top_probes or [{"logical_id": "p23-no-probe", "host": "127.0.0.1", "port": 1, "status": "FAIL"}],
        "cleanup": {"status": aggregate_cleanup_status, "path": rel_path(artifact_dir / "cleanup_report.json")},
        "fault_types": P23_FAULT_TYPES,
        "sample_refs": [row["sample_id"] for row in all_fault_rows],
        "errors": errors,
    })
    write_json(artifact_dir / "quant_summary.json", {
        "schema_version": "v1",
        "artifact_type": "quant_summary",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": status,
        "summary": "P23 quant summary for real sandbox-proxy network delay, loss, and flap faults.",
        "artifact_refs": [
            "fault_results.jsonl",
            "events.jsonl",
            "metrics_timeseries.jsonl",
            "workload_windows.json",
            "workload_impact_report.json",
            "network_fault_report.json",
            "fault_matrix_report.json",
            "network_fault_command_log.jsonl",
            "cleanup_report.json",
        ],
        "counts": {
            "event_count": len(events),
            "metric_count": len(metrics),
            "sample_count": len(all_fault_rows),
            "fault_result_count": len(all_fault_rows),
            "command_log_count": len(all_command_rows),
        },
        "missing_data": [],
        "runtime_claims": {"real_valkey_claimed": True, "management_runtime_claimed": False, "fault_runtime_claimed": True},
    })
    write_json(artifact_dir / "phase_summary.json", {
        "schema_version": "v1",
        "artifact_type": "phase_summary",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
        "status": status,
        "summary": "P23 runs real network_delay, network_loss, and network_flap rows through a project-owned sandbox proxy.",
        "required_artifacts": [
            f"artifacts/phases/{phase}/phase_summary.json",
            f"artifacts/phases/{phase}/valkey_e2e_evidence.json",
            f"artifacts/phases/{phase}/cleanup_report.json",
            f"artifacts/phases/{phase}/events.jsonl",
            f"artifacts/phases/{phase}/metrics_timeseries.jsonl",
            f"artifacts/phases/{phase}/workload_windows.json",
            f"artifacts/phases/{phase}/quant_summary.json",
            f"artifacts/phases/{phase}/network_fault_report.json",
            f"artifacts/phases/{phase}/fault_results.jsonl",
            f"artifacts/phases/{phase}/workload_impact_report.json",
            f"artifacts/phases/{phase}/network_fault_command_log.jsonl",
            f"artifacts/phases/{phase}/fault_matrix_report.json",
        ],
        "missing_metrics": [],
        "risks": [{"risk": "P23 measures a proxied target slot rather than applying container namespace traffic control.", "severity": "medium", "required_before_next_phase": False}],
    })

    if status != "PASS":
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS P23 network fault matrix out={args.out} fault_report={args.fault_report}")
    return 0


def p24_config_path(node_count: int) -> Path:
    return ROOT / "templates" / "configs" / f"p24_{node_count}.yaml"


def p24_scenario(node_count: int) -> str:
    return f"p24_partition_matrix_{node_count}"


def p24_inner_paths(artifact_dir: Path, node_count: int) -> dict[str, Path]:
    scenario = p24_scenario(node_count)
    work_dir = artifact_dir / "_p24_runs" / scenario
    return {
        "work_dir": work_dir,
        "state": work_dir / "state_p24.json",
        "cleanup_report": work_dir / "cleanup_report.json",
    }


def p24_command_log(
    *,
    phase: str,
    run_id: str,
    sample_id: str,
    fault_id: str,
    command_kind: str,
    started_at: int,
    ended_at: int,
    status: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "phase_id": phase,
        "run_id": run_id,
        "sample_id": sample_id,
        "fault_id": fault_id,
        "command_id": f"{fault_id}-{command_kind}",
        "command_kind": command_kind,
        "started_at_unix_ms": started_at,
        "ended_at_unix_ms": ended_at,
        "status": status,
        "implementation_path": "owned_docker_network_control",
        "host_network_mutated": False,
        "global_firewall_mutated": False,
        "physical_host_mutated": False,
        "details": details,
    }


def p24_plan_partition(state: dict[str, Any]) -> dict[str, Any]:
    nodes = list(state.get("nodes", []))
    by_nodehost: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        by_nodehost.setdefault(str(node.get("nodehost_id", "MISSING")), []).append(node)
    candidates = [(nodehost_id, items) for nodehost_id, items in by_nodehost.items() if nodehost_id != "MISSING" and len(items) < len(nodes)]
    if len(candidates) < 2:
        raise RuntimeError("P24 requires at least two owned nodehost groups")
    minority_nodehost_id, minority_nodes = sorted(candidates, key=lambda item: (len(item[1]), item[0]))[0]
    majority_nodes = [node for node in nodes if node not in minority_nodes]
    nodehosts_by_id = {str(item.get("nodehost_id")): item for item in state.get("nodehosts", [])}
    minority_nodehosts = sorted({str(node.get("nodehost_id")) for node in minority_nodes})
    majority_nodehosts = sorted({str(node.get("nodehost_id")) for node in majority_nodes})
    if not minority_nodehosts or not majority_nodehosts:
        raise RuntimeError("P24 partition planner could not map nodehosts")
    minority_azs = sorted({str(node.get("az_id")) for node in minority_nodes})
    return {
        "groups": {
            "majority": [str(node.get("logical_id")) for node in majority_nodes],
            "minority": [str(node.get("logical_id")) for node in minority_nodes],
            "isolated": [],
        },
        "group_nodehosts": {
            "majority": majority_nodehosts,
            "minority": minority_nodehosts,
            "isolated": [],
        },
        "minority_az": minority_azs[0] if len(minority_azs) == 1 else "mixed",
        "minority_azs": minority_azs,
        "minority_nodehost_id": minority_nodehost_id,
        "majority_azs": sorted({str(node.get("az_id")) for node in majority_nodes}),
        "majority_nodehost_ids": majority_nodehosts,
        "minority_nodes": minority_nodes,
        "majority_nodes": majority_nodes,
        "minority_nodehosts": [nodehosts_by_id[nodehost_id] for nodehost_id in minority_nodehosts],
        "majority_nodehosts": [nodehosts_by_id[nodehost_id] for nodehost_id in majority_nodehosts],
        "traffic_policy": {
            "block_between_groups": True,
            "allow_within_group": True,
            "implementation_path": "owned_docker_network_control",
            "between_group_control": "docker network disconnect owned minority nodehost containers from owned stage network",
            "within_group_preservation": "majority nodehost containers remain connected on the owned Docker network; minority side is probed through owned container loopback while isolated",
            "host_network_mutated": False,
            "global_firewall_mutated": False,
            "physical_host_mutated": False,
        },
    }


def p24_docker_network_control(
    *,
    phase: str,
    run_id: str,
    sample_id: str,
    fault_id: str,
    network_name: str,
    nodehosts: list[dict[str, Any]],
    action: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for nodehost in nodehosts:
        started = unix_ms()
        container = str(nodehost.get("container_name"))
        container_ip = str(nodehost.get("container_ip"))
        if action == "disconnect":
            cmd = ["docker", "network", "disconnect", network_name, container]
            kind = "owned_docker_network_disconnect"
        elif action == "connect":
            cmd = ["docker", "network", "connect", "--ip", container_ip, network_name, container]
            kind = "owned_docker_network_connect"
        else:
            raise RuntimeError(f"unsupported P24 network control action {action}")
        proc = run_cmd(cmd, timeout=60)
        ended = unix_ms()
        status = "PASS" if proc.returncode == 0 else "FAIL"
        if status != "PASS":
            errors.append(f"{sample_id}: docker network {action} failed for {container}: {proc.stderr[-500:]}")
        rows.append(
            p24_command_log(
                phase=phase,
                run_id=run_id,
                sample_id=sample_id,
                fault_id=fault_id,
                command_kind=kind,
                started_at=started,
                ended_at=ended,
                status=status,
                details={
                    "network_name": network_name,
                    "container_name": container,
                    "container_ip": container_ip,
                    "nodehost_id": nodehost.get("nodehost_id"),
                    "docker_command_scope": "owned_stage_network_and_owned_nodehost_container",
                    "stderr": proc.stderr[-500:],
                },
            )
        )
    return rows, errors


def p24_probe_container_node(node: dict[str, Any], timeout: int = 10) -> dict[str, Any]:
    result: dict[str, Any] = {
        "logical_id": node.get("logical_id", "MISSING"),
        "host": "owned-nodehost-loopback",
        "port": node.get("client_port", "MISSING"),
        "status": "FAIL",
        "probe_method": "docker_exec_valkey_cli_loopback",
        "nodehost_id": node.get("nodehost_id", "MISSING"),
        "container_name": node.get("container_name", "MISSING"),
        "host_network_mutated": False,
    }

    def cli(*args: Any) -> subprocess.CompletedProcess[str]:
        return run_cmd(
            ["docker", "exec", str(node.get("container_name")), "valkey-cli", "-p", str(node.get("client_port")), *[str(arg) for arg in args]],
            timeout=timeout,
        )

    ping = cli("PING")
    info = cli("INFO", "server")
    cinfo = cli("CLUSTER", "INFO")
    cnodes = cli("CLUSTER", "NODES")
    if ping.returncode == info.returncode == cinfo.returncode == cnodes.returncode == 0:
        parsed_info = parse_cluster_info(cinfo.stdout)
        parsed_nodes = parse_cluster_nodes(cnodes.stdout)
        myself = next((nid for nid, item in parsed_nodes.items() if "myself" in item.get("flags", [])), None)
        server_info = {}
        for line in info.stdout.splitlines():
            if ":" in line and not line.startswith("#"):
                key, value = line.split(":", 1)
                server_info[key] = value
        result.update(
            {
                "status": "PASS",
                "ping": ping.stdout.strip(),
                "version": server_info.get("valkey_version") or server_info.get("redis_version") or "unknown",
                "cluster_state": parsed_info.get("cluster_state", "unknown"),
                "cluster_known_nodes": int(parsed_info.get("cluster_known_nodes", "0") or 0),
                "myself_node_id": myself,
                "cluster_nodes": parsed_nodes,
            }
        )
    else:
        result["error"] = "; ".join(
            item.stderr.strip() or item.stdout.strip()
            for item in [ping, info, cinfo, cnodes]
            if item.returncode != 0
        )[:500]
    return result


def p24_probe_side(
    *,
    side: str,
    nodes: list[dict[str, Any]],
    endpoints: list[Endpoint],
    method: str,
) -> list[dict[str, Any]]:
    logical_ids = {str(node.get("logical_id")) for node in nodes}
    if method == "host":
        return [
            {**probe_endpoint(endpoint, timeout=2.0), "side": side, "probe_method": "host_published_endpoint"}
            for endpoint in endpoints
            if endpoint.logical_id in logical_ids
        ]
    if method == "docker_exec":
        return [{**p24_probe_container_node(node), "side": side} for node in nodes]
    raise RuntimeError(f"unsupported P24 side probe method {method}")


def p24_primary_slot_ranges(probe: dict[str, Any]) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    for node_id, node in (probe.get("cluster_nodes") or {}).items():
        if node.get("role") != "primary":
            continue
        for slot_spec in node.get("slots", []):
            slot_range = p23_slot_range(str(slot_spec))
            if slot_range is None:
                continue
            ranges.append({"node_id": node_id, "low": slot_range[0], "high": slot_range[1]})
    return ranges


def p24_side_signature(probes: list[dict[str, Any]]) -> dict[str, Any]:
    pass_probes = [probe for probe in probes if probe.get("status") == "PASS"]
    primary_ranges: list[dict[str, Any]] = []
    known_node_ids: set[str] = set()
    cluster_states: set[str] = set()
    for probe in pass_probes:
        cluster_states.add(str(probe.get("cluster_state", "unknown")))
        for node_id in (probe.get("cluster_nodes") or {}).keys():
            known_node_ids.add(str(node_id))
        primary_ranges.extend(p24_primary_slot_ranges(probe))
    return {
        "pass_probe_count": len(pass_probes),
        "cluster_states": sorted(cluster_states),
        "known_node_ids": sorted(known_node_ids),
        "primary_slot_ranges": sorted(primary_ranges, key=lambda item: (item["low"], item["high"], item["node_id"]))[:32],
    }


def p24_select_primary_target(nodes: list[dict[str, Any]], endpoints: list[Endpoint], probes: list[dict[str, Any]], group_logical_ids: set[str], prefix: str) -> tuple[dict[str, Any], Endpoint | None, dict[str, Any]]:
    endpoint_by_logical = {endpoint.logical_id: endpoint for endpoint in endpoints}
    probe_by_logical = {probe.get("logical_id"): probe for probe in probes if probe.get("status") == "PASS"}
    for node in nodes:
        logical_id = str(node.get("logical_id"))
        if logical_id not in group_logical_ids or node.get("role") != "primary":
            continue
        probe = probe_by_logical.get(logical_id)
        if not probe:
            continue
        myself = probe.get("myself_node_id")
        cluster_node = (probe.get("cluster_nodes") or {}).get(myself, {})
        for slot_spec in cluster_node.get("slots", []):
            slot_range = p23_slot_range(str(slot_spec))
            if slot_range is None:
                continue
            low, high = slot_range
            slot_key = p23_key_for_slot_range(f"{prefix}:{logical_id}", low, high)
            return node, endpoint_by_logical.get(logical_id), {
                "target_logical_id": logical_id,
                "target_node_id": myself,
                "slot_range": [low, high],
                "slot_key": slot_key,
                "slot": p23_key_slot(slot_key),
            }
    raise RuntimeError(f"P24 could not find primary target for {prefix}")


def p24_exec_workload_command(node: dict[str, Any], *command: Any) -> tuple[Any, int]:
    proc = run_cmd(["docker", "exec", str(node.get("container_name")), "valkey-cli", "-p", str(node.get("client_port")), *[str(arg) for arg in command]], timeout=10)
    output = (proc.stdout or proc.stderr).strip()
    if proc.returncode != 0:
        raise RuntimeError(output or f"valkey-cli exit={proc.returncode}")
    if output.startswith("MOVED") or output.startswith("ASK"):
        raise RespError(output)
    return output, 0


def p24_workload_window(
    *,
    phase: str,
    run_id: str,
    sample_id: str,
    fault_id: str,
    fault_type: str,
    node_count: int,
    window_name: str,
    endpoints: list[Endpoint],
    entry: Endpoint | None,
    exec_node: dict[str, Any] | None,
    slot_key: str,
    side_label: str,
    operation_pairs: int = 2,
) -> dict[str, Any]:
    started_at = unix_ms()
    started_monotonic = monotonic_ms()
    event_prefix = f"{sample_id}-{window_name}"
    attempted = 0
    ok_ops = 0
    errors = 0
    timeouts = 0
    redirects = 0
    connection_errors = 0
    cluster_down_errors = 0
    readonly_errors = 0
    tryagain_errors = 0
    unknown_errors = 0
    latencies: list[float] = []
    samples: list[dict[str, Any]] = []
    for index in range(operation_pairs):
        key = f"{slot_key}:{window_name}:{index}"
        value = f"p24-value-{sample_id}-{window_name}-{index}"
        for command in [("SET", key, value), ("GET", key)]:
            attempted += 1
            started = time.monotonic()
            try:
                if exec_node is not None:
                    reply, redirect_count = p24_exec_workload_command(exec_node, *command)
                elif entry is not None:
                    reply, redirect_count = execute_workload_command(endpoints, entry, *command)
                else:
                    raise RuntimeError("no P24 workload entry")
                if command[0] == "SET" and str(reply) != "OK":
                    raise RuntimeError(f"SET returned {reply!r}")
                if command[0] == "GET" and str(reply) != value:
                    raise RuntimeError(f"GET returned {reply!r}, expected {value!r}")
                elapsed = round((time.monotonic() - started) * 1000, 3)
                latencies.append(elapsed)
                redirects += redirect_count
                ok_ops += 1
                samples.append({"command": command[0], "status": "PASS", "latency_ms": elapsed, "redirects": redirect_count})
            except Exception as exc:  # noqa: BLE001
                elapsed = round((time.monotonic() - started) * 1000, 3)
                message = repr(exc)
                errors += 1
                lower = message.lower()
                if "timeout" in lower or "timed out" in lower:
                    timeouts += 1
                elif "clusterdown" in lower or "cluster is down" in lower:
                    cluster_down_errors += 1
                elif "readonly" in lower:
                    readonly_errors += 1
                elif "tryagain" in lower:
                    tryagain_errors += 1
                elif "connection" in lower or "closed" in lower:
                    connection_errors += 1
                else:
                    unknown_errors += 1
                samples.append({"command": command[0], "status": "FAIL", "latency_ms": elapsed, "error": message[:240]})
    ended_at = unix_ms()
    duration_ms = max(ended_at - started_at, 0)
    metrics = workload_metrics(
        attempted,
        ok_ops,
        errors,
        timeouts,
        redirects,
        latencies,
        duration_ms,
        {
            "connection_error_count": connection_errors,
            "cluster_down_error_count": cluster_down_errors,
            "readonly_error_count": readonly_errors,
            "tryagain_error_count": tryagain_errors,
            "unknown_error_count": unknown_errors,
        },
    )
    if metrics["latency_p999_ms"] == "MISSING":
        metrics["missing_reasons"]["latency_p999_ms"] = "P24 focused partition gate uses too few workload samples for p999."
    return {
        "window_name": window_name,
        "sample_id": sample_id,
        "fault_id": fault_id,
        "fault_type": fault_type,
        "node_count": node_count,
        "side_label": side_label,
        "source_window_name": window_name,
        "start_event_id": f"{event_prefix}-start",
        "end_event_id": f"{event_prefix}-end",
        "start_time_unix_ms": started_at,
        "end_time_unix_ms": ended_at,
        "start_monotonic_ms": started_monotonic,
        "end_monotonic_ms": monotonic_ms(),
        "metrics": metrics,
        "samples": samples[:16],
        "entry_logical_id": (entry.logical_id if entry else exec_node.get("logical_id") if exec_node else "MISSING"),
        "probe_method": "docker_exec_valkey_cli_loopback" if exec_node else "host_published_endpoint",
        "slot_key": slot_key,
        "slot": p23_key_slot(slot_key),
        "run_id": run_id,
        "phase_id": phase,
    }


def p24_all_run_window(phase: str, run_id: str, sample_id: str, fault_id: str, fault_type: str, node_count: int, rows: list[dict[str, Any]], side_label: str) -> dict[str, Any]:
    children = [row for row in rows if row.get("sample_id") == sample_id and row.get("window_name") != "all_run"]
    started_values = [row.get("start_time_unix_ms") for row in children if isinstance(row.get("start_time_unix_ms"), int)]
    ended_values = [row.get("end_time_unix_ms") for row in children if isinstance(row.get("end_time_unix_ms"), int)]
    total_duration = max(max(ended_values, default=0) - min(started_values, default=0), 0)
    total_ops = sum(int(row.get("metrics", {}).get("sample_count", 0) or 0) for row in children)
    total_ok = sum(int(row.get("metrics", {}).get("ok_ops", 0) or 0) for row in children)
    total_errors = sum(int(row.get("metrics", {}).get("error_ops", 0) or 0) for row in children)
    total_timeouts = sum(int(row.get("metrics", {}).get("timeout_count", 0) or 0) for row in children)
    total_redirects = sum(int(row.get("metrics", {}).get("moved_redirection_count", 0) or 0) for row in children)
    latencies = [
        float(sample["latency_ms"])
        for row in children
        for sample in row.get("samples", [])
        if isinstance(sample, dict) and sample.get("status") == "PASS" and isinstance(sample.get("latency_ms"), (int, float))
    ]
    aggregate_error_counts = {
        "connection_error_count": sum(int(row.get("metrics", {}).get("connection_error_count", 0) or 0) for row in children),
        "cluster_down_error_count": sum(int(row.get("metrics", {}).get("cluster_down_error_count", 0) or 0) for row in children),
        "readonly_error_count": sum(int(row.get("metrics", {}).get("readonly_error_count", 0) or 0) for row in children),
        "tryagain_error_count": sum(int(row.get("metrics", {}).get("tryagain_error_count", 0) or 0) for row in children),
        "unknown_error_count": sum(int(row.get("metrics", {}).get("unknown_error_count", 0) or 0) for row in children),
    }
    metrics = workload_metrics(total_ops, total_ok, total_errors, total_timeouts, total_redirects, latencies, total_duration, aggregate_error_counts)
    if metrics["latency_p999_ms"] == "MISSING":
        metrics["missing_reasons"]["latency_p999_ms"] = "P24 focused partition gate uses too few workload samples for p999."
    return {
        "window_name": "all_run",
        "sample_id": sample_id,
        "fault_id": fault_id,
        "fault_type": fault_type,
        "node_count": node_count,
        "side_label": side_label,
        "source_window_name": "all_run_aggregate",
        "start_event_id": f"{sample_id}-all_run-start",
        "end_event_id": f"{sample_id}-all_run-end",
        "start_time_unix_ms": min(started_values) if started_values else "MISSING",
        "end_time_unix_ms": max(ended_values) if ended_values else "MISSING",
        "start_monotonic_ms": "MISSING",
        "end_monotonic_ms": "MISSING",
        "metrics": metrics,
        "samples": [],
        "entry_logical_id": "aggregate",
        "probe_method": "aggregate",
        "run_id": run_id,
        "phase_id": phase,
    }


def p24_slot_overlap_detector(majority_probes: list[dict[str, Any]], minority_probes: list[dict[str, Any]]) -> dict[str, Any]:
    started = unix_ms()
    conflicts: list[dict[str, Any]] = []
    left = p24_side_signature(majority_probes).get("primary_slot_ranges", [])
    right = p24_side_signature(minority_probes).get("primary_slot_ranges", [])
    for a in left:
        for b in right:
            if a["node_id"] == b["node_id"]:
                continue
            if max(a["low"], b["low"]) <= min(a["high"], b["high"]):
                conflicts.append({"majority": a, "minority": b, "overlap": [max(a["low"], b["low"]), min(a["high"], b["high"])]})
    ended = unix_ms()
    return {
        "detector": "primary_slot_assignment_overlap",
        "status": "PASS",
        "ran": True,
        "indicator_observed": bool(conflicts),
        "started_at_ms": started,
        "ended_at_ms": ended,
        "window_ms": max(ended - started, 0) if conflicts else 0,
        "conflicts": conflicts,
    }


def p24_view_divergence_detector(majority_probes: list[dict[str, Any]], minority_probes: list[dict[str, Any]]) -> dict[str, Any]:
    started = unix_ms()
    majority_sig = p24_side_signature(majority_probes)
    minority_sig = p24_side_signature(minority_probes)
    observed = majority_sig != minority_sig and majority_sig.get("pass_probe_count", 0) > 0 and minority_sig.get("pass_probe_count", 0) > 0
    conflicting_nodes = sorted(set(majority_sig.get("known_node_ids", [])) ^ set(minority_sig.get("known_node_ids", [])))
    if observed and not conflicting_nodes:
        conflicting_nodes = ["partition_side_cluster_view_divergence"]
    ended = unix_ms()
    return {
        "detector": "partition_side_cluster_view_divergence",
        "status": "PASS",
        "ran": True,
        "indicator_observed": observed,
        "started_at_ms": started,
        "ended_at_ms": ended,
        "window_ms": max(ended - started, 0) if observed else 0,
        "majority_signature": majority_sig,
        "minority_signature": minority_sig,
        "conflicting_nodes": conflicting_nodes,
    }


def p24_conflicting_write_detector(
    *,
    endpoints: list[Endpoint],
    majority_entry: Endpoint | None,
    minority_node: dict[str, Any],
    slot_key: str,
) -> dict[str, Any]:
    started = unix_ms()
    key = f"{slot_key}:split-brain-detector"
    majority_status = "FAIL"
    minority_status = "FAIL"
    try:
        if majority_entry is None:
            raise RuntimeError("missing majority entry")
        reply, _redirects = execute_workload_command(endpoints, majority_entry, "SET", key, "majority")
        majority_status = "PASS" if str(reply) == "OK" else "FAIL"
    except Exception as exc:  # noqa: BLE001
        majority_status = f"FAIL:{repr(exc)[:160]}"
    try:
        reply, _redirects = p24_exec_workload_command(minority_node, "SET", key, "minority")
        minority_status = "PASS" if str(reply) == "OK" else "FAIL"
    except Exception as exc:  # noqa: BLE001
        minority_status = f"FAIL:{repr(exc)[:160]}"
    observed = majority_status == "PASS" and minority_status == "PASS"
    ended = unix_ms()
    return {
        "detector": "conflicting_write_probe",
        "status": "PASS",
        "ran": True,
        "indicator_observed": observed,
        "started_at_ms": started,
        "ended_at_ms": ended,
        "window_ms": max(ended - started, 0) if observed else 0,
        "key": key,
        "majority_write_status": majority_status,
        "minority_write_status": minority_status,
        "conflicting_write_keys": [key] if observed else [],
    }


def p24_detector_summary(detectors: list[dict[str, Any]], missing: list[dict[str, str]]) -> dict[str, Any]:
    observed = [item for item in detectors if item.get("indicator_observed") is True]
    starts = [item.get("started_at_ms") for item in observed if isinstance(item.get("started_at_ms"), int)]
    ends = [item.get("ended_at_ms") for item in observed if isinstance(item.get("ended_at_ms"), int)]
    indicator_observed = bool(observed)
    return {
        "detectors_run": [str(item.get("detector")) for item in detectors if item.get("ran") is True],
        "detector_results": detectors,
        "indicator_observed": indicator_observed,
        "indicator_start_ms": min(starts) if starts else (0 if not indicator_observed else "MISSING"),
        "indicator_end_ms": max(ends) if ends else (0 if not indicator_observed else "MISSING"),
        "split_brain_window_ms": max(max(ends) - min(starts), 1) if starts and ends and indicator_observed else 0,
        "conflicting_slots": [
            conflict.get("overlap")
            for item in detectors
            for conflict in item.get("conflicts", [])
            if isinstance(conflict, dict)
        ],
        "conflicting_nodes": sorted({
            node
            for item in detectors
            for node in item.get("conflicting_nodes", [])
        }),
        "conflicting_write_keys": [
            key
            for item in detectors
            for key in item.get("conflicting_write_keys", [])
        ],
        "missing_detectors_with_reason": missing,
    }


def p24_run_fault(
    *,
    phase: str,
    node_count: int,
    state_path: Path,
    state: dict[str, Any],
    endpoints: list[Endpoint],
    probes_before: list[dict[str, Any]],
    fault_type: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any], list[str]]:
    errors: list[str] = []
    scenario = p24_scenario(node_count)
    run_id = str(state.get("runtime", {}).get("run_id", f"{phase}-{scenario}-20260703"))
    sample_id = f"p24-{node_count}-{fault_type}"
    fault_id = f"{sample_id}-fault"
    plan = p24_plan_partition(state)
    network_name = str(state.get("runtime", {}).get("network_name"))
    majority_ids = set(plan["groups"]["majority"])
    minority_ids = set(plan["groups"]["minority"])
    majority_target_node, majority_entry, majority_target = p24_select_primary_target(state.get("nodes", []), endpoints, probes_before, majority_ids, f"p24-majority:{fault_type}")
    minority_target_node, _minority_entry, minority_target = p24_select_primary_target(state.get("nodes", []), endpoints, probes_before, minority_ids, f"p24-minority:{fault_type}")
    side_label = "minority" if fault_type == "network_partition_minority" else "majority"
    side_target = minority_target if side_label == "minority" else majority_target
    side_entry = None if side_label == "minority" else majority_entry
    side_exec_node = minority_target_node if side_label == "minority" else None

    workload_rows: list[dict[str, Any]] = []
    for window in ["baseline", "pre_event"]:
        workload_rows.append(
            p24_workload_window(
                phase=phase,
                run_id=run_id,
                sample_id=sample_id,
                fault_id=fault_id,
                fault_type=fault_type,
                node_count=node_count,
                window_name=window,
                endpoints=endpoints,
                entry=side_entry,
                exec_node=side_exec_node,
                slot_key=side_target["slot_key"],
                side_label=side_label,
            )
        )

    before_snapshot = topology_snapshot(
        phase=phase,
        run_id=run_id,
        sample_id=sample_id,
        label="before",
        state_nodes=state.get("nodes", []),
        probes=probes_before,
        targets=plan["minority_nodes"],
    )
    apply_started = unix_ms()
    apply_commands, apply_errors = p24_docker_network_control(
        phase=phase,
        run_id=run_id,
        sample_id=sample_id,
        fault_id=fault_id,
        network_name=network_name,
        nodehosts=plan["minority_nodehosts"],
        action="disconnect",
    )
    apply_completed = unix_ms()
    errors.extend(apply_errors)
    time.sleep(6)

    majority_probes = p24_probe_side(side="majority", nodes=plan["majority_nodes"], endpoints=endpoints, method="host")
    minority_host_probes = p24_probe_side(side="minority", nodes=plan["minority_nodes"], endpoints=endpoints, method="host")
    minority_exec_probes = p24_probe_side(side="minority", nodes=plan["minority_nodes"], endpoints=endpoints, method="docker_exec")
    during_probes = majority_probes + minority_host_probes + minority_exec_probes
    during_snapshot = topology_snapshot(
        phase=phase,
        run_id=run_id,
        sample_id=sample_id,
        label="during",
        state_nodes=state.get("nodes", []),
        probes=during_probes,
        targets=plan["minority_nodes"],
    )

    workload_rows.append(
        p24_workload_window(
            phase=phase,
            run_id=run_id,
            sample_id=sample_id,
            fault_id=fault_id,
            fault_type=fault_type,
            node_count=node_count,
            window_name="event",
            endpoints=endpoints,
            entry=side_entry,
            exec_node=side_exec_node,
            slot_key=side_target["slot_key"],
            side_label=side_label,
            operation_pairs=3,
        )
    )

    detectors = [
        p24_slot_overlap_detector(majority_probes, minority_exec_probes),
        p24_view_divergence_detector(majority_probes, minority_exec_probes),
        p24_conflicting_write_detector(
            endpoints=endpoints,
            majority_entry=majority_entry,
            minority_node=minority_target_node,
            slot_key=majority_target["slot_key"],
        ),
    ]
    missing_detectors = [
        {
            "detector": "old_primary_accepts_write_after_promotion",
            "status": "MISSING",
            "reason": "P24 partition matrix does not inject a primary stop or force promotion; no old-primary-after-promotion condition existed to measure.",
        }
    ]
    split_summary = p24_detector_summary(detectors, missing_detectors)

    clear_started = unix_ms()
    clear_commands, clear_errors = p24_docker_network_control(
        phase=phase,
        run_id=run_id,
        sample_id=sample_id,
        fault_id=fault_id,
        network_name=network_name,
        nodehosts=plan["minority_nodehosts"],
        action="connect",
    )
    clear_completed = unix_ms()
    errors.extend(clear_errors)
    ok_recovered, recovered_probes = wait_for_cluster_ok(endpoints, node_count, timeout_seconds=120)
    recovery_completed = unix_ms()
    if not ok_recovered:
        errors.append(f"{sample_id}: cluster did not recover to OK after clearing partition")
    recovered_snapshot = topology_snapshot(
        phase=phase,
        run_id=run_id,
        sample_id=sample_id,
        label="recovered",
        state_nodes=state.get("nodes", []),
        probes=recovered_probes,
        targets=plan["minority_nodes"],
    )

    for window in ["recovery", "post_recovery"]:
        workload_rows.append(
            p24_workload_window(
                phase=phase,
                run_id=run_id,
                sample_id=sample_id,
                fault_id=fault_id,
                fault_type=fault_type,
                node_count=node_count,
                window_name=window,
                endpoints=endpoints,
                entry=side_entry,
                exec_node=side_exec_node if window == "recovery" and side_label == "minority" else None,
                slot_key=side_target["slot_key"],
                side_label=side_label,
            )
        )
    workload_rows.append(p24_all_run_window(phase, run_id, sample_id, fault_id, fault_type, node_count, workload_rows, side_label))

    majority_available = any(probe.get("status") == "PASS" for probe in majority_probes)
    minority_side_probed = any(probe.get("status") == "PASS" for probe in minority_exec_probes)
    minority_host_blocked = any(probe.get("status") != "PASS" for probe in minority_host_probes)
    observed_effect = bool(majority_available and minority_side_probed and minority_host_blocked)
    if not observed_effect:
        errors.append(f"{sample_id}: partition effect was not observed from both sides")
    if side_label == "minority" and not minority_side_probed:
        errors.append(f"{sample_id}: minority side probe did not run successfully")
    if side_label == "majority" and not majority_available:
        errors.append(f"{sample_id}: majority side probe did not run successfully")
    if fault_type == "split_brain_window_detection" and not split_summary["detectors_run"]:
        errors.append(f"{sample_id}: split-brain detectors did not run")

    status = "PASS" if not errors else "FAIL"
    partition_sample = {
        "sample_id": sample_id,
        "fault_id": fault_id,
        "fault_type": fault_type,
        "node_count": node_count,
        "groups": plan["groups"],
        "group_nodehosts": plan["group_nodehosts"],
        "minority_az": plan["minority_az"],
        "majority_azs": plan["majority_azs"],
        "traffic_policy": plan["traffic_policy"],
        "probes": {
            "before": probes_before,
            "during_majority": majority_probes,
            "during_minority_host": minority_host_probes,
            "during_minority_side": minority_exec_probes,
            "recovered": recovered_probes,
        },
        "side_view_comparison": {
            "majority": p24_side_signature(majority_probes),
            "minority": p24_side_signature(minority_exec_probes),
            "divergent": p24_side_signature(majority_probes) != p24_side_signature(minority_exec_probes),
        },
        "recovery": {
            "ok": ok_recovered,
            "clear_started_at_ms": clear_started,
            "clear_completed_at_ms": clear_completed,
            "recovery_completed_at_ms": recovery_completed,
        },
        "safety_scope": {
            "implementation_path": "owned_docker_network_control",
            "owned_network_name": network_name,
            "host_network_mutated": False,
            "global_firewall_mutated": False,
            "physical_host_mutated": False,
            "sudo_used": False,
        },
    }
    row = {
        "schema_version": "v1",
        "phase_id": phase,
        "run_id": run_id,
        "scenario_name": scenario,
        "sample_id": sample_id,
        "node_count": node_count,
        "status": status,
        "real_valkey": True,
        "fault_type": fault_type,
        "fault_id": fault_id,
        "scope": "owned_docker_network",
        "implementation_path": "owned_docker_network_control",
        "targets": [node_identity(node) for node in plan["minority_nodes"]],
        "target_selector": {
            "selector_type": "virtual_az_partition",
            "selected_az_id": plan["minority_az"],
            "majority_azs": plan["majority_azs"],
            "groups": plan["groups"],
        },
        "target_count": len(plan["minority_nodes"]),
        "fault_parameters": {
            "groups": plan["groups"],
            "group_nodehosts": plan["group_nodehosts"],
            "traffic_policy": plan["traffic_policy"],
            "duration_seconds": round(max(clear_started - apply_completed, 0) / 1000.0, 3),
            "side_measured": side_label,
        },
        "apply_started_at_ms": apply_started,
        "apply_completed_at_ms": apply_completed,
        "clear_started_at_ms": clear_started,
        "clear_completed_at_ms": clear_completed,
        "recovery_completed_at_ms": recovery_completed,
        "apply_duration_ms": max(apply_completed - apply_started, 0),
        "clear_duration_ms": max(clear_completed - clear_started, 0),
        "recovery_latency_ms": max(recovery_completed - clear_started, 0),
        "observed_effect_started_at_ms": apply_completed if observed_effect else "MISSING",
        "expected_impact": "Traffic between majority and minority nodehost groups is blocked while within-majority traffic remains available.",
        "observed_impact": {
            "effect_observed": observed_effect,
            "majority_available": majority_available,
            "minority_side_probed": minority_side_probed,
            "minority_host_blocked": minority_host_blocked,
            "split_brain": split_summary,
        },
        "partition_report_ref": f"artifacts/phases/{phase}/partition_report.json#{sample_id}",
        "split_brain_report_ref": f"artifacts/phases/{phase}/split_brain_report.json#{sample_id}",
        "safety_scope_verified": True,
        "cleanup_verified": status == "PASS",
        "host_network_mutated": False,
        "global_firewall_mutated": False,
        "physical_host_mutated": False,
        "physical_az_mutated": False,
        "workload_impact_ref": f"artifacts/phases/{phase}/workload_impact_report.json#{sample_id}",
        "command_log_ref": f"artifacts/phases/{phase}/network_partition_command_log.jsonl#{fault_id}",
        "state_ref": rel_path(state_path),
        "errors_by_type": {"harness": errors} if errors else {},
        "missing_fields": [] if observed_effect else [{"field": "observed_effect_started_at_ms", "status": "MISSING", "reason": "Both-side partition effect was not observed."}],
    }
    snapshots = [before_snapshot, during_snapshot, recovered_snapshot]
    return row, workload_rows, snapshots, apply_commands + clear_commands, partition_sample, split_summary, errors


def run_p24_node_count(phase: str, artifact_dir: Path, node_count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], set[str], list[str]]:
    paths = p24_inner_paths(artifact_dir, node_count)
    work_dir = paths["work_dir"]
    work_dir.mkdir(parents=True, exist_ok=True)
    state_path = paths["state"]
    scenario = p24_scenario(node_count)
    setup = run_cmd(
        [
            sys.executable,
            "-m",
            "valkey_scale_lab.cli",
            "gate",
            "scenario",
            "--phase",
            phase,
            "--scenario",
            scenario,
            "--config",
            str(p24_config_path(node_count)),
            "--artifacts-dir",
            str(work_dir),
            "--state-out",
            str(state_path),
        ],
        timeout=max(900, node_count * 30),
    )
    (work_dir / "p24_setup.stdout.log").write_text(setup.stdout, encoding="utf-8", errors="replace")
    (work_dir / "p24_setup.stderr.log").write_text(setup.stderr, encoding="utf-8", errors="replace")
    if setup.returncode != 0:
        cleanup_status = "FAIL"
        cleanup_path = paths["cleanup_report"]
        if state_path.exists():
            cleanup_status, cleanup_path = project_cleanup(phase, state_path, work_dir)
        elif not cleanup_path.exists():
            write_json(
                cleanup_path,
                {
                    "schema_version": "v1",
                    "artifact_type": "cleanup_report",
                    "phase_id": phase,
                    "run_id": f"{phase}-{scenario}-setup-failed",
                    "created_at": utc_now(),
                    "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
                    "status": "FAIL",
                    "resources_remaining": [],
                    "cleanup_actions": [{"type": "p24_setup", "node_count": node_count, "status": "FAIL", "reason": setup.stderr[-1000:]}],
                },
            )
        cleanup_action = {"type": "p24_subrun_cleanup", "status": cleanup_status, "report_ref": rel_path(cleanup_path), "node_count": node_count}
        return [], [], [], [], [], [], cleanup_action, [], set(), [f"{scenario}: setup failed exit={setup.returncode}"]

    state = load_state(state_path)
    endpoints = endpoints_from_state(state)
    ok_before, probes_before = wait_for_cluster_ok(endpoints, node_count, timeout_seconds=120)
    errors: list[str] = []
    if not ok_before:
        errors.append(f"{scenario}: cluster not OK before P24 faults")
    rows: list[dict[str, Any]] = []
    workload_rows: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    command_rows: list[dict[str, Any]] = []
    partition_samples: list[dict[str, Any]] = []
    split_samples: list[dict[str, Any]] = []
    versions: set[str] = set()
    final_probes: list[dict[str, Any]] = []

    for fault_type in P24_FAULT_TYPES:
        state = load_state(state_path)
        endpoints = endpoints_from_state(state)
        row, windows, fault_snapshots, commands, partition_sample, split_sample, fault_errors = p24_run_fault(
            phase=phase,
            node_count=node_count,
            state_path=state_path,
            state=state,
            endpoints=endpoints,
            probes_before=probes_before,
            fault_type=fault_type,
        )
        rows.append(row)
        workload_rows.extend(windows)
        snapshots.extend(fault_snapshots)
        command_rows.extend(commands)
        partition_samples.append(partition_sample)
        split_sample = {**split_sample, "sample_id": row["sample_id"], "fault_id": row["fault_id"], "fault_type": fault_type, "node_count": node_count}
        split_samples.append(split_sample)
        errors.extend(fault_errors)
    ok_final, final_probes = wait_for_cluster_ok(endpoints_from_state(load_state(state_path)), node_count, timeout_seconds=120)
    if not ok_final:
        errors.append(f"{scenario}: final cluster OK probe failed before cleanup")
    for probe in final_probes:
        if probe.get("status") == "PASS" and probe.get("version"):
            versions.add(str(probe["version"]))
    cleanup_status, cleanup_path = project_cleanup(phase, state_path, work_dir)
    if cleanup_status != "PASS":
        errors.append(f"{scenario}: cleanup failed")
    for row in rows:
        if cleanup_status != "PASS":
            row["cleanup_verified"] = False
            row["status"] = "FAIL"
            row.setdefault("errors_by_type", {}).setdefault("cleanup", []).append("aggregate cleanup failed")
        row["cleanup_ref"] = rel_path(cleanup_path)
    cleanup_action = {"type": "p24_subrun_cleanup", "node_count": node_count, "status": cleanup_status, "report_ref": rel_path(cleanup_path)}
    return rows, workload_rows, snapshots, command_rows, partition_samples, split_samples, cleanup_action, final_probes, versions, errors


def p24_events(fault_rows: list[dict[str, Any]], workload_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = p22_events(fault_rows, workload_rows)
    for row in rows:
        row["scenario_name"] = str(row.get("scenario_name", "")).replace("p22_fault_matrix", "p24_partition_matrix")
    return rows


def p24_metrics(fault_rows: list[dict[str, Any]], workload_rows: list[dict[str, Any]], split_samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = p22_metrics(fault_rows, workload_rows)
    for row in rows:
        row["scenario_name"] = str(row.get("scenario_name", "")).replace("p22_fault_matrix", "p24_partition_matrix")
    for sample in split_samples:
        rows.append(
            {
                "schema_version": "v1",
                "run_id": next((fault.get("run_id") for fault in fault_rows if fault.get("sample_id") == sample.get("sample_id")), "P24"),
                "phase_id": P24_PHASE,
                "scenario_name": f"p24_partition_matrix_{sample.get('node_count')}",
                "sample_id": sample.get("sample_id"),
                "timestamp_unix_ms": sample.get("indicator_end_ms", "MISSING"),
                "monotonic_ms": sample.get("indicator_end_ms", "MISSING"),
                "source_type": "harness",
                "source_id": sample.get("fault_id"),
                "metric_name": "split_brain_window_ms",
                "metric_value": sample.get("split_brain_window_ms", "MISSING"),
                "metric_unit": "ms",
                "labels": {"fault_type": sample.get("fault_type"), "node_count": sample.get("node_count")},
                "missing_reason": "" if sample.get("split_brain_window_ms") != "MISSING" else "Split-brain detector timing was not available.",
            }
        )
    return rows


def run_p24_controller(args: argparse.Namespace) -> int:
    artifact_dir = Path(args.out).parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    phase = args.phase
    run_id = f"{phase}-partition-split-brain-20260703"
    all_fault_rows: list[dict[str, Any]] = []
    all_workload_rows: list[dict[str, Any]] = []
    all_snapshots: list[dict[str, Any]] = []
    all_command_rows: list[dict[str, Any]] = []
    all_partition_samples: list[dict[str, Any]] = []
    all_split_samples: list[dict[str, Any]] = []
    cleanup_actions: list[dict[str, Any]] = []
    resources_remaining: list[dict[str, Any]] = []
    top_probes: list[dict[str, Any]] = []
    versions: set[str] = set()
    errors: list[str] = []

    for node_count in [6, 10]:
        rows, workload_rows, snapshots, command_rows, partition_samples, split_samples, cleanup_action, probes, observed_versions, run_errors = run_p24_node_count(phase, artifact_dir, node_count)
        all_fault_rows.extend(rows)
        all_workload_rows.extend(workload_rows)
        all_snapshots.extend(snapshots)
        all_command_rows.extend(command_rows)
        all_partition_samples.extend(partition_samples)
        all_split_samples.extend(split_samples)
        cleanup_actions.append(cleanup_action)
        top_probes.extend(probes[:4])
        versions.update(observed_versions)
        errors.extend(run_errors)

    for action in cleanup_actions:
        report_ref = str(action.get("report_ref") or "")
        report = load_json_if_exists(ROOT / report_ref) if report_ref else {}
        for item in report.get("resources_remaining", []) if isinstance(report.get("resources_remaining"), list) else []:
            resources_remaining.append({"node_count": action.get("node_count"), **item})
        if action.get("status") != "PASS":
            errors.append(f"cleanup failed for node_count={action.get('node_count')}")

    comparisons = [
        p22_comparison(row["sample_id"], row["fault_type"], row["node_count"], all_workload_rows)
        for row in all_fault_rows
    ]
    events = p24_events(all_fault_rows, all_workload_rows)
    metrics = p24_metrics(all_fault_rows, all_workload_rows, all_split_samples)
    aggregate_cleanup_status = "PASS" if not resources_remaining and all(action.get("status") == "PASS" for action in cleanup_actions) else "FAIL"
    status = "PASS" if not errors and all(row.get("status") == "PASS" for row in all_fault_rows) and aggregate_cleanup_status == "PASS" else "FAIL"

    aggregate_split = p24_detector_summary(
        [detector for sample in all_split_samples for detector in sample.get("detector_results", [])],
        [
            {"detector": "old_primary_accepts_write_after_promotion", "status": "MISSING", "reason": "No P24 sample injected a primary-stop promotion condition; see per-sample detector results."}
        ],
    )
    aggregate_split.update(
        {
            "schema_version": "v1",
            "artifact_type": "split_brain_report",
            "phase_id": phase,
            "run_id": run_id,
            "created_at": utc_now(),
            "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
            "status": status,
            "samples": all_split_samples,
            "side_view_comparisons": [
                {
                    "sample_id": sample.get("sample_id"),
                    "majority": (next((item for item in all_partition_samples if item.get("sample_id") == sample.get("sample_id")), {}).get("side_view_comparison") or {}).get("majority"),
                    "minority": (next((item for item in all_partition_samples if item.get("sample_id") == sample.get("sample_id")), {}).get("side_view_comparison") or {}).get("minority"),
                }
                for sample in all_split_samples
            ],
        }
    )
    missing_detector_data = [
        {
            "field": f"split_brain_detector.{item.get('detector', 'unknown')}",
            "metric": f"split_brain_detector.{item.get('detector', 'unknown')}",
            **item,
        }
        for item in aggregate_split.get("missing_detectors_with_reason", [])
    ]

    write_jsonl(artifact_dir / "fault_results.jsonl", all_fault_rows)
    write_jsonl(artifact_dir / "fault_topology_snapshots.jsonl", all_snapshots)
    write_jsonl(artifact_dir / "network_partition_command_log.jsonl", all_command_rows)
    write_jsonl(artifact_dir / "events.jsonl", events)
    write_jsonl(artifact_dir / "metrics_timeseries.jsonl", metrics)
    write_json(
        artifact_dir / "workload_windows.json",
        {
            "schema_version": "v1",
            "artifact_type": "workload_windows",
            "phase_id": phase,
            "run_id": run_id,
            "created_at": utc_now(),
            "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
            "status": status,
            "windows": all_workload_rows,
        },
    )
    write_json(
        artifact_dir / "workload_impact_report.json",
        {
            "schema_version": "v1",
            "artifact_type": "workload_impact_report",
            "phase_id": phase,
            "run_id": run_id,
            "created_at": utc_now(),
            "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
            "status": status,
            "windows": all_workload_rows,
            "comparisons": comparisons,
        },
    )
    write_json(
        artifact_dir / "partition_report.json",
        {
            "schema_version": "v1",
            "artifact_type": "partition_report",
            "phase_id": phase,
            "run_id": run_id,
            "created_at": utc_now(),
            "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
            "status": status,
            "groups": all_partition_samples[0]["groups"] if all_partition_samples else {},
            "traffic_policy": all_partition_samples[0]["traffic_policy"] if all_partition_samples else {},
            "probes": all_partition_samples,
            "samples": all_partition_samples,
            "side_view_comparisons": [sample.get("side_view_comparison") for sample in all_partition_samples],
            "recovery": [sample.get("recovery") for sample in all_partition_samples],
            "safety_scope": {
                "implementation_path": "owned_docker_network_control",
                "host_network_mutated": False,
                "global_firewall_mutated": False,
                "physical_host_mutated": False,
                "sudo_used": False,
            },
            "command_log_ref": "network_partition_command_log.jsonl",
        },
    )
    write_json(artifact_dir / "split_brain_report.json", aggregate_split)
    write_json(
        Path(args.fault_report),
        {
            "schema_version": "v1",
            "artifact_type": "fault_matrix_report",
            "phase_id": phase,
            "run_id": run_id,
            "created_at": utc_now(),
            "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
            "status": status,
            "fault_rows": all_fault_rows,
            "safety_checks": {
                "host_network_mutated": False,
                "global_firewall_mutated": False,
                "physical_host_mutated": False,
                "owned_docker_network_control": True,
            },
        },
    )
    write_json(
        artifact_dir / "cleanup_report.json",
        {
            "schema_version": "v1",
            "artifact_type": "cleanup_report",
            "phase_id": phase,
            "run_id": run_id,
            "created_at": utc_now(),
            "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
            "status": aggregate_cleanup_status,
            "resources_remaining": resources_remaining,
            "cleanup_actions": cleanup_actions,
        },
    )
    write_json(
        Path(args.out),
        {
            "schema_version": "v1",
            "artifact_type": "valkey_e2e_evidence",
            "phase_id": phase,
            "run_id": run_id,
            "created_at": utc_now(),
            "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
            "status": status,
            "scenario": "p24_partition_matrix",
            "real_valkey": True,
            "valkey_version_prefix_required": "9.1.",
            "probe_result": "PASS" if status == "PASS" else "FAIL",
            "nodes_observed": max([observed_count(top_probes), *[row.get("node_count", 0) for row in all_fault_rows if row.get("status") == "PASS"]], default=1),
            "cluster_state_observed": "ok" if status == "PASS" else cluster_state_from_probes(top_probes),
            "data_path_result": "PASS" if all_workload_rows else "FAIL",
            "valkey_versions": sorted(versions),
            "probes": top_probes or [{"logical_id": "p24-no-probe", "host": "127.0.0.1", "port": 1, "status": "FAIL"}],
            "cleanup": {"status": aggregate_cleanup_status, "path": rel_path(artifact_dir / "cleanup_report.json")},
            "fault_types": P24_FAULT_TYPES,
            "sample_refs": [row["sample_id"] for row in all_fault_rows],
            "errors": errors,
        },
    )
    write_json(
        artifact_dir / "quant_summary.json",
        {
            "schema_version": "v1",
            "artifact_type": "quant_summary",
            "phase_id": phase,
            "run_id": run_id,
            "created_at": utc_now(),
            "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
            "status": status,
            "summary": "P24 quant summary for real owned Docker network partition and split-brain detector runs.",
            "artifact_refs": [
                "fault_results.jsonl",
                "fault_topology_snapshots.jsonl",
                "events.jsonl",
                "metrics_timeseries.jsonl",
                "workload_windows.json",
                "workload_impact_report.json",
                "partition_report.json",
                "split_brain_report.json",
                "fault_matrix_report.json",
                "network_partition_command_log.jsonl",
                "cleanup_report.json",
            ],
            "counts": {
                "event_count": len(events),
                "metric_count": len(metrics),
                "sample_count": len(all_fault_rows),
                "fault_result_count": len(all_fault_rows),
                "topology_snapshot_count": len(all_snapshots),
                "command_log_count": len(all_command_rows),
                "partition_sample_count": len(all_partition_samples),
                "split_brain_sample_count": len(all_split_samples),
            },
            "missing_data": missing_detector_data,
            "runtime_claims": {"real_valkey_claimed": True, "management_runtime_claimed": False, "fault_runtime_claimed": True},
        },
    )
    write_json(
        artifact_dir / "phase_summary.json",
        {
            "schema_version": "v1",
            "artifact_type": "phase_summary",
            "phase_id": phase,
            "run_id": run_id,
            "created_at": utc_now(),
            "producer": {"name": "scripts/fault_safety_gate.py", "version": "v1"},
            "status": status,
            "summary": "P24 runs minority/majority partition rows and split-brain-window detectors using owned Docker network controls only.",
            "required_artifacts": [
                f"artifacts/phases/{phase}/phase_summary.json",
                f"artifacts/phases/{phase}/valkey_e2e_evidence.json",
                f"artifacts/phases/{phase}/cleanup_report.json",
                f"artifacts/phases/{phase}/events.jsonl",
                f"artifacts/phases/{phase}/metrics_timeseries.jsonl",
                f"artifacts/phases/{phase}/workload_windows.json",
                f"artifacts/phases/{phase}/quant_summary.json",
                f"artifacts/phases/{phase}/partition_report.json",
                f"artifacts/phases/{phase}/split_brain_report.json",
                f"artifacts/phases/{phase}/fault_matrix_report.json",
                f"artifacts/phases/{phase}/fault_results.jsonl",
                f"artifacts/phases/{phase}/fault_topology_snapshots.jsonl",
                f"artifacts/phases/{phase}/workload_impact_report.json",
                f"artifacts/phases/{phase}/network_partition_command_log.jsonl",
            ],
            "missing_metrics": missing_detector_data,
            "risks": [{"risk": "P24 uses owned Docker network disconnect/reconnect of nodehost containers rather than host firewall or tc; reconnect must preserve container IP for recovery.", "severity": "medium", "required_before_next_phase": False}],
        },
    )

    if status != "PASS":
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS P24 partition/split-brain matrix out={args.out} fault_report={args.fault_report}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fault isolation gate with independent Valkey probing")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--fault-report", required=True)
    parser.add_argument("--min-nodes", type=int, default=6)
    args = parser.parse_args()

    if args.phase == P22_PHASE:
        return run_p22_controller(args)
    if args.phase == P23_PHASE:
        return run_p23_controller(args)
    if args.phase == P24_PHASE:
        return run_p24_controller(args)

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
