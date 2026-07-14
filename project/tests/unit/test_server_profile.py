from __future__ import annotations

from pathlib import Path

from valkey_scale_lab import resource
from valkey_scale_lab.config.validation import load_effective_config, validate_config_file
from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.server_profile import compute_effective_server_profile


def test_global_server_profile_defaults_to_one_b_dev_and_64mb() -> None:
    config = load_effective_config("templates/configs/scale_100.yaml")

    assert config["runtime"]["server_profile"] == "one_b_dev"
    assert config["runtime"]["valkey"]["io_threads"] == 1
    assert config["cluster"]["node_memory_limit_mb"] == 64
    assert config["_effective_server_profile"]["effective_io_threads"] == 1
    assert config["_effective_server_profile"]["effective_node_memory_limit_mb"] == 64


def test_cli_override_wins_for_io_threads_2(tmp_path: Path) -> None:
    report = validate_config_file(
        "templates/configs/scale_10.yaml",
        tmp_path / "config_validation_report.json",
        cli_overrides={"runtime": {"valkey": {"io_threads": 2, "io_threads_max_total": 64}}},
    )

    assert report["status"] == "PASS"
    assert report["requested_io_threads"] == 2
    assert report["effective_io_threads"] == 2
    assert report["requested_node_memory_limit_mb"] == 64
    assert report["effective_node_memory_limit_mb"] == 64
    assert report["io_thread_budget_status"] == "PASS"


def test_excessive_io_threads_degrades_with_reason() -> None:
    config = load_effective_config(
        "templates/configs/scale_30.yaml",
        cli_overrides={"runtime": {"valkey": {"io_threads": 99, "io_threads_max_per_node": 2, "io_threads_max_total": 60}}},
    )

    profile = compute_effective_server_profile(config, host_cpu_count=16, nodehost_count=2)

    assert profile["requested_io_threads"] == 99
    assert profile["effective_io_threads"] == 2
    assert profile["total_valkey_threads"] == 60
    assert profile["io_thread_budget_status"] == "DEGRADED_WITH_REASON"
    assert any("exceeds io_threads_max_per_node" in reason for reason in profile["io_thread_budget_reason"])


def test_resource_preflight_records_64mb_memory_and_blocks_when_insufficient(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(resource, "_docker_details", lambda: {"available": True, "server_version": "test"})
    monkeypatch.setattr(resource, "_cleanup_state_check", lambda capability_id, scenario, node_count: resource._check("previous_cleanup_state", True, {"node_count": node_count}))
    monkeypatch.setattr(resource, "_port_check", lambda base, count, name: resource._check(name, True, {"base": base, "count": count}))
    monkeypatch.setattr(resource, "_host_available_memory_mb", lambda: 1000)

    report = resource.run_resource_preflight("templates/configs/scale_30.yaml", tmp_path / "preflight.json")

    assert report["status"] == "FAIL"
    assert report["can_run"] is False
    assert report["node_memory_limit_mb"] == 64
    assert report["projected_node_memory_mb"] == 30 * 64
    assert report["host_available_memory_mb"] == 1000
    assert report["memory_budget_status"] == "FAIL"


def test_process_config_omits_io_threads_for_one_and_writes_two_with_maxmemory() -> None:
    base_node = {
        "run_id": "SERVER_PROFILE-test",
        "logical_id": "shard-0000-primary",
        "client_port": 7000,
        "cluster_bus_port": 17000,
        "requested_cluster_node_timeout_ms": 30000,
        "effective_cluster_node_timeout_ms": 30000,
        "cluster_node_timeout_source": "global",
        "cluster_node_timeout_profile": "MISSING",
        "effective_node_memory_limit_mb": 64,
    }
    nodehost = {"container_ip": "172.18.0.2"}

    text_one = docker_runtime._process_config_text({**base_node, "effective_io_threads": 1}, nodehost)
    text_two = docker_runtime._process_config_text({**base_node, "effective_io_threads": 2}, nodehost)

    assert "io-threads" not in text_one
    assert "maxmemory 64mb" in text_one
    assert "cluster-node-timeout 30000" in text_one
    assert "vslab cluster-node-timeout-source source=global" in text_one
    assert "io-threads 2" in text_two
    assert "maxmemory 64mb" in text_two
