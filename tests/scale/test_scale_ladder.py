from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab import resource
from valkey_scale_lab.runtime import docker_runtime


def test_resource_preflight_reports_port_and_cleanup_checks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(resource, "_docker_available", lambda: True)
    monkeypatch.setattr(resource, "_cleanup_state_check", lambda phase_id, scenario, node_count: resource._check("previous_cleanup_state", True, {"node_count": node_count}))
    monkeypatch.setattr(resource, "_port_check", lambda base, count, name: resource._check(name, True, {"base": base, "count": count}))

    report = resource.run_resource_preflight("templates/configs/scale_10.yaml", tmp_path / "preflight.json")

    assert report["status"] == "PASS"
    assert report["node_count"] == 10
    assert report["phase_id"] == "P12_SCALE_LADDER_10_30"
    assert {check["name"] for check in report["checks"]} >= {"docker_available", "client_ports", "cluster_bus_ports"}


def test_scale_ladder_artifacts_compare_two_rungs(tmp_path: Path, monkeypatch) -> None:
    def fake_cli(container: str, *args, timeout: int = 60, check: bool = True) -> str:
        if args[:2] == ("INFO", "server"):
            return "valkey_version:9.1.0\n"
        if args[:2] == ("INFO", "default"):
            return "used_memory:1000\ntotal_commands_processed:10\n"
        if args[:2] == ("CLUSTER", "INFO"):
            return "cluster_state:ok\ncluster_known_nodes:10\n"
        return "OK"

    monkeypatch.setattr(docker_runtime, "run_container_cli", fake_cli)
    nodes_10 = _nodes(10)
    nodes_30 = _nodes(30)

    docker_runtime.write_scale_ladder_artifacts(tmp_path, "P12_SCALE_LADDER_10_30", "scale_10", "run-10", {"profile_name": "scale_10"}, nodes_10)
    docker_runtime.write_scale_ladder_artifacts(tmp_path, "P12_SCALE_LADDER_10_30", "scale_30", "run-30", {"profile_name": "scale_30"}, nodes_30)

    report = json.loads((tmp_path / "scale_ladder_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["summary"]["rung_counts_observed"] == [10, 30]
    assert report["summary"]["comparison"]["node_count_multiplier"] == 3.0
    assert (tmp_path / "phase_summary.json").exists()


def test_scale_phase_summary_uses_p13_required_paths(tmp_path: Path) -> None:
    docker_runtime.write_scale_phase_summary(tmp_path / "phase_summary.json", "P13_SCALE_LADDER_50_100")
    summary = json.loads((tmp_path / "phase_summary.json").read_text(encoding="utf-8"))
    assert summary["phase_id"] == "P13_SCALE_LADDER_50_100"
    assert "artifacts/phases/P13_SCALE_LADDER_50_100/resource_preflight_50.json" in summary["required_artifacts"]
    assert "artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json" in summary["required_artifacts"]


def _nodes(count: int) -> list[dict]:
    primaries = count // 2
    nodes = []
    for idx in range(primaries):
        nodes.append(
            {
                "logical_id": f"shard-{idx:04d}-primary",
                "container_name": f"c-{idx}",
                "role": "primary",
                "az_id": f"az-{idx % 3}",
                "host_id": "local",
                "client_port": 7000 + idx,
            }
        )
    for idx in range(primaries):
        ordinal = primaries + idx
        nodes.append(
            {
                "logical_id": f"shard-{idx:04d}-replica-00",
                "container_name": f"c-{ordinal}",
                "role": "replica",
                "az_id": f"az-{ordinal % 3}",
                "host_id": "local",
                "client_port": 7000 + ordinal,
            }
        )
    return nodes
