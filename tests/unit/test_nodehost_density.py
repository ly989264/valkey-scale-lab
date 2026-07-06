from __future__ import annotations

from pathlib import Path

import pytest

from valkey_scale_lab.config.simple_yaml import parse_config_file
from valkey_scale_lab.config.validation import load_effective_config, normalize_config
from valkey_scale_lab.nodehost_density import NodehostDensityError, build_nodehost_density_plan
from valkey_scale_lab.planner.plan import build_cluster_plan, create_plan_file
from valkey_scale_lab import resource


def test_global_config_supplies_density_defaults() -> None:
    config = load_effective_config("templates/configs/scale_100.yaml")
    runtime = config["runtime"]

    assert runtime["nodehost_strategy"] == "density_limited"
    assert runtime["max_nodehosts"] == 64
    assert runtime["nodehosts_per_az"] == 2
    assert runtime["max_logical_nodes_per_nodehost"] == 25
    assert runtime["nodehost_distribution"] == "round_robin_by_az"
    assert config["_config_sources"]["merge_order"] == ["built-in defaults", "global config", "scenario config", "CLI override"]


def test_scenario_and_cli_override_global_density(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.yaml"
    text = Path("templates/configs/scale_30.yaml").read_text(encoding="utf-8")
    scenario.write_text(
        text.replace(
            "  sandbox_mode: container_namespace",
            "  sandbox_mode: container_namespace\n  max_logical_nodes_per_nodehost: 10",
        ),
        encoding="utf-8",
    )

    config = load_effective_config(
        scenario,
        cli_overrides={"runtime": {"max_logical_nodes_per_nodehost": 5}},
    )

    assert config["runtime"]["max_logical_nodes_per_nodehost"] == 5
    assert config["_config_sources"]["cli_override_applied"] is True


def test_density_planner_splits_100_and_200_nodes(tmp_path: Path) -> None:
    plan100 = create_plan_file("templates/configs/scale_100.yaml", tmp_path / "scale_100.json")
    assert plan100["nodehost_density"]["actual_nodehost_count"] == 4
    assert max(plan100["nodehost_density"]["logical_nodes_per_nodehost"].values()) == 25

    config200 = load_effective_config("templates/configs/scale_200.yaml")
    plan200 = build_cluster_plan(
        config200,
        config_path=Path("templates/configs/scale_200.yaml"),
        bounded_exception_phase="P32_MANAGEMENT_MATRIX_200_REAL",
        bounded_exception_scenario="strict_management_matrix_200",
    )
    assert plan200["nodehost_density"]["actual_nodehost_count"] == 8
    assert max(plan200["nodehost_density"]["logical_nodes_per_nodehost"].values()) == 25


def test_density_planner_fails_closed_when_max_nodehosts_too_low() -> None:
    config = load_effective_config("templates/configs/scale_200.yaml")
    config["runtime"]["max_nodehosts"] = 2

    with pytest.raises(NodehostDensityError, match="exceeds max_nodehosts"):
        build_nodehost_density_plan(
            config=config,
            nodes=_nodes_from_config(config),
            run_id="test-low-nodehost-cap",
            assign=True,
        )


def test_resource_preflight_records_density_checks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(resource, "_docker_details", lambda: {"available": True, "server_version": "test"})
    monkeypatch.setattr(resource, "_cleanup_state_check", lambda phase_id, scenario, node_count: resource._check("previous_cleanup_state", True, {"node_count": node_count}))
    monkeypatch.setattr(resource, "_port_check", lambda base, count, name: resource._check(name, True, {"base": base, "count": count}))

    report = resource.run_resource_preflight("templates/configs/scale_100.yaml", tmp_path / "preflight.json")

    assert report["status"] == "PASS"
    assert report["nodehost_density"]["actual_nodehost_count"] == 4
    names = {check["name"]: check["status"] for check in report["checks"]}
    assert names["nodehost_density_plan"] == "PASS"
    assert names["nodehost_count_limit"] == "PASS"
    assert names["nodehost_process_density"] == "PASS"
    assert names["total_port_count"] == "PASS"


def test_resource_preflight_fails_when_density_over_max(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(resource, "_docker_details", lambda: {"available": True, "server_version": "test"})
    monkeypatch.setattr(resource, "_cleanup_state_check", lambda phase_id, scenario, node_count: resource._check("previous_cleanup_state", True, {"node_count": node_count}))
    monkeypatch.setattr(resource, "_port_check", lambda base, count, name: resource._check(name, True, {"base": base, "count": count}))

    report = resource.run_resource_preflight(
        "templates/configs/scale_100.yaml",
        tmp_path / "preflight.json",
        cli_overrides={"runtime": {"max_nodehosts": 2}},
    )

    assert report["status"] == "FAIL"
    assert any(check["name"] == "nodehost_density_plan" and check["status"] == "FAIL" for check in report["checks"])


def _nodes_from_config(config: dict) -> list[dict]:
    cluster = config["cluster"]
    azs = list(config["network"]["azs"])
    nodes = []
    ordinal = 0
    for shard in range(int(cluster["shards"])):
        shard_id = f"shard-{shard:04d}"
        nodes.append(_node(cluster, shard_id, "primary", azs[shard % len(azs)], ordinal))
        ordinal += 1
    for shard in range(int(cluster["shards"])):
        shard_id = f"shard-{shard:04d}"
        nodes.append(_node(cluster, shard_id, "replica", azs[(shard + 1) % len(azs)], ordinal))
        ordinal += 1
    return nodes


def _node(cluster: dict, shard_id: str, role: str, az_id: str, ordinal: int) -> dict:
    return {
        "logical_id": f"{shard_id}-{role}",
        "shard_id": shard_id,
        "role": role,
        "az_id": az_id,
        "host_id": "local",
        "ordinal": ordinal,
        "client_port": int(cluster["port_base"]) + ordinal,
        "cluster_bus_port": int(cluster["cluster_bus_port_base"]) + ordinal,
    }
