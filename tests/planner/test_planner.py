from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import pytest

from valkey_scale_lab.planner.plan import PlannerError, create_plan_file


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
    assert [nodehost["az_id"] for nodehost in plan["nodehosts"]] == ["az-a", "az-b"]
    assert {node["nodehost_id"] for node in plan["nodes"]} == {"nodehost-az-a", "nodehost-az-b"}
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


def test_1000_node_plan_is_opt_in_dry_run(tmp_path: Path) -> None:
    plan = create_plan_file("templates/configs/scale_1000_dryrun_optin.yaml", tmp_path / "scale_1000.json", dry_run=True)
    assert plan["node_count"] == 1000
    assert plan["azs"] == ["az-a", "az-b"]
    assert len(plan["nodehosts"]) == 2
    assert plan["constraints"]["opt_in_1000"] is True
    assert plan["constraints"]["dry_run"] is True
    assert plan["constraints"]["two_virtual_azs"] is True
    assert all(node["dry_run"] is True for node in plan["nodes"])


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
