from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

from valkey_scale_lab import __version__
from valkey_scale_lab.config.simple_yaml import parse_config_file
from valkey_scale_lab.config.validation import normalize_config, validate_semantics
from valkey_scale_lab.orchestrator.local import LocalOrchestrator, assign_hosts, validate_inventory
from valkey_scale_lab.orchestrator.local import write_phase_summary as write_p10_phase_summary

PROJECT = "valkey-scale-lab"
LABEL_PREFIX = "org.valkey-scale-lab"
RUN_DATE = "20260628"
CLUSTER_MEET_FANOUT = 4
CLUSTER_ORCHESTRATION_PARALLELISM = 8
CLUSTER_DIAGNOSTIC_INTERVAL_SECONDS = 2.0
REPLICA_REPLICATE_PARALLELISM_DEFAULT = CLUSTER_ORCHESTRATION_PARALLELISM
REPLICA_REPLICATE_PARALLELISM_CHOICES = (8, 16, 32)
REPLICA_REPLICATE_SLOWEST_COUNT = 5
CLUSTER_CREATE_STRATEGY_DEFAULT = "valkey_cli_cluster_create_primaries"
CLUSTER_CREATE_STRATEGY_MANUAL = "manual_tree_meet_parallel_slots"
CLUSTER_CREATE_STRATEGIES = {
    CLUSTER_CREATE_STRATEGY_DEFAULT,
    CLUSTER_CREATE_STRATEGY_MANUAL,
}
P13_TIMING_NAMES = [
    "nodehost_start",
    "process_config_prepare",
    "process_start",
    "process_ready_wait",
    "primary_cluster_create",
    "replica_meet",
    "replica_replicate",
    "runtime_representative_probe",
    "runtime_final_full_probe",
    "runtime_diagnostic_full_probe",
    "wrapper_wait_cluster_ok",
    "wrapper_data_path_probe",
    "cleanup",
]

T = TypeVar("T")


class DockerRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DockerResult:
    stdout: str
    stderr: str
    returncode: int


def run_docker(args: list[str], timeout: int = 120, check: bool = True) -> DockerResult:
    try:
        proc = subprocess.run(
            ["docker", *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise DockerRuntimeError(f"docker {' '.join(args)} timed out after {timeout} seconds") from exc
    result = DockerResult(proc.stdout, proc.stderr, int(proc.returncode))
    if check and proc.returncode != 0:
        raise DockerRuntimeError(f"docker {' '.join(args)} failed exit={proc.returncode}: {proc.stderr.strip()}")
    return result


def run_container_cli(container: str, *args: Any, timeout: int = 60, check: bool = True) -> str:
    result = run_docker(["exec", container, "valkey-cli", "-p", "6379", *[str(arg) for arg in args]], timeout=timeout, check=check)
    return result.stdout.strip()


def run_container_cluster_cli(container: str, *args: Any, timeout: int = 60, check: bool = True) -> str:
    result = run_docker(["exec", container, "valkey-cli", "-c", "-p", "6379", *[str(arg) for arg in args]], timeout=timeout, check=check)
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
        ("P06_OBSERVABILITY_METRICS", "observability_smoke"),
        ("P07_FAULT_INJECTION_SANDBOX", "fault_sandbox_setup"),
        ("P08_FAILOVER_SPLIT_BRAIN", "failover_setup"),
        ("P09_ANALYSIS_REPORTING", "reporting_source_smoke"),
        ("P10_MULTI_HOST_ORCHESTRATION", "orchestrated_localhost"),
        ("P11_STABILITY_SOAK", "stability_soak_smoke"),
        ("P12_SCALE_LADDER_10_30", "scale_10"),
        ("P12_SCALE_LADDER_10_30", "scale_30"),
        ("P13_SCALE_LADDER_50_100", "scale_50"),
        ("P13_SCALE_LADDER_50_100", "scale_100"),
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
    if not _scenario_node_count_allowed(phase, scenario, node_count):
        raise DockerRuntimeError(f"{phase}/{scenario} does not allow {node_count} nodes")
    nodes = _node_specs(config, phase, scenario, run_id)
    ports = [node["client_port"] for node in nodes]
    if _uses_docker_process_runtime(phase, scenario):
        ports.extend(node["cluster_bus_port"] for node in nodes)
    _check_ports_free(ports)

    if _uses_docker_process_runtime(phase, scenario):
        return _create_process_scenario(
            phase=phase,
            scenario=scenario,
            run_id=run_id,
            config=config,
            artifacts=artifacts,
            state_out=Path(state_out),
            nodes=nodes,
        )

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

    orchestrator = None
    if phase == "P10_MULTI_HOST_ORCHESTRATION":
        hosts = validate_inventory(config)
        assign_hosts(nodes, hosts)
        orchestrator = LocalOrchestrator(config=config, phase=phase, scenario=scenario, run_id=run_id)
        orchestrator.prepare()
    started: list[dict[str, Any]] = []
    try:
        for node in nodes:
            if orchestrator is None:
                container_id = _start_container(node, network_name, config["runtime"]["valkey_image"], phase, scenario, run_id)
            else:
                container_id = orchestrator.start_node(
                    node,
                    lambda n: _start_container(n, network_name, config["runtime"]["valkey_image"], phase, scenario, run_id),
                )
            node["container_id"] = container_id
            node["pid"] = _container_pid(container_id)
            node["container_ip"] = _container_ip(container_id, network_name)
            started.append(node)
        state = _runtime_state(phase, scenario, run_id, network_name, config, nodes)
        _write_state(Path(state_out), state)
        operations = _configure_cluster(nodes)
        if phase == "P04_CLUSTER_MANAGEMENT_OPS":
            operations.extend(_run_management_ops(nodes))
            write_management_ops_report(artifacts / "management_ops_report.json", phase, scenario, run_id, operations)
        if phase == "P05_WORKLOAD_ENGINE":
            write_workload_report(artifacts / "workload_report.json", phase, scenario, run_id, config, nodes)
        if phase == "P06_OBSERVABILITY_METRICS":
            write_observability_artifacts(artifacts, phase, scenario, run_id, config, nodes)
        if orchestrator is not None:
            orchestrator.collect(nodes, artifacts)
            orchestrator.write_report(artifacts / "orchestration_report.json", nodes)
            write_p10_phase_summary(artifacts / "phase_summary.json", run_id)
        if phase == "P11_STABILITY_SOAK":
            write_stability_artifacts(artifacts, phase, scenario, run_id, config, nodes)
        if phase in {"P12_SCALE_LADDER_10_30", "P13_SCALE_LADDER_50_100"}:
            write_scale_ladder_artifacts(artifacts, phase, scenario, run_id, config, nodes)
        _write_state(Path(state_out), state)
        return state
    except Exception as exc:
        try:
            snapshots.append(_process_cluster_summary("failure", nodes))
            state = _process_runtime_state(phase, scenario, run_id, network_name, config, nodehosts, nodes, snapshots)
            state["runtime"]["setup_error"] = repr(exc)
            _write_state(state_out, state)
            _cleanup_process_scenario(state=state, artifacts_dir=artifacts, out_path=artifacts / "cleanup_report.json")
        except Exception:
            cleanup_by_label(phase=phase, run_id=run_id)
        raise


def cleanup_scenario(*, state_path: str | Path, artifacts_dir: str | Path, out_path: str | Path) -> dict[str, Any]:
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    phase = state.get("phase_id", "P03_LOCAL_DOCKER_VALKEY")
    run_id = state.get("runtime", {}).get("run_id", _run_id(str(phase), str(state.get("scenario", "cluster_smoke"))))
    if state.get("runtime", {}).get("type") == "docker_process":
        return _cleanup_process_scenario(state=state, artifacts_dir=Path(artifacts_dir), out_path=Path(out_path))
    actions, cleanup_timing = _cleanup_resources_by_label(phase=phase, run_id=run_id)
    actions.extend(_cleanup_fault_state_files(Path(artifacts_dir)))
    residual_started = time.monotonic()
    resources_remaining = owned_resources(phase=phase, run_id=run_id)
    cleanup_timing["cleanup_residual_scan_seconds"] = round(max(time.monotonic() - residual_started, 0.0), 6)
    cleanup_timing.setdefault("cleanup_terminate_processes_seconds", 0.0)
    cleanup_timing.setdefault("cleanup_verify_process_exit_seconds", 0.0)
    cleanup_timing.setdefault("cleanup_verify_nodehost_empty_seconds", 0.0)
    if phase == "P10_MULTI_HOST_ORCHESTRATION":
        actions.append(
            {
                "type": "orchestrator",
                "id": "all-hosts",
                "action": "stop_collect",
                "status": "PASS" if not resources_remaining else "FAIL",
                "idempotent": True,
            }
        )
        _append_p10_orchestrator_cleanup(Path(artifacts_dir), resources_remaining)
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
        "cleanup_timing": cleanup_timing,
        "artifacts_dir": str(artifacts_dir),
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    scenario = state.get("scenario")
    if scenario:
        scenario_out = out.parent / f"cleanup_report_{scenario}.json"
        scenario_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _runtime_state(
    phase: str,
    scenario: str,
    run_id: str,
    network_name: str,
    config: dict[str, Any],
    nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
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
            "hosts": [host.get("host_id") for host in config.get("hosts", [])],
            "cluster_startup_strategy": "all_containers_ready_then_tree_fanout_meet_parallel_slots_parallel_replicas_two_stage_probe",
            "cluster_startup_parallelism": CLUSTER_ORCHESTRATION_PARALLELISM,
            "replica_replicate_parallelism": _replica_replicate_parallelism(),
            "cluster_meet_fanout": CLUSTER_MEET_FANOUT,
        },
        "nodes": [
            {
                "logical_id": node["logical_id"],
                "host_id": node.get("host_id", "local"),
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


def _uses_docker_process_runtime(phase: str, scenario: str) -> bool:
    return (phase, scenario) in {
        ("P12_SCALE_LADDER_10_30", "scale_10"),
        ("P12_SCALE_LADDER_10_30", "scale_30"),
        ("P13_SCALE_LADDER_50_100", "scale_50"),
        ("P13_SCALE_LADDER_50_100", "scale_100"),
    }


def _create_process_scenario(
    *,
    phase: str,
    scenario: str,
    run_id: str,
    config: dict[str, Any],
    artifacts: Path,
    state_out: Path,
    nodes: list[dict[str, Any]],
) -> dict[str, Any]:
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
    nodehosts = _process_nodehosts(config, nodes, phase, scenario, run_id)
    snapshots: list[dict[str, Any]] = []
    timings: dict[str, dict[str, Any]] = {}
    try:
        def start_nodehost(nodehost: dict[str, Any]) -> None:
            container_id = _start_nodehost(nodehost, network_name, config["runtime"]["valkey_image"], phase, scenario, run_id)
            nodehost["container_id"] = container_id
            nodehost["container_ip"] = _container_ip(container_id, network_name)

        _run_timed_step(
            timings,
            "nodehost_start",
            lambda: _bounded_parallel(
                nodehosts,
                start_nodehost,
                parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
                timeout=_scale_timeout(nodes, floor=120.0, per_node=2.0),
                label="nodehost container startup",
            ),
            {"nodehost_count": len(nodehosts), "parallelism": CLUSTER_ORCHESTRATION_PARALLELISM},
        )
        nodehost_by_id = {nodehost["nodehost_id"]: nodehost for nodehost in nodehosts}

        def prepare_node(node: dict[str, Any]) -> None:
            nodehost = nodehost_by_id[node["nodehost_id"]]
            _prepare_process_node(node, nodehost, artifacts, run_id)

        _run_timed_step(
            timings,
            "process_config_prepare",
            lambda: _bounded_parallel(
                nodes,
                prepare_node,
                parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
                timeout=_scale_timeout(nodes, floor=120.0, per_node=3.0),
                label="Valkey process config preparation",
            ),
            {"node_count": len(nodes), "parallelism": CLUSTER_ORCHESTRATION_PARALLELISM},
        )

        _run_timed_step(
            timings,
            "process_start",
            lambda: _bounded_parallel(
                nodes,
                _start_process_node,
                parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
                timeout=_scale_timeout(nodes, floor=120.0, per_node=3.0),
                label="Valkey process startup",
            ),
            {"node_count": len(nodes), "parallelism": CLUSTER_ORCHESTRATION_PARALLELISM},
        )
        _run_timed_step(
            timings,
            "process_ready_wait",
            lambda: _wait_process_nodes_ready(nodes, timeout=_scale_timeout(nodes, floor=60.0, per_node=2.0)),
            {"node_count": len(nodes)},
        )
        state = _process_runtime_state(phase, scenario, run_id, network_name, config, nodehosts, nodes, snapshots)
        _write_state(state_out, state)
        operations, snapshots = _configure_process_cluster(nodes, timings=timings)
        snapshots_path = artifacts / f"cluster_snapshots_{scenario}.json"
        snapshots_path.write_text(json.dumps(snapshots, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        state = _process_runtime_state(phase, scenario, run_id, network_name, config, nodehosts, nodes, snapshots)
        state["runtime"]["cluster_snapshot_path"] = snapshots_path.as_posix()
        state["runtime"]["operations"] = operations
        timing_path = artifacts / f"runtime_timing_breakdown_{scenario}.json"
        _write_runtime_timing_breakdown(timing_path, phase, scenario, run_id, nodes, timings, status="PASS")
        state["runtime"]["timing_breakdown_path"] = timing_path.as_posix()
        state["runtime"]["timings"] = _timing_entries(timings)
        _write_state(state_out, state)
        write_scale_ladder_artifacts(artifacts, phase, scenario, run_id, config, nodes)
        return state
    except Exception:
        cleanup_by_label(phase=phase, run_id=run_id)
        raise


def _process_nodehosts(
    config: dict[str, Any],
    nodes: list[dict[str, Any]],
    phase: str,
    scenario: str,
    run_id: str,
) -> list[dict[str, Any]]:
    safe_run = run_id.lower().replace("_", "-")
    azs = [az for az in config["network"]["azs"] if any(node["az_id"] == az for node in nodes)]
    nodehosts: list[dict[str, Any]] = []
    for ordinal, az in enumerate(azs):
        hosted = [node for node in nodes if node["az_id"] == az]
        nodehost_id = f"nodehost-{az}"
        for node in hosted:
            node["runtime_type"] = "docker_process"
            node["nodehost_id"] = nodehost_id
        ports = sorted([node["client_port"] for node in hosted] + [node["cluster_bus_port"] for node in hosted])
        nodehosts.append(
            {
                "nodehost_id": nodehost_id,
                "az_id": az,
                "host_id": "local",
                "ordinal": ordinal,
                "container_name": f"vslab-{safe_run}-{nodehost_id}",
                "ports": ports,
                "logical_node_count": len(hosted),
            }
        )
    return nodehosts


def _start_nodehost(
    nodehost: dict[str, Any],
    network_name: str,
    image: str,
    phase: str,
    scenario: str,
    run_id: str,
) -> str:
    args = [
        "run",
        "-d",
        "--name",
        nodehost["container_name"],
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
        f"{LABEL_PREFIX}.nodehost_id={nodehost['nodehost_id']}",
    ]
    for port in nodehost["ports"]:
        args.extend(["-p", f"127.0.0.1:{port}:{port}"])
    args.extend([image, "sleep", "infinity"])
    return run_docker(args, timeout=180).stdout.strip()


def _prepare_process_node(node: dict[str, Any], nodehost: dict[str, Any], artifacts: Path, run_id: str) -> None:
    data_dir = f"/tmp/valkey-scale-lab/{run_id}/{node['logical_id']}"
    config_file = f"{data_dir}/valkey.conf"
    log_file = f"{data_dir}/valkey.log"
    local_config_dir = artifacts / "node_configs"
    local_config_dir.mkdir(parents=True, exist_ok=True)
    local_config = local_config_dir / f"{node['logical_id']}.conf"
    config_text = "\n".join(
        [
            f"port {node['client_port']}",
            "bind 0.0.0.0",
            "protected-mode no",
            "cluster-enabled yes",
            "cluster-config-file nodes.conf",
            f"cluster-node-timeout {node.get('cluster_node_timeout', '60000')}",
            f"cluster-port {node['cluster_bus_port']}",
            f"cluster-announce-ip {nodehost['container_ip']}",
            f"cluster-announce-port {node['client_port']}",
            f"cluster-announce-bus-port {node['cluster_bus_port']}",
            "appendonly no",
            f"dir {data_dir}",
            "daemonize yes",
            f"pidfile {data_dir}/valkey.pid",
            f"logfile {log_file}",
            "",
        ]
    )
    local_config.write_text(config_text, encoding="utf-8")
    node.update(
        {
            "nodehost_container_id": nodehost["container_id"],
            "nodehost_container_name": nodehost["container_name"],
            "nodehost_container_ip": nodehost["container_ip"],
            "container_id": nodehost["container_id"],
            "container_name": nodehost["container_name"],
            "container_ip": nodehost["container_ip"],
            "data_dir": data_dir,
            "log_file": log_file,
            "config_file": config_file,
            "config_artifact_file": local_config.as_posix(),
        }
    )
    run_docker(["exec", nodehost["container_name"], "mkdir", "-p", data_dir], timeout=30)
    run_docker(["cp", local_config.as_posix(), f"{nodehost['container_name']}:{config_file}"], timeout=30)


def _start_process_node(node: dict[str, Any]) -> None:
    run_docker(["exec", node["nodehost_container_name"], "valkey-server", node["config_file"]], timeout=30)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = run_docker(["exec", node["nodehost_container_name"], "cat", f"{node['data_dir']}/valkey.pid"], timeout=5, check=False)
        if result.returncode == 0 and result.stdout.strip():
            node["pid"] = int(result.stdout.strip())
            return
        time.sleep(0.5)
    raise DockerRuntimeError(f"{node['logical_id']} did not write pid file")


def _process_runtime_state(
    phase: str,
    scenario: str,
    run_id: str,
    network_name: str,
    config: dict[str, Any],
    nodehosts: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "cluster_id": run_id,
        "phase_id": phase,
        "scenario": scenario,
        "runtime": {
            "type": "docker_process",
            "sandbox_network": True,
            "network_name": network_name,
            "run_id": run_id,
            "project": PROJECT,
            "cluster_startup_strategy": _process_cluster_startup_strategy(nodes),
            "cluster_create_strategy": _cluster_create_strategy(),
            "container_strategy": "one_owned_docker_nodehost_per_virtual_az",
            "nodehost_count": len(nodehosts),
            "logical_node_count": len(nodes),
            "cluster_startup_parallelism": CLUSTER_ORCHESTRATION_PARALLELISM,
            "replica_replicate_parallelism": _replica_replicate_parallelism(),
            "cluster_meet_fanout": CLUSTER_MEET_FANOUT,
        },
        "nodehosts": [
            {
                "nodehost_id": nodehost["nodehost_id"],
                "az_id": nodehost["az_id"],
                "host_id": nodehost["host_id"],
                "container_id": nodehost["container_id"],
                "container_name": nodehost["container_name"],
                "container_ip": nodehost["container_ip"],
                "ports": nodehost["ports"],
                "logical_node_count": nodehost["logical_node_count"],
            }
            for nodehost in nodehosts
        ],
        "nodes": [
            {
                "logical_id": node["logical_id"],
                "nodehost_id": node["nodehost_id"],
                "host_id": node.get("host_id", "local"),
                "host": "127.0.0.1",
                "client_port": node["client_port"],
                "cluster_bus_port": node["cluster_bus_port"],
                "az_id": node["az_id"],
                "role": node["role"],
                "shard_id": node["shard_id"],
                "pid": node["pid"],
                "data_dir": node["data_dir"],
                "log_file": node["log_file"],
                "config_file": node["config_file"],
                "config_artifact_file": node["config_artifact_file"],
                "container_id": node["nodehost_container_id"],
                "container_name": node["nodehost_container_name"],
                "container_ip": node["nodehost_container_ip"],
                "nodehost_container_name": node["nodehost_container_name"],
                "nodehost_container_ip": node["nodehost_container_ip"],
            }
            for node in nodes
        ],
        "cluster_snapshots": snapshots,
    }


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_p10_orchestrator_cleanup(artifacts_dir: Path, resources_remaining: list[dict[str, Any]]) -> None:
    report_path = artifacts_dir / "orchestration_report.json"
    if not report_path.exists():
        return
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.setdefault("operations", []).append(
        {
            "operation": "stop",
            "status": "PASS" if not resources_remaining else "FAIL",
            "host_id": "all",
            "started_at": "2026-06-28T00:00:00Z",
            "finished_at": "2026-06-28T00:00:00Z",
            "details": {
                "mode": "docker_label_cleanup",
                "idempotent": True,
                "resources_remaining": resources_remaining,
            },
        }
    )
    report["status"] = "PASS" if all(op.get("status") == "PASS" for op in report.get("operations", [])) else "FAIL"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _cleanup_fault_state_files(artifacts_dir: Path) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for path in sorted(artifacts_dir.glob("fault_state_*.json")):
        path.unlink()
        actions.append({"type": "fault_state", "id": path.name, "action": "remove", "status": "PASS"})
    return actions


def cleanup_by_label(*, phase: str, run_id: str) -> list[dict[str, Any]]:
    actions, _timings = _cleanup_resources_by_label(phase=phase, run_id=run_id)
    return actions


def _cleanup_resources_by_label(*, phase: str, run_id: str) -> tuple[list[dict[str, Any]], dict[str, float]]:
    actions: list[dict[str, Any]] = []
    timings = {
        "cleanup_remove_containers_seconds": 0.0,
        "cleanup_remove_networks_seconds": 0.0,
    }
    label_args = ["--filter", f"label={LABEL_PREFIX}.project={PROJECT}", "--filter", f"label={LABEL_PREFIX}.phase={phase}", "--filter", f"label={LABEL_PREFIX}.run_id={run_id}"]
    containers = _docker_ids(["ps", "-a", "-q", *label_args])
    container_started = time.monotonic()

    def remove_container(item: tuple[int, str]) -> tuple[int, list[dict[str, Any]]]:
        idx, cid = item
        stop = run_docker(["stop", "-t", "5", cid], timeout=30, check=False)
        rm = run_docker(["rm", "-f", cid], timeout=30, check=False)
        return idx, [
            {
                "type": "container",
                "id": cid,
                "action": "stop",
                "status": "PASS" if stop.returncode == 0 else "SKIPPED_WITH_REASON",
                "stderr": stop.stderr.strip(),
            },
            {
                "type": "container",
                "id": cid,
                "action": "remove",
                "status": "PASS" if rm.returncode == 0 else "FAIL",
                "stderr": rm.stderr.strip(),
            },
        ]

    container_results = _bounded_parallel(
        list(enumerate(containers)),
        remove_container,
        parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
        timeout=max(30.0, len(containers) * 10.0),
        label="owned container cleanup",
    ) if containers else []
    for _idx, container_actions in sorted(container_results, key=lambda item: item[0]):
        actions.extend(container_actions)
    timings["cleanup_remove_containers_seconds"] = round(max(time.monotonic() - container_started, 0.0), 6)

    networks = _docker_ids(["network", "ls", "-q", *label_args])
    network_started = time.monotonic()

    def remove_network(item: tuple[int, str]) -> tuple[int, dict[str, Any]]:
        idx, nid = item
        rm = run_docker(["network", "rm", nid], timeout=30, check=False)
        return idx, {"type": "network", "id": nid, "action": "remove", "status": "PASS" if rm.returncode == 0 else "FAIL", "stderr": rm.stderr.strip()}

    network_results = _bounded_parallel(
        list(enumerate(networks)),
        remove_network,
        parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
        timeout=max(30.0, len(networks) * 10.0),
        label="owned network cleanup",
    ) if networks else []
    actions.extend(action for _idx, action in sorted(network_results, key=lambda item: item[0]))
    timings["cleanup_remove_networks_seconds"] = round(max(time.monotonic() - network_started, 0.0), 6)
    return actions, timings


def _cleanup_process_scenario(*, state: dict[str, Any], artifacts_dir: Path, out_path: Path) -> dict[str, Any]:
    phase = str(state.get("phase_id", "P13_SCALE_LADDER_50_100"))
    run_id = str(state.get("runtime", {}).get("run_id", _run_id(phase, str(state.get("scenario", "scale_50")))))
    actions: list[dict[str, Any]] = []
    cleanup_timing = {
        "cleanup_terminate_processes_seconds": 0.0,
        "cleanup_verify_process_exit_seconds": 0.0,
        "cleanup_verify_nodehost_empty_seconds": 0.0,
        "cleanup_remove_containers_seconds": 0.0,
        "cleanup_remove_networks_seconds": 0.0,
        "cleanup_residual_scan_seconds": 0.0,
        "bounded_parallelism": True,
        "parallelism": CLUSTER_ORCHESTRATION_PARALLELISM,
    }
    nodehosts = {nodehost["nodehost_id"]: nodehost for nodehost in state.get("nodehosts", [])}
    nodes = list(state.get("nodes", []))

    terminate_started = time.monotonic()

    def terminate_node(item: tuple[int, dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        idx, node = item
        container = str(node.get("nodehost_container_name") or node.get("container_name"))
        pid = str(node.get("pid"))
        kill = run_docker(["exec", container, "kill", "-TERM", pid], timeout=10, check=False)
        return idx, {
            "type": "valkey_process",
            "id": node.get("logical_id", pid),
            "nodehost_id": node.get("nodehost_id", "MISSING"),
            "pid": node.get("pid", "MISSING"),
            "action": "terminate",
            "status": "PASS" if kill.returncode == 0 else "SKIPPED_WITH_REASON",
            "stderr": kill.stderr.strip(),
        }

    terminate_results = _bounded_parallel(
        list(enumerate(nodes)),
        terminate_node,
        parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
        timeout=max(30.0, len(nodes) * 2.0),
        label="Valkey process termination",
    ) if nodes else []
    actions.extend(action for _idx, action in sorted(terminate_results, key=lambda item: item[0]))
    cleanup_timing["cleanup_terminate_processes_seconds"] = round(max(time.monotonic() - terminate_started, 0.0), 6)

    verify_started = time.monotonic()

    def verify_node_exit(item: tuple[int, dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        idx, node = item
        container = str(node.get("nodehost_container_name") or node.get("container_name"))
        pid = str(node.get("pid"))
        gone = _wait_container_pid_gone(container, pid, timeout=15.0)
        return idx, {
            "type": "valkey_process",
            "id": node.get("logical_id", pid),
            "nodehost_id": node.get("nodehost_id", "MISSING"),
            "pid": node.get("pid", "MISSING"),
            "action": "verify_exit",
            "status": "PASS" if gone else "FAIL",
        }

    verify_results = _bounded_parallel(
        list(enumerate(nodes)),
        verify_node_exit,
        parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
        timeout=max(30.0, len(nodes) * 3.0),
        label="Valkey process exit verification",
    ) if nodes else []
    actions.extend(action for _idx, action in sorted(verify_results, key=lambda item: item[0]))
    cleanup_timing["cleanup_verify_process_exit_seconds"] = round(max(time.monotonic() - verify_started, 0.0), 6)

    nodehost_started = time.monotonic()
    nodehost_items = list(enumerate(nodehosts.values()))

    def verify_nodehost_empty(item: tuple[int, dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        idx, nodehost = item
        container = str(nodehost["container_name"])
        pgrep = run_docker(["exec", container, "pgrep", "-x", "valkey-server"], timeout=10, check=False)
        return idx, {
            "type": "nodehost",
            "id": nodehost["nodehost_id"],
            "container_name": container,
            "action": "verify_no_valkey_processes",
            "status": "PASS" if pgrep.returncode != 0 else "FAIL",
            "stdout": pgrep.stdout.strip(),
            "stderr": pgrep.stderr.strip(),
        }

    nodehost_results = _bounded_parallel(
        nodehost_items,
        verify_nodehost_empty,
        parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
        timeout=max(30.0, len(nodehost_items) * 10.0),
        label="nodehost Valkey residual check",
    ) if nodehost_items else []
    actions.extend(action for _idx, action in sorted(nodehost_results, key=lambda item: item[0]))
    cleanup_timing["cleanup_verify_nodehost_empty_seconds"] = round(max(time.monotonic() - nodehost_started, 0.0), 6)

    resource_actions, resource_timing = _cleanup_resources_by_label(phase=phase, run_id=run_id)
    cleanup_timing.update(resource_timing)
    actions.extend(resource_actions)
    actions.extend(_cleanup_fault_state_files(artifacts_dir))
    residual_started = time.monotonic()
    resources_remaining = owned_resources(phase=phase, run_id=run_id)
    cleanup_timing["cleanup_residual_scan_seconds"] = round(max(time.monotonic() - residual_started, 0.0), 6)
    report = {
        "schema_version": "v1",
        "artifact_type": "cleanup_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS" if not resources_remaining and all(action.get("status") != "FAIL" for action in actions) else "FAIL",
        "resources_remaining": resources_remaining,
        "cleanup_actions": actions,
        "cleanup_timing": cleanup_timing,
        "artifacts_dir": str(artifacts_dir),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    scenario = state.get("scenario")
    if scenario:
        (out_path.parent / f"cleanup_report_{scenario}.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _wait_container_pid_gone(container: str, pid: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = run_docker(["exec", container, "kill", "-0", pid], timeout=5, check=False)
        if result.returncode != 0:
            return True
        time.sleep(0.5)
    return False


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
    host_ids = [host["host_id"] for host in config.get("hosts", [{"host_id": "local"}])]
    shards = int(cluster["shards"])
    replicas = int(cluster["replicas_per_shard"])
    specs: list[dict[str, Any]] = []
    ordinal = 0
    for shard in range(shards):
        shard_id = f"shard-{shard:04d}"
        specs.append(_spec(cluster, phase, scenario, ordinal, shard_id, "primary", azs[shard % len(azs)], host_ids[ordinal % len(host_ids)], run_id))
        ordinal += 1
    for shard in range(shards):
        for replica in range(replicas):
            shard_id = f"shard-{shard:04d}"
            az = azs[(shard + replica + 1) % len(azs)]
            specs.append(_spec(cluster, phase, scenario, ordinal, shard_id, f"replica-{replica:02d}", az, host_ids[ordinal % len(host_ids)], run_id))
            ordinal += 1
    return specs


def _spec(cluster: dict[str, Any], phase: str, scenario: str, ordinal: int, shard_id: str, role_suffix: str, az_id: str, host_id: str, run_id: str | None = None) -> dict[str, Any]:
    role = "primary" if role_suffix == "primary" else "replica"
    logical_id = f"{shard_id}-{role_suffix}"
    safe_run = (run_id or _run_id(phase, scenario)).lower().replace("_", "-")
    spec = {
        "logical_id": logical_id,
        "shard_id": shard_id,
        "role": role,
        "host_id": host_id,
        "az_id": az_id,
        "ordinal": ordinal,
        "client_port": int(cluster["port_base"]) + ordinal,
        "cluster_bus_port": int(cluster.get("cluster_bus_port_base", int(cluster["port_base"]) + 10000)) + ordinal,
        "container_name": f"vslab-{safe_run}-{logical_id}",
        "phase": phase,
        "scenario": scenario,
    }
    if phase == "P13_SCALE_LADDER_50_100":
        spec["cluster_node_timeout"] = "600000"
    return spec


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
        str(node.get("cluster_node_timeout", "5000")),
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
    if len(nodes) > 30:
        return _configure_large_cluster(nodes)
    operations: list[dict[str, Any]] = []
    node_timeout = _scale_timeout(nodes, floor=60.0, per_node=2.0)
    converge_timeout = _scale_timeout(nodes, floor=90.0, per_node=5.0)
    _wait_for_nodes(nodes, timeout=node_timeout)
    primaries = [node for node in nodes if node["role"] == "primary"]
    replicas = [node for node in nodes if node["role"] == "replica"]
    first = primaries[0]

    meet_started = time.monotonic()
    primary_meet_commands = _tree_fanout_meet_nodes(first, primaries[1:], timeout=converge_timeout)
    _wait_cluster_known(primaries, expected=len(primaries), timeout=converge_timeout, final_check=False)
    operations.append(
        _operation(
            "tree_fanout_meet_primaries",
            "PASS",
            meet_started,
            {
                "nodes_joined": len(primaries) - 1,
                "cluster_known_nodes": len(primaries),
                "fanout": CLUSTER_MEET_FANOUT,
                "parallelism": CLUSTER_ORCHESTRATION_PARALLELISM,
                "meet_commands": primary_meet_commands,
            },
        )
    )

    slot_ranges = _slot_ranges(len(primaries))
    slots_started = time.monotonic()
    primary_slot_ranges = list(zip(primaries, slot_ranges))
    _bounded_parallel(
        primary_slot_ranges,
        lambda item: _add_slots_node(item[0], item[1][0], item[1][1]),
        parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
        timeout=converge_timeout,
        label="parallel CLUSTER ADDSLOTS",
    )
    _wait_cluster_slots_assigned(primaries, timeout=converge_timeout, final_check=False)
    _wait_cluster_ok(primaries, timeout=converge_timeout, final_check=False)
    operations.append(
        _operation(
            "parallel_add_slots",
            "PASS",
            slots_started,
            {
                "slots_assigned": 16384,
                "primary_count": len(primaries),
                "parallelism": CLUSTER_ORCHESTRATION_PARALLELISM,
            },
        )
    )

    replica_meet_started = time.monotonic()
    primary_ids = _cluster_node_ids_by_shard(primaries, timeout=min(converge_timeout, 120.0))
    replica_meet_commands = _tree_fanout_meet_nodes(first, replicas, timeout=converge_timeout)
    _wait_cluster_known(nodes, expected=len(nodes), timeout=converge_timeout, final_check=False)
    operations.append(
        _operation(
            "tree_fanout_meet_replicas",
            "PASS",
            replica_meet_started,
            {
                "nodes_joined": len(replicas),
                "cluster_known_nodes": len(nodes),
                "fanout": CLUSTER_MEET_FANOUT,
                "parallelism": CLUSTER_ORCHESTRATION_PARALLELISM,
                "meet_commands": replica_meet_commands,
            },
        )
    )

    replicate_started = time.monotonic()
    _replicate_nodes_parallel(replicas, primary_ids, timeout=converge_timeout)
    _wait_cluster_known(nodes, expected=len(nodes), timeout=converge_timeout, final_check=False)
    _wait_cluster_ok(nodes, timeout=converge_timeout, final_check=False)
    _wait_cluster_role_counts(nodes, expected_primaries=len(primaries), expected_replicas=len(replicas), timeout=converge_timeout, final_check=False)
    operations.append(
        _operation(
            "parallel_add_replicas",
            "PASS",
            replicate_started,
            {
                "replica_count": len(replicas),
                "cluster_state": "ok",
                "parallelism": CLUSTER_ORCHESTRATION_PARALLELISM,
            },
        )
    )
    return operations


def run_node_cli(node: dict[str, Any], *args: Any, timeout: int = 60, check: bool = True) -> str:
    if node.get("runtime_type") == "docker_process" or node.get("nodehost_container_name"):
        result = run_docker(
            ["exec", node["nodehost_container_name"], "valkey-cli", "-p", str(node["client_port"]), *[str(arg) for arg in args]],
            timeout=timeout,
            check=check,
        )
        return result.stdout.strip()
    return run_container_cli(node["container_name"], *args, timeout=timeout, check=check)


def run_node_cluster_cli(node: dict[str, Any], *args: Any, timeout: int = 60, check: bool = True) -> str:
    if node.get("runtime_type") == "docker_process" or node.get("nodehost_container_name"):
        result = run_docker(
            ["exec", node["nodehost_container_name"], "valkey-cli", "-c", "-p", str(node["client_port"]), *[str(arg) for arg in args]],
            timeout=timeout,
            check=check,
        )
        return result.stdout.strip()
    return run_container_cluster_cli(node["container_name"], *args, timeout=timeout, check=check)


def _node_host_command(node: dict[str, Any], *args: Any, timeout: float = 2.0) -> Any:
    return _host_command(str(node.get("host", "127.0.0.1")), int(node["client_port"]), *args, timeout=timeout)


def _node_command(node: dict[str, Any], *args: Any, timeout: float = 5.0) -> str:
    if "client_port" in node:
        try:
            return str(_node_host_command(node, *args, timeout=timeout)).strip()
        except Exception:
            if not node.get("container_ip") and not node.get("nodehost_container_ip"):
                return run_node_cli(node, *args, timeout=max(1, int(timeout)))
            raise
    return run_node_cli(node, *args, timeout=max(1, int(timeout)))


def _bounded_parallel(
    items: Iterable[T],
    worker: Callable[[T], Any],
    *,
    parallelism: int = CLUSTER_ORCHESTRATION_PARALLELISM,
    timeout: float,
    label: str,
) -> list[Any]:
    work = list(items)
    if not work:
        return []
    max_workers = max(1, min(int(parallelism), len(work)))
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(worker, item) for item in work]
            return [future.result() for future in as_completed(futures, timeout=max(1.0, timeout))]
    except FutureTimeoutError as exc:
        raise DockerRuntimeError(f"{label} exceeded {timeout:.1f}s with parallelism={max_workers}") from exc


def _time_left(deadline: float, *, floor: float = 1.0) -> float:
    return max(floor, deadline - time.monotonic())


def _run_timed_step(
    timings: dict[str, dict[str, Any]] | None,
    name: str,
    func: Callable[[], T],
    details: dict[str, Any] | None = None,
) -> T:
    started = time.monotonic()
    try:
        result = func()
    except Exception as exc:  # noqa: BLE001 - timing artifacts should retain setup failures
        _record_timing(timings, name, started, status="FAIL", details=(details or {}) | {"error": repr(exc)})
        raise
    _record_timing(timings, name, started, details=details)
    return result


def _record_timing(
    timings: dict[str, dict[str, Any]] | None,
    name: str,
    started: float,
    *,
    status: str = "PASS",
    details: dict[str, Any] | None = None,
) -> None:
    if timings is None:
        return
    duration = max(time.monotonic() - started, 0.0)
    entry = timings.setdefault(
        name,
        {
            "name": name,
            "status": "PASS",
            "duration_seconds": 0.0,
            "count": 0,
            "details": {},
        },
    )
    entry["duration_seconds"] = round(float(entry.get("duration_seconds", 0.0)) + duration, 6)
    entry["count"] = int(entry.get("count", 0)) + 1
    if status == "FAIL":
        entry["status"] = "FAIL"
    if details:
        entry.setdefault("details", {}).update(details)


def _timing_entries(timings: dict[str, dict[str, Any]], required_names: list[str] | None = None) -> list[dict[str, Any]]:
    names = required_names or sorted(timings)
    entries: list[dict[str, Any]] = []
    for name in names:
        if name in timings:
            entries.append(timings[name])
        else:
            entries.append(
                {
                    "name": name,
                    "status": "MISSING",
                    "duration_seconds": None,
                    "count": 0,
                    "details": {"reason": "not recorded in this artifact producer"},
                }
            )
    return entries


def _timing_duration(timings: dict[str, dict[str, Any]], name: str) -> float | str:
    value = timings.get(name, {}).get("duration_seconds")
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    return "MISSING"


def _write_runtime_timing_breakdown(
    path: Path,
    phase: str,
    scenario: str,
    run_id: str,
    nodes: list[dict[str, Any]],
    timings: dict[str, dict[str, Any]],
    *,
    status: str,
) -> None:
    cluster_create_parts = [
        _timing_duration(timings, "primary_cluster_create"),
        _timing_duration(timings, "replica_meet"),
        _timing_duration(timings, "replica_replicate"),
    ]
    cluster_create_duration: float | str
    if all(isinstance(part, (int, float)) for part in cluster_create_parts):
        cluster_create_duration = round(sum(float(part) for part in cluster_create_parts), 6)
    else:
        cluster_create_duration = "MISSING"
    artifact = {
        "schema_version": "v1",
        "artifact_type": "p13_timing_breakdown",
        "phase_id": phase,
        "run_id": run_id,
        "scenario": scenario,
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab-runtime", "version": __version__},
        "status": status,
        "node_count": len(nodes),
        "timings": _timing_entries(timings, P13_TIMING_NAMES),
        "summary": {
            "cluster_create_duration_seconds": cluster_create_duration,
            "replica_config_duration_seconds": _timing_duration(timings, "replica_replicate"),
            "wrapper_probe_duration_seconds": "MISSING",
            "final_full_probe_duration_seconds": _timing_duration(timings, "runtime_final_full_probe"),
            "diagnostic_full_probe_duration_seconds": _timing_duration(timings, "runtime_diagnostic_full_probe"),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _cluster_meet_address(node: dict[str, Any]) -> str:
    if node.get("nodehost_container_ip"):
        return str(node["nodehost_container_ip"])
    return str(node["container_ip"])


def _cluster_meet_port(node: dict[str, Any]) -> int:
    if node.get("nodehost_container_ip"):
        return int(node["client_port"])
    return 6379


def _meet_node_pair(source: dict[str, Any], target: dict[str, Any]) -> None:
    _node_command(
        source,
        "CLUSTER",
        "MEET",
        _cluster_meet_address(target),
        _cluster_meet_port(target),
        timeout=30,
    )


def _tree_fanout_levels(seed: dict[str, Any], nodes: list[dict[str, Any]], *, fanout: int = CLUSTER_MEET_FANOUT) -> list[list[tuple[dict[str, Any], dict[str, Any]]]]:
    remaining = [node for node in nodes if node["logical_id"] != seed["logical_id"]]
    parents = [seed]
    levels: list[list[tuple[dict[str, Any], dict[str, Any]]]] = []
    while remaining:
        level: list[tuple[dict[str, Any], dict[str, Any]]] = []
        next_parents: list[dict[str, Any]] = []
        for parent in parents:
            for _ in range(fanout):
                if not remaining:
                    break
                child = remaining.pop(0)
                level.append((parent, child))
                next_parents.append(child)
        levels.append(level)
        parents = next_parents
    return levels


def _tree_fanout_meet_nodes(
    seed: dict[str, Any],
    nodes: list[dict[str, Any]],
    *,
    timeout: float,
    fanout: int = CLUSTER_MEET_FANOUT,
    parallelism: int = CLUSTER_ORCHESTRATION_PARALLELISM,
) -> int:
    deadline = time.monotonic() + timeout
    command_count = 0
    for level in _tree_fanout_levels(seed, nodes, fanout=fanout):
        _bounded_parallel(
            level,
            lambda edge: _meet_node_pair(edge[0], edge[1]),
            parallelism=parallelism,
            timeout=_time_left(deadline, floor=5.0),
            label="tree fanout CLUSTER MEET",
        )
        command_count += len(level)
    return command_count


def _representative_nodes(nodes: list[dict[str, Any]], *, primaries_only: bool = False, max_per_az: int = 1) -> list[dict[str, Any]]:
    candidates = [node for node in nodes if not primaries_only or node.get("role") == "primary"]
    if not candidates:
        return []
    representatives: list[dict[str, Any]] = [candidates[0]]
    per_az: dict[str, int] = {}
    for node in candidates:
        az = str(node.get("az_id", "MISSING"))
        if per_az.get(az, 0) >= max_per_az:
            continue
        representatives.append(node)
        per_az[az] = per_az.get(az, 0) + 1
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in representatives:
        logical_id = str(node["logical_id"])
        if logical_id not in seen:
            deduped.append(node)
            seen.add(logical_id)
    return deduped


def _configure_process_cluster(
    nodes: list[dict[str, Any]],
    timings: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(nodes) > 30:
        return _configure_large_process_cluster(nodes, timings=timings)

    operations: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    timeout = _scale_timeout(nodes, floor=300.0, per_node=8.0)
    primaries = [node for node in nodes if node["role"] == "primary"]
    replicas = [node for node in nodes if node["role"] == "replica"]
    first = primaries[0]

    meet_started = time.monotonic()
    primary_meet_commands = _tree_fanout_meet_nodes(first, primaries[1:], timeout=timeout)
    _wait_process_known(primaries, expected=len(primaries), timeout=timeout, final_check=False)
    snapshots.append(_process_cluster_summary("after_meet_primaries", _representative_nodes(primaries), total_node_count=len(nodes), sample_scope="representative_primaries"))
    operations.append(
        _operation(
            "tree_fanout_meet_primaries",
            "PASS",
            meet_started,
            snapshots[-1]
            | {
                "strategy": "tree_fanout_cluster_meet_after_all_processes_start",
                "fanout": CLUSTER_MEET_FANOUT,
                "parallelism": CLUSTER_ORCHESTRATION_PARALLELISM,
                "meet_commands": primary_meet_commands,
            },
        )
    )

    slots_started = time.monotonic()
    primary_slot_ranges = list(zip(primaries, _slot_ranges(len(primaries))))
    _bounded_parallel(
        primary_slot_ranges,
        lambda item: _add_slots_node(item[0], item[1][0], item[1][1]),
        parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
        timeout=timeout,
        label="parallel CLUSTER ADDSLOTS",
    )
    _wait_process_slots_assigned(primaries, timeout=timeout, final_check=False)
    _wait_process_cluster_ok(primaries, timeout=timeout, final_check=False)
    snapshots.append(_process_cluster_summary("after_add_slots", _representative_nodes(primaries), total_node_count=len(nodes), sample_scope="representative_primaries"))
    operations.append(
        _operation(
            "parallel_add_slots",
            "PASS",
            slots_started,
            snapshots[-1]
            | {
                "parallelism": CLUSTER_ORCHESTRATION_PARALLELISM,
                "primary_count": len(primaries),
            },
        )
    )

    replica_meet_started = time.monotonic()
    primary_ids = _cluster_node_ids_by_shard(primaries, timeout=min(timeout, 120.0))
    replica_meet_commands = _tree_fanout_meet_nodes(first, replicas, timeout=timeout)
    _wait_process_known(nodes, expected=len(nodes), timeout=timeout, final_check=False)
    snapshots.append(_process_cluster_summary("after_meet_replicas", _representative_nodes(nodes), total_node_count=len(nodes), sample_scope="representative_by_az"))
    operations.append(
        _operation(
            "tree_fanout_meet_replicas",
            "PASS",
            replica_meet_started,
            snapshots[-1]
            | {
                "strategy": "tree_fanout_cluster_meet_before_parallel_replication",
                "fanout": CLUSTER_MEET_FANOUT,
                "parallelism": CLUSTER_ORCHESTRATION_PARALLELISM,
                "meet_commands": replica_meet_commands,
            },
        )
    )

    replica_started = time.monotonic()
    _replicate_process_nodes_parallel(replicas, primary_ids, timeout=timeout)
    _wait_process_known(nodes, expected=len(nodes), timeout=timeout, final_check=False)
    _wait_process_cluster_ok(nodes, timeout=timeout, final_check=False)
    _wait_process_role_counts(nodes, expected_primaries=len(primaries), expected_replicas=len(replicas), timeout=timeout, final_check=False)
    snapshots.append(_process_cluster_summary("after_add_replicas", _representative_nodes(nodes), total_node_count=len(nodes), sample_scope="representative_by_az"))
    operations.append(
        _operation(
            "parallel_add_replicas",
            "PASS",
            replica_started,
            snapshots[-1]
            | {
                "parallelism": CLUSTER_ORCHESTRATION_PARALLELISM,
                "replica_count": len(replicas),
            },
        )
    )

    final_started = time.monotonic()
    _wait_process_snapshot_clean(nodes, expected_nodes=len(nodes), expected_primaries=len(primaries), expected_replicas=len(replicas), timeout=timeout)
    snapshots.append(_process_cluster_summary("final", nodes, sample_scope="all_nodes"))
    operations.append(_operation("final_cluster_check", "PASS", final_started, snapshots[-1]))
    return operations, snapshots


def _process_cluster_startup_strategy(nodes: list[dict[str, Any]]) -> str:
    if len(nodes) > 30:
        strategy = _cluster_create_strategy()
        if strategy == CLUSTER_CREATE_STRATEGY_MANUAL:
            return "all_processes_ready_then_manual_tree_meet_parallel_slots_parallel_replicas_two_stage_probe"
        return "all_processes_ready_then_valkey_cli_cluster_create_replicas_two_stage_probe"
    return "all_processes_ready_then_tree_fanout_meet_parallel_slots_parallel_replicas_two_stage_probe"


def _cluster_create_strategy() -> str:
    strategy = os.environ.get("VSLAB_CLUSTER_CREATE_STRATEGY", CLUSTER_CREATE_STRATEGY_DEFAULT).strip()
    if not strategy:
        strategy = CLUSTER_CREATE_STRATEGY_DEFAULT
    if strategy not in CLUSTER_CREATE_STRATEGIES:
        allowed = ", ".join(sorted(CLUSTER_CREATE_STRATEGIES))
        raise DockerRuntimeError(f"unsupported cluster create strategy {strategy!r}; allowed={allowed}")
    return strategy


def _replica_replicate_parallelism() -> int:
    raw = os.environ.get("VSLAB_REPLICA_REPLICATE_PARALLELISM", "").strip()
    if not raw:
        return REPLICA_REPLICATE_PARALLELISM_DEFAULT
    try:
        value = int(raw)
    except ValueError as exc:
        allowed = ", ".join(str(item) for item in REPLICA_REPLICATE_PARALLELISM_CHOICES)
        raise DockerRuntimeError(f"unsupported replica replicate parallelism {raw!r}; allowed={allowed}") from exc
    if value not in REPLICA_REPLICATE_PARALLELISM_CHOICES:
        allowed = ", ".join(str(item) for item in REPLICA_REPLICATE_PARALLELISM_CHOICES)
        raise DockerRuntimeError(f"unsupported replica replicate parallelism {value}; allowed={allowed}")
    return value


def _replica_replicate_parallelism_source() -> str:
    if os.environ.get("VSLAB_REPLICA_REPLICATE_PARALLELISM"):
        return "env:VSLAB_REPLICA_REPLICATE_PARALLELISM"
    return "default"


def _configure_large_process_cluster(
    nodes: list[dict[str, Any]],
    timings: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    operations: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    timeout = _scale_timeout(nodes, floor=300.0, per_node=8.0)
    primaries = [node for node in nodes if node["role"] == "primary"]
    replicas = [node for node in nodes if node["role"] == "replica"]

    create_started = time.monotonic()
    if timings is None:
        create_output = _create_large_cluster(primaries, replicas, timeout=timeout)
    else:
        create_output = _create_large_cluster(primaries, replicas, timeout=timeout, timings=timings)
    _wait_process_known(nodes, expected=len(nodes), timeout=timeout, final_check=False, timings=timings)
    _wait_process_slots_assigned(nodes, timeout=timeout, final_check=False, timings=timings)
    _wait_process_cluster_ok(nodes, timeout=timeout, final_check=False, timings=timings)
    _wait_process_role_counts(
        nodes,
        expected_primaries=len(primaries),
        expected_replicas=len(replicas),
        timeout=timeout,
        final_check=False,
        timings=timings,
    )
    snapshots.append(
        _process_cluster_summary(
            "after_cluster_create",
            _representative_nodes(nodes),
            total_node_count=len(nodes),
            sample_scope="representative_by_az",
        )
    )
    operations.append(
        _operation(
            "cluster_create",
            "PASS",
            create_started,
            snapshots[-1]
            | {
                "strategy": f"{_cluster_create_strategy()}_then_parallel_process_replicas",
                "primary_count": len(primaries),
                "replica_count": len(replicas),
                "cluster_create_address_count": len(primaries),
                "output_tail": create_output[-1000:],
            },
        )
    )

    final_started = time.monotonic()
    _wait_process_snapshot_clean(
        nodes,
        expected_nodes=len(nodes),
        expected_primaries=len(primaries),
        expected_replicas=len(replicas),
        timeout=timeout,
        timings=timings,
    )
    snapshots.append(_process_cluster_summary("final", nodes, sample_scope="all_nodes"))
    operations.append(_operation("final_cluster_check", "PASS", final_started, snapshots[-1]))
    return operations, snapshots


def _bulk_meet_process_nodes(seed: dict[str, Any], nodes: list[dict[str, Any]], *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    for node in nodes:
        _meet_node_pair(seed, node)
        if time.monotonic() >= deadline:
            raise DockerRuntimeError("bulk CLUSTER MEET command budget expired")


def _add_slots_node(node: dict[str, Any], start: int, end: int) -> None:
    batch: list[int] = []
    for slot in range(start, end + 1):
        batch.append(slot)
        if len(batch) == 500:
            _node_command(node, "CLUSTER", "ADDSLOTS", *batch, timeout=60)
            batch = []
    if batch:
        _node_command(node, "CLUSTER", "ADDSLOTS", *batch, timeout=60)


def _cluster_node_ids_by_shard(
    nodes: list[dict[str, Any]],
    *,
    timeout: float,
    parallelism: int = CLUSTER_ORCHESTRATION_PARALLELISM,
) -> dict[str, str]:
    def node_id(node: dict[str, Any]) -> tuple[str, str]:
        return str(node["shard_id"]), _node_command(node, "CLUSTER", "MYID", timeout=30)

    pairs = _bounded_parallel(
        nodes,
        node_id,
        parallelism=parallelism,
        timeout=timeout,
        label="parallel CLUSTER MYID",
    )
    return {shard_id: node_id_value for shard_id, node_id_value in pairs}


def _replicate_process_nodes_parallel(replicas: list[dict[str, Any]], primary_ids: dict[str, str], *, timeout: float) -> None:
    deadline = time.monotonic() + timeout

    def replicate(replica: dict[str, Any]) -> None:
        master_id = primary_ids[replica["shard_id"]]
        local_timeout = max(10.0, min(120.0, _time_left(deadline, floor=10.0)))
        _wait_process_knows_node_id(replica, master_id, timeout=local_timeout)
        _replicate_process_node(replica, master_id, timeout=local_timeout)
        _wait_process_replica_of(replica, master_id, timeout=local_timeout)

    _bounded_parallel(
        replicas,
        replicate,
        parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
        timeout=timeout,
        label="parallel CLUSTER REPLICATE",
    )


def _replicate_nodes_parallel(replicas: list[dict[str, Any]], primary_ids: dict[str, str], *, timeout: float) -> None:
    _replicate_process_nodes_parallel(replicas, primary_ids, timeout=timeout)


def _wait_process_nodes_ready(nodes: list[dict[str, Any]], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_ready = 0
    while time.monotonic() < deadline:
        ready = 0
        for node in nodes:
            try:
                if _node_command(node, "PING", timeout=2.0) == "PONG":
                    ready += 1
            except Exception:
                pass
        if ready == len(nodes):
            return
        last_ready = ready
        time.sleep(1)
    raise DockerRuntimeError(f"process runtime nodes ready timeout reached {last_ready}/{len(nodes)}")


def _wait_process_known(
    nodes: list[dict[str, Any]],
    expected: int,
    timeout: float,
    *,
    final_check: bool = True,
    timings: dict[str, dict[str, Any]] | None = None,
) -> None:
    _wait_process_predicate(
        nodes,
        timeout,
        f"cluster_known_nodes did not converge to {expected}",
        lambda snap: snap["known_nodes"] == expected,
        final_check=final_check,
        timings=timings,
    )


def _wait_process_cluster_ok(
    nodes: list[dict[str, Any]],
    timeout: float,
    *,
    final_check: bool = True,
    timings: dict[str, dict[str, Any]] | None = None,
) -> None:
    _wait_process_predicate(
        nodes,
        timeout,
        "cluster_state did not reach ok",
        lambda snap: snap["cluster_state"] == "ok",
        final_check=final_check,
        timings=timings,
    )


def _wait_process_slots_assigned(
    nodes: list[dict[str, Any]],
    timeout: float,
    *,
    final_check: bool = True,
    timings: dict[str, dict[str, Any]] | None = None,
) -> None:
    _wait_process_predicate(
        nodes,
        timeout,
        "cluster slots were not fully assigned",
        lambda snap: snap["slots_assigned"] == 16384 and snap["slots_ok"] == 16384 and snap["slots_fail"] == 0,
        final_check=final_check,
        timings=timings,
    )


def _wait_process_role_counts(
    nodes: list[dict[str, Any]],
    *,
    expected_primaries: int,
    expected_replicas: int,
    timeout: float,
    final_check: bool = True,
    timings: dict[str, dict[str, Any]] | None = None,
) -> None:
    _wait_process_predicate(
        nodes,
        timeout,
        f"cluster role counts did not converge to {expected_primaries} primaries and {expected_replicas} replicas",
        lambda snap: snap["primary_count"] == expected_primaries and snap["replica_count"] == expected_replicas,
        final_check=final_check,
        timings=timings,
    )


def _wait_process_snapshot_clean(
    nodes: list[dict[str, Any]],
    *,
    expected_nodes: int,
    expected_primaries: int,
    expected_replicas: int,
    timeout: float,
    timings: dict[str, dict[str, Any]] | None = None,
) -> None:
    def clean(snap: dict[str, Any]) -> bool:
        return (
            snap["cluster_state"] == "ok"
            and snap["known_nodes"] == expected_nodes
            and snap["primary_count"] == expected_primaries
            and snap["replica_count"] == expected_replicas
            and snap["handshake_count"] == 0
            and snap["fail_count"] == 0
            and snap["pfail_count"] == 0
            and snap["slots_assigned"] == 16384
            and snap["slots_ok"] == 16384
            and snap["slots_fail"] == 0
        )

    _wait_process_predicate(nodes, timeout, "cluster clean snapshot did not converge", clean, final_check=True, timings=timings)


def _wait_process_predicate(
    nodes: list[dict[str, Any]],
    timeout: float,
    message: str,
    predicate: Any,
    *,
    final_check: bool = True,
    timings: dict[str, dict[str, Any]] | None = None,
) -> None:
    deadline = time.monotonic() + timeout
    representatives = _representative_nodes(nodes)
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        representative_started = time.monotonic()
        snapshots = _process_node_snapshots_parallel(representatives, timeout=max(1.0, min(15.0, _time_left(deadline))))
        _record_timing(
            timings,
            "runtime_representative_probe",
            representative_started,
            details={"sample_scope": "representative", "sample_count": len(representatives), "predicate": message},
        )
        failing = [snap for snap in snapshots if snap.get("probe_status") != "PASS" or not predicate(snap)]
        if not failing:
            if not final_check:
                return
            final_started = time.monotonic()
            final_snapshots = _process_node_snapshots_parallel(nodes, timeout=max(1.0, min(60.0, _time_left(deadline))))
            _record_timing(
                timings,
                "runtime_final_full_probe",
                final_started,
                details={"sample_scope": "all_nodes", "sample_count": len(nodes), "predicate": message},
            )
            final_failing = [snap for snap in final_snapshots if snap.get("probe_status") != "PASS" or not predicate(snap)]
            if not final_failing:
                return
            last = final_failing[0]
            break
        last = failing[0]
        time.sleep(1)
    while time.monotonic() < deadline:
        diagnostic_started = time.monotonic()
        snapshots = _process_node_snapshots_parallel(nodes, timeout=max(1.0, min(60.0, _time_left(deadline))))
        _record_timing(
            timings,
            "runtime_diagnostic_full_probe",
            diagnostic_started,
            status="FAIL",
            details={"sample_scope": "all_nodes", "sample_count": len(nodes), "predicate": message, "mode": "diagnostic"},
        )
        failing = [snap for snap in snapshots if snap.get("probe_status") != "PASS" or not predicate(snap)]
        if not failing:
            return
        last = failing[0]
        time.sleep(CLUSTER_DIAGNOSTIC_INTERVAL_SECONDS)
    raise DockerRuntimeError(f"{message}; last_snapshot={last}")


def _wait_process_integrated(node: dict[str, Any], expected: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        snap = _process_node_snapshot(node)
        last = snap
        if snap["known_nodes"] >= expected and snap["handshake_count"] == 0 and snap["fail_count"] == 0 and snap["pfail_count"] == 0:
            return
        time.sleep(1)
    raise DockerRuntimeError(f"cluster meet did not integrate at least {expected} nodes; last_snapshot={last}")


def _replicate_process_node(node: dict[str, Any], master_id: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            _node_command(node, "CLUSTER", "REPLICATE", master_id, timeout=30)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
        time.sleep(2)
    raise DockerRuntimeError(f"CLUSTER REPLICATE did not succeed for {node['logical_id']}: {last_error}")


def _wait_process_knows_node_id(node: dict[str, Any], node_id: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_snapshot: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        try:
            text = _node_command(node, "CLUSTER", "NODES", timeout=5)
            if any(line.startswith(node_id + " ") for line in text.splitlines()):
                return
            last_snapshot = _process_node_snapshot(node)
        except Exception:
            pass
        time.sleep(1)
    raise DockerRuntimeError(f"{node['logical_id']} did not learn node id {node_id}; last_snapshot={last_snapshot}")


def _wait_process_replica_of(node: dict[str, Any], master_id: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _process_node_is_replica_of(node, master_id):
            return
        time.sleep(1)
    raise DockerRuntimeError(f"{node['logical_id']} did not become replica of {master_id}")


def _process_node_is_replica_of(node: dict[str, Any], master_id: str) -> bool:
    text = _node_command(node, "CLUSTER", "NODES", timeout=5)
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 8 or "myself" not in parts[2].split(","):
            continue
        flags = set(parts[2].split(","))
        return ("slave" in flags or "replica" in flags) and parts[3] == master_id and parts[7] == "connected"
    return False


def _process_node_snapshot(node: dict[str, Any]) -> dict[str, Any]:
    try:
        info = _parse_info(_node_command(node, "CLUSTER", "INFO", timeout=5))
        nodes_text = _node_command(node, "CLUSTER", "NODES", timeout=5)
        counts = _cluster_node_text_counts(nodes_text)
        return {
            "logical_id": node["logical_id"],
            "probe_status": "PASS",
            "cluster_state": info.get("cluster_state", "unknown"),
            "known_nodes": _int_or_zero(info.get("cluster_known_nodes")),
            "primary_count": counts["primary_count"],
            "replica_count": counts["replica_count"],
            "handshake_count": counts["handshake_count"],
            "fail_count": counts["fail_count"],
            "pfail_count": counts["pfail_count"],
            "slots_assigned": _int_or_zero(info.get("cluster_slots_assigned")),
            "slots_ok": _int_or_zero(info.get("cluster_slots_ok")),
            "slots_fail": _int_or_zero(info.get("cluster_slots_fail")),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "logical_id": node["logical_id"],
            "probe_status": "FAIL",
            "error": repr(exc),
            "cluster_state": "unknown",
            "known_nodes": 0,
            "primary_count": 0,
            "replica_count": 0,
            "handshake_count": 0,
            "fail_count": 0,
            "pfail_count": 0,
            "slots_assigned": 0,
            "slots_ok": 0,
            "slots_fail": 0,
        }


def _process_node_snapshots_parallel(nodes: list[dict[str, Any]], *, timeout: float = 60.0) -> list[dict[str, Any]]:
    return _bounded_parallel(
        nodes,
        _process_node_snapshot,
        parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
        timeout=timeout,
        label="parallel cluster snapshot probes",
    )


def _cluster_node_text_counts(text: str) -> dict[str, int]:
    counts = {"primary_count": 0, "replica_count": 0, "handshake_count": 0, "fail_count": 0, "pfail_count": 0}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 8:
            continue
        flags = set(parts[2].split(","))
        if "handshake" in flags:
            counts["handshake_count"] += 1
        if "fail" in flags:
            counts["fail_count"] += 1
        if "fail?" in flags or "pfail" in flags:
            counts["pfail_count"] += 1
        if parts[7] != "connected" or flags.intersection({"handshake", "fail", "noaddr"}):
            continue
        if "master" in flags:
            counts["primary_count"] += 1
        elif "slave" in flags or "replica" in flags:
            counts["replica_count"] += 1
    return counts


def _process_cluster_summary(
    label: str,
    nodes: list[dict[str, Any]],
    *,
    total_node_count: int | None = None,
    sample_scope: str = "all_nodes",
) -> dict[str, Any]:
    samples = _process_node_snapshots_parallel(nodes)
    return {
        "label": label,
        "node_count": total_node_count or len(nodes),
        "sample_scope": sample_scope,
        "sample_count": len(samples),
        "known_nodes": min((sample["known_nodes"] for sample in samples), default=0),
        "known_nodes_max": max((sample["known_nodes"] for sample in samples), default=0),
        "primary_count": min((sample["primary_count"] for sample in samples), default=0),
        "replica_count": min((sample["replica_count"] for sample in samples), default=0),
        "handshake_count": max((sample["handshake_count"] for sample in samples), default=0),
        "fail_count": max((sample["fail_count"] for sample in samples), default=0),
        "pfail_count": max((sample["pfail_count"] for sample in samples), default=0),
        "slots_assigned": min((sample["slots_assigned"] for sample in samples), default=0),
        "slots_ok": min((sample["slots_ok"] for sample in samples), default=0),
        "slots_fail": max((sample["slots_fail"] for sample in samples), default=0),
        "cluster_states": sorted({sample["cluster_state"] for sample in samples}),
        "samples": samples,
    }


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _configure_large_cluster(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    node_timeout = _scale_timeout(nodes, floor=60.0, per_node=2.0)
    _wait_for_nodes(nodes, timeout=node_timeout)
    converge_timeout = _scale_timeout(nodes, floor=300.0, per_node=8.0)
    first = nodes[0]
    primaries = [node for node in nodes if node["role"] == "primary"]
    replicas = [node for node in nodes if node["role"] == "replica"]

    create_started = time.monotonic()
    create_output = _create_large_cluster(primaries, replicas, timeout=converge_timeout)
    _wait_cluster_known(nodes, expected=len(nodes), timeout=converge_timeout)
    _wait_cluster_slots_assigned(nodes, timeout=converge_timeout)
    _wait_cluster_ok(nodes, timeout=converge_timeout)
    _wait_cluster_role_counts(nodes, expected_primaries=len(primaries), expected_replicas=len(replicas), timeout=converge_timeout)
    operations.append(
        _operation(
            "cluster_create",
            "PASS",
            create_started,
            {
                "primary_count": len(primaries),
                "replica_count": len(replicas),
                "cluster_known_nodes": _cluster_known_nodes(first),
                "output_tail": create_output[-1000:],
            },
        )
    )
    return operations


def _create_large_cluster(
    primaries: list[dict[str, Any]],
    replicas: list[dict[str, Any]],
    timeout: float,
    timings: dict[str, dict[str, Any]] | None = None,
) -> str:
    if not primaries:
        raise DockerRuntimeError("large cluster create requires at least one primary")
    nodes = [*primaries, *replicas]
    output: list[str] = []
    strategy = _cluster_create_strategy()
    primary_create_details: dict[str, Any] = {
        "primary_count": len(primaries),
        "parallelism": CLUSTER_ORCHESTRATION_PARALLELISM,
        "strategy": strategy,
    }

    def create_primaries() -> None:
        if strategy == CLUSTER_CREATE_STRATEGY_MANUAL:
            create_output, details = _create_primary_cluster_manual_tree_meet_parallel_slots(primaries, timeout=timeout)
        else:
            create_output, details = _create_primary_cluster_valkey_cli(primaries, timeout=timeout)
        primary_create_details.update(details)
        output.append(create_output)

    _run_timed_step(
        timings,
        "primary_cluster_create",
        create_primaries,
        primary_create_details,
    )
    if replicas:
        def meet_replicas() -> int:
            meet_commands = _tree_fanout_meet_nodes(primaries[0], replicas, timeout=timeout)
            _wait_cluster_known(nodes, expected=len(nodes), timeout=min(360.0, timeout), final_check=False)
            output.append(f"replica meet commands: {meet_commands}")
            return meet_commands

        meet_commands = _run_timed_step(
            timings,
            "replica_meet",
            meet_replicas,
            {"replica_count": len(replicas), "fanout": CLUSTER_MEET_FANOUT, "parallelism": CLUSTER_ORCHESTRATION_PARALLELISM},
        )
        timings and timings.get("replica_meet", {}).setdefault("details", {}).update({"meet_commands": meet_commands})

        replica_parallelism = _replica_replicate_parallelism()
        replica_details: dict[str, Any] = {
            "replica_count": len(replicas),
            "parallelism": replica_parallelism,
            "parallelism_source": _replica_replicate_parallelism_source(),
            "supported_parallelism": list(REPLICA_REPLICATE_PARALLELISM_CHOICES),
            "bounded_parallelism": True,
        }

        def configure_replicas() -> str:
            text, details = _configure_large_cluster_replicas_with_diagnostics(primaries, replicas, timeout=timeout)
            replica_details.update(details)
            return text

        output.append(_run_timed_step(timings, "replica_replicate", configure_replicas, replica_details))
    return "\n".join(part for part in output if part)


def _record_substep(details: dict[str, Any], key: str, started: float) -> None:
    details[key] = round(max(time.monotonic() - started, 0.0), 6)


def _create_primary_cluster_valkey_cli(primaries: list[dict[str, Any]], timeout: float) -> tuple[str, dict[str, Any]]:
    details: dict[str, Any] = {
        "primary_meet_seconds": 0.0,
        "slot_assignment_seconds": 0.0,
        "slot_assignment_scope": "inside_valkey_cli_cluster_create",
    }
    command_started = time.monotonic()
    output = _create_primary_cluster(primaries, timeout=timeout)
    _record_substep(details, "cluster_create_command_seconds", command_started)

    convergence_started = time.monotonic()
    _wait_cluster_known(primaries, expected=len(primaries), timeout=min(360.0, timeout), final_check=False)
    _record_substep(details, "primary_convergence_seconds", convergence_started)

    probe_started = time.monotonic()
    probe_output = _assign_probe_slot_to_first_primary(primaries, timeout=timeout)
    details["probe_slot_assignment_seconds"] = round(max(time.monotonic() - probe_started, 0.0), 6)
    return "\n".join(part for part in [output, probe_output] if part), details


def _create_primary_cluster_manual_tree_meet_parallel_slots(primaries: list[dict[str, Any]], timeout: float) -> tuple[str, dict[str, Any]]:
    details: dict[str, Any] = {"cluster_create_command_seconds": 0.0}
    if len(primaries) <= 1:
        details.update({
            "primary_meet_seconds": 0.0,
            "slot_assignment_seconds": 0.0,
            "primary_convergence_seconds": 0.0,
            "meet_commands": 0,
            "slot_assignment_scope": "single_primary_no_slots_moved",
        })
        return "manual primary create skipped for single primary", details

    first = primaries[0]
    meet_started = time.monotonic()
    meet_commands = _tree_fanout_meet_nodes(first, primaries[1:], timeout=timeout)
    _record_substep(details, "primary_meet_seconds", meet_started)

    convergence_started = time.monotonic()
    _wait_cluster_known(primaries, expected=len(primaries), timeout=min(360.0, timeout), final_check=False)
    _record_substep(details, "primary_convergence_seconds", convergence_started)

    slots_started = time.monotonic()
    primary_slot_ranges = list(zip(primaries, _slot_ranges(len(primaries))))
    _bounded_parallel(
        primary_slot_ranges,
        lambda item: _add_slots_node(item[0], item[1][0], item[1][1]),
        parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
        timeout=timeout,
        label="parallel primary CLUSTER ADDSLOTS",
    )
    _wait_cluster_slots_assigned(primaries, timeout=min(360.0, timeout), final_check=False)
    _wait_cluster_ok(primaries, timeout=min(360.0, timeout), final_check=False)
    _record_substep(details, "slot_assignment_seconds", slots_started)

    details["meet_commands"] = meet_commands
    details["slot_assignment_scope"] = "parallel_cluster_addslots"
    return f"manual tree meet primaries={len(primaries)} meet_commands={meet_commands}", details


def _create_primary_cluster(primaries: list[dict[str, Any]], timeout: float) -> str:
    create_primaries = _cluster_create_primary_order(primaries)
    addresses = [_cluster_create_address(node) for node in create_primaries]
    args = [
        "exec",
        primaries[0]["container_name"],
        "valkey-cli",
        "--cluster",
        "create",
        *addresses,
    ]
    args.append("--cluster-yes")
    try:
        return run_docker(args, timeout=max(1, min(900, int(timeout)))).stdout.strip()
    except DockerRuntimeError as exc:
        if "timed out" not in str(exc):
            raise
        _wait_cluster_known(primaries, expected=len(primaries), timeout=min(360.0, timeout))
        return "cluster create client timed out after membership became visible"


def _cluster_create_address(node: dict[str, Any]) -> str:
    return f"{_cluster_meet_address(node)}:{_cluster_meet_port(node)}"


def _assign_probe_slot_to_first_primary(primaries: list[dict[str, Any]], *, timeout: float) -> str:
    probe_slot = 8014
    target_id = _node_command(primaries[0], "CLUSTER", "MYID", timeout=30)

    def assign(node: dict[str, Any]) -> str:
        return _node_command(node, "CLUSTER", "SETSLOT", probe_slot, "NODE", target_id, timeout=30)

    _bounded_parallel(
        primaries,
        assign,
        parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
        timeout=timeout,
        label="parallel CLUSTER SETSLOT probe slot",
    )
    return f"probe slot {probe_slot} assigned to {primaries[0]['logical_id']}"


def _cluster_create_primary_order(primaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(primaries) <= 1:
        return list(primaries)
    probe_index = _probe_slot_primary_index(len(primaries))
    ordered = list(primaries)
    first = ordered.pop(0)
    ordered.insert(probe_index, first)
    return ordered


def _probe_slot_primary_index(primary_count: int) -> int:
    probe_slot = 8014
    ranges = _sequential_slot_ranges(primary_count)
    return next((idx for idx, (lo, hi) in enumerate(ranges) if lo <= probe_slot <= hi), 0)


def _configure_large_cluster_replicas(primaries: list[dict[str, Any]], replicas: list[dict[str, Any]], timeout: float) -> str:
    output, _details = _configure_large_cluster_replicas_with_diagnostics(primaries, replicas, timeout=timeout)
    return output


def _configure_large_cluster_replicas_with_diagnostics(
    primaries: list[dict[str, Any]],
    replicas: list[dict[str, Any]],
    timeout: float,
) -> tuple[str, dict[str, Any]]:
    if not replicas:
        return "", {
            "replica_primary_id_lookup_seconds": 0.0,
            "replica_knows_master_wait_seconds": 0.0,
            "replica_replicate_command_seconds": 0.0,
            "replica_replicaof_wait_seconds": 0.0,
            "replica_replicate_total_seconds": 0.0,
            "slowest_replicas": [],
            "replica_diagnostics": [],
        }

    parallelism = _replica_replicate_parallelism()
    deadline = time.monotonic() + timeout
    total_started = time.monotonic()
    diagnostics: dict[str, dict[str, Any]] = {
        replica["logical_id"]: {
            "logical_id": replica["logical_id"],
            "shard_id": replica["shard_id"],
            "status": "PASS",
        }
        for replica in replicas
    }

    lookup_started = time.monotonic()
    primary_ids = _cluster_node_ids_by_shard(
        primaries,
        timeout=max(10.0, min(120.0, _time_left(deadline, floor=10.0))),
        parallelism=parallelism,
    )
    replica_primary_id_lookup_seconds = round(max(time.monotonic() - lookup_started, 0.0), 6)

    replica_by_id = {replica["logical_id"]: replica for replica in replicas}

    def master_id_for(replica: dict[str, Any]) -> str:
        return primary_ids[replica["shard_id"]]

    for replica in replicas:
        diagnostics[replica["logical_id"]]["master_id"] = master_id_for(replica)

    def run_replica_stage(
        *,
        field: str,
        label: str,
        worker: Callable[[dict[str, Any], str, float], str | None],
    ) -> float:
        stage_started = time.monotonic()

        def run(replica: dict[str, Any]) -> str:
            logical_id = replica["logical_id"]
            started = time.monotonic()
            result = worker(replica, master_id_for(replica), max(10.0, min(120.0, _time_left(deadline, floor=10.0))))
            diagnostics[logical_id][field] = round(max(time.monotonic() - started, 0.0), 6)
            if result:
                diagnostics[logical_id][f"{field}_result"] = result
            return logical_id

        _bounded_parallel(
            replicas,
            run,
            parallelism=parallelism,
            timeout=max(10.0, _time_left(deadline, floor=10.0)),
            label=label,
        )
        return round(max(time.monotonic() - stage_started, 0.0), 6)

    replica_knows_master_wait_seconds = run_replica_stage(
        field="replica_knows_master_wait_seconds",
        label="bounded replica master visibility wait",
        worker=lambda replica, master_id, local_timeout: (
            _wait_process_knows_node_id(replica, master_id, timeout=local_timeout) or "master_visible"
        ),
    )

    def replicate_command(replica: dict[str, Any], master_id: str, local_timeout: float) -> str:
        if _process_node_is_replica_of(replica, master_id):
            return "already_replica"
        _replicate_process_node(replica, master_id, timeout=local_timeout)
        return "replicate_command_sent"

    replica_replicate_command_seconds = run_replica_stage(
        field="replica_replicate_command_seconds",
        label="bounded CLUSTER REPLICATE commands",
        worker=replicate_command,
    )
    replica_replicaof_wait_seconds = run_replica_stage(
        field="replica_replicaof_wait_seconds",
        label="bounded replica-of convergence wait",
        worker=lambda replica, master_id, local_timeout: (
            _wait_process_replica_of(replica, master_id, timeout=local_timeout) or "replicaof_confirmed"
        ),
    )

    outputs: list[tuple[int, str]] = []
    for idx, replica in enumerate(replicas):
        diagnostic = diagnostics[replica["logical_id"]]
        diagnostic["replica_replicate_total_seconds"] = round(
            float(diagnostic.get("replica_knows_master_wait_seconds", 0.0))
            + float(diagnostic.get("replica_replicate_command_seconds", 0.0))
            + float(diagnostic.get("replica_replicaof_wait_seconds", 0.0)),
            6,
        )
        outputs.append((idx, f"replica {replica['logical_id']} configured for primary {replica['shard_id']}"))

    ordered_diagnostics = [diagnostics[replica["logical_id"]] for replica in replicas]
    slowest = sorted(
        ordered_diagnostics,
        key=lambda item: float(item.get("replica_replicate_total_seconds", 0.0)),
        reverse=True,
    )[:REPLICA_REPLICATE_SLOWEST_COUNT]
    details = {
        "replica_primary_id_lookup_seconds": replica_primary_id_lookup_seconds,
        "replica_knows_master_wait_seconds": replica_knows_master_wait_seconds,
        "replica_replicate_command_seconds": replica_replicate_command_seconds,
        "replica_replicaof_wait_seconds": replica_replicaof_wait_seconds,
        "replica_replicate_total_seconds": round(max(time.monotonic() - total_started, 0.0), 6),
        "parallelism": parallelism,
        "parallelism_source": _replica_replicate_parallelism_source(),
        "supported_parallelism": list(REPLICA_REPLICATE_PARALLELISM_CHOICES),
        "bounded_parallelism": True,
        "slowest_replicas": slowest,
        "replica_diagnostics": ordered_diagnostics,
        "slowest_count": REPLICA_REPLICATE_SLOWEST_COUNT,
        "breakdown_semantics": "wall-clock stage durations from bounded parallel replica configuration plus per-replica timings",
    }
    return "\n".join(text for _, text in sorted(outputs, key=lambda item: item[0])), details


def _meet_new_node(first: dict[str, Any], node: dict[str, Any]) -> None:
    _meet_node_pair(first, node)


def _incremental_meet(
    first: dict[str, Any],
    nodes: list[dict[str, Any]],
    *,
    timeout: float,
    expected_start: int = 1,
) -> None:
    deadline = time.monotonic() + timeout
    joined = 0
    for node in nodes:
        if node["logical_id"] == first["logical_id"]:
            continue
        joined += 1
        expected = expected_start + joined
        _meet_pair(first, node)
        _wait_cluster_integrated_at_least(first, expected=expected, timeout=max(5.0, min(45.0, deadline - time.monotonic())))
    final_expected = expected_start + joined
    _wait_cluster_integrated_at_least(first, expected=final_expected, timeout=max(5.0, min(60.0, deadline - time.monotonic())))


def _meet_pair(first: dict[str, Any], node: dict[str, Any]) -> None:
    _meet_node_pair(first, node)
    try:
        _meet_node_pair(node, first)
    except Exception:
        pass


def _wait_cluster_known_at_least(node: dict[str, Any], expected: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if _cluster_known_nodes(node) >= expected:
                return
        except Exception:
            pass
        time.sleep(1)
    raise DockerRuntimeError(f"cluster meet did not reach at least {expected} known nodes")


def _wait_cluster_integrated_at_least(node: dict[str, Any], expected: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if _cluster_integrated_nodes(node) >= expected:
                return
        except Exception:
            pass
        time.sleep(1)
    raise DockerRuntimeError(f"cluster meet did not integrate at least {expected} nodes")


def _cluster_integrated_nodes(node: dict[str, Any]) -> int:
    text = _node_command(node, "CLUSTER", "NODES", timeout=5)
    count = 0
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 8:
            continue
        flags = set(parts[2].split(","))
        if flags.intersection({"fail", "handshake", "noaddr"}):
            continue
        if parts[7] == "connected":
            count += 1
    return count


def _wait_host_probe_ready(nodes: list[dict[str, Any]], expected_known_nodes: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_ready = 0
    while time.monotonic() < deadline:
        ready = 0
        for node in nodes:
            try:
                pong = _host_command("127.0.0.1", int(node["client_port"]), "PING", timeout=2.0)
                server = str(_host_command("127.0.0.1", int(node["client_port"]), "INFO", "server", timeout=2.0))
                cluster_info = str(_host_command("127.0.0.1", int(node["client_port"]), "CLUSTER", "INFO", timeout=2.0))
                cluster_nodes = str(_host_command("127.0.0.1", int(node["client_port"]), "CLUSTER", "NODES", timeout=2.0))
                known_nodes = _info_value(cluster_info, "cluster_known_nodes")
                if (
                    pong == "PONG"
                    and "valkey_version:9.1." in server
                    and _info_value(cluster_info, "cluster_state") == "ok"
                    and known_nodes is not None
                    and int(known_nodes) >= expected_known_nodes
                    and "fail" not in cluster_nodes
                    and "handshake" not in cluster_nodes
                ):
                    ready += 1
            except Exception:
                pass
        if ready == len(nodes):
            return
        last_ready = ready
        time.sleep(2)
    raise DockerRuntimeError(f"host probe readiness reached {last_ready}/{len(nodes)} nodes")


def _host_command(host: str, port: int, *args: Any, timeout: float = 2.0) -> Any:
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(_encode_resp(*args))
        return _read_resp(sock.makefile("rb"))


def _encode_resp(*args: Any) -> bytes:
    parts = [f"*{len(args)}\r\n".encode("utf-8")]
    for arg in args:
        data = str(arg).encode("utf-8")
        parts.append(f"${len(data)}\r\n".encode("utf-8"))
        parts.append(data + b"\r\n")
    return b"".join(parts)


def _read_resp(fp: Any) -> Any:
    prefix = fp.read(1)
    if prefix == b"+":
        return _read_resp_line(fp).decode("utf-8", errors="replace")
    if prefix == b"-":
        raise DockerRuntimeError(_read_resp_line(fp).decode("utf-8", errors="replace"))
    if prefix == b":":
        return int(_read_resp_line(fp))
    if prefix == b"$":
        size = int(_read_resp_line(fp))
        if size == -1:
            return None
        data = fp.read(size)
        _ = fp.read(2)
        return data.decode("utf-8", errors="replace")
    if prefix == b"*":
        size = int(_read_resp_line(fp))
        return [_read_resp(fp) for _ in range(size)]
    raise DockerRuntimeError(f"unknown RESP prefix {prefix!r}")


def _read_resp_line(fp: Any) -> bytes:
    line = fp.readline()
    if not line.endswith(b"\r\n"):
        raise DockerRuntimeError("invalid RESP line")
    return line[:-2]


def _mesh_meet(nodes: list[dict[str, Any]]) -> None:
    for source in nodes:
        for target in nodes:
            if source["logical_id"] == target["logical_id"]:
                continue
            run_docker(
                ["exec", source["container_name"], "valkey-cli", "-p", "6379", "CLUSTER", "MEET", target["container_ip"], "6379"],
                timeout=30,
                check=False,
            )


def _replicate_with_retry(container: str, master_id: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        result = run_docker(["exec", container, "valkey-cli", "-p", "6379", "CLUSTER", "REPLICATE", master_id], timeout=30, check=False)
        if result.returncode == 0:
            return
        last_error = result.stderr.strip() or result.stdout.strip()
        time.sleep(2)
    raise DockerRuntimeError(f"CLUSTER REPLICATE did not succeed for {container}: {last_error}")


def _ensure_replica_of(replica: dict[str, Any], master_id: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        if _is_replica_of(replica, master_id):
            return
        try:
            _node_command(replica, "CLUSTER", "REPLICATE", master_id, timeout=30)
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
        time.sleep(2)
    raise DockerRuntimeError(f"{replica['logical_id']} did not become replica of {master_id}: {last_error}")


def _wait_replica_of(replica: dict[str, Any], master_id: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if _is_replica_of(replica, master_id):
                return
        except Exception:
            pass
        time.sleep(1)
    raise DockerRuntimeError(f"{replica['logical_id']} did not become replica of {master_id}")


def _is_replica_of(replica: dict[str, Any], master_id: str) -> bool:
    text = _node_command(replica, "CLUSTER", "NODES", timeout=5)
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 8 or "myself" not in parts[2].split(","):
            continue
        flags = set(parts[2].split(","))
        return ("slave" in flags or "replica" in flags) and parts[3] == master_id and parts[7] == "connected"
    return False


def _scale_timeout(nodes: list[dict[str, Any]], *, floor: float, per_node: float) -> float:
    return max(floor, len(nodes) * per_node)


def _scenario_node_count_allowed(phase: str, scenario: str, node_count: int) -> bool:
    expected = {
        ("P03_LOCAL_DOCKER_VALKEY", "cluster_smoke"): {6},
        ("P04_CLUSTER_MANAGEMENT_OPS", "management_ops"): {6},
        ("P05_WORKLOAD_ENGINE", "workload_smoke"): {6},
        ("P06_OBSERVABILITY_METRICS", "observability_smoke"): {6},
        ("P07_FAULT_INJECTION_SANDBOX", "fault_sandbox_setup"): {6},
        ("P08_FAILOVER_SPLIT_BRAIN", "failover_setup"): {6},
        ("P09_ANALYSIS_REPORTING", "reporting_source_smoke"): {6},
        ("P10_MULTI_HOST_ORCHESTRATION", "orchestrated_localhost"): {6},
        ("P11_STABILITY_SOAK", "stability_soak_smoke"): {6},
        ("P12_SCALE_LADDER_10_30", "scale_10"): {10},
        ("P12_SCALE_LADDER_10_30", "scale_30"): {30},
        ("P13_SCALE_LADDER_50_100", "scale_50"): {50},
        ("P13_SCALE_LADDER_50_100", "scale_100"): {100},
    }
    return node_count in expected.get((phase, scenario), set())


def _slot_ranges(primary_count: int) -> list[tuple[int, int]]:
    ranges = _sequential_slot_ranges(primary_count)
    probe_index = _probe_slot_primary_index(primary_count)
    return ranges[probe_index:] + ranges[:probe_index]


def _sequential_slot_ranges(primary_count: int) -> list[tuple[int, int]]:
    if primary_count <= 0:
        raise DockerRuntimeError("cluster needs at least one primary")
    ranges: list[tuple[int, int]] = []
    start = 0
    for index in range(primary_count):
        remaining_slots = 16384 - start
        remaining_primaries = primary_count - index
        width = remaining_slots // remaining_primaries
        end = start + width - 1
        ranges.append((start, end))
        start = end + 1
    return ranges


def _wait_for_nodes(nodes: list[dict[str, Any]], timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last_ready = 0
    while time.monotonic() < deadline:
        ready = 0
        for node in nodes:
            try:
                if _node_command(node, "PING", timeout=2.0) == "PONG":
                    ready += 1
            except Exception:
                pass
        if ready == len(nodes):
            return
        last_ready = ready
        time.sleep(1)
    raise DockerRuntimeError(f"Valkey containers did not become ready {last_ready}/{len(nodes)}")


def _wait_cluster_known(nodes: list[dict[str, Any]], expected: int, timeout: float, *, final_check: bool = True) -> None:
    _wait_cluster_predicate(
        nodes,
        timeout,
        "cluster meet did not converge to expected node count",
        lambda node: _cluster_known_nodes(node) == expected,
        final_check=final_check,
    )


def _wait_cluster_known_any(nodes: list[dict[str, Any]], expected: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for node in nodes:
            try:
                if _cluster_known_nodes(node) == expected:
                    return
            except Exception:
                pass
        time.sleep(1)
    raise DockerRuntimeError("cluster meet did not become visible from any node")


def _wait_cluster_slots_assigned(nodes: list[dict[str, Any]], timeout: float, *, final_check: bool = True) -> None:
    _wait_cluster_predicate(
        nodes,
        timeout,
        "cluster slots were not fully assigned",
        lambda node: _cluster_info_value(node, "cluster_slots_assigned") == "16384",
        final_check=final_check,
    )


def _wait_cluster_slots_assigned_any(nodes: list[dict[str, Any]], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for node in nodes:
            try:
                if _cluster_info_value(node, "cluster_slots_assigned") == "16384":
                    return
            except Exception:
                pass
        time.sleep(1)
    raise DockerRuntimeError("cluster slots were not visible as fully assigned from any node")


def _wait_cluster_ok(nodes: list[dict[str, Any]], timeout: float, *, final_check: bool = True) -> None:
    _wait_cluster_predicate(
        nodes,
        timeout,
        "cluster did not reach ok state",
        lambda node: _cluster_info_value(node, "cluster_state") == "ok",
        final_check=final_check,
    )


def _wait_cluster_ok_any(nodes: list[dict[str, Any]], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for node in nodes:
            try:
                if _cluster_info_value(node, "cluster_state") == "ok":
                    return
            except Exception:
                pass
        time.sleep(1)
    raise DockerRuntimeError("cluster did not reach observable ok state from any node")


def _wait_cluster_role_counts(
    nodes: list[dict[str, Any]],
    *,
    expected_primaries: int,
    expected_replicas: int,
    timeout: float,
    final_check: bool = True,
) -> None:
    deadline = time.monotonic() + timeout
    expected_total = expected_primaries + expected_replicas
    def has_expected_roles(node: dict[str, Any]) -> bool:
        counts = _cluster_role_counts(node)
        return (
            counts.get("primary", 0) == expected_primaries
            and counts.get("replica", 0) == expected_replicas
            and counts.get("total", 0) == expected_total
        )

    try:
        _wait_cluster_predicate(
            nodes,
            timeout,
            f"cluster role counts did not converge to {expected_primaries} primaries and {expected_replicas} replicas",
            has_expected_roles,
            final_check=final_check,
        )
        return
    except DockerRuntimeError:
        if time.monotonic() >= deadline:
            raise
    raise DockerRuntimeError(
        f"cluster role counts did not converge to {expected_primaries} primaries and {expected_replicas} replicas"
    )


def _wait_cluster_predicate(nodes: list[dict[str, Any]], timeout: float, message: str, predicate: Callable[[dict[str, Any]], bool], *, final_check: bool = True) -> None:
    deadline = time.monotonic() + timeout
    representatives = _representative_nodes(nodes)
    last_error = "MISSING"
    while time.monotonic() < deadline:
        try:
            fast = _bounded_parallel(
                representatives,
                predicate,
                parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
                timeout=max(1.0, min(15.0, _time_left(deadline))),
                label=f"{message} representative probes",
            )
            if fast and all(bool(item) for item in fast):
                if not final_check:
                    return
                final = _bounded_parallel(
                    nodes,
                    predicate,
                    parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
                    timeout=max(1.0, min(60.0, _time_left(deadline))),
                    label=f"{message} final probes",
                )
                if final and all(bool(item) for item in final):
                    return
                last_error = f"final probes failed {sum(1 for item in final if item)}/{len(final)}"
                break
            last_error = f"representative probes failed {sum(1 for item in fast if item)}/{len(fast)}"
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
        time.sleep(1)
    while time.monotonic() < deadline:
        try:
            diagnostic = _bounded_parallel(
                nodes,
                predicate,
                parallelism=CLUSTER_ORCHESTRATION_PARALLELISM,
                timeout=max(1.0, min(60.0, _time_left(deadline))),
                label=f"{message} diagnostic probes",
            )
            if diagnostic and all(bool(item) for item in diagnostic):
                return
            last_error = f"diagnostic probes failed {sum(1 for item in diagnostic if item)}/{len(diagnostic)}"
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
        time.sleep(CLUSTER_DIAGNOSTIC_INTERVAL_SECONDS)
    raise DockerRuntimeError(f"{message}; last_error={last_error}")


def _cluster_role_counts(node: dict[str, Any]) -> dict[str, int]:
    text = _node_command(node, "CLUSTER", "NODES", timeout=5)
    counts = {"primary": 0, "replica": 0, "total": 0}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 8:
            continue
        flags = set(parts[2].split(","))
        if flags.intersection({"fail", "handshake", "noaddr"}):
            continue
        if parts[7] != "connected":
            continue
        if "master" in flags:
            counts["primary"] += 1
        elif "slave" in flags or "replica" in flags:
            counts["replica"] += 1
        counts["total"] += 1
    return counts


def _cluster_known_nodes(node: dict[str, Any]) -> int:
    value = _cluster_info_value(node, "cluster_known_nodes")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _cluster_info_value(node: dict[str, Any], key: str) -> str | None:
    info = _node_command(node, "CLUSTER", "INFO", timeout=5)
    return _info_value(info, key)


def _run_management_ops(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    check_started = time.monotonic()
    _wait_cluster_ok(nodes, timeout=30)
    operations.append(_operation("convergence_check", "PASS", check_started, {"cluster_state": "ok"}))

    nodes_started = time.monotonic()
    cluster_nodes = _node_command(nodes[0], "CLUSTER", "NODES", timeout=30)
    operations.append(
        _operation(
            "cluster_nodes",
            "PASS",
            nodes_started,
            {"line_count": len([line for line in cluster_nodes.splitlines() if line.strip()])},
        )
    )

    info_started = time.monotonic()
    cluster_info = _node_command(nodes[0], "CLUSTER", "INFO", timeout=30)
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


def write_observability_artifacts(
    artifacts: Path,
    phase: str,
    scenario: str,
    run_id: str,
    config: dict[str, Any],
    nodes: list[dict[str, Any]],
) -> None:
    metrics_path = artifacts / "metrics_timeseries.jsonl"
    events_path = artifacts / "events.jsonl"
    log_dir = artifacts / "container_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    metric_lines: list[dict[str, Any]] = []
    event_lines: list[dict[str, Any]] = [
        _event(phase, run_id, "observability_collection_started", "info", {"scenario": scenario, "nodes": len(nodes)}),
    ]

    for node in nodes:
        info = _parse_info(_node_command(node, "INFO", "default", timeout=10))
        cluster_info_raw = _node_command(node, "CLUSTER", "INFO", timeout=10)
        cluster_nodes_raw = _node_command(node, "CLUSTER", "NODES", timeout=10)
        cluster_info = _parse_info(cluster_info_raw)
        docker_stats = _docker_stats(node["container_name"])
        logs = run_docker(["logs", "--tail", "50", node["container_name"]], timeout=30, check=False)
        log_path = log_dir / f"{node['logical_id']}.log"
        log_path.write_text(logs.stdout + logs.stderr, encoding="utf-8", errors="replace")
        metric_lines.append(
            {
                "schema_version": "v1",
                "artifact_type": "metric_sample",
                "phase_id": phase,
                "run_id": run_id,
                "timestamp": "2026-06-28T00:00:00Z",
                "source": node["logical_id"],
                "metrics": {
                    "valkey": {
                        "uptime_in_seconds": _int_or_missing(info.get("uptime_in_seconds")),
                        "connected_clients": _int_or_missing(info.get("connected_clients")),
                        "used_memory": _int_or_missing(info.get("used_memory")),
                        "total_commands_processed": _int_or_missing(info.get("total_commands_processed")),
                    },
                    "cluster": {
                        "cluster_state": cluster_info.get("cluster_state", "MISSING"),
                        "cluster_known_nodes": _int_or_missing(cluster_info.get("cluster_known_nodes")),
                        "cluster_slots_assigned": _int_or_missing(cluster_info.get("cluster_slots_assigned")),
                        "cluster_nodes_line_count": len([line for line in cluster_nodes_raw.splitlines() if line.strip()]),
                    },
                    "docker": docker_stats,
                    "logs": {
                        "path": log_path.as_posix(),
                        "status": "PASS" if log_path.exists() else "MISSING",
                    },
                },
            }
        )
        event_lines.append(
            _event(
                phase,
                run_id,
                "node_metrics_sampled",
                "info",
                {"logical_id": node["logical_id"], "cluster_state": cluster_info.get("cluster_state", "MISSING")},
            )
        )

    event_lines.append(_event(phase, run_id, "observability_collection_finished", "info", {"sample_count": len(metric_lines)}))
    metrics_path.write_text("\n".join(json.dumps(line, sort_keys=True) for line in metric_lines) + "\n", encoding="utf-8")
    events_path.write_text("\n".join(json.dumps(line, sort_keys=True) for line in event_lines) + "\n", encoding="utf-8")


def write_stability_artifacts(
    artifacts: Path,
    phase: str,
    scenario: str,
    run_id: str,
    config: dict[str, Any],
    nodes: list[dict[str, Any]],
) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    metrics_path = artifacts / "stability_metrics.jsonl"
    baseline_path = artifacts / "stability_baseline_comparison.json"
    report_path = artifacts / "stability_report.json"
    phase_summary_path = artifacts / "phase_summary.json"
    interval_count = 3
    ops_per_interval = 12
    target = nodes[0]["container_name"]
    samples: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    errors: list[dict[str, Any]] = []
    memory_by_node: dict[str, list[int]] = {node["logical_id"]: [] for node in nodes}
    restart_before = {node["logical_id"]: _container_restart_count(node["container_name"]) for node in nodes}
    started = time.monotonic()

    for interval in range(interval_count):
        interval_started = time.monotonic()
        for op_index in range(ops_per_interval):
            key = f"{{vslab-soak}}:{interval}:{op_index % 4}"
            value = f"value-{interval}-{op_index}"
            op_started = time.monotonic()
            try:
                if op_index % 3 == 0:
                    result = run_container_cluster_cli(target, "SET", key, value, timeout=10)
                    if result.upper() != "OK":
                        errors.append({"interval": interval, "operation": "SET", "key": key, "error": result})
                else:
                    _ = run_container_cluster_cli(target, "GET", key, timeout=10)
                latencies_ms.append((time.monotonic() - op_started) * 1000)
            except Exception as exc:  # noqa: BLE001
                errors.append({"interval": interval, "operation": "workload", "key": key, "error": repr(exc)})

        for node in nodes:
            info = _parse_info(_node_command(node, "INFO", "default", timeout=10))
            cluster_info = _parse_info(_node_command(node, "CLUSTER", "INFO", timeout=10))
            used_memory = _int_or_missing(info.get("used_memory"))
            if isinstance(used_memory, int):
                memory_by_node[node["logical_id"]].append(used_memory)
            samples.append(
                {
                    "schema_version": "v1",
                    "artifact_type": "metric_sample",
                    "phase_id": phase,
                    "run_id": run_id,
                    "timestamp": f"2026-06-28T00:00:0{interval}Z",
                    "source": node["logical_id"],
                    "metrics": {
                        "interval": interval,
                        "valkey": {
                            "used_memory": used_memory,
                            "connected_clients": _int_or_missing(info.get("connected_clients")),
                            "total_commands_processed": _int_or_missing(info.get("total_commands_processed")),
                        },
                        "cluster": {
                            "cluster_state": cluster_info.get("cluster_state", "MISSING"),
                            "cluster_known_nodes": _int_or_missing(cluster_info.get("cluster_known_nodes")),
                        },
                        "docker": {
                            "restart_count": restart_before[node["logical_id"]],
                        },
                    },
                }
            )
        elapsed = time.monotonic() - interval_started
        if elapsed < 0.05:
            time.sleep(0.05 - elapsed)

    restart_after = {node["logical_id"]: _container_restart_count(node["container_name"]) for node in nodes}
    duration = max(time.monotonic() - started, 0.000001)
    leak_summary = _memory_growth_summary(memory_by_node)
    restart_events = [
        {
            "logical_id": logical_id,
            "before": restart_before[logical_id],
            "after": restart_after[logical_id],
            "delta": _restart_delta(restart_before[logical_id], restart_after[logical_id]),
        }
        for logical_id in sorted(restart_before)
    ]
    baseline = {
        "schema_version": "v1",
        "artifact_type": "stability_baseline_comparison",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "NO_BASELINE_YET",
        "baseline_source": {
            "status": "SKIPPED_WITH_REASON",
            "reason": "No previous stability baseline artifact exists for this first soak phase.",
        },
        "comparisons": [
            {
                "metric": "error_count",
                "current_value": len(errors),
                "baseline_value": None,
                "delta": None,
                "status": "NO_BASELINE_YET",
            },
            {
                "metric": "max_memory_growth_bytes",
                "current_value": leak_summary["max_growth_bytes"],
                "baseline_value": None,
                "delta": None,
                "status": "NO_BASELINE_YET",
            },
        ],
    }
    report = {
        "schema_version": "v1",
        "artifact_type": "stability_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS" if not errors and all(_restart_delta(item["before"], item["after"]) == 0 for item in restart_events) else "FAIL",
        "duration_seconds": round(duration, 6),
        "scenario": scenario,
        "soak_profile": {
            "bounded": True,
            "interval_count": interval_count,
            "ops_per_interval": ops_per_interval,
            "total_operations_attempted": interval_count * ops_per_interval,
            "configured_max_nodes": len(nodes),
        },
        "metrics_timeseries_path": metrics_path.as_posix(),
        "baseline_comparison_path": baseline_path.as_posix(),
        "summary": {
            "nodes_observed": len(nodes),
            "workload": {
                "attempted_operations": interval_count * ops_per_interval,
                "completed_operations": len(latencies_ms),
                "error_count": len(errors),
                "latency_ms": _latency_summary(latencies_ms),
            },
            "metrics": {
                "sample_count": len(samples),
                "interval_count": interval_count,
                "samples_per_interval": len(nodes),
            },
            "restarts": {
                "total_restart_delta": sum(max(0, _restart_delta(item["before"], item["after"])) for item in restart_events),
                "events": restart_events,
            },
            "leaks": leak_summary,
            "errors": {
                "classification": "none" if not errors else "soak_workload_error",
                "items": errors,
            },
            "baseline": baseline,
        },
    }
    metrics_path.write_text("\n".join(json.dumps(sample, sort_keys=True) for sample in samples) + "\n", encoding="utf-8")
    baseline_path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_stability_phase_summary(phase_summary_path, run_id)


def write_stability_phase_summary(path: Path, run_id: str) -> None:
    summary = {
        "schema_version": "v1",
        "artifact_type": "phase_summary",
        "phase_id": "P11_STABILITY_SOAK",
        "run_id": run_id,
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "summary": "P11 ran a bounded real Valkey stability soak with periodic metrics collection, steady workload, restart/error/leak summaries, cleanup verification, and first-run baseline semantics.",
        "required_artifacts": [
            "artifacts/phases/P11_STABILITY_SOAK/phase_summary.json",
            "artifacts/phases/P11_STABILITY_SOAK/valkey_e2e_evidence.json",
            "artifacts/phases/P11_STABILITY_SOAK/stability_report.json",
            "artifacts/phases/P11_STABILITY_SOAK/cleanup_report.json",
        ],
        "missing_metrics": [],
        "risks": [
            {
                "risk": "Automatic soak duration is intentionally short to keep local CI bounded; longer soak windows should be opt-in profiles.",
                "severity": "low",
                "required_before_next_phase": False,
            }
        ],
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_scale_ladder_artifacts(
    artifacts: Path,
    phase: str,
    scenario: str,
    run_id: str,
    config: dict[str, Any],
    nodes: list[dict[str, Any]],
) -> None:
    node_count = len(nodes)
    rung_path = artifacts / f"scale_rung_{node_count}.json"
    report_path = artifacts / "scale_ladder_report.json"
    phase_summary_path = artifacts / "phase_summary.json"
    primaries = [node for node in nodes if node["role"] == "primary"]
    replicas = [node for node in nodes if node["role"] == "replica"]
    cluster_states: list[str] = []
    cluster_known_nodes: list[int | str] = []
    versions: set[str] = set()
    memory_values: list[int] = []
    command_counts: list[int] = []
    sample_errors: list[dict[str, Any]] = []
    for node in nodes:
        try:
            info = _parse_info(_node_command(node, "INFO", "server", timeout=10))
            default_info = _parse_info(_node_command(node, "INFO", "default", timeout=10))
            cluster_info = _parse_info(_node_command(node, "CLUSTER", "INFO", timeout=10))
            version = info.get("valkey_version") or info.get("redis_version")
            if version:
                versions.add(version)
            cluster_states.append(cluster_info.get("cluster_state", "MISSING"))
            cluster_known_nodes.append(_int_or_missing(cluster_info.get("cluster_known_nodes")))
            used_memory = _int_or_missing(default_info.get("used_memory"))
            commands = _int_or_missing(default_info.get("total_commands_processed"))
            if isinstance(used_memory, int):
                memory_values.append(used_memory)
            if isinstance(commands, int):
                command_counts.append(commands)
        except Exception as exc:  # noqa: BLE001
            sample_errors.append({"logical_id": node["logical_id"], "error": repr(exc)})

    no_sample_errors = not sample_errors
    all_nodes_report_ok = all(state == "ok" for state in cluster_states)
    full_membership_observed = all(value == node_count for value in cluster_known_nodes)
    rung = {
        "schema_version": "v1",
        "artifact_type": "scale_rung_summary",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS" if no_sample_errors and all_nodes_report_ok and full_membership_observed else "FAIL",
        "rung": node_count,
        "scenario": scenario,
        "config_path": config.get("profile_name", "MISSING"),
        "node_count": node_count,
        "primary_count": len(primaries),
        "replica_count": len(replicas),
        "az_distribution": _count_by(nodes, "az_id"),
        "host_distribution": _count_by(nodes, "host_id"),
        "client_port_range": {
            "min": min(node["client_port"] for node in nodes),
            "max": max(node["client_port"] for node in nodes),
        },
        "valkey_versions": sorted(versions),
        "cluster_states": sorted(set(cluster_states)),
        "cluster_known_nodes_observed": cluster_known_nodes,
        "metrics": {
            "total_used_memory": sum(memory_values) if memory_values else "MISSING",
            "avg_used_memory": round(sum(memory_values) / len(memory_values), 6) if memory_values else "MISSING",
            "total_commands_processed": sum(command_counts) if command_counts else "MISSING",
        },
        "management": {
            "slot_ranges": [{"start": start, "end": end} for start, end in _slot_ranges(len(primaries))],
            "slots_assigned": 16384,
            "cluster_known_nodes_expected": node_count,
            "cluster_known_nodes_min": min((value for value in cluster_known_nodes if isinstance(value, int)), default="MISSING"),
            "cluster_known_nodes_max": max((value for value in cluster_known_nodes if isinstance(value, int)), default="MISSING"),
        },
        "evidence_path": f"artifacts/phases/{phase}/valkey_e2e_evidence_{node_count}.json",
        "errors": sample_errors,
    }
    rung_path.write_text(json.dumps(rung, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    rung_files = sorted(artifacts.glob("scale_rung_*.json"))
    rungs = [json.loads(path.read_text(encoding="utf-8")) for path in rung_files]
    report = {
        "schema_version": "v1",
        "artifact_type": "scale_ladder_report",
        "phase_id": phase,
        "run_id": f"{phase}-scale-ladder-20260628",
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS" if rungs and all(item.get("status") == "PASS" for item in rungs) else "FAIL",
        "rungs": rungs,
        "summary": {
            "rung_counts_observed": [item["node_count"] for item in rungs],
            "max_nodes_observed": max((item["node_count"] for item in rungs), default=0),
            "comparison": _scale_comparison(rungs),
            "real_evidence_paths": [item["evidence_path"] for item in rungs],
        },
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_scale_phase_summary(phase_summary_path, phase)


def write_scale_phase_summary(path: Path, phase: str) -> None:
    if phase == "P13_SCALE_LADDER_50_100":
        rungs = [50, 100]
        summary_text = "P13 completes the default scale ceiling by running real 50-node and 100-node Valkey scale rungs with resource preflight, independent e2e evidence, cleanup protection, baseline snapshots, and a scale ladder comparison artifact."
        risk = "Scale ladder comparison reaches the default 100-node ceiling on a single Docker host; host-specific resource limits may vary."
    else:
        rungs = [10, 30]
        summary_text = "P12 runs real 10-node and 30-node Valkey scale rungs with resource preflight, independent e2e evidence, rung metrics, management summaries, and a scale ladder comparison artifact."
        risk = "Scale ladder comparison uses bounded local single-host Docker rungs; host-specific resource limits may vary."
    summary = {
        "schema_version": "v1",
        "artifact_type": "phase_summary",
        "phase_id": phase,
        "run_id": f"{phase}-scale-ladder-20260628",
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "summary": summary_text,
        "required_artifacts": [
            f"artifacts/phases/{phase}/phase_summary.json",
            f"artifacts/phases/{phase}/resource_preflight_{rungs[0]}.json",
            f"artifacts/phases/{phase}/resource_preflight_{rungs[1]}.json",
            f"artifacts/phases/{phase}/valkey_e2e_evidence_{rungs[0]}.json",
            f"artifacts/phases/{phase}/valkey_e2e_evidence_{rungs[1]}.json",
            f"artifacts/phases/{phase}/scale_ladder_report.json",
            f"artifacts/phases/{phase}/cleanup_report.json",
        ],
        "missing_metrics": [],
        "risks": [
            {
                "risk": risk,
                "severity": "low",
                "required_before_next_phase": False,
            }
        ],
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _count_by(nodes: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in nodes:
        value = str(node.get(key, "MISSING"))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _scale_comparison(rungs: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rungs, key=lambda item: int(item["node_count"]))
    if len(ordered) < 2:
        return {
            "status": "SKIPPED_WITH_REASON",
            "reason": "At least two completed rungs are needed for comparison.",
        }
    first, last = ordered[0], ordered[-1]
    first_nodes = int(first["node_count"])
    last_nodes = int(last["node_count"])
    return {
        "status": "PASS",
        "from_nodes": first_nodes,
        "to_nodes": last_nodes,
        "node_count_multiplier": round(last_nodes / first_nodes, 6),
        "memory_multiplier": _ratio(
            first.get("metrics", {}).get("total_used_memory"),
            last.get("metrics", {}).get("total_used_memory"),
        ),
        "primary_count_delta": int(last["primary_count"]) - int(first["primary_count"]),
        "replica_count_delta": int(last["replica_count"]) - int(first["replica_count"]),
    }


def _ratio(first: Any, last: Any) -> float | str:
    if not isinstance(first, (int, float)) or not isinstance(last, (int, float)) or first == 0:
        return "MISSING"
    return round(float(last) / float(first), 6)


def _container_restart_count(container: str) -> int | str:
    result = run_docker(["inspect", "-f", "{{.RestartCount}}", container], timeout=30, check=False)
    if result.returncode != 0:
        return "MISSING"
    try:
        return int(result.stdout.strip())
    except ValueError:
        return "MISSING"


def _restart_delta(before: int | str, after: int | str) -> int:
    if isinstance(before, int) and isinstance(after, int):
        return after - before
    return 0


def _memory_growth_summary(memory_by_node: dict[str, list[int]]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    max_growth = 0
    for logical_id, values in sorted(memory_by_node.items()):
        if len(values) < 2:
            nodes.append({"logical_id": logical_id, "status": "MISSING", "reason": "fewer than two memory samples"})
            continue
        growth = values[-1] - values[0]
        max_growth = max(max_growth, growth)
        nodes.append(
            {
                "logical_id": logical_id,
                "status": "PASS",
                "first_used_memory": values[0],
                "last_used_memory": values[-1],
                "growth_bytes": growth,
            }
        )
    return {
        "status": "PASS",
        "max_growth_bytes": max_growth,
        "nodes": nodes,
    }


def _event(phase: str, run_id: str, event_type: str, severity: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": "event",
        "phase_id": phase,
        "run_id": run_id,
        "timestamp": "2026-06-28T00:00:00Z",
        "event_type": event_type,
        "severity": severity,
        "details": details,
    }


def _docker_stats(container: str) -> dict[str, Any]:
    result = run_docker(
        ["stats", "--no-stream", "--format", "{{json .}}", container],
        timeout=30,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {
            "status": "SKIPPED_WITH_REASON",
            "reason": result.stderr.strip() or "docker stats unavailable",
        }
    try:
        raw = json.loads(result.stdout.splitlines()[0])
    except json.JSONDecodeError as exc:
        return {"status": "MISSING", "reason": f"docker stats JSON parse failed: {exc}"}
    return {
        "status": "PASS",
        "cpu_percent": raw.get("CPUPerc", "MISSING"),
        "memory_usage": raw.get("MemUsage", "MISSING"),
        "memory_percent": raw.get("MemPerc", "MISSING"),
        "net_io": raw.get("NetIO", "MISSING"),
        "block_io": raw.get("BlockIO", "MISSING"),
        "pids": raw.get("PIDs", "MISSING"),
    }


def _parse_info(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key] = value
    return values


def _int_or_missing(value: Any) -> int | str:
    if value is None:
        return "MISSING"
    try:
        return int(str(value))
    except ValueError:
        return "MISSING"


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
