from __future__ import annotations

from pathlib import Path

import pytest

from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.runtime.docker_runtime import DockerRuntimeError
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline


def test_p03_node_specs_are_deterministic() -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/single_mac_6node.yaml"))
    nodes = docker_runtime._node_specs(config, "P03_LOCAL_DOCKER_VALKEY", "cluster_smoke")
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
    assert "p03-local-docker-valkey-cluster-smoke" in nodes[0]["container_name"]
    assert {node["host_id"] for node in nodes} == {"local"}


def test_p10_node_specs_preserve_multi_host_placement() -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/single_mac_6node.yaml"))
    config["hosts"] = [
        {"host_id": "local-a", "ip": "127.0.0.1", "docker_endpoint": "local", "labels": ["worker"]},
        {"host_id": "local-b", "ip": "127.0.0.1", "docker_endpoint": "local", "labels": ["worker"]},
    ]
    nodes = docker_runtime._node_specs(config, "P10_MULTI_HOST_ORCHESTRATION", "orchestrated_localhost")
    assert [node["host_id"] for node in nodes] == ["local-a", "local-b", "local-a", "local-b", "local-a", "local-b"]


def test_p13_node_specs_use_slower_cluster_failure_timeout() -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/scale_50.yaml"))
    nodes = docker_runtime._node_specs(config, "P13_SCALE_LADDER_50_100", "scale_50")
    assert {node["cluster_node_timeout"] for node in nodes} == {"600000"}


def test_p13_node_specs_preserve_replica_topology() -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/scale_50.yaml"))
    nodes = docker_runtime._node_specs(config, "P13_SCALE_LADDER_50_100", "scale_50")

    assert len(nodes) == 50
    assert len([node for node in nodes if node["role"] == "primary"]) == 25
    assert len([node for node in nodes if node["role"] == "replica"]) == 25
    assert nodes[0]["logical_id"] == "shard-0000-primary"
    assert nodes[25]["logical_id"] == "shard-0000-replica-00"


def test_p13_defaults_to_docker_process_runtime() -> None:
    assert docker_runtime._uses_docker_process_runtime("P12_SCALE_LADDER_10_30", "scale_10") is True
    assert docker_runtime._uses_docker_process_runtime("P12_SCALE_LADDER_10_30", "scale_30") is True
    assert docker_runtime._uses_docker_process_runtime("P13_SCALE_LADDER_50_100", "scale_50") is True
    assert docker_runtime._uses_docker_process_runtime("P13_SCALE_LADDER_50_100", "scale_100") is True
    assert docker_runtime._uses_docker_process_runtime("P21_FAILOVER_LATENCY_CURVE_200", "scale_200_sample_01") is True
    assert docker_runtime._uses_docker_process_runtime("P11_STABILITY_SOAK", "stability_soak_smoke") is False


def test_p16_quant_telemetry_is_six_node_only() -> None:
    assert docker_runtime._scenario_node_count_allowed(
        "P16_QUANT_TELEMETRY_UNIFICATION",
        "goal_loop_quant_telemetry",
        6,
    ) is True
    assert docker_runtime._scenario_node_count_allowed(
        "P16_QUANT_TELEMETRY_UNIFICATION",
        "goal_loop_quant_telemetry",
        10,
    ) is False


def test_p25_smoke_runtime_is_six_node_only_and_not_process_runtime() -> None:
    assert docker_runtime._scenario_node_count_allowed(
        "P25_FAULT_WORKLOAD_IMPACT_ANALYSIS",
        "fault_workload_impact_analysis",
        6,
    ) is True
    assert docker_runtime._scenario_node_count_allowed(
        "P25_FAULT_WORKLOAD_IMPACT_ANALYSIS",
        "fault_workload_impact_analysis",
        10,
    ) is False
    assert docker_runtime._uses_docker_process_runtime(
        "P25_FAULT_WORKLOAD_IMPACT_ANALYSIS",
        "fault_workload_impact_analysis",
    ) is False


def test_p21_runtime_allows_only_exact_200_sample_scenarios() -> None:
    assert docker_runtime._p21_scale_sample_node_count("P21_FAILOVER_LATENCY_CURVE_200", "scale_200_sample_01") == 200
    assert docker_runtime._scenario_node_count_allowed("P21_FAILOVER_LATENCY_CURVE_200", "scale_200_sample_01", 200) is True
    assert docker_runtime._scenario_node_count_allowed("P21_FAILOVER_LATENCY_CURVE_200", "scale_200_sample_01", 100) is False
    assert docker_runtime._scenario_node_count_allowed("P21_FAILOVER_LATENCY_CURVE_200", "scale_200_sample_01", 201) is False
    assert docker_runtime._uses_docker_process_runtime("P22_FAULT_REPLICA_HOST_AZ_STOP", "scale_200_sample_01") is False
    assert docker_runtime._scenario_node_count_allowed("P22_FAULT_REPLICA_HOST_AZ_STOP", "scale_200_sample_01", 200) is False


def test_p22_runtime_admits_only_bounded_fault_matrix_scenarios() -> None:
    for node_count in [6, 10, 30, 50, 100]:
        scenario = f"p22_fault_matrix_{node_count}"
        assert docker_runtime._p22_fault_matrix_node_count("P22_FAULT_REPLICA_HOST_AZ_STOP", scenario) == node_count
        assert docker_runtime._scenario_node_count_allowed("P22_FAULT_REPLICA_HOST_AZ_STOP", scenario, node_count) is True
        assert docker_runtime._uses_docker_process_runtime("P22_FAULT_REPLICA_HOST_AZ_STOP", scenario) is True
    assert docker_runtime._p22_fault_matrix_node_count("P22_FAULT_REPLICA_HOST_AZ_STOP", "p22_fault_matrix_200") is None
    assert docker_runtime._scenario_node_count_allowed("P22_FAULT_REPLICA_HOST_AZ_STOP", "p22_fault_matrix_200", 200) is False
    assert docker_runtime._uses_docker_process_runtime("P22_FAULT_REPLICA_HOST_AZ_STOP", "p22_fault_matrix_200") is False


def test_p23_runtime_admits_only_bounded_network_fault_matrix_scenarios() -> None:
    for node_count in [6, 10, 30, 50, 100]:
        scenario = f"p23_fault_matrix_{node_count}"
        assert docker_runtime._p23_fault_matrix_node_count("P23_FAULT_NETWORK_DELAY_LOSS_FLAP", scenario) == node_count
        assert docker_runtime._scenario_node_count_allowed("P23_FAULT_NETWORK_DELAY_LOSS_FLAP", scenario, node_count) is True
        assert docker_runtime._uses_docker_process_runtime("P23_FAULT_NETWORK_DELAY_LOSS_FLAP", scenario) is True
    assert docker_runtime._p23_fault_matrix_node_count("P23_FAULT_NETWORK_DELAY_LOSS_FLAP", "p23_fault_matrix_200") is None
    assert docker_runtime._scenario_node_count_allowed("P23_FAULT_NETWORK_DELAY_LOSS_FLAP", "p23_fault_matrix_200", 200) is False
    assert docker_runtime._uses_docker_process_runtime("P23_FAULT_NETWORK_DELAY_LOSS_FLAP", "p23_fault_matrix_200") is False


def test_p24_runtime_admits_only_bounded_partition_matrix_scenarios() -> None:
    for node_count in [6, 10, 30, 50, 100]:
        scenario = f"p24_partition_matrix_{node_count}"
        assert docker_runtime._p24_fault_matrix_node_count("P24_PARTITION_SPLIT_BRAIN_MATRIX", scenario) == node_count
        assert docker_runtime._scenario_node_count_allowed("P24_PARTITION_SPLIT_BRAIN_MATRIX", scenario, node_count) is True
        assert docker_runtime._uses_docker_process_runtime("P24_PARTITION_SPLIT_BRAIN_MATRIX", scenario) is True
    assert docker_runtime._p24_fault_matrix_node_count("P24_PARTITION_SPLIT_BRAIN_MATRIX", "p24_partition_matrix_200") is None
    assert docker_runtime._scenario_node_count_allowed("P24_PARTITION_SPLIT_BRAIN_MATRIX", "p24_partition_matrix_200", 200) is False
    assert docker_runtime._uses_docker_process_runtime("P24_PARTITION_SPLIT_BRAIN_MATRIX", "p24_partition_matrix_200") is False
    assert docker_runtime._p24_fault_matrix_node_count("P24_PARTITION_SPLIT_BRAIN_MATRIX", "p24_partition_matrix_1000") is None
    assert docker_runtime._scenario_node_count_allowed("P24_PARTITION_SPLIT_BRAIN_MATRIX", "p24_partition_matrix_1000", 1000) is False


def test_p21_runtime_semantic_exception_is_narrow() -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/scale_200.yaml"))

    assert docker_runtime._runtime_semantic_errors(config, phase="P21_FAILOVER_LATENCY_CURVE_200", scenario="scale_200_sample_01") == []
    assert any(
        error["code"] == "NODE_CAP_EXCEEDED"
        for error in docker_runtime._runtime_semantic_errors(config, phase="P22_FAULT_REPLICA_HOST_AZ_STOP", scenario="scale_200_sample_01")
    )


def test_p13_runtime_timing_names_split_diagnostic_probe() -> None:
    assert "runtime_final_full_probe" in docker_runtime.P13_TIMING_NAMES
    assert "runtime_diagnostic_full_probe" in docker_runtime.P13_TIMING_NAMES
    timings: dict[str, dict] = {}
    started = docker_runtime.time.monotonic()
    docker_runtime._record_timing(timings, "runtime_final_full_probe", started, status="PASS")
    docker_runtime._record_timing(timings, "runtime_diagnostic_full_probe", started, status="FAIL")

    entries = {entry["name"]: entry for entry in docker_runtime._timing_entries(timings, docker_runtime.P13_TIMING_NAMES)}
    assert entries["runtime_final_full_probe"]["status"] == "PASS"
    assert entries["runtime_diagnostic_full_probe"]["status"] == "FAIL"


def test_cluster_create_strategy_defaults_to_valkey_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VSLAB_CLUSTER_CREATE_STRATEGY", raising=False)
    assert docker_runtime._cluster_create_strategy() == docker_runtime.CLUSTER_CREATE_STRATEGY_DEFAULT


def test_cluster_create_strategy_accepts_manual_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSLAB_CLUSTER_CREATE_STRATEGY", docker_runtime.CLUSTER_CREATE_STRATEGY_MANUAL)
    assert docker_runtime._cluster_create_strategy() == docker_runtime.CLUSTER_CREATE_STRATEGY_MANUAL


def test_cluster_create_strategy_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSLAB_CLUSTER_CREATE_STRATEGY", "nodes_conf_fast_bootstrap")
    with pytest.raises(DockerRuntimeError, match="unsupported cluster create strategy"):
        docker_runtime._cluster_create_strategy()


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
    nodes = docker_runtime._node_specs(config, "P13_SCALE_LADDER_50_100", "scale_50", "run")

    nodehosts = docker_runtime._process_nodehosts(config, nodes, "P13_SCALE_LADDER_50_100", "scale_50", "run")

    assert [nodehost["nodehost_id"] for nodehost in nodehosts] == ["nodehost-az-a", "nodehost-az-b"]
    assert sum(nodehost["logical_node_count"] for nodehost in nodehosts) == 50
    assert all(node["runtime_type"] == "docker_process" for node in nodes)
    assert all(node["nodehost_id"].startswith("nodehost-az-") for node in nodes)
    assert all(node["cluster_bus_port"] >= 17400 for node in nodes)


def _assert_process_bootstrap_uses_nodehost_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_path: str,
    phase: str,
    scenario: str,
    expected_nodes: int,
) -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file(config_path))
    run_id = f"{phase}-{scenario}-20260628"
    nodes = docker_runtime._node_specs(config, phase, scenario, run_id)
    nodehosts = docker_runtime._process_nodehosts(config, nodes, phase, scenario, run_id)
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
        "P12_SCALE_LADDER_10_30",
        "scale_10",
        10,
    )


def test_process_bootstrap_uses_nodehost_bundle_for_scale_30(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_process_bootstrap_uses_nodehost_bundle(
        tmp_path,
        monkeypatch,
        "templates/configs/scale_30.yaml",
        "P12_SCALE_LADDER_10_30",
        "scale_30",
        30,
    )


def test_process_bootstrap_records_setup_timeline_child_spans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/scale_10.yaml"))
    run_id = "P12_SCALE_LADDER_10_30-scale_10-20260628"
    nodes = docker_runtime._node_specs(config, "P12_SCALE_LADDER_10_30", "scale_10", run_id)
    nodehosts = docker_runtime._process_nodehosts(config, nodes, "P12_SCALE_LADDER_10_30", "scale_10", run_id)
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


def test_process_runtime_state_records_required_node_fields() -> None:
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
        "P13_SCALE_LADDER_50_100",
        "scale_50",
        "run",
        "network",
        {"hosts": [{"host_id": "local"}]},
        nodehosts,
        nodes,
        [{"label": "final"}],
    )

    assert state["runtime"]["type"] == "docker_process"
    assert state["runtime"]["cluster_startup_strategy"] == "all_processes_ready_then_tree_fanout_meet_parallel_slots_parallel_replicas_two_stage_probe"
    assert state["runtime"]["cluster_meet_fanout"] == 4
    assert state["runtime"]["cluster_startup_parallelism"] == 8
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
        "P13_SCALE_LADDER_50_100",
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


def test_slot_ranges_cover_all_slots_for_scale_rungs() -> None:
    ranges = docker_runtime._slot_ranges(15)
    assert ranges[0][0] <= 8014 <= ranges[0][1]
    assert len(ranges) == 15
    assert sum((end - start + 1) for start, end in ranges) == 16384
    assert sorted(ranges)[0][0] == 0
    assert sorted(ranges)[-1][1] == 16383


def test_cluster_create_primary_order_keeps_probe_slot_on_first_primary() -> None:
    primaries = [{"logical_id": f"p{idx}"} for idx in range(25)]

    ordered = docker_runtime._cluster_create_primary_order(primaries)
    sequential_ranges = docker_runtime._sequential_slot_ranges(len(primaries))
    probe_index = docker_runtime._probe_slot_primary_index(len(primaries))

    assert ordered[probe_index]["logical_id"] == "p0"
    assert sequential_ranges[probe_index][0] <= 8014 <= sequential_ranges[probe_index][1]
    assert {node["logical_id"] for node in ordered} == {node["logical_id"] for node in primaries}


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
        "P13_SCALE_LADDER_50_100",
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


def test_process_wait_predicate_uses_representatives_then_full_check(monkeypatch: pytest.MonkeyPatch) -> None:
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

    assert calls == [["p0", "p1"], ["p0", "p1", "r0", "r1"]]


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
    monkeypatch.setattr(docker_runtime, "_wait_process_knows_node_id", lambda replica, master_id, timeout: None)
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
    monkeypatch.setattr(docker_runtime, "_wait_process_knows_node_id", lambda replica, master_id, timeout: None)
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
        "bounded replica master visibility wait",
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
    monkeypatch.setattr(docker_runtime, "_wait_process_knows_node_id", lambda replica, master_id, timeout: None)
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
        "bounded replica master visibility wait",
        "bounded CLUSTER REPLICATE commands",
        "bounded replica-of convergence wait",
    ]
    assert details["parallelism"] == 16
    assert details["bounded_parallelism"] is True
    assert details["replica_primary_id_lookup_seconds"] >= 0.0
    assert details["replica_knows_master_wait_seconds"] >= 0.0
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


def test_primary_cluster_create_orders_process_addresses_for_probe_slot(monkeypatch: pytest.MonkeyPatch) -> None:
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
    probe_index = docker_runtime._probe_slot_primary_index(len(primaries))
    assert calls[0][address_start + probe_index] == "172.18.0.2:7400"


def test_assign_probe_slot_to_first_primary_sets_slot_on_all_primaries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple[object, ...]]] = []
    primaries = [{"logical_id": f"p{idx}"} for idx in range(3)]

    def fake_node_command(node: dict, *args: object, timeout: float = 5.0) -> str:
        calls.append((node["logical_id"], args))
        if args == ("CLUSTER", "MYID"):
            return "id-p0"
        return "OK"

    monkeypatch.setattr(docker_runtime, "_node_command", fake_node_command)

    result = docker_runtime._assign_probe_slot_to_first_primary(primaries, timeout=30)

    assert result == "probe slot 8014 assigned to p0"
    assert ("p0", ("CLUSTER", "MYID")) in calls
    assert {
        (logical_id, args)
        for logical_id, args in calls
        if args[:2] == ("CLUSTER", "SETSLOT")
    } == {
        ("p0", ("CLUSTER", "SETSLOT", 8014, "NODE", "id-p0")),
        ("p1", ("CLUSTER", "SETSLOT", 8014, "NODE", "id-p0")),
        ("p2", ("CLUSTER", "SETSLOT", 8014, "NODE", "id-p0")),
    }


def test_default_primary_create_records_strategy_subtimings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VSLAB_CLUSTER_CREATE_STRATEGY", raising=False)
    monkeypatch.setattr(docker_runtime, "_create_primary_cluster", lambda primaries, timeout: "cluster create OK")
    monkeypatch.setattr(docker_runtime, "_wait_cluster_known", lambda *args, **kwargs: None)
    monkeypatch.setattr(docker_runtime, "_assign_probe_slot_to_first_primary", lambda primaries, timeout: "probe slot assigned")

    output, details = docker_runtime._create_primary_cluster_valkey_cli([{"logical_id": "p0"}, {"logical_id": "p1"}], timeout=30)

    assert "cluster create OK" in output
    assert details["primary_meet_seconds"] == 0.0
    assert details["slot_assignment_seconds"] == 0.0
    assert details["slot_assignment_scope"] == "inside_valkey_cli_cluster_create"
    assert details["cluster_create_command_seconds"] >= 0.0
    assert details["primary_convergence_seconds"] >= 0.0
    assert details["probe_slot_assignment_seconds"] >= 0.0


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
        "phase_id": "P03_LOCAL_DOCKER_VALKEY",
        "scenario": "cluster_smoke",
        "runtime": {"run_id": "test-run"},
        "nodes": [],
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(docker_runtime.json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(docker_runtime, "_cleanup_resources_by_label", lambda *, phase, run_id: ([], {"cleanup_remove_containers_seconds": 0.0, "cleanup_remove_networks_seconds": 0.0}))
    monkeypatch.setattr(docker_runtime, "owned_resources", lambda *, phase, run_id: [])
    report = docker_runtime.cleanup_scenario(state_path=state_path, artifacts_dir=tmp_path, out_path=tmp_path / "cleanup.json")
    assert report["status"] == "PASS"
    assert report["resources_remaining"] == []
    assert report["cleanup_timing"]["cleanup_residual_scan_seconds"] >= 0.0
    assert (tmp_path / "cleanup_report_cluster_smoke.json").exists()


def test_cleanup_removes_fault_state_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "schema_version": "v1",
        "cluster_id": "test",
        "phase_id": "P08_FAILOVER_SPLIT_BRAIN",
        "runtime": {"run_id": "test-run"},
        "nodes": [],
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(docker_runtime.json.dumps(state), encoding="utf-8")
    fault_state = tmp_path / "fault_state_fault-primary-stop.json"
    fault_state.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(docker_runtime, "_cleanup_resources_by_label", lambda *, phase, run_id: ([], {"cleanup_remove_containers_seconds": 0.0, "cleanup_remove_networks_seconds": 0.0}))
    monkeypatch.setattr(docker_runtime, "owned_resources", lambda *, phase, run_id: [])
    report = docker_runtime.cleanup_scenario(state_path=state_path, artifacts_dir=tmp_path, out_path=tmp_path / "cleanup.json")
    assert report["status"] == "PASS"
    assert not fault_state.exists()
    assert any(action["type"] == "fault_state" for action in report["cleanup_actions"])


def test_process_cleanup_records_timing_and_uses_bounded_parallelism(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    labels: list[str] = []
    state = {
        "schema_version": "v1",
        "cluster_id": "test",
        "phase_id": "P13_SCALE_LADDER_50_100",
        "scenario": "scale_50",
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
        if args[:2] == ["exec", "nodehost-a"] or args[:2] == ["exec", "nodehost-b"]:
            if args[2:4] == ["kill", "-TERM"]:
                return docker_runtime.DockerResult("", "", 0)
            if args[2:4] == ["kill", "-0"]:
                return docker_runtime.DockerResult("", "gone", 1)
            if args[2:4] == ["pgrep", "-x"]:
                return docker_runtime.DockerResult("", "", 1)
        return docker_runtime.DockerResult("", "", 0)

    monkeypatch.setattr(docker_runtime, "_bounded_parallel", fake_parallel)
    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    monkeypatch.setattr(
        docker_runtime,
        "_cleanup_resources_by_label",
        lambda *, phase, run_id: (
            [{"type": "container", "id": "nodehost-a", "action": "remove", "status": "PASS"}],
            {"cleanup_remove_containers_seconds": 0.01, "cleanup_remove_networks_seconds": 0.02},
        ),
    )
    monkeypatch.setattr(docker_runtime, "owned_resources", lambda *, phase, run_id: [])

    report = docker_runtime._cleanup_process_scenario(state=state, artifacts_dir=tmp_path, out_path=tmp_path / "cleanup.json")

    assert report["status"] == "PASS"
    assert labels == [
        "Valkey process termination",
        "Valkey process exit verification",
        "nodehost Valkey residual check",
    ]
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


def test_p10_cleanup_appends_orchestrator_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "schema_version": "v1",
        "cluster_id": "test",
        "phase_id": "P10_MULTI_HOST_ORCHESTRATION",
        "runtime": {"run_id": "test-run"},
        "nodes": [],
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(docker_runtime.json.dumps(state), encoding="utf-8")
    orch_report = {
        "schema_version": "v1",
        "artifact_type": "orchestration_report",
        "phase_id": "P10_MULTI_HOST_ORCHESTRATION",
        "run_id": "test-run",
        "status": "PASS",
        "operations": [{"operation": "prepare", "status": "PASS"}],
    }
    (tmp_path / "orchestration_report.json").write_text(docker_runtime.json.dumps(orch_report), encoding="utf-8")
    monkeypatch.setattr(docker_runtime, "_cleanup_resources_by_label", lambda *, phase, run_id: ([], {"cleanup_remove_containers_seconds": 0.0, "cleanup_remove_networks_seconds": 0.0}))
    monkeypatch.setattr(docker_runtime, "owned_resources", lambda *, phase, run_id: [])

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
    docker_runtime.write_management_ops_report(out, "P04_CLUSTER_MANAGEMENT_OPS", "management_ops", "run", operations)
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
    event = docker_runtime._event("P06_OBSERVABILITY_METRICS", "run", "sampled", "info", {"node": "n1"})
    assert event["artifact_type"] == "event"
    assert event["severity"] == "info"
    assert event["details"]["node"] == "n1"
