from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab.analysis import create_analysis_summary
from valkey_scale_lab.management_matrix import REQUIRED_MANAGEMENT_OPERATIONS, write_management_matrix_fixture_artifacts


def test_analysis_preserves_missing_metrics_and_writes_baseline(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write(
        source / "run_summary.json",
        {
            "capability_id": "fault_matrix",
            "run_id": "failover-run",
            "status": "PASS",
            "missing_metrics": [
                {"metric": "split_brain_duration_ms", "status": "MISSING", "reason": "not measured"}
            ],
        },
    )
    _write(
        source / "valkey_e2e_evidence.json",
        {
            "status": "PASS",
            "real_valkey": True,
            "valkey_versions": ["9.1.0"],
            "nodes_observed": 5,
            "cluster_state_observed": "ok",
        },
    )
    _write(
        source / "failover_report.json",
        {
            "status": "PASS",
            "failovers": [{"target_logical_id": "shard-0000-primary", "failover_latency_ms": 12.5}],
            "summary": {
                "split_brain_duration_ms": {
                    "value": None,
                    "status": "MISSING",
                    "reason": "not measured",
                }
            },
        },
    )
    _write(source / "cleanup_report.json", {"status": "PASS", "resources_remaining": []})

    summary = create_analysis_summary(source, tmp_path / "analysis_summary.json")

    assert summary["status"] == "PASS"
    assert any(item["metric"] == "split_brain_duration_ms" for item in summary["missing_metrics"])
    assert summary["metrics"][1]["name"] == "failover_latency_ms"
    assert (tmp_path / "baseline_comparison.json").exists()
    assert summary["baseline_comparison"]["status"] == "NO_BASELINE_YET"


def test_analysis_aggregates_command_log(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write(source / "run_summary.json", {"capability_id": "command_audit", "run_id": "command-audit", "status": "PASS", "missing_metrics": []})
    _write(source / "valkey_e2e_evidence.json", {"status": "PASS", "real_valkey": False, "valkey_versions": [], "nodes_observed": 1, "cluster_state_observed": "ok"})
    _write(source / "failover_report.json", {"status": "PASS", "failovers": [{"failover_latency_ms": 1}], "summary": {}})
    _write(source / "cleanup_report.json", {"status": "PASS", "resources_remaining": []})
    fixture = Path("tests/fixtures/command_log/retry/command_log.jsonl")
    (source / "command_log.jsonl").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    summary = create_analysis_summary(source, tmp_path / "analysis_summary.json")

    assert summary["command_audit"]["total_commands"] == 2
    assert summary["command_audit"]["failure_count"] == 1
    assert summary["command_audit"]["retry_count"] == 1


def test_analysis_aggregates_management_matrix(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write(source / "run_summary.json", {"capability_id": "management_matrix", "run_id": "management-matrix", "status": "PASS", "missing_metrics": []})
    _write(source / "valkey_e2e_evidence.json", {"status": "PASS", "real_valkey": False, "valkey_versions": [], "nodes_observed": 6, "cluster_state_observed": "ok"})
    _write(source / "failover_report.json", {"status": "SKIPPED_WITH_REASON", "failovers": [{"failover_latency_ms": 1}], "summary": {}})
    _write(source / "cleanup_report.json", {"status": "PASS", "resources_remaining": []})
    write_management_matrix_fixture_artifacts(source, capability_id="management_matrix", run_id="management-matrix", scenario="management_matrix", node_count=6)

    summary = create_analysis_summary(source, tmp_path / "analysis_summary.json")

    assert summary["management_ops"]["operation_count"] == len(REQUIRED_MANAGEMENT_OPERATIONS)
    assert not summary["management_ops"]["missing_required_operations"]
    assert summary["management_ops"]["duration_ranking_topN"]


def test_analysis_aggregates_workload_benchmark(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write(source / "run_summary.json", {"capability_id": "workload", "run_id": "workload-analysis", "status": "PASS", "missing_metrics": []})
    _write(source / "valkey_e2e_evidence.json", {"status": "PASS", "real_valkey": False, "valkey_versions": [], "nodes_observed": 1, "cluster_state_observed": "ok"})
    _write(source / "failover_report.json", {"status": "SKIPPED_WITH_REASON", "failovers": [{"failover_latency_ms": 1}], "summary": {}})
    _write(source / "cleanup_report.json", {"status": "PASS", "resources_remaining": []})
    _write(
        source / "workload_windows.json",
        {
            "schema_version": "v1",
            "artifact_type": "workload_windows",
            "capability_id": "workload",
            "run_id": "workload-analysis",
            "status": "PASS",
            "workload_mode": "benchmark",
            "profiles_covered": ["uniform"],
            "hash_slot_coverage": {"uniform": {"full_slot_covered": True, "slot_count_observed": 16384}},
            "windows": [
                {
                    "window_name": "baseline",
                    "profile": "uniform",
                    "status": "PASS",
                    "start_event_id": "evt-start",
                    "end_event_id": "evt-end",
                    "key_slot_coverage": {"full_slot_covered": True, "slot_count_observed": 16384},
                    "metrics": {
                        "requested_qps": 10,
                        "achieved_qps": 9,
                        "throughput_ratio": 0.9,
                        "ok_ops": 9,
                        "error_ops": 0,
                        "error_rate": 0,
                        "latency_p50_ms": 1,
                        "latency_p90_ms": 2,
                        "latency_p95_ms": 3,
                        "latency_p99_ms": 4,
                        "latency_p999_ms": 5,
                        "timeout_count": 0,
                        "connection_error_count": 0,
                        "moved_count": 0,
                        "ask_count": 0,
                        "cluster_down_count": 0,
                        "readonly_count": 0,
                        "tryagain_count": 0,
                    },
                }
            ],
        },
    )

    summary = create_analysis_summary(source, tmp_path / "analysis_summary.json")

    assert summary["workload_benchmark"]["aggregate"]["achieved_qps"] == 9.0
    assert summary["workload_benchmark"]["full_slot_covered"] is True
    assert any(item["name"] == "workload_benchmark" for item in summary["findings"])


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")
