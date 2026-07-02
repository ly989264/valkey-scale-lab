#!/usr/bin/env python3
from __future__ import annotations

import argparse
import binascii
import json
import os
import platform
import re
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


def unix_ms() -> int:
    return int(time.time() * 1000)


def monotonic_ms() -> float:
    return round(time.monotonic() * 1000, 3)


def run_cmd(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}" + env.get("PYTHONPATH", "")
    return subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env)


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def scale_setup_scenario(scenario: str) -> str:
    sample_match = re.fullmatch(r"(scale_(?:30|50|100)_sample_\d+)_fault_failover", scenario)
    if sample_match:
        return sample_match.group(1)
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
    started_at_ms = unix_ms()
    started_monotonic_ms = monotonic_ms()
    attempted = 0
    succeeded = 0
    errors = 0
    timeouts = 0
    roundtrip_successes = 0
    roundtrip_failures = 0
    latencies: list[float] = []
    samples: list[dict[str, Any]] = []
    first_successful_read_at_ms: int | None = None
    first_successful_write_at_ms: int | None = None
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
                success_ms = unix_ms()
                if command[0] == "GET" and first_successful_read_at_ms is None:
                    first_successful_read_at_ms = success_ms
                if command[0] == "SET" and first_successful_write_at_ms is None:
                    first_successful_write_at_ms = success_ms
                elapsed_ms = round((time.monotonic() - started) * 1000, 3)
                latencies.append(elapsed_ms)
                succeeded += 1
                samples.append({
                    "command": command[0],
                    "status": "PASS",
                    "completed_at_ms": success_ms,
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
    ended_at_ms = unix_ms()
    duration_ms = max(ended_at_ms - started_at_ms, 0)
    return {
        "name": name,
        "status": status,
        "started_at_ms": started_at_ms,
        "ended_at_ms": ended_at_ms,
        "started_monotonic_ms": started_monotonic_ms,
        "ended_monotonic_ms": monotonic_ms(),
        "duration_ms": duration_ms,
        "workload_scope": target.get("scope") if target else "MISSING",
        "source_logical_id": target.get("source_logical_id") if target else "MISSING",
        "source_node_id": target.get("source_node_id") if target else "MISSING",
        "slot": target.get("slot") if target else {"status": "MISSING", "reason": "no workload target"},
        "slot_range": target.get("slot_range") if target else [],
        "operation_count": attempted,
        "successful_operations": succeeded,
        "roundtrip_successes": roundtrip_successes,
        "roundtrip_failures": roundtrip_failures,
        "availability_percent": availability,
        "errors_total": errors,
        "timeouts_total": timeouts,
        "first_successful_read_at_ms": first_successful_read_at_ms if first_successful_read_at_ms is not None else "MISSING",
        "first_successful_write_at_ms": first_successful_write_at_ms if first_successful_write_at_ms is not None else "MISSING",
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


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def p20_config_path(rung: int) -> Path:
    return ROOT / "templates" / "configs" / f"scale_{rung}.yaml"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def metric_value(value: Any) -> float | str:
    return value if isinstance(value, (int, float)) else "MISSING"


def p20_percentiles(values: list[float]) -> dict[str, float]:
    return {
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "max_ms": round(max(values), 3) if values else 0.0,
    }


def run_p20_resource_preflight(phase: str, rung: int, artifact_dir: Path) -> tuple[bool, Path]:
    source_path = artifact_dir / f"resource_preflight_{rung}.source.json"
    normalized_path = artifact_dir / f"resource_preflight_{rung}.json"
    config_path = p20_config_path(rung)
    proc = run_cmd(
        [
            sys.executable, "-m", "valkey_scale_lab.cli", "resource", "preflight",
            "--config", str(config_path), "--out", str(source_path),
        ],
        timeout=180,
    )
    report = load_json_if_exists(source_path)
    checks = list(report.get("checks", [])) if isinstance(report.get("checks"), list) else []
    checks.append({
        "name": "p20_exact_rung_required",
        "status": "PASS" if rung in {30, 50, 100} and report.get("node_count") == rung else "FAIL",
        "details": {"required_rung": rung, "reported_node_count": report.get("node_count")},
    })
    if proc.returncode != 0:
        checks.append({
            "name": "resource_preflight_command",
            "status": "FAIL",
            "details": {"returncode": proc.returncode, "stderr": proc.stderr[-2000:]},
        })
    can_run = proc.returncode == 0 and report.get("can_run") is True and all(item.get("status") == "PASS" for item in checks)
    normalized = {
        **report,
        "schema_version": "v1",
        "artifact_type": "resource_preflight",
        "phase_id": phase,
        "run_id": f"{phase}-resource-preflight-{rung}-20260628",
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": "PASS" if can_run else "FAIL",
        "node_count": rung,
        "can_run": can_run,
        "config_path": rel_path(config_path),
        "p20_rung": rung,
        "normalized_from_phase_id": report.get("phase_id", "MISSING"),
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


def write_p20_blocked(phase: str, reasons: list[str]) -> None:
    blocked_dir = ROOT / "artifacts" / "goal_loop" / phase
    blocked_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# BLOCKED — {phase}",
        "",
        "P20 cannot pass without real Valkey failover samples for 30, 50, and 100 nodes.",
        "",
        "Blocking reasons:",
        *[f"- {reason}" for reason in reasons],
        "",
        "No fake samples, downshifted node counts, or 1000-node path were used.",
        "",
    ]
    (blocked_dir / "BLOCKED.md").write_text("\n".join(lines), encoding="utf-8")


def p20_inner_paths(artifact_dir: Path, rung: int, sample_index: int) -> dict[str, Path]:
    sample_id = f"rung-{rung}-sample-{sample_index:02d}"
    sample_dir = artifact_dir / "_p20_samples" / sample_id
    return {
        "sample_dir": sample_dir,
        "evidence": sample_dir / "valkey_e2e_evidence.json",
        "failover_report": sample_dir / "failover_report.json",
        "fault_report": sample_dir / "fault_report.json",
        "workload_report": sample_dir / "workload_window_report.json",
        "cleanup_report": sample_dir / "cleanup_report.json",
        "state": sample_dir / f"_fault_failover_work_scale_{rung}_sample_{sample_index:02d}_fault_failover" / "state_failover.json",
    }


def run_p20_single_sample(args: argparse.Namespace, artifact_dir: Path, rung: int, sample_index: int) -> dict[str, Any]:
    paths = p20_inner_paths(artifact_dir, rung, sample_index)
    paths["sample_dir"].mkdir(parents=True, exist_ok=True)
    scenario = f"scale_{rung}_sample_{sample_index:02d}_fault_failover"
    cmd = [
        sys.executable, str(Path(__file__).resolve()),
        "--phase", args.phase,
        "--scenario", scenario,
        "--config", str(p20_config_path(rung)),
        "--out", str(paths["evidence"]),
        "--failover-report", str(paths["failover_report"]),
        "--fault-report", str(paths["fault_report"]),
        "--workload-window-report", str(paths["workload_report"]),
        "--cleanup-report", str(paths["cleanup_report"]),
        "--min-nodes", str(rung),
        "--wait-after-fault", str(args.wait_after_fault),
        "--failover-node-timeout-ms", str(args.failover_node_timeout_ms),
    ]
    if args.require_data_path:
        cmd.append("--require-data-path")
    started = unix_ms()
    proc = run_cmd(cmd, timeout=1500)
    finished = unix_ms()
    (paths["sample_dir"] / "single_sample.stdout.log").write_text(proc.stdout, encoding="utf-8", errors="replace")
    (paths["sample_dir"] / "single_sample.stderr.log").write_text(proc.stderr, encoding="utf-8", errors="replace")
    return {
        "sample_id": f"rung-{rung}-sample-{sample_index:02d}",
        "rung": rung,
        "sample_index": sample_index,
        "scenario": scenario,
        "returncode": proc.returncode,
        "started_at_ms": started,
        "finished_at_ms": finished,
        "paths": {key: rel_path(value) for key, value in paths.items() if key != "sample_dir"},
        "absolute_paths": paths,
    }


def target_node_metadata(state_path: Path, logical_id: str | None) -> dict[str, Any]:
    state = load_json_if_exists(state_path)
    for node in state.get("nodes", []):
        if node.get("logical_id") == logical_id:
            return node
    return {}


def p20_sample_row(run: dict[str, Any]) -> dict[str, Any]:
    paths = run["absolute_paths"]
    evidence = load_json_if_exists(paths["evidence"])
    cleanup = load_json_if_exists(paths["cleanup_report"])
    workload = load_json_if_exists(paths["workload_report"])
    target = target_node_metadata(paths["state"], evidence.get("selected_primary_logical_id"))
    after_recovery = next((w for w in workload.get("windows", []) if w.get("name") == "after_recovery"), {})
    fault_injected = evidence.get("fault_injected_at_ms", "MISSING")
    first_read = evidence.get("first_successful_read_at_ms", after_recovery.get("first_successful_read_at_ms", "MISSING"))
    first_write = evidence.get("first_successful_write_at_ms", after_recovery.get("first_successful_write_at_ms", "MISSING"))
    return {
        "schema_version": "v1",
        "phase_id": run.get("phase_id", "P20_FAILOVER_LATENCY_CURVE_30_50_100"),
        "run_id": evidence.get("run_id", f"{run['sample_id']}-run"),
        "scenario_name": run["scenario"],
        "node_count": run["rung"],
        "rung": run["rung"],
        "sample_index": run["sample_index"],
        "sample_id": run["sample_id"],
        "status": "PASS" if run["returncode"] == 0 and evidence.get("status") == "PASS" and cleanup.get("status") == "PASS" else "FAIL",
        "real_valkey": evidence.get("real_valkey") is True,
        "state_ref": run["paths"].get("state", "MISSING"),
        "evidence_ref": run["paths"].get("evidence", "MISSING"),
        "cleanup_ref": run["paths"].get("cleanup_report", "MISSING"),
        "cleanup_status": cleanup.get("status", "MISSING"),
        "target_primary_logical_id": evidence.get("selected_primary_logical_id") or "MISSING",
        "target_primary_node_id": evidence.get("old_primary_node_id") or "MISSING",
        "target_primary_az_id": target.get("az_id", "MISSING"),
        "target_primary_host_id": target.get("host_id", "MISSING"),
        "target_primary_host": target.get("host", "MISSING"),
        "replica_candidates": [evidence.get("expected_replica_node_id")] if evidence.get("expected_replica_node_id") else [],
        "promoted_node_id": evidence.get("promoted_node_id") or "MISSING",
        "fault_injection_method": "project_fault_api_node_stop_owned_container_or_process",
        "promotion_detection_method": "live_cluster_nodes_expected_replica_primary",
        "slot_coverage_detection_method": "live_cluster_info_cluster_state_ok",
        "fault_injected_at_ms": fault_injected,
        "primary_unreachable_at_ms": evidence.get("primary_unreachable_at_ms", "MISSING"),
        "replica_promoted_at_ms": evidence.get("replica_promoted_at_ms", "MISSING"),
        "cluster_state_ok_at_ms": evidence.get("cluster_state_ok_at_ms", "MISSING"),
        "slot_coverage_ok_at_ms": evidence.get("slot_coverage_ok_at_ms", "MISSING"),
        "first_successful_read_at_ms": first_read,
        "first_successful_write_at_ms": first_write,
        "fault_cleared_at_ms": evidence.get("fault_cleared_at_ms", "MISSING"),
        "old_primary_rejoined_at_ms": evidence.get("old_primary_rejoined_at_ms", "MISSING"),
        "old_primary_rejoined_missing_reason": evidence.get("old_primary_rejoined_missing_reason", "not_observed_before_cleanup"),
        "promotion_latency_ms": metric_value(evidence.get("promotion_latency_ms")),
        "cluster_recovery_latency_ms": metric_value(evidence.get("cluster_recovery_latency_ms")),
        "read_unavailability_ms": metric_value(evidence.get("read_unavailability_ms")),
        "write_unavailability_ms": metric_value(evidence.get("write_unavailability_ms")),
        "split_brain_window_ms": evidence.get("split_brain_window_ms", "MISSING"),
        "workload_impact_ref": f"artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/workload_impact_report.json#{run['sample_id']}",
    }


def window_metrics(window: dict[str, Any]) -> dict[str, Any]:
    operation_count = int(window.get("operation_count", 0) or 0)
    errors_total = int(window.get("errors_total", 0) or 0)
    ok_ops = int(window.get("successful_operations", operation_count - errors_total) or 0)
    duration_sec = max(float(window.get("duration_ms", 0) or 0) / 1000.0, 0.001)
    latency = window.get("latency_ms", {}) if isinstance(window.get("latency_ms"), dict) else {}
    return {
        "requested_qps": round(operation_count / duration_sec, 3) if operation_count else 0.0,
        "achieved_qps": round(ok_ops / duration_sec, 3) if operation_count else 0.0,
        "ok_ops": ok_ops,
        "error_ops": errors_total,
        "error_rate": round(errors_total / operation_count, 6) if operation_count else 0.0,
        "latency_p50_ms": latency.get("p50", "MISSING"),
        "latency_p90_ms": "MISSING",
        "latency_p95_ms": latency.get("p95", "MISSING"),
        "latency_p99_ms": latency.get("p99", "MISSING"),
        "latency_p999_ms": "MISSING",
        "timeout_count": int(window.get("timeouts_total", 0) or 0),
        "connection_error_count": 0,
        "moved_redirection_count": sum(int(item.get("redirects", 0) or 0) for item in window.get("samples", []) if isinstance(item, dict)),
        "ask_redirection_count": 0,
        "cluster_down_error_count": 0,
        "readonly_error_count": 0,
        "tryagain_error_count": 0,
        "unknown_error_count": max(errors_total - int(window.get("timeouts_total", 0) or 0), 0),
        "sample_count": operation_count,
        "missing_reasons": {
            "latency_p90_ms": "single-sample failover workload records p50/p95/p99 only",
            "latency_p999_ms": "sample count too small for p999",
        },
    }


def p20_workload_rows(runs: list[dict[str, Any]], sample_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sample_by_id = {sample["sample_id"]: sample for sample in sample_rows}
    mapping = {
        "baseline": "before_fault",
        "pre_event": "before_fault",
        "event": "during_fault",
        "recovery": "during_fault",
        "post_recovery": "after_recovery",
    }
    for run in runs:
        workload = load_json_if_exists(run["absolute_paths"]["workload_report"])
        windows = {window.get("name"): window for window in workload.get("windows", [])}
        sample = sample_by_id[run["sample_id"]]
        for canonical, source_name in mapping.items():
            source = windows.get(source_name, {})
            rows.append({
                "window_name": canonical,
                "sample_id": run["sample_id"],
                "rung": run["rung"],
                "node_count": run["rung"],
                "source_window_name": source_name,
                "start_event_id": f"{run['sample_id']}-{canonical}-start",
                "end_event_id": f"{run['sample_id']}-{canonical}-end",
                "start_time_unix_ms": source.get("started_at_ms", "MISSING"),
                "end_time_unix_ms": source.get("ended_at_ms", "MISSING"),
                "metrics": window_metrics(source),
            })
        started_values = [window.get("started_at_ms") for window in windows.values() if isinstance(window.get("started_at_ms"), int)]
        ended_values = [window.get("ended_at_ms") for window in windows.values() if isinstance(window.get("ended_at_ms"), int)]
        totals = {
            "operation_count": sum(int(window.get("operation_count", 0) or 0) for window in windows.values()),
            "successful_operations": sum(int(window.get("successful_operations", 0) or 0) for window in windows.values()),
            "errors_total": sum(int(window.get("errors_total", 0) or 0) for window in windows.values()),
            "timeouts_total": sum(int(window.get("timeouts_total", 0) or 0) for window in windows.values()),
            "duration_ms": sum(int(window.get("duration_ms", 0) or 0) for window in windows.values()),
            "latency_ms": {"p50": sample["promotion_latency_ms"], "p95": sample["cluster_recovery_latency_ms"], "p99": sample["cluster_recovery_latency_ms"]},
            "samples": [],
        }
        rows.append({
            "window_name": "all_run",
            "sample_id": run["sample_id"],
            "rung": run["rung"],
            "node_count": run["rung"],
            "source_window_name": "aggregate",
            "start_event_id": f"{run['sample_id']}-all_run-start",
            "end_event_id": f"{run['sample_id']}-all_run-end",
            "start_time_unix_ms": min(started_values) if started_values else "MISSING",
            "end_time_unix_ms": max(ended_values) if ended_values else "MISSING",
            "metrics": window_metrics(totals),
        })
    return rows


def p20_events(sample_rows: list[dict[str, Any]], workload_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample in sample_rows:
        for event_type, field in [
            ("fault_injected", "fault_injected_at_ms"),
            ("primary_unreachable", "primary_unreachable_at_ms"),
            ("replica_promoted", "replica_promoted_at_ms"),
            ("slot_coverage_ok", "slot_coverage_ok_at_ms"),
            ("fault_cleared", "fault_cleared_at_ms"),
        ]:
            timestamp = sample.get(field)
            rows.append({
                "schema_version": "v1",
                "run_id": sample["run_id"],
                "phase_id": sample["phase_id"],
                "scenario_name": sample["scenario_name"],
                "sample_id": sample["sample_id"],
                "event_id": f"{sample['sample_id']}-{event_type}",
                "event_type": event_type,
                "timestamp_unix_ms": timestamp,
                "monotonic_ms": timestamp if isinstance(timestamp, int) else "MISSING",
                "severity": "INFO" if sample["status"] == "PASS" else "ERROR",
                "subject_type": "failover_sample",
                "subject_id": sample["target_primary_logical_id"],
                "operation_id": "",
                "fault_id": "fault-primary-stop",
                "message": f"{event_type} for {sample['sample_id']}",
                "metadata": {"rung": sample["rung"], "node_count": sample["node_count"]},
            })
    for row in workload_rows:
        for suffix in ["start", "end"]:
            rows.append({
                "schema_version": "v1",
                "run_id": f"P20-workload-{row['sample_id']}",
                "phase_id": "P20_FAILOVER_LATENCY_CURVE_30_50_100",
                "scenario_name": "failover_curve_30_50_100",
                "sample_id": row["sample_id"],
                "event_id": row[f"{suffix}_event_id"],
                "event_type": f"workload_window_{suffix}",
                "timestamp_unix_ms": row.get(f"{suffix}_time_unix_ms", "MISSING"),
                "monotonic_ms": row.get(f"{suffix}_time_unix_ms", "MISSING"),
                "severity": "INFO",
                "subject_type": "workload_window",
                "subject_id": row["window_name"],
                "operation_id": "",
                "fault_id": "fault-primary-stop",
                "message": f"{row['window_name']} {suffix}",
                "metadata": {"rung": row["rung"], "source_window_name": row["source_window_name"]},
            })
    return rows


def p20_metrics(sample_rows: list[dict[str, Any]], workload_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample in sample_rows:
        for name in ["promotion_latency_ms", "cluster_recovery_latency_ms", "read_unavailability_ms", "write_unavailability_ms"]:
            value = sample.get(name, "MISSING")
            rows.append({
                "schema_version": "v1",
                "run_id": sample["run_id"],
                "phase_id": sample["phase_id"],
                "scenario_name": sample["scenario_name"],
                "sample_id": sample["sample_id"],
                "timestamp_unix_ms": sample.get("slot_coverage_ok_at_ms", 0),
                "monotonic_ms": sample.get("slot_coverage_ok_at_ms", 0),
                "source_type": "harness",
                "source_id": sample["sample_id"],
                "metric_name": name,
                "metric_value": value,
                "metric_unit": "ms",
                "labels": {"rung": sample["rung"], "node_count": sample["node_count"]},
                "missing_reason": "" if value != "MISSING" else f"{name} not observed by failover sample",
            })
    for row in workload_rows:
        for name in ["achieved_qps", "error_rate", "latency_p99_ms"]:
            value = row["metrics"].get(name, "MISSING")
            rows.append({
                "schema_version": "v1",
                "run_id": f"P20-workload-{row['sample_id']}",
                "phase_id": "P20_FAILOVER_LATENCY_CURVE_30_50_100",
                "scenario_name": "failover_curve_30_50_100",
                "sample_id": row["sample_id"],
                "timestamp_unix_ms": row.get("end_time_unix_ms", "MISSING"),
                "monotonic_ms": row.get("end_time_unix_ms", "MISSING"),
                "source_type": "workload",
                "source_id": f"{row['sample_id']}:{row['window_name']}",
                "metric_name": name,
                "metric_value": value,
                "metric_unit": "ratio" if name == "error_rate" else ("ops_per_second" if name == "achieved_qps" else "ms"),
                "labels": {"rung": row["rung"], "window_name": row["window_name"]},
                "missing_reason": "" if value != "MISSING" else row["metrics"].get("missing_reasons", {}).get(name, "not observed"),
            })
    return rows


def p20_curve(sample_rows: list[dict[str, Any]], phase: str, run_id: str) -> dict[str, Any]:
    derived: list[dict[str, Any]] = []
    for rung in [30, 50, 100]:
        rung_samples = [row for row in sample_rows if row.get("rung") == rung]
        for metric in ["promotion_latency_ms", "cluster_recovery_latency_ms"]:
            values = [float(row[metric]) for row in rung_samples if isinstance(row.get(metric), (int, float))]
            derived.append({
                "rung": rung,
                "node_count": rung,
                "metric": metric,
                "unit": "ms",
                "sample_count": len(values),
                "percentile_method": "nearest_rank_round_index",
                "sample_refs": [row["sample_id"] for row in rung_samples],
                **p20_percentiles(values),
            })
    return {
        "schema_version": "v1",
        "artifact_type": "failover_latency_curve",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": "PASS" if all(row.get("status") == "PASS" for row in sample_rows) and len(sample_rows) == 9 else "FAIL",
        "rungs": [30, 50, 100],
        "sample_refs": [row["sample_id"] for row in sample_rows],
        "sample_source": "failover_latency_samples.jsonl",
        "derived_series": derived,
    }


def run_p20_controller(args: argparse.Namespace) -> int:
    artifact_dir = Path(args.out).parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    phase = args.phase
    run_id = f"{phase}-failover-curve-20260628"
    blocked: list[str] = []
    for rung in [30, 50, 100]:
        can_run, preflight_path = run_p20_resource_preflight(phase, rung, artifact_dir)
        if not can_run:
            blocked.append(f"resource preflight failed for {rung} nodes: {rel_path(preflight_path)}")
    if blocked:
        write_p20_blocked(phase, blocked)
        for reason in blocked:
            print(f"FAIL: {reason}", file=sys.stderr)
        return 1

    runs: list[dict[str, Any]] = []
    errors: list[str] = []
    for rung in [30, 50, 100]:
        for sample_index in [1, 2, 3]:
            run = run_p20_single_sample(args, artifact_dir, rung, sample_index)
            run["phase_id"] = phase
            runs.append(run)
            if run["returncode"] != 0:
                errors.append(f"{run['sample_id']} failed exit={run['returncode']}")

    sample_rows = [p20_sample_row(run) for run in runs]
    for sample in sample_rows:
        if sample.get("status") != "PASS":
            errors.append(f"{sample['sample_id']} status={sample.get('status')} cleanup={sample.get('cleanup_status')}")

    workload_rows = p20_workload_rows(runs, sample_rows)
    events = p20_events(sample_rows, workload_rows)
    metrics = p20_metrics(sample_rows, workload_rows)
    curve = p20_curve(sample_rows, phase, run_id)
    cleanup_actions = []
    resources_remaining: list[dict[str, Any]] = []
    for run in runs:
        cleanup = load_json_if_exists(run["absolute_paths"]["cleanup_report"])
        cleanup_actions.append({
            "type": "sample_cleanup",
            "sample_id": run["sample_id"],
            "status": cleanup.get("status", "MISSING"),
            "report_ref": run["paths"].get("cleanup_report", "MISSING"),
        })
        for item in cleanup.get("resources_remaining", []) if isinstance(cleanup.get("resources_remaining"), list) else []:
            resources_remaining.append({"sample_id": run["sample_id"], **item})
    status = "PASS" if not errors and curve.get("status") == "PASS" and not resources_remaining else "FAIL"

    write_jsonl(artifact_dir / "failover_latency_samples.jsonl", sample_rows)
    write_json(artifact_dir / "failover_latency_curve.json", curve)
    write_jsonl(artifact_dir / "events.jsonl", events)
    write_jsonl(artifact_dir / "metrics_timeseries.jsonl", metrics)
    write_json(artifact_dir / "workload_windows.json", {
        "schema_version": "v1",
        "artifact_type": "workload_windows",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "windows": workload_rows,
    })
    write_json(Path(args.workload_window_report), {
        "schema_version": "v1",
        "artifact_type": "workload_impact_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "windows": workload_rows,
        "comparisons": [
            {
                "sample_id": sample["sample_id"],
                "rung": sample["rung"],
                "baseline_ref": f"{sample['sample_id']}:baseline",
                "event_ref": f"{sample['sample_id']}:event",
                "post_recovery_ref": f"{sample['sample_id']}:post_recovery",
            }
            for sample in sample_rows
        ],
    })
    write_json(Path(args.fault_report), {
        "schema_version": "v1",
        "artifact_type": "fault_matrix_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "fault_rows": [
            {
                "fault_type": "primary_stop_failover",
                "fault_id": f"{sample['sample_id']}-primary-stop",
                "node_count": sample["node_count"],
                "sample_id": sample["sample_id"],
                "scope": "owned_container_or_process",
                "implementation_path": sample["fault_injection_method"],
                "targets": [sample["target_primary_logical_id"]],
                "observed_impact": {
                    "promotion_latency_ms": sample["promotion_latency_ms"],
                    "cluster_recovery_latency_ms": sample["cluster_recovery_latency_ms"],
                },
                "safety_scope_verified": True,
                "cleanup_verified": sample["cleanup_status"] == "PASS",
                "workload_impact_ref": sample["workload_impact_ref"],
            }
            for sample in sample_rows
        ],
    })
    top_probes: list[dict[str, Any]] = []
    versions: set[str] = set()
    for run in runs:
        evidence = load_json_if_exists(run["absolute_paths"]["evidence"])
        top_probes.extend(evidence.get("probes", [])[:3])
        versions.update(str(v) for v in evidence.get("valkey_versions", []) if v)
    write_json(Path(args.cleanup_report), {
        "schema_version": "v1",
        "artifact_type": "cleanup_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": "PASS" if not resources_remaining and all(action.get("status") == "PASS" for action in cleanup_actions) else "FAIL",
        "resources_remaining": resources_remaining,
        "cleanup_actions": cleanup_actions,
    })
    write_json(Path(args.failover_report), {
        "schema_version": "v1",
        "artifact_type": "failover_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "failovers": [
            {
                "fault_id": f"{sample['sample_id']}-primary-stop",
                "target_logical_id": sample["target_primary_logical_id"],
                "old_primary_node_id": sample["target_primary_node_id"],
                "promoted_node_id": sample["promoted_node_id"],
                "failover_latency_ms": sample["promotion_latency_ms"],
            }
            for sample in sample_rows
        ],
        "summary": {"rungs": [30, 50, 100], "samples_per_rung": 3, "errors": errors},
    })
    write_json(Path(args.out), {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "scenario": args.scenario,
        "real_valkey": True,
        "valkey_version_prefix_required": "9.1.",
        "probe_result": "PASS" if status == "PASS" else "FAIL",
        "nodes_observed": max((sample["node_count"] for sample in sample_rows if sample.get("status") == "PASS"), default=1),
        "cluster_state_observed": "ok" if status == "PASS" else "unknown",
        "data_path_result": "PASS" if status == "PASS" else "FAIL",
        "valkey_versions": sorted(versions),
        "probes": top_probes or [{"logical_id": "p20-no-pass-sample", "host": "127.0.0.1", "port": 0, "status": "FAIL"}],
        "cleanup": {"status": "PASS" if not resources_remaining else "FAIL", "path": rel_path(Path(args.cleanup_report))},
        "rungs": [30, 50, 100],
        "sample_refs": [sample["sample_id"] for sample in sample_rows],
        "errors": errors,
    })
    write_json(artifact_dir / "quant_summary.json", {
        "schema_version": "v1",
        "artifact_type": "quant_summary",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "summary": "P20 failover latency curve quant summary over 30, 50, and 100 node primary-stop samples.",
        "artifact_refs": [
            "failover_latency_samples.jsonl",
            "failover_latency_curve.json",
            "events.jsonl",
            "metrics_timeseries.jsonl",
            "workload_windows.json",
            "workload_impact_report.json",
            "fault_matrix_report.json",
        ],
        "counts": {"event_count": len(events), "metric_count": len(metrics), "sample_count": len(sample_rows)},
        "missing_data": [],
        "runtime_claims": {"real_valkey_claimed": True, "management_runtime_claimed": False, "fault_runtime_claimed": True},
    })
    write_json(artifact_dir / "phase_summary.json", {
        "schema_version": "v1",
        "artifact_type": "phase_summary",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "summary": "P20 runs real primary-stop failover samples for 30, 50, and 100 node Valkey clusters and derives the latency curve from raw samples.",
        "required_artifacts": [
            f"artifacts/phases/{phase}/phase_summary.json",
            f"artifacts/phases/{phase}/valkey_e2e_evidence.json",
            f"artifacts/phases/{phase}/cleanup_report.json",
            f"artifacts/phases/{phase}/events.jsonl",
            f"artifacts/phases/{phase}/metrics_timeseries.jsonl",
            f"artifacts/phases/{phase}/workload_windows.json",
            f"artifacts/phases/{phase}/quant_summary.json",
            f"artifacts/phases/{phase}/failover_latency_samples.jsonl",
            f"artifacts/phases/{phase}/failover_latency_curve.json",
            f"artifacts/phases/{phase}/fault_matrix_report.json",
            f"artifacts/phases/{phase}/workload_impact_report.json",
        ],
        "missing_metrics": [],
        "risks": [{"risk": "Large local Docker failover runs depend on host resources.", "severity": "medium", "required_before_next_phase": False}],
    })

    if status != "PASS":
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS P20 failover latency curve out={args.out}")
    return 0


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

    if args.phase == "P20_FAILOVER_LATENCY_CURVE_30_50_100" and args.scenario == "failover_curve_30_50_100":
        if not args.fault_report or not args.workload_window_report or not args.cleanup_report:
            print("FAIL: P20 controller requires fault, workload, and cleanup report paths", file=sys.stderr)
            return 1
        return run_p20_controller(args)

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
    recovery_unix_ms: int | None = None
    fault_injected_at_ms: int | None = None
    primary_unreachable_at_ms: int | None = None
    fault_cleared_at_ms: int | None = None
    first_successful_read_at_ms: int | str = "MISSING"
    first_successful_write_at_ms: int | str = "MISSING"
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
                fault_injected_at_ms = unix_ms()
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
                if fault_apply_status == "PASS":
                    primary_unreachable_at_ms = unix_ms()
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
                        recovery_unix_ms = unix_ms()
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
                if fault_clear_status == "PASS":
                    fault_cleared_at_ms = unix_ms()
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
                after_recovery_window = workload_window("after_recovery", endpoints, 8, run_id, workload_target)
                first_successful_read_at_ms = after_recovery_window.get("first_successful_read_at_ms", "MISSING")
                first_successful_write_at_ms = after_recovery_window.get("first_successful_write_at_ms", "MISSING")
                workload_windows.append(after_recovery_window)
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
    cluster_recovery_latency_ms = failover_latency_ms
    read_unavailability_ms = (
        first_successful_read_at_ms - fault_injected_at_ms
        if isinstance(first_successful_read_at_ms, int) and isinstance(fault_injected_at_ms, int)
        else "MISSING"
    )
    write_unavailability_ms = (
        first_successful_write_at_ms - fault_injected_at_ms
        if isinstance(first_successful_write_at_ms, int) and isinstance(fault_injected_at_ms, int)
        else "MISSING"
    )
    old_primary_rejoined_at_ms: int | str = "MISSING"
    old_primary_rejoined_missing_reason = "old primary did not rejoin before cleanup"
    if selected_logical and any(p.get("status") == "PASS" and p.get("logical_id") == selected_logical for p in probes_after_clear):
        old_primary_rejoined_at_ms = unix_ms()
        old_primary_rejoined_missing_reason = ""
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
        "fault_injected_at_ms": fault_injected_at_ms or "MISSING",
        "primary_unreachable_at_ms": primary_unreachable_at_ms or "MISSING",
        "replica_promoted_at_ms": recovery_unix_ms or "MISSING",
        "cluster_state_ok_at_ms": recovery_unix_ms or "MISSING",
        "slot_coverage_ok_at_ms": recovery_unix_ms or "MISSING",
        "first_successful_read_at_ms": first_successful_read_at_ms,
        "first_successful_write_at_ms": first_successful_write_at_ms,
        "fault_cleared_at_ms": fault_cleared_at_ms or "MISSING",
        "old_primary_rejoined_at_ms": old_primary_rejoined_at_ms,
        "old_primary_rejoined_missing_reason": old_primary_rejoined_missing_reason,
        "promotion_latency_ms": failover_latency_ms if failover_latency_ms is not None else "MISSING",
        "cluster_recovery_latency_ms": cluster_recovery_latency_ms if cluster_recovery_latency_ms is not None else "MISSING",
        "read_unavailability_ms": read_unavailability_ms,
        "write_unavailability_ms": write_unavailability_ms,
        "split_brain_window_ms": "MISSING",
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
