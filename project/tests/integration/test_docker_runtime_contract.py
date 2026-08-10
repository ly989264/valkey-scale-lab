from __future__ import annotations

import errno
import inspect
import json
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

from valkey_scale_lab.metrics import TelemetryRun
from valkey_scale_lab.observability.contracts import CollectionError, SemanticFailure
from valkey_scale_lab.runtime.command_recorder import classify_command_kind
from valkey_scale_lab.runtime import docker_runtime, teardown
from valkey_scale_lab.runtime.docker_runtime import DockerRuntimeError
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline, shared_monotonic


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

    backend = docker_runtime.DockerNodeBackend()
    config_details = docker_runtime._prepare_process_nodehost_bundles(
        backend=backend,
        nodes=nodes,
        nodehosts=nodehosts,
        nodehost_by_id=nodehost_by_id,
        artifacts=tmp_path,
        run_id=run_id,
    )
    start_details = docker_runtime._start_process_nodes_batched(backend=backend, nodes=nodes, nodehosts=nodehosts)
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

    backend = docker_runtime.DockerNodeBackend()
    docker_runtime._prepare_process_nodehost_bundles(
        backend=backend,
        nodes=nodes,
        nodehosts=nodehosts,
        nodehost_by_id=nodehost_by_id,
        artifacts=tmp_path,
        run_id=run_id,
        setup_timeline=timeline,
    )
    docker_runtime._start_process_nodes_batched(
        backend=backend, nodes=nodes, nodehosts=nodehosts, setup_timeline=timeline
    )

    names = [segment["name"] for segment in timeline.segments]
    assert "node_config_local_generate" in names
    assert "nodehost_bundle_write" in names
    assert "docker_cp_bundle" in names
    assert "nodehost_bundle_install" in names
    assert "nodehost_start_all" in names
    assert "pidfile_collect" in names


class RecordingNodeBackend:
    """A runtime that records the operations runtime_start asks of a backend."""

    def __init__(self, *, pids: dict[str, dict[str, int]] | None = None) -> None:
        self.operations: list[str] = []
        self.cluster_admin: list[list[str]] = []
        self.samplers: list[tuple[str, list, list]] = []
        self.pids = pids or {}
        self.kill_result = "OK"

    def verify_image(self, image: str) -> dict[str, object]:
        self.operations.append("verify_image")
        return {"status": "PASS"}

    def reclaim_run(self, *, capability_id: str, run_id: str) -> None:
        self.operations.append("reclaim_run")

    def create_network(self, *, network_name: str, capability_id: str, run_id: str) -> None:
        self.operations.append("create_network")

    def start_nodehost(
        self,
        nodehost: dict[str, object],
        *,
        network_name: str,
        image: str,
        capability_id: str,
        scenario: str,
        run_id: str,
    ) -> docker_runtime.NodehostAddress:
        self.operations.append("start_nodehost")
        return docker_runtime.NodehostAddress(handle="container-1", address="127.0.0.1")

    def send_bundle(self, nodehost: dict[str, object]) -> None:
        self.operations.append("send_bundle")

    def install_bundle(self, nodehost: dict[str, object]) -> None:
        self.operations.append("install_bundle")

    def start_node_processes(self, nodehost: dict[str, object]) -> None:
        self.operations.append("start_node_processes")

    def collect_node_pids(self, nodehost: dict[str, object]) -> dict[str, int]:
        self.operations.append("collect_node_pids")
        return self.pids.get(str(nodehost["nodehost_id"]), {})

    def wait_nodes_ready(self, nodes: list[dict[str, object]], *, timeout: float) -> None:
        self.operations.append("wait_nodes_ready")

    def client_host(self, node: dict[str, object]) -> str:
        self.operations.append("client_host")
        return "10.0.0.1"

    def run_cluster_admin(
        self,
        node: dict[str, object],
        argv: list[str],
        *,
        timeout: float,
        operation_id: str,
        record_node: dict[str, object] | None = None,
        command_kind: str | None = None,
    ) -> str:
        self.cluster_admin.append(list(argv))
        self.operations.append("run_cluster_admin")
        return "OK"

    def stop_node(self, node: dict[str, object], *, command_kind: str) -> list[dict[str, object]]:
        self.operations.append(f"stop_node:{node['logical_id']}")
        return [
            {
                "command_kind": f"{command_kind}_shutdown_nosave",
                "argv": ["docker", "exec", "recorded"],
                "started_at_unix_ms": 1,
                "ended_at_unix_ms": 2,
                "status": "PASS",
                "stdout_tail": "",
                "stderr_tail": "",
                "returncode": 0,
            }
        ]

    def start_node(
        self, node: dict[str, object], *, fresh_cluster_identity: bool
    ) -> tuple[int, list[dict[str, object]]]:
        self.operations.append(
            f"start_node:{node['logical_id']}:fresh={fresh_cluster_identity}"
        )
        return int(node.get("pid", 0)) + 1000, [
            {
                "command_kind": "owned_valkey_process_start",
                "argv": ["docker", "exec", "recorded"],
                "started_at_unix_ms": 3,
                "ended_at_unix_ms": 4,
                "status": "PASS",
                "stdout_tail": "",
                "stderr_tail": "",
                "returncode": 0,
            }
        ]

    def _fault(self, command_kind: str, action: str) -> list[dict[str, object]]:
        return [
            {
                "command_kind": command_kind,
                "action": action,
                "argv": ["recorded", command_kind],
                "result": "OK",
                "started_at_unix_ms": 5,
                "ended_at_unix_ms": 6,
                "status": "PASS",
                "stdout_tail": "",
                "stderr_tail": "",
                "returncode": 0,
            }
        ]

    def kill_node(self, node: dict[str, object]) -> list[dict[str, object]]:
        self.operations.append(f"kill_node:{node['logical_id']}")
        records = self._fault("actuator_kill_primary", f"recorded kill {node['logical_id']}")
        records[0]["argv"] = ["sh", "-c", f"kill -KILL {node.get('pid')}"]
        records[0]["result"] = self.kill_result
        return records

    def pause_node(self, node: dict[str, object]) -> list[dict[str, object]]:
        self.operations.append(f"pause_node:{node['logical_id']}")
        return self._fault("owned_valkey_process_pause", f"recorded pause {node['logical_id']}")

    def resume_node(self, node: dict[str, object]) -> list[dict[str, object]]:
        self.operations.append(f"resume_node:{node['logical_id']}")
        return self._fault("owned_valkey_process_resume", f"recorded resume {node['logical_id']}")

    def pause_nodehost(self, nodehost: dict[str, object]) -> list[dict[str, object]]:
        self.operations.append(f"pause_nodehost:{nodehost['nodehost_id']}")
        return self._fault("owned_nodehost_pause", f"recorded pause {nodehost['nodehost_id']}")

    def resume_nodehost(self, nodehost: dict[str, object]) -> list[dict[str, object]]:
        self.operations.append(f"resume_nodehost:{nodehost['nodehost_id']}")
        return self._fault("owned_nodehost_resume", f"recorded resume {nodehost['nodehost_id']}")

    def isolate_nodehost(self, nodehost: dict[str, object]) -> list[dict[str, object]]:
        self.operations.append(f"isolate_nodehost:{nodehost['nodehost_id']}")
        return self._fault("owned_nodehost_network_disconnect", f"recorded isolate {nodehost['nodehost_id']}")

    def rejoin_nodehost(self, nodehost: dict[str, object]) -> list[dict[str, object]]:
        self.operations.append(f"rejoin_nodehost:{nodehost['nodehost_id']}")
        return self._fault("owned_nodehost_network_connect", f"recorded rejoin {nodehost['nodehost_id']}")

    def resource_sampler(
        self,
        nodes: list[dict[str, object]],
        *,
        sampler_id: str,
        processes: object,
        expected_gone: object,
    ) -> object:
        self.operations.append(f"resource_sampler:{sampler_id}")
        self.samplers.append((sampler_id, list(processes), list(expected_gone)))
        return object()


def test_process_bootstrap_reaches_the_runtime_only_through_the_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/scale_10.yaml"))
    run_id = "scale_ladder-scale_10-20260628"
    nodes = docker_runtime._node_specs(config, "scale_ladder", "scale_10", run_id)
    nodehosts = docker_runtime._process_nodehosts(config, nodes, "scale_ladder", "scale_10", run_id)
    for index, nodehost in enumerate(nodehosts):
        nodehost["container_id"] = f"cid-{index}"
        nodehost["container_ip"] = f"172.18.0.{index + 2}"
    nodehost_by_id = {nodehost["nodehost_id"]: nodehost for nodehost in nodehosts}
    pids = {
        str(nodehost["nodehost_id"]): {
            str(node["logical_id"]): 5000 + offset
            for offset, node in enumerate(nodes)
            if node["nodehost_id"] == nodehost["nodehost_id"]
        }
        for nodehost in nodehosts
    }
    backend = RecordingNodeBackend(pids=pids)

    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("bundle install and process start must go through the backend")
        ),
    )
    monkeypatch.setattr(
        docker_runtime,
        "_bounded_parallel",
        lambda items, worker, **_kwargs: [worker(item) for item in list(items)],
    )

    docker_runtime._prepare_process_nodehost_bundles(
        backend=backend,
        nodes=nodes,
        nodehosts=nodehosts,
        nodehost_by_id=nodehost_by_id,
        artifacts=tmp_path,
        run_id=run_id,
    )
    docker_runtime._start_process_nodes_batched(backend=backend, nodes=nodes, nodehosts=nodehosts)

    # Every bundle is sent before any is installed, and every nodehost starts
    # before any pid is collected: that is what the four timeline segments of
    # this stage measure.
    barriers = [item for item in backend.operations if item != "client_host"]
    assert barriers == (
        ["send_bundle"] * len(nodehosts)
        + ["install_bundle"] * len(nodehosts)
        + ["start_node_processes"] * len(nodehosts)
        + ["collect_node_pids"] * len(nodehosts)
    )
    assert [node["pid"] for node in nodes] == [5000 + offset for offset in range(len(nodes))]
    # The endpoint this run connects to is the backend's to name, and it is not
    # the address the cluster announces. Nothing may default it to loopback.
    assert {node["host"] for node in nodes} == {"10.0.0.1"}
    assert {node["nodehost_container_ip"] for node in nodes} == {
        f"172.18.0.{index + 2}" for index in range(len(nodehosts))
    }


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

    # runtime_start owns no Docker call of its own: every one goes through the
    # backend seam, so a direct run_docker from the lifecycle is a failure.
    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("runtime_start must reach the runtime through the backend")
        ),
    )
    monkeypatch.setattr(docker_runtime, "_process_nodehosts", lambda *_args: nodehosts)
    monkeypatch.setattr(docker_runtime, "_write_nodehost_density_plan_artifact", lambda *_args: None)
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

    backend = RecordingNodeBackend()

    docker_runtime._create_process_scenario(
        backend=backend,
        capability_id=capability_id,
        scenario=scenario,
        run_id="real-path-test",
        config={"runtime": {"valkey_image": "valkey:test"}},
        artifacts=tmp_path,
        state_out=tmp_path / "state.json",
        nodes=nodes,
        profile_id="exact-50",
    )

    assert backend.operations == [
        "reclaim_run",
        "create_network",
        "start_nodehost",
        "wait_nodes_ready",
    ]
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
            "host": "127.0.0.1",
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
            "host": "127.0.0.1",
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
            "host": "127.0.0.1",
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

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True, **_kwargs) -> docker_runtime.DockerResult:
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

    def fake_create(primaries: list[dict], replicas: list[dict], timeout: float, **_kwargs) -> str:
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

    operations, snapshots = docker_runtime._configure_process_cluster(nodes, backend=RecordingNodeBackend())

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

    def fake_create(primaries: list[dict], replicas: list[dict], timeout: float, **_kwargs) -> str:
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

    monkeypatch.setattr(docker_runtime, "_management_cluster_health", light_health)
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

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True, **_kwargs) -> docker_runtime.DockerResult:
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

    docker_runtime._create_large_cluster(
        primaries, replicas, timeout=30, backend=docker_runtime.DockerNodeBackend()
    )

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

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True, **_kwargs) -> docker_runtime.DockerResult:
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

    docker_runtime._create_primary_cluster(
        primaries, timeout=30, backend=docker_runtime.DockerNodeBackend()
    )

    assert calls[0][:5] == ["exec", "nodehost-a", "valkey-cli", "--cluster", "create"]
    assert "172.18.0.2:7400" in calls[0]
    assert "172.18.0.3:7401" in calls[0]
    assert "172.18.0.2:6379" not in calls[0]


def test_primary_cluster_create_keeps_process_addresses_in_primary_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_docker(args: list[str], timeout: int = 120, check: bool = True, **_kwargs) -> docker_runtime.DockerResult:
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

    docker_runtime._create_primary_cluster(
        primaries, timeout=30, backend=docker_runtime.DockerNodeBackend()
    )

    address_start = calls[0].index("create") + 1
    addresses = calls[0][address_start : address_start + len(primaries)]
    assert addresses == [f"172.18.0.{2 + idx % 2}:{7400 + idx}" for idx in range(25)]


def test_default_primary_create_records_strategy_subtimings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VSLAB_CLUSTER_CREATE_STRATEGY", raising=False)
    monkeypatch.setattr(
        docker_runtime,
        "_create_primary_cluster",
        lambda primaries, timeout, backend: "cluster create OK",
    )
    monkeypatch.setattr(docker_runtime, "_wait_cluster_known", lambda *args, **kwargs: None)

    output, details = docker_runtime._create_primary_cluster_valkey_cli(
        [{"logical_id": "p0"}, {"logical_id": "p1"}],
        timeout=30,
        backend=RecordingNodeBackend(),
    )

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

    docker_runtime._create_large_cluster([{"logical_id": "p0"}], [], timeout=30, timings=timings, backend=RecordingNodeBackend())

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
    output = docker_runtime._create_large_cluster(primaries, replicas, timeout=30, timings=timings, backend=RecordingNodeBackend())

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


def _release_through_teardown(state: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    """Release `state` the way the Gate's cleanup step does.

    The state names its backend, because that is what teardown resolves on now -
    it no longer reads `runtime.type` itself. Driving the whole neutral path
    keeps these tests asserting the report a real cleanup writes, rather than a
    backend return value no artifact ever shows.
    """
    state = {"backend_id": "docker_process", **state}
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return teardown.cleanup_scenario(
        state_path=state_path,
        artifacts_dir=tmp_path,
        out_path=tmp_path / "cleanup.json",
    )


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

    report = _release_through_teardown(state, tmp_path)

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

    report = _release_through_teardown(state, tmp_path)

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


def test_backend_stop_node_uses_shell_builtin_for_term_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The image ships no kill binary, only the shell builtin.

    Stopping a node is the backend's now, so the mechanism is asserted where it
    lives. What the lifecycle still owns is the evidence: `stop_node` returns a
    record per command it ran, because those rows are compared against the
    frozen baseline.
    """
    calls: list[list[str]] = []
    gone = iter([False, True])

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run_docker(args: list[str], **_kwargs: Any) -> Any:
        calls.append(list(args))
        return Result()

    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    monkeypatch.setattr(
        docker_runtime,
        "_wait_container_pid_gone",
        lambda *_args, **_kwargs: next(gone),
    )

    records = docker_runtime.DockerNodeBackend().stop_node(
        {
            "logical_id": "node-a",
            "nodehost_container_name": "nodehost-a",
            "pid": 101,
            "client_port": 7000,
        },
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
    assert [record["command_kind"] for record in records] == [
        "owned_valkey_process_stop_shutdown_nosave",
        "owned_valkey_process_stop_kill_term_fallback",
    ]
    assert [record["argv"][:2] for record in records] == [["docker", "exec"]] * 2
    assert {record["status"] for record in records} == {"PASS"}



def test_kill_primary_actuator_signals_through_the_shell(monkeypatch) -> None:
    """The image ships no kill binary, only the shell builtin.

    `docker exec <container> kill ...` therefore exits 127 and the primary is
    never killed, so the fault is recorded as failing to execute. Every other
    signal this backend sends already goes through `sh -c`; this one must too.
    """
    calls: list[list[str]] = []

    def fake_run_docker(args, **_kwargs):
        calls.append(list(args))
        return docker_runtime.DockerResult("", "", 0)

    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    monkeypatch.setattr(
        docker_runtime, "_wait_container_pid_gone", lambda *_a, **_k: True
    )

    records = docker_runtime.DockerNodeBackend().kill_node(
        {"nodehost_container_name": "nodehost-a", "pid": 101, "logical_id": "shard-0000-primary"}
    )

    assert calls == [["exec", "nodehost-a", "sh", "-c", "kill -KILL 101"]]
    # A bare exec of the binary is what fails with 127.
    assert calls[0][2] != "kill"
    # The evidence names the signal, not the transport that carried it, and
    # §9.1 requires a result the actuator can record.
    assert records[0]["argv"] == ["sh", "-c", "kill -KILL 101"]
    assert records[0]["result"] == "OK"
    assert records[0]["status"] == "PASS"


def test_kill_node_reports_a_surviving_process_instead_of_raising(monkeypatch) -> None:
    """§9.1: an actuator that could not act is a tool error, not a verdict.

    So the backend reports what happened and the fault lane decides what it
    means. Swallowing it into an exception here would take the choice away
    from the only layer that owns `OK/FAIL/ERROR`.
    """
    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        lambda args, **_kwargs: docker_runtime.DockerResult("", "no such process", 1),
    )
    monkeypatch.setattr(
        docker_runtime, "_wait_container_pid_gone", lambda *_a, **_k: False
    )

    records = docker_runtime.DockerNodeBackend().kill_node(
        {"nodehost_container_name": "nodehost-a", "pid": 101, "logical_id": "shard-0000-primary"}
    )

    assert records[0]["result"] == "returncode=1, process_gone=False"
    assert records[0]["status"] == "FAIL"


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

    started = docker_runtime.DockerNodeBackend().start_nodehost(
        {"container_name": "nodehost-a", "nodehost_id": "nodehost-a", "ports": []},
        network_name="network-a",
        image="valkey:9.1",
        capability_id="local_full_flow",
        scenario="local_full_flow",
        run_id="run-1",
    )

    assert calls[0][:4] == ["run", "-d", "--init", "--name"]
    assert started.handle == "cid"


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
        # Still one strict snapshot: exact counts, full slot coverage and node
        # health. Only the original role plan is dropped, because the
        # management matrix and the failover have already moved roles by the
        # time a partition is healed.
        "validation_options": {"require_plan_roles": False},
    }


def test_local_full_flow_network_disconnect_reconnects_when_side_observation_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    recovered: list[tuple[int, float]] = []
    nodes = [
        {
            "logical_id": "target",
            "nodehost_id": "nodehost-a",
            "nodehost_container_name": "nodehost-a",
            "nodehost_container_ip": "172.18.0.2",
            "client_port": 7000,
        },
        {"logical_id": "survivor", "nodehost_id": "nodehost-b", "nodehost_container_name": "nodehost-b", "client_port": 7001},
    ]
    nodehost = {
        "nodehost_id": "nodehost-a",
        "container_name": "nodehost-a",
        "container_ip": "172.18.0.2",
        "network_name": "owned-network",
    }

    def run_docker(args: list[str], timeout: int = 120, check: bool = True) -> docker_runtime.DockerResult:
        calls.append(args)
        if args[0] == "inspect":
            return docker_runtime.DockerResult("{}\n", "", 0)
        return docker_runtime.DockerResult("", "", 0)

    monkeypatch.setattr(docker_runtime, "run_docker", run_docker)
    monkeypatch.setattr(
        docker_runtime,
        "_node_host_command",
        lambda node, *args, timeout: (_ for _ in ()).throw(DockerRuntimeError("side probe failed")),
    )
    monkeypatch.setattr(
        docker_runtime,
        "_local_full_flow_wait_clean_cluster_snapshot",
        lambda actual_nodes, timeout: recovered.append((len(actual_nodes), timeout)),
    )

    # Neither side answers, so the scenario cannot reach a verdict - but the
    # owned network must be reconnected and the cluster waited on regardless.
    with pytest.raises(DockerRuntimeError, match="recovery probe did not succeed"):
        docker_runtime._local_full_flow_network_disconnect_probe(
            nodehost, nodes, "network_partition", backend=docker_runtime.DockerNodeBackend()
        )

    assert ["network", "connect", "--ip", "172.18.0.2", "owned-network", "nodehost-a"] in calls
    assert recovered == [(2, 180.0)]


def test_partition_probe_reads_the_isolated_side_only_from_this_side_of_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreachable isolated node is fail-closed, and is not chased with docker exec.

    Measured on a real partition: the host path to the isolated node timed out
    for 33s while `_node_command`'s `docker exec valkey-cli` fallback answered
    `cluster_state:ok` from inside the container. The scenario was judging an
    isolated node by a path that bypasses the isolation.
    """
    nodes = [
        {
            "logical_id": "isolated",
            "nodehost_id": "nodehost-a",
            "nodehost_container_name": "nodehost-a",
            "nodehost_container_ip": "172.18.0.2",
            "client_port": 7000,
        },
        {"logical_id": "majority", "nodehost_id": "nodehost-b", "nodehost_container_name": "nodehost-b", "client_port": 7001},
    ]
    nodehost = {
        "nodehost_id": "nodehost-a",
        "container_name": "nodehost-a",
        "container_ip": "172.18.0.2",
        "network_name": "owned-network",
    }
    reconnected: list[bool] = []

    def run_docker(args: list[str], **_kwargs: Any) -> docker_runtime.DockerResult:
        if args[0] == "inspect":
            return docker_runtime.DockerResult("{}\n", "", 0)
        if args[:2] == ["network", "connect"]:
            reconnected.append(True)
        return docker_runtime.DockerResult("", "", 0)

    def host_command(node: dict[str, Any], *args: Any, timeout: float) -> str:
        if node["logical_id"] == "isolated" and not reconnected:
            raise TimeoutError("timed out")
        if args == ("PING",):
            return "PONG"
        return "cluster_state:ok\ncluster_known_nodes:2\n"

    def forbidden(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("the partition probe must not reach a node through docker exec")

    monkeypatch.setattr(docker_runtime, "run_docker", run_docker)
    monkeypatch.setattr(docker_runtime, "_node_host_command", host_command)
    monkeypatch.setattr(docker_runtime, "_node_command", forbidden)
    monkeypatch.setattr(docker_runtime, "run_node_cli", forbidden)
    monkeypatch.setattr(
        docker_runtime,
        "_local_full_flow_wait_clean_cluster_snapshot",
        lambda *_args, **_kwargs: None,
    )

    for scenario_id in ("minority_majority", "split_brain_detection"):
        reconnected.clear()
        details = docker_runtime._local_full_flow_network_disconnect_probe(
            nodehost, nodes, scenario_id, backend=docker_runtime.DockerNodeBackend()
        )
        assert details["majority_cluster_state_ok"] is True
        assert details["isolated_cluster_state_ok"] is False
        assert details["isolated_reachable_from_this_side"] is False
        assert "TimeoutError" in details["isolated_unreachable_reason"]
        isolated = next(row for row in details["client_observations"] if row["side"] == "isolated")
        assert isolated["success"] is False
        # The observation validator is the other consumer of these fields, and
        # it has to accept unreachable-with-a-reason as an observation too.
        docker_runtime._local_full_flow_validate_fault_probe_observation(scenario_id, details)


def test_fault_probe_validator_rejects_an_isolated_side_with_neither_answer_nor_reason() -> None:
    details = {
        "actions": ["docker network disconnect owned-network nodehost-a"],
        "disconnect_verified": True,
        "majority_cluster_state_ok": True,
        "isolated_cluster_state_ok": False,
        "isolated_reachable_from_this_side": False,
        "isolated_unreachable_reason": "",
        "majority_cluster_info": "cluster_state:ok",
        "isolated_cluster_info": "",
        "client_observations": [{"side": "majority", "success": True, "latency_ms": 1.0}],
        "recovery_verified": True,
    }

    with pytest.raises(DockerRuntimeError, match="neither an isolated-side observation nor a reason"):
        docker_runtime._local_full_flow_validate_fault_probe_observation("network_partition", details)


def _cluster_form_nodes(shards: int) -> list[dict[str, object]]:
    """Nodes as runtime_start leaves them: a client host and a peer address."""
    nodes: list[dict[str, object]] = []
    for role, suffix in (("primary", "primary"), ("replica", "replica-00")):
        for idx in range(shards):
            nodes.append(
                {
                    "logical_id": f"shard-{idx:04d}-{suffix}",
                    "role": role,
                    "shard_id": f"shard-{idx:04d}",
                    "az_id": "az-a" if idx % 2 == 0 else "az-b",
                    "host": "10.0.0.1",
                    "client_port": 7400 + idx + (1000 if role == "replica" else 0),
                    "container_name": f"nodehost-{idx % 2}",
                    "nodehost_container_name": f"nodehost-{idx % 2}",
                    "nodehost_container_ip": f"172.18.0.{2 + idx % 2}",
                }
            )
    return nodes


def _silence_cluster_form_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer the RESP layer so the stage's own structure is what is measured."""
    for name in (
        "_wait_process_known",
        "_wait_process_slots_assigned",
        "_wait_process_cluster_ok",
        "_wait_process_role_counts",
        "_wait_process_snapshot_clean",
        "_wait_cluster_known",
        "_add_slots_node",
        "_replicate_process_nodes_parallel",
    ):
        monkeypatch.setattr(docker_runtime, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_tree_fanout_meet_nodes", lambda *args, **kwargs: 3)
    monkeypatch.setattr(
        docker_runtime,
        "_cluster_node_ids_by_shard",
        lambda nodes, **kwargs: {str(node["shard_id"]): f"id-{node['logical_id']}" for node in nodes},
    )
    monkeypatch.setattr(
        docker_runtime,
        "_configure_large_cluster_replicas_with_diagnostics",
        lambda primaries, replicas, timeout: ("replicas OK", {}),
    )
    monkeypatch.setattr(
        docker_runtime,
        "_process_cluster_summary",
        lambda label, sampled, **kwargs: {"label": label, "samples": []},
    )
    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cluster_form must reach the runtime only through the backend")
        ),
    )


def test_cluster_form_small_branch_segments_and_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """At or below thirty nodes the stage assigns slots itself and never creates."""
    _silence_cluster_form_probes(monkeypatch)
    timeline = SetupTimeline(clock=iter(float(tick) for tick in range(1, 200)).__next__)
    backend = RecordingNodeBackend()

    docker_runtime._configure_process_cluster(
        _cluster_form_nodes(3), setup_timeline=timeline, backend=backend
    )

    assert [segment["name"] for segment in timeline.segments if segment["kind"] == "span"] == [
        "primary_cluster_create",
        "cluster_slots_assign",
        "replica_meet",
        "replica_replicate",
        "cluster_final_full_snapshot",
    ]
    assert {segment["category"] for segment in timeline.segments if segment["kind"] == "span"} == {
        "cluster_formation"
    }
    # This branch forms the cluster by RESP alone, so it asks the backend for
    # nothing at all. cluster_convergence_wait and cluster_final_snapshot are
    # the large branch's, and REQUIRED_SETUP_SEGMENTS asks for both.
    assert backend.operations == []


def test_cluster_form_large_branch_segments_and_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Above thirty nodes the stage creates the cluster through the backend."""
    monkeypatch.delenv("VSLAB_CLUSTER_CREATE_STRATEGY", raising=False)
    _silence_cluster_form_probes(monkeypatch)
    timeline = SetupTimeline(clock=iter(float(tick) for tick in range(1, 200)).__next__)
    backend = RecordingNodeBackend()
    nodes = _cluster_form_nodes(20)

    docker_runtime._configure_process_cluster(nodes, setup_timeline=timeline, backend=backend)

    assert [segment["name"] for segment in timeline.segments if segment["kind"] == "span"] == [
        "primary_cluster_create",
        "replica_meet",
        "replica_replicate",
        "cluster_convergence_wait",
        "cluster_final_snapshot",
        "cluster_final_full_snapshot",
    ]
    assert backend.operations == ["run_cluster_admin"]
    argv = backend.cluster_admin[0]
    assert argv[:2] == ["--cluster", "create"]
    assert argv[-1] == "--cluster-yes"
    # The addresses handed to cluster create are the peer addresses the cluster
    # announces, never the client host this run connects to.
    assert argv[2:-1] == [
        f"172.18.0.{2 + idx % 2}:{7400 + idx}" for idx in range(20)
    ]
    assert not any(address.startswith("10.0.0.1") for address in argv[2:-1])


def _management_nodes(node_count: int) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for shard_index in range(node_count // 2):
        shard_id = f"shard-{shard_index:04d}"
        for role in ("primary", "replica"):
            logical_id = f"{shard_id}-{role}"
            nodes.append(
                {
                    "logical_id": logical_id,
                    "role": role,
                    "shard_id": shard_id,
                    "az_id": f"az-{shard_index % 3}",
                    "host": "127.0.0.1",
                    "client_port": 7000 + len(nodes),
                    "pid": 100 + len(nodes),
                    "nodehost_id": f"nodehost-{shard_index % 2}",
                    "nodehost_container_id": f"cid-{shard_index % 2}",
                    "nodehost_container_name": f"nodehost-{shard_index % 2}",
                    "nodehost_container_ip": f"172.18.0.{2 + shard_index % 2}",
                    "container_name": f"nodehost-{shard_index % 2}",
                    "data_dir": f"/tmp/{logical_id}",
                    "config_file": f"/tmp/{logical_id}.conf",
                    "pid_file": f"/tmp/{logical_id}.pid",
                }
            )
    return nodes


def _no_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("management_matrix must reach the runtime only through the backend")
        ),
    )


def test_rolling_restart_stops_and_starts_each_node_through_the_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pair the rolling restart does run back to back, and its evidence.

    The 212 `docker` rows this stage writes at exact-50 all come from here, so
    the backend returning records rather than logging them is what keeps them
    in `management_command_log.jsonl`.
    """
    _no_runtime(monkeypatch)
    nodes = _management_nodes(4)
    backend = RecordingNodeBackend()
    command_rows: list[dict[str, Any]] = []

    result = docker_runtime._management_matrix_restart_process_target(
        entry={"sequence": 1},
        target=nodes[0],
        telemetry=_recording_telemetry(),
        capability_id="local_full_flow",
        run_id="slice-3",
        operation_id="restart-1",
        backend=backend,
    )
    docker_runtime._management_matrix_merge_parallel_command_rows(
        command_rows, result.pop("command_rows")
    )

    assert backend.operations == [
        "stop_node:shard-0000-primary",
        "start_node:shard-0000-primary:fresh=False",
    ]
    # A restart's evidence is that the pid changed, and both commands are named.
    assert result["process_pid_before"] == 100
    assert result["process_pid_after"] == 1100
    assert nodes[0]["pid"] == 1100
    assert [row["command_kind"] for row in command_rows] == [
        "owned_valkey_process_restart_stop_shutdown_nosave",
        "owned_valkey_process_start",
    ]
    assert [row["command_id"] for row in command_rows] == [
        "restart-1-cmd-0001",
        "restart-1-cmd-0002",
    ]
    assert {row["target_logical_id"] for row in command_rows} == {"shard-0000-primary"}


def test_remove_and_restore_separates_stop_from_start_across_the_forget_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Why `stop_node` and `start_node` are two operations and not `restart_node`.

    Between them this row forgets the node on every survivor and waits for the
    cluster to be clean without it. A fused restart could not express that.
    """
    _no_runtime(monkeypatch)
    nodes = _management_nodes(4)
    backend = RecordingNodeBackend()
    order: list[str] = []

    monkeypatch.setattr(
        docker_runtime,
        "_management_live_topology",
        lambda probe_nodes: (
            {node["logical_id"]: {"role": node["role"]} for node in nodes},
            {},
        ),
    )
    monkeypatch.setattr(docker_runtime, "_node_command", lambda *_a, **_k: "node-id-1")
    monkeypatch.setattr(
        docker_runtime,
        "_management_forget_until_absent",
        lambda **_kwargs: order.append("forget_until_absent"),
    )
    monkeypatch.setattr(docker_runtime, "_management_removed_absent", lambda *_a: True)
    monkeypatch.setattr(
        docker_runtime, "_management_matrix_rejoin_as_replica", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        docker_runtime, "_management_wait_clean_cluster", lambda *_a, **_k: None
    )

    original_stop = backend.stop_node
    original_start = backend.start_node
    backend.stop_node = lambda node, **kw: (order.append("stop"), original_stop(node, **kw))[1]
    backend.start_node = lambda node, **kw: (order.append("start"), original_start(node, **kw))[1]

    row = docker_runtime._management_matrix_remove_and_restore_row(
        _recording_telemetry(),
        "local_full_flow",
        "slice-3",
        "remove_replica",
        "remove-1",
        nodes,
        [],
        backend,
    )

    assert order == ["stop", "forget_until_absent", "start"]
    assert row["operation_status"] == "PASS"


def test_bounded_stability_asks_the_backend_for_one_sampler_per_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§11.1 puts one long-lived sampler on each host; §15 makes deploying it
    the adapter's job. Which nodes share a host is inventory, and `nodehost_id`
    names it without naming a container."""
    _no_runtime(monkeypatch)
    nodes = _management_nodes(8)
    backend = RecordingNodeBackend()

    runners = docker_runtime._resource_runners_for_nodes(
        nodes,
        backend=backend,
        expected_gone_processes=[{"logical_id": nodes[0]["logical_id"], "pid": nodes[0]["pid"]}],
    )

    assert len(runners) == 2
    assert backend.operations == ["resource_sampler:nodehost-0", "resource_sampler:nodehost-1"]
    first_id, first_processes, first_expected_gone = backend.samplers[0]
    assert first_id == "nodehost-0"
    assert first_processes == [
        ("shard-0000-primary", 100),
        ("shard-0000-replica", 101),
        ("shard-0002-primary", 104),
        ("shard-0002-replica", 105),
    ]
    # The expected-gone process is only handed to the host that runs it.
    assert first_expected_gone == [("shard-0000-primary", 100)]
    assert backend.samplers[1][2] == []


def test_management_workload_reaches_the_cluster_through_the_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The workload beside each operation follows a MOVED, so it needs a client
    inside the cluster network - which is `run_cluster_admin`, not a Docker
    call the stage makes itself. Its recorded attribution is unchanged."""
    _no_runtime(monkeypatch)
    nodes = _management_nodes(2)
    backend = RecordingNodeBackend()
    recorded: list[dict[str, Any]] = []

    def run_cluster_admin(node, argv, **kwargs):
        recorded.append({"argv": list(argv), **kwargs})
        return "OK" if "SET" in argv else "value"

    backend.run_cluster_admin = run_cluster_admin
    monkeypatch.setattr(
        docker_runtime, "_management_topology_snapshot", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(
        docker_runtime,
        "_management_matrix_execute_operation",
        lambda **_kwargs: ({"operation_status": "PASS", "real_execution_verified": True}, {}),
    )

    docker_runtime._management_matrix_run_operation_with_workload(
        telemetry=_recording_telemetry(),
        capability_id="local_full_flow",
        run_id="slice-3",
        scenario="local_full_flow",
        operation_name="reshard_slot_range",
        operation_id="workload-1",
        nodes=nodes,
        command_log=[],
        backend=backend,
    )

    assert recorded, "the workload must run"
    first = recorded[0]
    assert first["argv"][:3] == ["-c", "-p", str(nodes[0]["client_port"])]
    assert first["operation_id"] == "cluster_setup"
    assert first["record_node"] is nodes[0]
    # The classification is taken from the Valkey command words, as
    # run_node_cluster_cli took it, and not from the docker argv around them.
    assert first["command_kind"] == classify_command_kind(["valkey-cli", *first["argv"][3:]])


def _recording_telemetry() -> TelemetryRun:
    return TelemetryRun(
        capability_id="local_full_flow",
        scenario_name="local_full_flow",
        run_id="slice-3",
        coverage_id="4.management.slice-3",
        scale=4,
        node_count=4,
    )


def test_an_error_reply_is_the_node_s_answer_and_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `-ERR` must not be re-sent down a second transport.

    Measured once at exact-50: a `CLUSTER REPLICATE` that had already taken
    effect was re-run through `docker exec`, the second attempt replied
    `ERR ... must be empty`, and because docker exited 0 the lifecycle stored a
    failed Valkey command as `status: PASS` and raised nothing. Every command
    this path carries - REPLICATE, FAILOVER, FORGET, SETSLOT, MIGRATE - changes
    state when it runs, so a retry is not free either.
    """
    node = {
        "logical_id": "node-a",
        "host": "127.0.0.1",
        "client_port": 7000,
        "nodehost_container_name": "nodehost-a",
        "runtime_type": "docker_process",
    }
    monkeypatch.setattr(
        docker_runtime,
        "_node_host_command",
        lambda *_a, **_k: (_ for _ in ()).throw(
            docker_runtime.ValkeyErrorReply(
                "ERR To set a master the node must be empty and without assigned slots."
            )
        ),
    )
    monkeypatch.setattr(
        docker_runtime,
        "run_node_cli",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("an error reply must not be re-executed through docker exec")
        ),
    )

    with pytest.raises(docker_runtime.DockerRuntimeError, match="must be empty"):
        docker_runtime._node_command(node, "CLUSTER", "REPLICATE", "abc")

    # and the lifecycle records it as the failure it is
    class Telemetry:
        def now_unix_ms(self) -> int:
            return 0

    log: list[dict[str, Any]] = []
    with pytest.raises(docker_runtime.DockerRuntimeError):
        docker_runtime._management_log_node_command(
            log,
            telemetry=Telemetry(),
            capability_id="local_full_flow",
            parent_run_id="r",
            operation_id="op",
            command_kind="cluster_replicate_restored_node",
            target=node,
            args=["CLUSTER", "REPLICATE", "abc"],
            timeout=60,
        )
    assert log[0]["status"] == "FAIL"


def test_forget_of_an_unknown_node_is_tolerated_now_that_it_is_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_management_log_forget_removed_node` has always meant to tolerate
    `ERR Unknown node`, and every survivor is asked to forget in each round, so
    it happens routinely. The swallow made that handler unreachable: the error
    arrived as a passing stdout instead of an exception."""
    node = {
        "logical_id": "node-a",
        "host": "127.0.0.1",
        "client_port": 7000,
        "nodehost_container_name": "nodehost-a",
        "runtime_type": "docker_process",
    }
    monkeypatch.setattr(
        docker_runtime,
        "_node_host_command",
        lambda *_a, **_k: (_ for _ in ()).throw(
            docker_runtime.ValkeyErrorReply("ERR Unknown node abc123")
        ),
    )
    monkeypatch.setattr(
        docker_runtime,
        "run_node_cli",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no docker exec")),
    )

    class Telemetry:
        def now_unix_ms(self) -> int:
            return 0

    log: list[dict[str, Any]] = []
    row = docker_runtime._management_log_forget_removed_node(
        log,
        telemetry=Telemetry(),
        capability_id="local_full_flow",
        parent_run_id="r",
        operation_id="op",
        target=node,
        removed_id="abc123",
    )
    assert row["status"] == "PASS"


def test_being_unable_to_reach_a_node_is_the_answer_not_a_docker_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The boundary, asserted so it stays a decision rather than an accident.

    This test used to assert the opposite. The `docker exec` fallback for
    transport failures is gone: §16.2 forbids reaching a node's protocol that
    way, 85d5096a caught it answering for a node the scenario had just
    partitioned away, and with the recorder installed it was measured firing
    four times in a passing exact-200 - all four in `start_node`'s own 30s
    readiness retry, which catches the failure and asks again anyway.
    """
    node = {
        "logical_id": "node-a",
        "host": "127.0.0.1",
        "client_port": 7000,
        "nodehost_container_name": "nodehost-a",
        "runtime_type": "docker_process",
    }
    monkeypatch.setattr(
        docker_runtime,
        "_node_host_command",
        lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("timed out")),
    )

    def unreachable_by_docker(*_a: Any, **_k: Any) -> str:
        raise AssertionError("a transport failure must not be retried through docker exec")

    monkeypatch.setattr(docker_runtime, "run_node_cli", unreachable_by_docker)

    with pytest.raises(TimeoutError, match="timed out"):
        docker_runtime._node_command(node, "PING")


def test_an_error_reply_still_propagates_and_is_still_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """c3bd05fc's semantics, unchanged by the fallback's removal.

    A node that answered with an error and a node that could not be reached now
    take the same path out; this pins that the error reply is still the thing
    raised, rather than being flattened into a transport failure or re-run.
    """
    node = {
        "logical_id": "node-a",
        "host": "127.0.0.1",
        "client_port": 7000,
        "nodehost_container_name": "nodehost-a",
        "runtime_type": "docker_process",
    }
    monkeypatch.setattr(
        docker_runtime,
        "_node_host_command",
        lambda *_a, **_k: (_ for _ in ()).throw(
            docker_runtime.ValkeyErrorReply("ERR Unknown node abc")
        ),
    )

    def unreachable_by_docker(*_a: Any, **_k: Any) -> str:
        raise AssertionError("an error reply must not be re-run through docker exec")

    monkeypatch.setattr(docker_runtime, "run_node_cli", unreachable_by_docker)

    with pytest.raises(docker_runtime.ValkeyErrorReply, match="Unknown node"):
        docker_runtime._node_command(node, "PING")


def test_a_node_with_no_client_endpoint_is_not_the_removed_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one `run_node_cli` call left in `_node_response`, pinned as distinct.

    It is reached only when the node carries no `client_port` at all - there is
    no endpoint to fail over *from* - which is a different question from
    retrying a reachable endpoint's failure, and it keeps its own evidence.
    """
    monkeypatch.setattr(docker_runtime, "run_node_cli", lambda *_a, **_k: "PONG")
    monkeypatch.setattr(
        docker_runtime,
        "_node_host_command",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("no client endpoint means the host path is not attempted")
        ),
    )

    assert docker_runtime._node_command({"logical_id": "node-a"}, "PING") == "PONG"


def test_reshard_drains_every_key_from_a_slot_before_reassigning_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valkey refuses SETSLOT NODE while a node still holds keys for the slot.

    The reshard used to migrate only the keys it planted itself, and only for
    the row that plants any, so a workload key landing in a moved slot made the
    reassignment fail. Measured at exact-50 as `ERR Can't assign hashslot 0 to
    a different node while I still hold keys for this hash slot.`
    """
    source = {
        "logical_id": "shard-0000-primary",
        "host": "127.0.0.1",
        "client_port": 7000,
        "nodehost_container_name": "nodehost-a",
    }
    target = {
        "logical_id": "shard-0001-primary",
        "nodehost_container_ip": "172.18.0.5",
        "client_port": 7401,
    }
    batches = [["{wl-a}:k", "{wl-b}:k"], ["{seeded}:k"], []]
    monkeypatch.setattr(docker_runtime, "_node_response", lambda *_a, **_k: batches.pop(0))
    monkeypatch.setattr(docker_runtime, "_node_command", lambda *_a, **_k: "OK")

    class Telemetry:
        def now_unix_ms(self) -> int:
            return 0

    log: list[dict[str, Any]] = []
    moved = docker_runtime._management_reshard_drain_slot(
        log, Telemetry(), "local_full_flow", "r", "op", source=source, target=target, slot=0
    )

    # It keeps going until the slot reports empty, not until its own key moved.
    assert moved == 3
    assert [row["command_kind"] for row in log] == ["cluster_migrate_keys"] * 2
    assert log[0]["argv"] == [
        "MIGRATE", "172.18.0.5", "7401", "", "0", "5000", "KEYS", "{wl-a}:k", "{wl-b}:k",
    ]


def test_reshard_drain_of_an_empty_slot_logs_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slot with no keys must cost no command row, so a run whose slots are
    empty records exactly what it recorded before the drain existed - which is
    what keeps the artifact diff against the frozen baseline meaningful."""
    monkeypatch.setattr(docker_runtime, "_node_response", lambda *_a, **_k: [])

    class Telemetry:
        def now_unix_ms(self) -> int:
            return 0

    log: list[dict[str, Any]] = []
    moved = docker_runtime._management_reshard_drain_slot(
        log,
        Telemetry(),
        "local_full_flow",
        "r",
        "op",
        source={"logical_id": "s", "client_port": 7000},
        target={"logical_id": "t", "nodehost_container_ip": "172.18.0.5", "client_port": 7401},
        slot=1,
    )

    assert moved == 0
    assert log == []


def test_reshard_drain_gives_up_rather_than_looping_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slot that never empties is a defect, not a reason to spin."""
    monkeypatch.setattr(docker_runtime, "_node_response", lambda *_a, **_k: ["{x}:k"])
    monkeypatch.setattr(docker_runtime, "_node_command", lambda *_a, **_k: "OK")

    class Telemetry:
        def now_unix_ms(self) -> int:
            return 0

    with pytest.raises(docker_runtime.DockerRuntimeError, match="still held keys"):
        docker_runtime._management_reshard_drain_slot(
            [],
            Telemetry(),
            "local_full_flow",
            "r",
            "op",
            source={"logical_id": "s", "client_port": 7000},
            target={"logical_id": "t", "nodehost_container_ip": "172.18.0.5", "client_port": 7401},
            slot=2,
        )


def _fault_stage_nodes() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Two AZs, one nodehost each - the smallest topology the stage accepts.

    `az_stop` needs a node outside the target AZ and the partition scenarios
    need a node on another host, so a single-AZ inventory cannot reach either.
    """
    nodes = [
        {
            "logical_id": "shard-0000-primary",
            "shard_id": "0",
            "role": "primary",
            "az_id": "az-a",
            "nodehost_id": "nodehost-az-a-00",
            "nodehost_container_name": "host-a",
            "nodehost_container_ip": "172.18.0.2",
            "client_port": 7000,
            "pid": 101,
            "effective_cluster_node_timeout_ms": 1,
        },
        {
            "logical_id": "shard-0000-replica-00",
            "shard_id": "0",
            "role": "replica",
            "az_id": "az-b",
            "nodehost_id": "nodehost-az-b-00",
            "nodehost_container_name": "host-b",
            "nodehost_container_ip": "172.18.0.3",
            "client_port": 7001,
            "pid": 102,
            "effective_cluster_node_timeout_ms": 1,
        },
    ]
    nodehosts = [
        {"nodehost_id": "nodehost-az-a-00", "container_name": "host-a", "container_ip": "172.18.0.2", "network_name": "owned-network"},
        {"nodehost_id": "nodehost-az-b-00", "container_name": "host-b", "container_ip": "172.18.0.3", "network_name": "owned-network"},
    ]
    return nodes, nodehosts


def _forbid_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_docker(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the fault stage must not reach Docker outside the backend")

    monkeypatch.setattr(docker_runtime, "run_docker", raise_docker)
    monkeypatch.setattr(docker_runtime, "run_node_cluster_cli", raise_docker)
    monkeypatch.setattr(docker_runtime, "run_node_cli", raise_docker)


def test_fault_process_pause_probe_suspends_and_resumes_through_the_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`replica_stop` freezes a node in place and lists what it did.

    The action strings used to be written here in Docker's vocabulary, before
    the actions were taken. They now come from the backend, in the order the
    calls ran, so a second backend describes its own actuator.
    """
    nodes, _ = _fault_stage_nodes()
    _forbid_docker(monkeypatch)
    monkeypatch.setattr(docker_runtime, "_node_command", lambda *_a, **_k: "cluster_state:ok\n")
    monkeypatch.setattr(docker_runtime, "_management_wait_clean_cluster", lambda *_a, **_k: None)
    backend = RecordingNodeBackend()

    details = docker_runtime._local_full_flow_process_pause_probe(
        nodes[1], nodes[0], nodes, backend=backend
    )

    assert backend.operations == [
        "pause_node:shard-0000-replica-00",
        "resume_node:shard-0000-replica-00",
    ]
    assert details["actions"] == [
        "recorded pause shard-0000-replica-00",
        "recorded resume shard-0000-replica-00",
    ]
    assert details["target_logical_id"] == "shard-0000-replica-00"


def test_fault_process_pause_probe_resumes_when_the_observation_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A suspended node left suspended is residue, so the resume is a finally."""
    nodes, _ = _fault_stage_nodes()
    _forbid_docker(monkeypatch)
    monkeypatch.setattr(
        docker_runtime,
        "_node_command",
        lambda *_a, **_k: (_ for _ in ()).throw(DockerRuntimeError("probe failed")),
    )
    monkeypatch.setattr(docker_runtime, "_management_wait_clean_cluster", lambda *_a, **_k: None)
    backend = RecordingNodeBackend()

    with pytest.raises(DockerRuntimeError, match="probe failed"):
        docker_runtime._local_full_flow_process_pause_probe(
            nodes[1], nodes[0], nodes, backend=backend
        )

    assert backend.operations[-1] == "resume_node:shard-0000-replica-00"


def test_fault_az_pause_probe_resumes_in_reverse_and_only_what_it_paused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case a scoped pause could not express.

    N hosts suspended in order and resumed in reverse, and if the third pause
    fails only the two that took effect are resumed - which is why pause and
    resume are separate operations rather than one scope.
    """
    nodes, _ = _fault_stage_nodes()
    _forbid_docker(monkeypatch)
    monkeypatch.setattr(docker_runtime, "_node_command", lambda *_a, **_k: "cluster_state:ok\n")
    monkeypatch.setattr(docker_runtime, "_management_wait_clean_cluster", lambda *_a, **_k: None)
    hosts = [
        {"nodehost_id": f"nodehost-az-a-{index:02d}", "container_name": f"host-{index}"}
        for index in range(3)
    ]
    backend = RecordingNodeBackend()

    details = docker_runtime._local_full_flow_az_pause_probe(hosts, nodes[1], nodes, backend=backend)

    assert backend.operations == [
        "pause_nodehost:nodehost-az-a-00",
        "pause_nodehost:nodehost-az-a-01",
        "pause_nodehost:nodehost-az-a-02",
        "resume_nodehost:nodehost-az-a-02",
        "resume_nodehost:nodehost-az-a-01",
        "resume_nodehost:nodehost-az-a-00",
    ]
    assert details["target_containers"] == ["host-0", "host-1", "host-2"]
    assert details["actions"][:3] == [
        "recorded pause nodehost-az-a-00",
        "recorded pause nodehost-az-a-01",
        "recorded pause nodehost-az-a-02",
    ]

    partial = RecordingNodeBackend()
    original = partial.pause_nodehost

    def fail_on_third(nodehost: dict[str, Any]) -> list[dict[str, Any]]:
        if nodehost["nodehost_id"].endswith("02"):
            raise DockerRuntimeError("pause failed")
        return original(nodehost)

    partial.pause_nodehost = fail_on_third  # type: ignore[method-assign]
    with pytest.raises(DockerRuntimeError, match="pause failed"):
        docker_runtime._local_full_flow_az_pause_probe(hosts, nodes[1], nodes, backend=partial)

    assert [op for op in partial.operations if op.startswith("resume_")] == [
        "resume_nodehost:nodehost-az-a-01",
        "resume_nodehost:nodehost-az-a-00",
    ]


def test_fault_partition_probe_isolates_through_the_backend_and_still_reads_from_this_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seam must not give the partition probe a way through the partition.

    `85d5096a` made an unreachable isolated node the observation, fail-closed,
    because `_node_command`'s `docker exec` fallback reached straight through
    the isolation. Moving the actuator behind the backend must not reopen that.
    """
    nodes, nodehosts = _fault_stage_nodes()
    _forbid_docker(monkeypatch)
    monkeypatch.setattr(
        docker_runtime,
        "_node_command",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no docker exec through a partition")),
    )
    backend = RecordingNodeBackend()
    rejoined: list[bool] = []
    original_rejoin = backend.rejoin_nodehost

    def rejoin(nodehost: dict[str, Any]) -> list[dict[str, Any]]:
        rejoined.append(True)
        return original_rejoin(nodehost)

    backend.rejoin_nodehost = rejoin  # type: ignore[method-assign]

    def host_command(node: dict[str, Any], *args: Any, timeout: float) -> str:
        if node["logical_id"] == "shard-0000-primary" and not rejoined:
            raise TimeoutError("timed out")
        if args == ("PING",):
            return "PONG"
        return "cluster_state:ok\ncluster_known_nodes:2\n"

    monkeypatch.setattr(docker_runtime, "_node_host_command", host_command)
    monkeypatch.setattr(
        docker_runtime, "_local_full_flow_wait_clean_cluster_snapshot", lambda *_a, **_k: None
    )

    details = docker_runtime._local_full_flow_network_disconnect_probe(
        nodehosts[0], nodes, "minority_majority", backend=backend
    )

    assert backend.operations == [
        "isolate_nodehost:nodehost-az-a-00",
        "rejoin_nodehost:nodehost-az-a-00",
    ]
    assert details["actions"] == [
        "recorded isolate nodehost-az-a-00",
        "recorded rejoin nodehost-az-a-00",
    ]
    # Confirming the isolation took effect is the backend's, per §9.1, so
    # reaching a result is what makes this true.
    assert details["disconnect_verified"] is True
    assert details["isolated_reachable_from_this_side"] is False
    assert "TimeoutError" in details["isolated_unreachable_reason"]
    docker_runtime._local_full_flow_validate_fault_probe_observation("minority_majority", details)


def test_fault_proxy_probe_touches_no_backend_actuator(monkeypatch: pytest.MonkeyPatch) -> None:
    """The three proxy scenarios act on nothing the runtime owns.

    They stand a local proxy in front of a node's client endpoint and measure a
    client through it, so all they need is where that endpoint is. Pinning it
    keeps the dissolution a decision rather than an omission - and pins that
    the endpoint comes from the backend and not from a hardcoded loopback.
    """
    nodes, _ = _fault_stage_nodes()
    _forbid_docker(monkeypatch)
    backend = RecordingNodeBackend()
    captured: dict[str, Any] = {}

    class FakeProxy:
        def __init__(self, *, target_host: str, target_port: int, rule: Any) -> None:
            captured["host"] = target_host
            captured["port"] = target_port

        @property
        def address(self) -> tuple[str, int]:
            return ("127.0.0.1", 1)

        def start(self) -> None:
            pass

        def snapshot(self) -> dict[str, Any]:
            return {"accepted_connections": 0}

        def close(self) -> None:
            pass

    monkeypatch.setattr(docker_runtime, "SandboxNetworkProxy", FakeProxy)
    monkeypatch.setattr(
        docker_runtime.socket,
        "create_connection",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("refused")),
    )

    details = docker_runtime._local_full_flow_proxy_fault_probe(
        nodes[0],
        docker_runtime.ProxyRule("network_loss", loss_percent=100.0),
        expect_success=False,
        backend=backend,
    )

    assert backend.operations == ["client_host"]
    assert captured == {"host": "10.0.0.1", "port": 7000}
    assert details["actions"] == ["sandbox_proxy network_loss"]


def test_baseline_workload_speaks_to_the_cluster_through_the_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`baseline_workload` rides along with the fault slice.

    Its two calls and the fault windows' two are the same redirect-following
    client `run_cluster_admin` already owns, so converting only one of them
    would leave the lifecycle naming `docker exec valkey-cli` for the stage
    immediately before the one this slice cleans.
    """
    nodes, _ = _fault_stage_nodes()
    _forbid_docker(monkeypatch)
    monkeypatch.setattr(docker_runtime, "_management_matrix_first_live_node", lambda given: given[0])
    backend = RecordingNodeBackend()

    result = docker_runtime._local_full_flow_run_baseline_workload(
        "local_full_flow", "local_full_flow", "run-1", 50, nodes, backend=backend
    )

    assert backend.operations == ["run_cluster_admin"] * 6
    assert [argv[:2] for argv in backend.cluster_admin] == [["-c", "-p"]] * 6
    assert [argv[3] for argv in backend.cluster_admin] == ["SET", "GET", "SET", "GET", "SET", "GET"]
    assert result["windows"][0]["status"] == "PASS"


@pytest.mark.parametrize("fresh", [True, False])
def test_a_fresh_start_discards_the_dataset_not_only_the_cluster_identity(
    monkeypatch: pytest.MonkeyPatch, fresh: bool
) -> None:
    """A node told to rejoin as new must be empty, or CLUSTER REPLICATE refuses it.

    Removing `nodes.conf` alone left the RDB in place. The generated config sets
    no `save` directive, so Valkey's default policy writes a `dump.rdb` during any
    workload and `SHUTDOWN NOSAVE` does not remove one already written. A real
    exact-50 run failed on exactly that, one run after passing:
    `ERR To set a master the node must be empty and without assigned slots.`
    """

    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "4242"
        stderr = ""

    def fake_run_docker(args: list[str], **_kwargs: Any) -> Any:
        calls.append(list(args))
        return Result()

    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    monkeypatch.setattr(docker_runtime, "_node_command", lambda *_a, **_k: "PONG")

    pid, records = docker_runtime.DockerNodeBackend().start_node(
        {
            "logical_id": "node-a",
            "nodehost_container_name": "nodehost-a",
            "data_dir": "/data/node-a",
            "config_file": "/data/node-a/valkey.conf",
            "pid_file": "/data/node-a/valkey.pid",
            "client_port": 7000,
        },
        fresh_cluster_identity=fresh,
    )

    removals = [args for args in calls if "rm" in args]
    if not fresh:
        assert removals == [], "a plain restart must keep the node's state"
        assert not any(
            "discard_prior_state" in str(row.get("command_kind")) for row in records
        )
        return

    assert len(removals) == 1
    argv = removals[0]
    assert "/data/node-a/nodes.conf" in argv
    assert "/data/node-a/dump.rdb" in argv
    # The record names what the command did; it removes more than nodes.conf now,
    # and evidence that said otherwise would be a false record.
    kinds = [str(row.get("command_kind")) for row in records]
    assert "owned_valkey_process_discard_prior_state" in kinds
    assert "owned_valkey_process_remove_nodes_conf" not in kinds
    assert pid == 4242


def _light_clean_nodes(count: int = 2) -> list[dict[str, Any]]:
    return [
        {
            "logical_id": f"node-{index}",
            "host": "127.0.0.1",
            "client_port": 7000 + index,
            "role": "primary" if index == 0 else "replica",
            "shard_id": "shard-0000",
        }
        for index in range(count)
    ]


def test_a_bounded_wait_that_converges_leaves_no_failure_behind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An attempt that did not hold is not a failure of anything.

    Absorbing those is what a bounded wait is for, and the timing row is a
    measurement rather than a verdict. The frozen baseline records this row as
    `count=30 status=FAIL` in a run that converged and passed, and the other
    baseline as `count=1 status=PASS` - the same wait, the same outcome, two
    different labels.
    """

    attempts = {"n": 0}

    class Probe:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        def run(self, **_options: Any) -> dict[str, Any]:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise SemanticFailure("shard-0000-replica CLUSTER INFO mismatch")
            return {
                "status": "OK",
                "nodes_observed": 2,
                "primary_count": 1,
                "replica_count": 1,
            }

    monkeypatch.setattr(docker_runtime, "LightClusterProbe", Probe)
    monkeypatch.setattr(docker_runtime.time, "sleep", lambda _s: None)
    timings: dict[str, dict[str, Any]] = {}

    docker_runtime._wait_process_light_clean(
        _light_clean_nodes(),
        expected_nodes=2,
        expected_primaries=1,
        expected_replicas=1,
        timeout=30.0,
        timings=timings,
    )

    row = timings["runtime_all_node_light_probe"]
    assert attempts["n"] == 3
    assert row["count"] == 3
    # The wait returned, so the row says so. `_record_timing` is sticky-FAIL, which
    # is why stamping an interim attempt was permanent.
    assert row["status"] == "PASS"
    assert "shard-0000-replica" in row["details"]["last_attempt_error"]
    assert row["details"]["last_attempt_kind"] == "semantic"


@pytest.mark.parametrize(
    ("raised", "expected", "kind"),
    [
        (SemanticFailure("cluster never converged"), docker_runtime.DockerRuntimeError, "semantic"),
        (CollectionError("all-node light collection failed"), CollectionError, "tool"),
        (
            OSError(errno.EADDRNOTAVAIL, "Can't assign requested address"),
            CollectionError,
            "tool",
        ),
    ],
)
def test_a_bounded_wait_that_never_converged_says_which_kind_it_was(
    monkeypatch: pytest.MonkeyPatch,
    raised: Exception,
    expected: type[Exception],
    kind: str,
) -> None:
    """Never getting a reading and reading a cluster that never converged are
    different findings, and only the second is the cluster's."""

    class Probe:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        def run(self, **_options: Any) -> dict[str, Any]:
            raise raised

    monkeypatch.setattr(docker_runtime, "LightClusterProbe", Probe)
    monkeypatch.setattr(docker_runtime.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        docker_runtime, "_process_node_snapshots_parallel", lambda *_a, **_k: []
    )
    timings: dict[str, dict[str, Any]] = {}

    with pytest.raises(expected) as excinfo:
        docker_runtime._wait_process_light_clean(
            _light_clean_nodes(),
            expected_nodes=2,
            expected_primaries=1,
            expected_replicas=1,
            timeout=0.01,
            timings=timings,
        )

    assert excinfo.type is expected
    assert "did not converge" in str(excinfo.value)
    assert timings["runtime_all_node_light_probe"]["details"]["last_attempt_kind"] == kind
    # The measured local case: ephemeral-port exhaustion at 200 nodes is the tool
    # failing, not the cluster refusing.
    assert (kind == "tool") == (expected is CollectionError)


def test_a_process_that_vanishes_mid_probe_is_gone_not_a_probe_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The disappearance is what this probe waits for, so it cannot be an error.

    The readability test and the read are two separate syscalls. A process that
    exited between them made `awk` fail and the script exit 70, so the success
    condition took the error path. Measured at exact-200, where stop and kill run
    far more often than at 50:
    `exit=70 stderr=awk: cannot open "/proc/72/stat" (No such file or directory)`.
    """

    scripts: list[str] = []

    class Vanished:
        """What the container returns once the process is gone mid-read."""

        returncode = 70
        stdout = ""
        stderr = 'awk: cannot open "/proc/72/stat" (No such file or directory)'

    class Gone:
        returncode = 0
        stdout = "VSLAB_GONE"
        stderr = ""

    def fake_run_docker(args: list[str], **_kwargs: Any) -> Any:
        scripts.append(args[-1])
        return Gone()

    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    assert docker_runtime._wait_container_pid_gone("nodehost-a", "72", timeout=1.0) is True

    script = scripts[0]
    # The read tolerates the file vanishing, and only then.
    assert "2>/dev/null" in script
    assert "[ -e /proc/72/stat ] && exit 70" in script
    # A read that fails while the file is still there is a genuine malfunction and
    # must still be one, so the guard is kept rather than widened to "any failure
    # means gone".
    assert "exit 70" in script

    monkeypatch.setattr(docker_runtime, "run_docker", lambda *_a, **_k: Vanished())
    with pytest.raises(docker_runtime.DockerRuntimeError, match="owned process probe failed"):
        docker_runtime._wait_container_pid_gone("nodehost-a", "72", timeout=1.0)


class _FakeDockerFleet:
    """Just enough Docker for `_execute_runtime`'s container path and its cleanup.

    The failure handler's whole point is that it reaches cleanup, so cleanup has
    to be able to find and remove something; a fake that answered nothing would
    have produced an empty report either way and proved nothing.
    """

    def __init__(self) -> None:
        self.containers: list[str] = []
        self.networks: list[str] = []
        self.removed: list[str] = []

    def run_docker(self, args: list[str], timeout: int = 120, check: bool = True, **_kwargs: Any) -> Any:
        argv = [str(item) for item in args]
        if argv[:2] == ["network", "create"]:
            self.networks.append("net-0001")
            return docker_runtime.DockerResult("net-0001\n", "", 0)
        if argv[:3] == ["ps", "-a", "-q"]:
            return docker_runtime.DockerResult("".join(f"{cid}\n" for cid in self.containers), "", 0)
        if argv[:3] == ["network", "ls", "-q"]:
            return docker_runtime.DockerResult("".join(f"{nid}\n" for nid in self.networks), "", 0)
        if argv[0] == "stop":
            return docker_runtime.DockerResult("", "", 0)
        if argv[:2] == ["rm", "-f"]:
            self.containers.remove(argv[2])
            self.removed.append(argv[2])
            return docker_runtime.DockerResult("", "", 0)
        if argv[:2] == ["network", "rm"]:
            self.networks.remove(argv[2])
            self.removed.append(argv[2])
            return docker_runtime.DockerResult("", "", 0)
        raise AssertionError(f"unexpected docker command in this test: {argv}")


def _container_path_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    fail_after_started: int | None,
    fail_at_configure: bool = False,
) -> tuple[_FakeDockerFleet, list[str], Path, Path]:
    fleet = _FakeDockerFleet()
    bare_cleanups: list[str] = []
    monkeypatch.setattr(docker_runtime, "run_docker", fleet.run_docker)
    monkeypatch.setattr(docker_runtime, "_check_ports_free", lambda _ports: None)
    monkeypatch.setattr(
        docker_runtime.DockerNodeBackend,
        "verify_image",
        lambda _self, image: {"image": image, "status": "PASS"},
    )
    monkeypatch.setattr(docker_runtime, "_container_pid", lambda _cid: 4242)
    monkeypatch.setattr(docker_runtime, "_container_ip", lambda _cid, _net: "172.18.0.9")
    monkeypatch.setattr(
        docker_runtime,
        "cleanup_by_label",
        lambda **kwargs: bare_cleanups.append(str(kwargs.get("run_id"))),
    )

    def fake_start_container(*_args: Any, **_kwargs: Any) -> str:
        if fail_after_started is not None and len(fleet.containers) >= fail_after_started:
            raise RuntimeError("induced runtime failure")
        cid = f"cid-{len(fleet.containers):04d}"
        fleet.containers.append(cid)
        return cid

    monkeypatch.setattr(docker_runtime, "_start_container", fake_start_container)
    if fail_at_configure:
        monkeypatch.setattr(
            docker_runtime,
            "_configure_cluster",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("induced runtime failure")),
        )

    artifacts = tmp_path / "artifacts"
    state_out = tmp_path / "state.json"
    with pytest.raises(RuntimeError, match="induced runtime failure"):
        docker_runtime._execute_runtime(
            capability_id="cluster_lifecycle",
            scenario="cluster_lifecycle",
            backend_id="docker_container",
            profile_id="small-real",
            requested_nodes=6,
            config_path="templates/configs/single_mac_6node.yaml",
            artifacts_dir=artifacts,
            state_out=state_out,
        )
    return fleet, bare_cleanups, artifacts, state_out


def test_a_failure_while_starting_containers_still_reports_what_it_cleaned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The container path's failure handler used to be the process path's.

    `_process_runtime_state` was called with `nodehosts` and `snapshots`, neither
    of which this scope binds, so the first line raised
    `NameError: name 'snapshots' is not defined`, the surrounding branch
    swallowed it, and every mid-runtime failure degraded to bare label cleanup -
    no state, no `setup_error`, no cleanup report at all.
    """
    fleet, bare_cleanups, artifacts, state_out = _container_path_runtime(
        monkeypatch, tmp_path, fail_after_started=2
    )

    # The pre-run reclaim is the only `cleanup_by_label`; the failure path did
    # not fall through to it.
    assert len(bare_cleanups) == 1

    state = json.loads(state_out.read_text(encoding="utf-8"))
    assert state["runtime"]["setup_error"] == "RuntimeError('induced runtime failure')"
    # What was asked for, and what actually came up. Building this from the full
    # planned fleet raises `KeyError: 'container_id'` on the first node that
    # never started, which is why it is built from what did.
    assert state["requested_nodes"] == 6
    assert state["observed_nodes"] == 2
    assert [node["container_id"] for node in state["nodes"]] == ["cid-0000", "cid-0001"]

    report = json.loads((artifacts / "cleanup_report.json").read_text(encoding="utf-8"))
    assert report["artifact_type"] == "cleanup_report"
    assert report["status"] == "PASS"
    assert report["resources_remaining"] == []
    assert [
        (action["type"], action["id"], action["action"])
        for action in report["cleanup_actions"]
        if action["action"] == "remove"
    ] == [
        ("container", "cid-0000", "remove"),
        ("container", "cid-0001", "remove"),
        ("network", "net-0001", "remove"),
    ]
    assert fleet.containers == [] and fleet.networks == []


def test_a_failure_after_the_fleet_is_up_reports_the_whole_fleet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The other shape the handler has to cover, where `started` is every node."""
    _fleet, bare_cleanups, artifacts, state_out = _container_path_runtime(
        monkeypatch, tmp_path, fail_after_started=None, fail_at_configure=True
    )

    assert len(bare_cleanups) == 1
    state = json.loads(state_out.read_text(encoding="utf-8"))
    assert state["requested_nodes"] == 6
    assert state["observed_nodes"] == 6
    assert state["runtime"]["setup_error"] == "RuntimeError('induced runtime failure')"
    report = json.loads((artifacts / "cleanup_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["resources_remaining"] == []


def test_parallel_work_can_see_the_command_recorder(tmp_path: Path) -> None:
    """A worker thread starts with an empty context unless one is copied into it.

    The recorder is the only `ContextVar` in the product, and `_bounded_parallel`
    is how cluster formation, the rolling restart health gate and the snapshot
    probes issue their commands - so without this, everything they do is
    unrecorded, and "no fallback was recorded" would mean nothing.
    """
    from valkey_scale_lab.runtime.command_recorder import (
        CommandRecorder,
        command_recorder_context,
        current_command_recorder,
    )

    recorder = CommandRecorder(
        capability_id="local_full_flow",
        run_id="unit-bounded-parallel",
        scenario="local_full_flow",
        artifacts_dir=tmp_path / "artifacts",
    )

    with command_recorder_context(recorder):
        seen = docker_runtime._bounded_parallel(
            range(8),
            lambda _item: current_command_recorder() is recorder,
            timeout=10.0,
            label="recorder visibility",
        )
    assert seen == [True] * 8

    # And nothing is invented where no recorder was installed.
    assert docker_runtime._bounded_parallel(
        range(3),
        lambda _item: current_command_recorder(),
        timeout=10.0,
        label="recorder absence",
    ) == [None, None, None]


# --- roadmap item 0.5: the two seam operations §15 names ----------------------


def test_docker_load_lane_host_keeps_the_command_the_baselines_record() -> None:
    """The Docker half of the Load Lane's evidence upload, asserted where it lives.

    `observability/load.py` no longer names Docker, so the exec wrapper and the
    output copy are pinned here instead. The argv is byte-identical to what the
    frozen exact-50 baselines record in `scalable_stability_observation.json`,
    which is what makes this a move rather than a change.
    """
    backend = docker_runtime.DockerNodeBackend()
    host = backend.load_lane_host(
        {
            "container_name": "vslab-run-nodehost-az-a-00",
            "nodehost_container_name": "vslab-run-nodehost-az-a-00",
            "client_port": 7400,
        }
    )

    # A node answers on loopback inside the nodehost its process listens in.
    assert host.seed_host == "127.0.0.1"

    command = host.command(
        ["memtier_benchmark", "--server", "127.0.0.1", "--cluster-mode"],
        remote_dir="/tmp/vslab-load-lane/formal",
    )
    assert command == [
        "docker",
        "exec",
        "vslab-run-nodehost-az-a-00",
        "sh",
        "-c",
        "mkdir -p /tmp/vslab-load-lane/formal && exec memtier_benchmark "
        "--server 127.0.0.1 --cluster-mode",
    ]


def test_docker_load_lane_host_collects_output_and_reports_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = docker_runtime.DockerLoadLaneHost(container="vslab-run-nodehost-az-a-00")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> Any:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(docker_runtime.subprocess, "run", fake_run)
    host.collect_evidence("/tmp/vslab-load-lane/formal", tmp_path)

    assert calls == [
        [
            "docker",
            "cp",
            "vslab-run-nodehost-az-a-00:/tmp/vslab-load-lane/formal/.",
            tmp_path.as_posix(),
        ]
    ]

    monkeypatch.setattr(
        docker_runtime.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 1, "", "no such container"
        ),
    )
    with pytest.raises(CollectionError, match="could not copy memtier output"):
        host.collect_evidence("/tmp/vslab-load-lane/formal", tmp_path)


def test_load_lane_seed_asks_the_backend_where_to_run() -> None:
    """The seed's host is the adapter's answer, not a container name read here."""
    nodes = [
        {
            "container_name": "vslab-run-nodehost-az-a-00",
            "nodehost_container_name": "vslab-run-nodehost-az-a-00",
            "client_port": 7400,
        }
    ]
    host, seed_host, port = docker_runtime._load_lane_seed(
        nodes, backend=docker_runtime.DockerNodeBackend()
    )

    assert host.container == "vslab-run-nodehost-az-a-00"
    assert (seed_host, port) == ("127.0.0.1", 7400)


def test_cleanup_refuses_a_run_whose_backend_has_no_implementation(
    tmp_path: Path,
) -> None:
    """The defect item 0.5 exists to prevent, pinned.

    Before the seam reached teardown, a state naming any other backend fell into
    the Docker container path, which found nothing owned by that run in Docker -
    there being nothing in Docker - and wrote `status: PASS` while every process
    it started was still running. `native_multi_ecs` is deliberately absent from
    the backend registry, so it stands in for exactly that state here.
    """
    state = {
        "capability_id": "local_full_flow",
        "scenario": "local_full_flow",
        "backend_id": "native_multi_ecs",
        "runtime": {"type": "native_multi_ecs", "run_id": "owned-run"},
        "nodes": [{"logical_id": "node-000", "pid": 101}],
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(teardown.TeardownError, match="native_multi_ecs"):
        teardown.cleanup_scenario(
            state_path=state_path,
            artifacts_dir=tmp_path,
            out_path=tmp_path / "cleanup.json",
        )

    # And it wrote nothing: a report claiming a clean teardown is the failure.
    assert not (tmp_path / "cleanup.json").exists()


def test_cleanup_status_rule_is_one_rule_for_every_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Slice map §2.6: the two status rules became the stricter one.

    That is a no-op on the container path by enumeration - every `FAIL` a row
    there can carry already forces `FAIL` through `cleanup_errors` or through
    `resources_remaining`. This pins the enumeration by driving the container
    path with each of the three producers that can emit a row.
    """
    state = {
        "capability_id": "cluster_lifecycle",
        "scenario": "cluster_lifecycle",
        "backend_id": "docker_container",
        "runtime": {"type": "docker", "run_id": "test-run"},
        "nodes": [],
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(docker_runtime, "owned_resources", lambda **_kwargs: [])

    # Only PASS and SKIPPED_WITH_REASON rows: still PASS under either rule.
    monkeypatch.setattr(
        docker_runtime,
        "_cleanup_resources_by_label",
        lambda **_kwargs: (
            [
                {"type": "container", "id": "c", "action": "stop", "status": "SKIPPED_WITH_REASON"},
                {"type": "container", "id": "c", "action": "remove", "status": "PASS"},
            ],
            {"cleanup_remove_containers_seconds": 0.0, "cleanup_remove_networks_seconds": 0.0},
        ),
    )
    report = teardown.cleanup_scenario(
        state_path=state_path,
        artifacts_dir=tmp_path,
        out_path=tmp_path / "cleanup.json",
    )
    assert report["status"] == "PASS"
    assert not any(action["status"] == "FAIL" for action in report["cleanup_actions"])

    # The discovery failure is the one producer that emits FAIL, and it appends
    # to cleanup_errors in the same breath - so the added term changes nothing.
    def raise_discovery(**_kwargs: Any):
        raise DockerRuntimeError("discovery failed")

    monkeypatch.setattr(docker_runtime, "_cleanup_resources_by_label", raise_discovery)
    report = teardown.cleanup_scenario(
        state_path=state_path,
        artifacts_dir=tmp_path,
        out_path=tmp_path / "cleanup.json",
    )
    assert report["status"] == "FAIL"
    assert report["cleanup_errors"] == ["discovery failed"]
    assert any(action["status"] == "FAIL" for action in report["cleanup_actions"])
