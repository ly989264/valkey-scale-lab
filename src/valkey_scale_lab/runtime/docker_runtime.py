from __future__ import annotations

import json
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__
from valkey_scale_lab.config.simple_yaml import parse_config_file
from valkey_scale_lab.config.validation import normalize_config, validate_semantics

PROJECT = "valkey-scale-lab"
LABEL_PREFIX = "org.valkey-scale-lab"
RUN_DATE = "20260628"


class DockerRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DockerResult:
    stdout: str
    stderr: str
    returncode: int


def run_docker(args: list[str], timeout: int = 120, check: bool = True) -> DockerResult:
    proc = subprocess.run(
        ["docker", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    result = DockerResult(proc.stdout, proc.stderr, int(proc.returncode))
    if check and proc.returncode != 0:
        raise DockerRuntimeError(f"docker {' '.join(args)} failed exit={proc.returncode}: {proc.stderr.strip()}")
    return result


def run_container_cli(container: str, *args: Any, timeout: int = 60, check: bool = True) -> str:
    result = run_docker(["exec", container, "valkey-cli", "-p", "6379", *[str(arg) for arg in args]], timeout=timeout, check=check)
    return result.stdout.strip()


def create_scenario(
    *,
    phase: str,
    scenario: str,
    config_path: str | Path,
    artifacts_dir: str | Path,
    state_out: str | Path,
) -> dict[str, Any]:
    if (phase, scenario) not in {
        ("P03_LOCAL_DOCKER_VALKEY", "cluster_smoke"),
        ("P04_CLUSTER_MANAGEMENT_OPS", "management_ops"),
        ("P05_WORKLOAD_ENGINE", "workload_smoke"),
    }:
        raise DockerRuntimeError(f"runtime does not implement phase/scenario {phase}/{scenario}")
    run_id = _run_id(phase, scenario)

    artifacts = Path(artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    config = normalize_config(parse_config_file(config_path))
    errors = validate_semantics(config)
    if errors:
        message = "; ".join(f"{item['code']}: {item['message']}" for item in errors)
        raise DockerRuntimeError(message)
    cluster = config["cluster"]
    node_count = int(cluster["shards"]) * (1 + int(cluster["replicas_per_shard"]))
    if node_count != 6:
        raise DockerRuntimeError(f"P03 cluster_smoke expects 6 nodes, got {node_count}")
    ports = [int(cluster["port_base"]) + idx for idx in range(node_count)]
    _check_ports_free(ports)

    network_name = _network_name(phase, scenario)
    cleanup_by_label(phase=phase, run_id=run_id)
    run_docker(
        [
            "network",
            "create",
            "--label",
            f"{LABEL_PREFIX}.project={PROJECT}",
            "--label",
            f"{LABEL_PREFIX}.phase={phase}",
            "--label",
            f"{LABEL_PREFIX}.run_id={run_id}",
            network_name,
        ],
        timeout=120,
    )

    nodes = _node_specs(config, phase, scenario, run_id)
    started: list[dict[str, Any]] = []
    try:
        for node in nodes:
            container_id = _start_container(node, network_name, config["runtime"]["valkey_image"], phase, scenario, run_id)
            node["container_id"] = container_id
            node["pid"] = _container_pid(container_id)
            node["container_ip"] = _container_ip(container_id, network_name)
            started.append(node)
        operations = _configure_cluster(nodes)
        if phase == "P04_CLUSTER_MANAGEMENT_OPS":
            operations.extend(_run_management_ops(nodes))
            write_management_ops_report(artifacts / "management_ops_report.json", phase, scenario, run_id, operations)
        if phase == "P05_WORKLOAD_ENGINE":
            write_workload_report(artifacts / "workload_report.json", phase, scenario, run_id, config, nodes)
        state = {
            "schema_version": "v1",
            "cluster_id": run_id,
            "phase_id": phase,
            "scenario": scenario,
            "runtime": {
                "type": "docker",
                "sandbox_network": True,
                "network_name": network_name,
                "run_id": run_id,
                "project": PROJECT,
            },
            "nodes": [
                {
                    "logical_id": node["logical_id"],
                    "host": "127.0.0.1",
                    "client_port": node["client_port"],
                    "az_id": node["az_id"],
                    "role": node["role"],
                    "container_id": node["container_id"],
                    "container_name": node["container_name"],
                    "container_ip": node["container_ip"],
                    "pid": node["pid"],
                    "shard_id": node["shard_id"],
                }
                for node in nodes
            ],
        }
        out = Path(state_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return state
    except Exception:
        cleanup_by_label(phase=phase, run_id=run_id)
        raise


def cleanup_scenario(*, state_path: str | Path, artifacts_dir: str | Path, out_path: str | Path) -> dict[str, Any]:
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    phase = state.get("phase_id", "P03_LOCAL_DOCKER_VALKEY")
    run_id = state.get("runtime", {}).get("run_id", _run_id(str(phase), str(state.get("scenario", "cluster_smoke"))))
    actions = cleanup_by_label(phase=phase, run_id=run_id)
    resources_remaining = owned_resources(phase=phase, run_id=run_id)
    report = {
        "schema_version": "v1",
        "artifact_type": "cleanup_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS" if not resources_remaining else "FAIL",
        "resources_remaining": resources_remaining,
        "cleanup_actions": actions,
        "artifacts_dir": str(artifacts_dir),
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def cleanup_by_label(*, phase: str, run_id: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    label_args = ["--filter", f"label={LABEL_PREFIX}.project={PROJECT}", "--filter", f"label={LABEL_PREFIX}.phase={phase}", "--filter", f"label={LABEL_PREFIX}.run_id={run_id}"]
    containers = _docker_ids(["ps", "-a", "-q", *label_args])
    for cid in containers:
        stop = run_docker(["stop", "-t", "5", cid], timeout=30, check=False)
        actions.append({"type": "container", "id": cid, "action": "stop", "status": "PASS" if stop.returncode == 0 else "SKIPPED_WITH_REASON", "stderr": stop.stderr.strip()})
        rm = run_docker(["rm", "-f", cid], timeout=30, check=False)
        actions.append({"type": "container", "id": cid, "action": "remove", "status": "PASS" if rm.returncode == 0 else "FAIL", "stderr": rm.stderr.strip()})
    networks = _docker_ids(["network", "ls", "-q", *label_args])
    for nid in networks:
        rm = run_docker(["network", "rm", nid], timeout=30, check=False)
        actions.append({"type": "network", "id": nid, "action": "remove", "status": "PASS" if rm.returncode == 0 else "FAIL", "stderr": rm.stderr.strip()})
    return actions


def owned_resources(*, phase: str, run_id: str) -> list[dict[str, Any]]:
    label_args = ["--filter", f"label={LABEL_PREFIX}.project={PROJECT}", "--filter", f"label={LABEL_PREFIX}.phase={phase}", "--filter", f"label={LABEL_PREFIX}.run_id={run_id}"]
    resources: list[dict[str, Any]] = []
    for cid in _docker_ids(["ps", "-a", "-q", *label_args]):
        resources.append({"type": "container", "id": cid})
    for nid in _docker_ids(["network", "ls", "-q", *label_args]):
        resources.append({"type": "network", "id": nid})
    return resources


def _docker_ids(args: list[str]) -> list[str]:
    result = run_docker(args, timeout=30, check=False)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _node_specs(config: dict[str, Any], phase: str, scenario: str, run_id: str | None = None) -> list[dict[str, Any]]:
    cluster = config["cluster"]
    azs = list(config["network"]["azs"])
    shards = int(cluster["shards"])
    replicas = int(cluster["replicas_per_shard"])
    specs: list[dict[str, Any]] = []
    ordinal = 0
    for shard in range(shards):
        shard_id = f"shard-{shard:04d}"
        specs.append(_spec(cluster, phase, scenario, ordinal, shard_id, "primary", azs[shard % len(azs)], run_id))
        ordinal += 1
    for shard in range(shards):
        for replica in range(replicas):
            shard_id = f"shard-{shard:04d}"
            az = azs[(shard + replica + 1) % len(azs)]
            specs.append(_spec(cluster, phase, scenario, ordinal, shard_id, f"replica-{replica:02d}", az, run_id))
            ordinal += 1
    return specs


def _spec(cluster: dict[str, Any], phase: str, scenario: str, ordinal: int, shard_id: str, role_suffix: str, az_id: str, run_id: str | None = None) -> dict[str, Any]:
    role = "primary" if role_suffix == "primary" else "replica"
    logical_id = f"{shard_id}-{role_suffix}"
    safe_run = (run_id or _run_id(phase, scenario)).lower().replace("_", "-")
    return {
        "logical_id": logical_id,
        "shard_id": shard_id,
        "role": role,
        "az_id": az_id,
        "ordinal": ordinal,
        "client_port": int(cluster["port_base"]) + ordinal,
        "container_name": f"vslab-{safe_run}-{logical_id}",
        "phase": phase,
        "scenario": scenario,
    }


def _start_container(node: dict[str, Any], network_name: str, image: str, phase: str, scenario: str, run_id: str) -> str:
    args = [
        "run",
        "-d",
        "--name",
        node["container_name"],
        "--network",
        network_name,
        "--label",
        f"{LABEL_PREFIX}.project={PROJECT}",
        "--label",
        f"{LABEL_PREFIX}.phase={phase}",
        "--label",
        f"{LABEL_PREFIX}.run_id={run_id}",
        "--label",
        f"{LABEL_PREFIX}.scenario={scenario}",
        "--label",
        f"{LABEL_PREFIX}.logical_id={node['logical_id']}",
        "-p",
        f"127.0.0.1:{node['client_port']}:6379",
        image,
        "valkey-server",
        "--port",
        "6379",
        "--cluster-enabled",
        "yes",
        "--cluster-config-file",
        "nodes.conf",
        "--cluster-node-timeout",
        "5000",
        "--appendonly",
        "no",
        "--protected-mode",
        "no",
        "--bind",
        "0.0.0.0",
        "--cluster-announce-port",
        "6379",
        "--cluster-announce-bus-port",
        "16379",
    ]
    return run_docker(args, timeout=180).stdout.strip()


def _configure_cluster(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    _wait_for_nodes(nodes)
    first = nodes[0]
    meet_started = time.monotonic()
    for node in nodes[1:]:
        run_container_cli(first["container_name"], "CLUSTER", "MEET", node["container_ip"], "6379", timeout=30)
    _wait_cluster_known(nodes, expected=len(nodes), timeout=90)
    operations.append(_operation("meet", "PASS", meet_started, {"nodes_joined": len(nodes) - 1, "cluster_known_nodes": len(nodes)}))

    primaries = [node for node in nodes if node["role"] == "primary"]
    replicas = [node for node in nodes if node["role"] == "replica"]
    slot_ranges = [(5461, 10922), (0, 5460), (10923, 16383)]
    slots_started = time.monotonic()
    for primary, (start, end) in zip(primaries, slot_ranges):
        _add_slots(primary["container_name"], start, end)
    _wait_cluster_slots_assigned(nodes, timeout=90)
    operations.append(_operation("add_slots", "PASS", slots_started, {"slots_assigned": 16384, "primary_count": len(primaries)}))

    replicate_started = time.monotonic()
    primary_ids = {node["shard_id"]: run_container_cli(node["container_name"], "CLUSTER", "MYID") for node in primaries}
    for replica in replicas:
        master_id = primary_ids[replica["shard_id"]]
        run_container_cli(replica["container_name"], "CLUSTER", "REPLICATE", master_id, timeout=30)
    _wait_cluster_ok(nodes, timeout=90)
    operations.append(_operation("add_replica", "PASS", replicate_started, {"replica_count": len(replicas), "cluster_state": "ok"}))
    return operations


def _wait_for_nodes(nodes: list[dict[str, Any]], timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready = 0
        for node in nodes:
            try:
                if run_container_cli(node["container_name"], "PING", timeout=5) == "PONG":
                    ready += 1
            except Exception:
                pass
        if ready == len(nodes):
            return
        time.sleep(1)
    raise DockerRuntimeError("Valkey containers did not become ready")


def _wait_cluster_known(nodes: list[dict[str, Any]], expected: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        known = []
        for node in nodes:
            try:
                info = run_container_cli(node["container_name"], "CLUSTER", "INFO", timeout=5)
                known.append(_info_value(info, "cluster_known_nodes") == str(expected))
            except Exception:
                known.append(False)
        if all(known):
            return
        time.sleep(1)
    raise DockerRuntimeError("cluster meet did not converge to expected node count")


def _wait_cluster_slots_assigned(nodes: list[dict[str, Any]], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assigned = []
        for node in nodes:
            try:
                info = run_container_cli(node["container_name"], "CLUSTER", "INFO", timeout=5)
                assigned.append(_info_value(info, "cluster_slots_assigned") == "16384")
            except Exception:
                assigned.append(False)
        if all(assigned):
            return
        time.sleep(1)
    raise DockerRuntimeError("cluster slots were not fully assigned")


def _wait_cluster_ok(nodes: list[dict[str, Any]], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        states = []
        for node in nodes:
            try:
                info = run_container_cli(node["container_name"], "CLUSTER", "INFO", timeout=5)
                states.append(_info_value(info, "cluster_state") == "ok")
            except Exception:
                states.append(False)
        if all(states):
            return
        time.sleep(1)
    raise DockerRuntimeError("cluster did not reach ok state")


def _run_management_ops(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    check_started = time.monotonic()
    _wait_cluster_ok(nodes, timeout=30)
    operations.append(_operation("convergence_check", "PASS", check_started, {"cluster_state": "ok"}))

    nodes_started = time.monotonic()
    cluster_nodes = run_container_cli(nodes[0]["container_name"], "CLUSTER", "NODES", timeout=30)
    operations.append(
        _operation(
            "cluster_nodes",
            "PASS",
            nodes_started,
            {"line_count": len([line for line in cluster_nodes.splitlines() if line.strip()])},
        )
    )

    info_started = time.monotonic()
    cluster_info = run_container_cli(nodes[0]["container_name"], "CLUSTER", "INFO", timeout=30)
    operations.append(
        _operation(
            "cluster_info",
            "PASS",
            info_started,
            {
                "cluster_state": _info_value(cluster_info, "cluster_state"),
                "cluster_known_nodes": _info_value(cluster_info, "cluster_known_nodes"),
            },
        )
    )

    for name, reason in [
        ("remove_node", "P04 records taxonomy only; destructive removal is deferred until a dedicated lifecycle phase."),
        ("reshard", "P04 smoke cluster keeps slot ownership stable for wrapper data-path proof."),
        ("rebalance", "Valkey cluster rebalance orchestration is deferred until management expansion."),
        ("rolling_restart", "Restart orchestration is deferred to later stability/fault phases."),
    ]:
        operations.append(
            {
                "operation": name,
                "status": "SKIPPED_WITH_REASON",
                "duration_seconds": 0.0,
                "reason": reason,
                "started_at": "2026-06-28T00:00:00Z",
                "finished_at": "2026-06-28T00:00:00Z",
            }
        )
    return operations


def write_management_ops_report(path: Path, phase: str, scenario: str, run_id: str, operations: list[dict[str, Any]]) -> None:
    passed = sum(1 for op in operations if op.get("status") == "PASS")
    skipped = sum(1 for op in operations if op.get("status") == "SKIPPED_WITH_REASON")
    failed = sum(1 for op in operations if op.get("status") == "FAIL")
    report = {
        "schema_version": "v1",
        "artifact_type": "management_ops_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS" if failed == 0 else "FAIL",
        "scenario": scenario,
        "operations": operations,
        "summary": {
            "total_operations": len(operations),
            "passed": passed,
            "failed": failed,
            "skipped_with_reason": skipped,
            "error_taxonomy": {
                "PASS": "operation completed and convergence was observed",
                "FAIL": "operation attempted but did not complete or converge",
                "SKIPPED_WITH_REASON": "operation intentionally not executed with an explicit reason",
                "UNSUPPORTED": "operation unavailable in current runtime scope",
            },
            "cluster_safe_for_cleanup": failed == 0,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_workload_report(path: Path, phase: str, scenario: str, run_id: str, config: dict[str, Any], nodes: list[dict[str, Any]]) -> None:
    workload = config.get("workload", {})
    requested_qps = float(workload.get("uniform_qps", 0)) + float(workload.get("hotspot_qps", 0))
    read_ratio = float(workload.get("read_ratio", 0.8))
    write_ratio = float(workload.get("write_ratio", 0.2))
    pipeline = int(workload.get("pipeline", 1) or 1)
    total_ops = 100
    write_ops = max(1, int(total_ops * write_ratio))
    read_ops = total_ops - write_ops
    key_count = max(10, write_ops)
    target = nodes[0]["container_name"]
    latencies_ms: list[float] = []
    error_items: list[dict[str, Any]] = []
    timeout_count = 0
    started = time.monotonic()

    for idx in range(write_ops):
        key = f"{{vslab-probe}}:workload:{idx % key_count}"
        value = f"value-{idx}"
        op_started = time.monotonic()
        try:
            result = run_container_cli(target, "SET", key, value, timeout=10)
            latencies_ms.append((time.monotonic() - op_started) * 1000)
            if result.upper() != "OK":
                error_items.append({"operation": "SET", "key": key, "error": f"unexpected result {result!r}"})
        except subprocess.TimeoutExpired:
            timeout_count += 1
            error_items.append({"operation": "SET", "key": key, "error": "timeout"})
        except Exception as exc:  # noqa: BLE001
            error_items.append({"operation": "SET", "key": key, "error": repr(exc)})

    for idx in range(read_ops):
        key = f"{{vslab-probe}}:workload:{idx % key_count}"
        op_started = time.monotonic()
        try:
            _ = run_container_cli(target, "GET", key, timeout=10)
            latencies_ms.append((time.monotonic() - op_started) * 1000)
        except subprocess.TimeoutExpired:
            timeout_count += 1
            error_items.append({"operation": "GET", "key": key, "error": "timeout"})
        except Exception as exc:  # noqa: BLE001
            error_items.append({"operation": "GET", "key": key, "error": repr(exc)})

    duration = max(time.monotonic() - started, 0.000001)
    completed_ops = len(latencies_ms)
    report = {
        "schema_version": "v1",
        "artifact_type": "workload_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS" if not error_items else "FAIL",
        "scenario": scenario,
        "requested_qps": requested_qps,
        "achieved_qps": round(completed_ops / duration, 6),
        "operation_counts": {
            "requested_total": total_ops,
            "completed_total": completed_ops,
            "writes": write_ops,
            "reads": read_ops,
        },
        "workload_model": {
            "read_ratio": read_ratio,
            "write_ratio": write_ratio,
            "uniform_qps": workload.get("uniform_qps", 0),
            "hotspot_qps": workload.get("hotspot_qps", 0),
            "hotspot_key_fraction": workload.get("hotspot_key_fraction", "MISSING"),
            "pipeline": pipeline,
            "keyspace": key_count,
        },
        "timing_windows": [
            {
                "name": str(workload.get("timing", "all_run")),
                "status": "PASS",
                "duration_seconds": round(duration, 6),
                "operations": completed_ops,
            },
            {
                "name": "before_fault",
                "status": "SKIPPED_WITH_REASON",
                "reason": "P05 workload_smoke has no fault window.",
            },
            {
                "name": "during_fault",
                "status": "SKIPPED_WITH_REASON",
                "reason": "P05 workload_smoke has no fault window.",
            },
            {
                "name": "after_recovery",
                "status": "SKIPPED_WITH_REASON",
                "reason": "P05 workload_smoke has no recovery window.",
            },
        ],
        "latency": _latency_summary(latencies_ms),
        "errors": {
            "total": len(error_items),
            "timeout_count": timeout_count,
            "items": error_items,
            "classification": "none" if not error_items else "data_path_error",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _latency_summary(values_ms: list[float]) -> dict[str, Any]:
    if not values_ms:
        missing = {"status": "MISSING", "reason": "no completed workload operations"}
        return {"unit": "ms", "p50": missing, "p95": missing, "p99": missing, "sample_count": 0}
    ordered = sorted(values_ms)
    return {
        "unit": "ms",
        "p50": round(_percentile(ordered, 50), 6),
        "p95": round(_percentile(ordered, 95), 6),
        "p99": round(_percentile(ordered, 99), 6),
        "min": round(ordered[0], 6),
        "max": round(ordered[-1], 6),
        "sample_count": len(ordered),
    }


def _percentile(ordered: list[float], percentile: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    rank = (percentile / 100.0) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _operation(name: str, status: str, started_monotonic: float, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation": name,
        "status": status,
        "duration_seconds": round(time.monotonic() - started_monotonic, 6),
        "started_at": "2026-06-28T00:00:00Z",
        "finished_at": "2026-06-28T00:00:00Z",
        "details": details,
    }


def _add_slots(container: str, start: int, end: int) -> None:
    batch: list[int] = []
    for slot in range(start, end + 1):
        batch.append(slot)
        if len(batch) == 500:
            run_container_cli(container, "CLUSTER", "ADDSLOTS", *batch, timeout=60)
            batch = []
    if batch:
        run_container_cli(container, "CLUSTER", "ADDSLOTS", *batch, timeout=60)


def _info_value(info: str, key: str) -> str | None:
    for line in info.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return None


def _container_pid(container_id: str) -> int:
    text = run_docker(["inspect", "-f", "{{.State.Pid}}", container_id], timeout=30).stdout.strip()
    return int(text)


def _container_ip(container_id: str, network_name: str) -> str:
    template = "{{range .NetworkSettings.Networks}}{{if eq .NetworkID \"" + _network_id(network_name) + "\"}}{{.IPAddress}}{{end}}{{end}}"
    ip = run_docker(["inspect", "-f", template, container_id], timeout=30).stdout.strip()
    if ip:
        return ip
    return run_docker(["inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container_id], timeout=30).stdout.strip()


def _network_id(network_name: str) -> str:
    return run_docker(["network", "inspect", "-f", "{{.Id}}", network_name], timeout=30).stdout.strip()


def _network_name(phase: str, scenario: str) -> str:
    return f"vslab-{phase.lower().replace('_', '-')}-{scenario}"


def _check_ports_free(ports: list[int]) -> None:
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as exc:
                raise DockerRuntimeError(f"port 127.0.0.1:{port} is not available: {exc}") from exc


def _run_id(phase: str, scenario: str) -> str:
    return f"{phase}-{scenario}-{RUN_DATE}"
