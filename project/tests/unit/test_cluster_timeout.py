from __future__ import annotations

from pathlib import Path

from valkey_scale_lab.config.validation import load_effective_config, normalize_config, validate_config_file
from valkey_scale_lab.runtime import docker_runtime


def test_global_cluster_timeout_defaults_to_30000() -> None:
    config = load_effective_config("templates/configs/scale_30.yaml")
    timeout = config["_effective_cluster_timeout"]

    assert config["cluster"]["cluster_node_timeout_ms"] == 30000
    assert timeout["requested_cluster_node_timeout_ms"] == 30000
    assert timeout["effective_cluster_node_timeout_ms"] == 30000
    assert timeout["cluster_node_timeout_source"] == "global"
    assert timeout["cluster_node_timeout_matrix_ms"] == [5000, 10000, 15000, 30000, 60000]


def test_cluster_timeout_profile_and_scenario_and_cli_precedence() -> None:
    raw = docker_runtime.parse_config_file("templates/configs/scale_10.yaml")
    raw.setdefault("cluster", {})["cluster_node_timeout_profile"] = "management_safe"
    profiled = normalize_config(raw, scenario_config_path="templates/configs/scale_10.yaml")
    assert profiled["_effective_cluster_timeout"]["cluster_node_timeout_source"] == "profile"
    assert profiled["_effective_cluster_timeout"]["effective_cluster_node_timeout_ms"] == 30000

    raw["cluster"]["cluster_node_timeout_ms"] = 60000
    scenario = normalize_config(raw, scenario_config_path="templates/configs/scale_10.yaml")
    assert scenario["_effective_cluster_timeout"]["cluster_node_timeout_source"] == "scenario"
    assert scenario["_effective_cluster_timeout"]["effective_cluster_node_timeout_ms"] == 60000

    cli = normalize_config(
        raw,
        scenario_config_path="templates/configs/scale_10.yaml",
        cli_overrides={"cluster": {"cluster_node_timeout_ms": 10000}},
    )
    assert cli["_effective_cluster_timeout"]["cluster_node_timeout_source"] == "cli"
    assert cli["_effective_cluster_timeout"]["effective_cluster_node_timeout_ms"] == 10000


def test_invalid_cluster_timeout_values_fail_validation(tmp_path: Path) -> None:
    text = Path("templates/configs/scale_10.yaml").read_text(encoding="utf-8")
    bad = tmp_path / "bad_timeout.yaml"
    bad.write_text(text.replace("cluster_bus_port_base: 17200", "cluster_bus_port_base: 17200\n  cluster_node_timeout_ms: 0"), encoding="utf-8")

    report = validate_config_file(bad, tmp_path / "report.json")

    assert report["valid"] is False
    assert "CLUSTER_NODE_TIMEOUT_VALUE" in {error["code"] for error in report["errors"]}


def test_generated_process_config_contains_timeout_and_source() -> None:
    config = load_effective_config("templates/configs/scale_10.yaml")
    node = docker_runtime._node_specs(config, "P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE", "p43_cluster_timeout_scale_10", "p43-test")[0]
    node["run_id"] = "p43-test"
    nodehost = {"container_ip": "172.18.0.2"}

    text = docker_runtime._process_config_text(node, nodehost)

    assert "cluster-node-timeout 30000" in text
    assert "vslab cluster-node-timeout-source source=global" in text
    assert node["effective_cluster_node_timeout_ms"] == 30000
