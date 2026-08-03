from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from valkey_scale_lab.observability.cluster import (
    FullClusterValidator,
    NodeEndpoint,
    TopologyObserver,
)
from valkey_scale_lab.observability.contracts import SemanticFailure
from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.runtime.docker_runtime import DockerRuntimeError
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline, shared_monotonic


def _boundary_docker(args: list[str], *, timeout: int = 60) -> str:
    completed = subprocess.run(
        ["docker", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _boundary_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _boundary_valkey_ports(count: int) -> list[int]:
    ports: list[int] = []
    used: set[int] = set()
    while len(ports) < count:
        port = _boundary_free_port()
        if port > 55000 or port + 10000 > 65535:
            continue
        if port in used or port + 10000 in used:
            continue
        used.add(port)
        used.add(port + 10000)
        ports.append(port)
    return ports


def _boundary_wait_ping(container: str, port: int) -> None:
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        ping = subprocess.run(
            ["docker", "exec", container, "valkey-cli", "-p", str(port), "PING"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
        if ping.returncode == 0 and ping.stdout.strip() == "PONG":
            return
        time.sleep(0.2)
    raise AssertionError(f"Valkey port {port} did not answer PING")


def _boundary_wait_topology(endpoints: list[NodeEndpoint]) -> dict[str, object]:
    deadline = time.monotonic() + 30.0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return TopologyObserver(endpoints, observer_count=3, timeout=5.0).run(
                expected_node_count=len(endpoints)
            )
        except SemanticFailure as exc:
            last_error = exc
            time.sleep(0.5)
    raise AssertionError(f"CLUSTER SHARDS did not become healthy: {last_error}")


def test_cached_production_image_supports_m2_shell_kill_and_proc_probe() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is unavailable")
    image = docker_runtime.CUSTOM_VALKEY_IMAGE
    inspected = subprocess.run(
        [docker, "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if inspected.returncode != 0:
        pytest.skip(f"cached production image {image} is unavailable")

    script = (
        "command -v sh >/dev/null || exit 73; "
        "command -v kill >/dev/null || exit 74; "
        "command -v cat >/dev/null || exit 75; "
        "command -v valkey-cli >/dev/null || exit 76; "
        "command -v getconf >/dev/null || exit 77; "
        "command -v awk >/dev/null || exit 78; "
        "command -v readlink >/dev/null || exit 79; "
        "getconf CLK_TCK >/dev/null || exit 80; "
        "getconf PAGESIZE >/dev/null || exit 81; "
        "valkey-server --port 6399 --cluster-enabled yes "
        "--cluster-config-file /tmp/vslab-nodes.conf --appendonly no "
        "--daemonize no --logfile /tmp/vslab.log & pid=$!; "
        "attempt=0; until valkey-cli -p 6399 PING >/dev/null 2>&1; do "
        "attempt=$((attempt + 1)); [ \"$attempt\" -lt 50 ] || exit 82; sleep 0.1; done; "
        "readlink /proc/$pid/exe >/dev/null || exit 85; "
        "stat_line=$(cat /proc/$pid/stat) && "
        'case "$stat_line" in *") "*) ;; *) exit 71;; esac; '
        'stat_tail=${stat_line##*) }; state=${stat_tail%% *}; '
        'case "$state" in R|S|D|T|t|W|K|P|I) ;; *) exit 72;; esac; '
        'kill -KILL "$pid" && wait "$pid" 2>/dev/null; '
        'test ! -e "/proc/$pid/stat"'
    )
    completed = subprocess.run(
        [docker, "run", "--rm", "--entrypoint", "sh", image, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(
    os.environ.get("VSLAB_RUN_REAL_BOUNDARY_SMOKE") != "1",
    reason="set VSLAB_RUN_REAL_BOUNDARY_SMOKE=1 to run Docker/Valkey boundary smoke",
)
def test_nodehost_resource_and_topology_boundary_smoke() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is unavailable")
    image = docker_runtime.CUSTOM_VALKEY_IMAGE
    inspected = subprocess.run(
        [docker, "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if inspected.returncode != 0:
        pytest.skip(f"cached production image {image} is unavailable")

    run_id = f"vslab-boundary-{os.getpid()}-{int(time.time())}"
    container = f"{run_id}-nodehost"
    ports = _boundary_valkey_ports(6)
    docker_args = ["run", "-d", "--name", container]
    for port in ports:
        docker_args.extend(["-p", f"127.0.0.1:{port}:{port}"])
        docker_args.extend(["-p", f"127.0.0.1:{port + 10000}:{port + 10000}"])
    docker_args.extend([image, "sleep", "600"])

    try:
        container_id = _boundary_docker(docker_args, timeout=60)
        for port in ports:
            _boundary_docker(
                [
                    "exec",
                    container,
                    "valkey-server",
                    "--port",
                    str(port),
                    "--bind",
                    "0.0.0.0",
                    "--protected-mode",
                    "no",
                    "--cluster-enabled",
                    "yes",
                    "--cluster-config-file",
                    f"/tmp/vslab-nodes-{port}.conf",
                    "--cluster-announce-ip",
                    "127.0.0.1",
                    "--cluster-announce-port",
                    str(port),
                    "--cluster-announce-bus-port",
                    str(port + 10000),
                    "--appendonly",
                    "no",
                    "--daemonize",
                    "yes",
                    "--pidfile",
                    f"/tmp/vslab-{port}.pid",
                ],
                timeout=30,
            )
            _boundary_wait_ping(container, port)

        create_targets = " ".join(f"127.0.0.1:{port}" for port in ports)
        _boundary_docker(
            [
                "exec",
                container,
                "sh",
                "-c",
                f"printf 'yes\\n' | valkey-cli --cluster create {create_targets} --cluster-replicas 1",
            ],
            timeout=60,
        )

        provisional = [
            NodeEndpoint(
                logical_id=f"node-{index}",
                host="127.0.0.1",
                port=port,
                expected_role="primary",
                expected_shard=f"shard-{index}",
                placement_id=container,
            )
            for index, port in enumerate(ports)
        ]
        topology = _boundary_wait_topology(provisional)

        node_ids_by_port: dict[int, dict[str, object]] = {}
        normalized = topology["normalized_topology"]
        assert isinstance(normalized, dict)
        for shard_index, shard in enumerate(normalized["shards"]):
            for member in shard["nodes"]:
                node_ids_by_port[int(member["port"])] = {
                    "role": member["role"],
                    "shard_id": f"shard-{shard_index}",
                }
        assert set(node_ids_by_port) == set(ports)

        nodes: list[dict[str, object]] = []
        for index, port in enumerate(ports):
            pid = int(_boundary_docker(["exec", container, "cat", f"/tmp/vslab-{port}.pid"]))
            actual = node_ids_by_port[port]
            nodes.append(
                {
                    "logical_id": f"node-{index}",
                    "host": "127.0.0.1",
                    "client_port": port,
                    "role": actual["role"],
                    "shard_id": actual["shard_id"],
                    "nodehost_id": container,
                    "nodehost_container_id": container_id,
                    "nodehost_container_name": container,
                    "pid": pid,
                }
            )

        runners = docker_runtime._resource_runners_for_nodes(nodes)
        assert len(runners) == 1
        sampler = runners[0].sampler
        static = sampler.static()
        samples = [sampler.host_sample(), sampler.process_sample()]
        assert static["sampler_id"] == container
        assert samples[0]["kind"] == "host"
        assert samples[1]["kind"] == "process"
        assert len(samples[1]["processes"]) == 6
        assert all(row["status"] == "OK" for row in samples[1]["processes"])

        inventory = [NodeEndpoint.from_inventory(node) for node in nodes]
        consistent = _boundary_wait_topology(inventory)
        assert consistent["observer_count"] == 3
        assert FullClusterValidator(
            inventory,
            concurrency=32,
            observer_count=3,
            timeout=5.0,
        ).run()["status"] == "OK"
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )


def test_custom_valkey_image_preflight_verifies_labels_binaries_and_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_sha256 = "a" * 64
    cli_sha256 = "b" * 64
    labels = {
        "org.valkey-scale-lab.valkey.version": docker_runtime.CUSTOM_VALKEY_VERSION,
        "org.valkey-scale-lab.valkey.source.sha256": docker_runtime.CUSTOM_VALKEY_SOURCE_SHA256,
        "org.valkey-scale-lab.valkey.patch.sha256": docker_runtime.CUSTOM_VALKEY_PATCH_SHA256,
        docker_runtime.CUSTOM_VALKEY_SERVER_SHA256_LABEL: server_sha256,
        docker_runtime.CUSTOM_VALKEY_CLI_SHA256_LABEL: cli_sha256,
    }
    calls: list[list[str]] = []

    def fake_run_docker(
        args: list[str],
        timeout: int = 120,
        check: bool = True,
    ) -> docker_runtime.DockerResult:
        calls.append(args)
        if args[:2] == ["image", "inspect"]:
            return docker_runtime.DockerResult(json.dumps(labels), "", 0)
        return docker_runtime.DockerResult("cluster|myslots\n", "", 0)

    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)

    result = docker_runtime._verify_custom_valkey_image(
        docker_runtime.CUSTOM_VALKEY_IMAGE
    )

    assert result["status"] == "PASS"
    assert result["valkey_server_sha256"] == server_sha256
    assert calls[0][:3] == [
        "image",
        "inspect",
        docker_runtime.CUSTOM_VALKEY_IMAGE,
    ]
    assert calls[1][:4] == [
        "run",
        "--rm",
        "--entrypoint",
        "sh",
    ]


def test_custom_valkey_image_preflight_missing_image_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        lambda *_args, **_kwargs: docker_runtime.DockerResult("", "not found", 1),
    )

    with pytest.raises(
        DockerRuntimeError,
        match=r"\./project/scripts/build_valkey_image\.sh",
    ):
        docker_runtime._verify_custom_valkey_image(
            docker_runtime.CUSTOM_VALKEY_IMAGE
        )


def test_cluster_myslots_report_validates_full_coverage_and_replicas(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    server_sha256 = "c" * 64
    primary_zero = bytes([0xFF]) * 1024 + bytes(1024)
    primary_one = bytes(1024) + bytes([0xFF]) * 1024
    node_ids = [f"{index + 1:040x}" for index in range(4)]
    shard_ids = ["a" * 40, "b" * 40]
    nodes = [
        {
            "logical_id": "shard-0000-primary",
            "ordinal": 0,
            "client_port": 7000,
            "role": "primary",
            "shard_id": "shard-0000",
            "az_id": "az-a",
            "nodehost_container_name": "nodehost-0",
            "pid": 100,
        },
        {
            "logical_id": "shard-0001-primary",
            "ordinal": 1,
            "client_port": 7001,
            "role": "primary",
            "shard_id": "shard-0001",
            "az_id": "az-b",
            "nodehost_container_name": "nodehost-1",
            "pid": 101,
        },
        {
            "logical_id": "shard-0000-replica-00",
            "ordinal": 2,
            "client_port": 7002,
            "role": "replica",
            "shard_id": "shard-0000",
            "az_id": "az-b",
            "nodehost_container_name": "nodehost-0",
            "pid": 102,
        },
        {
            "logical_id": "shard-0001-replica-00",
            "ordinal": 3,
            "client_port": 7003,
            "role": "replica",
            "shard_id": "shard-0001",
            "az_id": "az-a",
            "nodehost_container_name": "nodehost-1",
            "pid": 103,
        },
    ]

    def response(
        node_id: str,
        shard_id: str,
        role: str,
        owner_id: str,
        bitmap: bytes,
    ) -> list[object]:
        return [
            b"node-id",
            node_id.encode(),
            b"shard-id",
            shard_id.encode(),
            b"role",
            role.encode(),
            b"slot-owner-id",
            owner_id.encode(),
            b"slot-count",
            8192,
            b"bitmap-encoding",
            b"lsb0",
            b"slot-bitmap",
            bitmap,
        ]

    responses = {
        7000: response(node_ids[0], shard_ids[0], "primary", node_ids[0], primary_zero),
        7001: response(node_ids[1], shard_ids[1], "primary", node_ids[1], primary_one),
        7002: response(node_ids[2], shard_ids[0], "replica", node_ids[0], primary_zero),
        7003: response(node_ids[3], shard_ids[1], "replica", node_ids[1], primary_one),
    }
    light_rows = []
    for node, raw in zip(nodes, responses.values()):
        values = dict(zip(raw[0::2], raw[1::2]))
        bitmap = bytes(values[b"slot-bitmap"])
        light_rows.append(
            {
                "logical_id": node["logical_id"],
                "cluster_info": {"cluster_state": "ok"},
                "role": {
                    "role": node["role"],
                    "replication_state": (
                        "not_applicable"
                        if node["role"] == "primary"
                        else "connected"
                    ),
                },
                "myslots": {
                    "node-id": bytes(values[b"node-id"]).decode(),
                    "shard-id": bytes(values[b"shard-id"]).decode(),
                    "role": bytes(values[b"role"]).decode(),
                    "slot-owner-id": bytes(values[b"slot-owner-id"]).decode(),
                    "slot-count": values[b"slot-count"],
                    "bitmap-encoding": "lsb0",
                    "slot-bitmap-bytes": 2048,
                    "slot-bitmap-sha256": docker_runtime.hashlib.sha256(bitmap).hexdigest(),
                    "slot-bitmap-base64": docker_runtime.base64.b64encode(bitmap).decode(),
                },
            }
        )

    class FakeValidator:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run(self) -> dict:
            return {
                "status": "OK",
                "light_validation": {
                    "status": "OK",
                    "nodes_observed": 4,
                    "primary_count": 2,
                    "replica_count": 2,
                    "nodes": light_rows,
                },
                "topology_validation": {
                    "status": "OK",
                    "observer_count": 3,
                },
            }

    monkeypatch.setattr(docker_runtime, "FullClusterValidator", FakeValidator)
    monkeypatch.setattr(
        docker_runtime,
        "_host_command_binary",
        lambda _host, port, *_args, **_kwargs: responses[port],
    )
    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        lambda *_args, **_kwargs: docker_runtime.DockerResult(
            f"{server_sha256}  /proc/100/exe\n",
            "",
            0,
        ),
    )
    path = tmp_path / "cluster_myslots_report.json"

    report = docker_runtime._write_cluster_myslots_report(
        path,
        capability_id="local_full_flow",
        scenario="local_full_flow",
        run_id="test",
        nodes=nodes,
        image_preflight={"valkey_server_sha256": server_sha256},
    )

    assert report["status"] == "PASS"
    assert report["nodes_observed"] == 4
    assert report["primary_count"] == 2
    assert report["coverage"]["all_slots_covered_exactly_once"] is True
    assert all(item["slot-bitmap-bytes"] == 2048 for item in report["nodes"])
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "PASS"


def test_cluster_lifecycle_node_specs_are_deterministic() -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/single_mac_6node.yaml"))
    nodes = docker_runtime._node_specs(config, "cluster_lifecycle", "cluster_lifecycle")
    assert [node["logical_id"] for node in nodes] == [
        "shard-0000-primary",
        "shard-0001-primary",
        "shard-0002-primary",
        "shard-0000-replica-00",
        "shard-0001-replica-00",
        "shard-0002-replica-00",
    ]
    assert [node["client_port"] for node in nodes] == [7000, 7001, 7002, 7003, 7004, 7005]
    assert len({node["container_name"] for node in nodes}) == 6
    assert "cluster-lifecycle-cluster-lifecycle" in nodes[0]["container_name"]
    assert {node["host_id"] for node in nodes} == {"local"}


def test_orchestration_node_specs_preserve_multi_host_placement() -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/single_mac_6node.yaml"))
    config["hosts"] = [
        {"host_id": "local-a", "ip": "127.0.0.1", "docker_endpoint": "local", "labels": ["worker"]},
        {"host_id": "local-b", "ip": "127.0.0.1", "docker_endpoint": "local", "labels": ["worker"]},
    ]
    nodes = docker_runtime._node_specs(config, "orchestration", "orchestration")
    assert [node["host_id"] for node in nodes] == ["local-a", "local-b", "local-a", "local-b", "local-a", "local-b"]


def test_setup_node_specs_use_global_cluster_node_timeout() -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/scale_50.yaml"))
    nodes = docker_runtime._node_specs(config, "scale_ladder", "scale_50")
    assert {node["effective_cluster_node_timeout_ms"] for node in nodes} == {30000}
    assert {node["cluster_node_timeout_source"] for node in nodes} == {"global"}


def test_setup_node_specs_preserve_replica_topology() -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/scale_50.yaml"))
    nodes = docker_runtime._node_specs(config, "scale_ladder", "scale_50")

    assert len(nodes) == 50
    assert len([node for node in nodes if node["role"] == "primary"]) == 25
    assert len([node for node in nodes if node["role"] == "replica"]) == 25
    assert nodes[0]["logical_id"] == "shard-0000-primary"
    assert nodes[25]["logical_id"] == "shard-0000-replica-00"


@pytest.mark.parametrize("node_count", [50, 100, 200])
def test_exact_runtime_scale_comes_only_from_profile(node_count: int) -> None:
    profile = docker_runtime._runtime_scale_profile(node_count)

    assert profile is not None
    assert profile.profile_id == f"exact-{node_count}"
    assert profile.requested_nodes == node_count
    assert not hasattr(profile, "scenario_id")
    assert not hasattr(profile, "capability_id")


def test_profile_rejects_unregistered_exact_size_without_changing_scenario() -> None:
    assert docker_runtime._runtime_scale_profile(199) is None
    assert docker_runtime._full_flow_profile(
        "local_full_flow",
        "local_full_flow",
        200,
    ).profile_id == "exact-200"


def test_management_matrix_200_node_specs_use_global_cluster_node_timeout() -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/scale_200.yaml"))
    nodes = docker_runtime._node_specs(config, "management_matrix", "management_matrix")

    assert len(nodes) == 200
    assert {node["effective_cluster_node_timeout_ms"] for node in nodes} == {30000}
    assert {node["cluster_node_timeout_source"] for node in nodes} == {"global"}


def test_process_nodehosts_use_global_density_for_100_and_200() -> None:
    config100 = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/scale_100.yaml"))
    nodes100 = docker_runtime._node_specs(config100, "scale_ladder", "scale_100", "density-100")
    nodehosts100 = docker_runtime._process_nodehosts(config100, nodes100, "scale_ladder", "scale_100", "density-100")
    assert len(nodehosts100) == 4
    assert max(nodehost["logical_node_count"] for nodehost in nodehosts100) == 25

    config200 = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/scale_200.yaml"))
    nodes200 = docker_runtime._node_specs(config200, "management_matrix", "management_matrix", "density-200")
    nodehosts200 = docker_runtime._process_nodehosts(config200, nodes200, "management_matrix", "management_matrix", "density-200")
    assert len(nodehosts200) == 8
    assert max(nodehost["logical_node_count"] for nodehost in nodehosts200) == 25


def test_process_nodehosts_preserve_single_az_fault_domains() -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/single_mac_6node.yaml"))
    nodes = docker_runtime._node_specs(config, "cluster_lifecycle", "cluster_lifecycle", "density-smoke")
    nodehosts = docker_runtime._process_nodehosts(config, nodes, "cluster_lifecycle", "cluster_lifecycle", "density-smoke")
    by_shard: dict[str, set[str]] = {}
    for node in nodes:
        by_shard.setdefault(node["shard_id"], set()).add(node["nodehost_id"])

    assert len(nodehosts) == 2
    assert all(len(nodehost_ids) == 2 for nodehost_ids in by_shard.values())


def test_management_matrix_200_cluster_plan_writer_allows_only_exact_profile_exception(tmp_path: Path) -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/scale_200.yaml"))
    out = tmp_path / "cluster_plan.json"

    docker_runtime._write_management_matrix_cluster_plan(
        out,
        config,
        "management_matrix",
        "management_matrix",
        "management_matrix_200-test-run",
    )

    plan = docker_runtime.json.loads(out.read_text(encoding="utf-8"))
    assert plan["capability_id"] == "management_matrix"
    assert plan["scenario_name"] == "management_matrix"
    assert plan["node_count"] == 200
    assert plan["constraints"]["default_node_cap"] == 100
    assert plan["constraints"]["opt_in_1000"] is False
    assert plan["constraints"]["exact_200_bounded_exception"] is True


def test_full_flow_50_cluster_plan_writer_uses_the_registered_scale_profile(tmp_path: Path) -> None:
    config = docker_runtime.normalize_config(
        docker_runtime.parse_config_file("templates/configs/scale_50.yaml")
    )
    out = tmp_path / "cluster_plan.json"

    docker_runtime._write_management_matrix_cluster_plan(
        out,
        config,
        "local_full_flow",
        "local_full_flow",
        "local-full-flow-50-test-run",
    )

    plan = docker_runtime.json.loads(out.read_text(encoding="utf-8"))
    assert plan["capability_id"] == "local_full_flow"
    assert plan["scenario_name"] == "local_full_flow"
    assert plan["node_count"] == 50


def test_observability_writer_uses_scalable_validator_not_cluster_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeValidator:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run(self) -> dict:
            return {
                "status": "OK",
                "complexity": {
                    "light_command_count": 12,
                    "cluster_shards_view_count": 2,
                    "cluster_nodes_command_count": 0,
                },
                "light_validation": {
                    "primary_count": 1,
                    "replica_count": 1,
                },
                "topology_validation": {"status": "OK"},
            }

    monkeypatch.setattr(docker_runtime, "FullClusterValidator", FakeValidator)
    monkeypatch.setattr(
        docker_runtime,
        "_node_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("CLUSTER NODES path must not be used")
        ),
    )

    docker_runtime.write_observability_artifacts(
        tmp_path,
        "observability",
        "observability",
        "run-observability",
        {},
        [
            {
                "logical_id": "node-a",
                "host": "127.0.0.1",
                "client_port": 7000,
                "role": "primary",
                "shard_id": "s0",
            },
            {
                "logical_id": "node-b",
                "host": "127.0.0.1",
                "client_port": 7001,
                "role": "replica",
                "shard_id": "s0",
            },
        ],
    )

    report = docker_runtime.json.loads(
        (tmp_path / "scalable_cluster_validation.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "PASS"
    assert report["normal_path_cluster_nodes_command_count"] == 0
    assert report["docker_exec_for_valkey_protocol"] is False


@pytest.mark.parametrize(
    "capability_id",
    [
        "failover_latency_curve",
        "management_matrix",
        "fault_matrix",
        "local_full_flow",
        "failover_timeline",
        "clean_gate_diagnostics",
    ],
)
def test_exact_200_runtime_semantic_exception_is_profile_and_scenario_bound(
    capability_id: str,
) -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/scale_200.yaml"))

    assert docker_runtime._runtime_semantic_errors(
        config,
        capability_id=capability_id,
        scenario=capability_id,
        profile_id="exact-200",
    ) == []
    assert any(
        error["code"] == "NODE_CAP_EXCEEDED"
        for error in docker_runtime._runtime_semantic_errors(
            config,
            capability_id=capability_id,
            scenario=f"{capability_id}_other",
            profile_id="exact-200",
        )
    )


def test_exact_2000_runtime_semantics_require_local_full_flow_opt_in() -> None:
    config = docker_runtime.normalize_config(
        docker_runtime.parse_config_file(
            "templates/configs/scale_2000_local_full_flow_optin.yaml"
        )
    )

    assert docker_runtime._runtime_semantic_errors(
        config,
        capability_id="local_full_flow",
        scenario="local_full_flow",
        profile_id="exact-2000",
        operator_opt_in=True,
        cost_acknowledged=True,
    ) == []
    assert any(
        error["code"] == "EXACT_2000_LOCAL_FULL_FLOW_OPT_IN_REQUIRED"
        for error in docker_runtime._runtime_semantic_errors(
            config,
            capability_id="local_full_flow",
            scenario="local_full_flow",
            profile_id="exact-2000",
        )
    )
    assert any(
        error["code"] == "EXACT_2000_LOCAL_FULL_FLOW_OPT_IN_REQUIRED"
        for error in docker_runtime._runtime_semantic_errors(
            config,
            capability_id="management_matrix",
            scenario="management_matrix",
            profile_id="exact-2000",
            operator_opt_in=True,
            cost_acknowledged=True,
        )
    )


def test_runtime_setup_timing_names_split_diagnostic_probe() -> None:
    assert "runtime_all_node_light_probe" in docker_runtime.SETUP_TIMING_NAMES
    assert "runtime_final_full_probe" in docker_runtime.SETUP_TIMING_NAMES
    assert "runtime_diagnostic_full_probe" in docker_runtime.SETUP_TIMING_NAMES
    timings: dict[str, dict] = {}
    started = docker_runtime.time.monotonic()
    docker_runtime._record_timing(timings, "runtime_all_node_light_probe", started, status="PASS")
    docker_runtime._record_timing(timings, "runtime_final_full_probe", started, status="PASS")
    docker_runtime._record_timing(timings, "runtime_diagnostic_full_probe", started, status="FAIL")

    entries = {entry["name"]: entry for entry in docker_runtime._timing_entries(timings, docker_runtime.SETUP_TIMING_NAMES)}
    assert entries["runtime_all_node_light_probe"]["status"] == "PASS"
    assert entries["runtime_final_full_probe"]["status"] == "PASS"
    assert entries["runtime_diagnostic_full_probe"]["status"] == "FAIL"


def test_cluster_create_strategy_defaults_to_valkey_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VSLAB_CLUSTER_CREATE_STRATEGY", raising=False)
    assert docker_runtime._cluster_create_strategy() == docker_runtime.CLUSTER_CREATE_STRATEGY_DEFAULT


def test_m2_measurement_hooks_are_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    timeline = SetupTimeline(clock=lambda: 10.0)
    monkeypatch.delenv(docker_runtime.M2_MEASUREMENT_ENV, raising=False)
    monkeypatch.setenv(docker_runtime.M2_RUN_ID_ENV, "m2-explicit-run")
    monkeypatch.setenv(docker_runtime.M2_BOOTSTRAP_RESOURCE_SECONDS_ENV, "120")

    docker_runtime._m2_setup_event(timeline, "last_process_ping")
    assert timeline.events == []
    assert docker_runtime._m2_bootstrap_resource_seconds() is None
    assert docker_runtime._run_id("failover_timeline", "failover_timeline") == "failover_timeline-failover_timeline-20260628"

    monkeypatch.setenv(docker_runtime.M2_MEASUREMENT_ENV, "1")
    docker_runtime._m2_setup_event(timeline, "last_process_ping", {"node_count": 50})
    assert timeline.events[0]["name"] == "last_process_ping"
    assert timeline.events[0]["details"] == {"node_count": 50}
    assert docker_runtime._m2_bootstrap_resource_seconds() == 120.0
    assert docker_runtime._run_id("failover_timeline", "failover_timeline") == "m2-explicit-run"

    monkeypatch.setenv(docker_runtime.M2_BOOTSTRAP_RESOURCE_SECONDS_ENV, "not-a-duration")
    with pytest.raises(DockerRuntimeError, match="must be numeric"):
        docker_runtime._m2_bootstrap_resource_seconds()


def test_cluster_create_strategy_accepts_manual_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSLAB_CLUSTER_CREATE_STRATEGY", docker_runtime.CLUSTER_CREATE_STRATEGY_MANUAL)
    assert docker_runtime._cluster_create_strategy() == docker_runtime.CLUSTER_CREATE_STRATEGY_MANUAL


def test_cluster_create_strategy_accepts_addslotsrange_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSLAB_CLUSTER_CREATE_STRATEGY", docker_runtime.CLUSTER_CREATE_STRATEGY_ADDSLOTSRANGE)
    assert docker_runtime._cluster_create_strategy() == docker_runtime.CLUSTER_CREATE_STRATEGY_ADDSLOTSRANGE
    assert (
        docker_runtime._process_cluster_startup_strategy([{} for _ in range(31)])
        == "all_processes_ready_then_tree_meet_addslotsrange_parallel_replicas_two_stage_probe"
    )


def test_cluster_create_strategy_accepts_preseed_pipeline_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSLAB_CLUSTER_CREATE_STRATEGY", docker_runtime.CLUSTER_CREATE_STRATEGY_PRESEED_EPOCH_PIPELINE_REPLICAS)
    assert docker_runtime._cluster_create_strategy() == docker_runtime.CLUSTER_CREATE_STRATEGY_PRESEED_EPOCH_PIPELINE_REPLICAS
    assert (
        docker_runtime._process_cluster_startup_strategy([{} for _ in range(31)])
        == "all_processes_ready_then_preseed_epoch_tree_meet_replica_local_pipeline_two_stage_probe"
    )


def test_cluster_create_strategy_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSLAB_CLUSTER_CREATE_STRATEGY", "nodes_conf_fast_bootstrap")
    with pytest.raises(DockerRuntimeError, match="unsupported cluster create strategy"):
        docker_runtime._cluster_create_strategy()


def test_cluster_create_parallelism_defaults_to_8(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VSLAB_CLUSTER_CREATE_PARALLELISM", raising=False)
    assert docker_runtime._cluster_create_parallelism() == 8
    assert docker_runtime._cluster_create_parallelism_source() == "default"


def test_cluster_create_parallelism_accepts_discovery_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("2", "4", "8", "16"):
        monkeypatch.setenv("VSLAB_CLUSTER_CREATE_PARALLELISM", value)
        assert docker_runtime._cluster_create_parallelism() == int(value)
        assert docker_runtime._cluster_create_parallelism_source() == "env:VSLAB_CLUSTER_CREATE_PARALLELISM"


def test_cluster_create_parallelism_rejects_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSLAB_CLUSTER_CREATE_PARALLELISM", "32")
    with pytest.raises(DockerRuntimeError, match="unsupported cluster create parallelism"):
        docker_runtime._cluster_create_parallelism()


def test_replica_replicate_parallelism_defaults_to_8(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VSLAB_REPLICA_REPLICATE_PARALLELISM", raising=False)
    assert docker_runtime._replica_replicate_parallelism() == 8


def test_replica_replicate_parallelism_accepts_supported_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("8", "16", "32"):
        monkeypatch.setenv("VSLAB_REPLICA_REPLICATE_PARALLELISM", value)
        assert docker_runtime._replica_replicate_parallelism() == int(value)


def test_replica_replicate_parallelism_rejects_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSLAB_REPLICA_REPLICATE_PARALLELISM", "64")
    with pytest.raises(DockerRuntimeError, match="unsupported replica replicate parallelism"):
        docker_runtime._replica_replicate_parallelism()


def test_process_nodehosts_group_logical_nodes_by_az() -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/scale_50.yaml"))
    nodes = docker_runtime._node_specs(config, "scale_ladder", "scale_50", "run")

    nodehosts = docker_runtime._process_nodehosts(config, nodes, "scale_ladder", "scale_50", "run")

    assert [nodehost["nodehost_id"] for nodehost in nodehosts] == [
        "nodehost-az-a-00",
        "nodehost-az-a-01",
        "nodehost-az-b-00",
        "nodehost-az-b-01",
    ]
    assert sum(nodehost["logical_node_count"] for nodehost in nodehosts) == 50
    assert max(nodehost["logical_node_count"] for nodehost in nodehosts) <= 25
    assert all(node["runtime_type"] == "docker_process" for node in nodes)
    assert all(node["nodehost_id"].startswith("nodehost-az-") for node in nodes)
    assert all(node["cluster_bus_port"] >= 17400 for node in nodes)


def _assert_process_bootstrap_uses_nodehost_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_path: str,
    capability_id: str,
    scenario: str,
    expected_nodes: int,
) -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file(config_path))
    run_id = f"{capability_id}-{scenario}-20260628"
    nodes = docker_runtime._node_specs(config, capability_id, scenario, run_id)
    nodehosts = docker_runtime._process_nodehosts(config, nodes, capability_id, scenario, run_id)
    for index, nodehost in enumerate(nodehosts):
        nodehost["container_id"] = f"cid-{index}"
        nodehost["container_ip"] = f"172.18.0.{index + 2}"
    nodehost_by_id = {nodehost["nodehost_id"]: nodehost for nodehost in nodehosts}
    calls: list[list[str]] = []

    def fake_parallel(items, worker, *, parallelism, timeout, label):
        work = list(items)
        return [worker(item) for item in work]

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True) -> docker_runtime.DockerResult:
        calls.append(args)
        if args[0] == "cp":
            assert "nodehost_bundles" in args[1]
            assert not args[1].endswith(".conf")
            return docker_runtime.DockerResult("", "", 0)
        if args[:1] == ["exec"]:
            assert args[2] == "sh"
            script = args[3]
            if script.endswith("/collect_pidfiles.sh"):
                nodehost = next(item for item in nodehosts if item["container_name"] == args[1])
                hosted = [node for node in nodes if node["nodehost_id"] == nodehost["nodehost_id"]]
                stdout = "\n".join(f"{node['logical_id']}\t{4000 + idx}" for idx, node in enumerate(hosted))
                return docker_runtime.DockerResult(stdout + "\n", "", 0)
            assert script.endswith("/install.sh") or script.endswith("/start_all.sh")
            return docker_runtime.DockerResult("", "", 0)
        raise AssertionError(f"unexpected docker command: {args}")

    monkeypatch.setattr(docker_runtime, "_bounded_parallel", fake_parallel)
    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)

    config_details = docker_runtime._prepare_process_nodehost_bundles(
        nodes=nodes,
        nodehosts=nodehosts,
        nodehost_by_id=nodehost_by_id,
        artifacts=tmp_path,
        run_id=run_id,
    )
    start_details = docker_runtime._start_process_nodes_batched(nodes=nodes, nodehosts=nodehosts)
    summary = docker_runtime._process_bootstrap_batching_details(
        nodes=nodes,
        nodehosts=nodehosts,
        config_prepare_details=config_details,
        process_start_details=start_details,
    )

    assert len(nodes) == expected_nodes
    assert len([call for call in calls if call[0] == "cp"]) == len(nodehosts)
    assert len([call for call in calls if call[:1] == ["exec"] and call[3].endswith("/install.sh")]) == len(nodehosts)
    assert len([call for call in calls if call[:1] == ["exec"] and call[3].endswith("/start_all.sh")]) == len(nodehosts)
    assert len([call for call in calls if call[:1] == ["exec"] and call[3].endswith("/collect_pidfiles.sh")]) == len(nodehosts)
    assert not any(call[:3] == ["exec", call[1], "valkey-server"] for call in calls)
    assert not any(call[:3] == ["exec", call[1], "cat"] for call in calls)
    assert summary["nodehost_bulk_install_used"] is True
    assert summary["nodehost_bulk_start_used"] is True
    assert summary["docker_exec_count_before_after"]["after"] < summary["docker_exec_count_before_after"]["before"]
    assert summary["docker_cp_count_before_after"]["after"] < summary["docker_cp_count_before_after"]["before"]
    assert all("pid" in node for node in nodes)


def test_process_bootstrap_uses_nodehost_bundle_for_scale_10(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_process_bootstrap_uses_nodehost_bundle(
        tmp_path,
        monkeypatch,
        "templates/configs/scale_10.yaml",
        "scale_ladder",
        "scale_10",
        10,
    )


def test_process_bootstrap_uses_nodehost_bundle_for_scale_30(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_process_bootstrap_uses_nodehost_bundle(
        tmp_path,
        monkeypatch,
        "templates/configs/scale_30.yaml",
        "scale_ladder",
        "scale_30",
        30,
    )


def test_process_bootstrap_records_setup_timeline_child_spans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/scale_10.yaml"))
    run_id = "scale_ladder-scale_10-20260628"
    nodes = docker_runtime._node_specs(config, "scale_ladder", "scale_10", run_id)
    nodehosts = docker_runtime._process_nodehosts(config, nodes, "scale_ladder", "scale_10", run_id)
    for index, nodehost in enumerate(nodehosts):
        nodehost["container_id"] = f"cid-{index}"
        nodehost["container_ip"] = f"172.18.0.{index + 2}"
    nodehost_by_id = {nodehost["nodehost_id"]: nodehost for nodehost in nodehosts}
    timeline = SetupTimeline(gap_threshold_seconds=60.0)

    def fake_parallel(items, worker, *, parallelism, timeout, label):
        return [worker(item) for item in list(items)]

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True) -> docker_runtime.DockerResult:
        if args[0] == "cp":
            return docker_runtime.DockerResult("", "", 0)
        if args[:1] == ["exec"]:
            if args[3].endswith("/collect_pidfiles.sh"):
                nodehost = next(item for item in nodehosts if item["container_name"] == args[1])
                hosted = [node for node in nodes if node["nodehost_id"] == nodehost["nodehost_id"]]
                stdout = "\n".join(f"{node['logical_id']}\t{5000 + idx}" for idx, node in enumerate(hosted))
                return docker_runtime.DockerResult(stdout + "\n", "", 0)
            return docker_runtime.DockerResult("", "", 0)
        raise AssertionError(f"unexpected docker command: {args}")

    monkeypatch.setattr(docker_runtime, "_bounded_parallel", fake_parallel)
    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)

    docker_runtime._prepare_process_nodehost_bundles(
        nodes=nodes,
        nodehosts=nodehosts,
        nodehost_by_id=nodehost_by_id,
        artifacts=tmp_path,
        run_id=run_id,
        setup_timeline=timeline,
    )
    docker_runtime._start_process_nodes_batched(nodes=nodes, nodehosts=nodehosts, setup_timeline=timeline)

    names = [segment["name"] for segment in timeline.segments]
    assert "node_config_local_generate" in names
    assert "nodehost_bundle_write" in names
    assert "docker_cp_bundle" in names
    assert "nodehost_bundle_install" in names
    assert "nodehost_start_all" in names
    assert "pidfile_collect" in names


@pytest.mark.parametrize(
    ("capability_id", "scenario", "expected_scale_writes"),
    [
        ("cluster_timeout", "cluster_timeout", 0),
        ("scale_ladder", "scale_ladder", 1),
    ],
)
def test_process_scenario_writes_scale_artifacts_only_for_scale_ladder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability_id: str,
    scenario: str,
    expected_scale_writes: int,
) -> None:
    nodes = [{"logical_id": "node-1", "host": "127.0.0.1", "client_port": 7400}]
    nodehosts = [{"nodehost_id": "host-1"}]
    scale_writes: list[tuple[str, str]] = []
    resource_clocks: list[object] = []
    events: list[str] = []
    allow_resource_finish = threading.Event()

    def fake_resource_observation(
        path: Path,
        *,
        monotonic: object,
        first_complete_sample_event: object,
        **_kwargs: object,
    ) -> dict[str, str]:
        resource_clocks.append(monotonic)
        events.append("resource-first-sample")
        first_complete_sample_event.set()  # type: ignore[attr-defined]
        assert allow_resource_finish.wait(timeout=1.0)
        events.append("resource-end")
        path.write_text('{"status":"PASS"}\n', encoding="utf-8")
        return {"status": "PASS"}

    def fake_protocol_boundary(
        boundary_nodes: list[dict[str, object]],
        label: str,
    ) -> dict[str, object]:
        events.append(f"boundary-{label}")
        assert boundary_nodes == nodes
        return {
            "status": "PASS",
            "label": label,
            "expected_live_nodes": ["node-1"],
            "node_metrics": [
                {
                    "logical_id": "node-1",
                    "cluster_stats_bytes_sent": 10 if label == "start" else 20,
                    "cluster_stats_bytes_received": 30 if label == "start" else 50,
                    "total_cluster_links_buffer_limit_exceeded": 1
                    if label == "start"
                    else 3,
                }
            ],
            "errors": [],
        }

    def fake_configure_process_cluster(*_args: object, **_kwargs: object) -> tuple[list[object], list[object]]:
        events.append("configure")
        allow_resource_finish.set()
        return [], []

    monkeypatch.setattr(docker_runtime, "cleanup_by_label", lambda **_kwargs: None)
    monkeypatch.setattr(docker_runtime, "run_docker", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(docker_runtime, "_process_nodehosts", lambda *_args: nodehosts)
    monkeypatch.setattr(docker_runtime, "_write_nodehost_density_plan_artifact", lambda *_args: None)
    monkeypatch.setattr(docker_runtime, "_start_nodehost", lambda *_args: "container-1")
    monkeypatch.setattr(docker_runtime, "_container_ip", lambda *_args: "127.0.0.1")
    monkeypatch.setattr(
        docker_runtime,
        "_bounded_parallel",
        lambda items, worker, **_kwargs: [worker(item) for item in items],
    )
    monkeypatch.setattr(
        docker_runtime,
        "_prepare_process_nodehost_bundles",
        lambda **_kwargs: {"prepared": True},
    )
    monkeypatch.setattr(docker_runtime, "_write_generated_valkey_configs_manifest", lambda *_args: None)
    monkeypatch.setattr(
        docker_runtime,
        "_start_process_nodes_batched",
        lambda **_kwargs: {"started": True},
    )
    monkeypatch.setattr(
        docker_runtime,
        "_process_bootstrap_batching_details",
        lambda **_kwargs: {"status": "PASS"},
    )
    monkeypatch.setattr(docker_runtime, "_wait_process_nodes_ready", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(docker_runtime, "_process_runtime_state", lambda *_args, **_kwargs: {"runtime": {}})
    monkeypatch.setattr(docker_runtime, "_write_effective_server_profile_artifact", lambda *_args: None)
    monkeypatch.setattr(docker_runtime, "_write_effective_cluster_timeout_artifact", lambda *_args: None)
    monkeypatch.setattr(docker_runtime, "_write_state", lambda *_args: None)
    monkeypatch.setattr(docker_runtime, "_resource_runners_for_nodes", lambda *_args, **_kwargs: ["runner"])
    monkeypatch.setattr(docker_runtime, "write_resource_observation", fake_resource_observation)
    monkeypatch.setattr(docker_runtime, "_m2_bootstrap_protocol_boundary", fake_protocol_boundary)
    monkeypatch.setattr(
        docker_runtime,
        "_m2_bootstrap_resource_seconds",
        lambda: 1.0 if scenario == "cluster_timeout" else None,
    )
    monkeypatch.setattr(docker_runtime, "_configure_process_cluster", fake_configure_process_cluster)
    monkeypatch.setattr(docker_runtime, "_write_runtime_timing_breakdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        docker_runtime,
        "write_scale_ladder_artifacts",
        lambda _artifacts, selected_capability, selected_scenario, *_args: scale_writes.append(
            (selected_capability, selected_scenario)
        ),
    )

    docker_runtime._create_process_scenario(
        capability_id=capability_id,
        scenario=scenario,
        run_id="real-path-test",
        config={"runtime": {"valkey_image": "valkey:test"}},
        artifacts=tmp_path,
        state_out=tmp_path / "state.json",
        nodes=nodes,
        profile_id="exact-50",
    )

    assert scale_writes == [("scale_ladder", "scale_ladder")] * expected_scale_writes
    assert resource_clocks == ([shared_monotonic] if scenario == "cluster_timeout" else [])
    if scenario == "cluster_timeout":
        assert events == [
            "resource-first-sample",
            "boundary-start",
            "configure",
            "resource-end",
            "boundary-end",
        ]
        resource_report = json.loads((tmp_path / "resource_observation.json").read_text())
        assert resource_report["m2_bootstrap_protocol_boundaries"]["start"]["label"] == "start"
        assert resource_report["m2_bootstrap_protocol_boundaries"]["end"]["label"] == "end"
    else:
        assert events == ["configure"]


def test_m2_bootstrap_protocol_boundary_uses_direct_cluster_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, tuple[str, ...]]] = []

    class FakeRespConnection:
        def __init__(self, endpoint: object, *, timeout: float) -> None:
            self.endpoint = endpoint

        def __enter__(self) -> "FakeRespConnection":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, *command: str) -> str:
            port = int(self.endpoint.port)  # type: ignore[attr-defined]
            calls.append((port, command))
            return (
                "cluster_stats_bytes_sent:100\n"
                "cluster_stats_bytes_received:200\n"
                "total_cluster_links_buffer_limit_exceeded:3\n"
            )

    def fail_node_command(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("bootstrap protocol boundary must use direct RESP")

    monkeypatch.setattr(docker_runtime, "RespConnection", FakeRespConnection)
    monkeypatch.setattr(docker_runtime, "_node_command", fail_node_command)

    boundary = docker_runtime._m2_bootstrap_protocol_boundary(
        [{"logical_id": "node-1", "host": "127.0.0.1", "client_port": 7400}],
        "start",
    )

    assert calls == [(7400, ("CLUSTER", "INFO"))]
    assert boundary["node_metrics"] == [
        {
            "logical_id": "node-1",
            "cluster_stats_bytes_sent": 100,
            "cluster_stats_bytes_received": 200,
            "total_cluster_links_buffer_limit_exceeded": 3,
        }
    ]


def test_process_runtime_state_records_required_node_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSLAB_CLUSTER_CREATE_STRATEGY", docker_runtime.CLUSTER_CREATE_STRATEGY_ADDSLOTSRANGE)
    monkeypatch.setenv("VSLAB_CLUSTER_CREATE_PARALLELISM", "16")
    nodes = [
        {
            "logical_id": "shard-0000-primary",
            "nodehost_id": "nodehost-az-a",
            "host_id": "local",
            "client_port": 7400,
            "cluster_bus_port": 17400,
            "az_id": "az-a",
            "role": "primary",
            "shard_id": "shard-0000",
            "pid": 123,
            "pid_file": "/tmp/vslab/node/valkey.pid",
            "data_dir": "/tmp/vslab/node",
            "log_file": "/tmp/vslab/node/valkey.log",
            "config_file": "/tmp/vslab/node/valkey.conf",
            "config_artifact_file": "artifacts/node.conf",
            "nodehost_container_id": "cid",
            "nodehost_container_name": "nodehost",
            "nodehost_container_ip": "172.18.0.2",
        }
    ]
    nodehosts = [
        {
            "nodehost_id": "nodehost-az-a",
            "az_id": "az-a",
            "host_id": "local",
            "container_id": "cid",
            "container_name": "nodehost",
            "container_ip": "172.18.0.2",
            "ports": [7400, 17400],
            "logical_node_count": 1,
        }
    ]

    state = docker_runtime._process_runtime_state(
        "scale_ladder",
        "scale_50",
        "run",
        "network",
        {"hosts": [{"host_id": "local"}]},
        nodehosts,
        nodes,
        [{"label": "final"}],
    )

    assert state["runtime"]["type"] == "docker_process"
    assert state["scenario_id"] == "scale_50"
    assert state["backend_id"] == "docker_process"
    assert state["requested_nodes"] == 1
    assert state["observed_nodes"] == 1
    assert state["runtime"]["cluster_startup_strategy"] == "all_processes_ready_then_tree_fanout_meet_parallel_slots_parallel_replicas_two_stage_probe"
    assert state["runtime"]["cluster_meet_fanout"] == 4
    assert state["runtime"]["cluster_startup_parallelism"] == 8
    assert state["runtime"]["cluster_create_strategy"] == docker_runtime.CLUSTER_CREATE_STRATEGY_ADDSLOTSRANGE
    assert state["runtime"]["cluster_create_parallelism"] == 16
    assert state["runtime"]["cluster_create_parallelism_source"] == "env:VSLAB_CLUSTER_CREATE_PARALLELISM"
    recorded = state["nodes"][0]
    for key in ["logical_id", "nodehost_id", "pid", "pid_file", "client_port", "cluster_bus_port", "role", "shard_id", "data_dir", "log_file", "config_file"]:
        assert key in recorded
    assert state["cluster_snapshots"] == [{"label": "final"}]


def test_process_runtime_state_records_large_cluster_create_strategy() -> None:
    nodes = [
        {
            "logical_id": f"shard-{idx:04d}-primary",
            "nodehost_id": "nodehost-az-a",
            "host_id": "local",
            "client_port": 7400 + idx,
            "cluster_bus_port": 17400 + idx,
            "az_id": "az-a",
            "role": "primary",
            "shard_id": f"shard-{idx:04d}",
            "pid": 1000 + idx,
            "pid_file": "/tmp/vslab/node/valkey.pid",
            "data_dir": "/tmp/vslab/node",
            "log_file": "/tmp/vslab/node/valkey.log",
            "config_file": "/tmp/vslab/node/valkey.conf",
            "config_artifact_file": "artifacts/node.conf",
            "nodehost_container_id": "cid",
            "nodehost_container_name": "nodehost",
            "nodehost_container_ip": "172.18.0.2",
        }
        for idx in range(31)
    ]
    state = docker_runtime._process_runtime_state(
        "scale_ladder",
        "scale_50",
        "run",
        "network",
        {"hosts": [{"host_id": "local"}]},
        [
            {
                "nodehost_id": "nodehost-az-a",
                "az_id": "az-a",
                "host_id": "local",
                "container_id": "cid",
                "container_name": "nodehost",
                "container_ip": "172.18.0.2",
                "ports": [],
                "logical_node_count": 31,
            }
        ],
        nodes,
        [],
    )

    assert (
        state["runtime"]["cluster_startup_strategy"]
        == "all_processes_ready_then_valkey_cli_cluster_create_replicas_two_stage_probe"
    )
    assert "cluster_create_parallelism" not in state["runtime"]
    assert "cluster_create_parallelism_source" not in state["runtime"]


def test_process_runtime_state_records_preseed_strategy_parallelism(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSLAB_CLUSTER_CREATE_STRATEGY", docker_runtime.CLUSTER_CREATE_STRATEGY_PRESEED_EPOCH_PIPELINE_REPLICAS)
    monkeypatch.setenv("VSLAB_CLUSTER_CREATE_PARALLELISM", "8")
    nodes = [
        {
            "logical_id": f"shard-{idx:04d}-primary",
            "nodehost_id": "nodehost-az-a",
            "host_id": "local",
            "client_port": 7400 + idx,
            "cluster_bus_port": 17400 + idx,
            "az_id": "az-a",
            "role": "primary",
            "shard_id": f"shard-{idx:04d}",
            "pid": 1000 + idx,
            "pid_file": "/tmp/vslab/node/valkey.pid",
            "data_dir": "/tmp/vslab/node",
            "log_file": "/tmp/vslab/node/valkey.log",
            "config_file": "/tmp/vslab/node/valkey.conf",
            "config_artifact_file": "artifacts/node.conf",
            "nodehost_container_id": "cid",
            "nodehost_container_name": "nodehost",
            "nodehost_container_ip": "172.18.0.2",
        }
        for idx in range(31)
    ]

    state = docker_runtime._process_runtime_state(
        "scale_ladder",
        "scale_50",
        "run",
        "network",
        {"hosts": [{"host_id": "local"}]},
        [
            {
                "nodehost_id": "nodehost-az-a",
                "az_id": "az-a",
                "host_id": "local",
                "container_id": "cid",
                "container_name": "nodehost",
                "container_ip": "172.18.0.2",
                "ports": [],
                "logical_node_count": 31,
            }
        ],
        nodes,
        [],
    )

    assert state["runtime"]["cluster_create_strategy"] == docker_runtime.CLUSTER_CREATE_STRATEGY_PRESEED_EPOCH_PIPELINE_REPLICAS
    assert state["runtime"]["cluster_create_parallelism"] == 8
    assert state["runtime"]["replica_replicate_parallelism"] == 8
    assert state["runtime"]["cluster_startup_strategy"] == "all_processes_ready_then_preseed_epoch_tree_meet_replica_local_pipeline_two_stage_probe"


def test_slot_ranges_cover_all_slots_for_scale_rungs() -> None:
    ranges = docker_runtime._slot_ranges(15)
    assert ranges == docker_runtime._sequential_slot_ranges(15)
    assert len(ranges) == 15
    assert sum((end - start + 1) for start, end in ranges) == 16384
    assert ranges[0][0] == 0
    assert ranges[-1][1] == 16383
    assert all(ranges[index][1] + 1 == ranges[index + 1][0] for index in range(len(ranges) - 1))


def test_primary_create_preserves_process_address_order() -> None:
    primaries = [{"logical_id": f"p{idx}"} for idx in range(25)]
    assert [node["logical_id"] for node in primaries] == [f"p{idx}" for idx in range(25)]


def test_natural_probe_key_for_primary_hits_owned_myslots_bitmap(monkeypatch: pytest.MonkeyPatch) -> None:
    bitmap = bytearray(2048)
    slot = 8014
    bitmap[slot >> 3] |= 1 << (slot & 7)
    monkeypatch.setattr(
        docker_runtime,
        "_host_command_binary",
        lambda *args, **kwargs: {
            "node-id": "id-p0",
            "shard-id": "shard-0",
            "role": "primary",
            "slot-owner-id": "id-p0",
            "slot-count": 1,
            "bitmap-encoding": "lsb0",
            "slot-bitmap": bytes(bitmap),
        },
    )

    observed_slot, key = docker_runtime._natural_probe_key_for_primary(
        {"logical_id": "p0", "host": "127.0.0.1", "client_port": 7400},
        prefix="probe",
    )

    assert observed_slot == slot
    assert docker_runtime.sentinel_key_slot(key) == slot


def test_wait_process_predicate_success_does_not_run_all_node_final_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = [{"logical_id": f"n{idx}", "az_id": "az-a"} for idx in range(5)]
    sample_counts: list[int] = []

    def snapshots(probe_nodes, *, timeout):
        sample_counts.append(len(probe_nodes))
        return [{"probe_status": "PASS", "known_nodes": 5}]

    monkeypatch.setattr(docker_runtime, "_process_node_snapshots_parallel", snapshots)

    docker_runtime._wait_process_predicate(nodes, 1.0, "known", lambda snap: snap["known_nodes"] == 5)

    assert sample_counts == [1]


def test_wait_process_predicate_timeout_runs_one_all_node_diagnostic(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = [{"logical_id": f"n{idx}", "az_id": "az-a"} for idx in range(4)]
    sample_counts: list[int] = []

    def snapshots(probe_nodes, *, timeout):
        sample_counts.append(len(probe_nodes))
        return [{"probe_status": "PASS", "known_nodes": 1}]

    monkeypatch.setattr(docker_runtime, "_process_node_snapshots_parallel", snapshots)

    with pytest.raises(DockerRuntimeError, match="known"):
        docker_runtime._wait_process_predicate(nodes, 0.0, "known", lambda snap: snap["known_nodes"] == 4)

    assert sample_counts == [4]


def test_wait_process_snapshot_clean_uses_light_probe_then_bounded_topology_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = [
        {"logical_id": "p0", "host": "127.0.0.1", "client_port": 7400, "role": "primary", "shard_id": "s0"},
        {"logical_id": "r0", "host": "127.0.0.1", "client_port": 7401, "role": "replica", "shard_id": "s0"},
    ]
    calls: list[str] = []

    class FakeLightProbe:
        def __init__(self, inventory, *, concurrency, timeout):
            calls.append(f"light:{len(inventory)}:{concurrency}")

        def run(self):
            return {"status": "OK", "nodes_observed": 2, "primary_count": 1, "replica_count": 1}

    monkeypatch.setattr(docker_runtime, "LightClusterProbe", FakeLightProbe)
    monkeypatch.setattr(
        docker_runtime,
        "_process_node_snapshots_parallel",
        lambda probe_nodes, **kwargs: [{
            "probe_status": "PASS",
            "cluster_state": "ok",
            "known_nodes": 2,
            "primary_count": 1,
            "replica_count": 1,
            "handshake_count": 0,
            "fail_count": 0,
            "pfail_count": 0,
            "slots_assigned": 16384,
            "slots_ok": 16384,
            "slots_fail": 0,
        }],
    )

    docker_runtime._wait_process_snapshot_clean(
        nodes,
        expected_nodes=2,
        expected_primaries=1,
        expected_replicas=1,
        timeout=1.0,
    )

    assert calls == ["light:2:64"]


def test_scale_timeout_grows_with_node_count() -> None:
    assert docker_runtime._scale_timeout([{}] * 6, floor=90.0, per_node=5.0) == 90.0
    assert docker_runtime._scale_timeout([{}] * 100, floor=90.0, per_node=5.0) == 500.0


def test_replicate_with_retry_succeeds_after_transient_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True) -> docker_runtime.DockerResult:
        calls["count"] += 1
        if calls["count"] == 1:
            return docker_runtime.DockerResult("", "not known yet", 1)
        return docker_runtime.DockerResult("OK", "", 0)

    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    monkeypatch.setattr(docker_runtime.time, "sleep", lambda _: None)
    docker_runtime._replicate_with_retry("container", "master-id", timeout=1)
    assert calls["count"] == 2


def test_mesh_meet_connects_each_distinct_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True) -> docker_runtime.DockerResult:
        calls.append(args)
        return docker_runtime.DockerResult("OK", "", 0)

    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    docker_runtime._mesh_meet(
        [
            {"logical_id": "a", "container_name": "ca", "container_ip": "10.0.0.1"},
            {"logical_id": "b", "container_name": "cb", "container_ip": "10.0.0.2"},
            {"logical_id": "c", "container_name": "cc", "container_ip": "10.0.0.3"},
        ]
    )

    assert len(calls) == 6
    assert all(call[2:6] == ["valkey-cli", "-p", "6379", "CLUSTER"] for call in calls)


def test_runtime_state_contains_cleanup_and_probe_fields() -> None:
    config = {"hosts": [{"host_id": "local"}]}
    state = docker_runtime._runtime_state(
        "scale_ladder",
        "scale_50",
        "run",
        "network",
        config,
        [
            {
                "logical_id": "shard-0000-primary",
                "host_id": "local",
                "client_port": 7000,
                "az_id": "az-a",
                "role": "primary",
                "container_id": "cid",
                "container_name": "container",
                "container_ip": "172.18.0.2",
                "pid": 123,
                "shard_id": "shard-0000",
            }
        ],
    )

    assert state["runtime"]["sandbox_network"] is True
    assert state["runtime"]["run_id"] == "run"
    assert state["nodes"][0]["host"] == "127.0.0.1"
    assert state["nodes"][0]["client_port"] == 7000
    assert state["nodes"][0]["container_id"] == "cid"


def test_any_node_wait_helpers_accept_one_observable_ok_node(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = {
        "bad": "cluster_state:fail\ncluster_known_nodes:1\ncluster_slots_assigned:0\n",
        "good": "cluster_state:ok\ncluster_known_nodes:50\ncluster_slots_assigned:16384\n",
    }

    def fake_cli(container: str, *args, timeout: int = 60, check: bool = True) -> str:
        return responses[container]

    monkeypatch.setattr(docker_runtime, "run_container_cli", fake_cli)
    nodes = [{"container_name": "bad"}, {"container_name": "good"}]

    docker_runtime._wait_cluster_known_any(nodes, expected=50, timeout=1)
    docker_runtime._wait_cluster_slots_assigned_any(nodes, timeout=1)
    docker_runtime._wait_cluster_ok_any(nodes, timeout=1)


def test_incremental_meet_waits_for_each_new_node(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[int] = []
    meets: list[str] = []

    def fake_meet_pair(first: dict, node: dict) -> None:
        meets.append(node["logical_id"])

    def fake_wait(node: dict, expected: int, timeout: float) -> None:
        waits.append(expected)

    monkeypatch.setattr(docker_runtime, "_meet_pair", fake_meet_pair)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_integrated_at_least", fake_wait)

    first = {"logical_id": "shard-0000-primary"}
    docker_runtime._incremental_meet(
        first,
        [
            first,
            {"logical_id": "shard-0001-primary"},
            {"logical_id": "shard-0002-primary"},
        ],
        timeout=60,
    )

    assert meets == ["shard-0001-primary", "shard-0002-primary"]
    assert waits == [2, 3, 3]


def test_bulk_process_meet_sends_seed_meets_without_per_node_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_cli(seed: dict, *args, timeout: int = 60, check: bool = True) -> str:
        calls.append((seed["logical_id"], " ".join(str(arg) for arg in args)))
        return "OK"

    monkeypatch.setattr(docker_runtime, "run_node_cli", fake_cli)

    docker_runtime._bulk_meet_process_nodes(
        {"logical_id": "seed"},
        [
            {"logical_id": "p1", "nodehost_container_ip": "172.18.0.3", "client_port": 7401},
            {"logical_id": "p2", "nodehost_container_ip": "172.18.0.4", "client_port": 7402},
        ],
        timeout=30.0,
    )

    assert calls == [
        ("seed", "CLUSTER MEET 172.18.0.3 7401"),
        ("seed", "CLUSTER MEET 172.18.0.4 7402"),
    ]


def test_tree_fanout_levels_spread_meet_sources() -> None:
    nodes = [{"logical_id": f"p{idx}"} for idx in range(10)]

    levels = docker_runtime._tree_fanout_levels(nodes[0], nodes[1:], fanout=4)

    assert [[(src["logical_id"], dst["logical_id"]) for src, dst in level] for level in levels] == [
        [("p0", "p1"), ("p0", "p2"), ("p0", "p3"), ("p0", "p4")],
        [("p1", "p5"), ("p1", "p6"), ("p1", "p7"), ("p1", "p8"), ("p2", "p9")],
    ]


def test_process_wait_predicate_uses_representatives_without_success_full_check(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    nodes = [
        {"logical_id": "p0", "role": "primary", "az_id": "az-a"},
        {"logical_id": "p1", "role": "primary", "az_id": "az-b"},
        {"logical_id": "r0", "role": "replica", "az_id": "az-b"},
        {"logical_id": "r1", "role": "replica", "az_id": "az-a"},
    ]

    def fake_snapshots(sampled: list[dict], *, timeout: float = 60.0) -> list[dict]:
        calls.append([node["logical_id"] for node in sampled])
        return [
            {
                "logical_id": node["logical_id"],
                "probe_status": "PASS",
                "known_nodes": 4,
            }
            for node in sampled
        ]

    monkeypatch.setattr(docker_runtime, "_process_node_snapshots_parallel", fake_snapshots)

    docker_runtime._wait_process_known(nodes, expected=4, timeout=1)

    assert calls == [["p0", "p1"]]


def test_process_wait_predicate_above_200_avoids_all_node_cluster_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    nodes = [
        {
            "logical_id": f"node-{index:04d}",
            "role": "primary" if index % 2 == 0 else "replica",
            "az_id": f"az-{index % 3}",
        }
        for index in range(201)
    ]

    def fake_snapshots(sampled: list[dict], *, timeout: float = 60.0) -> list[dict]:
        calls.append([node["logical_id"] for node in sampled])
        return [
            {
                "logical_id": node["logical_id"],
                "probe_status": "PASS",
                "known_nodes": len(nodes),
            }
            for node in sampled
        ]

    monkeypatch.setattr(docker_runtime, "_process_node_snapshots_parallel", fake_snapshots)

    docker_runtime._wait_process_known(nodes, expected=len(nodes), timeout=1)

    assert len(calls) == 1
    assert all(len(call) < len(nodes) for call in calls)




def test_large_process_cluster_uses_cluster_create(monkeypatch: pytest.MonkeyPatch) -> None:
    create_calls: list[tuple[list[str], list[str]]] = []
    waits: list[str] = []

    nodes = [
        {
            "logical_id": f"shard-{idx:04d}-primary",
            "role": "primary",
            "shard_id": f"shard-{idx:04d}",
            "az_id": "az-a" if idx % 2 == 0 else "az-b",
        }
        for idx in range(20)
    ]
    nodes.extend(
        {
            "logical_id": f"shard-{idx:04d}-replica-00",
            "role": "replica",
            "shard_id": f"shard-{idx:04d}",
            "az_id": "az-b" if idx % 2 == 0 else "az-a",
        }
        for idx in range(20)
    )

    def fake_create(primaries: list[dict], replicas: list[dict], timeout: float) -> str:
        create_calls.append(
            (
                [node["logical_id"] for node in primaries],
                [node["logical_id"] for node in replicas],
            )
        )
        return "cluster create OK"

    def fake_summary(label: str, sampled: list[dict], **kwargs) -> dict:
        return {
            "label": label,
            "node_count": kwargs.get("total_node_count", len(sampled)),
            "known_nodes": len(nodes),
            "primary_count": 20,
            "replica_count": 20,
            "slots_assigned": 16384,
            "slots_ok": 16384,
            "slots_fail": 0,
        }

    monkeypatch.setattr(docker_runtime, "_create_large_cluster", fake_create)
    monkeypatch.setattr(docker_runtime, "_wait_process_known", lambda *args, **kwargs: waits.append("known"))
    monkeypatch.setattr(docker_runtime, "_wait_process_slots_assigned", lambda *args, **kwargs: waits.append("slots"))
    monkeypatch.setattr(docker_runtime, "_wait_process_cluster_ok", lambda *args, **kwargs: waits.append("ok"))
    monkeypatch.setattr(docker_runtime, "_wait_process_role_counts", lambda *args, **kwargs: waits.append("roles"))
    monkeypatch.setattr(docker_runtime, "_wait_process_snapshot_clean", lambda *args, **kwargs: waits.append("clean"))
    monkeypatch.setattr(docker_runtime, "_process_cluster_summary", fake_summary)

    operations, snapshots = docker_runtime._configure_process_cluster(nodes)

    assert len(create_calls) == 1
    assert len(create_calls[0][0]) == 20
    assert len(create_calls[0][1]) == 20
    assert [op["operation"] for op in operations] == ["cluster_create", "final_cluster_check"]
    assert [snapshot["label"] for snapshot in snapshots] == ["after_cluster_create", "final"]
    assert "slots" in waits


def test_large_cluster_uses_replicated_cluster_create(monkeypatch: pytest.MonkeyPatch) -> None:
    create_calls: list[tuple[list[str], list[str]]] = []

    def fake_cli(container: str, *args, timeout: int = 60, check: bool = True) -> str:
        if args == ("PING",):
            return "PONG"
        if args[:2] == ("CLUSTER", "MYID"):
            return f"id-{container}"
        if args[:2] == ("CLUSTER", "INFO"):
            return "cluster_state:ok\ncluster_known_nodes:50\ncluster_slots_assigned:16384\n"
        return "OK"

    def fake_create(primaries: list[dict], replicas: list[dict], timeout: float) -> str:
        create_calls.append(
            (
                [node["logical_id"] for node in primaries],
                [node["logical_id"] for node in replicas],
            )
        )
        return "OK"

    nodes = [
        {
            "logical_id": f"shard-{idx:04d}-primary",
            "container_name": f"p{idx}",
            "container_ip": f"172.18.0.{idx + 2}",
            "role": "primary",
            "shard_id": f"shard-{idx:04d}",
        }
        for idx in range(25)
    ]
    nodes.extend(
        {
            "logical_id": f"shard-{idx:04d}-replica-00",
            "container_name": f"r{idx}",
            "container_ip": f"172.18.1.{idx + 2}",
            "role": "replica",
            "shard_id": f"shard-{idx:04d}",
        }
        for idx in range(25)
    )
    monkeypatch.setattr(docker_runtime, "_create_large_cluster", fake_create)
    monkeypatch.setattr(docker_runtime, "run_container_cli", fake_cli)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_known", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_slots_assigned", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_ok", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_role_counts", lambda *args, **kwargs: None)

    operations = docker_runtime._configure_large_cluster(nodes)

    assert len(create_calls) == 1
    assert len(create_calls[0][0]) == 25
    assert len(create_calls[0][1]) == 25
    assert [op["operation"] for op in operations] == ["cluster_create"]


def test_management_wait_clean_cluster_uses_light_health_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nodes = [
        {
            "logical_id": "shard-0000-primary",
            "role": "primary",
            "client_port": 7400,
            "shard_id": "shard-0000",
        },
        {
            "logical_id": "shard-0001-replica-00",
            "role": "replica",
            "client_port": 7401,
            "shard_id": "shard-0001",
        },
    ]
    health_calls: list[int] = []
    topology_calls: list[tuple[int, int]] = []

    def light_health(probed: list[dict]) -> dict[str, object]:
        health_calls.append(len(probed))
        return {
            "cluster_state": "ok",
            "known_nodes": len(probed),
            "primary_count": 1,
            "replica_count": 1,
            "slots_assigned": 16384,
            "slots_ok": 16384,
            "slots_fail": 0,
            "snapshots": [],
        }

    class FakeTopologyObserver:
        def __init__(self, endpoints, *, observer_count: int, timeout: float):
            topology_calls.append((len(endpoints), observer_count))

        def run(self, *, expected_node_count: int) -> dict[str, object]:
            assert expected_node_count == 2
            return {"status": "OK"}

    monkeypatch.setattr(docker_runtime, "_management_cluster_health", light_health)
    monkeypatch.setattr(docker_runtime, "TopologyObserver", FakeTopologyObserver)
    monkeypatch.setattr(
        docker_runtime,
        "_wait_cluster_role_counts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("all-node CLUSTER NODES role wait must not run")
        ),
    )
    monkeypatch.setattr(
        docker_runtime,
        "_process_node_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("failure diagnostic must not run on success")
        ),
    )

    docker_runtime._management_wait_clean_cluster(nodes, timeout=1)

    assert health_calls == [2]
    assert topology_calls == [(2, 3)]


def test_management_wait_clean_cluster_waits_for_topology_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nodes = [
        {
            "logical_id": f"node-{idx}",
            "role": "primary" if idx == 0 else "replica",
            "client_port": 7400 + idx,
            "shard_id": "shard-0000",
        }
        for idx in range(6)
    ]
    health_calls = 0
    topology_calls = 0

    def light_health(probed: list[dict]) -> dict[str, object]:
        nonlocal health_calls
        health_calls += 1
        return {
            "cluster_state": "ok",
            "known_nodes": len(probed),
            "primary_count": 1,
            "replica_count": 5,
            "slots_assigned": 16384,
            "slots_ok": 16384,
            "slots_fail": 0,
            "snapshots": [],
        }

    class FakeTopologyObserver:
        def __init__(self, endpoints, *, observer_count: int, timeout: float):
            assert len(endpoints) == 6
            assert observer_count == 3

        def run(self, *, expected_node_count: int) -> dict[str, object]:
            nonlocal topology_calls
            topology_calls += 1
            assert expected_node_count == 6
            if topology_calls == 1:
                raise RuntimeError("CLUSTER SHARDS contains unhealthy nodes: node-5")
            return {"status": "OK"}

    monkeypatch.setattr(docker_runtime, "_management_cluster_health", light_health)
    monkeypatch.setattr(docker_runtime, "TopologyObserver", FakeTopologyObserver)
    monkeypatch.setattr(docker_runtime.time, "sleep", lambda _seconds: None)

    docker_runtime._management_wait_clean_cluster(nodes, timeout=1)

    assert health_calls == 2
    assert topology_calls == 2


def test_management_wait_clean_cluster_timeout_reports_last_topology_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nodes = [
        {
            "logical_id": "node-0",
            "role": "primary",
            "client_port": 7400,
            "shard_id": "shard-0000",
        },
        {
            "logical_id": "node-1",
            "role": "replica",
            "client_port": 7401,
            "shard_id": "shard-0000",
        },
    ]
    monotonic = iter([0.0, 0.1, 1.1])

    monkeypatch.setattr(docker_runtime.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(docker_runtime.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        docker_runtime,
        "_process_node_snapshot",
        lambda node: {"logical_id": node["logical_id"]},
    )
    monkeypatch.setattr(
        docker_runtime,
        "_management_cluster_health",
        lambda probed: {
            "cluster_state": "ok",
            "known_nodes": len(probed),
            "primary_count": 1,
            "replica_count": 1,
            "slots_assigned": 16384,
            "slots_ok": 16384,
            "slots_fail": 0,
            "snapshots": [{"probe_status": "PASS"}],
        },
    )

    class FailingTopologyObserver:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, *, expected_node_count: int) -> dict[str, object]:
            raise RuntimeError("CLUSTER SHARDS observers disagree on normalized topology")

    monkeypatch.setattr(docker_runtime, "TopologyObserver", FailingTopologyObserver)

    with pytest.raises(
        DockerRuntimeError,
        match="last_topology_error=.*observers disagree",
    ):
        docker_runtime._management_wait_clean_cluster(nodes, timeout=1)


def test_management_wait_clean_cluster_success_path_does_not_use_cluster_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nodes = [
        {
            "logical_id": f"node-{idx}",
            "role": "primary" if idx == 0 else "replica",
            "client_port": 7400 + idx,
            "shard_id": "shard-0000",
        }
        for idx in range(3)
    ]

    monkeypatch.setattr(
        docker_runtime,
        "_node_command",
        lambda _node, *args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("CLUSTER NODES must not be used")
        )
        if args == ("CLUSTER", "NODES")
        else "",
    )
    monkeypatch.setattr(
        docker_runtime,
        "_management_cluster_health",
        lambda probed: {
            "cluster_state": "ok",
            "known_nodes": len(probed),
            "primary_count": 1,
            "replica_count": 2,
            "slots_assigned": 16384,
            "slots_ok": 16384,
            "slots_fail": 0,
            "snapshots": [],
        },
    )

    class FakeTopologyObserver:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, *, expected_node_count: int) -> dict[str, object]:
            return {"status": "OK", "expected_node_count": expected_node_count}

    monkeypatch.setattr(docker_runtime, "TopologyObserver", FakeTopologyObserver)

    docker_runtime._management_wait_clean_cluster(nodes, timeout=1)


def test_management_forget_until_absent_uses_fixed_topology_observers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    survivors = [
        {
            "logical_id": f"node-{idx}",
            "role": "primary" if idx % 2 == 0 else "replica",
            "client_port": 7400 + idx,
            "shard_id": f"shard-{idx // 2:04d}",
            "az_id": f"az-{idx}",
        }
        for idx in range(1999)
    ]
    topology_checks: list[str] = []
    forget_commands: list[str] = []

    class FakeTelemetry:
        def now_unix_ms(self) -> int:
            return 1

    def fake_node_command(node: dict, *args: object, timeout: float = 5.0) -> str:
        if args[:2] == ("CLUSTER", "FORGET"):
            forget_commands.append(str(node["logical_id"]))
            return "OK"
        raise AssertionError(f"unexpected command {args!r}")

    def fake_contains(node: dict, removed_id: str) -> bool:
        topology_checks.append(str(node["logical_id"]))
        assert removed_id == "removed-id"
        return False

    monkeypatch.setattr(docker_runtime, "_node_command", fake_node_command)
    monkeypatch.setattr(docker_runtime, "_management_cluster_nodes_contains", fake_contains)
    monkeypatch.setattr(
        docker_runtime,
        "_management_cluster_health",
        lambda nodes: {
            "cluster_state": "ok",
            "known_nodes": len(nodes),
            "primary_count": sum(node["role"] == "primary" for node in nodes),
            "replica_count": sum(node["role"] == "replica" for node in nodes),
            "slots_assigned": 16384,
            "slots_ok": 16384,
            "slots_fail": 0,
            "snapshots": [],
        },
    )
    command_log: list[dict[str, object]] = []

    docker_runtime._management_forget_until_absent(
        telemetry=FakeTelemetry(),  # type: ignore[arg-type]
        capability_id="cap",
        parent_run_id="run",
        operation_id="remove",
        survivors=survivors,
        removed_id="removed-id",
        expected_nodes=len(survivors),
        expected_primaries=sum(node["role"] == "primary" for node in survivors),
        expected_replicas=sum(node["role"] == "replica" for node in survivors),
        command_log=command_log,  # type: ignore[arg-type]
    )

    assert len(topology_checks) == 3
    assert len(forget_commands) == len(survivors)
    assert {row["status"] for row in command_log} == {"PASS"}


def test_management_forget_unknown_removed_node_is_absent_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTelemetry:
        def now_unix_ms(self) -> int:
            return 1

    def fake_node_command(*_args: object, **_kwargs: object) -> str:
        raise DockerRuntimeError("ERR Unknown node removed-id")

    monkeypatch.setattr(docker_runtime, "_node_command", fake_node_command)
    command_log: list[dict[str, object]] = []

    row = docker_runtime._management_log_forget_removed_node(
        command_log,  # type: ignore[arg-type]
        telemetry=FakeTelemetry(),  # type: ignore[arg-type]
        capability_id="cap",
        parent_run_id="run",
        operation_id="remove",
        target={"logical_id": "survivor"},
        removed_id="removed-id",
    )

    assert row["status"] == "PASS"
    assert command_log == [row]


def test_large_cluster_create_retargets_replicas_after_primary_create(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    meet_calls: list[tuple[list[str], list[str]]] = []
    ensured: list[tuple[str, str]] = []
    parallel_labels: list[str] = []

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True) -> docker_runtime.DockerResult:
        calls.append(args)
        return docker_runtime.DockerResult("OK", "", 0)

    def fake_cli(container: str, *args, timeout: int = 60, check: bool = True) -> str:
        if args[:2] == ("CLUSTER", "MYID"):
            return f"id-{container}"
        return "OK"

    primaries = [
        {"logical_id": "shard-0000-primary", "container_name": "p0", "container_ip": "172.18.0.2", "shard_id": "shard-0000"},
        {"logical_id": "shard-0001-primary", "container_name": "p1", "container_ip": "172.18.0.3", "shard_id": "shard-0001"},
    ]
    replicas = [
        {"logical_id": "shard-0000-replica-00", "container_name": "r0", "container_ip": "172.18.0.4", "shard_id": "shard-0000"},
        {"logical_id": "shard-0001-replica-00", "container_name": "r1", "container_ip": "172.18.0.5", "shard_id": "shard-0001"},
    ]
    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    monkeypatch.setattr(docker_runtime, "run_container_cli", fake_cli)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_known", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_slots_assigned", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_ok", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_role_counts", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        docker_runtime,
        "_tree_fanout_meet_nodes",
        lambda seed, nodes, **kwargs: meet_calls.append(([seed["logical_id"]], [node["logical_id"] for node in nodes])) or len(nodes),
    )
    monkeypatch.setattr(docker_runtime, "_process_node_is_replica_of", lambda replica, master_id: False)
    monkeypatch.setattr(
        docker_runtime,
        "_replicate_process_node",
        lambda replica, master_id, timeout: ensured.append((replica["container_name"], master_id)),
    )
    monkeypatch.setattr(docker_runtime, "_wait_process_replica_of", lambda replica, master_id, timeout: None)

    original_parallel = docker_runtime._bounded_parallel

    def capture_parallel(items, worker, *, parallelism, timeout, label):
        parallel_labels.append(label)
        return original_parallel(items, worker, parallelism=parallelism, timeout=timeout, label=label)

    monkeypatch.setattr(docker_runtime, "_bounded_parallel", capture_parallel)

    docker_runtime._create_large_cluster(primaries, replicas, timeout=30)

    assert calls[0][:6] == ["exec", "p0", "valkey-cli", "--cluster", "create", "172.18.0.2:6379"]
    assert "172.18.0.4:6379" not in calls[0]
    assert "--cluster-replicas" not in calls[0]
    assert meet_calls == [(["shard-0000-primary"], ["shard-0000-replica-00", "shard-0001-replica-00"])]
    assert set(ensured) == {("r0", "id-p0"), ("r1", "id-p1")}
    assert "bounded CLUSTER REPLICATE commands" in parallel_labels


def test_large_cluster_replica_configuration_output_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    parallel_calls: list[dict[str, object]] = []
    primaries = [
        {"logical_id": "shard-0000-primary", "container_name": "p0", "shard_id": "shard-0000"},
        {"logical_id": "shard-0001-primary", "container_name": "p1", "shard_id": "shard-0001"},
    ]
    replicas = [
        {"logical_id": "shard-0001-replica-00", "container_name": "r1", "shard_id": "shard-0001"},
        {"logical_id": "shard-0000-replica-00", "container_name": "r0", "shard_id": "shard-0000"},
    ]

    monkeypatch.setattr(
        docker_runtime,
        "_cluster_node_ids_by_shard",
        lambda nodes, *, timeout, parallelism=docker_runtime.CLUSTER_ORCHESTRATION_PARALLELISM: {
            "shard-0000": "id-p0",
            "shard-0001": "id-p1",
        },
    )
    monkeypatch.setattr(docker_runtime, "_process_node_is_replica_of", lambda replica, master_id: False)
    monkeypatch.setattr(docker_runtime, "_replicate_process_node", lambda replica, master_id, timeout: None)
    monkeypatch.setattr(docker_runtime, "_wait_process_replica_of", lambda replica, master_id, timeout: None)

    def fake_parallel(items, worker, *, parallelism, timeout, label):
        work = list(items)
        parallel_calls.append({"parallelism": parallelism, "label": label, "item_count": len(work)})
        return [worker(item) for item in reversed(work)]

    monkeypatch.setattr(docker_runtime, "_bounded_parallel", fake_parallel)

    output = docker_runtime._configure_large_cluster_replicas(primaries, replicas, timeout=30)

    assert [call["label"] for call in parallel_calls] == [
        "bounded CLUSTER REPLICATE commands",
        "bounded replica-of convergence wait",
    ]
    assert all(call["parallelism"] == docker_runtime.CLUSTER_ORCHESTRATION_PARALLELISM for call in parallel_calls)
    assert all(call["item_count"] == 2 for call in parallel_calls)
    assert output.splitlines() == [
        "replica shard-0001-replica-00 configured for primary shard-0001",
        "replica shard-0000-replica-00 configured for primary shard-0000",
    ]


def test_large_cluster_replica_configuration_records_breakdown_and_slowest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSLAB_REPLICA_REPLICATE_PARALLELISM", "16")
    primaries = [
        {"logical_id": "shard-0000-primary", "container_name": "p0", "shard_id": "shard-0000"},
        {"logical_id": "shard-0001-primary", "container_name": "p1", "shard_id": "shard-0001"},
        {"logical_id": "shard-0002-primary", "container_name": "p2", "shard_id": "shard-0002"},
    ]
    replicas = [
        {"logical_id": "shard-0000-replica-00", "container_name": "r0", "shard_id": "shard-0000"},
        {"logical_id": "shard-0001-replica-00", "container_name": "r1", "shard_id": "shard-0001"},
        {"logical_id": "shard-0002-replica-00", "container_name": "r2", "shard_id": "shard-0002"},
    ]
    labels: list[str] = []

    monkeypatch.setattr(
        docker_runtime,
        "_cluster_node_ids_by_shard",
        lambda nodes, *, timeout, parallelism=docker_runtime.CLUSTER_ORCHESTRATION_PARALLELISM: {
            "shard-0000": "id-p0",
            "shard-0001": "id-p1",
            "shard-0002": "id-p2",
        },
    )
    monkeypatch.setattr(docker_runtime, "_process_node_is_replica_of", lambda replica, master_id: False)
    monkeypatch.setattr(docker_runtime, "_replicate_process_node", lambda replica, master_id, timeout: None)
    monkeypatch.setattr(docker_runtime, "_wait_process_replica_of", lambda replica, master_id, timeout: None)

    def fake_parallel(items, worker, *, parallelism, timeout, label):
        work = list(items)
        labels.append(label)
        assert parallelism == 16
        return [worker(item) for item in work]

    monkeypatch.setattr(docker_runtime, "_bounded_parallel", fake_parallel)

    output, details = docker_runtime._configure_large_cluster_replicas_with_diagnostics(primaries, replicas, timeout=30)

    assert output.splitlines() == [
        "replica shard-0000-replica-00 configured for primary shard-0000",
        "replica shard-0001-replica-00 configured for primary shard-0001",
        "replica shard-0002-replica-00 configured for primary shard-0002",
    ]
    assert labels == [
        "bounded CLUSTER REPLICATE commands",
        "bounded replica-of convergence wait",
    ]
    assert details["parallelism"] == 16
    assert details["bounded_parallelism"] is True
    assert details["replica_primary_id_lookup_seconds"] >= 0.0
    assert details["replica_replicate_command_seconds"] >= 0.0
    assert details["replica_replicaof_wait_seconds"] >= 0.0
    assert details["replica_replicate_total_seconds"] >= 0.0
    assert len(details["replica_diagnostics"]) == 3
    assert len(details["slowest_replicas"]) == 3
    assert all(item["status"] == "PASS" for item in details["slowest_replicas"])


def test_primary_cluster_create_uses_process_node_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True) -> docker_runtime.DockerResult:
        calls.append(args)
        return docker_runtime.DockerResult("OK", "", 0)

    primaries = [
        {
            "logical_id": "shard-0000-primary",
            "container_name": "nodehost-a",
            "nodehost_container_ip": "172.18.0.2",
            "client_port": 7400,
            "shard_id": "shard-0000",
        },
        {
            "logical_id": "shard-0001-primary",
            "container_name": "nodehost-b",
            "nodehost_container_ip": "172.18.0.3",
            "client_port": 7401,
            "shard_id": "shard-0001",
        },
    ]
    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)

    docker_runtime._create_primary_cluster(primaries, timeout=30)

    assert calls[0][:5] == ["exec", "nodehost-a", "valkey-cli", "--cluster", "create"]
    assert "172.18.0.2:7400" in calls[0]
    assert "172.18.0.3:7401" in calls[0]
    assert "172.18.0.2:6379" not in calls[0]


def test_primary_cluster_create_keeps_process_addresses_in_primary_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True) -> docker_runtime.DockerResult:
        calls.append(args)
        return docker_runtime.DockerResult("OK", "", 0)

    primaries = [
        {
            "logical_id": f"shard-{idx:04d}-primary",
            "container_name": f"nodehost-{idx % 2}",
            "nodehost_container_ip": f"172.18.0.{2 + idx % 2}",
            "client_port": 7400 + idx,
            "shard_id": f"shard-{idx:04d}",
        }
        for idx in range(25)
    ]
    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)

    docker_runtime._create_primary_cluster(primaries, timeout=30)

    address_start = calls[0].index("create") + 1
    addresses = calls[0][address_start : address_start + len(primaries)]
    assert addresses == [f"172.18.0.{2 + idx % 2}:{7400 + idx}" for idx in range(25)]


def test_default_primary_create_records_strategy_subtimings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VSLAB_CLUSTER_CREATE_STRATEGY", raising=False)
    monkeypatch.setattr(docker_runtime, "_create_primary_cluster", lambda primaries, timeout: "cluster create OK")
    monkeypatch.setattr(docker_runtime, "_wait_cluster_known", lambda *args, **kwargs: None)

    output, details = docker_runtime._create_primary_cluster_valkey_cli([{"logical_id": "p0"}, {"logical_id": "p1"}], timeout=30)

    assert "cluster create OK" in output
    assert details["primary_meet_seconds"] == 0.0
    assert details["slot_assignment_seconds"] == 0.0
    assert details["slot_assignment_scope"] == "inside_valkey_cli_cluster_create"
    assert details["cluster_create_command_seconds"] >= 0.0
    assert details["primary_convergence_seconds"] >= 0.0


def test_manual_primary_create_uses_tree_meet_and_parallel_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    primaries = [{"logical_id": f"p{idx}"} for idx in range(3)]
    slot_calls: list[tuple[str, int, int]] = []
    parallel_labels: list[str] = []

    monkeypatch.setattr(docker_runtime, "_tree_fanout_meet_nodes", lambda seed, nodes, timeout: 2)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_known", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_slots_assigned", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_ok", lambda *args, **kwargs: None)

    def fake_add_slots(node: dict, start: int, end: int) -> None:
        slot_calls.append((node["logical_id"], start, end))

    def fake_parallel(items, worker, *, parallelism, timeout, label):
        parallel_labels.append(label)
        work = list(items)
        for item in work:
            worker(item)
        return []

    monkeypatch.setattr(docker_runtime, "_add_slots_node", fake_add_slots)
    monkeypatch.setattr(docker_runtime, "_bounded_parallel", fake_parallel)

    output, details = docker_runtime._create_primary_cluster_manual_tree_meet_parallel_slots(primaries, timeout=30)

    assert "manual tree meet" in output
    assert details["meet_commands"] == 2
    assert details["cluster_create_command_seconds"] == 0.0
    assert details["primary_meet_seconds"] >= 0.0
    assert details["slot_assignment_seconds"] >= 0.0
    assert details["primary_convergence_seconds"] >= 0.0
    assert details["slot_assignment_scope"] == "parallel_cluster_addslots"
    assert parallel_labels == ["parallel primary CLUSTER ADDSLOTS"]
    assert len(slot_calls) == 3


def test_non_range_strategy_does_not_report_unused_range_parallelism(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSLAB_CLUSTER_CREATE_STRATEGY", docker_runtime.CLUSTER_CREATE_STRATEGY_MANUAL)
    monkeypatch.setenv("VSLAB_CLUSTER_CREATE_PARALLELISM", "16")
    monkeypatch.delenv(docker_runtime.M2_MEASUREMENT_ENV, raising=False)
    monkeypatch.setattr(
        docker_runtime,
        "_create_primary_cluster_manual_tree_meet_parallel_slots",
        lambda primaries, timeout: ("manual", {"slot_assignment_scope": "parallel_cluster_addslots"}),
    )
    timings: dict[str, dict] = {}

    docker_runtime._create_large_cluster([{"logical_id": "p0"}], [], timeout=30, timings=timings)

    details = timings["primary_cluster_create"]["details"]
    assert details["strategy"] == docker_runtime.CLUSTER_CREATE_STRATEGY_MANUAL
    assert "parallelism" not in details
    assert "parallelism_source" not in details
    assert "bounded_parallelism" not in details


def test_addslotsrange_primary_create_uses_selected_bounded_parallelism(monkeypatch: pytest.MonkeyPatch) -> None:
    primaries = [{"logical_id": f"p{idx}"} for idx in range(3)]
    range_calls: list[tuple[str, tuple[object, ...]]] = []
    parallel_calls: list[tuple[str, int]] = []
    meet_parallelism: list[int] = []

    def fake_meet(seed, nodes, *, timeout, fanout=docker_runtime.CLUSTER_MEET_FANOUT, parallelism):
        meet_parallelism.append(parallelism)
        return len(nodes)

    def fake_node_command(node, *args, timeout):
        range_calls.append((node["logical_id"], args))
        return "OK"

    def fake_parallel(items, worker, *, parallelism, timeout, label):
        parallel_calls.append((label, parallelism))
        work = list(items)
        for item in work:
            worker(item)
        return []

    monkeypatch.setattr(docker_runtime, "_tree_fanout_meet_nodes", fake_meet)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_known", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_slots_assigned", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_ok", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_node_command", fake_node_command)
    monkeypatch.setattr(docker_runtime, "_bounded_parallel", fake_parallel)

    output, details = docker_runtime._create_primary_cluster_tree_meet_addslotsrange(
        primaries,
        timeout=30,
        parallelism=16,
    )

    assert "tree meet ADDSLOTSRANGE" in output
    assert meet_parallelism == [16]
    assert parallel_calls == [("parallel primary CLUSTER ADDSLOTSRANGE", 16)]
    assert [args[:2] for _logical_id, args in range_calls] == [
        ("CLUSTER", "ADDSLOTSRANGE"),
        ("CLUSTER", "ADDSLOTSRANGE"),
        ("CLUSTER", "ADDSLOTSRANGE"),
    ]
    assert details["parallelism"] == 16
    assert details["bounded_parallelism"] is True
    assert details["slot_assignment_commands"] == 3
    assert details["slot_assignment_scope"] == "parallel_cluster_addslotsrange"


def test_preseed_epoch_primary_create_orders_slots_epochs_then_first_meet(monkeypatch: pytest.MonkeyPatch) -> None:
    primaries = [{"logical_id": f"p{idx}", "shard_id": f"shard-{idx}"} for idx in range(3)]
    calls: list[tuple[str, str, tuple[object, ...]]] = []

    def fake_node_command(node, *args, timeout):
        calls.append(("command", node["logical_id"], args))
        return "OK"

    def fake_parallel(items, worker, *, parallelism, timeout, label):
        for item in list(items):
            worker(item)
        return []

    def fake_meet(seed, nodes, *, timeout, fanout=docker_runtime.CLUSTER_MEET_FANOUT, parallelism):
        calls.append(("meet", seed["logical_id"], tuple(node["logical_id"] for node in nodes)))
        return len(nodes)

    def fake_barrier(observer, *, expected_primaries, timeout):
        calls.append(("barrier", observer["logical_id"], (expected_primaries,)))

    monkeypatch.setattr(docker_runtime, "_node_command", fake_node_command)
    monkeypatch.setattr(docker_runtime, "_bounded_parallel", fake_parallel)
    monkeypatch.setattr(docker_runtime, "_tree_fanout_meet_nodes", fake_meet)
    monkeypatch.setattr(docker_runtime, "_wait_primary_service_barrier", fake_barrier)

    output, details = docker_runtime._create_primary_cluster_preseed_epoch_tree_meet(
        primaries,
        timeout=30,
        parallelism=8,
    )

    kinds = [
        "addslotsrange" if call[2][:2] == ("CLUSTER", "ADDSLOTSRANGE")
        else "epoch" if call[2][:2] == ("CLUSTER", "SET-CONFIG-EPOCH")
        else call[0]
        for call in calls
    ]
    assert kinds == ["addslotsrange", "addslotsrange", "addslotsrange", "epoch", "epoch", "epoch", "meet", "barrier"]
    assert [call[2][2] for call in calls if call[2][:2] == ("CLUSTER", "SET-CONFIG-EPOCH")] == [1, 2, 3]
    assert "preseed epoch tree meet" in output
    assert details["config_epochs"] == [1, 2, 3]
    assert details["slot_assignment_scope"] == "parallel_cluster_addslotsrange_before_epoch_preseed"


def test_preseed_replica_pipeline_runs_local_meet_replicate_then_role_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    primaries = [
        {"logical_id": "p0", "shard_id": "s0"},
        {"logical_id": "p1", "shard_id": "s1"},
    ]
    replicas = [
        {"logical_id": "r0", "shard_id": "s0"},
        {"logical_id": "r1", "shard_id": "s1"},
    ]
    calls: dict[str, list[str]] = {replica["logical_id"]: [] for replica in replicas}

    monkeypatch.setattr(docker_runtime, "_cluster_node_ids_by_shard", lambda nodes, *, timeout, parallelism: {"s0": "id-p0", "s1": "id-p1"})
    monkeypatch.setattr(docker_runtime, "_meet_node_pair", lambda replica, primary: calls[replica["logical_id"]].append("MEET"))
    monkeypatch.setattr(docker_runtime, "_replicate_process_node", lambda replica, master_id, timeout: calls[replica["logical_id"]].append("REPLICATE"))
    monkeypatch.setattr(docker_runtime, "_wait_process_replica_of", lambda replica, master_id, timeout: calls[replica["logical_id"]].append("ROLE_MYSLOTS"))
    monkeypatch.setattr(docker_runtime, "_bounded_parallel", lambda items, worker, *, parallelism, timeout, label: [worker(item) for item in items])

    output, details = docker_runtime._configure_replicas_local_meet_replicate_pipeline(primaries, replicas, timeout=30)

    assert calls == {"r0": ["MEET", "REPLICATE", "ROLE_MYSLOTS"], "r1": ["MEET", "REPLICATE", "ROLE_MYSLOTS"]}
    assert "local-meet pipelined" in output
    assert details["replica_meet_integrated_with_pipeline"] is True
    assert details["replica_meet_commands"] == 2


def test_preseed_large_cluster_uses_replica_pipeline_without_global_replica_meet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSLAB_CLUSTER_CREATE_STRATEGY", docker_runtime.CLUSTER_CREATE_STRATEGY_PRESEED_EPOCH_PIPELINE_REPLICAS)
    primaries = [{"logical_id": "p0", "shard_id": "s0"}, {"logical_id": "p1", "shard_id": "s1"}]
    replicas = [{"logical_id": "r0", "shard_id": "s0"}, {"logical_id": "r1", "shard_id": "s1"}]
    monkeypatch.setattr(docker_runtime, "_create_primary_cluster_preseed_epoch_tree_meet", lambda primaries, timeout, parallelism, setup_timeline=None: ("primaries", {"primary_meet_seconds": 0.1}))
    monkeypatch.setattr(docker_runtime, "_configure_replicas_local_meet_replicate_pipeline", lambda primaries, replicas, timeout: ("replicas", {"replica_pipeline_seconds": 0.2, "replica_meet_integrated_with_pipeline": True}))
    monkeypatch.setattr(docker_runtime, "_tree_fanout_meet_nodes", lambda *args, **kwargs: pytest.fail("preseed strategy must not run global replica MEET"))
    monkeypatch.setattr(docker_runtime, "_wait_process_known", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_wait_process_slots_assigned", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_wait_process_cluster_ok", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_wait_process_role_counts", lambda *args, **kwargs: None)

    timings: dict[str, dict] = {}
    output = docker_runtime._create_large_cluster(primaries, replicas, timeout=30, timings=timings)

    assert output == "primaries\nreplicas"
    assert "replica_meet" not in timings
    assert timings["replica_replicate"]["details"]["replica_meet_integrated_with_pipeline"] is True


def test_preseed_runtime_timing_counts_integrated_replica_pipeline_once(tmp_path: Path) -> None:
    timings = {
        "primary_cluster_create": {
            "name": "primary_cluster_create",
            "status": "PASS",
            "duration_seconds": 1.25,
            "count": 1,
            "details": {},
        },
        "replica_replicate": {
            "name": "replica_replicate",
            "status": "PASS",
            "duration_seconds": 2.5,
            "count": 1,
            "details": {"replica_meet_integrated_with_pipeline": True},
        },
    }

    path = tmp_path / "runtime_timing.json"
    docker_runtime._write_runtime_timing_breakdown(
        path,
        "scale_ladder",
        "scale_ladder",
        "exact-50",
        "run-1",
        [{"logical_id": "p0"}],
        timings,
        status="PASS",
    )
    artifact = json.loads(path.read_text(encoding="utf-8"))

    assert artifact["summary"]["cluster_create_duration_seconds"] == 3.75
    entries = {entry["name"]: entry for entry in artifact["timings"]}
    assert entries["replica_meet"]["status"] == "MISSING"
    assert entries["replica_replicate"]["details"]["replica_meet_integrated_with_pipeline"] is True


def test_legacy_runtime_timing_still_requires_replica_meet(tmp_path: Path) -> None:
    timings = {
        "primary_cluster_create": {
            "name": "primary_cluster_create",
            "status": "PASS",
            "duration_seconds": 1.25,
            "count": 1,
            "details": {},
        },
        "replica_replicate": {
            "name": "replica_replicate",
            "status": "PASS",
            "duration_seconds": 2.5,
            "count": 1,
            "details": {},
        },
    }

    path = tmp_path / "runtime_timing.json"
    docker_runtime._write_runtime_timing_breakdown(
        path,
        "scale_ladder",
        "scale_ladder",
        "exact-50",
        "run-1",
        [{"logical_id": "p0"}],
        timings,
        status="PASS",
    )
    artifact = json.loads(path.read_text(encoding="utf-8"))

    assert artifact["summary"]["cluster_create_duration_seconds"] == "MISSING"


def test_addslotsrange_primary_create_assigns_full_range_to_single_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []

    def fake_node_command(node, *args, timeout):
        calls.append(args)
        return "OK"

    def fake_parallel(items, worker, *, parallelism, timeout, label):
        return [worker(item) for item in items]

    monkeypatch.setattr(
        docker_runtime,
        "_tree_fanout_meet_nodes",
        lambda *args, **kwargs: pytest.fail("single-primary strategy must not run CLUSTER MEET"),
    )
    monkeypatch.setattr(docker_runtime, "_wait_cluster_slots_assigned", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_wait_cluster_ok", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_node_command", fake_node_command)
    monkeypatch.setattr(docker_runtime, "_bounded_parallel", fake_parallel)

    _output, details = docker_runtime._create_primary_cluster_tree_meet_addslotsrange(
        [{"logical_id": "p0"}],
        timeout=30,
        parallelism=4,
    )

    assert calls == [("CLUSTER", "ADDSLOTSRANGE", 0, 16383)]
    assert details["meet_commands"] == 0
    assert details["slot_assignment_commands"] == 1
    assert details["slot_assignment_scope"] == "parallel_cluster_addslotsrange"


def test_addslotsrange_failure_is_explicit_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []

    def unavailable(node, *args, timeout):
        calls.append(args)
        raise DockerRuntimeError("ERR unknown command")

    monkeypatch.setattr(docker_runtime, "_node_command", unavailable)

    with pytest.raises(DockerRuntimeError, match="native CLUSTER ADDSLOTSRANGE unavailable or failed for p0"):
        docker_runtime._add_slots_range_node({"logical_id": "p0"}, 0, 100)

    assert calls == [("CLUSTER", "ADDSLOTSRANGE", 0, 100)]


def test_port_collision_check_rejects_bound_port(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSocket:
        def __enter__(self) -> "FakeSocket":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def setsockopt(self, *args: object) -> None:
            return None

        def bind(self, *args: object) -> None:
            raise OSError("already bound")

    monkeypatch.setattr(docker_runtime.socket, "socket", lambda *args, **kwargs: FakeSocket())
    with pytest.raises(DockerRuntimeError, match="not available"):
        docker_runtime._check_ports_free([7000])


def test_cleanup_report_shape_without_owned_resources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "schema_version": "v1",
        "cluster_id": "test",
        "capability_id": "cluster_lifecycle",
        "scenario": "cluster_lifecycle",
        "runtime": {"run_id": "test-run"},
        "nodes": [],
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(docker_runtime.json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(docker_runtime, "_cleanup_resources_by_label", lambda *, capability_id, run_id: ([], {"cleanup_remove_containers_seconds": 0.0, "cleanup_remove_networks_seconds": 0.0}))
    monkeypatch.setattr(docker_runtime, "owned_resources", lambda *, capability_id, run_id: [])
    report = docker_runtime.cleanup_scenario(state_path=state_path, artifacts_dir=tmp_path, out_path=tmp_path / "cleanup.json")
    assert report["status"] == "PASS"
    assert report["resources_remaining"] == []
    assert report["cleanup_timing"]["cleanup_residual_scan_seconds"] >= 0.0
    assert (tmp_path / "cleanup_report_cluster_lifecycle.json").exists()


def test_cleanup_removes_fault_state_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "schema_version": "v1",
        "cluster_id": "test",
        "capability_id": "fault_matrix",
        "runtime": {"run_id": "test-run"},
        "nodes": [],
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(docker_runtime.json.dumps(state), encoding="utf-8")
    fault_state = tmp_path / "fault_state_fault-primary-stop.json"
    fault_state.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(docker_runtime, "_cleanup_resources_by_label", lambda *, capability_id, run_id: ([], {"cleanup_remove_containers_seconds": 0.0, "cleanup_remove_networks_seconds": 0.0}))
    monkeypatch.setattr(docker_runtime, "owned_resources", lambda *, capability_id, run_id: [])
    report = docker_runtime.cleanup_scenario(state_path=state_path, artifacts_dir=tmp_path, out_path=tmp_path / "cleanup.json")
    assert report["status"] == "PASS"
    assert not fault_state.exists()
    assert any(action["type"] == "fault_state" for action in report["cleanup_actions"])


def test_process_cleanup_records_timing_and_uses_bounded_parallelism(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    labels: list[str] = []
    calls: list[list[str]] = []
    state = {
        "schema_version": "v1",
        "cluster_id": "test",
        "capability_id": "scale_ladder",
        "scenario": "scale_ladder",
        "runtime": {"type": "docker_process", "run_id": "test-run"},
        "nodehosts": [
            {"nodehost_id": "nodehost-az-a", "container_name": "nodehost-a"},
            {"nodehost_id": "nodehost-az-b", "container_name": "nodehost-b"},
        ],
        "nodes": [
            {"logical_id": "n0", "nodehost_id": "nodehost-az-a", "nodehost_container_name": "nodehost-a", "pid": 101},
            {"logical_id": "n1", "nodehost_id": "nodehost-az-b", "nodehost_container_name": "nodehost-b", "pid": 102},
        ],
    }

    def fake_parallel(items, worker, *, parallelism, timeout, label):
        work = list(items)
        labels.append(label)
        assert parallelism == docker_runtime.CLUSTER_ORCHESTRATION_PARALLELISM
        return [worker(item) for item in work]

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True) -> docker_runtime.DockerResult:
        calls.append(args)
        if args[:2] == ["inspect", "-f"]:
            return docker_runtime.DockerResult(
                json.dumps(
                    {
                        f"{docker_runtime.LABEL_PREFIX}.project": docker_runtime.PROJECT,
                        f"{docker_runtime.LABEL_PREFIX}.capability_id": state["capability_id"],
                        f"{docker_runtime.LABEL_PREFIX}.run_id": state["runtime"]["run_id"],
                    }
                ),
                "",
                0,
            )
        if args[:2] == ["exec", "nodehost-a"] or args[:2] == ["exec", "nodehost-b"]:
            if args[2:4] == ["sh", "-c"]:
                if "kill -TERM" in args[4]:
                    return docker_runtime.DockerResult("signaled=1 already_stopped=0 failed=0\n", "", 0)
                return docker_runtime.DockerResult("", "", 0)
            if args[2:4] == ["pgrep", "-x"]:
                return docker_runtime.DockerResult("", "", 1)
        return docker_runtime.DockerResult("", "", 0)

    monkeypatch.setattr(docker_runtime, "_bounded_parallel", fake_parallel)
    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    monkeypatch.setattr(
        docker_runtime,
        "_cleanup_resources_by_label",
        lambda *, capability_id, run_id: (
            [{"type": "container", "id": "nodehost-a", "action": "remove", "status": "PASS"}],
            {"cleanup_remove_containers_seconds": 0.01, "cleanup_remove_networks_seconds": 0.02},
        ),
    )
    monkeypatch.setattr(docker_runtime, "owned_resources", lambda *, capability_id, run_id: [])

    report = docker_runtime._cleanup_process_scenario(state=state, artifacts_dir=tmp_path, out_path=tmp_path / "cleanup.json")

    assert report["status"] == "PASS"
    assert labels == [
        "nodehost Valkey process termination",
        "nodehost Valkey process exit verification",
        "nodehost Valkey residual check",
    ]
    assert len([call for call in calls if call[:3] == ["exec", call[1], "sh"] and "kill -TERM" in call[-1]]) == 2
    assert not any(call[:4] == ["exec", call[1], "kill", "-TERM"] for call in calls)
    for field in [
        "cleanup_terminate_processes_seconds",
        "cleanup_verify_process_exit_seconds",
        "cleanup_verify_nodehost_empty_seconds",
        "cleanup_remove_containers_seconds",
        "cleanup_remove_networks_seconds",
        "cleanup_residual_scan_seconds",
    ]:
        assert report["cleanup_timing"][field] >= 0.0
    assert report["cleanup_timing"]["bounded_parallelism"] is True


def test_process_cleanup_tolerates_slow_bulk_termination_when_residuals_clear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "schema_version": "v1",
        "cluster_id": "test",
        "capability_id": "management_matrix",
        "scenario": "management_matrix",
        "runtime": {"type": "docker_process", "run_id": "test-run"},
        "nodehosts": [
            {"nodehost_id": "nodehost-az-a", "container_name": "nodehost-a"},
        ],
        "nodes": [
            {"logical_id": "n0", "nodehost_id": "nodehost-az-a", "nodehost_container_name": "nodehost-a", "pid": 101},
            {"logical_id": "n1", "nodehost_id": "nodehost-az-a", "nodehost_container_name": "nodehost-a", "pid": 102},
        ],
    }

    def fake_parallel(items, worker, *, parallelism, timeout, label):
        return [worker(item) for item in list(items)]

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True) -> docker_runtime.DockerResult:
        if args[:2] == ["inspect", "-f"]:
            return docker_runtime.DockerResult(
                json.dumps(
                    {
                        f"{docker_runtime.LABEL_PREFIX}.project": docker_runtime.PROJECT,
                        f"{docker_runtime.LABEL_PREFIX}.capability_id": state["capability_id"],
                        f"{docker_runtime.LABEL_PREFIX}.run_id": state["runtime"]["run_id"],
                    }
                ),
                "",
                0,
            )
        if args[:4] == ["exec", "nodehost-a", "sh", "-c"]:
            if "kill -TERM" in args[4]:
                raise DockerRuntimeError("docker exec nodehost-a kill batch timed out after 60 seconds")
            return docker_runtime.DockerResult("", "", 0)
        if args[:4] == ["exec", "nodehost-a", "pgrep", "-x"]:
            return docker_runtime.DockerResult("", "", 1)
        return docker_runtime.DockerResult("", "", 0)

    monkeypatch.setattr(docker_runtime, "_bounded_parallel", fake_parallel)
    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    monkeypatch.setattr(
        docker_runtime,
        "_cleanup_resources_by_label",
        lambda *, capability_id, run_id: (
            [{"type": "container", "id": "nodehost-a", "action": "remove", "status": "PASS"}],
            {"cleanup_remove_containers_seconds": 0.01, "cleanup_remove_networks_seconds": 0.02},
        ),
    )
    monkeypatch.setattr(docker_runtime, "owned_resources", lambda *, capability_id, run_id: [])

    report = docker_runtime._cleanup_process_scenario(state=state, artifacts_dir=tmp_path, out_path=tmp_path / "cleanup.json")

    assert report["status"] == "PASS"
    terminate_actions = [action for action in report["cleanup_actions"] if action.get("action") == "terminate"]
    assert terminate_actions[0]["status"] == "SKIPPED_WITH_REASON"
    assert "timed out" in terminate_actions[0]["stderr"]
    assert report["resources_remaining"] == []


def test_container_cleanup_timeout_budget_matches_stop_and_remove(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, float] = {}

    def fake_ids(args: list[str]) -> list[str]:
        if args[:3] == ["ps", "-a", "-q"]:
            return ["cid-a", "cid-b"]
        return []

    def fake_parallel(items, worker, *, parallelism, timeout, label):
        captured[label] = timeout
        return [worker(item) for item in list(items)]

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True) -> docker_runtime.DockerResult:
        if args[0] == "stop":
            raise DockerRuntimeError("slow stop")
        if args[0] == "rm":
            return docker_runtime.DockerResult("", "", 0)
        raise AssertionError(f"unexpected docker command: {args}")

    monkeypatch.setattr(docker_runtime, "_docker_ids", fake_ids)
    monkeypatch.setattr(docker_runtime, "_bounded_parallel", fake_parallel)
    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)

    actions, _timing = docker_runtime._cleanup_resources_by_label(capability_id="management_matrix", run_id="test-run")

    assert captured["owned container cleanup"] >= docker_runtime.CONTAINER_STOP_TIMEOUT_SECONDS + docker_runtime.CONTAINER_REMOVE_TIMEOUT_SECONDS
    assert [action["status"] for action in actions] == [
        "SKIPPED_WITH_REASON",
        "PASS",
        "SKIPPED_WITH_REASON",
        "PASS",
    ]


def test_orchestration_cleanup_appends_orchestrator_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "schema_version": "v1",
        "cluster_id": "test",
        "capability_id": "orchestration",
        "runtime": {"run_id": "test-run"},
        "nodes": [],
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(docker_runtime.json.dumps(state), encoding="utf-8")
    orch_report = {
        "schema_version": "v1",
        "artifact_type": "orchestration_report",
        "capability_id": "orchestration",
        "run_id": "test-run",
        "status": "PASS",
        "operations": [{"operation": "prepare", "status": "PASS"}],
    }
    (tmp_path / "orchestration_report.json").write_text(docker_runtime.json.dumps(orch_report), encoding="utf-8")
    monkeypatch.setattr(docker_runtime, "_cleanup_resources_by_label", lambda *, capability_id, run_id: ([], {"cleanup_remove_containers_seconds": 0.0, "cleanup_remove_networks_seconds": 0.0}))
    monkeypatch.setattr(docker_runtime, "owned_resources", lambda *, capability_id, run_id: [])

    report = docker_runtime.cleanup_scenario(state_path=state_path, artifacts_dir=tmp_path, out_path=tmp_path / "cleanup.json")
    updated = docker_runtime.json.loads((tmp_path / "orchestration_report.json").read_text(encoding="utf-8"))

    assert report["status"] == "PASS"
    assert updated["operations"][-1]["operation"] == "stop"
    assert updated["operations"][-1]["details"]["idempotent"] is True


def test_management_ops_report_taxonomy(tmp_path: Path) -> None:
    operations = [
        {"operation": "meet", "status": "PASS", "duration_seconds": 0.1},
        {
            "operation": "remove_node",
            "status": "SKIPPED_WITH_REASON",
            "duration_seconds": 0.0,
            "reason": "not destructive in smoke",
        },
    ]
    out = tmp_path / "management_ops_report.json"
    docker_runtime.write_management_ops_report(out, "management_matrix", "management_ops", "run", operations)
    report = docker_runtime.json.loads(out.read_text(encoding="utf-8"))
    assert report["artifact_type"] == "management_ops_report"
    assert report["status"] == "PASS"
    assert report["summary"]["passed"] == 1
    assert report["summary"]["skipped_with_reason"] == 1


def test_latency_summary_has_required_percentiles() -> None:
    summary = docker_runtime._latency_summary([1.0, 2.0, 3.0, 4.0])
    assert summary["p50"] == 2.5
    assert summary["p95"] > summary["p50"]
    assert summary["p99"] >= summary["p95"]
    assert summary["sample_count"] == 4


def test_empty_latency_summary_marks_missing() -> None:
    summary = docker_runtime._latency_summary([])
    assert summary["p50"]["status"] == "MISSING"
    assert summary["p95"]["status"] == "MISSING"
    assert summary["p99"]["status"] == "MISSING"


def test_parse_info_and_missing_integer_encoding() -> None:
    parsed = docker_runtime._parse_info("# Server\nuptime_in_seconds:12\nused_memory:not-an-int\n")
    assert parsed["uptime_in_seconds"] == "12"
    assert docker_runtime._int_or_missing(parsed["uptime_in_seconds"]) == 12
    assert docker_runtime._int_or_missing(parsed["used_memory"]) == "MISSING"
    assert docker_runtime._int_or_missing(None) == "MISSING"


def test_event_shape() -> None:
    event = docker_runtime._event("observability", "run", "sampled", "info", {"node": "n1"})
    assert event["artifact_type"] == "event"
    assert event["severity"] == "info"
    assert event["details"]["node"] == "n1"


def test_docker_stats_many_uses_one_command_for_all_nodehosts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True) -> docker_runtime.DockerResult:
        calls.append(args)
        rows = [
            {"Name": "nodehost-a", "CPUPerc": "1.00%", "MemUsage": "10MiB / 1GiB", "NetIO": "1kB / 2kB", "PIDs": "4"},
            {"Name": "nodehost-b", "CPUPerc": "2.00%", "MemUsage": "20MiB / 1GiB", "NetIO": "3kB / 4kB", "PIDs": "5"},
        ]
        return docker_runtime.DockerResult("\n".join(json.dumps(row) for row in rows), "", 0)

    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)

    result = docker_runtime._docker_stats_many(["nodehost-a", "nodehost-b", "nodehost-a"])

    assert calls == [["stats", "--no-stream", "--format", "{{json .}}", "nodehost-a", "nodehost-b"]]
    assert result["nodehost-a"]["memory_usage"] == "10MiB / 1GiB"
    assert result["nodehost-b"]["pids"] == "5"


def test_docker_stats_many_degrades_timeouts_to_structured_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        lambda *args, **kwargs: (_ for _ in ()).throw(DockerRuntimeError("stats timeout")),
    )

    result = docker_runtime._docker_stats_many(["nodehost-a", "nodehost-b"])

    assert set(result) == {"nodehost-a", "nodehost-b"}
    assert all(item["status"] == "MISSING" for item in result.values())
    assert all("timeout" in item["reason"] for item in result.values())


def test_docker_stats_rejects_non_object_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        lambda *args, **kwargs: docker_runtime.DockerResult("null\n", "", 0),
    )

    result = docker_runtime._docker_stats("nodehost-a")

    assert result["status"] == "MISSING"
    assert "not an object" in result["reason"]


def test_cleanup_process_scan_parsing_and_zombie_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True) -> docker_runtime.DockerResult:
        calls.append(args)
        return docker_runtime.DockerResult("alive=\nzombie=101\nunreadable=\nmissing=102\n", "", 0)

    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    result = docker_runtime._wait_container_pids_gone("nodehost-a", ["101", "102"], timeout=1.0)

    assert result["gone"] is True
    assert result["zombie_pids"] == ["101"]
    assert "/proc/$pid/stat" in calls[0][-1]
    assert "kill -0" not in calls[0][-1]


def test_single_process_wait_requires_an_explicit_process_state_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def failed_probe(
        args: list[str], timeout: int = 120, check: bool = True
    ) -> docker_runtime.DockerResult:
        calls.append(args)
        return docker_runtime.DockerResult("", "executable not found", 127)

    monkeypatch.setattr(docker_runtime, "run_docker", failed_probe)

    with pytest.raises(DockerRuntimeError, match="owned process probe failed"):
        docker_runtime._wait_container_pid_gone("nodehost-a", "101", timeout=1.0)

    assert calls[0][:4] == ["exec", "nodehost-a", "sh", "-c"]
    assert "/proc/101/stat" in calls[0][-1]


@pytest.mark.parametrize("pid", [True, 0, -1, "1.5", "1; touch /tmp/unsafe"])
def test_single_process_wait_rejects_unsafe_pids(pid: object) -> None:
    with pytest.raises(DockerRuntimeError, match="unsafe process runtime pid"):
        docker_runtime._wait_container_pid_gone("nodehost-a", pid, timeout=1.0)


def test_single_process_wait_observes_alive_then_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(
        [
            docker_runtime.DockerResult("VSLAB_ALIVE", "", 0),
            docker_runtime.DockerResult("VSLAB_GONE", "", 0),
        ]
    )
    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        lambda *_args, **_kwargs: next(observations),
    )
    monkeypatch.setattr(docker_runtime.time, "sleep", lambda _seconds: None)

    assert docker_runtime._wait_container_pid_gone(
        "nodehost-a", "101", timeout=1.0
    )


def test_management_stop_uses_shell_builtin_for_term_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    gone = iter([False, True])

    def record_command(
        _log,
        _telemetry,
        _capability,
        _run,
        _operation,
        _kind,
        _target,
        args,
        **_kwargs,
    ):
        calls.append(args)

    monkeypatch.setattr(
        docker_runtime,
        "_management_matrix_log_docker_exec",
        record_command,
    )
    monkeypatch.setattr(
        docker_runtime,
        "_wait_container_pid_gone",
        lambda *_args, **_kwargs: next(gone),
    )

    docker_runtime._management_matrix_stop_process(
        {
            "logical_id": "node-a",
            "nodehost_container_name": "nodehost-a",
            "pid": 101,
            "client_port": 7000,
        },
        object(),
        "management_matrix",
        "run-1",
        "operation-1",
        [],
        command_kind="owned_valkey_process_stop",
    )

    assert calls == [
        [
            "exec",
            "nodehost-a",
            "valkey-cli",
            "-p",
            "7000",
            "SHUTDOWN",
            "NOSAVE",
        ],
        ["exec", "nodehost-a", "sh", "-c", "kill -TERM 101"],
    ]


def test_cleanup_residual_scan_treats_unreadable_process_as_uncertain() -> None:
    script = docker_runtime._cleanup_scan_valkey_script()
    parsed = docker_runtime._cleanup_parse_process_scan("live=\nzombie=\nunreadable=101\n")

    assert parsed["unreadable"] == ["101"]
    assert 'unreadable="$unreadable ${proc_dir##*/}"' in script
    assert 'test -z "$live" -a -z "$unreadable"' in script


def test_nodehost_runtime_uses_init_for_process_reaping(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        lambda args, timeout=120, check=True: calls.append(args) or docker_runtime.DockerResult("cid\n", "", 0),
    )

    docker_runtime._start_nodehost(
        {"container_name": "nodehost-a", "nodehost_id": "nodehost-a", "ports": []},
        "network-a",
        "valkey:9.1",
        "local_full_flow",
        "local_full_flow",
        "run-1",
    )

    assert calls[0][:4] == ["run", "-d", "--init", "--name"]


def test_local_full_flow_fault_recovery_uses_one_strict_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    nodes = [{"logical_id": f"node-{index}"} for index in range(6)]

    def wait_snapshot(actual_nodes, **kwargs):
        captured["nodes"] = actual_nodes
        captured.update(kwargs)

    monkeypatch.setattr(docker_runtime, "_wait_process_snapshot_clean", wait_snapshot)

    docker_runtime._local_full_flow_wait_clean_cluster_snapshot(nodes, timeout=180.0)

    assert captured == {
        "nodes": nodes,
        "expected_nodes": 6,
        "expected_primaries": 3,
        "expected_replicas": 3,
        "timeout": 180.0,
    }


def test_local_full_flow_network_disconnect_reconnects_when_side_observation_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    recovered: list[tuple[int, float]] = []
    nodes = [
        {
            "logical_id": "target",
            "nodehost_container_name": "nodehost-a",
            "nodehost_container_ip": "172.18.0.2",
            "client_port": 7000,
        },
        {"logical_id": "survivor", "nodehost_container_name": "nodehost-b", "client_port": 7001},
    ]

    def run_docker(args: list[str], timeout: int = 120, check: bool = True) -> docker_runtime.DockerResult:
        calls.append(args)
        if args[0] == "inspect":
            return docker_runtime.DockerResult("{}\n", "", 0)
        return docker_runtime.DockerResult("", "", 0)

    monkeypatch.setattr(docker_runtime, "run_docker", run_docker)
    monkeypatch.setattr(
        docker_runtime,
        "_node_command",
        lambda node, *args, timeout: (_ for _ in ()).throw(DockerRuntimeError("side probe failed")),
    )
    monkeypatch.setattr(
        docker_runtime,
        "_local_full_flow_wait_clean_cluster_snapshot",
        lambda actual_nodes, timeout: recovered.append((len(actual_nodes), timeout)),
    )

    with pytest.raises(DockerRuntimeError, match="side probe failed"):
        docker_runtime._local_full_flow_network_disconnect_probe("owned-network", "nodehost-a", nodes, "network_partition")

    assert ["network", "connect", "--ip", "172.18.0.2", "owned-network", "nodehost-a"] in calls
    assert recovered == [(2, 180.0)]
