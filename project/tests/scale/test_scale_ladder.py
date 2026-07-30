from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab import resource
from valkey_scale_lab.runtime import docker_runtime


def _patch_resource_preflight_host(monkeypatch) -> None:
    monkeypatch.setattr(resource, "_docker_details", lambda: {"available": True, "server_version": "test"})
    monkeypatch.setattr(
        resource,
        "_cleanup_state_check",
        lambda capability_id, scenario, node_count: resource._check(
            "previous_cleanup_state",
            True,
            {"node_count": node_count, "capability_id": capability_id, "scenario": scenario},
        ),
    )
    monkeypatch.setattr(resource, "_port_check", lambda base, count, name: resource._check(name, True, {"base": base, "count": count}))
    monkeypatch.setattr(resource, "_host_available_memory_mb", lambda: 65536)
    monkeypatch.setattr(
        resource.os_resource,
        "getrlimit",
        lambda _kind: (
            resource.os_resource.RLIM_INFINITY,
            resource.os_resource.RLIM_INFINITY,
        ),
    )


def test_resource_preflight_reports_port_and_cleanup_checks(tmp_path: Path, monkeypatch) -> None:
    _patch_resource_preflight_host(monkeypatch)

    report = resource.run_resource_preflight("templates/configs/scale_10.yaml", tmp_path / "preflight.json")

    assert report["status"] == "PASS"
    assert report["node_count"] == 10
    assert report["capability_id"] == "scale_ladder"
    assert {check["name"] for check in report["checks"]} >= {"docker_available", "client_ports", "cluster_bus_ports"}


def test_failover_latency_exact_200_resource_preflight_allows_only_exact_200_exception(tmp_path: Path, monkeypatch) -> None:
    _patch_resource_preflight_host(monkeypatch)

    report = resource.run_resource_preflight(
        "templates/configs/scale_200.yaml",
        tmp_path / "preflight.json",
        capability_id="failover_latency_curve",
        scenario="failover_latency_curve",
        profile_id="exact-200",
    )

    assert report["status"] == "PASS"
    assert report["capability_id"] == "failover_latency_curve"
    assert report["node_count"] == 200
    assert report["dry_run"] is False
    assert report["bounded_exception"]["capability_id"] == "failover_latency_curve"
    assert report["bounded_exception"]["default_max_nodes"] == 100


def test_management_matrix_200_resource_preflight_allows_exact_200_profile_exception(tmp_path: Path, monkeypatch) -> None:
    _patch_resource_preflight_host(monkeypatch)

    report = resource.run_resource_preflight(
        "templates/configs/scale_200.yaml",
        tmp_path / "management_matrix_200_preflight.json",
        capability_id="management_matrix",
        scenario="management_matrix",
        profile_id="exact-200",
    )

    assert report["status"] == "PASS"
    assert report["capability_id"] == "management_matrix"
    assert report["scenario_name"] == "management_matrix"
    assert report["node_count"] == 200
    assert report["bounded_exception"]["capability_id"] == "management_matrix"
    assert report["bounded_exception"]["default_max_nodes"] == 100


def test_management_matrix_200_resource_preflight_rejects_wrong_200_scenario(tmp_path: Path, monkeypatch) -> None:
    _patch_resource_preflight_host(monkeypatch)

    report = resource.run_resource_preflight(
        "templates/configs/scale_200.yaml",
        tmp_path / "bad_management_matrix_200_preflight.json",
        capability_id="management_matrix",
        scenario="management_matrix_typo",
        profile_id="exact-200",
    )

    assert report["status"] == "FAIL"
    assert any(check["name"] == "exact_200_bounded_exception" and check["status"] == "FAIL" for check in report["checks"])


def test_fault_matrix_200_resource_preflight_allows_exact_200_fault_profile_exception(tmp_path: Path, monkeypatch) -> None:
    _patch_resource_preflight_host(monkeypatch)

    report = resource.run_resource_preflight(
        "templates/configs/scale_200.yaml",
        tmp_path / "fault_matrix_200_preflight.json",
        capability_id="fault_matrix",
        scenario="fault_matrix",
        profile_id="exact-200",
    )

    assert report["status"] == "PASS"
    assert report["capability_id"] == "fault_matrix"
    assert report["scenario_name"] == "fault_matrix"
    assert report["node_count"] == 200
    assert report["bounded_exception"]["capability_id"] == "fault_matrix"
    assert report["bounded_exception"]["scenario_name"] == "fault_matrix"
    assert report["bounded_exception"]["default_max_nodes"] == 100


def test_local_full_flow_resource_preflight_allows_exact_200_full_flow_exception(tmp_path: Path, monkeypatch) -> None:
    _patch_resource_preflight_host(monkeypatch)

    report = resource.run_resource_preflight(
        "templates/configs/scale_200.yaml",
        tmp_path / "local_full_flow_preflight.json",
        capability_id="local_full_flow",
        scenario="local_full_flow",
        profile_id="exact-200",
    )

    assert report["status"] == "PASS"
    assert report["capability_id"] == "local_full_flow"
    assert report["scenario_name"] == "local_full_flow"
    assert report["node_count"] == 200
    assert report["bounded_exception"]["capability_id"] == "local_full_flow"
    assert report["bounded_exception"]["scenario_name"] == "local_full_flow"
    assert report["bounded_exception"]["default_max_nodes"] == 100


def test_local_full_flow_resource_preflight_allows_exact_2000_opt_in(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_resource_preflight_host(monkeypatch)

    report = resource.run_resource_preflight(
        "templates/configs/scale_2000_local_full_flow_optin.yaml",
        tmp_path / "local_full_flow_2000_preflight.json",
        capability_id="local_full_flow",
        scenario="local_full_flow",
        profile_id="exact-2000",
        operator_opt_in=True,
        cost_acknowledged=True,
    )

    assert report["status"] == "PASS"
    assert report["node_count"] == 2000
    assert report["controlled_scale_exception"]["capability_id"] == "local_full_flow"
    assert report["controlled_scale_exception"]["scenario_name"] == "local_full_flow"
    assert report["controlled_scale_exception"]["operator_opt_in"] is True
    assert any(
        check["name"] == "exact_2000_local_full_flow_opt_in"
        and check["status"] == "PASS"
        for check in report["checks"]
    )


def test_local_full_flow_resource_preflight_rejects_exact_2000_without_opt_in(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_resource_preflight_host(monkeypatch)

    report = resource.run_resource_preflight(
        "templates/configs/scale_2000_local_full_flow_optin.yaml",
        tmp_path / "local_full_flow_2000_preflight.json",
        capability_id="local_full_flow",
        scenario="local_full_flow",
        profile_id="exact-2000",
    )

    assert report["status"] == "FAIL"
    assert any(
        check["name"] == "exact_2000_local_full_flow_opt_in"
        and check["status"] == "FAIL"
        for check in report["checks"]
    )


def test_resource_preflight_rejects_exact_2000_wrong_scenario(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_resource_preflight_host(monkeypatch)

    report = resource.run_resource_preflight(
        "templates/configs/scale_2000_local_full_flow_optin.yaml",
        tmp_path / "wrong_2000_preflight.json",
        capability_id="management_matrix",
        scenario="management_matrix",
        profile_id="exact-2000",
        operator_opt_in=True,
        cost_acknowledged=True,
    )

    assert report["status"] == "FAIL"
    assert any(
        check["name"] == "exact_2000_local_full_flow_opt_in"
        and check["status"] == "FAIL"
        for check in report["checks"]
    )


def test_fault_matrix_200_resource_preflight_rejects_wrong_200_fault_scenario(tmp_path: Path, monkeypatch) -> None:
    _patch_resource_preflight_host(monkeypatch)

    report = resource.run_resource_preflight(
        "templates/configs/scale_200.yaml",
        tmp_path / "bad_fault_matrix_200_preflight.json",
        capability_id="fault_matrix",
        scenario="fault_matrix_typo",
        profile_id="exact-200",
    )

    assert report["status"] == "FAIL"
    assert any(check["name"] == "exact_200_bounded_exception" and check["status"] == "FAIL" for check in report["checks"])


def test_resource_preflight_rejects_profile_without_exact_200_scale_exception(tmp_path: Path, monkeypatch) -> None:
    _patch_resource_preflight_host(monkeypatch)
    raw = Path("templates/configs/scale_200.yaml").read_text(encoding="utf-8")
    bad_config = tmp_path / "bad_scale_200.yaml"
    bad_config.write_text(raw.replace("bounded_exception_nodes: 200", "bounded_exception_nodes: 199"), encoding="utf-8")

    report = resource.run_resource_preflight(
        bad_config,
        tmp_path / "bad_preflight.json",
        capability_id="failover_latency_curve",
        scenario="failover_latency_curve",
        profile_id="exact-200",
    )

    assert report["status"] == "FAIL"
    assert any(check["name"] == "exact_200_bounded_exception" and check["status"] == "FAIL" for check in report["checks"])


def test_scale_ladder_artifacts_compare_two_rungs(tmp_path: Path, monkeypatch) -> None:
    expected = {"count": 10}

    def fake_cli(container: str, *args, timeout: int = 60, check: bool = True) -> str:
        if args[:2] == ("INFO", "server"):
            return "valkey_version:9.1.0\n"
        if args[:2] == ("INFO", "default"):
            return "used_memory:1000\ntotal_commands_processed:10\n"
        if args[:2] == ("CLUSTER", "INFO"):
            return f"cluster_state:ok\ncluster_known_nodes:{expected['count']}\n"
        return "OK"

    monkeypatch.setattr(docker_runtime, "run_container_cli", fake_cli)
    nodes_10 = _nodes(10)
    nodes_30 = _nodes(30)

    docker_runtime.write_scale_ladder_artifacts(tmp_path, "scale_ladder", "scale_10", "run-10", {"profile_name": "scale_10"}, nodes_10)
    expected["count"] = 30
    docker_runtime.write_scale_ladder_artifacts(tmp_path, "scale_ladder", "scale_30", "run-30", {"profile_name": "scale_30"}, nodes_30)

    report = json.loads((tmp_path / "scale_ladder_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["summary"]["rung_counts_observed"] == [10, 30]
    assert report["summary"]["comparison"]["node_count_multiplier"] == 3.0
    assert (tmp_path / "run_summary.json").exists()


def test_scale_rung_fails_when_membership_is_fragmented(tmp_path: Path, monkeypatch) -> None:
    def fake_cli(container: str, *args, timeout: int = 60, check: bool = True) -> str:
        if args[:2] == ("INFO", "server"):
            return "valkey_version:9.1.0\n"
        if args[:2] == ("INFO", "default"):
            return "used_memory:1000\ntotal_commands_processed:10\n"
        if args[:2] == ("CLUSTER", "INFO"):
            return "cluster_state:ok\ncluster_known_nodes:6\n"
        return "OK"

    monkeypatch.setattr(docker_runtime, "run_container_cli", fake_cli)
    docker_runtime.write_scale_ladder_artifacts(
        tmp_path,
        "scale_ladder",
        "scale_50",
        "run-50",
        {"profile_name": "scale_50"},
        _nodes(50),
    )

    rung = json.loads((tmp_path / "scale_rung_50.json").read_text(encoding="utf-8"))
    assert rung["status"] == "FAIL"
    assert rung["management"]["cluster_known_nodes_min"] == 6
    assert rung["management"]["cluster_known_nodes_max"] == 6


def test_scale_run_summary_uses_canonical_rung_paths(tmp_path: Path) -> None:
    docker_runtime.write_scale_run_summary(tmp_path / "run_summary.json", "scale_ladder")
    summary = json.loads((tmp_path / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["capability_id"] == "scale_ladder"
    assert "artifacts/captures/scale_ladder/resource_preflight_10.json" in summary["required_artifacts"]
    assert "artifacts/captures/scale_ladder/resource_preflight_50.json" in summary["required_artifacts"]
    assert "artifacts/captures/scale_ladder/valkey_e2e_evidence_100.json" in summary["required_artifacts"]


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
