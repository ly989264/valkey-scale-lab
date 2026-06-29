from __future__ import annotations

import json
from pathlib import Path

import pytest

from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.runtime.docker_runtime import DockerRuntimeError


def test_process_bundle_generation_preserves_per_node_evidence(tmp_path: Path) -> None:
    nodehost = {
        "nodehost_id": "nodehost-az-a",
        "container_id": "cid",
        "container_name": "nodehost-a",
        "container_ip": "172.18.0.2",
    }
    nodes = [
        {
            "logical_id": "shard-0000-primary",
            "run_id": "P13_SCALE_LADDER_50_100-scale_50-20260628",
            "client_port": 7400,
            "cluster_bus_port": 17400,
            "cluster_node_timeout": "600000",
        },
        {
            "logical_id": "shard-0001-primary",
            "run_id": "P13_SCALE_LADDER_50_100-scale_50-20260628",
            "client_port": 7401,
            "cluster_bus_port": 17401,
            "cluster_node_timeout": "600000",
        },
    ]
    for node in nodes:
        docker_runtime._prepare_process_node_metadata(node, nodehost, tmp_path, node["run_id"])

    record = docker_runtime._write_nodehost_bundle(
        nodehost,
        nodes,
        tmp_path,
        "P13_SCALE_LADDER_50_100-scale_50-20260628",
    )

    bundle_dir = Path(record["bundle_artifact_dir"])
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["node_count"] == 2
    assert {item["logical_id"] for item in manifest["nodes"]} == {"shard-0000-primary", "shard-0001-primary"}
    for item in manifest["nodes"]:
        assert item["config_file"].endswith("/valkey.conf")
        assert item["data_dir"].startswith("/tmp/valkey-scale-lab/")
        assert item["log_file"].endswith("/valkey.log")
        assert item["pid_file"].endswith("/valkey.pid")
    assert (bundle_dir / "install.sh").exists()
    assert (bundle_dir / "start_all.sh").exists()
    assert (bundle_dir / "collect_pidfiles.sh").exists()
    assert "valkey-server" in (bundle_dir / "start_all.sh").read_text(encoding="utf-8")


def test_process_bundle_rejects_unsafe_path_tokens(tmp_path: Path) -> None:
    nodehost = {
        "nodehost_id": "nodehost-az-a",
        "container_id": "cid",
        "container_name": "nodehost-a",
        "container_ip": "172.18.0.2",
    }
    node = {
        "logical_id": "../escape",
        "client_port": 7400,
        "cluster_bus_port": 17400,
    }

    with pytest.raises(DockerRuntimeError, match="unsafe process runtime logical_id"):
        docker_runtime._prepare_process_node_metadata(node, nodehost, tmp_path, "safe-run")


def test_process_bootstrap_count_summary_reduces_exec_and_cp() -> None:
    config_details = {
        "config_local_generate_seconds": 0.1,
        "config_remote_install_seconds": 0.2,
        "nodehost_bulk_install_used": True,
        "docker_exec_count_before_after": {"before": 30, "after": 2},
        "docker_cp_count_before_after": {"before": 30, "after": 2},
    }
    start_details = {
        "process_start_command_seconds": 0.3,
        "pidfile_collect_seconds": 0.4,
        "nodehost_bulk_start_used": True,
        "docker_exec_count_before_after": {"before": 60, "after": 4},
    }
    nodes = [
        {
            "logical_id": f"n{idx}",
            "config_file": f"/tmp/run/n{idx}/valkey.conf",
            "config_artifact_file": f"artifacts/n{idx}.conf",
            "data_dir": f"/tmp/run/n{idx}",
            "log_file": f"/tmp/run/n{idx}/valkey.log",
            "pid_file": f"/tmp/run/n{idx}/valkey.pid",
            "pid": 1000 + idx,
        }
        for idx in range(30)
    ]

    summary = docker_runtime._process_bootstrap_batching_details(
        nodes=nodes,
        nodehosts=[{"nodehost_id": "a"}, {"nodehost_id": "b"}],
        config_prepare_details=config_details,
        process_start_details=start_details,
    )

    assert summary["nodehost_bulk_install_used"] is True
    assert summary["nodehost_bulk_start_used"] is True
    assert summary["docker_exec_count_before_after"]["before"] == 90
    assert summary["docker_exec_count_before_after"]["after"] == 6
    assert summary["docker_cp_count_before_after"]["before"] == 30
    assert summary["docker_cp_count_before_after"]["after"] == 2
    assert len(summary["per_logical_node_evidence"]) == 30
