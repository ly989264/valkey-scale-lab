from __future__ import annotations

import csv
import html
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__

PHASE_ID = "P09_ANALYSIS_REPORTING"
RUN_ID = "P09_ANALYSIS_REPORTING-analysis-20260628"
CREATED_AT = "2026-06-28T00:00:00Z"


class ReportError(RuntimeError):
    pass


def render_report(analysis_path: str | Path, out_dir: str | Path, index_out: str | Path) -> dict[str, Any]:
    analysis_file = Path(analysis_path)
    try:
        analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportError(f"analysis artifact does not exist: {analysis_file}") from exc
    except json.JSONDecodeError as exc:
        raise ReportError(f"analysis artifact is invalid JSON: {analysis_file}: {exc}") from exc

    report_dir = Path(out_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    metrics = list(analysis.get("metrics", []))
    missing = list(analysis.get("missing_metrics", []))
    report_run_id = str(analysis.get("run_id") or RUN_ID)
    report_created_at = str(analysis.get("created_at") or CREATED_AT)

    generated = [
        _write_metrics_csv(report_dir / "metrics.csv", metrics),
        _write_missing_csv(report_dir / "missing_metrics.csv", missing),
        _write_baseline_csv(report_dir / "baseline_comparison.csv", analysis.get("baseline_comparison", {})),
        _write_setup_phase_csv(report_dir / "setup_phase_durations.csv", analysis.get("setup_aggregates", {})),
        _write_setup_nodes_csv(report_dir / "setup_slowest_nodes.csv", analysis.get("setup_aggregates", {})),
        _write_command_rows_csv(report_dir / "command_slowest.csv", analysis.get("command_audit", {}).get("slowest_commands_topN", [])),
        _write_command_rows_csv(report_dir / "command_failures.csv", analysis.get("command_audit", {}).get("failed_commands", [])),
        _write_command_rows_csv(report_dir / "command_retries.csv", analysis.get("command_audit", {}).get("retry_commands", [])),
        _write_management_ops_csv(report_dir / "management_ops_matrix.csv", analysis.get("management_ops", {})),
        _write_management_duration_csv(report_dir / "management_operation_durations.csv", analysis.get("management_ops", {})),
        _write_management_topology_csv(report_dir / "management_topology_diffs.csv", analysis.get("management_ops", {})),
        _write_management_detail_csv(report_dir / "management_rolling_restart.csv", analysis.get("management_ops", {}).get("rolling_restart_summary", [])),
        _write_management_detail_csv(report_dir / "management_reshard_rebalance.csv", analysis.get("management_ops", {}).get("reshard_rebalance_summary", [])),
        _write_workload_windows_csv(report_dir / "workload_benchmark_windows.csv", analysis.get("workload_benchmark", {})),
        _write_workload_profile_csv(report_dir / "workload_profile_summary.csv", analysis.get("workload_benchmark", {})),
        _write_fault_timeline_events_csv(report_dir / "fault_timeline_events.csv", analysis.get("fault_timeline", {})),
        _write_fault_timeline_summary_csv(report_dir / "fault_timeline_summary.csv", analysis.get("fault_timeline", {})),
        _write_failover_latency_distribution_csv(report_dir / "failover_latency_distribution.csv", analysis.get("fault_timeline", {})),
        _write_split_brain_windows_csv(report_dir / "split_brain_windows.csv", analysis.get("fault_timeline", {})),
        _write_fault_workload_impact_csv(report_dir / "fault_workload_impact.csv", analysis.get("fault_timeline", {})),
        _write_chart(report_dir / "metric_chart.svg", metrics),
        _write_setup_waterfall_svg(report_dir / "setup_waterfall.svg", analysis.get("setup_aggregates", {})),
        _write_command_latency_svg(report_dir / "command_latency.svg", analysis.get("command_audit", {})),
        _write_management_duration_svg(report_dir / "management_operation_duration.svg", analysis.get("management_ops", {})),
        _write_management_topology_svg(report_dir / "management_topology_diff.svg", analysis.get("management_ops", {})),
        _write_workload_svg(report_dir / "workload_qps_p99_error.svg", analysis.get("workload_benchmark", {})),
        _write_fault_timeline_svg(report_dir / "fault_timeline.svg", analysis.get("fault_timeline", {})),
        _write_fault_distribution_svg(report_dir / "failover_latency_distribution.svg", analysis.get("fault_timeline", {})),
        _write_split_brain_svg(report_dir / "split_brain_window.svg", analysis.get("fault_timeline", {})),
        _write_fault_workload_svg(report_dir / "fault_workload_impact.svg", analysis.get("fault_timeline", {})),
        _write_markdown(report_dir / "report.md", analysis),
        _write_html(report_dir / "index.html", analysis),
    ]

    index_path = Path(index_out)
    index = {
        "schema_version": "v1",
        "artifact_type": "report_index",
        "phase_id": PHASE_ID,
        "run_id": report_run_id,
        "created_at": report_created_at,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "analysis_path": _rel(analysis_file),
        "run_manifest_ref": analysis.get("run_manifest_ref")
        or {
            "status": "MISSING",
            "reason": "analysis_summary.json did not include run_manifest_ref.",
            "impact": "Report cannot link back to run manifest.",
        },
        "run_metadata_ref": analysis.get("run_metadata_ref")
        or {
            "status": "MISSING",
            "reason": "analysis_summary.json did not include run_metadata_ref.",
            "impact": "Report cannot link back to run metadata.",
        },
        "reports": [_report_record(path) for path in generated],
        "setup_report_inputs": {
            "setup_telemetry": analysis.get("setup_telemetry", {"status": "SKIPPED_WITH_REASON", "reason": "analysis did not include setup telemetry"}),
            "csv": "setup_phase_durations.csv",
            "svg": "setup_waterfall.svg",
        },
        "command_audit_report_inputs": {
            "command_log": analysis.get("command_audit", {}).get("command_log_ref", {"status": "SKIPPED_WITH_REASON", "reason": "analysis did not include command audit"}),
            "command_audit_summary": analysis.get("command_audit", {}).get("summary_artifact", {"status": "SKIPPED_WITH_REASON", "reason": "analysis did not include command_audit_summary.json"}),
            "csv": ["command_slowest.csv", "command_failures.csv", "command_retries.csv"],
            "svg": "command_latency.svg",
        },
        "management_report_inputs": {
            "management_ops": analysis.get("management_ops", {"status": "SKIPPED_WITH_REASON", "reason": "analysis did not include management operation aggregates"}),
            "csv": [
                "management_ops_matrix.csv",
                "management_operation_durations.csv",
                "management_topology_diffs.csv",
                "management_rolling_restart.csv",
                "management_reshard_rebalance.csv"
            ],
            "svg": ["management_operation_duration.svg", "management_topology_diff.svg"],
        },
        "workload_report_inputs": {
            "workload_benchmark": analysis.get("workload_benchmark", {"status": "SKIPPED_WITH_REASON", "reason": "analysis did not include workload benchmark aggregates"}),
            "refs": {
                "workload_windows": "workload_windows.json",
                "workload_report": "workload_report.json",
                "management_workload_impact": "management_workload_impact.json",
            },
            "csv": ["workload_benchmark_windows.csv", "workload_profile_summary.csv"],
            "svg": "workload_qps_p99_error.svg",
        },
        "fault_timeline_report_inputs": {
            "fault_timeline": analysis.get("fault_timeline", {"status": "SKIPPED_WITH_REASON", "reason": "analysis did not include fault timeline aggregates"}),
            "refs": analysis.get("fault_timeline", {}).get("source_refs", {
                "fault_timeline_report": "fault_timeline_report.json",
                "fault_timeline_events": "fault_timeline_events.jsonl",
                "failover_latency_samples": "failover_latency_samples.jsonl",
                "fault_workload_impact": "fault_workload_impact.json",
                "cleanup": "cleanup_report.json",
                "evidence": "valkey_e2e_evidence.json",
            }),
            "csv": [
                "fault_timeline_events.csv",
                "fault_timeline_summary.csv",
                "failover_latency_distribution.csv",
                "split_brain_windows.csv",
                "fault_workload_impact.csv",
            ],
            "svg": [
                "fault_timeline.svg",
                "failover_latency_distribution.svg",
                "split_brain_window.svg",
                "fault_workload_impact.svg",
            ],
        },
    }
    _write_json(index_path, index)
    _write_phase_summary(index_path.parent, analysis, index_path, generated)
    return index


def _write_metrics_csv(path: Path, metrics: list[dict[str, Any]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "status", "value", "unit", "reason"])
        writer.writeheader()
        for metric in metrics:
            writer.writerow(
                {
                    "metric": metric.get("name", "MISSING"),
                    "status": metric.get("status", "MISSING"),
                    "value": "" if metric.get("value") is None else metric.get("value"),
                    "unit": metric.get("unit", ""),
                    "reason": metric.get("reason", ""),
                }
            )
    return path


def _write_missing_csv(path: Path, missing: list[dict[str, Any]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "status", "reason", "impact"])
        writer.writeheader()
        for item in missing:
            writer.writerow(
                {
                    "metric": item.get("metric", "MISSING"),
                    "status": item.get("status", "MISSING"),
                    "reason": item.get("reason", ""),
                    "impact": item.get("impact", ""),
                }
            )
    return path


def _write_baseline_csv(path: Path, baseline: dict[str, Any]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "current_value", "baseline_value", "delta", "unit", "status"])
        writer.writeheader()
        for item in baseline.get("comparisons", []):
            writer.writerow(
                {
                    "metric": item.get("metric", "MISSING"),
                    "current_value": "" if item.get("current_value") is None else item.get("current_value"),
                    "baseline_value": "" if item.get("baseline_value") is None else item.get("baseline_value"),
                    "delta": "" if item.get("delta") is None else item.get("delta"),
                    "unit": item.get("unit", ""),
                    "status": item.get("status", "MISSING"),
                }
            )
    return path


def _write_setup_phase_csv(path: Path, setup: dict[str, Any]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "value_ms", "status", "reason"])
        writer.writeheader()
        for item in setup.get("phase_duration_ranking", []):
            writer.writerow({"metric": item.get("metric", "MISSING"), "value_ms": item.get("value_ms", ""), "status": "PASS", "reason": ""})
        if not setup.get("phase_duration_ranking"):
            writer.writerow({"metric": "setup_telemetry", "value_ms": "", "status": setup.get("status", "SKIPPED_WITH_REASON"), "reason": setup.get("reason", "")})
    return path


def _write_setup_nodes_csv(path: Path, setup: dict[str, Any]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["logical_id", "nodehost_id", "node_ready_ms", "node_role", "node_cluster_state", "node_cluster_known_nodes"])
        writer.writeheader()
        for item in setup.get("slowest_nodes_topN", []):
            if not isinstance(item, dict) or item.get("status") == "SKIPPED_WITH_REASON":
                continue
            writer.writerow(
                {
                    "logical_id": item.get("logical_id", "MISSING"),
                    "nodehost_id": item.get("nodehost_id", "MISSING"),
                    "node_ready_ms": item.get("node_ready_ms", ""),
                    "node_role": item.get("node_role", "MISSING"),
                    "node_cluster_state": item.get("node_cluster_state", "MISSING"),
                    "node_cluster_known_nodes": item.get("node_cluster_known_nodes", "MISSING"),
                }
            )
    return path


def _write_command_rows_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["command_id", "operation_id", "step_id", "command_kind", "duration_ms", "status", "exit_code", "retry_index", "error_type"])
        writer.writeheader()
        for item in rows:
            writer.writerow(
                {
                    "command_id": item.get("command_id", "MISSING"),
                    "operation_id": item.get("operation_id", "MISSING"),
                    "step_id": item.get("step_id", "MISSING"),
                    "command_kind": item.get("command_kind", "MISSING"),
                    "duration_ms": item.get("duration_ms", ""),
                    "status": item.get("status", "MISSING"),
                    "exit_code": item.get("exit_code", ""),
                    "retry_index": item.get("retry_index", 0),
                    "error_type": item.get("error_type", ""),
                }
            )
    return path


def _write_management_ops_csv(path: Path, management: dict[str, Any]) -> Path:
    matrix = management.get("matrix", {}) if isinstance(management, dict) else {}
    operations = matrix.get("operations", []) if isinstance(matrix, dict) else []
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["operation_name", "operation_id", "coverage_id", "status", "command_count", "workload_impact_ref", "cleanup_ref"])
        writer.writeheader()
        for row in operations:
            writer.writerow(
                {
                    "operation_name": row.get("operation_name", "MISSING"),
                    "operation_id": row.get("operation_id", "MISSING"),
                    "coverage_id": row.get("coverage_id", "MISSING"),
                    "status": row.get("operation_status", "MISSING"),
                    "command_count": row.get("command_count", 0),
                    "workload_impact_ref": row.get("workload_impact_ref", "MISSING"),
                    "cleanup_ref": row.get("cleanup_ref", "MISSING"),
                }
            )
    return path


def _write_management_duration_csv(path: Path, management: dict[str, Any]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["operation_name", "operation_id", "status", "operation_duration_ms", "convergence_ms", "command_count", "retry_count", "error_count"])
        writer.writeheader()
        for row in management.get("duration_ranking_topN", []) if isinstance(management, dict) else []:
            writer.writerow(
                {
                    "operation_name": row.get("operation_name", "MISSING"),
                    "operation_id": row.get("operation_id", "MISSING"),
                    "status": row.get("operation_status", "MISSING"),
                    "operation_duration_ms": row.get("operation_duration_ms", ""),
                    "convergence_ms": row.get("convergence_ms", ""),
                    "command_count": row.get("command_count", 0),
                    "retry_count": row.get("retry_count", 0),
                    "error_count": row.get("error_count", 0),
                }
            )
    return path


def _write_management_topology_csv(path: Path, management: dict[str, Any]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["operation_id", "known_nodes_delta", "moved_slot_range_count", "role_diff", "status"])
        writer.writeheader()
        for row in management.get("topology_diff_summary", []) if isinstance(management, dict) else []:
            writer.writerow(
                {
                    "operation_id": row.get("operation_id", "MISSING"),
                    "known_nodes_delta": row.get("known_nodes_delta", "MISSING"),
                    "moved_slot_range_count": row.get("moved_slot_range_count", "MISSING"),
                    "role_diff": json.dumps(row.get("role_diff", {}), sort_keys=True),
                    "status": row.get("status", "MISSING"),
                }
            )
    return path


def _write_management_detail_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["operation_name", "operation_id", "operation_duration_ms", "convergence_ms", "slots_moved", "keys_moved", "cluster_impact_ms", "status"])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "operation_name": row.get("operation_name", "MISSING"),
                    "operation_id": row.get("operation_id", "MISSING"),
                    "operation_duration_ms": row.get("operation_duration_ms", row.get("wall_ms", "")),
                    "convergence_ms": row.get("convergence_ms", ""),
                    "slots_moved": row.get("slots_moved", ""),
                    "keys_moved": row.get("keys_moved", ""),
                    "cluster_impact_ms": row.get("cluster_impact_ms", ""),
                    "status": row.get("operation_status", "MISSING"),
                }
            )
    return path


def _write_workload_windows_csv(path: Path, workload: dict[str, Any]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["profile", "window_name", "status", "requested_qps", "achieved_qps", "throughput_ratio", "latency_p99_ms", "error_rate", "slot_count_observed", "full_slot_covered"])
        writer.writeheader()
        rows = workload.get("windows", []) if isinstance(workload, dict) else []
        if not rows:
            writer.writerow({"profile": "SKIPPED_WITH_REASON", "window_name": "", "status": workload.get("status", "SKIPPED_WITH_REASON") if isinstance(workload, dict) else "SKIPPED_WITH_REASON"})
        for row in rows:
            coverage = row.get("key_slot_coverage", {}) if isinstance(row, dict) else {}
            writer.writerow(
                {
                    "profile": row.get("profile", "MISSING"),
                    "window_name": row.get("window_name", "MISSING"),
                    "status": row.get("status", "MISSING"),
                    "requested_qps": row.get("requested_qps", "MISSING"),
                    "achieved_qps": row.get("achieved_qps", "MISSING"),
                    "throughput_ratio": row.get("throughput_ratio", "MISSING"),
                    "latency_p99_ms": row.get("latency_p99_ms", "MISSING"),
                    "error_rate": row.get("error_rate", "MISSING"),
                    "slot_count_observed": coverage.get("slot_count_observed", "MISSING") if isinstance(coverage, dict) else "MISSING",
                    "full_slot_covered": coverage.get("full_slot_covered", "MISSING") if isinstance(coverage, dict) else "MISSING",
                }
            )
    return path


def _write_workload_profile_csv(path: Path, workload: dict[str, Any]) -> Path:
    coverage = workload.get("hash_slot_coverage", {}) if isinstance(workload, dict) else {}
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["profile", "window_count", "slot_count_observed", "full_slot_requested", "full_slot_covered", "fixed_hash_tag_only"])
        writer.writeheader()
        profiles = workload.get("profiles_covered", []) if isinstance(workload, dict) else []
        if not profiles:
            writer.writerow({"profile": "SKIPPED_WITH_REASON", "window_count": 0})
        for profile in profiles:
            item = coverage.get(profile, {}) if isinstance(coverage, dict) else {}
            writer.writerow(
                {
                    "profile": profile,
                    "window_count": sum(1 for row in workload.get("windows", []) if row.get("profile") == profile),
                    "slot_count_observed": item.get("slot_count_observed", "MISSING") if isinstance(item, dict) else "MISSING",
                    "full_slot_requested": item.get("full_slot_requested", "MISSING") if isinstance(item, dict) else "MISSING",
                    "full_slot_covered": item.get("full_slot_covered", "MISSING") if isinstance(item, dict) else "MISSING",
                    "fixed_hash_tag_only": item.get("fixed_hash_tag_only", "MISSING") if isinstance(item, dict) else "MISSING",
                }
            )
    return path


def _write_fault_timeline_events_csv(path: Path, fault: dict[str, Any]) -> Path:
    rows = fault.get("event_completeness", []) if isinstance(fault, dict) else []
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sample_id", "observed_event_count", "missing_events", "status"])
        writer.writeheader()
        if not rows:
            writer.writerow({"sample_id": "SKIPPED_WITH_REASON", "observed_event_count": 0, "missing_events": fault.get("reason", "无故障 timeline 输入") if isinstance(fault, dict) else "无故障 timeline 输入", "status": fault.get("status", "SKIPPED_WITH_REASON") if isinstance(fault, dict) else "SKIPPED_WITH_REASON"})
        for row in rows:
            writer.writerow({
                "sample_id": row.get("sample_id", "MISSING"),
                "observed_event_count": row.get("observed_event_count", 0),
                "missing_events": ",".join(str(item) for item in row.get("missing_events", [])),
                "status": "PASS" if not row.get("missing_events") else "PARTIAL",
            })
    return path


def _write_fault_timeline_summary_csv(path: Path, fault: dict[str, Any]) -> Path:
    rows = fault.get("rows", []) if isinstance(fault, dict) else []
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sample_id", "fault_type", "scale_rung", "node_count", "status", "failover_latency_ms", "client_unavailability_ms", "cleanup_duration_ms"])
        writer.writeheader()
        if not rows:
            writer.writerow({"sample_id": "SKIPPED_WITH_REASON", "status": fault.get("status", "SKIPPED_WITH_REASON") if isinstance(fault, dict) else "SKIPPED_WITH_REASON"})
        for row in rows:
            metrics = row.get("metrics", {}) if isinstance(row, dict) else {}
            writer.writerow({
                "sample_id": row.get("sample_id", "MISSING"),
                "fault_type": row.get("fault_type", "MISSING"),
                "scale_rung": row.get("scale_rung", "MISSING"),
                "node_count": row.get("node_count", "MISSING"),
                "status": row.get("status", "MISSING"),
                "failover_latency_ms": _csv_value(metrics.get("failover_latency_ms")),
                "client_unavailability_ms": _csv_value(metrics.get("client_unavailability_ms")),
                "cleanup_duration_ms": _csv_value(metrics.get("cleanup_duration_ms")),
            })
    return path


def _write_failover_latency_distribution_csv(path: Path, fault: dict[str, Any]) -> Path:
    fields = ["failover_latency", "promotion_latency", "client_unavailability", "workload_recovery"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "sample_count", "p50_ms", "p95_ms", "max_ms", "status", "reason"])
        writer.writeheader()
        for name in fields:
            item = fault.get(name, {}) if isinstance(fault, dict) else {}
            writer.writerow({
                "metric": name,
                "sample_count": item.get("sample_count", 0),
                "p50_ms": item.get("p50_ms", "MISSING"),
                "p95_ms": item.get("p95_ms", "MISSING"),
                "max_ms": item.get("max_ms", "MISSING"),
                "status": item.get("status", "MISSING"),
                "reason": item.get("reason", ""),
            })
    return path


def _write_split_brain_windows_csv(path: Path, fault: dict[str, Any]) -> Path:
    fields = ["split_brain_window", "cluster_down_window"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "sample_count", "p95_ms", "max_ms", "status", "reason"])
        writer.writeheader()
        for name in fields:
            item = fault.get(name, {}) if isinstance(fault, dict) else {}
            writer.writerow({"metric": name, "sample_count": item.get("sample_count", 0), "p95_ms": item.get("p95_ms", "MISSING"), "max_ms": item.get("max_ms", "MISSING"), "status": item.get("status", "MISSING"), "reason": item.get("reason", "")})
    return path


def _write_fault_workload_impact_csv(path: Path, fault: dict[str, Any]) -> Path:
    rows = fault.get("rows", []) if isinstance(fault, dict) else []
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sample_id", "fault_type", "client_unavailability_ms", "workload_recovery_ms", "cluster_down_window_ms", "status"])
        writer.writeheader()
        if not rows:
            writer.writerow({"sample_id": "SKIPPED_WITH_REASON", "status": fault.get("status", "SKIPPED_WITH_REASON") if isinstance(fault, dict) else "SKIPPED_WITH_REASON"})
        for row in rows:
            metrics = row.get("metrics", {}) if isinstance(row, dict) else {}
            writer.writerow({
                "sample_id": row.get("sample_id", "MISSING"),
                "fault_type": row.get("fault_type", "MISSING"),
                "client_unavailability_ms": _csv_value(metrics.get("client_unavailability_ms")),
                "workload_recovery_ms": _csv_value(metrics.get("workload_recovery_ms")),
                "cluster_down_window_ms": _csv_value(metrics.get("cluster_down_window_ms")),
                "status": row.get("status", "MISSING"),
            })
    return path


def _csv_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("status", "MISSING")
    return "" if value is None else value


def _display_metric(value: Any) -> str:
    if isinstance(value, dict):
        reason = value.get("reason", "")
        return f"{value.get('status', 'MISSING')} ({reason})" if reason else str(value.get("status", "MISSING"))
    return str(value)


def _write_chart(path: Path, metrics: list[dict[str, Any]]) -> Path:
    numeric = [m for m in metrics if isinstance(m.get("value"), (int, float)) and not isinstance(m.get("value"), bool)]
    max_value = max([float(m["value"]) for m in numeric] + [1.0])
    rows: list[str] = []
    y = 42
    for metric in metrics:
        name = html.escape(str(metric.get("name", "MISSING")))
        status = str(metric.get("status", "MISSING"))
        value = metric.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            width = int(360 * (float(value) / max_value))
            label = html.escape(str(value))
            color = "#2f6f4e"
        else:
            width = 24
            label = html.escape(status)
            color = "#8a8f98"
        rows.append(f'<text x="12" y="{y + 14}" font-size="12">{name}</text>')
        rows.append(f'<rect x="190" y="{y}" width="{max(width, 2)}" height="18" fill="{color}"/>')
        rows.append(f'<text x="{200 + max(width, 2)}" y="{y + 14}" font-size="12">{label}</text>')
        y += 34
    height = max(y + 16, 96)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="{height}" viewBox="0 0 640 {height}">\n'
        '<rect width="100%" height="100%" fill="#ffffff"/>\n'
        '<text x="12" y="24" font-size="16" font-weight="700">P09 Artifact Metrics</text>\n'
        + "\n".join(rows)
        + "\n</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")
    return path


def _write_setup_waterfall_svg(path: Path, setup: dict[str, Any]) -> Path:
    rows = [item for item in setup.get("phase_duration_ranking", []) if isinstance(item.get("value_ms"), (int, float))]
    max_value = max([float(item["value_ms"]) for item in rows] + [1.0])
    y = 42
    parts: list[str] = []
    for item in rows[:17]:
        name = html.escape(str(item.get("metric", "MISSING")))
        value = float(item["value_ms"])
        width = int(380 * (value / max_value))
        parts.append(f'<text x="12" y="{y + 14}" font-size="12">{name}</text>')
        parts.append(f'<rect x="210" y="{y}" width="{max(width, 2)}" height="18" fill="#326c7a"/>')
        parts.append(f'<text x="{220 + max(width, 2)}" y="{y + 14}" font-size="12">{value:.3f} ms</text>')
        y += 32
    if not rows:
        parts.append('<text x="12" y="56" font-size="13">setup_telemetry.json 未提供可绘制的数值阶段耗时。</text>')
    height = max(y + 20, 100)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="720" height="{height}" viewBox="0 0 720 {height}">\n'
        '<rect width="100%" height="100%" fill="#ffffff"/>\n'
        '<text x="12" y="24" font-size="16" font-weight="700">集群拉起瀑布图</text>\n'
        + "\n".join(parts)
        + "\n</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")
    return path


def _write_command_latency_svg(path: Path, audit: dict[str, Any]) -> Path:
    rows = [item for item in audit.get("slowest_commands_topN", []) if isinstance(item.get("duration_ms"), (int, float))]
    max_value = max([float(item["duration_ms"]) for item in rows] + [1.0])
    y = 42
    parts: list[str] = []
    for item in rows[:10]:
        name = html.escape(f"{item.get('command_kind', 'MISSING')} {item.get('command_id', 'MISSING')}")
        value = float(item["duration_ms"])
        width = int(380 * (value / max_value))
        color = "#7c4d1d" if item.get("status") != "PASS" else "#475f9b"
        parts.append(f'<text x="12" y="{y + 14}" font-size="12">{name}</text>')
        parts.append(f'<rect x="230" y="{y}" width="{max(width, 2)}" height="18" fill="{color}"/>')
        parts.append(f'<text x="{240 + max(width, 2)}" y="{y + 14}" font-size="12">{value:.3f} ms</text>')
        y += 32
    if not rows:
        parts.append('<text x="12" y="56" font-size="13">command_log.jsonl 未提供可绘制的命令耗时。</text>')
    height = max(y + 20, 100)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="760" height="{height}" viewBox="0 0 760 {height}">\n'
        '<rect width="100%" height="100%" fill="#ffffff"/>\n'
        '<text x="12" y="24" font-size="16" font-weight="700">命令耗时分布</text>\n'
        + "\n".join(parts)
        + "\n</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")
    return path


def _write_management_duration_svg(path: Path, management: dict[str, Any]) -> Path:
    rows = [item for item in management.get("duration_ranking_topN", []) if isinstance(item.get("operation_duration_ms"), (int, float))]
    max_value = max([float(item["operation_duration_ms"]) for item in rows] + [1.0])
    y = 42
    parts: list[str] = []
    for item in rows[:10]:
        name = html.escape(str(item.get("operation_name", "MISSING")))
        value = float(item["operation_duration_ms"])
        width = int(380 * (value / max_value))
        parts.append(f'<text x="12" y="{y + 14}" font-size="12">{name}</text>')
        parts.append(f'<rect x="250" y="{y}" width="{max(width, 2)}" height="18" fill="#5f6f2f"/>')
        parts.append(f'<text x="{260 + max(width, 2)}" y="{y + 14}" font-size="12">{value:.3f} ms</text>')
        y += 32
    if not rows:
        parts.append('<text x="12" y="56" font-size="13">management_operation_results.jsonl 未提供可绘制的管理操作耗时。</text>')
    height = max(y + 20, 100)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="820" height="{height}" viewBox="0 0 820 {height}">\n'
        '<rect width="100%" height="100%" fill="#ffffff"/>\n'
        '<text x="12" y="24" font-size="16" font-weight="700">管理操作耗时排序</text>\n'
        + "\n".join(parts)
        + "\n</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")
    return path


def _write_management_topology_svg(path: Path, management: dict[str, Any]) -> Path:
    rows = management.get("topology_diff_summary", []) if isinstance(management, dict) else []
    y = 42
    parts: list[str] = []
    for item in rows[:10]:
        name = html.escape(str(item.get("operation_id", "MISSING")))
        moved = item.get("moved_slot_range_count", 0)
        moved_value = int(moved) if isinstance(moved, int) else 0
        width = max(2, moved_value * 6)
        parts.append(f'<text x="12" y="{y + 14}" font-size="12">{name}</text>')
        parts.append(f'<rect x="340" y="{y}" width="{width}" height="18" fill="#326c7a"/>')
        parts.append(f'<text x="{350 + width}" y="{y + 14}" font-size="12">moved_ranges={html.escape(str(moved))}</text>')
        y += 32
    if not rows:
        parts.append('<text x="12" y="56" font-size="13">management_topology_diffs.jsonl 未提供 topology diff。</text>')
    height = max(y + 20, 100)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="820" height="{height}" viewBox="0 0 820 {height}">\n'
        '<rect width="100%" height="100%" fill="#ffffff"/>\n'
        '<text x="12" y="24" font-size="16" font-weight="700">管理 topology diff 摘要</text>\n'
        + "\n".join(parts)
        + "\n</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")
    return path


def _write_workload_svg(path: Path, workload: dict[str, Any]) -> Path:
    rows = [row for row in workload.get("windows", []) if isinstance(row, dict)] if isinstance(workload, dict) else []
    plot_rows = rows[:12]
    width = 760
    height = 120 + max(len(plot_rows), 1) * 28
    max_qps = max([float(row.get("achieved_qps", 0) or 0) for row in plot_rows if isinstance(row.get("achieved_qps"), (int, float))] or [1.0])
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img" aria-label="Workload QPS p99 错误率">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="20" y="28" font-size="16" font-family="sans-serif">Workload QPS / p99 / 错误率</text>',
    ]
    if not plot_rows:
        parts.append('<text x="20" y="64" font-size="13" font-family="sans-serif">SKIPPED_WITH_REASON: 无 workload benchmark 行</text>')
    for idx, row in enumerate(plot_rows):
        y = 58 + idx * 28
        qps = row.get("achieved_qps", 0)
        bar = int((float(qps) / max_qps) * 260) if isinstance(qps, (int, float)) else 0
        label = html.escape(f"{row.get('profile', 'MISSING')}:{row.get('window_name', 'MISSING')}")
        p99 = html.escape(str(row.get("latency_p99_ms", "MISSING")))
        error = html.escape(str(row.get("error_rate", "MISSING")))
        parts.append(f'<text x="20" y="{y + 14}" font-size="12" font-family="sans-serif">{label}</text>')
        parts.append(f'<rect x="190" y="{y}" width="{bar}" height="18" fill="#2f80ed"/>')
        parts.append(f'<text x="{200 + bar}" y="{y + 14}" font-size="12" font-family="sans-serif">QPS={html.escape(str(qps))} p99={p99} 错误率={error}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def _write_fault_timeline_svg(path: Path, fault: dict[str, Any]) -> Path:
    rows = fault.get("event_completeness", []) if isinstance(fault, dict) else []
    y = 52
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="820" height="360" viewBox="0 0 820 360">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="16" y="28" font-size="16" font-weight="700">故障 Timeline</text>',
    ]
    if not rows:
        parts.append('<text x="16" y="70" font-size="13">SKIPPED_WITH_REASON: 无 fault_timeline_events.jsonl 输入</text>')
    for row in rows[:8]:
        sample_id = html.escape(str(row.get("sample_id", "MISSING")))
        count = int(row.get("observed_event_count", 0) or 0)
        parts.append(f'<text x="16" y="{y + 14}" font-size="12">{sample_id}</text>')
        parts.append(f'<rect x="180" y="{y}" width="{max(count * 36, 2)}" height="18" fill="#326c7a"/>')
        parts.append(f'<text x="{190 + max(count * 36, 2)}" y="{y + 14}" font-size="12">{count}/12 events</text>')
        y += 32
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def _write_fault_distribution_svg(path: Path, fault: dict[str, Any]) -> Path:
    rows = [(name, fault.get(name, {})) for name in ["failover_latency", "promotion_latency", "client_unavailability", "workload_recovery"]] if isinstance(fault, dict) else []
    values = [float(item.get("p95_ms")) for _, item in rows if isinstance(item.get("p95_ms"), (int, float))]
    max_value = max(values or [1.0])
    y = 50
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="820" height="240" viewBox="0 0 820 240">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="16" y="28" font-size="16" font-weight="700">Failover 延迟分布</text>',
    ]
    for name, item in rows:
        value = item.get("p95_ms", "MISSING")
        width = int(420 * (float(value) / max_value)) if isinstance(value, (int, float)) else 2
        parts.append(f'<text x="16" y="{y + 14}" font-size="12">{html.escape(name)}</text>')
        parts.append(f'<rect x="210" y="{y}" width="{max(width, 2)}" height="18" fill="#475f9b"/>')
        parts.append(f'<text x="{220 + max(width, 2)}" y="{y + 14}" font-size="12">p95={html.escape(str(value))} ms</text>')
        y += 34
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def _write_split_brain_svg(path: Path, fault: dict[str, Any]) -> Path:
    rows = [(name, fault.get(name, {})) for name in ["split_brain_window", "cluster_down_window"]] if isinstance(fault, dict) else []
    max_value = max([float(item.get("max_ms")) for _, item in rows if isinstance(item.get("max_ms"), (int, float))] or [1.0])
    y = 56
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="760" height="170" viewBox="0 0 760 170">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="16" y="28" font-size="16" font-weight="700">Split-brain 窗口</text>',
    ]
    for name, item in rows:
        value = item.get("max_ms", "MISSING")
        width = int(360 * (float(value) / max_value)) if isinstance(value, (int, float)) else 2
        parts.append(f'<text x="16" y="{y + 14}" font-size="12">{html.escape(name)}</text>')
        parts.append(f'<rect x="210" y="{y}" width="{max(width, 2)}" height="18" fill="#7c4d1d"/>')
        parts.append(f'<text x="{220 + max(width, 2)}" y="{y + 14}" font-size="12">max={html.escape(str(value))} ms</text>')
        y += 34
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def _write_fault_workload_svg(path: Path, fault: dict[str, Any]) -> Path:
    rows = fault.get("rows", []) if isinstance(fault, dict) else []
    max_value = max([
        float(row.get("metrics", {}).get("client_unavailability_ms"))
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("metrics", {}).get("client_unavailability_ms"), (int, float))
    ] or [1.0])
    y = 52
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="840" height="320" viewBox="0 0 840 320">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="16" y="28" font-size="16" font-weight="700">故障期间 Workload 影响</text>',
    ]
    if not rows:
        parts.append('<text x="16" y="70" font-size="13">SKIPPED_WITH_REASON: 无 fault workload impact 输入</text>')
    for row in rows[:8]:
        metrics = row.get("metrics", {}) if isinstance(row, dict) else {}
        value = metrics.get("client_unavailability_ms", "MISSING")
        width = int(360 * (float(value) / max_value)) if isinstance(value, (int, float)) else 2
        label = html.escape(f"{row.get('fault_type', 'MISSING')} {row.get('sample_id', 'MISSING')}")
        parts.append(f'<text x="16" y="{y + 14}" font-size="12">{label}</text>')
        parts.append(f'<rect x="280" y="{y}" width="{max(width, 2)}" height="18" fill="#5f6f2f"/>')
        parts.append(f'<text x="{290 + max(width, 2)}" y="{y + 14}" font-size="12">unavailable={html.escape(str(value))} ms</text>')
        y += 32
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def _write_markdown(path: Path, analysis: dict[str, Any]) -> Path:
    metadata = analysis.get("run_metadata", {})
    setup = analysis.get("setup_aggregates", {})
    command_audit = analysis.get("command_audit", {})
    management = analysis.get("management_ops", {})
    workload = analysis.get("workload_benchmark", {})
    fault = analysis.get("fault_timeline", {})
    lines = [
        "# P09 Analysis Report",
        "",
        f"Status: {analysis.get('status', 'MISSING')}",
        f"Source phase: {analysis.get('source', {}).get('phase_id', 'MISSING')}",
        "",
        "## 运行元数据",
        "",
        f"- run_id: {_metadata_value(metadata, 'run_id')}",
        f"- created_at: {_metadata_value(metadata, 'created_at')}",
        f"- git_sha: {_metadata_value(metadata, 'git_sha')}",
        f"- valkey_version: {_metadata_value(metadata, 'valkey_version')}",
        f"- artifact_root: {_metadata_value(metadata, 'artifact_root')}",
        "",
        "## 分析发现",
        "",
    ]
    for finding in analysis.get("findings", []):
        lines.append(f"- {finding.get('name', 'finding')}: {finding.get('status', 'MISSING')}")
    lines.extend(["", "## 集群拉起瀑布图", ""])
    if setup.get("phase_duration_ranking"):
        lines.append("![集群拉起瀑布图](setup_waterfall.svg)")
    else:
        lines.append(f"- {setup.get('status', 'SKIPPED_WITH_REASON')}: {setup.get('reason', '未提供 setup telemetry')}")
    lines.extend(["", "## 阶段耗时排序", ""])
    for item in setup.get("phase_duration_ranking", [])[:10]:
        lines.append(f"- {item.get('metric', 'MISSING')}: {item.get('value_ms', 'MISSING')} ms")
    if not setup.get("phase_duration_ranking"):
        lines.append("- SKIPPED_WITH_REASON: 无可排序的阶段耗时")
    lines.extend(["", "## 慢节点 TopN", ""])
    slow_nodes = setup.get("slowest_nodes_topN", [])
    if slow_nodes:
        for item in slow_nodes[:10]:
            if isinstance(item, dict) and item.get("status") == "SKIPPED_WITH_REASON":
                lines.append(f"- SKIPPED_WITH_REASON: {item.get('reason', '')}")
            elif isinstance(item, dict):
                lines.append(f"- {item.get('logical_id', 'MISSING')}: {item.get('node_ready_ms', 'MISSING')} ms, role={item.get('node_role', 'MISSING')}")
    else:
        lines.append("- SKIPPED_WITH_REASON: 无慢节点样本")
    lines.extend(["", "## 慢命令 TopN", ""])
    if command_audit.get("slowest_commands_topN"):
        lines.append("![命令耗时分布](command_latency.svg)")
        for item in command_audit.get("slowest_commands_topN", [])[:10]:
            lines.append(f"- {item.get('command_id', 'MISSING')} {item.get('command_kind', 'MISSING')}: {item.get('duration_ms', 'MISSING')} ms status={item.get('status', 'MISSING')}")
    else:
        lines.append(f"- {command_audit.get('status', 'SKIPPED_WITH_REASON')}: {command_audit.get('reason', '无 command log 样本')}")
    lines.extend(["", "## 失败命令", ""])
    failures = command_audit.get("failed_commands", [])
    if failures:
        for item in failures[:10]:
            lines.append(f"- {item.get('command_id', 'MISSING')} {item.get('command_kind', 'MISSING')}: {item.get('error_type', '')}")
    else:
        lines.append("- none")
    lines.extend(["", "## 重试命令", ""])
    retries = command_audit.get("retry_commands", [])
    if retries:
        for item in retries[:10]:
            lines.append(f"- {item.get('command_id', 'MISSING')} {item.get('command_kind', 'MISSING')}: retry_index={item.get('retry_index', 0)} status={item.get('status', 'MISSING')}")
    else:
        lines.append("- none")
    lines.extend(["", "## 命令审计覆盖", ""])
    lines.append(f"- total_commands: {command_audit.get('total_commands', 0)}")
    for kind, count in sorted(command_audit.get("by_command_kind", {}).items()):
        lines.append(f"- {kind}: {count}")
    lines.extend(["", "## 管理操作矩阵", ""])
    if management.get("duration_ranking_topN"):
        lines.append("![管理操作耗时排序](management_operation_duration.svg)")
        for item in management.get("duration_ranking_topN", [])[:11]:
            lines.append(f"- {item.get('operation_name', 'MISSING')}: {item.get('operation_duration_ms', 'MISSING')} ms status={item.get('operation_status', 'MISSING')} commands={item.get('command_count', 0)}")
    else:
        lines.append(f"- {management.get('status', 'SKIPPED_WITH_REASON')}: {management.get('reason', '无管理操作样本')}")
    lines.extend(["", "## 管理 topology diff 摘要", ""])
    if management.get("topology_diff_summary"):
        lines.append("![管理 topology diff 摘要](management_topology_diff.svg)")
        for item in management.get("topology_diff_summary", [])[:10]:
            lines.append(f"- {item.get('operation_id', 'MISSING')}: known_nodes_delta={item.get('known_nodes_delta', 'MISSING')}, moved_slot_ranges={item.get('moved_slot_range_count', 'MISSING')}")
    else:
        lines.append("- SKIPPED_WITH_REASON: 无 topology diff 样本")
    lines.extend(["", "## Workload 基准压测", ""])
    if workload.get("windows"):
        lines.append("![Workload QPS p99 error](workload_qps_p99_error.svg)")
        lines.append(f"- 覆盖 profile: {', '.join(str(item) for item in workload.get('profiles_covered', []))}")
        lines.append(f"- 全 slot 覆盖: {workload.get('full_slot_covered', 'MISSING')}。该值来自 workload_windows.json 的 hash_slot_coverage，用于确认基准压测不是只走固定 hash tag。")
        for item in workload.get("windows", [])[:12]:
            lines.append(
                f"- {item.get('profile', 'MISSING')} {item.get('window_name', 'MISSING')}: "
                f"实际 QPS={item.get('achieved_qps', 'MISSING')}，p99 延迟 ms={item.get('latency_p99_ms', 'MISSING')}，错误率={item.get('error_rate', 'MISSING')}"
            )
    else:
        lines.append(f"- {workload.get('status', 'SKIPPED_WITH_REASON')}: {workload.get('reason', '无 workload benchmark 样本')}")
    lines.extend(["", "## 故障 Timeline", ""])
    if fault.get("event_completeness"):
        lines.append("![故障 Timeline](fault_timeline.svg)")
        for item in fault.get("event_completeness", [])[:10]:
            missing_events = ", ".join(str(name) for name in item.get("missing_events", [])) or "none"
            lines.append(f"- {item.get('sample_id', 'MISSING')}: observed={item.get('observed_event_count', 0)}/12, missing={missing_events}")
    else:
        lines.append(f"- {fault.get('status', 'SKIPPED_WITH_REASON')}: {fault.get('reason', '无 fault timeline artifact')}")
    lines.extend(["", "## Failover 延迟分布", ""])
    lines.append("![Failover 延迟分布](failover_latency_distribution.svg)")
    for name in ["failover_latency", "promotion_latency", "client_unavailability", "workload_recovery"]:
        item = fault.get(name, {}) if isinstance(fault, dict) else {}
        lines.append(f"- {name}: p50={item.get('p50_ms', 'MISSING')} ms, p95={item.get('p95_ms', 'MISSING')} ms, max={item.get('max_ms', 'MISSING')} ms, status={item.get('status', 'MISSING')}")
    lines.extend(["", "## Split-brain 窗口", ""])
    lines.append("![Split-brain 窗口](split_brain_window.svg)")
    for name in ["split_brain_window", "cluster_down_window"]:
        item = fault.get(name, {}) if isinstance(fault, dict) else {}
        lines.append(f"- {name}: p95={item.get('p95_ms', 'MISSING')} ms, max={item.get('max_ms', 'MISSING')} ms, status={item.get('status', 'MISSING')}")
    lines.extend(["", "## 故障期间 Workload 影响", ""])
    if fault.get("rows"):
        lines.append("![故障期间 Workload 影响](fault_workload_impact.svg)")
        for row in fault.get("rows", [])[:10]:
            metrics = row.get("metrics", {}) if isinstance(row, dict) else {}
            lines.append(
                f"- {row.get('fault_type', 'MISSING')} {row.get('sample_id', 'MISSING')}: "
                f"client_unavailability_ms={_display_metric(metrics.get('client_unavailability_ms'))}, "
                f"workload_recovery_ms={_display_metric(metrics.get('workload_recovery_ms'))}, status={row.get('status', 'MISSING')}"
            )
    else:
        lines.append(f"- {fault.get('status', 'SKIPPED_WITH_REASON')}: {fault.get('reason', '无故障期间 workload impact 输入')}")
    lines.extend(["", "## 缺失指标", ""])
    missing = analysis.get("missing_metrics", [])
    if missing:
        for item in missing:
            lines.append(f"- {item.get('metric', 'MISSING')}: {item.get('status', 'MISSING')} - {item.get('reason', '')}")
    else:
        lines.append("- none")
    lines.extend(["", "## 生成表格", "", "- metrics.csv", "- missing_metrics.csv", "- baseline_comparison.csv", "- setup_phase_durations.csv", "- setup_slowest_nodes.csv", "- command_slowest.csv", "- command_failures.csv", "- command_retries.csv", "- management_ops_matrix.csv", "- management_operation_durations.csv", "- management_topology_diffs.csv", "- management_rolling_restart.csv", "- management_reshard_rebalance.csv", "- workload_benchmark_windows.csv", "- workload_profile_summary.csv", "- fault_timeline_events.csv", "- fault_timeline_summary.csv", "- failover_latency_distribution.csv", "- split_brain_windows.csv", "- fault_workload_impact.csv", "- metric_chart.svg", "- setup_waterfall.svg", "- command_latency.svg", "- management_operation_duration.svg", "- management_topology_diff.svg", "- workload_qps_p99_error.svg", "- fault_timeline.svg", "- failover_latency_distribution.svg", "- split_brain_window.svg", "- fault_workload_impact.svg"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_html(path: Path, analysis: dict[str, Any]) -> Path:
    metadata = analysis.get("run_metadata", {})
    setup = analysis.get("setup_aggregates", {})
    command_audit = analysis.get("command_audit", {})
    management = analysis.get("management_ops", {})
    workload = analysis.get("workload_benchmark", {})
    fault = analysis.get("fault_timeline", {})
    metadata_rows = "\n".join(
        "<tr><td>{}</td><td><code>{}</code></td></tr>".format(
            html.escape(key),
            html.escape(_metadata_value(metadata, key)),
        )
        for key in ["run_id", "created_at", "git_sha", "valkey_version", "artifact_root"]
    )
    finding_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(item.get("name", "finding"))),
            html.escape(str(item.get("status", "MISSING"))),
        )
        for item in analysis.get("findings", [])
    )
    missing_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(item.get("metric", "MISSING"))),
            html.escape(str(item.get("status", "MISSING"))),
            html.escape(str(item.get("reason", ""))),
        )
        for item in analysis.get("missing_metrics", [])
    ) or '<tr><td colspan="3">none</td></tr>'
    setup_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td></tr>".format(html.escape(str(item.get("metric", "MISSING"))), html.escape(str(item.get("value_ms", "MISSING"))))
        for item in setup.get("phase_duration_ranking", [])[:12]
    ) or '<tr><td colspan="2">SKIPPED_WITH_REASON: 无可排序的阶段耗时</td></tr>'
    slow_node_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(item.get("logical_id", item.get("status", "MISSING")))),
            html.escape(str(item.get("node_ready_ms", ""))),
            html.escape(str(item.get("node_role", ""))),
            html.escape(str(item.get("node_cluster_state", item.get("reason", "")))),
        )
        for item in setup.get("slowest_nodes_topN", [])[:10]
        if isinstance(item, dict)
    ) or '<tr><td colspan="4">SKIPPED_WITH_REASON: 无慢节点样本</td></tr>'
    slow_command_rows = _command_html_rows(command_audit.get("slowest_commands_topN", [])) or '<tr><td colspan="5">SKIPPED_WITH_REASON: 无慢命令样本</td></tr>'
    failed_command_rows = _command_html_rows(command_audit.get("failed_commands", [])) or '<tr><td colspan="5">none</td></tr>'
    retry_command_rows = _command_html_rows(command_audit.get("retry_commands", [])) or '<tr><td colspan="5">none</td></tr>'
    command_coverage_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td></tr>".format(html.escape(str(kind)), html.escape(str(count)))
        for kind, count in sorted(command_audit.get("by_command_kind", {}).items())
    ) or '<tr><td colspan="2">SKIPPED_WITH_REASON: 无 command log 样本</td></tr>'
    management_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(item.get("operation_name", "MISSING"))),
            html.escape(str(item.get("operation_duration_ms", "MISSING"))),
            html.escape(str(item.get("operation_status", "MISSING"))),
            html.escape(str(item.get("command_count", 0))),
        )
        for item in management.get("duration_ranking_topN", [])[:11]
    ) or '<tr><td colspan="4">SKIPPED_WITH_REASON: 无管理操作样本</td></tr>'
    topology_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(item.get("operation_id", "MISSING"))),
            html.escape(str(item.get("known_nodes_delta", "MISSING"))),
            html.escape(str(item.get("moved_slot_range_count", "MISSING"))),
            html.escape(str(item.get("status", "MISSING"))),
        )
        for item in management.get("topology_diff_summary", [])[:10]
    ) or '<tr><td colspan="4">SKIPPED_WITH_REASON: 无 topology diff 样本</td></tr>'
    workload_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(item.get("profile", "MISSING"))),
            html.escape(str(item.get("window_name", "MISSING"))),
            html.escape(str(item.get("achieved_qps", "MISSING"))),
            html.escape(str(item.get("latency_p99_ms", "MISSING"))),
            html.escape(str(item.get("error_rate", "MISSING"))),
        )
        for item in workload.get("windows", [])[:12]
    ) or '<tr><td colspan="5">SKIPPED_WITH_REASON: 无 workload benchmark 样本</td></tr>'
    fault_event_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(item.get("sample_id", "MISSING"))),
            html.escape(str(item.get("observed_event_count", 0))),
            html.escape(", ".join(str(name) for name in item.get("missing_events", [])) or "none"),
        )
        for item in fault.get("event_completeness", [])[:10]
    ) or '<tr><td colspan="3">SKIPPED_WITH_REASON: 无 fault timeline 样本</td></tr>'
    fault_distribution_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(name),
            html.escape(str((fault.get(name, {}) if isinstance(fault, dict) else {}).get("p50_ms", "MISSING"))),
            html.escape(str((fault.get(name, {}) if isinstance(fault, dict) else {}).get("p95_ms", "MISSING"))),
            html.escape(str((fault.get(name, {}) if isinstance(fault, dict) else {}).get("max_ms", "MISSING"))),
            html.escape(str((fault.get(name, {}) if isinstance(fault, dict) else {}).get("status", "MISSING"))),
        )
        for name in ["failover_latency", "promotion_latency", "client_unavailability", "workload_recovery"]
    )
    split_brain_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(name),
            html.escape(str((fault.get(name, {}) if isinstance(fault, dict) else {}).get("p95_ms", "MISSING"))),
            html.escape(str((fault.get(name, {}) if isinstance(fault, dict) else {}).get("max_ms", "MISSING"))),
            html.escape(str((fault.get(name, {}) if isinstance(fault, dict) else {}).get("status", "MISSING"))),
        )
        for name in ["split_brain_window", "cluster_down_window"]
    )
    fault_workload_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(row.get("fault_type", "MISSING"))),
            html.escape(str(row.get("sample_id", "MISSING"))),
            html.escape(_display_metric((row.get("metrics", {}) if isinstance(row, dict) else {}).get("client_unavailability_ms"))),
            html.escape(_display_metric((row.get("metrics", {}) if isinstance(row, dict) else {}).get("workload_recovery_ms"))),
            html.escape(str(row.get("status", "MISSING"))),
        )
        for row in fault.get("rows", [])[:10]
    ) or '<tr><td colspan="5">SKIPPED_WITH_REASON: 无故障期间 workload impact 输入</td></tr>'
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>P09 Analysis Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #202124; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; text-align: left; }}
    th {{ background: #f6f8fa; }}
    code {{ background: #f6f8fa; padding: 2px 4px; }}
  </style>
</head>
<body>
  <h1>P09 Analysis Report</h1>
  <p>Status: <code>{html.escape(str(analysis.get("status", "MISSING")))}</code></p>
  <p>Source phase: <code>{html.escape(str(analysis.get("source", {}).get("phase_id", "MISSING")))}</code></p>
  <h2>运行元数据</h2>
  <table><thead><tr><th>字段</th><th>值</th></tr></thead><tbody>{metadata_rows}</tbody></table>
  <h2>分析发现</h2>
  <table><thead><tr><th>Name</th><th>Status</th></tr></thead><tbody>{finding_rows}</tbody></table>
  <h2>缺失指标</h2>
  <table><thead><tr><th>指标</th><th>状态</th><th>原因</th></tr></thead><tbody>{missing_rows}</tbody></table>
  <h2>集群拉起瀑布图</h2>
  <img src="setup_waterfall.svg" alt="集群拉起瀑布图">
  <h2>阶段耗时排序</h2>
  <table><thead><tr><th>阶段指标</th><th>耗时 ms</th></tr></thead><tbody>{setup_rows}</tbody></table>
  <h2>慢节点 TopN</h2>
  <table><thead><tr><th>节点</th><th>ready ms</th><th>角色</th><th>状态</th></tr></thead><tbody>{slow_node_rows}</tbody></table>
  <h2>慢命令 TopN</h2>
  <img src="command_latency.svg" alt="命令耗时分布">
  <table><thead><tr><th>命令</th><th>操作</th><th>类型</th><th>耗时 ms</th><th>状态</th></tr></thead><tbody>{slow_command_rows}</tbody></table>
  <h2>失败命令</h2>
  <table><thead><tr><th>命令</th><th>操作</th><th>类型</th><th>耗时 ms</th><th>状态</th></tr></thead><tbody>{failed_command_rows}</tbody></table>
  <h2>重试命令</h2>
  <table><thead><tr><th>命令</th><th>操作</th><th>类型</th><th>耗时 ms</th><th>状态</th></tr></thead><tbody>{retry_command_rows}</tbody></table>
  <h2>命令审计覆盖</h2>
  <table><thead><tr><th>命令类型</th><th>数量</th></tr></thead><tbody>{command_coverage_rows}</tbody></table>
  <h2>管理操作矩阵</h2>
  <img src="management_operation_duration.svg" alt="管理操作耗时排序">
  <table><thead><tr><th>操作</th><th>耗时 ms</th><th>状态</th><th>命令数</th></tr></thead><tbody>{management_rows}</tbody></table>
  <h2>管理 topology diff 摘要</h2>
  <img src="management_topology_diff.svg" alt="管理 topology diff 摘要">
  <table><thead><tr><th>操作</th><th>known_nodes_delta</th><th>moved_slot_ranges</th><th>状态</th></tr></thead><tbody>{topology_rows}</tbody></table>
  <h2>Workload 基准压测</h2>
  <p>覆盖 profile: <code>{html.escape(", ".join(str(item) for item in workload.get("profiles_covered", [])))}</code>；全 slot 覆盖: <code>{html.escape(str(workload.get("full_slot_covered", "MISSING")))}</code>。该结论来自本地 workload artifact，不依赖 LLM 或外网。</p>
  <img src="workload_qps_p99_error.svg" alt="Workload QPS p99 错误率对比">
  <table><thead><tr><th>压测 profile</th><th>采集窗口</th><th>实际 QPS</th><th>p99 延迟 ms</th><th>错误率</th></tr></thead><tbody>{workload_rows}</tbody></table>
  <h2>故障 Timeline</h2>
  <img src="fault_timeline.svg" alt="故障 Timeline">
  <table><thead><tr><th>样本</th><th>观察事件数</th><th>缺失事件</th></tr></thead><tbody>{fault_event_rows}</tbody></table>
  <h2>Failover 延迟分布</h2>
  <img src="failover_latency_distribution.svg" alt="Failover 延迟分布">
  <table><thead><tr><th>指标</th><th>p50 ms</th><th>p95 ms</th><th>max ms</th><th>状态</th></tr></thead><tbody>{fault_distribution_rows}</tbody></table>
  <h2>Split-brain 窗口</h2>
  <img src="split_brain_window.svg" alt="Split-brain 窗口">
  <table><thead><tr><th>指标</th><th>p95 ms</th><th>max ms</th><th>状态</th></tr></thead><tbody>{split_brain_rows}</tbody></table>
  <h2>故障期间 Workload 影响</h2>
  <img src="fault_workload_impact.svg" alt="故障期间 Workload 影响">
  <table><thead><tr><th>故障类型</th><th>样本</th><th>客户端不可用 ms</th><th>workload 恢复 ms</th><th>状态</th></tr></thead><tbody>{fault_workload_rows}</tbody></table>
  <h2>图表</h2>
  <img src="metric_chart.svg" alt="P09 artifact metrics chart">
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")
    return path


def _command_html_rows(rows: list[dict[str, Any]]) -> str:
    return "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(item.get("command_id", "MISSING"))),
            html.escape(str(item.get("operation_id", "MISSING"))),
            html.escape(str(item.get("command_kind", "MISSING"))),
            html.escape(str(item.get("duration_ms", "MISSING"))),
            html.escape(str(item.get("status", "MISSING"))),
        )
        for item in rows
        if isinstance(item, dict)
    )


def _write_phase_summary(phase_dir: Path, analysis: dict[str, Any], index_path: Path, reports: list[Path]) -> None:
    phase_summary = {
        "schema_version": "v1",
        "artifact_type": "phase_summary",
        "phase_id": PHASE_ID,
        "run_id": str(analysis.get("run_id") or RUN_ID),
        "created_at": str(analysis.get("created_at") or CREATED_AT),
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "summary": "P09 analyzed prior real Valkey failover artifacts and rendered deterministic machine-readable, tabular, chart, HTML, and markdown report outputs without inventing missing metrics.",
        "required_artifacts": [
            "artifacts/phases/P09_ANALYSIS_REPORTING/phase_summary.json",
            "artifacts/phases/P09_ANALYSIS_REPORTING/analysis_summary.json",
            "artifacts/phases/P09_ANALYSIS_REPORTING/report_index.json",
            "artifacts/phases/P09_ANALYSIS_REPORTING/valkey_e2e_evidence.json",
            "artifacts/phases/P09_ANALYSIS_REPORTING/cleanup_report.json",
        ],
        "missing_metrics": list(analysis.get("missing_metrics", [])),
        "run_manifest_ref": analysis.get("run_manifest_ref"),
        "run_metadata_ref": analysis.get("run_metadata_ref"),
        "risks": [
            {
                "risk": "Baseline comparison is initialized with NO_BASELINE_YET until a versioned baseline exists.",
                "severity": "low",
                "required_before_next_phase": False,
            }
        ],
        "report_index": _rel(index_path),
        "report_outputs": [_rel(path) for path in reports],
    }
    _write_json(phase_dir / "phase_summary.json", phase_summary)


def _report_record(path: Path) -> dict[str, str]:
    return {"path": _rel(path), "sha256": _sha256_file(path)}


def _metadata_value(metadata: Any, key: str) -> str:
    if not isinstance(metadata, dict):
        return "SKIPPED_WITH_REASON: no run metadata attached"
    value = metadata.get(key, {"status": "MISSING", "reason": f"{key} absent from run metadata"})
    if isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON"}:
        return f"{value.get('status')}: {value.get('reason', '')}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
