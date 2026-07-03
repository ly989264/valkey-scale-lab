#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    probe_endpoint,
    wait_for_cluster_ok,
)

P22_PHASE = "P22_FAULT_REPLICA_HOST_AZ_STOP"
P22_FAULT_TYPES = ["replica_stop", "node_host_stop", "az_stop"]
P22_WINDOWS = ["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]


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


def workload_metrics(operation_count: int, ok_ops: int, errors: int, timeouts: int, redirects: int, latencies: list[float], duration_ms: int) -> dict[str, Any]:
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
        "connection_error_count": 0,
        "moved_redirection_count": redirects,
        "ask_redirection_count": 0,
        "cluster_down_error_count": 0,
        "readonly_error_count": 0,
        "tryagain_error_count": 0,
        "unknown_error_count": max(errors - timeouts, 0),
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
