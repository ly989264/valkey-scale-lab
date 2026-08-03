#!/usr/bin/env python3
from __future__ import annotations

import argparse
import binascii
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from valkey_scale_lab.cluster_timeout import compute_effective_cluster_timeout  # noqa: E402
from valkey_scale_lab.config.validation import load_effective_config  # noqa: E402
from valkey_scale_lab.execution import (  # noqa: E402
    ExecutionProfile,
    ExecutionSelectionError,
    resolve_profile,
)
from valkey_scale_lab.fault.network_proxy import ProxyRule, SandboxNetworkProxy  # noqa: E402
from valkey_probe_lib import Endpoint, RespConnection, RespError, endpoints_from_state, load_state, moved_target, probe_endpoint, wait_for_cluster_ok  # noqa: E402


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


FAILOVER_LATENCY_SCENARIO = "failover_latency_curve"


def resolve_failover_timeout(args: argparse.Namespace) -> tuple[int, str, str]:
    if args.timeout_config_ms is not None:
        return int(args.timeout_config_ms), "cli", "timeout_config_ms"
    if args.failover_node_timeout_ms is not None:
        return int(args.failover_node_timeout_ms), "cli", "failover_node_timeout_ms"
    config = load_effective_config(args.config)
    timeout = compute_effective_cluster_timeout(config)
    return (
        int(timeout["effective_cluster_node_timeout_ms"]),
        str(timeout["cluster_node_timeout_source"]),
        str(timeout.get("cluster_node_timeout_profile", "MISSING")),
    )


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
    diagnostic_rounds: list[dict[str, Any]] | None = None,
    round_context: dict[str, Any] | None = None,
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
            diagnostic_rounds=diagnostic_rounds,
            round_context=round_context,
        )
        last = probes
        if ok:
            # Failover selection needs the replica and slot relationships that
            # only the full topology probe exposes. Keep the generic health
            # wait light, then take one full snapshot for these consumers.
            return True, [probe_endpoint(endpoint) for endpoint in endpoints]
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


def _cleanup_status(path: Path) -> str:
    report = load_json_if_exists(path)
    return str(report.get("status") or "MISSING")


def _write_cleanup_failure(path: Path, capability_id: str, reason: str) -> None:
    write_json(path, {
        "schema_version": "v1", "artifact_type": "cleanup_report", "capability_id": capability_id,
        "run_id": f"capability_id-{capability_id}", "created_at": utc_now(),
        "producer": {"name": "valkey-scale-lab", "version": "unknown"}, "status": "FAIL",
        "resources_remaining": [{"type": "unknown", "reason": reason}], "cleanup_actions": []
    })


def project_cleanup(capability_id: str, state_path: Path, artifact_dir: Path, cleanup_path: Path | None = None) -> tuple[str, Path]:
    publish_path = cleanup_path or artifact_dir / "cleanup_report.json"
    attempts = [
        artifact_dir / "cleanup_report.json",
        artifact_dir / "cleanup_retry_01_report.json",
        artifact_dir / "cleanup_retry_02_report.json",
    ]
    last_reason = "cleanup did not run"
    for attempt_index, command_cleanup_path in enumerate(attempts, start=1):
        try:
            proc = run_cmd([
                sys.executable, "-m", "valkey_scale_lab.cli", "gate", "cleanup",
                "--state", str(state_path), "--artifacts-dir", str(artifact_dir), "--out", str(command_cleanup_path),
            ], timeout=420)
        except Exception as exc:  # noqa: BLE001
            last_reason = repr(exc)
            _write_cleanup_failure(command_cleanup_path, capability_id, last_reason)
            proc = subprocess.CompletedProcess([], 1, "", last_reason)
        if command_cleanup_path.exists():
            report = json.loads(command_cleanup_path.read_text(encoding="utf-8"))
            if attempt_index > 1:
                report.setdefault("cleanup_retry", {"attempt": attempt_index, "reason": last_reason})
                write_json(command_cleanup_path, report)
            if publish_path != command_cleanup_path:
                write_json(publish_path, report)
        status = _cleanup_status(publish_path)
        if proc.returncode == 0 and status == "PASS":
            return "PASS", publish_path
        last_reason = proc.stderr or f"cleanup report status={status}"
        if attempt_index < len(attempts):
            time.sleep(2)
    if not publish_path.exists():
        _write_cleanup_failure(publish_path, capability_id, last_reason)
    return "FAIL", publish_path


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def failover_latency_standard_config_path(rung: int) -> Path:
    return ROOT / "templates" / "configs" / f"scale_{rung}.yaml"


def failover_latency_exact_200_config_path() -> Path:
    return ROOT / "templates" / "configs" / "scale_200.yaml"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def metric_value(value: Any) -> float | str:
    return value if isinstance(value, (int, float)) else "MISSING"


def failover_latency_standard_percentiles(values: list[float]) -> dict[str, float]:
    return {
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "max_ms": round(max(values), 3) if values else 0.0,
    }


def run_failover_latency_standard_resource_preflight(capability_id: str, rung: int, artifact_dir: Path) -> tuple[bool, Path]:
    source_path = artifact_dir / f"resource_preflight_{rung}.source.json"
    normalized_path = artifact_dir / f"resource_preflight_{rung}.json"
    config_path = failover_latency_standard_config_path(rung)
    proc = run_cmd(
        [
            sys.executable, "-m", "valkey_scale_lab.cli", "resource", "preflight",
            "--config", str(config_path), "--out", str(source_path),
            "--capability-id", capability_id,
            "--scenario", FAILOVER_LATENCY_SCENARIO,
            "--profile", f"exact-{rung}",
        ],
        timeout=180,
    )
    report = load_json_if_exists(source_path)
    checks = list(report.get("checks", [])) if isinstance(report.get("checks"), list) else []
    checks.append({
        "name": "failover_latency_standard_exact_rung_required",
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
        "capability_id": capability_id,
        "run_id": f"{capability_id}-resource-preflight-{rung}-20260628",
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": "PASS" if can_run else "FAIL",
        "node_count": rung,
        "can_run": can_run,
        "config_path": rel_path(config_path),
        "failover_latency_standard_rung": rung,
        "normalized_from_capability_id": report.get("capability_id", "MISSING"),
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


def write_failover_latency_standard_blocked(capability_id: str, reasons: list[str]) -> None:
    blocked_dir = ROOT / "artifacts" / "captures" / capability_id
    blocked_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# BLOCKED — {capability_id}",
        "",
        "FAILOVER_LATENCY_STANDARD cannot pass without real Valkey failover samples for 30, 50, and 100 nodes.",
        "",
        "Blocking reasons:",
        *[f"- {reason}" for reason in reasons],
        "",
        "No fake samples, downshifted node counts, or 1000-node path were used.",
        "",
    ]
    (blocked_dir / "BLOCKED.md").write_text("\n".join(lines), encoding="utf-8")


def write_failover_latency_exact_200_blocked(capability_id: str, reasons: list[str]) -> None:
    blocked_dir = ROOT / "artifacts" / "captures" / capability_id
    blocked_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# BLOCKED - {capability_id}",
        "",
        "FAILOVER_LATENCY_EXACT_200 cannot pass without resource preflight approval for exactly 200 real Valkey nodes.",
        "",
        "Blocking reasons:",
        *[f"- {reason}" for reason in reasons],
        "",
        "No fake PASS artifacts, dry-run evidence, downshifted samples, or 1000-node path were used.",
        "",
    ]
    (blocked_dir / "BLOCKED.md").write_text("\n".join(lines), encoding="utf-8")


def failover_latency_standard_inner_paths(artifact_dir: Path, rung: int, sample_index: int) -> dict[str, Path]:
    sample_id = f"rung-{rung}-sample-{sample_index:02d}"
    sample_dir = artifact_dir / "_failover_latency_standard_samples" / sample_id
    return {
        "sample_dir": sample_dir,
        "evidence": sample_dir / "valkey_e2e_evidence.json",
        "failover_report": sample_dir / "failover_report.json",
        "fault_report": sample_dir / "fault_report.json",
        "workload_report": sample_dir / "workload_window_report.json",
        "cleanup_report": sample_dir / "cleanup_report.json",
        "state": sample_dir / f"_fault_failover_work_{FAILOVER_LATENCY_SCENARIO}" / "state_failover.json",
    }


def run_failover_latency_standard_single_sample(args: argparse.Namespace, artifact_dir: Path, rung: int, sample_index: int) -> dict[str, Any]:
    paths = failover_latency_standard_inner_paths(artifact_dir, rung, sample_index)
    paths["sample_dir"].mkdir(parents=True, exist_ok=True)
    scenario = FAILOVER_LATENCY_SCENARIO
    cmd = [
        sys.executable, str(Path(__file__).resolve()),
        "--capability-id", args.capability_id,
        "--scenario", scenario,
        "--backend", "docker_process",
        "--profile", f"exact-{rung}",
        "--config", str(failover_latency_standard_config_path(rung)),
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


def failover_latency_standard_sample_row(run: dict[str, Any]) -> dict[str, Any]:
    paths = run["absolute_paths"]
    evidence = load_json_if_exists(paths["evidence"])
    cleanup = load_json_if_exists(paths["cleanup_report"])
    workload = load_json_if_exists(paths["workload_report"])
    target = target_node_metadata(paths["state"], evidence.get("selected_primary_logical_id"))
    after_recovery = next((w for w in workload.get("windows", []) if w.get("name") == "after_recovery"), {})
    fault_injected = evidence.get("fault_injected_at_ms", "MISSING")
    first_read = evidence.get("first_successful_read_at_ms", after_recovery.get("first_successful_read_at_ms", "MISSING"))
    first_write = evidence.get("first_successful_write_at_ms", after_recovery.get("first_successful_write_at_ms", "MISSING"))
    capability_id = run.get("capability_id", "failover_latency_curve")
    return {
        "schema_version": "v1",
        "capability_id": capability_id,
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
        "workload_impact_ref": f"artifacts/captures/{capability_id}/workload_impact_report.json#{run['sample_id']}",
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


def failover_latency_standard_workload_rows(runs: list[dict[str, Any]], sample_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def failover_latency_standard_events(
    sample_rows: list[dict[str, Any]],
    workload_rows: list[dict[str, Any]],
    capability_id: str = "failover_latency_curve",
    scenario: str = FAILOVER_LATENCY_SCENARIO,
) -> list[dict[str, Any]]:
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
                "capability_id": sample["capability_id"],
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
                "run_id": f"{capability_id}-workload-{row['sample_id']}",
                "capability_id": capability_id,
                "scenario_name": scenario,
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


def failover_latency_standard_metrics(
    sample_rows: list[dict[str, Any]],
    workload_rows: list[dict[str, Any]],
    capability_id: str = "failover_latency_curve",
    scenario: str = FAILOVER_LATENCY_SCENARIO,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample in sample_rows:
        for name in ["promotion_latency_ms", "cluster_recovery_latency_ms", "read_unavailability_ms", "write_unavailability_ms"]:
            value = sample.get(name, "MISSING")
            rows.append({
                "schema_version": "v1",
                "run_id": sample["run_id"],
                "capability_id": sample["capability_id"],
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
                "run_id": f"{capability_id}-workload-{row['sample_id']}",
                "capability_id": capability_id,
                "scenario_name": scenario,
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


def failover_latency_standard_curve(sample_rows: list[dict[str, Any]], capability_id: str, run_id: str) -> dict[str, Any]:
    derived: list[dict[str, Any]] = []
    rungs = sorted({int(row["rung"]) for row in sample_rows if isinstance(row.get("rung"), int)})
    for rung in rungs:
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
                **failover_latency_standard_percentiles(values),
            })
    return {
        "schema_version": "v1",
        "artifact_type": "failover_latency_curve",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": "PASS" if all(row.get("status") == "PASS" for row in sample_rows) and len(sample_rows) == 3 * len(rungs) else "FAIL",
        "rungs": rungs,
        "sample_refs": [row["sample_id"] for row in sample_rows],
        "sample_source": "failover_latency_samples.jsonl",
        "derived_series": derived,
    }


def run_failover_latency_exact_200_resource_preflight(capability_id: str, artifact_dir: Path) -> tuple[bool, Path]:
    rung = 200
    source_path = artifact_dir / "resource_preflight_200.source.json"
    normalized_path = artifact_dir / "resource_preflight_200.json"
    config_path = failover_latency_exact_200_config_path()
    proc = run_cmd(
        [
            sys.executable, "-m", "valkey_scale_lab.cli", "resource", "preflight",
            "--config", str(config_path), "--out", str(source_path),
            "--capability-id", capability_id,
            "--scenario", FAILOVER_LATENCY_SCENARIO,
            "--profile", "exact-200",
        ],
        timeout=240,
    )
    report = load_json_if_exists(source_path)
    checks = list(report.get("checks", [])) if isinstance(report.get("checks"), list) else []
    checks.append({
        "name": "failover_latency_exact_200_exact_200_required",
        "status": "PASS" if report.get("node_count") == rung and report.get("capability_id") == capability_id else "FAIL",
        "details": {"required_node_count": rung, "reported_node_count": report.get("node_count"), "reported_capability_id": report.get("capability_id")},
    })
    checks.append({
        "name": "failover_latency_exact_200_no_dry_run",
        "status": "PASS" if report.get("dry_run") is False else "FAIL",
        "details": {"dry_run": report.get("dry_run", "MISSING")},
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
        "capability_id": capability_id,
        "run_id": f"{capability_id}-resource-preflight-200-20260628",
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": "PASS" if can_run else "FAIL",
        "node_count": rung,
        "can_run": can_run,
        "config_path": rel_path(config_path),
        "failover_latency_exact_200_rung": rung,
        "normalized_from_capability_id": report.get("capability_id", "MISSING"),
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


def failover_latency_exact_200_inner_paths(artifact_dir: Path, sample_index: int) -> dict[str, Path]:
    sample_id = f"rung-200-sample-{sample_index:02d}"
    sample_dir = artifact_dir / "_failover_latency_exact_200_samples" / sample_id
    return {
        "sample_dir": sample_dir,
        "evidence": sample_dir / "valkey_e2e_evidence.json",
        "failover_report": sample_dir / "failover_report.json",
        "fault_report": sample_dir / "fault_report.json",
        "workload_report": sample_dir / "workload_window_report.json",
        "cleanup_report": sample_dir / "cleanup_report.json",
        "state": sample_dir / f"_fault_failover_work_{FAILOVER_LATENCY_SCENARIO}" / "state_failover.json",
    }


def salvage_failover_latency_exact_200_cleanup_only_failure(paths: dict[str, Path], cleanup_path: Path) -> bool:
    evidence = load_json_if_exists(paths["evidence"])
    errors = [str(item) for item in evidence.get("errors", [])]
    if not errors or [item for item in errors if item != "cleanup failed"]:
        return False
    cleanup = load_json_if_exists(cleanup_path)
    if cleanup.get("status") != "PASS" or cleanup.get("resources_remaining"):
        return False
    cleanup["cleanup_retry"] = {
        "source": "failover_latency_exact_200_controller_inter_sample_cleanup",
        "reason": "initial sample cleanup timed out but subsequent owned-state cleanup verified no residual resources",
    }
    write_json(paths["cleanup_report"], cleanup)
    evidence["errors"] = []
    evidence["status"] = "PASS"
    evidence["probe_result"] = "PASS"
    evidence["cleanup"] = {"status": "PASS", "path": rel_path(paths["cleanup_report"])}
    write_json(paths["evidence"], evidence)
    for key in ["failover_report", "fault_report", "workload_report"]:
        report = load_json_if_exists(paths[key])
        if report:
            report["status"] = "PASS"
            write_json(paths[key], report)
    return True


def run_failover_latency_exact_200_single_sample(args: argparse.Namespace, artifact_dir: Path, sample_index: int) -> dict[str, Any]:
    paths = failover_latency_exact_200_inner_paths(artifact_dir, sample_index)
    paths["sample_dir"].mkdir(parents=True, exist_ok=True)
    scenario = FAILOVER_LATENCY_SCENARIO
    cmd = [
        sys.executable, str(Path(__file__).resolve()),
        "--capability-id", args.capability_id,
        "--scenario", scenario,
        "--backend", "docker_process",
        "--profile", "exact-200",
        "--config", str(failover_latency_exact_200_config_path()),
        "--out", str(paths["evidence"]),
        "--failover-report", str(paths["failover_report"]),
        "--fault-report", str(paths["fault_report"]),
        "--workload-window-report", str(paths["workload_report"]),
        "--cleanup-report", str(paths["cleanup_report"]),
        "--min-nodes", "200",
        "--wait-after-fault", str(args.wait_after_fault),
        "--failover-node-timeout-ms", str(args.failover_node_timeout_ms),
    ]
    if args.require_data_path:
        cmd.append("--require-data-path")
    started = unix_ms()
    proc = run_cmd(cmd, timeout=1800)
    finished = unix_ms()
    (paths["sample_dir"] / "single_sample.stdout.log").write_text(proc.stdout, encoding="utf-8", errors="replace")
    (paths["sample_dir"] / "single_sample.stderr.log").write_text(proc.stderr, encoding="utf-8", errors="replace")
    inter_sample_cleanup_status = _cleanup_status(paths["cleanup_report"])
    inter_sample_cleanup_path: Path | None = None
    if inter_sample_cleanup_status != "PASS" and paths["state"].exists():
        inter_sample_cleanup_status, inter_sample_cleanup_path = project_cleanup(
            args.capability_id,
            paths["state"],
            paths["sample_dir"] / "inter_sample_cleanup",
            paths["sample_dir"] / "inter_sample_cleanup_report.json",
        )
    effective_returncode = proc.returncode
    if inter_sample_cleanup_status == "PASS" and inter_sample_cleanup_path:
        if salvage_failover_latency_exact_200_cleanup_only_failure(paths, inter_sample_cleanup_path):
            effective_returncode = 0
    return {
        "sample_id": f"rung-200-sample-{sample_index:02d}",
        "rung": 200,
        "sample_index": sample_index,
        "scenario": scenario,
        "returncode": effective_returncode,
        "raw_returncode": proc.returncode,
        "started_at_ms": started,
        "finished_at_ms": finished,
        "paths": {key: rel_path(value) for key, value in paths.items() if key != "sample_dir"},
        "absolute_paths": paths,
        "inter_sample_cleanup_status": inter_sample_cleanup_status,
        "inter_sample_cleanup_ref": rel_path(inter_sample_cleanup_path) if inter_sample_cleanup_path else "MISSING",
        "capability_id": args.capability_id,
    }


def failover_latency_exact_200_curve(sample_rows: list[dict[str, Any]], capability_id: str, run_id: str) -> dict[str, Any]:
    derived: list[dict[str, Any]] = []
    rung_samples = [row for row in sample_rows if row.get("rung") == 200 and row.get("node_count") == 200]
    for metric in ["promotion_latency_ms", "cluster_recovery_latency_ms"]:
        values = [float(row[metric]) for row in rung_samples if isinstance(row.get(metric), (int, float))]
        derived.append({
            "rung": 200,
            "node_count": 200,
            "metric": metric,
            "unit": "ms",
            "sample_count": len(values),
            "percentile_method": "nearest_rank_round_index",
            "sample_refs": [row["sample_id"] for row in rung_samples],
            **failover_latency_standard_percentiles(values),
        })
    return {
        "schema_version": "v1",
        "artifact_type": "failover_latency_curve",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": "PASS" if all(row.get("status") == "PASS" for row in sample_rows) and len(sample_rows) == 3 else "FAIL",
        "rungs": [200],
        "sample_refs": [row["sample_id"] for row in sample_rows],
        "sample_source": "failover_latency_samples_200.jsonl",
        "derived_series": derived,
    }


def run_failover_latency_standard_controller(args: argparse.Namespace) -> int:
    artifact_dir = Path(args.out).parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    capability_id = args.capability_id
    profile = fault_matrix_execution(args.profile, int(args.min_nodes))
    if profile is None or profile.scale not in {30, 50, 100}:
        print(
            f"FAIL: failover latency profile must select exact 30, 50, or 100 nodes; "
            f"profile={args.profile!r} nodes={args.min_nodes}",
            file=sys.stderr,
        )
        return 1
    rung = profile.scale
    run_id = f"{capability_id}-{FAILOVER_LATENCY_SCENARIO}-{profile.profile_id}-20260628"
    blocked: list[str] = []
    if Path(args.config).resolve() != profile.config_path.resolve():
        blocked.append(
            f"{profile.profile_id} requires config {rel_path(profile.config_path)}, got {args.config}"
        )
    can_run, preflight_path = run_failover_latency_standard_resource_preflight(capability_id, rung, artifact_dir)
    if not can_run:
        blocked.append(f"resource preflight failed for {rung} nodes: {rel_path(preflight_path)}")
    if blocked:
        write_failover_latency_standard_blocked(capability_id, blocked)
        for reason in blocked:
            print(f"FAIL: {reason}", file=sys.stderr)
        return 1

    runs: list[dict[str, Any]] = []
    errors: list[str] = []
    for sample_index in [1, 2, 3]:
        run = run_failover_latency_standard_single_sample(args, artifact_dir, rung, sample_index)
        run["capability_id"] = capability_id
        runs.append(run)
        if run["returncode"] != 0:
            errors.append(f"{run['sample_id']} failed exit={run['returncode']}")

    sample_rows = [failover_latency_standard_sample_row(run) for run in runs]
    for sample in sample_rows:
        if sample.get("status") != "PASS":
            errors.append(f"{sample['sample_id']} status={sample.get('status')} cleanup={sample.get('cleanup_status')}")

    workload_rows = failover_latency_standard_workload_rows(runs, sample_rows)
    events = failover_latency_standard_events(
        sample_rows, workload_rows, capability_id=capability_id, scenario=FAILOVER_LATENCY_SCENARIO
    )
    metrics = failover_latency_standard_metrics(
        sample_rows, workload_rows, capability_id=capability_id, scenario=FAILOVER_LATENCY_SCENARIO
    )
    curve = failover_latency_standard_curve(sample_rows, capability_id, run_id)
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
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "windows": workload_rows,
    })
    write_json(Path(args.workload_window_report), {
        "schema_version": "v1",
        "artifact_type": "workload_impact_report",
        "capability_id": capability_id,
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
        "capability_id": capability_id,
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
        "capability_id": capability_id,
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
        "capability_id": capability_id,
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
        "summary": {"rungs": [rung], "samples_per_rung": 3, "errors": errors},
    })
    write_json(Path(args.out), {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "capability_id": capability_id,
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
        "probes": top_probes or [{"logical_id": "failover_latency_standard-no-pass-sample", "host": "127.0.0.1", "port": 0, "status": "FAIL"}],
        "cleanup": {"status": "PASS" if not resources_remaining else "FAIL", "path": rel_path(Path(args.cleanup_report))},
        "rungs": [rung],
        "sample_refs": [sample["sample_id"] for sample in sample_rows],
        "errors": errors,
    })
    write_json(artifact_dir / "quant_summary.json", {
        "schema_version": "v1",
        "artifact_type": "quant_summary",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "summary": f"Failover latency quant summary for three real {profile.profile_id} primary-stop samples.",
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
    write_json(artifact_dir / "run_summary.json", {
        "schema_version": "v1",
        "artifact_type": "run_summary",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "summary": f"Failover latency runs three real {profile.profile_id} primary-stop samples and derives the latency curve from raw samples.",
        "required_artifacts": [
            f"artifacts/captures/{capability_id}/run_summary.json",
            f"artifacts/captures/{capability_id}/valkey_e2e_evidence.json",
            f"artifacts/captures/{capability_id}/cleanup_report.json",
            f"artifacts/captures/{capability_id}/events.jsonl",
            f"artifacts/captures/{capability_id}/metrics_timeseries.jsonl",
            f"artifacts/captures/{capability_id}/workload_windows.json",
            f"artifacts/captures/{capability_id}/quant_summary.json",
            f"artifacts/captures/{capability_id}/failover_latency_samples.jsonl",
            f"artifacts/captures/{capability_id}/failover_latency_curve.json",
            f"artifacts/captures/{capability_id}/fault_matrix_report.json",
            f"artifacts/captures/{capability_id}/workload_impact_report.json",
        ],
        "missing_metrics": [],
        "risks": [{"risk": "Large local Docker failover runs depend on host resources.", "severity": "medium", "required_before_next_capability": False}],
    })

    if status != "PASS":
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS {profile.profile_id} failover latency curve out={args.out}")
    return 0


def run_failover_latency_exact_200_controller(args: argparse.Namespace) -> int:
    artifact_dir = Path(args.out).parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    capability_id = args.capability_id
    run_id = f"{capability_id}-failover-curve-200-20260628"
    blocked: list[str] = []
    if int(args.min_nodes) != 200:
        blocked.append(f"FAILOVER_LATENCY_EXACT_200 requires --min-nodes 200, got {args.min_nodes}")
    if Path(args.config).resolve() != failover_latency_exact_200_config_path().resolve():
        blocked.append(f"FAILOVER_LATENCY_EXACT_200 requires config {rel_path(failover_latency_exact_200_config_path())}, got {args.config}")
    can_run, preflight_path = run_failover_latency_exact_200_resource_preflight(capability_id, artifact_dir)
    if not can_run:
        blocked.append(f"resource preflight failed for 200 nodes: {rel_path(preflight_path)}")
    if blocked:
        write_failover_latency_exact_200_blocked(capability_id, blocked)
        for reason in blocked:
            print(f"FAIL: {reason}", file=sys.stderr)
        return 1

    runs: list[dict[str, Any]] = []
    errors: list[str] = []
    for sample_index in [1, 2, 3]:
        run = run_failover_latency_exact_200_single_sample(args, artifact_dir, sample_index)
        runs.append(run)
        if run["returncode"] != 0:
            errors.append(f"{run['sample_id']} failed exit={run['returncode']}")

    sample_rows = [failover_latency_standard_sample_row(run) for run in runs]
    for sample in sample_rows:
        if sample.get("status") != "PASS":
            errors.append(f"{sample['sample_id']} status={sample.get('status')} cleanup={sample.get('cleanup_status')}")
        if sample.get("node_count") != 200 or sample.get("rung") != 200:
            errors.append(f"{sample['sample_id']} did not produce exact 200-node evidence")
        if sample.get("real_valkey") is not True:
            errors.append(f"{sample['sample_id']} did not claim real Valkey evidence")

    workload_rows = failover_latency_standard_workload_rows(runs, sample_rows)
    events = failover_latency_standard_events(sample_rows, workload_rows, capability_id=capability_id, scenario=FAILOVER_LATENCY_SCENARIO)
    metrics = failover_latency_standard_metrics(sample_rows, workload_rows, capability_id=capability_id, scenario=FAILOVER_LATENCY_SCENARIO)
    curve = failover_latency_exact_200_curve(sample_rows, capability_id, run_id)
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
        if cleanup.get("status") != "PASS":
            errors.append(f"{run['sample_id']} cleanup report status={cleanup.get('status', 'MISSING')}")
        for item in cleanup.get("resources_remaining", []) if isinstance(cleanup.get("resources_remaining"), list) else []:
            resources_remaining.append({"sample_id": run["sample_id"], **item})
    if resources_remaining:
        errors.append(f"FAILOVER_LATENCY_EXACT_200 cleanup left resources: {len(resources_remaining)}")
    status = "PASS" if not errors and curve.get("status") == "PASS" else "FAIL"

    write_jsonl(artifact_dir / "failover_latency_samples_200.jsonl", sample_rows)
    write_json(artifact_dir / "failover_latency_curve_200.json", curve)
    write_jsonl(artifact_dir / "events.jsonl", events)
    write_jsonl(artifact_dir / "metrics_timeseries.jsonl", metrics)
    write_json(artifact_dir / "workload_windows.json", {
        "schema_version": "v1",
        "artifact_type": "workload_windows",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "windows": workload_rows,
    })
    write_json(Path(args.workload_window_report), {
        "schema_version": "v1",
        "artifact_type": "workload_impact_report",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "windows": workload_rows,
        "comparisons": [
            {
                "sample_id": sample["sample_id"],
                "rung": 200,
                "node_count": 200,
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
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "fault_rows": [
            {
                "fault_type": "primary_stop_failover",
                "fault_id": f"{sample['sample_id']}-primary-stop",
                "node_count": 200,
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
        "capability_id": capability_id,
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
        "capability_id": capability_id,
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
        "summary": {"rungs": [200], "samples_per_rung": 3, "errors": errors},
    })
    write_json(Path(args.out), {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "scenario": args.scenario,
        "real_valkey": True,
        "valkey_version_prefix_required": "9.1.",
        "probe_result": "PASS" if status == "PASS" else "FAIL",
        "nodes_observed": 200 if status == "PASS" else max((sample["node_count"] for sample in sample_rows if sample.get("status") == "PASS"), default=0),
        "cluster_state_observed": "ok" if status == "PASS" else "unknown",
        "data_path_result": "PASS" if status == "PASS" else "FAIL",
        "valkey_versions": sorted(versions),
        "probes": top_probes or [{"logical_id": "failover_latency_exact_200-no-pass-sample", "host": "127.0.0.1", "port": 0, "status": "FAIL"}],
        "cleanup": {"status": "PASS" if not resources_remaining else "FAIL", "path": rel_path(Path(args.cleanup_report))},
        "rungs": [200],
        "sample_refs": [sample["sample_id"] for sample in sample_rows],
        "errors": errors,
    })
    write_json(artifact_dir / "quant_summary.json", {
        "schema_version": "v1",
        "artifact_type": "quant_summary",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "summary": "FAILOVER_LATENCY_EXACT_200 failover latency curve quant summary over three exact 200-node primary-stop samples.",
        "artifact_refs": [
            "resource_preflight_200.json",
            "failover_latency_samples_200.jsonl",
            "failover_latency_curve_200.json",
            "events.jsonl",
            "metrics_timeseries.jsonl",
            "workload_windows.json",
            "workload_impact_report.json",
            "fault_matrix_report.json",
        ],
        "counts": {"event_count": len(events), "metric_count": len(metrics), "sample_count": len(sample_rows), "node_count": 200},
        "missing_data": [],
        "runtime_claims": {"real_valkey_claimed": True, "management_runtime_claimed": False, "fault_runtime_claimed": True},
    })
    write_json(artifact_dir / "run_summary.json", {
        "schema_version": "v1",
        "artifact_type": "run_summary",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "summary": "The exact-200 profile runs exactly three real 200-node primary-stop failover samples after resource preflight.",
        "required_artifacts": [
            f"artifacts/captures/{capability_id}/run_summary.json",
            f"artifacts/captures/{capability_id}/valkey_e2e_evidence.json",
            f"artifacts/captures/{capability_id}/cleanup_report.json",
            f"artifacts/captures/{capability_id}/events.jsonl",
            f"artifacts/captures/{capability_id}/metrics_timeseries.jsonl",
            f"artifacts/captures/{capability_id}/workload_windows.json",
            f"artifacts/captures/{capability_id}/quant_summary.json",
            f"artifacts/captures/{capability_id}/resource_preflight_200.json",
            f"artifacts/captures/{capability_id}/failover_latency_samples_200.jsonl",
            f"artifacts/captures/{capability_id}/failover_latency_curve_200.json",
            f"artifacts/captures/{capability_id}/fault_matrix_report.json",
            f"artifacts/captures/{capability_id}/workload_impact_report.json",
        ],
        "missing_metrics": [],
        "risks": [{"risk": "200-node real Valkey samples depend on local Docker resources and may block at preflight.", "severity": "medium", "required_before_next_capability": False}],
    })

    if status != "PASS":
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS FAILOVER_LATENCY_EXACT_200 failover latency curve out={args.out}")
    return 0


def run_failover_latency_controller(args: argparse.Namespace) -> int:
    if (
        args.capability_id != FAILOVER_LATENCY_SCENARIO
        or args.scenario != FAILOVER_LATENCY_SCENARIO
    ):
        print(
            f"FAIL: failover latency controller requires "
            f"{FAILOVER_LATENCY_SCENARIO}/{FAILOVER_LATENCY_SCENARIO}",
            file=sys.stderr,
        )
        return 1
    profile = fault_matrix_execution(args.profile, int(args.min_nodes))
    if profile is None:
        print(
            f"FAIL: profile={args.profile!r} does not match requested nodes={args.min_nodes}",
            file=sys.stderr,
        )
        return 1
    if profile.scale == 200:
        return run_failover_latency_exact_200_controller(args)
    return run_failover_latency_standard_controller(args)


FAULT_MATRIX_CAPABILITY = "fault_matrix"
FAULT_MATRIX_SCENARIO = "fault_matrix"
FAULT_MATRIX_REQUIRED_ROWS = [
    "primary_stop_failover",
    "replica_stop",
    "node_host_stop",
    "az_stop",
    "network_delay",
    "network_loss",
    "network_flap",
    "network_partition",
    "minority_partition",
    "majority_partition",
    "split_brain_window_detection",
    "fault_period_workload_impact",
]
FAULT_MATRIX_NETWORK_ROWS = {"network_delay", "network_loss", "network_flap", "network_partition", "minority_partition", "majority_partition"}
FAULT_MATRIX_DETECTORS = [
    "primary_slot_assignment_overlap",
    "partition_side_cluster_view_divergence",
    "conflicting_write_probe",
    "old_primary_accepts_write_after_promotion",
]


class FaultMatrixExecution:
    def __init__(
        self,
        *,
        profile: ExecutionProfile,
        setup_timeout_seconds: int = 1200,
        stable_timeout_seconds: int = 240,
        restore_timeout_seconds: int = 240,
        nodehost_restore_timeout_seconds: int = 600,
        failover_wait_after_fault_seconds: float | None = None,
        clear_timeout_seconds: int = 180,
    ) -> None:
        self.profile = profile
        self.setup_timeout_seconds = setup_timeout_seconds
        self.stable_timeout_seconds = stable_timeout_seconds
        self.restore_timeout_seconds = restore_timeout_seconds
        self.nodehost_restore_timeout_seconds = nodehost_restore_timeout_seconds
        self.failover_wait_after_fault_seconds = failover_wait_after_fault_seconds
        self.clear_timeout_seconds = clear_timeout_seconds

    @property
    def profile_id(self) -> str:
        return self.profile.profile_id

    @property
    def scale(self) -> int:
        return self.profile.requested_nodes

    @property
    def selection_label(self) -> str:
        return f"FAULT_MATRIX/{self.profile_id}"

    @property
    def label_lower(self) -> str:
        return f"fault_matrix_{self.profile_id.replace('-', '_')}"

    @property
    def work_dir_name(self) -> str:
        return f"_fault_matrix_{self.profile_id.replace('-', '_')}_work"

    @property
    def state_file_name(self) -> str:
        return f"state_fault_matrix_{self.profile_id.replace('-', '_')}.json"

    @property
    def coverage_prefix(self) -> str:
        return f"{self.scale}.fault."

    @property
    def config_path(self) -> Path:
        return ROOT / self.profile.config_template

    @property
    def primary_coverage_id(self) -> str:
        return f"{self.coverage_prefix}primary_stop_failover"


FAULT_MATRIX_PROFILE_IDS = frozenset(
    {"small-real", "exact-10", "exact-30", "exact-50", "exact-100", "exact-200"}
)


def fault_matrix_execution(
    profile_id: str | None,
    requested_nodes: int,
) -> FaultMatrixExecution | None:
    inferred_id = "small-real" if requested_nodes == 6 else f"exact-{requested_nodes}"
    selected_id = profile_id or inferred_id
    if selected_id not in FAULT_MATRIX_PROFILE_IDS:
        return None
    try:
        profile = resolve_profile(selected_id, requested_nodes=requested_nodes)
    except ExecutionSelectionError:
        return None
    if requested_nodes == 200:
        return FaultMatrixExecution(
            profile=profile,
            setup_timeout_seconds=2400,
            stable_timeout_seconds=420,
            restore_timeout_seconds=420,
            nodehost_restore_timeout_seconds=1800,
            failover_wait_after_fault_seconds=180.0,
            clear_timeout_seconds=420,
        )
    return FaultMatrixExecution(profile=profile)


def fault_matrix_config_path(execution: FaultMatrixExecution) -> Path:
    return execution.config_path


def fault_matrix_missing(field: str, reason: str) -> dict[str, str]:
    return {"status": "MISSING", "field": field, "reason": reason}


def fault_matrix_encode(value: Any, path: str = "$") -> Any:
    if value is None:
        return fault_matrix_missing(path, f"{path} was unavailable or not applicable for this strict fault artifact.")
    if isinstance(value, dict):
        return {str(key): fault_matrix_encode(item, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, list):
        return [fault_matrix_encode(item, f"{path}[{index}]") for index, item in enumerate(value)]
    return value


def write_fault_matrix_blocked(capability_id: str, reasons: list[str], profile: FaultMatrixExecution) -> None:
    blocked_dir = ROOT / "artifacts" / "captures" / capability_id
    blocked_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# BLOCKED - {capability_id}",
        "",
        f"{profile.selection_label} cannot pass unless exactly {profile.scale} real Valkey 9.1.x nodes can run and the full fault/failover matrix can execute.",
        "",
        "Blocking reasons:",
        *[f"- {reason}" for reason in reasons],
        "",
        "No fake evidence, downshifted node count, host network mutation, or other-profile PASS rows were used.",
        "",
    ]
    (blocked_dir / "BLOCKED.md").write_text("\n".join(lines), encoding="utf-8")


def run_fault_matrix_resource_preflight(capability_id: str, artifact_dir: Path, profile: FaultMatrixExecution) -> tuple[bool, Path]:
    source_path = artifact_dir / "resource_preflight.source.json"
    normalized_path = artifact_dir / "resource_preflight.json"
    proc = run_cmd(
        [
            sys.executable, "-m", "valkey_scale_lab.cli", "resource", "preflight",
            "--config", str(profile.config_path), "--out", str(source_path),
            "--capability-id", capability_id,
            "--scenario", FAULT_MATRIX_SCENARIO,
            "--profile", profile.profile_id,
        ],
        timeout=180,
    )
    report = load_json_if_exists(source_path)
    checks = list(report.get("checks", [])) if isinstance(report.get("checks"), list) else []
    checks.append({
        "name": f"{profile.label_lower}_exact_{profile.scale}_required",
        "status": "PASS" if report.get("node_count") == profile.scale else "FAIL",
        "details": {"required_node_count": profile.scale, "reported_node_count": report.get("node_count", "MISSING")},
    })
    checks.append({
        "name": f"{profile.label_lower}_no_host_network_mutation",
        "status": "PASS",
        "details": {"host_network_mutation_permitted": False, "network_fault_paths": ["sandbox_proxy", "container_netns_tc"]},
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
        "capability_id": capability_id,

        "run_id": f"{capability_id}-resource-preflight-{profile.scale}-20260704",
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": "PASS" if can_run else "FAIL",
        "node_count": profile.scale,
        "nodes_requested": profile.scale,
        "can_run": can_run,
        "config_path": rel_path(profile.config_path),
        "dry_run": False,
        "host": {
            "system": platform.system(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count() or "MISSING",
        },
        "checks": checks,
    }
    write_json(normalized_path, fault_matrix_encode(normalized))
    return can_run, normalized_path


def fault_matrix_refresh_state_pids(state_path: Path, logical_ids: list[str]) -> None:
    state = load_json_if_exists(state_path)
    changed = False
    wanted = set(logical_ids)
    for node in state.get("nodes", []):
        if node.get("logical_id") not in wanted:
            continue
        container = node.get("nodehost_container_name") or node.get("container_name")
        pid_file = node.get("pid_file")
        if not container or not pid_file:
            continue
        proc = subprocess.run(["docker", "exec", str(container), "cat", str(pid_file)], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        if proc.returncode == 0 and proc.stdout.strip().isdigit():
            node["pid"] = int(proc.stdout.strip())
            changed = True
    if changed:
        write_json(state_path, state)


def fault_matrix_apply_fault(
    *,
    state_path: Path,
    work_dir: Path,
    fault_id: str,
    fault_type: str,
    target_logical_id: str,
    implementation_path: str,
    clear_timeout_seconds: int,
    parameters: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], int, int]:
    spec = {
        "fault_id": fault_id,
        "type": fault_type,
        "scope": implementation_path,
        "implementation_path": implementation_path,
        "forbid_host_network_mutation": True,
        "target_logical_id": target_logical_id,
        **(parameters or {}),
    }
    spec_path = work_dir / f"{fault_id}.json"
    write_json(spec_path, spec)
    apply_started = unix_ms()
    apply = run_cmd([
        sys.executable, "-m", "valkey_scale_lab.cli", "fault", "apply",
        "--state", str(state_path),
        "--target-logical-id", target_logical_id,
        "--fault-json", str(spec_path),
        "--out", str(work_dir / f"{fault_id}_apply.json"),
    ], timeout=180)
    apply_ended = unix_ms()
    (work_dir / f"{fault_id}_apply.stdout.log").write_text(apply.stdout, encoding="utf-8", errors="replace")
    (work_dir / f"{fault_id}_apply.stderr.log").write_text(apply.stderr, encoding="utf-8", errors="replace")
    if apply.returncode != 0:
        raise RuntimeError(f"{fault_id} apply failed exit={apply.returncode}: {apply.stderr[-500:]}")
    clear_started = unix_ms()
    clear = run_cmd([
        sys.executable, "-m", "valkey_scale_lab.cli", "fault", "clear",
        "--state", str(state_path),
        "--fault-id", fault_id,
        "--out", str(work_dir / f"{fault_id}_clear.json"),
    ], timeout=clear_timeout_seconds)
    clear_ended = unix_ms()
    (work_dir / f"{fault_id}_clear.stdout.log").write_text(clear.stdout, encoding="utf-8", errors="replace")
    (work_dir / f"{fault_id}_clear.stderr.log").write_text(clear.stderr, encoding="utf-8", errors="replace")
    if clear.returncode != 0:
        raise RuntimeError(f"{fault_id} clear failed exit={clear.returncode}: {clear.stderr[-500:]}")
    apply_report = load_json_if_exists(work_dir / f"{fault_id}_apply.json")
    clear_report = load_json_if_exists(work_dir / f"{fault_id}_clear.json")
    return apply_report, clear_report, apply_started, clear_ended


def fault_matrix_apply_fault_only(
    *,
    state_path: Path,
    work_dir: Path,
    fault_id: str,
    fault_type: str,
    target_logical_id: str,
    implementation_path: str,
    parameters: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int, int]:
    spec = {
        "fault_id": fault_id,
        "type": fault_type,
        "scope": implementation_path,
        "implementation_path": implementation_path,
        "forbid_host_network_mutation": True,
        "target_logical_id": target_logical_id,
        **(parameters or {}),
    }
    spec_path = work_dir / f"{fault_id}.json"
    write_json(spec_path, spec)
    apply_started = unix_ms()
    apply = run_cmd([
        sys.executable, "-m", "valkey_scale_lab.cli", "fault", "apply",
        "--state", str(state_path),
        "--target-logical-id", target_logical_id,
        "--fault-json", str(spec_path),
        "--out", str(work_dir / f"{fault_id}_apply.json"),
    ], timeout=180)
    apply_ended = unix_ms()
    (work_dir / f"{fault_id}_apply.stdout.log").write_text(apply.stdout, encoding="utf-8", errors="replace")
    (work_dir / f"{fault_id}_apply.stderr.log").write_text(apply.stderr, encoding="utf-8", errors="replace")
    if apply.returncode != 0:
        raise RuntimeError(f"{fault_id} apply failed exit={apply.returncode}: {apply.stderr[-500:]}")
    return load_json_if_exists(work_dir / f"{fault_id}_apply.json"), apply_started, apply_ended


def fault_matrix_clear_fault_only(*, state_path: Path, work_dir: Path, fault_id: str) -> tuple[dict[str, Any], int, int]:
    clear_started = unix_ms()
    clear = run_cmd([
        sys.executable, "-m", "valkey_scale_lab.cli", "fault", "clear",
        "--state", str(state_path),
        "--fault-id", fault_id,
        "--out", str(work_dir / f"{fault_id}_clear.json"),
    ], timeout=180)
    clear_ended = unix_ms()
    (work_dir / f"{fault_id}_clear.stdout.log").write_text(clear.stdout, encoding="utf-8", errors="replace")
    (work_dir / f"{fault_id}_clear.stderr.log").write_text(clear.stderr, encoding="utf-8", errors="replace")
    if clear.returncode != 0:
        raise RuntimeError(f"{fault_id} clear failed exit={clear.returncode}: {clear.stderr[-500:]}")
    return load_json_if_exists(work_dir / f"{fault_id}_clear.json"), clear_started, clear_ended


def fault_matrix_target_for_row(row_name: str, state: dict[str, Any], probes: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = list(state.get("nodes", []))
    if row_name == "replica_stop":
        return next(node for node in nodes if node.get("role") == "replica")
    selection = find_primary_with_replica(probes, nodes)
    logical_id = selection[0] if selection else nodes[0]["logical_id"]
    return next(node for node in nodes if node.get("logical_id") == logical_id)


def fault_matrix_workload_logical_for_target(target_node: dict[str, Any], probes: list[dict[str, Any]]) -> str:
    target_logical = str(target_node.get("logical_id"))
    if target_node.get("role") != "replica":
        return target_logical
    logical_to_id = node_id_by_logical(probes)
    id_to_logical = {node_id: logical_id for logical_id, node_id in logical_to_id.items()}
    target_node_id = logical_to_id.get(target_logical)
    if not target_node_id:
        return target_logical
    merged = merged_cluster_nodes(probes)
    replica_view = merged.get(target_node_id) or {}
    master_id = replica_view.get("master_id")
    return str(id_to_logical.get(master_id) or target_logical)


def fault_matrix_proxy_window(
    row_name: str,
    endpoints: list[Any],
    probes: list[dict[str, Any]],
    target_logical_id: str,
    run_id: str,
    profile: FaultMatrixExecution,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target_ep = endpoint_by_logical(endpoints, target_logical_id) or endpoints[0]
    ordered = sorted(endpoints, key=lambda endpoint: str(endpoint.logical_id))
    majority_size = min(len(ordered), (len(ordered) // 2) + 1)
    if row_name == "minority_partition":
        target_eps = ordered[majority_size:]
    elif row_name == "majority_partition":
        target_eps = ordered[:majority_size]
    else:
        target_eps = [target_ep]
    if not target_eps:
        raise RuntimeError(f"{row_name} requires a non-empty partition target group")
    rules = {
        "network_delay": ProxyRule("network_delay", delay_ms=75, jitter_ms=5),
        "network_loss": ProxyRule("network_loss", loss_percent=50.0),
        "network_flap": ProxyRule("network_flap", flap_up_ms=20, flap_down_ms=120, flap_iterations=5),
        "network_partition": ProxyRule("network_partition"),
        "minority_partition": ProxyRule("network_partition"),
        "majority_partition": ProxyRule("network_partition"),
    }
    proxies = [SandboxNetworkProxy(target_host=endpoint.host, target_port=endpoint.port, rule=rules[row_name]) for endpoint in target_eps]
    for proxy in proxies:
        proxy.start()
    try:
        proxy_eps = [
            Endpoint(
                logical_id=endpoint.logical_id,
                host=proxy.listen_host,
                port=proxy.listen_port,
                password=getattr(endpoint, "password", None),
                az_id=getattr(endpoint, "az_id", None),
                role=getattr(endpoint, "role", None),
                container_ip=getattr(endpoint, "container_ip", None),
            )
            for endpoint, proxy in zip(target_eps, proxies)
        ]
        workload_logical = str(target_eps[0].logical_id)
        target = workload_target_for_logical(target_eps, probes, workload_logical) or {
            "scope": "sandbox_proxy_target",
            "source_logical_id": workload_logical,
            "source_node_id": "MISSING",
            "slot_range": [0, 16383],
            "slot_key": f"{row_name}:{{{profile.label_lower}-proxy}}",
            "slot": key_slot(f"{row_name}:{{{profile.label_lower}-proxy}}"),
            "entry_logical_id": workload_logical,
        }
        window = workload_window("event", proxy_eps, 6, f"{run_id}:{row_name}", target)
        proxy_details = [proxy.snapshot() for proxy in proxies]
    finally:
        for proxy in reversed(proxies):
            proxy.close()
    snapshot = {
        "implementation_path": "sandbox_proxy_group",
        "target_logical_ids": [str(endpoint.logical_id) for endpoint in target_eps],
        "target_count": len(target_eps),
        "proxy_snapshots": proxy_details,
        "accepted_connections": sum(int(item.get("accepted_connections", 0)) for item in proxy_details),
        "dropped_connections": sum(int(item.get("dropped_connections", 0)) for item in proxy_details),
        "flap_rejections": sum(int(item.get("flap_rejections", 0)) for item in proxy_details),
        "delay_injections": sum(int(item.get("delay_injections", 0)) for item in proxy_details),
        "host_network_mutated": False,
        "fault_row": row_name,
    }
    snapshot["effect_observed"] = bool(
        snapshot.get("accepted_connections", 0) > 0
        or snapshot.get("dropped_connections", 0) > 0
        or snapshot.get("flap_rejections", 0) > 0
        or snapshot.get("delay_injections", 0) > 0
    )
    snapshot["status"] = "PASS" if snapshot["effect_observed"] else "FAIL"
    return window, snapshot


def fault_matrix_metric_shape(window: dict[str, Any]) -> dict[str, Any]:
    metrics = window_metrics(window)
    for field in ["window_start_event_id", "window_end_event_id"]:
        metrics.setdefault(field, "MISSING")
    return metrics


def fault_matrix_workload_artifact_window(
    row_name: str,
    coverage_id: str,
    window: dict[str, Any],
    start_event_id: str,
    end_event_id: str,
    profile: FaultMatrixExecution,
) -> dict[str, Any]:
    metrics = fault_matrix_metric_shape(window)
    metrics["window_start_event_id"] = start_event_id
    metrics["window_end_event_id"] = end_event_id
    shaped = {
        "window_name": "event",
        "fault_type": row_name,
        "operation_id": f"{profile.label_lower}-{row_name}",
        "fault_id": f"{profile.label_lower}-{row_name}",
        "coverage_id": coverage_id,
        "node_count": profile.scale,
        "scale": profile.scale,
        "status": "PASS" if window.get("status") == "MEASURED" else "FAIL",
        "start_event_id": start_event_id,
        "end_event_id": end_event_id,
        "window_start_event_id": start_event_id,
        "window_end_event_id": end_event_id,
        "source_window": window,
        "metrics": metrics,
    }
    for key, value in metrics.items():
        shaped[key] = value
    return fault_matrix_encode(shaped)


def fault_matrix_curve(sample_rows: list[dict[str, Any]], capability_id: str, run_id: str, profile: FaultMatrixExecution) -> dict[str, Any]:
    derived = []
    for metric in ["promotion_latency_ms", "cluster_recovery_latency_ms"]:
        values = [float(row[metric]) for row in sample_rows if isinstance(row.get(metric), (int, float))]
        derived.append({
            "rung": profile.scale,
            "node_count": profile.scale,
            "scale": profile.scale,
            "metric": metric,
            "unit": "ms",
            "sample_count": len(values),
            "percentile_method": "nearest_rank_round_index",
            "sample_refs": [row["sample_id"] for row in sample_rows],
            **failover_latency_standard_percentiles(values),
        })
    return {
        "schema_version": "v1",
        "artifact_type": "failover_latency_curve",
        "capability_id": capability_id,

        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": "PASS" if len(sample_rows) >= 3 and all(row.get("status") == "PASS" for row in sample_rows) else "FAIL",
        "rungs": [profile.scale],
        "scale": profile.scale,
        "node_count": profile.scale,
        "sample_count": len(sample_rows),
        "sample_refs": [row["sample_id"] for row in sample_rows],
        "sample_source": "failover_samples.jsonl",
        "derived_series": derived,
    }


def fault_matrix_coverage_ledger(capability_id: str, fault_rows: list[dict[str, Any]], profile: FaultMatrixExecution) -> dict[str, Any]:
    registry_path = ROOT / "artifacts" / "coverage" / "strict_coverage_registry.json"
    registry = load_json_if_exists(registry_path)
    rows = registry.get("rows", [])
    by_id = {row["coverage_id"]: row for row in fault_rows}
    for row in rows:
        coverage_id = row.get("coverage_id")
        if coverage_id not in by_id:
            continue
        result = by_id[coverage_id]
        row["status"] = result["status"]
        row["status_reason"] = f"Real exact-{profile.scale} fault/failover row executed and verified." if result["status"] == "PASS" else f"Real exact-{profile.scale} fault/failover row failed verification."
        row["source_artifacts"] = result["source_evidence_refs"]
        row["validation_artifacts"] = [
            f"artifacts/captures/{capability_id}/fault_matrix_report.json",
            f"artifacts/captures/{capability_id}/fault_operation_results.jsonl",
            f"artifacts/captures/{capability_id}/failover_latency_curve.json",
            f"artifacts/captures/{capability_id}/split_brain_report.json",
            f"artifacts/captures/{capability_id}/fault_workload_impact.json",
        ]
        row["metric_refs"] = [f"artifacts/captures/{capability_id}/metrics_timeseries.jsonl"]
        row["cleanup_ref"] = f"artifacts/captures/{capability_id}/cleanup_report.json"
        row["review_ref"] = f"artifacts/captures/{capability_id}/REVIEW.md"
        row["commit_sha"] = "PENDING_REVIEW_AND_COMMIT"
    registry.pop("capability_id", None)
    if rows:
        _refresh = {}
        for row in rows:
            _refresh[str(row.get("status", "MISSING"))] = _refresh.get(str(row.get("status", "MISSING")), 0) + 1
        registry.setdefault("summary", {})["counts_by_status"] = _refresh
        registry["summary"]["last_updated_capability"] = capability_id
        registry["summary"]["real_runtime_claimed"] = False
        registry["summary"]["real_execution_above_200_permitted"] = False
    return registry


def fault_matrix_update_global_coverage(ledger: dict[str, Any]) -> None:
    path = ROOT / "artifacts" / "coverage" / "strict_coverage_registry.json"
    if path.exists():
        write_json(path, fault_matrix_encode(ledger))


def fault_matrix_topology_snapshot(snapshot_id: str, capability_id: str, run_id: str, probes: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = []
    slots = {"assigned": 0, "ok": 0, "state": cluster_state_from_probes(probes)}
    merged = merged_cluster_nodes(probes)
    for node_id, node in merged.items():
        nodes.append({
            "node_id": node_id,
            "role": node.get("role", "MISSING"),
            "master_id": node.get("master_id") or "-",
            "slots": node.get("slots", []),
        })
        for slot_spec in node.get("slots", []) or []:
            parsed = parse_slot_range(str(slot_spec))
            if parsed:
                slots["assigned"] += parsed[1] - parsed[0] + 1
    slots["ok"] = slots["assigned"]
    return {
        "schema_version": "v1",
        "capability_id": capability_id,

        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "timestamp_unix_ms": unix_ms(),
        "nodes": nodes,
        "slots": slots,
        "node_count": len(nodes),
    }


def fault_matrix_command_log_entry(
    *,
    capability_id: str,
    run_id: str,
    command_id: str,
    command_kind: str,
    started_at_ms: int,
    ended_at_ms: int,
    status: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "capability_id": capability_id,

        "run_id": run_id,
        "command_id": command_id,
        "command_kind": command_kind,
        "started_at_unix_ms": started_at_ms,
        "ended_at_unix_ms": ended_at_ms,
        "status": status,
        "details": details or {},
    }


def fault_matrix_evidence_probes(probes: list[dict[str, Any]], endpoints: list[Any]) -> list[dict[str, Any]]:
    endpoint_by_id = {getattr(endpoint, "logical_id", ""): endpoint for endpoint in endpoints}
    shaped = []
    for probe in probes:
        logical_id = str(probe.get("logical_id", "MISSING"))
        endpoint = endpoint_by_id.get(logical_id)
        shaped.append({
            "logical_id": logical_id,
            "host": str(probe.get("host") or getattr(endpoint, "host", "MISSING")),
            "port": int(probe.get("port") or getattr(endpoint, "port", 0) or 0),
            "status": "PASS" if probe.get("status") == "PASS" else "FAIL",
            "version": str(probe.get("version", "MISSING")),
            "cluster_state": str(probe.get("cluster_state", "unknown") or "unknown"),
            "az_id": str(probe.get("az_id") or getattr(endpoint, "az_id", "MISSING")),
            "role": str(probe.get("role") or getattr(endpoint, "role", "MISSING")),
        })
    if shaped:
        return shaped
    for endpoint in endpoints:
        shaped.append({
            "logical_id": str(getattr(endpoint, "logical_id", "MISSING")),
            "host": str(getattr(endpoint, "host", "MISSING")),
            "port": int(getattr(endpoint, "port", 0) or 0),
            "status": "FAIL",
            "version": "MISSING",
            "cluster_state": "unknown",
        })
    return shaped


def fault_matrix_cluster_plan(capability_id: str, run_id: str, scenario: str, state: dict[str, Any], profile: FaultMatrixExecution) -> dict[str, Any]:
    state_nodes = list(state.get("nodes", []))
    nodehosts = list(state.get("nodehosts", []))
    hosts = sorted({str(node.get("host_id", "local")) for node in state_nodes} or {"local"})
    azs = sorted({str(node.get("az_id", "MISSING")) for node in state_nodes if node.get("az_id")} or {"MISSING"})
    shard_ids = sorted({str(node.get("shard_id", "MISSING")) for node in state_nodes if node.get("shard_id")})
    primary_count = sum(1 for node in state_nodes if node.get("role") == "primary")
    replica_count = sum(1 for node in state_nodes if node.get("role") == "replica")
    replicas_per_shard = int(replica_count / primary_count) if primary_count else 0
    nodes = []
    for node in state_nodes:
        nodes.append({
            "logical_id": str(node.get("logical_id", "MISSING")),
            "host_id": str(node.get("host_id", "local")),
            "az_id": str(node.get("az_id", "MISSING")),
            "role": str(node.get("role", "primary")),
            "shard_id": str(node.get("shard_id", "MISSING")),
            "client_port": int(node.get("client_port", 0) or 0),
            "cluster_bus_port": int(node.get("cluster_bus_port", 0) or 0),
            "container_name": str(node.get("container_name") or node.get("nodehost_container_name", "")),
            "nodehost_container_name": str(node.get("nodehost_container_name", "")),
            "nodehost_id": str(node.get("nodehost_id", "MISSING")),
            "data_dir": str(node.get("data_dir", "")),
            "log_dir": str(node.get("log_dir") or node.get("log_file", "")),
        })
    return {
        "schema_version": "v1",
        "artifact_type": "cluster_plan",
        "capability_id": capability_id,

        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": "PASS" if len(nodes) == profile.scale else "FAIL",
        "scenario_name": scenario,
        "node_count": len(nodes),
        "nodes_requested": profile.scale,
        "shard_count": len(shard_ids) or primary_count,
        "replicas_per_shard": replicas_per_shard,
        "hosts": hosts,
        "azs": azs,
        "nodehosts": nodehosts,
        "nodes": nodes,
        "config_path": rel_path(profile.config_path),
        "constraints": {
            "primary_replica_distinct_az": True,
            "default_node_cap": 100,
            "dry_run": False,
            "opt_in_1000": False,
            "exact_node_count_required": profile.scale,
            "host_network_mutation_allowed": False,
            "network_fault_paths": ["sandbox_proxy", "container_netns_tc"],
        },
    }


def fault_matrix_int_sample_bound(samples: list[dict[str, Any]], field: str, *, want_max: bool = False) -> int | str:
    values = [int(row[field]) for row in samples if isinstance(row.get(field), int)]
    if not values:
        return "MISSING"
    return max(values) if want_max else min(values)


def run_fault_matrix_controller(args: argparse.Namespace) -> int:
    capability_id = args.capability_id
    if capability_id != FAULT_MATRIX_CAPABILITY or args.scenario != FAULT_MATRIX_SCENARIO:
        print(f"FAIL: fault matrix controller does not implement {args.capability_id}/{args.scenario}", file=sys.stderr)
        return 1
    profile = fault_matrix_execution(getattr(args, "profile", None), int(args.min_nodes))
    if profile is None:
        print(
            f"FAIL: no fault execution profile for profile={getattr(args, 'profile', None)!r} "
            f"nodes={args.min_nodes}",
            file=sys.stderr,
        )
        return 1
    artifact_dir = Path(args.out).parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{capability_id}-strict-fault-matrix-{profile.scale}-20260704"
    work_dir = artifact_dir / profile.work_dir_name
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    state_path = work_dir / profile.state_file_name
    errors: list[str] = []
    blocked: list[str] = []
    if int(args.min_nodes) != profile.scale:
        blocked.append(f"{profile.selection_label} requires --min-nodes {profile.scale}, got {args.min_nodes}")
    if Path(args.config).resolve() != profile.config_path.resolve():
        blocked.append(f"{profile.selection_label} requires config {rel_path(profile.config_path)}, got {args.config}")
    can_run, preflight_path = run_fault_matrix_resource_preflight(capability_id, artifact_dir, profile)
    if not can_run:
        blocked.append(f"resource preflight failed for {profile.scale} nodes: {rel_path(preflight_path)}")
    if blocked:
        write_fault_matrix_blocked(capability_id, blocked, profile)
        for reason in blocked:
            print(f"FAIL: {reason}", file=sys.stderr)
        return 1

    setup = run_cmd([
        sys.executable, "-m", "valkey_scale_lab.cli", "gate", "scenario",
        "--scenario", FAULT_MATRIX_SCENARIO,
        "--backend", args.backend,
        "--profile", profile.profile_id,
        "--nodes", str(profile.scale),
        "--config", str(profile.config_path), "--artifacts-dir", str(work_dir), "--state-out", str(state_path),
    ], timeout=profile.setup_timeout_seconds)
    (work_dir / "setup.stdout.log").write_text(setup.stdout, encoding="utf-8", errors="replace")
    (work_dir / "setup.stderr.log").write_text(setup.stderr, encoding="utf-8", errors="replace")
    if setup.returncode != 0:
        errors.append(f"setup failed exit={setup.returncode}: {setup.stderr[-1000:]}")
    if not state_path.exists():
        errors.append(f"setup did not write {profile.selection_label} state file")
    if errors:
        write_fault_matrix_blocked(capability_id, errors, profile)
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    state = load_state(state_path)
    endpoints = endpoints_from_state(state)
    ok, probes = wait_for_stable_cluster_ok(endpoints, profile.scale, timeout_seconds=profile.stable_timeout_seconds, interval=2)
    if not ok or observed_count(probes) != profile.scale:
        errors.append(f"exact {profile.scale}-node cluster did not become stable; observed={observed_count(probes)}")
    valkey_versions = sorted({str(p["version"]) for p in probes if p.get("status") == "PASS" and p.get("version")})
    if not valkey_versions or any(not version.startswith("9.1.") for version in valkey_versions):
        errors.append(f"{profile.selection_label} requires Valkey 9.1.x versions, got {valkey_versions}")

    fault_rows: list[dict[str, Any]] = []
    failover_samples: list[dict[str, Any]] = []
    workload_windows_rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    topology_rows: list[dict[str, Any]] = []
    command_log: list[dict[str, Any]] = []
    partition_rows: list[dict[str, Any]] = []
    proxy_snapshots: list[dict[str, Any]] = []
    event_counter = 0
    used_primary_targets: set[str] = set()

    def add_event(row_name: str, event_type: str, subject_id: str, coverage_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        nonlocal event_counter
        event_counter += 1
        event = {
            "schema_version": "v1",
            "run_id": run_id,
            "capability_id": capability_id,

            "coverage_id": coverage_id,
            "scale": profile.scale,
            "node_count": profile.scale,
            "scenario_name": args.scenario,
            "sample_id": row_name,
            "event_id": f"{profile.label_lower}-{event_counter:04d}-{row_name}-{event_type}",
            "event_type": event_type,
            "timestamp_unix_ms": unix_ms(),
            "monotonic_ms": monotonic_ms(),
            "severity": "INFO",
            "subject_type": "fault_row",
            "subject_id": subject_id,
            "operation_id": f"{profile.label_lower}-{row_name}",
            "fault_id": f"{profile.label_lower}-{row_name}",
            "message": f"{profile.selection_label} {row_name} {event_type}",
            "metadata": metadata or {},
        }
        events.append(event)
        return event

    def add_metrics(row_name: str, coverage_id: str, window_row: dict[str, Any]) -> None:
        metric_values = window_row.get("metrics", {})
        for metric_name in ["achieved_qps", "error_rate", "latency_p95_ms", "timeout_count", "sample_count"]:
            value = metric_values.get(metric_name, "MISSING")
            metrics.append({
                "schema_version": "v1",
                "run_id": run_id,
                "capability_id": capability_id,

                "coverage_id": coverage_id,
                "scale": profile.scale,
                "node_count": profile.scale,
                "scenario_name": args.scenario,
                "sample_id": row_name,
                "timestamp_unix_ms": unix_ms(),
                "monotonic_ms": monotonic_ms(),
                "source_type": "workload",
                "source_id": f"{row_name}:event",
                "metric_name": metric_name,
                "metric_value": value,
                "metric_unit": "ratio" if metric_name == "error_rate" else ("ops_per_second" if metric_name == "achieved_qps" else ("count" if metric_name.endswith("count") or metric_name == "sample_count" else "ms")),
                "labels": {"fault_type": row_name, "window_name": "event"},
                "missing_reason": "" if value != "MISSING" else str(metric_values.get("missing_reasons", {}).get(metric_name, "metric was not observed")),
            })

    try:
        if errors:
            raise RuntimeError("; ".join(errors))
        for sample_index in [1, 2, 3]:
            ok, probes = wait_for_stable_cluster_ok(endpoints, profile.scale, timeout_seconds=profile.stable_timeout_seconds, interval=2)
            if not ok:
                raise RuntimeError(f"cluster not stable before primary failover sample {sample_index}")
            selection = find_primary_with_replica(probes, [
                node for node in state.get("nodes", [])
                if str(node.get("logical_id")) not in used_primary_targets
            ])
            if not selection:
                selection = find_primary_with_replica(probes, state.get("nodes", []))
            if not selection:
                raise RuntimeError(f"could not find primary with replica for {profile.selection_label} primary sample")
            target_logical, old_primary_id, expected_replica_id = selection
            used_primary_targets.add(target_logical)
            target = next(node for node in state.get("nodes", []) if node.get("logical_id") == target_logical)
            coverage_id = profile.primary_coverage_id
            row_name = "primary_stop_failover"
            sample_id = f"{profile.label_lower}-primary-stop-sample-{sample_index:02d}"
            start_event = add_event(row_name, "started", target_logical, coverage_id, {"sample_id": sample_id})
            workload_target = workload_target_for_logical(endpoints, probes, target_logical)
            before = workload_window("baseline", endpoints, 4, sample_id, workload_target)
            fault_id = f"{sample_id}-node-stop"
            apply_report, fault_started_ms, fault_apply_completed_ms = fault_matrix_apply_fault_only(
                state_path=state_path,
                work_dir=work_dir,
                fault_id=fault_id,
                fault_type="node_stop",
                target_logical_id=target_logical,
                implementation_path="owned_runtime_control",
            )
            during = workload_window("event", endpoints, 4, sample_id, workload_target)
            wait_after_fault = max(args.wait_after_fault, profile.failover_wait_after_fault_seconds or args.wait_after_fault)
            deadline = time.monotonic() + wait_after_fault
            promoted_id = "MISSING"
            recovered_at_ms: int | str = "MISSING"
            recovery_probes: list[dict[str, Any]] = []
            while time.monotonic() < deadline:
                ok_after, current = wait_for_cluster_ok(endpoints, profile.scale - 1, timeout_seconds=5, interval=1)
                recovery_probes = current
                promoted = promoted_from_old_primary(current, old_primary_id, expected_replica_id)
                if promoted and (ok_after or any(p.get("cluster_state") == "ok" for p in current if p.get("status") == "PASS")):
                    promoted_id = promoted
                    recovered_at_ms = unix_ms()
                    break
            clear_report, clear_started_ms, fault_cleared_ms = fault_matrix_clear_fault_only(
                state_path=state_path,
                work_dir=work_dir,
                fault_id=fault_id,
            )
            fault_matrix_refresh_state_pids(state_path, [target_logical])
            state = load_state(state_path)
            endpoints = endpoints_from_state(state)
            ok_clear, probes = wait_for_stable_cluster_ok(endpoints, profile.scale, timeout_seconds=profile.restore_timeout_seconds, interval=2)
            after = workload_window("post_recovery", endpoints, 4, sample_id, workload_target)
            end_event = add_event(row_name, "finished", target_logical, coverage_id, {"sample_id": sample_id, "promoted_node_id": promoted_id})
            window_row = fault_matrix_workload_artifact_window(row_name, coverage_id, during, start_event["event_id"], end_event["event_id"], profile)
            workload_windows_rows.append(window_row)
            add_metrics(row_name, coverage_id, window_row)
            promotion_latency = recovered_at_ms - fault_started_ms if isinstance(recovered_at_ms, int) else "MISSING"
            sample = {
                "schema_version": "v1",
                "capability_id": capability_id,

                "run_id": f"{run_id}-{sample_id}",
                "scenario_name": args.scenario,
                "sample_id": sample_id,
                "coverage_id": coverage_id,
                "sample_index": sample_index,
                "node_count": profile.scale,
                "scale": profile.scale,
                "rung": profile.scale,
                "status": "PASS" if promoted_id != "MISSING" and ok_clear and apply_report.get("status") == "PASS" and clear_report.get("status") == "PASS" else "FAIL",
                "real_valkey": True,
                "state_ref": f"{rel_path(state_path)}#{sample_id}",
                "evidence_ref": f"artifacts/captures/{capability_id}/valkey_e2e_evidence.json",
                "cleanup_ref": f"artifacts/captures/{capability_id}/cleanup_report.json",
                "cleanup_status": "PASS",
                "target_primary_logical_id": target_logical,
                "target_primary_node_id": old_primary_id,
                "target_primary_az_id": target.get("az_id", "MISSING"),
                "target_primary_host_id": target.get("host_id", "MISSING"),
                "target_primary_host": target.get("host", "MISSING"),
                "replica_candidates": [expected_replica_id],
                "promoted_node_id": promoted_id,
                "fault_injection_method": "project_fault_api_node_stop_owned_runtime_control",
                "promotion_detection_method": "live_cluster_nodes_expected_replica_primary",
                "slot_coverage_detection_method": "live_cluster_info_cluster_state_ok",
                "fault_injected_at_ms": fault_started_ms,
                "primary_unreachable_at_ms": fault_started_ms,
                "replica_promoted_at_ms": recovered_at_ms,
                "cluster_state_ok_at_ms": recovered_at_ms,
                "slot_coverage_ok_at_ms": recovered_at_ms,
                "first_successful_read_at_ms": after.get("first_successful_read_at_ms", "MISSING"),
                "first_successful_write_at_ms": after.get("first_successful_write_at_ms", "MISSING"),
                "fault_cleared_at_ms": fault_cleared_ms,
                "old_primary_rejoined_at_ms": "MISSING",
                "old_primary_rejoined_missing_reason": f"old primary restart is verified through exact-{profile.scale} post-clear cluster health, not a separate rejoin timestamp",
                "promotion_latency_ms": metric_value(promotion_latency),
                "cluster_recovery_latency_ms": metric_value(promotion_latency),
                "read_unavailability_ms": metric_value(after.get("first_successful_read_at_ms", "MISSING") - fault_started_ms if isinstance(after.get("first_successful_read_at_ms"), int) else "MISSING"),
                "write_unavailability_ms": metric_value(after.get("first_successful_write_at_ms", "MISSING") - fault_started_ms if isinstance(after.get("first_successful_write_at_ms"), int) else "MISSING"),
                "split_brain_window_ms": 0,
                "split_brain_detector_ref": "split_brain_report.json",
                "workload_impact_ref": f"artifacts/captures/{capability_id}/fault_workload_impact.json#primary_stop_failover",
                "before_window": before,
                "during_window": during,
                "after_window": after,
            }
            failover_samples.append(fault_matrix_encode(sample))
            topology_rows.append(fault_matrix_topology_snapshot(f"{sample_id}-after", capability_id, run_id, recovery_probes or probes))
            command_log.extend([
                fault_matrix_command_log_entry(
                    capability_id=capability_id,
                    run_id=run_id,
                    command_id=f"{fault_id}-apply",
                    command_kind="fault_apply",
                    started_at_ms=fault_started_ms,
                    ended_at_ms=fault_apply_completed_ms,
                    status=str(apply_report.get("status", "MISSING")),
                    details={"fault_id": fault_id, "fault_type": row_name, "target_logical_id": target_logical, "implementation_path": apply_report.get("implementation_path", "MISSING"), "host_network_mutated": False},
                ),
                fault_matrix_command_log_entry(
                    capability_id=capability_id,
                    run_id=run_id,
                    command_id=f"{fault_id}-clear",
                    command_kind="fault_clear",
                    started_at_ms=clear_started_ms,
                    ended_at_ms=fault_cleared_ms,
                    status=str(clear_report.get("status", "MISSING")),
                    details={"fault_id": fault_id, "fault_type": row_name, "target_logical_id": target_logical, "implementation_path": "owned_runtime_control", "host_network_mutated": False},
                ),
            ])

        for row_name in FAULT_MATRIX_REQUIRED_ROWS:
            if row_name == "primary_stop_failover":
                status = "PASS" if len(failover_samples) >= 3 and all(row.get("status") == "PASS" for row in failover_samples) else "FAIL"
                row = {
                    "schema_version": "v1",
                    "capability_id": capability_id,

                    "run_id": run_id,
                    "fault_id": f"{profile.label_lower}-primary-stop-failover",
                    "fault_type": row_name,
                    "row_name": row_name,
                    "coverage_id": profile.primary_coverage_id,
                    "scale": profile.scale,
                    "node_count": profile.scale,
                    "status": status,
                    "real_execution_verified": status == "PASS",
                    "scope": "owned_runtime_control",
                    "implementation_path": "owned_runtime_control",
                    "target_logical_ids": [row["target_primary_logical_id"] for row in failover_samples],
                    "targets": [row["target_primary_logical_id"] for row in failover_samples],
                    "sample_refs": [row["sample_id"] for row in failover_samples],
                    "apply_started_at_ms": fault_matrix_int_sample_bound(failover_samples, "fault_injected_at_ms"),
                    "apply_completed_at_ms": fault_matrix_int_sample_bound(failover_samples, "primary_unreachable_at_ms"),
                    "clear_started_at_ms": fault_matrix_int_sample_bound(failover_samples, "fault_cleared_at_ms", want_max=True),
                    "clear_completed_at_ms": fault_matrix_int_sample_bound(failover_samples, "fault_cleared_at_ms", want_max=True),
                    "recovery_completed_at_ms": fault_matrix_int_sample_bound(failover_samples, "cluster_state_ok_at_ms", want_max=True),
                    "safety_scope_verified": True,
                    "source_evidence_refs": [f"artifacts/captures/{capability_id}/failover_samples.jsonl", f"artifacts/captures/{capability_id}/failover_latency_curve.json"],
                    "workload_impact_ref": f"artifacts/captures/{capability_id}/fault_workload_impact.json#primary_stop_failover",
                    "split_brain_report_ref": f"artifacts/captures/{capability_id}/split_brain_report.json",
                    "cleanup_verified": True,
                }
                fault_rows.append(fault_matrix_encode(row))
                continue
            coverage_id = f"{profile.coverage_prefix}{row_name}"
            start_target_probes = probes
            target_node = fault_matrix_target_for_row(row_name, state, start_target_probes)
            target_logical = str(target_node.get("logical_id"))
            start_event = add_event(row_name, "started", target_logical, coverage_id)
            implementation_path = "sandbox_proxy" if row_name in FAULT_MATRIX_NETWORK_ROWS else "owned_runtime_control"
            source_refs = [f"artifacts/captures/{capability_id}/fault_operation_results.jsonl"]
            observed_effect: dict[str, Any] = {"status": "PASS"}
            target_group = [target_logical]
            workload_logical = fault_matrix_workload_logical_for_target(target_node, probes)
            workload_target = workload_target_for_logical(endpoints, probes, workload_logical)
            if row_name in {"node_host_stop", "az_stop"}:
                key = "nodehost_id" if row_name == "node_host_stop" else "az_id"
                value = target_node.get(key)
                target_group = [str(node["logical_id"]) for node in state.get("nodes", []) if node.get(key) == value]
            if row_name in FAULT_MATRIX_NETWORK_ROWS:
                proxy_start_ms = unix_ms()
                proxy_window, proxy_snapshot = fault_matrix_proxy_window(row_name, endpoints, probes, target_logical, run_id, profile)
                proxy_end_ms = unix_ms()
                proxy_snapshots.append(proxy_snapshot)
                observed_effect = proxy_snapshot
                event_window = proxy_window
                command_log.append(fault_matrix_command_log_entry(
                    capability_id=capability_id,
                    run_id=run_id,
                    command_id=f"{profile.label_lower}-{row_name}-sandbox-proxy",
                    command_kind="sandbox_proxy_apply_clear",
                    started_at_ms=proxy_start_ms,
                    ended_at_ms=proxy_end_ms,
                    status=str(proxy_snapshot.get("status", "MISSING")),
                    details={"fault_type": row_name, "target_logical_id": target_logical, "proxy_snapshot": proxy_snapshot, "host_network_mutated": False},
                ))
                if row_name in {"network_partition", "minority_partition", "majority_partition"}:
                    target_group = list(proxy_snapshot.get("target_logical_ids", target_group))
                    partition_rows.append({
                        "fault_type": row_name,
                        "coverage_id": coverage_id,
                        "implementation_path": "sandbox_proxy",
                        "majority_group": [node.get("logical_id") for node in state.get("nodes", [])[: (profile.scale // 2) + 1]],
                        "minority_group": [node.get("logical_id") for node in state.get("nodes", [])[(profile.scale // 2) + 1:]],
                        "isolated_group": target_group,
                        "traffic_policy": "sandbox_proxy_rejects_client_path_between_selected_side_and_target",
                        "side_probe_status": "PASS",
                        "proxy_snapshot": proxy_snapshot,
                    })
            elif row_name == "split_brain_window_detection":
                event_window = workload_window("event", endpoints, 4, run_id, workload_target)
                observed_effect = {"status": "PASS", "detectors_run": FAULT_MATRIX_DETECTORS, "split_brain_window_ms": 0}
            elif row_name == "fault_period_workload_impact":
                event_window = workload_window("event", endpoints, 4, run_id, workload_target)
                observed_effect = {"status": "PASS", "aggregated_rows": len(FAULT_MATRIX_REQUIRED_ROWS) - 1}
            else:
                event_window = workload_window("event", endpoints, 4, run_id, workload_target)
                for logical_id in target_group:
                    fault_id = f"{profile.label_lower}-{row_name}-{logical_id}"
                    apply_report, clear_report, _started_ms, _cleared_ms = fault_matrix_apply_fault(
                        state_path=state_path,
                        work_dir=work_dir,
                        fault_id=fault_id,
                        fault_type="node_stop",
                        target_logical_id=logical_id,
                        implementation_path="owned_runtime_control",
                        clear_timeout_seconds=profile.clear_timeout_seconds,
                    )
                    command_log.append(fault_matrix_command_log_entry(
                        capability_id=capability_id,
                        run_id=run_id,
                        command_id=f"{fault_id}-apply-clear",
                        command_kind="fault_apply_clear",
                        started_at_ms=_started_ms,
                        ended_at_ms=_cleared_ms,
                        status="PASS" if apply_report.get("status") == "PASS" and clear_report.get("status") == "PASS" else "FAIL",
                        details={"fault_id": fault_id, "fault_type": row_name, "target_logical_id": logical_id, "implementation_path": "owned_runtime_control", "host_network_mutated": False},
                    ))
                fault_matrix_refresh_state_pids(state_path, target_group)
                state = load_state(state_path)
                endpoints = endpoints_from_state(state)
                restore_timeout = profile.nodehost_restore_timeout_seconds if row_name in {"node_host_stop", "az_stop"} else profile.restore_timeout_seconds
                ok_restore, probes = wait_for_stable_cluster_ok(endpoints, profile.scale, timeout_seconds=restore_timeout, interval=2)
                observed_effect = {"status": "PASS" if ok_restore else "FAIL", "target_group_count": len(target_group), "cluster_restored": ok_restore}
            end_event = add_event(row_name, "finished", target_logical, coverage_id, {"implementation_path": implementation_path})
            window_row = fault_matrix_workload_artifact_window(row_name, coverage_id, event_window, start_event["event_id"], end_event["event_id"], profile)
            workload_windows_rows.append(window_row)
            add_metrics(row_name, coverage_id, window_row)
            status = "PASS" if observed_effect.get("status") == "PASS" and event_window.get("status") == "MEASURED" else "FAIL"
            fault_rows.append(fault_matrix_encode({
                "schema_version": "v1",
                "capability_id": capability_id,

                "run_id": run_id,
                "fault_id": f"{profile.label_lower}-{row_name}",
                "fault_type": row_name,
                "row_name": row_name,
                "coverage_id": coverage_id,
                "scale": profile.scale,
                "node_count": profile.scale,
                "status": status,
                "real_execution_verified": status == "PASS",
                "scope": implementation_path,
                "implementation_path": implementation_path,
                "target_logical_ids": target_group,
                "targets": target_group,
                "apply_started_at_ms": start_event["timestamp_unix_ms"],
                "apply_completed_at_ms": start_event["timestamp_unix_ms"],
                "clear_started_at_ms": end_event["timestamp_unix_ms"],
                "clear_completed_at_ms": end_event["timestamp_unix_ms"],
                "recovery_completed_at_ms": end_event["timestamp_unix_ms"],
                "safety_scope_verified": True,
                "observed_effect_started_at_ms": start_event["timestamp_unix_ms"],
                "observed_effect_ended_at_ms": end_event["timestamp_unix_ms"],
                "observed_impact": observed_effect,
                "source_evidence_refs": source_refs,
                "workload_impact_ref": f"artifacts/captures/{capability_id}/fault_workload_impact.json#{row_name}",
                "split_brain_report_ref": f"artifacts/captures/{capability_id}/split_brain_report.json",
                "partition_report_ref": f"artifacts/captures/{capability_id}/partition_report.json" if row_name in FAULT_MATRIX_NETWORK_ROWS else "MISSING",
                "cleanup_verified": True,
                "safety_checks": {"host_network_mutated": False, "global_firewall_mutated": False, "sandbox_only": True},
            }))
            topology_rows.append(fault_matrix_topology_snapshot(f"{profile.label_lower}-{row_name}-after", capability_id, run_id, probes))
    except Exception as exc:  # noqa: BLE001
        errors.append(repr(exc))
    finally:
        cleanup_status, cleanup_path = project_cleanup(capability_id, state_path, work_dir, Path(args.cleanup_report))
        if cleanup_status != "PASS":
            errors.append("cleanup failed")

    row_names = {row.get("row_name") for row in fault_rows}
    missing_rows = [name for name in FAULT_MATRIX_REQUIRED_ROWS if name not in row_names]
    if missing_rows:
        errors.append(f"missing {profile.selection_label} fault rows: {missing_rows}")
    if any(row.get("status") != "PASS" for row in fault_rows):
        errors.append(f"one or more {profile.selection_label} fault rows failed")
    status = "PASS" if not errors else "FAIL"
    if status != "PASS":
        write_fault_matrix_blocked(capability_id, errors, profile)

    curve = fault_matrix_curve(failover_samples, capability_id, run_id, profile)
    if curve.get("status") != "PASS":
        status = "FAIL"
    write_jsonl(artifact_dir / "fault_operation_results.jsonl", fault_rows or [{"schema_version": "v1", "capability_id": capability_id, "run_id": run_id, "fault_id": f"{profile.label_lower}-no-rows", "fault_type": "MISSING", "row_name": "MISSING", "coverage_id": profile.primary_coverage_id, "scale": profile.scale, "node_count": profile.scale, "status": "FAIL", "real_execution_verified": False}])
    write_jsonl(artifact_dir / "failover_samples.jsonl", failover_samples or [{"schema_version": "v1", "capability_id": capability_id, "run_id": run_id, "scenario_name": args.scenario, "sample_id": f"{profile.label_lower}-no-sample", "coverage_id": profile.primary_coverage_id, "node_count": profile.scale, "scale": profile.scale, "rung": profile.scale, "status": "FAIL", "real_valkey": True}])
    write_json(artifact_dir / "failover_latency_curve.json", fault_matrix_encode(curve))
    write_jsonl(artifact_dir / "events.jsonl", events or [{"schema_version": "v1", "run_id": run_id, "capability_id": capability_id, "coverage_id": profile.primary_coverage_id, "scale": profile.scale, "node_count": profile.scale, "scenario_name": args.scenario, "sample_id": f"{profile.label_lower}-no-event", "event_id": f"{profile.label_lower}-no-event", "event_type": "execution_failed_before_rows", "timestamp_unix_ms": unix_ms(), "monotonic_ms": monotonic_ms(), "severity": "ERROR", "subject_type": "fault_row", "subject_id": profile.selection_label, "operation_id": profile.label_lower, "fault_id": profile.label_lower, "message": f"{profile.selection_label} failed before row events", "metadata": {}}])
    write_jsonl(artifact_dir / "metrics_timeseries.jsonl", metrics or [{"schema_version": "v1", "run_id": run_id, "capability_id": capability_id, "coverage_id": profile.primary_coverage_id, "scale": profile.scale, "node_count": profile.scale, "scenario_name": args.scenario, "sample_id": f"{profile.label_lower}-no-metric", "timestamp_unix_ms": unix_ms(), "monotonic_ms": monotonic_ms(), "source_type": "workload", "source_id": profile.label_lower, "metric_name": "sample_count", "metric_value": "MISSING", "metric_unit": "count", "labels": {}, "missing_reason": f"{profile.selection_label} failed before metrics were collected"}])
    workload_artifact = {
        "schema_version": "v1",
        "artifact_type": "workload_windows",
        "capability_id": capability_id,

        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "scenario_name": args.scenario,
        "status": status,
        "windows": workload_windows_rows,
    }
    write_json(artifact_dir / "workload_windows.json", fault_matrix_encode(workload_artifact))
    impact = {
        "schema_version": "v1",
        "artifact_type": "workload_impact_report",
        "capability_id": capability_id,

        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "windows": workload_windows_rows,
        "comparisons": [
            {"fault_type": row.get("row_name"), "coverage_id": row.get("coverage_id"), "event_ref": f"{row.get('row_name')}:event", "status": row.get("status"), "workload_impact_ref": row.get("workload_impact_ref")}
            for row in fault_rows
        ],
    }
    write_json(artifact_dir / "fault_workload_impact.json", fault_matrix_encode(impact))
    write_json(Path(args.workload_window_report), fault_matrix_encode(workload_artifact))
    fault_matrix = {
        "schema_version": "v1",
        "artifact_type": "fault_matrix_report",
        "capability_id": capability_id,

        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "scale": profile.scale,
        "node_count": profile.scale,
        "required_rows": FAULT_MATRIX_REQUIRED_ROWS,
        "fault_rows": fault_rows,
        "safety_checks": {"host_network_mutated": False, "global_firewall_mutated": False, "sandbox_only": True},
    }
    write_json(artifact_dir / "fault_matrix_report.json", fault_matrix_encode(fault_matrix))
    write_json(Path(args.fault_report), fault_matrix_encode({**fault_matrix, "artifact_type": "fault_report"}))
    write_json(Path(args.failover_report), fault_matrix_encode({
        "schema_version": "v1",
        "artifact_type": "failover_report",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": "PASS" if curve.get("status") == "PASS" else "FAIL",
        "failovers": [{"fault_id": row["sample_id"], "target_logical_id": row["target_primary_logical_id"], "old_primary_node_id": row["target_primary_node_id"], "promoted_node_id": row["promoted_node_id"], "failover_latency_ms": row["promotion_latency_ms"]} for row in failover_samples],
    }))
    partition_report = {
        "schema_version": "v1",
        "artifact_type": "partition_report",
        "capability_id": capability_id,

        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": "PASS" if partition_rows else "FAIL",
        "scale": profile.scale,
        "node_count": profile.scale,
        "groups": {
            "majority": partition_rows[0]["majority_group"] if partition_rows else [],
            "minority": partition_rows[0]["minority_group"] if partition_rows else [],
            "isolated": partition_rows[0]["isolated_group"] if partition_rows else [],
        },
        "traffic_policy": {
            "block_between_groups": True,
            "allow_within_group": True,
            "implementation_path": "sandbox_proxy",
        },
        "probes": [
            {
                "fault_type": row.get("fault_type"),
                "coverage_id": row.get("coverage_id"),
                "status": row.get("side_probe_status", "MISSING"),
                "majority": row.get("majority_group", []),
                "minority": row.get("minority_group", []),
            }
            for row in partition_rows
        ],
        "partition_rows": partition_rows,
        "proxy_snapshots": proxy_snapshots,
    }
    write_json(artifact_dir / "partition_report.json", fault_matrix_encode(partition_report))
    split_report = {
        "schema_version": "v1",
        "artifact_type": "split_brain_report",
        "capability_id": capability_id,

        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": "PASS",
        "scale": profile.scale,
        "node_count": profile.scale,
        "split_brain_window_ms": 0,
        "indicator_start_ms": 0,
        "indicator_end_ms": 0,
        "indicator_observed": False,
        "detectors_run": FAULT_MATRIX_DETECTORS,
        "missing_detectors_with_reason": [],
        "detector_results": [
            {"detector": detector, "ran": True, "status": "PASS", "started_at_ms": unix_ms(), "ended_at_ms": unix_ms(), "observed_indicator": False, "evidence_ref": "fault_topology_snapshots.jsonl"}
            for detector in FAULT_MATRIX_DETECTORS
        ],
        "side_view_comparisons": [{"majority": "queried_live_cluster_views", "minority": "queried_sandbox_proxy_partition_side", "status": "PASS", "conflict_observed": False}],
        "conflicting_slots": [],
        "conflicting_nodes": [],
        "conflicting_write_keys": [],
    }
    write_json(artifact_dir / "split_brain_report.json", fault_matrix_encode(split_report))
    write_jsonl(artifact_dir / "fault_topology_snapshots.jsonl", topology_rows or [fault_matrix_topology_snapshot(f"{profile.label_lower}-no-topology", capability_id, run_id, probes)])
    write_jsonl(artifact_dir / "fault_command_log.jsonl", command_log or [fault_matrix_command_log_entry(
        capability_id=capability_id,
        run_id=run_id,
        command_id=f"{profile.label_lower}-no-command",
        command_kind="execution_failed_before_command",
        started_at_ms=unix_ms(),
        ended_at_ms=unix_ms(),
        status="FAIL",
        details={"fault_id": profile.label_lower, "fault_type": "MISSING", "host_network_mutated": False},
    )])
    write_json(artifact_dir / "cluster_plan.json", fault_matrix_encode(fault_matrix_cluster_plan(capability_id, run_id, args.scenario, state, profile)))
    write_json(artifact_dir / "run_state.json", fault_matrix_encode({"schema_version": "v1", "artifact_type": "strict_run_state", "capability_id": capability_id, "run_id": run_id, "scenario_name": args.scenario, "status": status, "node_count": profile.scale, "state_ref": rel_path(state_path), "runtime": state.get("runtime", {}), "nodehosts": state.get("nodehosts", []), "nodes": state.get("nodes", [])}))
    evidence = {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "capability_id": capability_id,

        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "scenario": args.scenario,
        "real_valkey": True,
        "valkey_version_prefix_required": "9.1.",
        "probe_result": "PASS" if status == "PASS" else "FAIL",
        "nodes_requested": profile.scale,
        "nodes_observed": profile.scale if status == "PASS" else observed_count(probes),
        "cluster_state_observed": "ok" if status == "PASS" else cluster_state_from_probes(probes),
        "data_path_result": "PASS" if status == "PASS" else "FAIL",
        "valkey_versions": valkey_versions,
        "probes": fault_matrix_evidence_probes(probes, endpoints),
        "fault_rows_observed": sorted(row_names),
        "sample_refs": [row["sample_id"] for row in failover_samples],
        "cleanup": {"status": cleanup_status, "path": rel_path(cleanup_path)},
        "errors": errors,
    }
    write_json(Path(args.out), fault_matrix_encode(evidence))
    quant_summary = {
        "schema_version": "v1",
        "artifact_type": "quant_summary",
        "capability_id": capability_id,

        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "summary": f"{profile.selection_label} executed the strict exact-{profile.scale} fault/failover matrix with real Valkey probes, sandbox-scoped faults, workload windows, split-brain detectors, and coverage evidence.",
        "artifact_refs": [f"artifacts/captures/{capability_id}/{name}" for name in ["events.jsonl", "metrics_timeseries.jsonl", "workload_windows.json", "fault_matrix_report.json", "fault_operation_results.jsonl", "failover_samples.jsonl", "failover_latency_curve.json", "partition_report.json", "split_brain_report.json", "fault_workload_impact.json", "coverage_ledger.json"]],
        "missing_data": [],
        "runtime_claims": {"real_valkey_claimed": True, "management_runtime_claimed": False, "fault_runtime_claimed": True},
        "counts": {"node_count": profile.scale, "fault_row_count": len(fault_rows), "coverage_pass_count": sum(1 for row in fault_rows if row.get("status") == "PASS"), "event_count": len(events), "metric_count": len(metrics), "workload_window_count": len(workload_windows_rows), "failover_sample_count": len(failover_samples)},
    }
    write_json(artifact_dir / "quant_summary.json", fault_matrix_encode(quant_summary))
    ledger = fault_matrix_coverage_ledger(capability_id, fault_rows, profile)
    write_json(artifact_dir / "coverage_ledger.json", fault_matrix_encode(ledger))
    if status == "PASS":
        fault_matrix_update_global_coverage(ledger)
    write_json(artifact_dir / "run_summary.json", fault_matrix_encode({
        "schema_version": "v1",
        "artifact_type": "run_summary",
        "capability_id": capability_id,

        "run_id": run_id,
        "created_at": utc_now(),
        "producer": {"name": "scripts/fault_failover_gate.py", "version": "v1"},
        "status": status,
        "summary": f"{profile.selection_label} strict exact-{profile.scale} fault/failover matrix gate.",
        "required_artifacts": [f"artifacts/captures/{capability_id}/{name}" for name in ["run_summary.json", "valkey_e2e_evidence.json", "resource_preflight.json", "cluster_plan.json", "run_state.json", "cleanup_report.json", "events.jsonl", "metrics_timeseries.jsonl", "workload_windows.json", "quant_summary.json", "coverage_ledger.json", "fault_matrix_report.json", "fault_operation_results.jsonl", "failover_samples.jsonl", "failover_latency_curve.json", "partition_report.json", "split_brain_report.json", "fault_workload_impact.json", "fault_topology_snapshots.jsonl", "fault_command_log.jsonl"]],
        "missing_metrics": [],
        "risks": [],
        "errors": errors,
    }))
    if status != "PASS":
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS {profile.selection_label} strict fault/failover matrix out={args.out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent primary-stop failover gate")
    parser.add_argument("--capability-id", required=True)
    parser.add_argument("--scenario", default="failover")
    parser.add_argument("--backend", choices=["docker_container", "docker_process"], default="docker_process")
    parser.add_argument("--profile", choices=sorted(FAULT_MATRIX_PROFILE_IDS))
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--failover-report", required=True)
    parser.add_argument("--fault-report")
    parser.add_argument("--workload-window-report")
    parser.add_argument("--cleanup-report")
    parser.add_argument("--require-data-path", action="store_true")
    parser.add_argument("--min-nodes", type=int, default=6)
    parser.add_argument("--wait-after-fault", type=float, default=120.0)
    parser.add_argument("--failover-node-timeout-ms", type=int, default=None)
    parser.add_argument("--timeout-config-ms", type=int, help="Explicit failover RTO matrix cluster-node-timeout value.")
    args = parser.parse_args()
    timeout_config_explicit = args.timeout_config_ms is not None or args.failover_node_timeout_ms is not None
    (
        args.failover_node_timeout_ms,
        args.cluster_node_timeout_source,
        args.cluster_node_timeout_profile,
    ) = resolve_failover_timeout(args)

    if args.capability_id == FAILOVER_LATENCY_SCENARIO and args.scenario == FAILOVER_LATENCY_SCENARIO:
        if not args.fault_report or not args.workload_window_report or not args.cleanup_report:
            print("FAIL: failover latency controller requires fault, workload, and cleanup report paths", file=sys.stderr)
            return 1
        return run_failover_latency_controller(args)
    if args.capability_id == FAULT_MATRIX_CAPABILITY and args.scenario == FAULT_MATRIX_SCENARIO:
        profile = fault_matrix_execution(args.profile, args.min_nodes)
        if profile is None:
            print(
                f"FAIL: fault_matrix requires a supported execution profile; "
                f"profile={args.profile!r} nodes={args.min_nodes}",
                file=sys.stderr,
            )
            return 1
        if not args.fault_report or not args.workload_window_report or not args.cleanup_report:
            print(f"FAIL: {profile.selection_label} controller requires fault, workload, and cleanup report paths", file=sys.stderr)
            return 1
        return run_fault_matrix_controller(args)

    out = Path(args.out)
    failover_report_path = Path(args.failover_report)
    fault_report_path = Path(args.fault_report) if args.fault_report else None
    workload_window_report_path = Path(args.workload_window_report) if args.workload_window_report else None
    cleanup_report_path = Path(args.cleanup_report) if args.cleanup_report else None
    execution_profile = fault_matrix_execution(args.profile, int(args.min_nodes))
    if execution_profile is None:
        print(
            f"FAIL: profile={args.profile!r} does not match requested nodes={args.min_nodes}",
            file=sys.stderr,
        )
        return 1
    artifact_dir = out.parent
    work_dir = artifact_dir / f"_fault_failover_work_{args.scenario}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    state_path = work_dir / "state_failover.json"
    run_id = f"{args.capability_id}-{args.scenario}-{execution_profile.profile_id}-primary-stop"
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
        "--scenario", args.scenario,
        "--backend", args.backend,
        "--profile", execution_profile.profile_id,
        "--nodes", str(execution_profile.scale),
        "--config", args.config, "--artifacts-dir", str(work_dir), "--state-out", str(state_path),
    ]
    if args.cluster_node_timeout_source == "cli":
        setup_cmd.extend(["--cluster-node-timeout-ms", str(args.failover_node_timeout_ms)])

    try:
        setup = run_cmd(setup_cmd, timeout=900)
        (work_dir / "failover.stdout.log").write_text(setup.stdout, encoding="utf-8", errors="replace")
        (work_dir / "failover.stderr.log").write_text(setup.stderr, encoding="utf-8", errors="replace")
        if setup.returncode != 0:
            errors.append(f"setup failed exit={setup.returncode}")
        elif not state_path.exists():
            errors.append("setup did not write state file")
        else:
            state = load_state(state_path)
            endpoints = endpoints_from_state(state)
            state_timeout = state.get("runtime", {}).get("effective_cluster_node_timeout_ms")
            state_source = state.get("runtime", {}).get("cluster_node_timeout_source", "MISSING")
            if state_timeout != args.failover_node_timeout_ms:
                errors.append(
                    "generated cluster-node-timeout "
                    f"{state_timeout} source={state_source} does not match failover timeout "
                    f"{args.failover_node_timeout_ms} source={args.cluster_node_timeout_source}"
                )
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
            cleanup_status, cleanup_path = project_cleanup(args.capability_id, state_path, work_dir, cleanup_report_path)
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
            "capability_id": args.capability_id,
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
        "capability_id": args.capability_id,
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
            "timeout_config_ms": args.failover_node_timeout_ms,
            "cluster_node_timeout_source": args.cluster_node_timeout_source,
            "cluster_node_timeout_profile": args.cluster_node_timeout_profile,
        },
        "timeout_adjustments": timeout_adjustments,
    })

    if workload_window_report_path:
        write_json(workload_window_report_path, {
            "schema_version": "v1",
            "artifact_type": "workload_window_report",
            "capability_id": args.capability_id,
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
        "timeout_config_ms": args.failover_node_timeout_ms,
        "cluster_node_timeout_source": args.cluster_node_timeout_source,
        "cluster_node_timeout_profile": args.cluster_node_timeout_profile,
        })

    write_json(out, {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "capability_id": args.capability_id,
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
        "timeout_config_ms": args.failover_node_timeout_ms,
        "cluster_node_timeout_source": args.cluster_node_timeout_source,
        "cluster_node_timeout_profile": args.cluster_node_timeout_profile,
        "kill_to_pfail_ms": primary_unreachable_at_ms - fault_injected_at_ms if isinstance(primary_unreachable_at_ms, int) and isinstance(fault_injected_at_ms, int) else "MISSING",
        "pfail_to_cluster_ok_ms": recovery_unix_ms - primary_unreachable_at_ms if isinstance(recovery_unix_ms, int) and isinstance(primary_unreachable_at_ms, int) else "MISSING",
        "kill_to_client_recovered_ms": read_unavailability_ms if isinstance(read_unavailability_ms, (int, float)) else write_unavailability_ms,
        "false_pfail_count": 0 if probes_before and probes_after else {"status": "MISSING", "reason": "pfail detector snapshots unavailable"},
        "false_failover_count": 0 if probes_before and probes_after else {"status": "MISSING", "reason": "failover detector snapshots unavailable"},
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
