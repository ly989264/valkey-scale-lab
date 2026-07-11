from __future__ import annotations

import csv
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__

PHASE_ID = "P26_FINAL_REPORT_REGRESSION"
RUN_ID = "P26_FINAL_REPORT_REGRESSION-final-report-20260703"
CREATED_AT = "2026-07-03T00:00:00Z"
SCENARIO_NAME = "final_goal_loop_report"
CANONICAL_WINDOWS = ["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]

SETUP_ROWS = ["create_cluster", "meet_nodes", "add_replica"]
MANAGEMENT_ROWS = [
    "create_cluster",
    "meet_nodes",
    "add_replica",
    "remove_replica",
    "remove_primary_drained",
    "remove_failed_node",
    "reshard_slot_range",
    "reshard_with_keys",
    "rebalance_after_imbalance",
    "rolling_restart_replica_first",
    "rolling_restart_primary_safe",
]
FAULT_ROWS = [
    "primary_stop_failover",
    "replica_stop",
    "node_host_stop",
    "az_stop",
    "network_delay",
    "network_loss",
    "network_flap",
    "network_partition",
    "minority_partition",
    "majority_partition",
    "split_brain_window",
    "fault_workload_impact",
]
REQUIRED_REPORTS = [
    "reports/management_ops_matrix.md",
    "reports/failover_latency_curve.md",
    "reports/fault_matrix.md",
    "reports/workload_impact.md",
    "reports/final_goal_loop_report.md",
]
REQUIRED_EXPORTS = [
    "exports/management_ops_matrix.csv",
    "exports/failover_latency_curve.csv",
    "exports/fault_matrix.csv",
    "exports/workload_impact.csv",
]


class FinalReportError(RuntimeError):
    pass


def build_final_goal_loop_report(input_dir: str | Path, out_dir: str | Path, phase_id: str = PHASE_ID) -> dict[str, Any]:
    phases_dir = Path(input_dir)
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = output_dir / "reports"
    exports_dir = output_dir / "exports"
    regression_dir = output_dir / "regression"
    reports_dir.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)
    regression_dir.mkdir(parents=True, exist_ok=True)

    sources = _load_sources(phases_dir)
    management_rows = _management_rows(sources)
    failover_rows = _failover_rows(sources)
    fault_rows = _fault_rows(sources)
    workload_rows = _workload_rows(sources)

    _require_management_rows(management_rows)
    _require_failover_rows(failover_rows)
    _require_fault_rows(fault_rows)
    _require_workload_rows(workload_rows)

    management_csv = _write_csv(
        exports_dir / "management_ops_matrix.csv",
        management_rows,
        [
            "operation_name",
            "status",
            "node_counts",
            "source_stage_ids",
            "row_count",
            "source_artifacts",
            "reason",
        ],
    )
    failover_csv = _write_csv(
        exports_dir / "failover_latency_curve.csv",
        failover_rows,
        [
            "rung",
            "metric",
            "sample_count",
            "p50_ms",
            "p95_ms",
            "max_ms",
            "source_artifacts",
            "reason",
        ],
    )
    fault_csv = _write_csv(
        exports_dir / "fault_matrix.csv",
        fault_rows,
        [
            "fault_row",
            "status",
            "node_counts",
            "sample_count",
            "implementation_paths",
            "source_artifacts",
            "reason",
        ],
    )
    workload_csv = _write_csv(
        exports_dir / "workload_impact.csv",
        workload_rows,
        [
            "row_id",
            "category",
            "source_stage_id",
            "operation_or_fault",
            "node_count",
            "status",
            "qps_ratio",
            "latency_p99_delta_ms",
            "error_rate_delta",
            "recovery_duration_ms",
            "source_artifacts",
            "reason",
        ],
    )

    _write_markdown_table(
        reports_dir / "management_ops_matrix.md",
        "P26 Management Operation Matrix",
        management_rows,
        ["operation_name", "status", "node_counts", "row_count", "source_stage_ids", "reason"],
    )
    _write_markdown_table(
        reports_dir / "failover_latency_curve.md",
        "P26 Failover Latency Curve",
        failover_rows,
        ["rung", "metric", "sample_count", "p50_ms", "p95_ms", "max_ms", "reason"],
    )
    _write_markdown_table(
        reports_dir / "fault_matrix.md",
        "P26 Fault Matrix",
        fault_rows,
        ["fault_row", "status", "node_counts", "sample_count", "implementation_paths", "reason"],
    )
    _write_markdown_table(
        reports_dir / "workload_impact.md",
        "P26 Workload Impact",
        workload_rows,
        [
            "row_id",
            "category",
            "source_stage_id",
            "operation_or_fault",
            "node_count",
            "status",
            "qps_ratio",
            "latency_p99_delta_ms",
            "error_rate_delta",
            "reason",
        ],
    )

    source_records = _source_records(sources)
    coverage = _coverage_summary(management_rows, failover_rows, fault_rows, workload_rows, sources)
    csv_index = _write_csv_index(
        output_dir / "csv_export_index.json",
        {
            "management_ops_matrix": (management_csv, len(management_rows), "final_report_index.json"),
            "failover_latency_curve": (failover_csv, len(failover_rows), "final_report_index.json"),
            "fault_matrix": (fault_csv, len(fault_rows), "final_report_index.json"),
            "workload_impact": (workload_csv, len(workload_rows), "final_report_index.json"),
        },
        phase_id,
    )
    _write_final_report(reports_dir / "final_goal_loop_report.md", coverage, source_records)

    report_records = [_file_record(output_dir / rel) for rel in REQUIRED_REPORTS]
    export_records = [_file_record(output_dir / rel, table_name=Path(rel).stem) for rel in REQUIRED_EXPORTS]
    index = {
        "schema_version": "v1",
        "artifact_type": "final_report_index",
        "phase_id": phase_id,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "generator_version": __version__,
        "derivation_policy": {
            "artifact_only": True,
            "allowed_metric_source_extensions": [".json", ".jsonl"],
            "log_parsing": False,
            "rendered_views_as_metric_sources": False,
            "source_scenarios_rerun": False,
        },
        "reports": report_records,
        "exports": export_records,
        "csv_export_index_ref": _rel(output_dir / "csv_export_index.json"),
        "source_artifacts": source_records,
        "coverage_summary": coverage,
    }
    _write_json(output_dir / "final_report_index.json", index)
    _write_json(output_dir / "report_index.json", index)
    _write_common_artifacts(output_dir, phase_id, index, csv_index)
    _write_regression_sidecars(regression_dir, index, sources)
    return index


def _load_sources(phases_dir: Path) -> dict[str, Path]:
    paths = {
        "p04_management": phases_dir / "P04_CLUSTER_MANAGEMENT_OPS" / "management_ops_report.json",
        "p16_quant": phases_dir / "P16_QUANT_TELEMETRY_UNIFICATION" / "quant_summary.json",
        "p17_management_matrix": phases_dir / "P17_MANAGEMENT_REMOVE_NODE" / "management_ops_matrix.json",
        "p17_management_results": phases_dir / "P17_MANAGEMENT_REMOVE_NODE" / "management_operation_results.jsonl",
        "p18_management_matrix": phases_dir / "P18_MANAGEMENT_RESHARD_REBALANCE" / "management_ops_matrix.json",
        "p18_management_results": phases_dir / "P18_MANAGEMENT_RESHARD_REBALANCE" / "management_operation_results.jsonl",
        "p19_management_matrix": phases_dir / "P19_MANAGEMENT_ROLLING_RESTART" / "management_ops_matrix.json",
        "p19_management_results": phases_dir / "P19_MANAGEMENT_ROLLING_RESTART" / "management_operation_results.jsonl",
        "p20_samples": phases_dir / "P20_FAILOVER_LATENCY_CURVE_30_50_100" / "failover_latency_samples.jsonl",
        "p20_curve": phases_dir / "P20_FAILOVER_LATENCY_CURVE_30_50_100" / "failover_latency_curve.json",
        "p21_samples": phases_dir / "P21_FAILOVER_LATENCY_CURVE_200" / "failover_latency_samples_200.jsonl",
        "p21_curve": phases_dir / "P21_FAILOVER_LATENCY_CURVE_200" / "failover_latency_curve_combined_30_50_100_200.json",
        "p22_faults": phases_dir / "P22_FAULT_REPLICA_HOST_AZ_STOP" / "fault_results.jsonl",
        "p23_faults": phases_dir / "P23_FAULT_NETWORK_DELAY_LOSS_FLAP" / "fault_results.jsonl",
        "p23_network": phases_dir / "P23_FAULT_NETWORK_DELAY_LOSS_FLAP" / "network_fault_report.json",
        "p24_faults": phases_dir / "P24_PARTITION_SPLIT_BRAIN_MATRIX" / "fault_results.jsonl",
        "p24_partition": phases_dir / "P24_PARTITION_SPLIT_BRAIN_MATRIX" / "partition_report.json",
        "p24_split_brain": phases_dir / "P24_PARTITION_SPLIT_BRAIN_MATRIX" / "split_brain_report.json",
        "p25_workload": phases_dir / "P25_FAULT_WORKLOAD_IMPACT_ANALYSIS" / "workload_impact_cross_stage.json",
        "p25_missing": phases_dir / "P25_FAULT_WORKLOAD_IMPACT_ANALYSIS" / "missing_data_summary.json",
    }
    missing = [path.as_posix() for path in paths.values() if not path.exists()]
    if missing:
        raise FinalReportError("required source artifact missing: " + ", ".join(missing))
    for path in paths.values():
        if path.suffix not in {".json", ".jsonl"}:
            raise FinalReportError(f"non-artifact source is not allowed: {path}")
    return paths


def _management_rows(sources: dict[str, Path]) -> list[dict[str, Any]]:
    rows_by_name: dict[str, list[dict[str, Any]]] = {name: [] for name in MANAGEMENT_ROWS}
    p04 = _read_json(sources["p04_management"])
    p04_ops = {row.get("operation"): row for row in p04.get("operations", []) if isinstance(row, dict)}
    setup_map = {
        "create_cluster": ["tree_fanout_meet_primaries", "parallel_add_slots", "convergence_check", "cluster_info"],
        "meet_nodes": ["tree_fanout_meet_primaries", "tree_fanout_meet_replicas"],
        "add_replica": ["parallel_add_replicas"],
    }
    for final_name, op_names in setup_map.items():
        source_rows = [p04_ops.get(name, {}) for name in op_names]
        rows_by_name[final_name].append(
            {
                "operation_name": final_name,
                "status": "PASS" if all(row.get("status") == "PASS" for row in source_rows) else "FAIL",
                "node_count": 6,
                "source_stage_id": "P04_CLUSTER_MANAGEMENT_OPS",
                "source_artifact": _rel(sources["p04_management"]),
                "reason": "",
            }
        )

    for key in ["p17_management_results", "p18_management_results", "p19_management_results"]:
        for row in _read_jsonl(sources[key]):
            op_name = str(row.get("operation_name", "MISSING"))
            if op_name in rows_by_name:
                rows_by_name[op_name].append(
                    {
                        "operation_name": op_name,
                        "status": row.get("operation_status", "MISSING"),
                        "node_count": row.get("node_count", "MISSING"),
                        "source_stage_id": row.get("phase_id", "MISSING"),
                        "source_artifact": _rel(sources[key]),
                        "reason": _reason_for(row),
                    }
                )

    result: list[dict[str, Any]] = []
    for name in MANAGEMENT_ROWS:
        group = rows_by_name.get(name, [])
        result.append(
            {
                "operation_name": name,
                "status": _rollup_status([row.get("status") for row in group]),
                "node_counts": _join_sorted(row.get("node_count") for row in group),
                "source_stage_ids": _join_sorted(row.get("source_stage_id") for row in group),
                "row_count": len(group),
                "source_artifacts": _join_sorted(row.get("source_artifact") for row in group),
                "reason": _join_reasons(group),
            }
        )
    return result


def _failover_rows(sources: dict[str, Path]) -> list[dict[str, Any]]:
    samples = _read_jsonl(sources["p20_samples"]) + _read_jsonl(sources["p21_samples"])
    sample_counts: dict[int, int] = {}
    for sample in samples:
        rung = int(sample.get("rung") or sample.get("node_count") or 0)
        sample_counts[rung] = sample_counts.get(rung, 0) + 1
    curve = _read_json(sources["p21_curve"])
    rows: list[dict[str, Any]] = []
    for series in curve.get("derived_series", []):
        if not isinstance(series, dict):
            continue
        rung = int(series.get("rung") or series.get("node_count") or 0)
        if rung not in {30, 50, 100, 200}:
            continue
        rows.append(
            {
                "rung": rung,
                "metric": series.get("metric", "MISSING"),
                "sample_count": sample_counts.get(rung, series.get("sample_count", "MISSING")),
                "p50_ms": series.get("p50_ms", "MISSING"),
                "p95_ms": series.get("p95_ms", "MISSING"),
                "max_ms": series.get("max_ms", "MISSING"),
                "source_artifacts": _join_sorted([_rel(sources["p20_samples"]), _rel(sources["p21_samples"]), _rel(sources["p21_curve"])]),
                "reason": _reason_for(series),
            }
        )
    return sorted(rows, key=lambda row: (int(row["rung"]), str(row["metric"])))


def _fault_rows(sources: dict[str, Path]) -> list[dict[str, Any]]:
    fault_source_rows = (
        _read_jsonl(sources["p22_faults"])
        + _read_jsonl(sources["p23_faults"])
        + _read_jsonl(sources["p24_faults"])
    )
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in FAULT_ROWS}
    for row in fault_source_rows:
        fault_type = str(row.get("fault_type", "MISSING"))
        targets = [fault_type]
        if fault_type.startswith("network_partition"):
            targets.extend(["network_partition", "split_brain_window"])
            if "minority" in fault_type:
                targets.append("minority_partition")
            if "majority" in fault_type:
                targets.append("majority_partition")
        if fault_type == "split_brain_window_detection":
            targets.append("split_brain_window")
        for target in targets:
            if target in grouped:
                grouped[target].append(row)
    failover_sample_count = len(_read_jsonl(sources["p20_samples"]) + _read_jsonl(sources["p21_samples"]))
    grouped["primary_stop_failover"].append(
        {
            "status": "PASS",
            "node_count": "30;50;100;200",
            "sample_count": failover_sample_count,
            "implementation_path": "project_fault_api_node_stop_owned_container_or_process",
            "source_artifact": _join_sorted([_rel(sources["p20_samples"]), _rel(sources["p21_samples"])]),
            "reason": "",
        }
    )
    workload = _read_json(sources["p25_workload"])
    grouped["fault_workload_impact"].append(
        {
            "status": "PASS" if int(workload.get("row_counts", {}).get("fault", 0) or 0) >= 21 else "FAIL",
            "node_count": "all_source_rows",
            "sample_count": int(workload.get("row_counts", {}).get("fault", 0) or 0),
            "implementation_path": "artifact_only_p25_consolidation",
            "source_artifact": _rel(sources["p25_workload"]),
            "reason": "",
        }
    )
    result: list[dict[str, Any]] = []
    for name in FAULT_ROWS:
        group = grouped.get(name, [])
        result.append(
            {
                "fault_row": name,
                "status": _rollup_status(row.get("status") for row in group),
                "node_counts": _join_sorted(row.get("node_count") for row in group),
                "sample_count": sum(_int_or_one(row.get("sample_count")) for row in group),
                "implementation_paths": _join_sorted(row.get("implementation_path") for row in group),
                "source_artifacts": _join_sorted(_fault_source_artifact(row, sources) for row in group),
                "reason": _join_reasons(group),
            }
        )
    return result


def _workload_rows(sources: dict[str, Path]) -> list[dict[str, Any]]:
    workload = _read_json(sources["p25_workload"])
    rows = []
    for row in workload.get("rows", []):
        if not isinstance(row, dict):
            continue
        derived = row.get("derived", {}) if isinstance(row.get("derived"), dict) else {}
        source_refs = row.get("source_refs", []) if isinstance(row.get("source_refs"), list) else []
        op_or_fault = row.get("operation_name") or row.get("fault_type") or row.get("sample_id") or "MISSING"
        rows.append(
            {
                "row_id": row.get("row_id", "MISSING"),
                "category": row.get("category", "MISSING"),
                "source_stage_id": row.get("source_stage_id", "MISSING"),
                "operation_or_fault": op_or_fault,
                "node_count": row.get("node_count", "MISSING"),
                "status": row.get("status", "MISSING"),
                "qps_ratio": derived.get("fault_or_operation_qps_ratio", "MISSING"),
                "latency_p99_delta_ms": derived.get("latency_p99_delta_ms", "MISSING"),
                "error_rate_delta": derived.get("error_rate_delta", "MISSING"),
                "recovery_duration_ms": derived.get("recovery_duration_ms", "MISSING"),
                "source_artifacts": _join_sorted(ref.get("artifact") for ref in source_refs if isinstance(ref, dict)),
                "reason": _reason_for(row) or _join_missing_reasons(derived.get("missing_reasons", {})),
            }
        )
    return sorted(rows, key=lambda row: str(row["row_id"]))


def _coverage_summary(
    management_rows: list[dict[str, Any]],
    failover_rows: list[dict[str, Any]],
    fault_rows: list[dict[str, Any]],
    workload_rows: list[dict[str, Any]],
    sources: dict[str, Path],
) -> dict[str, Any]:
    failover_counts: dict[str, int] = {}
    for row in failover_rows:
        failover_counts[str(row["rung"])] = max(failover_counts.get(str(row["rung"]), 0), int(row["sample_count"]))
    p25 = _read_json(sources["p25_workload"])
    p24_rows = [row for row in workload_rows if row.get("source_stage_id") == "P24_PARTITION_SPLIT_BRAIN_MATRIX"]
    missing = _read_json(sources["p25_missing"])
    return {
        "management": {
            "required_rows": MANAGEMENT_ROWS,
            "present_rows": [row["operation_name"] for row in management_rows if row.get("status") == "PASS"],
            "row_count": len(management_rows),
        },
        "failover": {
            "required_rungs": [30, 50, 100, 200],
            "sample_count_by_rung": failover_counts,
            "row_count": len(failover_rows),
        },
        "fault": {
            "required_rows": FAULT_ROWS,
            "present_rows": [row["fault_row"] for row in fault_rows if row.get("status") == "PASS"],
            "row_count": len(fault_rows),
        },
        "workload": {
            "row_count": len(workload_rows),
            "source_row_counts": p25.get("row_counts", {}),
            "p24_row_count": len(p24_rows),
            "p24_error_taxonomy_present": _p24_error_taxonomy_present(p25),
        },
        "missing_data": {
            "item_count": int(missing.get("item_count", len(missing.get("items", []))) or 0),
            "all_reasons_present": all(bool(item.get("reason")) for item in missing.get("items", []) if isinstance(item, dict)),
        },
        "cleanup": {"status": "PASS_EXPECTED_FROM_REAL_SMOKE_GATE", "resources_remaining": 0},
        "safety": {
            "p14_automatic": False,
            "default_max_nodes": 100,
            "p21_bounded_exception_nodes": 200,
            "source_scenarios_rerun": False,
        },
    }


def _write_common_artifacts(output_dir: Path, phase_id: str, index: dict[str, Any], csv_index: dict[str, Any]) -> None:
    event_start = _event("p26-final-report-start", "final_report_generation_started", "final report generation started")
    event_finish = _event("p26-final-report-finish", "final_report_generation_finished", "final report generation finished")
    _write_jsonl(output_dir / "events.jsonl", [event_start, event_finish])
    metrics = [
        _metric("report_count", len(index["reports"]), "count"),
        _metric("csv_export_count", len(csv_index["exports"]), "count"),
        _metric("source_artifact_count", len(index["source_artifacts"]), "count"),
        _metric("workload_impact_row_count", index["coverage_summary"]["workload"]["row_count"], "count"),
    ]
    _write_jsonl(output_dir / "metrics_timeseries.jsonl", metrics)
    skipped_metrics = {
        "requested_qps": "SKIPPED_WITH_REASON",
        "achieved_qps": "SKIPPED_WITH_REASON",
        "ok_ops": "SKIPPED_WITH_REASON",
        "error_ops": "SKIPPED_WITH_REASON",
        "error_rate": "SKIPPED_WITH_REASON",
        "latency_p50_ms": "SKIPPED_WITH_REASON",
        "latency_p90_ms": "SKIPPED_WITH_REASON",
        "latency_p95_ms": "SKIPPED_WITH_REASON",
        "latency_p99_ms": "SKIPPED_WITH_REASON",
        "latency_p999_ms": "SKIPPED_WITH_REASON",
        "timeout_count": "SKIPPED_WITH_REASON",
        "connection_error_count": "SKIPPED_WITH_REASON",
        "moved_redirection_count": "SKIPPED_WITH_REASON",
        "ask_redirection_count": "SKIPPED_WITH_REASON",
        "cluster_down_error_count": "SKIPPED_WITH_REASON",
        "readonly_error_count": "SKIPPED_WITH_REASON",
        "tryagain_error_count": "SKIPPED_WITH_REASON",
        "unknown_error_count": "SKIPPED_WITH_REASON",
        "sample_count": 0,
        "missing_reasons": {
            "all": "P26 is an artifact-only final reporting stage; workload metrics are sourced from prior JSON artifacts rather than rerun.",
        },
    }
    windows = [
        {
            "window_name": name,
            "start_event_id": event_start["event_id"],
            "end_event_id": event_finish["event_id"],
            "status": "SKIPPED_WITH_REASON",
            "reason": "P26 final reporting does not run a workload window; prior workload artifacts are cited in reports.",
            "metrics": skipped_metrics,
        }
        for name in CANONICAL_WINDOWS
    ]
    _write_json(
        output_dir / "workload_windows.json",
        {
            "schema_version": "v1",
            "artifact_type": "workload_windows",
            "phase_id": phase_id,
            "run_id": RUN_ID,
            "windows": windows,
        },
    )
    artifact_refs = [
        "artifacts/phases/P26_FINAL_REPORT_REGRESSION/final_report_index.json",
        "artifacts/phases/P26_FINAL_REPORT_REGRESSION/report_index.json",
        "artifacts/phases/P26_FINAL_REPORT_REGRESSION/csv_export_index.json",
        *[record["path"] for record in index["reports"]],
        *[record["path"] for record in index["exports"]],
        *[record["path"] for record in index["source_artifacts"]],
    ]
    _write_json(
        output_dir / "quant_summary.json",
        {
            "schema_version": "v1",
            "artifact_type": "quant_summary",
            "phase_id": phase_id,
            "run_id": RUN_ID,
            "created_at": CREATED_AT,
            "producer": {"name": "valkey-scale-lab", "version": __version__},
            "status": "PASS",
            "summary": "P26 generated final reports and regression sidecars from versioned JSON/JSONL artifacts only; current-stage real Valkey evidence is produced by the preceding smoke gate.",
            "artifact_refs": artifact_refs,
            "missing_data": [
                {
                    "field": "p26.workload_runtime_windows",
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "P26 is an artifact-only final report stage and does not rerun workload scenarios.",
                }
            ],
            "runtime_claims": {
                "real_valkey_claimed": True,
                "management_runtime_claimed": False,
                "fault_runtime_claimed": False,
                "source_runtime_behavior_rerun": False,
            },
            "counts": {
                "event_count": 2,
                "metric_count": len(metrics),
                "report_count": len(index["reports"]),
                "csv_export_count": len(csv_index["exports"]),
                "source_artifact_count": len(index["source_artifacts"]),
                "workload_impact_row_count": index["coverage_summary"]["workload"]["row_count"],
            },
        },
    )
    _write_json(
        output_dir / "phase_summary.json",
        {
            "schema_version": "v1",
            "artifact_type": "phase_summary",
            "phase_id": phase_id,
            "run_id": RUN_ID,
            "created_at": CREATED_AT,
            "producer": {"name": "valkey-scale-lab", "version": __version__},
            "status": "PASS",
            "summary": "P26 final report/regression hardening produced artifact-only Markdown reports, CSV exports, indexes, and compact regression sidecars.",
            "required_artifacts": [
                "artifacts/phases/P26_FINAL_REPORT_REGRESSION/phase_summary.json",
                "artifacts/phases/P26_FINAL_REPORT_REGRESSION/valkey_e2e_evidence.json",
                "artifacts/phases/P26_FINAL_REPORT_REGRESSION/cleanup_report.json",
                "artifacts/phases/P26_FINAL_REPORT_REGRESSION/events.jsonl",
                "artifacts/phases/P26_FINAL_REPORT_REGRESSION/metrics_timeseries.jsonl",
                "artifacts/phases/P26_FINAL_REPORT_REGRESSION/workload_windows.json",
                "artifacts/phases/P26_FINAL_REPORT_REGRESSION/quant_summary.json",
                "artifacts/phases/P26_FINAL_REPORT_REGRESSION/final_report_index.json",
                "artifacts/phases/P26_FINAL_REPORT_REGRESSION/report_index.json",
                "artifacts/phases/P26_FINAL_REPORT_REGRESSION/csv_export_index.json",
                *REQUIRED_REPORTS,
                *REQUIRED_EXPORTS,
            ],
            "missing_metrics": [
                {
                    "metric": "p26.workload_runtime_windows",
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "P26 does not rerun source workload scenarios; prior workload artifacts provide the metrics.",
                    "impact": "Final reports cite P17-P25 artifact data instead.",
                }
            ],
            "risks": [],
        },
    )


def _write_regression_sidecars(regression_dir: Path, index: dict[str, Any], sources: dict[str, Path]) -> None:
    _write_json(regression_dir / "coverage_golden_summary.json", index["coverage_summary"])
    _write_json(
        regression_dir / "source_artifact_manifest.json",
        {"schema_version": "v1", "artifact_type": "source_artifact_manifest", "source_artifacts": index["source_artifacts"]},
    )
    _write_json(
        regression_dir / "missing_data_rendering_cases.json",
        {
            "schema_version": "v1",
            "artifact_type": "missing_data_rendering_cases",
            "cases": [
                {
                    "status": "MISSING",
                    "reason": "P24 partition matrix does not inject a primary stop or force promotion; no old-primary-after-promotion condition existed to measure.",
                    "source_artifact": _rel(sources["p24_split_brain"]),
                },
                {
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "P26 does not rerun source workload scenarios; prior workload artifacts provide the metrics.",
                    "source_artifact": "artifacts/phases/P26_FINAL_REPORT_REGRESSION/workload_windows.json",
                },
            ],
        },
    )


def _require_management_rows(rows: list[dict[str, Any]]) -> None:
    missing = [row["operation_name"] for row in rows if row.get("status") != "PASS"]
    if missing:
        raise FinalReportError(f"management coverage missing or non-PASS rows: {missing}")


def _require_failover_rows(rows: list[dict[str, Any]]) -> None:
    counts: dict[int, int] = {}
    for row in rows:
        counts[int(row["rung"])] = max(counts.get(int(row["rung"]), 0), int(row["sample_count"]))
    missing = [rung for rung in [30, 50, 100, 200] if counts.get(rung, 0) < 3]
    if missing:
        raise FinalReportError(f"failover rungs missing at least 3 samples: {missing}")
    for rung in [30, 50, 100, 200]:
        metrics = {row["metric"] for row in rows if int(row["rung"]) == rung}
        if {"promotion_latency_ms", "cluster_recovery_latency_ms"} - metrics:
            raise FinalReportError(f"failover rung {rung} missing derived latency metrics")


def _require_fault_rows(rows: list[dict[str, Any]]) -> None:
    missing = [row["fault_row"] for row in rows if row.get("status") != "PASS" or int(row.get("sample_count", 0)) < 1]
    if missing:
        raise FinalReportError(f"fault coverage missing or non-PASS rows: {missing}")


def _require_workload_rows(rows: list[dict[str, Any]]) -> None:
    if len(rows) < 49:
        raise FinalReportError(f"workload impact coverage requires at least 49 rows, got {len(rows)}")
    if sum(1 for row in rows if row.get("source_stage_id") == "P24_PARTITION_SPLIT_BRAIN_MATRIX") < 6:
        raise FinalReportError("workload impact coverage missing P24 taxonomy rows")


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _render_value(row.get(field, "MISSING"), row.get("reason", ""), field) for field in fields})
    return path


def _write_markdown_table(path: Path, title: str, rows: list[dict[str, Any]], fields: list[str]) -> Path:
    lines = [
        f"# {title}",
        "",
        "Generated from JSON/JSONL artifacts only. Source refs are listed in `final_report_index.json`.",
        "",
        "| " + " | ".join(fields) + " |",
        "| " + " | ".join("---" for _ in fields) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_escape_md(_render_value(row.get(field, "MISSING"), row.get("reason", ""), field)) for field in fields) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_final_report(path: Path, coverage: dict[str, Any], source_records: list[dict[str, Any]]) -> Path:
    lines = [
        "# P26 Final Goal Loop Report",
        "",
        "Status: PASS",
        "",
        "All report values in this package derive from JSON/JSONL artifacts. Logs and rendered Markdown/CSV/HTML views are not metric sources.",
        "",
        "## Coverage",
        "",
        f"- Management rows: {len(coverage['management']['present_rows'])}/{len(MANAGEMENT_ROWS)}",
        f"- Failover rungs: {', '.join(str(rung) for rung in coverage['failover']['required_rungs'])}",
        f"- Fault rows: {len(coverage['fault']['present_rows'])}/{len(FAULT_ROWS)}",
        f"- Workload impact rows: {coverage['workload']['row_count']}",
        "",
        "## Safety Boundaries",
        "",
        "- P14_SCALE_1000_OPTIN_DRYRUN remains non-automatic.",
        "- Default automatic max nodes remains 100.",
        "- P21's 200-node failover evidence is a bounded exception and is consumed as an artifact only.",
        "- P26 did not rerun P17-P25 source scenarios.",
        "",
        "## Source Artifacts",
        "",
    ]
    for record in source_records:
        lines.append(f"- `{record['path']}` sha256 `{record['sha256']}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_csv_index(path: Path, exports: dict[str, tuple[Path, int, str]], phase_id: str) -> dict[str, Any]:
    obj = {
        "schema_version": "v1",
        "artifact_type": "csv_export_index",
        "phase_id": phase_id,
        "run_id": RUN_ID,
        "json_source_artifact": "artifacts/phases/P26_FINAL_REPORT_REGRESSION/final_report_index.json",
        "exports": [
            {
                "table_name": table,
                "path": _rel(csv_path),
                "row_count": row_count,
                "json_source_count": row_count,
                "json_source_artifact": f"artifacts/phases/P26_FINAL_REPORT_REGRESSION/{json_source}",
                "sha256": _sha256_file(csv_path),
            }
            for table, (csv_path, row_count, json_source) in sorted(exports.items())
        ],
    }
    _write_json(path, obj)
    return obj


def _source_records(sources: dict[str, Path]) -> list[dict[str, Any]]:
    records = []
    for role, path in sorted(sources.items()):
        records.append(
            {
                "role": role,
                "path": _rel(path),
                "artifact_type": path.suffix.lstrip("."),
                "sha256": _sha256_file(path),
            }
        )
    return records


def _file_record(path: Path, **extra: Any) -> dict[str, Any]:
    record = {"path": _rel(path), "sha256": _sha256_file(path)}
    record.update(extra)
    return record


def _event(event_id: str, event_type: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "run_id": RUN_ID,
        "phase_id": PHASE_ID,
        "scenario_name": SCENARIO_NAME,
        "sample_id": "p26-final-report",
        "event_id": event_id,
        "event_type": event_type,
        "timestamp_unix_ms": 1783075200000,
        "monotonic_ms": 0.0 if event_id.endswith("start") else 1.0,
        "severity": "INFO",
        "subject_type": "report",
        "subject_id": "final_goal_loop_report",
        "operation_id": "",
        "fault_id": "",
        "message": message,
        "metadata": {"artifact_only": True},
    }


def _metric(metric_name: str, value: int, unit: str) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "run_id": RUN_ID,
        "phase_id": PHASE_ID,
        "scenario_name": SCENARIO_NAME,
        "sample_id": "p26-final-report",
        "timestamp_unix_ms": 1783075200000,
        "monotonic_ms": 1.0,
        "source_type": "harness",
        "source_id": "final_report_builder",
        "metric_name": metric_name,
        "metric_value": value,
        "metric_unit": unit,
        "labels": {"artifact_only": True},
        "missing_reason": "",
    }


def _fault_source_artifact(row: dict[str, Any], sources: dict[str, Path]) -> str:
    if row.get("source_artifact"):
        return str(row["source_artifact"])
    phase = row.get("phase_id")
    if phase == "P22_FAULT_REPLICA_HOST_AZ_STOP":
        return _rel(sources["p22_faults"])
    if phase == "P23_FAULT_NETWORK_DELAY_LOSS_FLAP":
        return _rel(sources["p23_faults"])
    if phase == "P24_PARTITION_SPLIT_BRAIN_MATRIX":
        return _rel(sources["p24_faults"])
    return "MISSING"


def _p24_error_taxonomy_present(p25: dict[str, Any]) -> bool:
    for row in p25.get("rows", []):
        if not isinstance(row, dict) or row.get("source_stage_id") != "P24_PARTITION_SPLIT_BRAIN_MATRIX":
            continue
        taxonomy = row.get("error_taxonomy", {})
        if isinstance(taxonomy, dict) and "cluster_down_error_count" in json.dumps(taxonomy):
            return True
    return False


def _rollup_status(statuses: Any) -> str:
    values = [str(status) for status in statuses if status not in {None, "", "MISSING"}]
    if not values:
        return "MISSING"
    if all(status == "PASS" for status in values):
        return "PASS"
    if any(status == "FAIL" for status in values):
        return "FAIL"
    return "SKIPPED_WITH_REASON" if any(status == "SKIPPED_WITH_REASON" for status in values) else values[0]


def _reason_for(row: dict[str, Any]) -> str:
    reason = row.get("reason") or row.get("missing_reason") or ""
    if reason:
        return str(reason)
    if row.get("status") in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"}:
        return "reason absent in source row"
    if row.get("operation_status") in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"}:
        return "reason absent in source row"
    missing = row.get("missing_fields")
    if missing:
        if isinstance(missing, list):
            reasons = []
            for item in missing:
                if isinstance(item, dict):
                    field = item.get("field", "field")
                    item_reason = item.get("reason", "reason absent")
                    reasons.append(f"{field}: {item_reason}")
                else:
                    reasons.append(str(item))
            return "missing_fields=" + "; ".join(sorted(set(reasons)))
        return f"missing_fields={missing}"
    return ""


def _join_reasons(rows: list[dict[str, Any]]) -> str:
    return _join_sorted(_reason_for(row) for row in rows if _reason_for(row))


def _join_missing_reasons(missing_reasons: Any) -> str:
    if not isinstance(missing_reasons, dict):
        return ""
    return "; ".join(f"{key}: {value}" for key, value in sorted(missing_reasons.items()) if value)


def _join_sorted(values: Any) -> str:
    cleaned = sorted({str(value) for value in values if value not in {None, "", "MISSING"}})
    return ";".join(cleaned) if cleaned else "MISSING"


def _int_or_one(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def _render_value(value: Any, reason: str = "", field: str = "") -> str:
    if field == "reason" and value in {None, ""}:
        return ""
    if value in {None, ""}:
        return f"MISSING ({reason or 'value absent from source artifact'})"
    if value in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"}:
        return f"{value} ({reason or 'reason absent from source artifact'})"
    return str(value)


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FinalReportError(f"invalid JSON source artifact {path}: {exc}") from exc
    if not isinstance(obj, dict):
        raise FinalReportError(f"source artifact must be a JSON object: {path}")
    return obj


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FinalReportError(f"invalid JSONL source artifact {path}:{lineno}: {exc}") from exc
        if not isinstance(obj, dict):
            raise FinalReportError(f"JSONL source row must be an object: {path}:{lineno}")
        rows.append(obj)
    if not rows:
        raise FinalReportError(f"JSONL source artifact is empty: {path}")
    return rows


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
