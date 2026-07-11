from __future__ import annotations

from pathlib import Path

import pytest

from valkey_scale_lab.orchestrator import LocalOrchestrator, OrchestratorError, assign_hosts, validate_inventory


def test_inventory_accepts_local_and_ssh_hosts() -> None:
    hosts = validate_inventory(
        {
            "hosts": [
                {"host_id": "local-a", "ip": "127.0.0.1", "docker_endpoint": "local", "labels": ["controller"]},
                {"host_id": "remote-b", "ip": "192.0.2.10", "docker_endpoint": "ssh://remote-b", "labels": ["worker"]},
            ]
        }
    )
    assert [host.host_id for host in hosts] == ["local-a", "remote-b"]


def test_inventory_rejects_duplicate_hosts() -> None:
    with pytest.raises(OrchestratorError, match="duplicate host_id"):
        validate_inventory(
            {
                "hosts": [
                    {"host_id": "local", "ip": "127.0.0.1", "docker_endpoint": "local", "labels": []},
                    {"host_id": "local", "ip": "127.0.0.2", "docker_endpoint": "local", "labels": []},
                ]
            }
        )


def test_assign_hosts_round_robins_loopback_inventory() -> None:
    hosts = validate_inventory(
        {
            "hosts": [
                {"host_id": "h1", "ip": "127.0.0.1", "docker_endpoint": "local", "labels": []},
                {"host_id": "h2", "ip": "127.0.0.1", "docker_endpoint": "local", "labels": []},
            ]
        }
    )
    nodes = [{"logical_id": f"node-{idx}"} for idx in range(4)]
    assign_hosts(nodes, hosts)
    assert [node["host_id"] for node in nodes] == ["h1", "h2", "h1", "h2"]


def test_local_orchestrator_wraps_start_and_collects_host_identity(tmp_path: Path) -> None:
    config = {"hosts": [{"host_id": "local", "ip": "127.0.0.1", "docker_endpoint": "local", "labels": ["worker"]}]}
    orch = LocalOrchestrator(config=config, phase="P10_MULTI_HOST_ORCHESTRATION", scenario="orchestrated_localhost", run_id="run")
    node = {"logical_id": "shard-0000-primary", "host_id": "local", "az_id": "az-local", "role": "primary", "client_port": 7000}
    orch.prepare()
    container_id = orch.start_node(node, lambda _: "container-1")
    orch.collect([node], tmp_path)
    report = orch.write_report(tmp_path / "orchestration_report.json", [node])

    assert container_id == "container-1"
    assert report["status"] == "PASS"
    assert report["placements"][0]["host_id"] == "local"
    assert [op["operation"] for op in report["operations"]] == ["prepare", "start", "collect"]
