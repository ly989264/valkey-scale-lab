from __future__ import annotations

import csv
import json
from pathlib import Path

from valkey_scale_lab.analysis.workload_impact import build_workload_impact_analysis


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def metrics(**overrides: object) -> dict:
    base = {
        "requested_qps": 100.0,
        "achieved_qps": 50.0,
        "ok_ops": 5,
        "error_ops": 0,
        "error_rate": 0.0,
        "latency_p50_ms": 1.0,
        "latency_p90_ms": 1.4,
        "latency_p95_ms": 1.5,
        "latency_p99_ms": 2.0,
        "latency_p999_ms": "MISSING",
        "timeout_count": 0,
        "connection_error_count": 0,
        "moved_redirection_count": 0,
        "ask_redirection_count": 0,
        "cluster_down_error_count": 0,
        "readonly_error_count": 0,
        "tryagain_error_count": 0,
        "unknown_error_count": 0,
        "sample_count": 5,
        "duration_seconds": 0.1,
        "missing_reasons": {"latency_p999_ms": "fixture does not provide p999"},
    }
    base.update(overrides)
    return base


def window(entity_field: str, entity_id: str, name: str, metric_overrides: dict | None = None) -> dict:
    return {
        entity_field: entity_id,
        "window_name": name,
        "start_event_id": f"{entity_id}-{name}-start",
        "end_event_id": f"{entity_id}-{name}-end",
        "status": "PASS",
        "node_count": 6,
        "metrics": metrics(**(metric_overrides or {})),
    }


def write_management_source(root: Path) -> None:
    capability = root / "management_matrix"
    operation_id = "remove_replica-06"
    write_json(
        capability / "workload_windows.json",
        {
            "schema_version": "v1",
            "artifact_type": "workload_windows",
            "capability_id": "management_matrix",
            "run_id": "run",
            "windows": [
                window("operation_id", operation_id, "baseline"),
                window("operation_id", operation_id, "pre_event"),
                window("operation_id", operation_id, "event", {"achieved_qps": 25.0, "latency_p99_ms": 5.0}),
                window("operation_id", operation_id, "recovery", {"duration_seconds": 0.25}),
                window("operation_id", operation_id, "post_recovery", {"achieved_qps": 40.0}),
                window("operation_id", operation_id, "all_run"),
            ],
        },
    )
    write_jsonl(
        capability / "management_operation_results.jsonl",
        [
            {
                "schema_version": "v1",
                "capability_id": "management_matrix",
                "operation_id": operation_id,
                "operation_name": "remove_replica",
                "operation_status": "PASS",
                "node_count": 6,
                "workload_window_ref": f"{operation_id}:event",
            }
        ],
    )


def write_partition_fault_matrix_source(root: Path) -> None:
    capability = root / "fault_matrix"
    sample_id = "partition_fault_matrix-6-network_partition_minority"
    event_metrics = metrics(
        achieved_qps=0.0,
        ok_ops=0,
        error_ops=3,
        error_rate=1.0,
        latency_p50_ms="MISSING",
        latency_p95_ms="MISSING",
        latency_p99_ms="MISSING",
        cluster_down_error_count=3,
        missing_reasons={
            "latency_p50_ms": "No successful operations during minority partition.",
            "latency_p95_ms": "No successful operations during minority partition.",
            "latency_p99_ms": "No successful operations during minority partition.",
            "latency_p999_ms": "No successful operations during minority partition.",
        },
    )
    write_json(
        capability / "fault_workload_impact.json",
        {
            "schema_version": "v1",
            "artifact_type": "workload_impact_report",
            "capability_id": "fault_matrix",
            "run_id": "run",
            "status": "PASS",
            "comparisons": [],
            "windows": [
                window("fault_id", sample_id, "baseline"),
                window("fault_id", sample_id, "pre_event"),
                window("fault_id", sample_id, "event", event_metrics),
                window("fault_id", sample_id, "recovery", {"duration_seconds": 0.3}),
                window("fault_id", sample_id, "post_recovery", {"achieved_qps": 20.0}),
                window("fault_id", sample_id, "all_run"),
            ],
        },
    )
    write_jsonl(
        capability / "fault_operation_results.jsonl",
        [
            {
                "schema_version": "v1",
                "capability_id": "fault_matrix",
                "sample_id": sample_id,
                "fault_id": sample_id,
                "fault_type": "network_partition_minority",
                "status": "PASS",
                "node_count": 6,
            }
        ],
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_builder_derives_rows_and_csvs_from_json_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "capabilities"
    out = tmp_path / "out"
    write_management_source(source)
    write_partition_fault_matrix_source(source)

    build_workload_impact_analysis(source, out)

    cross = read_json(out / "workload_impact_analysis.json")
    rows = {row["row_id"]: row for row in cross["rows"]}
    management = rows["management_matrix:remove_replica-06"]
    assert management["derived"]["fault_or_operation_qps_ratio"] == 0.5
    assert management["derived"]["latency_p99_delta_ms"] == 3.0
    assert management["derived"]["recovery_duration_ms"] == 250.0
    partition_fault_matrix = rows["fault_matrix:partition_fault_matrix-6-network_partition_minority"]
    assert partition_fault_matrix["error_taxonomy"]["event"]["cluster_down_error_count"] == 3
    assert partition_fault_matrix["error_taxonomy"]["event"]["error_ops"] == 3
    assert partition_fault_matrix["derived"]["latency_p99_delta_ms"] == "MISSING"
    assert partition_fault_matrix["derived"]["missing_reasons"]["latency_p99_delta_ms"]

    with (out / "workload_impact_by_operation.csv").open(newline="", encoding="utf-8") as f:
        operation_rows = list(csv.DictReader(f))
    assert len(operation_rows) == cross["row_counts"]["management"]
    index = read_json(out / "csv_export_index.json")
    assert {entry["table_name"] for entry in index["exports"]} == {"operation", "fault", "latency", "error", "recovery"}


def test_builder_represents_absent_source_capabilities_with_reasons(tmp_path: Path) -> None:
    source = tmp_path / "empty_capabilities"
    source.mkdir()
    out = tmp_path / "out"

    build_workload_impact_analysis(source, out)

    cross = read_json(out / "workload_impact_analysis.json")
    assert {item["capability_id"] for item in cross["source_capability_statuses"]} >= {
        "management_matrix",
        "fault_matrix",
    }
    assert all(item["status"] == "MISSING" and item["reason"] for item in cross["source_capability_statuses"])
    missing = read_json(out / "missing_data_summary.json")
    assert missing["item_count"] >= 3
    assert all(item["reason"] for item in missing["items"])
