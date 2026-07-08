from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab.analysis import create_analysis_summary
from valkey_scale_lab.management_matrix import REQUIRED_MANAGEMENT_OPERATIONS, write_management_matrix_artifacts
from valkey_scale_lab.report import render_report
from valkey_scale_lab.runtime import docker_runtime


def _base_required_artifacts(path: Path) -> None:
    (path / "phase_summary.json").write_text(json.dumps({"phase_id": "M1-S04", "run_id": "m1-s04", "status": "PASS", "missing_metrics": []}), encoding="utf-8")
    (path / "valkey_e2e_evidence.json").write_text(json.dumps({"status": "PASS", "real_valkey": False, "valkey_versions": [], "nodes_observed": 6, "cluster_state_observed": "ok"}), encoding="utf-8")
    (path / "failover_report.json").write_text(json.dumps({"status": "SKIPPED_WITH_REASON", "failovers": [{"failover_latency_ms": "MISSING"}], "summary": {}}), encoding="utf-8")
    (path / "cleanup_report.json").write_text(json.dumps({"status": "PASS", "resources_remaining": []}), encoding="utf-8")


def test_management_writer_emits_required_m1_contract(tmp_path: Path) -> None:
    write_management_matrix_artifacts(tmp_path, phase_id="M1-S04", run_id="m1-s04-test", scenario="fixture", node_count=6)

    matrix = json.loads((tmp_path / "management_ops_matrix.json").read_text(encoding="utf-8"))
    results = [json.loads(line) for line in (tmp_path / "management_operation_results.jsonl").read_text(encoding="utf-8").splitlines()]

    assert [row["operation_name"] for row in matrix["operations"]] == REQUIRED_MANAGEMENT_OPERATIONS
    assert len(results) == len(REQUIRED_MANAGEMENT_OPERATIONS)
    assert all(row["command_count"] > 0 for row in results)
    assert all(row["before_topology_snapshot_ref"] and row["after_topology_snapshot_ref"] for row in results)
    assert any(row["operation_name"] == "rolling_restart_primary_safe" and "cluster_impact_ms" in row for row in results)
    assert any(row["operation_name"] == "reshard_with_keys" and "bytes_migrated" in row for row in results)


def test_management_analysis_and_report_rendering(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _base_required_artifacts(source)
    write_management_matrix_artifacts(source, phase_id="M1-S04", run_id="m1-s04-test", scenario="fixture", node_count=6)

    analysis = create_analysis_summary(source, tmp_path / "analysis_summary.json")
    assert analysis["management_ops"]["operation_count"] == len(REQUIRED_MANAGEMENT_OPERATIONS)
    assert analysis["management_ops"]["missing_required_operations"] == []
    assert analysis["management_ops"]["topology_diff_summary"]

    index = render_report(tmp_path / "analysis_summary.json", tmp_path / "report", tmp_path / "report_index.json")
    report_names = {Path(item["path"]).name for item in index["reports"]}
    assert "management_ops_matrix.csv" in report_names
    assert "management_operation_duration.svg" in report_names
    assert "management_report_inputs" in index
    assert "管理操作矩阵" in (tmp_path / "report" / "report.md").read_text(encoding="utf-8")


def test_p04_real_smoke_emits_m1_matrix_contract_without_fake_destructive_pass(tmp_path: Path, monkeypatch) -> None:
    command_rows = [
        {"command_id": "cmd-meet", "command_kind": "cluster_meet", "command": ["CLUSTER", "MEET"]},
        {"command_id": "cmd-slots", "command_kind": "cluster_addslots", "command": ["CLUSTER", "ADDSLOTS"]},
        {"command_id": "cmd-replica", "command_kind": "cluster_replicate", "command": ["CLUSTER", "REPLICATE"]},
        {"command_id": "cmd-probe", "command_kind": "cluster_probe", "command": ["CLUSTER", "INFO"]},
    ]
    (tmp_path / "command_log.jsonl").write_text("\n".join(json.dumps(row) for row in command_rows) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        docker_runtime,
        "_p17_cluster_health",
        lambda nodes: {
            "cluster_state": "ok",
            "known_nodes": len(nodes),
            "slots_assigned": 16384,
            "slots_ok": 16384,
            "slots_fail": 0,
            "primary_count": 3,
            "replica_count": 3,
        },
    )

    def snapshot(_telemetry, phase, run_id, operation_id, label, _probe_nodes, _all_nodes):
        return {
            "schema_version": "v1",
            "phase_id": phase,
            "run_id": run_id,
            "snapshot_id": f"{operation_id}-{label}",
            "nodes": [],
            "slots": {"assigned": 16384, "ok": 16384},
        }

    monkeypatch.setattr(docker_runtime, "_p17_topology_snapshot", snapshot)

    docker_runtime.write_p04_management_matrix_contract_artifacts(
        tmp_path,
        "P04_CLUSTER_MANAGEMENT_OPS",
        "management_ops",
        "run-p04",
        [{"logical_id": f"node-{index}"} for index in range(6)],
    )

    matrix = json.loads((tmp_path / "management_ops_matrix.json").read_text(encoding="utf-8"))
    results = [json.loads(line) for line in (tmp_path / "management_operation_results.jsonl").read_text(encoding="utf-8").splitlines()]
    diffs = [json.loads(line) for line in (tmp_path / "management_topology_diffs.jsonl").read_text(encoding="utf-8").splitlines()]

    setup_rows = [row for row in results if row["operation_name"] in {"create_cluster", "meet_nodes", "add_replica"}]
    destructive_rows = [row for row in results if row["operation_name"] not in {"create_cluster", "meet_nodes", "add_replica"}]
    assert len(matrix["operations"]) == len(REQUIRED_MANAGEMENT_OPERATIONS)
    assert len(diffs) == len(REQUIRED_MANAGEMENT_OPERATIONS)
    assert all(row["operation_status"] == "PASS_NOOP_VERIFIED" and row["command_count"] > 0 for row in setup_rows)
    assert all(row["operation_status"] == "SKIPPED_WITH_REASON" and row["missing_fields"] for row in destructive_rows)
