from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab.analysis import create_analysis_summary
from valkey_scale_lab.management_matrix import REQUIRED_MANAGEMENT_OPERATIONS, write_management_matrix_fixture_artifacts
from valkey_scale_lab.report import render_report
from valkey_scale_lab.runtime import docker_runtime


def _base_required_artifacts(path: Path) -> None:
    (path / "run_summary.json").write_text(json.dumps({"capability_id": "management_matrix", "run_id": "management-matrix", "status": "PASS", "missing_metrics": []}), encoding="utf-8")
    (path / "valkey_e2e_evidence.json").write_text(json.dumps({"status": "PASS", "real_valkey": False, "valkey_versions": [], "nodes_observed": 6, "cluster_state_observed": "ok"}), encoding="utf-8")
    (path / "failover_report.json").write_text(json.dumps({"status": "SKIPPED_WITH_REASON", "failovers": [{"failover_latency_ms": "MISSING"}], "summary": {}}), encoding="utf-8")
    (path / "cleanup_report.json").write_text(json.dumps({"status": "PASS", "resources_remaining": []}), encoding="utf-8")


def test_management_writer_emits_required_contract(tmp_path: Path) -> None:
    write_management_matrix_fixture_artifacts(tmp_path, capability_id="management_matrix", run_id="management-matrix-test", scenario="management_matrix", node_count=6)

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
    write_management_matrix_fixture_artifacts(source, capability_id="management_matrix", run_id="management-matrix-test", scenario="management_matrix", node_count=6)

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


def test_canonical_management_matrix_does_not_promote_unexecuted_rows(tmp_path: Path) -> None:
    command_rows = [
        {"command_id": "cmd-meet", "command_kind": "cluster_meet", "command": ["CLUSTER", "MEET"]},
        {"command_id": "cmd-slots", "command_kind": "cluster_addslots", "command": ["CLUSTER", "ADDSLOTS"]},
        {"command_id": "cmd-replica", "command_kind": "cluster_replicate", "command": ["CLUSTER", "REPLICATE"]},
        {"command_id": "cmd-probe", "command_kind": "cluster_probe", "command": ["CLUSTER", "INFO"]},
    ]
    (tmp_path / "command_log.jsonl").write_text("\n".join(json.dumps(row) for row in command_rows) + "\n", encoding="utf-8")

    rows = [
        {
            "capability_id": "management_matrix",
            "operation_name": "create_cluster",
            "operation_status": "PASS",
            "command_count": 0,
            "command_log_refs": [],
            "source_evidence_refs": [],
            "missing_fields": [],
        },
        {
            "capability_id": "management_matrix",
            "operation_name": "remove_replica",
            "operation_status": "FAIL",
            "command_count": 0,
            "command_log_refs": [],
            "source_evidence_refs": [],
            "missing_fields": [{"field": "real_execution_verified", "status": "MISSING", "reason": "not executed"}],
        },
    ]

    docker_runtime._management_matrix_attach_setup_command_refs(rows, tmp_path)

    assert rows[0]["operation_status"] == "PASS"
    assert rows[0]["command_count"] == 4
    assert rows[0]["command_log_refs"] == [
        "command_log.jsonl#cmd-meet",
        "command_log.jsonl#cmd-probe",
        "command_log.jsonl#cmd-replica",
        "command_log.jsonl#cmd-slots",
    ]
    assert rows[1]["operation_status"] == "FAIL"
    assert rows[1]["command_count"] == 0
    assert rows[1]["missing_fields"]
