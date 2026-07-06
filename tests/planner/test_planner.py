from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import pytest

from valkey_scale_lab.config.simple_yaml import parse_config_file
from valkey_scale_lab.config.validation import normalize_config
from valkey_scale_lab.planner.plan import PlannerError, build_cluster_plan, create_plan_file


def test_multi_az_plan_places_replicas_apart(tmp_path: Path) -> None:
    plan = create_plan_file("templates/configs/local_az_3x2.yaml", tmp_path / "cluster_plan.json")
    assert plan["node_count"] == 6
    assert plan["azs"] == ["az-a", "az-b"]
    assert plan["constraints"]["primary_replica_distinct_az"] is True
    assert plan["constraints"]["two_virtual_azs"] is True
    assert plan["constraints"]["primary_replica_opposite_az_pair"] is True
    by_shard: dict[str, list[dict]] = defaultdict(list)
    for node in plan["nodes"]:
        by_shard[node["shard_id"]].append(node)
    for nodes in by_shard.values():
        primary = [node for node in nodes if node["role"] == "primary"][0]
        replica = [node for node in nodes if node["role"] == "replica"][0]
        assert primary["az_id"] != replica["az_id"]


def test_plan_has_unique_names_dirs_and_ports(tmp_path: Path) -> None:
    plan = create_plan_file("templates/configs/local_az_3x2.yaml", tmp_path / "cluster_plan.json")
    for key in ["logical_id", "container_name", "data_dir", "log_dir"]:
        values = [node[key] for node in plan["nodes"]]
        assert len(values) == len(set(values))
    assert [nodehost["az_id"] for nodehost in plan["nodehosts"]] == ["az-a", "az-a", "az-b", "az-b"]
    assert {node["nodehost_id"] for node in plan["nodes"]} == {
        "nodehost-az-a-00",
        "nodehost-az-a-01",
        "nodehost-az-b-00",
        "nodehost-az-b-01",
    }
    assert all(node["nodehost_container_name"] for node in plan["nodes"])
    ports_by_host: dict[str, list[int]] = defaultdict(list)
    for node in plan["nodes"]:
        ports_by_host[node["host_id"]].extend([node["client_port"], node["cluster_bus_port"]])
    for ports in ports_by_host.values():
        assert len(ports) == len(set(ports))


def test_az_balancing_is_deterministic(tmp_path: Path) -> None:
    plan = create_plan_file("templates/configs/local_az_3x2.yaml", tmp_path / "cluster_plan.json")
    counts = Counter(node["az_id"] for node in plan["nodes"])
    assert max(counts.values()) - min(counts.values()) <= 1
    plan2 = create_plan_file("templates/configs/local_az_3x2.yaml", tmp_path / "cluster_plan2.json")
    assert plan["nodes"] == plan2["nodes"]


def test_multi_replica_plan_keeps_replicas_away_from_primary_az(tmp_path: Path) -> None:
    config = tmp_path / "multi_replica.yaml"
    text = Path("templates/configs/local_az_3x2.yaml").read_text(encoding="utf-8")
    config.write_text(text.replace("replicas_per_shard: 1", "replicas_per_shard: 2"), encoding="utf-8")
    plan = create_plan_file(config, tmp_path / "cluster_plan.json")
    assert plan["node_count"] == 9
    by_shard: dict[str, list[dict]] = defaultdict(list)
    for node in plan["nodes"]:
        by_shard[node["shard_id"]].append(node)
    for nodes in by_shard.values():
        primary = [node for node in nodes if node["role"] == "primary"][0]
        replicas = [node for node in nodes if node["role"] == "replica"]
        assert len(replicas) == 2
        assert all(replica["az_id"] != primary["az_id"] for replica in replicas)


def test_1000_node_plan_is_opt_in_dry_run(tmp_path: Path) -> None:
    plan = create_plan_file("templates/configs/scale_1000_dryrun_optin.yaml", tmp_path / "scale_1000.json", dry_run=True)
    assert plan["node_count"] == 1000
    assert plan["azs"] == ["az-a", "az-b"]
    assert len(plan["nodehosts"]) == 40
    assert plan["constraints"]["opt_in_1000"] is True
    assert plan["constraints"]["dry_run"] is True
    assert plan["constraints"]["two_virtual_azs"] is True
    assert all(node["dry_run"] is True for node in plan["nodes"])


def test_p37_250_node_plan_is_dry_run_only(tmp_path: Path) -> None:
    config = tmp_path / "scale_250_p37.yaml"
    config.write_text(p37_config_text(250, dry_run=True), encoding="utf-8")

    plan = create_plan_file(config, tmp_path / "scale_250.json", dry_run=True)

    assert plan["node_count"] == 250
    assert plan["runtime"]["dry_run"] is True
    assert plan["constraints"]["p37_200_plus_dry_run"] is True
    assert plan["constraints"]["above_200_dry_run_only"] is True
    assert plan["constraints"]["no_execution"] is True
    assert all(node["dry_run"] is True for node in plan["nodes"])


def test_p37_planner_rejects_real_above_200(tmp_path: Path) -> None:
    config = tmp_path / "scale_250_real.yaml"
    config.write_text(p37_config_text(250, dry_run=False), encoding="utf-8")

    with pytest.raises(PlannerError, match="REAL_EXECUTION_ABOVE_200_FORBIDDEN"):
        create_plan_file(config, tmp_path / "scale_250_real.json")


def test_p32_exact_200_plan_uses_bounded_exception_without_raising_cap() -> None:
    config = normalize_config(parse_config_file("templates/configs/scale_200.yaml"))

    plan = build_cluster_plan(
        config,
        config_path=Path("templates/configs/scale_200.yaml"),
        bounded_exception_phase="P32_MANAGEMENT_MATRIX_200_REAL",
        bounded_exception_scenario="strict_management_matrix_200",
    )

    assert plan["node_count"] == 200
    assert plan["constraints"]["default_node_cap"] == 100
    assert plan["constraints"]["opt_in_1000"] is False
    assert plan["constraints"]["exact_200_bounded_exception"] is True
    assert plan["constraints"]["bounded_exception_phase"] == "P32_MANAGEMENT_MATRIX_200_REAL"
    assert plan["constraints"]["bounded_exception_scenario"] == "strict_management_matrix_200"
    assert plan["runtime"]["dry_run"] is False
    assert plan["nodehost_density"]["actual_nodehost_count"] == 8


def test_p36_exact_200_plan_uses_bounded_exception_without_raising_cap() -> None:
    config = normalize_config(parse_config_file("templates/configs/scale_200.yaml"))

    plan = build_cluster_plan(
        config,
        config_path=Path("templates/configs/scale_200.yaml"),
        bounded_exception_phase="P36_FULL_FLOW_E2E_50_100_200_REAL",
        bounded_exception_scenario="strict_full_flow_200",
    )

    assert plan["node_count"] == 200
    assert plan["constraints"]["default_node_cap"] == 100
    assert plan["constraints"]["opt_in_1000"] is False
    assert plan["constraints"]["exact_200_bounded_exception"] is True
    assert plan["constraints"]["bounded_exception_phase"] == "P36_FULL_FLOW_E2E_50_100_200_REAL"
    assert plan["constraints"]["bounded_exception_scenario"] == "strict_full_flow_200"
    assert plan["runtime"]["dry_run"] is False


def test_p32_exact_200_plan_rejects_wrong_scenario() -> None:
    config = normalize_config(parse_config_file("templates/configs/scale_200.yaml"))

    with pytest.raises(PlannerError, match="node count exceeds default cap"):
        build_cluster_plan(
            config,
            config_path=Path("templates/configs/scale_200.yaml"),
            bounded_exception_phase="P32_MANAGEMENT_MATRIX_200_REAL",
            bounded_exception_scenario="strict_management_matrix_199",
        )


def test_p32_bounded_exception_rejects_non_200_node_count() -> None:
    config = normalize_config(parse_config_file("templates/configs/scale_200.yaml"))
    config["cluster"]["shards"] = 99

    with pytest.raises(PlannerError, match="node count exceeds default cap"):
        build_cluster_plan(
            config,
            config_path=Path("templates/configs/scale_200.yaml"),
            bounded_exception_phase="P32_MANAGEMENT_MATRIX_200_REAL",
            bounded_exception_scenario="strict_management_matrix_200",
        )


def test_plain_scale_200_plan_still_requires_existing_opt_in(tmp_path: Path) -> None:
    with pytest.raises(PlannerError, match="NODE_CAP_EXCEEDED"):
        create_plan_file("templates/configs/scale_200.yaml", tmp_path / "plain_scale_200_plan.json")


def test_single_az_replicas_rejected_without_non_ha_marker(tmp_path: Path) -> None:
    with pytest.raises(PlannerError, match="single-AZ replica"):
        create_plan_file("templates/configs/single_mac_6node.yaml", tmp_path / "single.json")


def test_single_az_replicas_allowed_with_non_ha_marker(tmp_path: Path) -> None:
    config = tmp_path / "single_non_ha.yaml"
    text = Path("templates/configs/single_mac_6node.yaml").read_text(encoding="utf-8")
    text = text.replace("  node_memory_limit_mb: 128", "  node_memory_limit_mb: 128\n  non_ha_allowed: true")
    config.write_text(text, encoding="utf-8")
    plan = create_plan_file(config, tmp_path / "single_non_ha.json")
    assert plan["node_count"] == 6
    assert plan["constraints"]["non_ha_single_az"] is True
    assert plan["constraints"]["primary_replica_distinct_az"] is True


def test_numeric_host_capacity_is_enforced(tmp_path: Path) -> None:
    config = tmp_path / "zero_memory.yaml"
    text = Path("templates/configs/local_az_3x2.yaml").read_text(encoding="utf-8")
    config.write_text(text.replace("memory_gb: auto", "memory_gb: 0"), encoding="utf-8")
    with pytest.raises(PlannerError, match="planner constraints failed"):
        create_plan_file(config, tmp_path / "zero_memory.json")


def test_numeric_host_capacity_can_pass(tmp_path: Path) -> None:
    config = tmp_path / "numeric_memory.yaml"
    text = Path("templates/configs/local_az_3x2.yaml").read_text(encoding="utf-8")
    config.write_text(text.replace("memory_gb: auto", "memory_gb: 2"), encoding="utf-8")
    plan = create_plan_file(config, tmp_path / "numeric_memory.json")
    assert plan["constraints"]["host_capacity_checked"] is True
    assert plan["constraints"]["host_capacity"][0]["status"] == "PASS"


def p37_config_text(target: int, *, dry_run: bool) -> str:
    return f"""
schema_version: v1
profile_name: scale_{target}_p37_dry_run
safety:
  default_max_nodes: 100
  allow_1000_nodes: false
  require_sandbox_network: true
  forbid_host_network_mutation: true
  cleanup_on_error: true
runtime:
  provider: docker
  valkey_image: valkey/valkey:9.1.0
  sandbox_mode: container_namespace
  dry_run: {str(dry_run).lower()}
hosts:
  - host_id: local
    os: auto
    arch: auto
    ip: 127.0.0.1
    docker_endpoint: local
    memory_gb: auto
    disk_gb: auto
    labels: [controller]
network:
  virtual_az_mode: multi
  azs: [az-a, az-b]
cluster:
  shards: {target}
  replicas_per_shard: 0
  port_base: 12000
  cluster_bus_port_base: 22000
  node_memory_limit_mb: 32
scale_profile:
  dry_run_only: true
  p37_dry_run_target: true
  target_nodes: {target}
  execution_mode: dry_run
workload:
  enabled: false
faults: []
""".strip() + "\n"
