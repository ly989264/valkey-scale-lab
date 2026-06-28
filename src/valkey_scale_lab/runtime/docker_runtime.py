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
RUN_ID = "P03_LOCAL_DOCKER_VALKEY-cluster_smoke-20260628"


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
    if phase != "P03_LOCAL_DOCKER_VALKEY":
        raise DockerRuntimeError(f"P03 runtime does not implement phase {phase}")
    if scenario != "cluster_smoke":
        raise DockerRuntimeError(f"P03 runtime does not implement scenario {scenario}")

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
    cleanup_by_label(phase=phase, run_id=RUN_ID)
    run_docker(
        [
            "network",
            "create",
            "--label",
            f"{LABEL_PREFIX}.project={PROJECT}",
            "--label",
            f"{LABEL_PREFIX}.phase={phase}",
            "--label",
            f"{LABEL_PREFIX}.run_id={RUN_ID}",
            network_name,
        ],
        timeout=120,
    )

    nodes = _node_specs(config, phase, scenario)
    started: list[dict[str, Any]] = []
    try:
        for node in nodes:
            container_id = _start_container(node, network_name, config["runtime"]["valkey_image"], phase, scenario)
            node["container_id"] = container_id
            node["pid"] = _container_pid(container_id)
            node["container_ip"] = _container_ip(container_id, network_name)
            started.append(node)
        _configure_cluster(nodes)
        state = {
            "schema_version": "v1",
            "cluster_id": RUN_ID,
            "phase_id": phase,
            "scenario": scenario,
            "runtime": {
                "type": "docker",
                "sandbox_network": True,
                "network_name": network_name,
                "run_id": RUN_ID,
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
        cleanup_by_label(phase=phase, run_id=RUN_ID)
        raise


def cleanup_scenario(*, state_path: str | Path, artifacts_dir: str | Path, out_path: str | Path) -> dict[str, Any]:
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    phase = state.get("phase_id", "P03_LOCAL_DOCKER_VALKEY")
    run_id = state.get("runtime", {}).get("run_id", RUN_ID)
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


def _node_specs(config: dict[str, Any], phase: str, scenario: str) -> list[dict[str, Any]]:
    cluster = config["cluster"]
    azs = list(config["network"]["azs"])
    shards = int(cluster["shards"])
    replicas = int(cluster["replicas_per_shard"])
    specs: list[dict[str, Any]] = []
    ordinal = 0
    for shard in range(shards):
        shard_id = f"shard-{shard:04d}"
        specs.append(_spec(cluster, phase, scenario, ordinal, shard_id, "primary", azs[shard % len(azs)]))
        ordinal += 1
    for shard in range(shards):
        for replica in range(replicas):
            shard_id = f"shard-{shard:04d}"
            az = azs[(shard + replica + 1) % len(azs)]
            specs.append(_spec(cluster, phase, scenario, ordinal, shard_id, f"replica-{replica:02d}", az))
            ordinal += 1
    return specs


def _spec(cluster: dict[str, Any], phase: str, scenario: str, ordinal: int, shard_id: str, role_suffix: str, az_id: str) -> dict[str, Any]:
    role = "primary" if role_suffix == "primary" else "replica"
    logical_id = f"{shard_id}-{role_suffix}"
    safe_run = RUN_ID.lower().replace("_", "-")
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


def _start_container(node: dict[str, Any], network_name: str, image: str, phase: str, scenario: str) -> str:
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
        f"{LABEL_PREFIX}.run_id={RUN_ID}",
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


def _configure_cluster(nodes: list[dict[str, Any]]) -> None:
    _wait_for_nodes(nodes)
    first = nodes[0]
    for node in nodes[1:]:
        run_container_cli(first["container_name"], "CLUSTER", "MEET", node["container_ip"], "6379", timeout=30)
    _wait_cluster_known(nodes, expected=len(nodes), timeout=90)

    primaries = [node for node in nodes if node["role"] == "primary"]
    replicas = [node for node in nodes if node["role"] == "replica"]
    slot_ranges = [(5461, 10922), (0, 5460), (10923, 16383)]
    for primary, (start, end) in zip(primaries, slot_ranges):
        _add_slots(primary["container_name"], start, end)
    _wait_cluster_slots_assigned(nodes, timeout=90)

    primary_ids = {node["shard_id"]: run_container_cli(node["container_name"], "CLUSTER", "MYID") for node in primaries}
    for replica in replicas:
        master_id = primary_ids[replica["shard_id"]]
        run_container_cli(replica["container_name"], "CLUSTER", "REPLICATE", master_id, timeout=30)
    _wait_cluster_ok(nodes, timeout=90)


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
