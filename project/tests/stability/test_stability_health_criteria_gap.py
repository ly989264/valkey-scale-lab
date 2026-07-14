from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab.runtime import docker_runtime


def test_bounded_soak_fails_when_sampled_cluster_health_is_failed(tmp_path: Path, monkeypatch) -> None:
    def fake_node_command(node: dict, *args: str, timeout: int = 60) -> str:
        if args[:2] == ("CLUSTER", "INFO"):
            return "cluster_state:fail\ncluster_known_nodes:2\n"
        if args[0] == "INFO":
            return "used_memory:1000\nconnected_clients:1\ntotal_commands_processed:42\n"
        return "OK"

    monkeypatch.setattr(docker_runtime, "_node_command", fake_node_command)
    monkeypatch.setattr(docker_runtime, "run_container_cluster_cli", lambda *args, **kwargs: "OK")
    monkeypatch.setattr(docker_runtime, "_container_restart_count", lambda container: 0)
    nodes = [
        {"logical_id": "primary-a", "container_name": "node-a"},
        {"logical_id": "primary-b", "container_name": "node-b"},
    ]

    docker_runtime.write_stability_artifacts(
        tmp_path,
        "stability",
        "stability",
        "health-gap",
        {"workload": {}},
        nodes,
    )

    report = json.loads((tmp_path / "stability_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL", "sampled cluster_state=fail was admitted as a passing bounded soak"
