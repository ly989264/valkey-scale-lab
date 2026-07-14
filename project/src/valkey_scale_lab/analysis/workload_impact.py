from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__

CAPABILITY_ID = "fault_workload_impact"
RUN_ID = "fault_workload_impact-workload-impact-20260703"
SCENARIO_NAME = "fault_workload_impact"
CREATED_AT = "2026-07-03T00:00:00Z"
TIMESTAMP_UNIX_MS = 1783036800000
CANONICAL_WINDOWS = ["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]
REQUIRED_COMPARISON_WINDOWS = ["baseline", "event", "recovery", "post_recovery"]
ERROR_TAXONOMY_FIELDS = [
    "timeout_count",
    "connection_error_count",
    "moved_redirection_count",
    "ask_redirection_count",
    "cluster_down_error_count",
    "readonly_error_count",
    "tryagain_error_count",
    "unknown_error_count",
    "error_ops",
]


class WorkloadImpactError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceCapability:
    capability_id: str
    category: str
    windows_artifact: str
    metadata_artifact: str
    key_field: str
    row_kind_field: str


SOURCE_CAPABILITIES = [
    SourceCapability(
        "management_matrix",
        "management",
        "workload_windows.json",
        "management_operation_results.jsonl",
        "operation_id",
        "operation_name",
    ),
    SourceCapability(
        "failover_latency_curve",
        "failover",
        "workload_impact_report.json",
        "failover_latency_samples.jsonl",
        "sample_id",
        "fault_type",
    ),
    SourceCapability(
        "fault_matrix",
        "fault",
        "fault_workload_impact.json",
        "fault_operation_results.jsonl",
        "fault_id",
        "fault_type",
    ),
]


def build_workload_impact_analysis(
    source_root: str | Path,
    out_dir: str | Path,
    *,
    capability_id: str = CAPABILITY_ID,
    run_id: str = RUN_ID,
) -> dict[str, Any]:
    if capability_id != CAPABILITY_ID:
        raise WorkloadImpactError(f"workload-impact analysis only supports {CAPABILITY_ID}, got {capability_id}")
    source_root_path = Path(source_root)
    if not source_root_path.exists():
        raise WorkloadImpactError(f"source capabilities root does not exist: {source_root_path}")
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    missing_items: list[dict[str, Any]] = []
    source_statuses: list[dict[str, Any]] = []
    source_artifacts: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []

    for spec in SOURCE_CAPABILITIES:
        capability_dir = source_root_path / spec.capability_id
        capability_rows, status, artifacts = _load_source_capability(spec, capability_dir, missing_items)
        source_statuses.append(status)
        source_artifacts.update(artifacts)
        rows.extend(capability_rows)

    row_counts = {
        "total": len(rows),
        "management": sum(1 for row in rows if row.get("category") == "management"),
        "failover": sum(1 for row in rows if row.get("category") == "failover"),
        "fault": sum(1 for row in rows if row.get("category") == "fault"),
        "missing_rows": sum(1 for row in rows if row.get("status") != "PASS"),
        "partition_fault_matrix_rows": sum(1 for row in rows if row.get("source_capability_id") == "fault_matrix"),
    }
    analysis = {
        "schema_version": "v1",
        "artifact_type": "workload_impact_analysis",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS" if all(status["status"] == "PASS" for status in source_statuses) else "PARTIAL",
        "derivation_rules": {
            "inputs": "Canonical management_matrix, failover_latency_curve, and fault_matrix JSON/JSONL artifacts only",
            "log_parsing": False,
            "source_scenarios_rerun": False,
            "fault_or_operation_qps_ratio": "event.achieved_qps / baseline.achieved_qps",
            "latency_delta_ms": "event percentile - baseline percentile",
            "error_rate_delta": "event.error_rate - baseline.error_rate",
            "recovery_duration_ms": "recovery.duration_seconds * 1000 when present",
        },
        "source_capability_statuses": source_statuses,
        "source_artifacts": sorted(source_artifacts.values(), key=lambda item: item["path"]),
        "rows": rows,
        "row_counts": row_counts,
    }
    cross_path = out_path / "workload_impact_analysis.json"
    _write_json(cross_path, analysis)

    exports = _write_csv_exports(out_path, rows, capability_id, run_id)
    analysis["csv_exports"] = exports
    analysis["missing_data_summary_ref"] = "missing_data_summary.json"
    _write_json(cross_path, analysis)

    missing_summary = _missing_summary(missing_items, rows, capability_id, run_id)
    _write_json(out_path / "missing_data_summary.json", missing_summary)
    _write_json(out_path / "csv_export_index.json", _csv_index(exports, capability_id, run_id))
    events = _events(source_statuses, rows, capability_id, run_id)
    metrics = _metrics(source_statuses, row_counts, missing_summary, capability_id, run_id)
    _write_jsonl(out_path / "events.jsonl", events)
    _write_jsonl(out_path / "metrics_timeseries.jsonl", metrics)
    _write_json(out_path / "workload_windows.json", _analysis_workload_windows(rows, capability_id, run_id))
    _write_json(out_path / "run_summary.json", _run_summary(row_counts, missing_summary, capability_id, run_id))
    _write_json(out_path / "quant_summary.json", _quant_summary(row_counts, missing_summary, events, metrics, exports, source_artifacts, capability_id, run_id))
    return analysis


def _load_source_capability(
    spec: SourceCapability,
    capability_dir: Path,
    missing_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, dict[str, Any]]]:
    artifacts: dict[str, dict[str, Any]] = {}
    if not capability_dir.exists():
        reason = f"required source capability artifact directory is absent: {capability_dir.as_posix()}"
        missing_items.append(_missing(spec.capability_id, capability_dir.as_posix(), "capability_dir", reason))
        return (
            [_missing_row(spec, reason)],
            {"capability_id": spec.capability_id, "category": spec.category, "status": "MISSING", "reason": reason, "row_count": 1},
            artifacts,
        )

    windows_path = capability_dir / spec.windows_artifact
    metadata_path = capability_dir / spec.metadata_artifact
    for path in [windows_path, metadata_path]:
        if path.exists():
            artifacts[path.as_posix()] = _artifact_record(path)

    if not windows_path.exists() or not metadata_path.exists():
        missing_name = spec.windows_artifact if not windows_path.exists() else spec.metadata_artifact
        reason = f"required source artifact is absent: {missing_name}"
        missing_items.append(_missing(spec.capability_id, capability_dir.as_posix(), missing_name, reason))
        return (
            [_missing_row(spec, reason)],
            {"capability_id": spec.capability_id, "category": spec.category, "status": "MISSING", "reason": reason, "row_count": 1},
            artifacts,
        )

    windows_obj = _load_json(windows_path)
    windows = [window for window in windows_obj.get("windows", []) if isinstance(window, dict)]
    metadata_rows = _read_jsonl(metadata_path)
    windows_by_key: dict[str, dict[str, dict[str, Any]]] = {}
    for window in windows:
        key = window.get(spec.key_field)
        if not key:
            continue
        windows_by_key.setdefault(str(key), {})[str(window.get("window_name"))] = window

    metadata_by_key = {str(row.get(spec.key_field)): (line_no, row) for line_no, row in metadata_rows if row.get(spec.key_field)}
    keys = sorted(set(windows_by_key) | set(metadata_by_key))
    rows: list[dict[str, Any]] = []
    for key in keys:
        line_no, metadata = metadata_by_key.get(key, (None, {}))
        row = _build_row(spec, key, metadata, line_no, windows_by_key.get(key, {}), windows_path, metadata_path, missing_items)
        rows.append(row)
    status = {
        "capability_id": spec.capability_id,
        "category": spec.category,
        "status": "PASS",
        "row_count": len(rows),
        "source_artifacts": [windows_path.as_posix(), metadata_path.as_posix()],
    }
    return rows, status, artifacts


def _build_row(
    spec: SourceCapability,
    entity_id: str,
    metadata: dict[str, Any],
    metadata_line_no: int | None,
    windows: dict[str, dict[str, Any]],
    windows_path: Path,
    metadata_path: Path,
    missing_items: list[dict[str, Any]],
) -> dict[str, Any]:
    source_capability = spec.capability_id
    row_id = f"{source_capability}:{entity_id}"
    category = spec.category
    operation_id = entity_id if category == "management" else ""
    sample_id = entity_id if category != "management" else ""
    operation_name = str(metadata.get("operation_name", ""))
    fault_type = str(metadata.get("fault_type") or ("primary_stop_failover" if category == "failover" else ""))
    node_count = metadata.get("node_count", _first_window_value(windows, "node_count", "MISSING"))
    status = str(metadata.get("operation_status") or metadata.get("status") or "PASS")
    window_records: dict[str, Any] = {}
    missing_reasons: dict[str, str] = {}

    for name in CANONICAL_WINDOWS:
        window = windows.get(name)
        field = f"windows.{name}"
        if not window:
            reason = f"{name} window is absent for {entity_id} in {windows_path.as_posix()}"
            missing_reasons[field] = reason
            missing_items.append(_missing(source_capability, windows_path.as_posix(), field, reason, entity_id=entity_id))
            window_records[name] = {
                "status": "MISSING",
                "reason": reason,
                "metrics": {},
                "source_ref": {"artifact": windows_path.as_posix(), "pointer": f"/windows/{entity_id}/{name}"},
            }
            continue
        metrics = dict(window.get("metrics", {})) if isinstance(window.get("metrics"), dict) else {}
        _collect_metric_missing(source_capability, windows_path, entity_id, name, metrics, missing_items)
        window_records[name] = {
            "status": window.get("status", "PASS"),
            "metrics": metrics,
            "start_event_id": window.get("start_event_id", "MISSING"),
            "end_event_id": window.get("end_event_id", "MISSING"),
            "profile": window.get("profile", "MISSING"),
            "workload_mode": window.get("workload_mode", "MISSING"),
            "hash_slot_distribution": window.get("hash_slot_distribution", "MISSING"),
            "key_slot_coverage": window.get("key_slot_coverage", {}),
            "source_ref": {"artifact": windows_path.as_posix(), "pointer": f"/windows/{entity_id}/{name}"},
        }

    derived = _derived_metrics(row_id, window_records, missing_reasons, missing_items, source_capability, windows_path, entity_id)
    row_status = "PASS" if status == "PASS" and all(name in windows for name in REQUIRED_COMPARISON_WINDOWS) else "MISSING"
    reason = "" if row_status == "PASS" else "; ".join(missing_reasons.values()) or f"source status is {status}"
    return {
        "schema_version": "v1",
        "row_id": row_id,
        "source_capability_id": source_capability,
        "category": category,
        "status": row_status,
        "reason": reason,
        "operation_id": operation_id,
        "operation_name": operation_name,
        "sample_id": sample_id,
        "fault_id": str(metadata.get("fault_id", "")),
        "fault_type": fault_type,
        "fault_timeline_ref": metadata.get("fault_timeline_ref", metadata.get("timeline_ref", "")),
        "fault_event_window": metadata.get("fault_event_window", {"start_event": "fault_apply_completed", "end_event": "workload_recovered"} if category != "management" else {}),
        "client_unavailability_ms": metadata.get("client_unavailability_ms", _first_metric_value(window_records, "client_unavailability_ms", "MISSING")),
        "cluster_down_window_ms": metadata.get("cluster_down_window_ms", _first_metric_value(window_records, "cluster_down_window_ms", "MISSING")),
        "workload_recovery_ms": metadata.get("workload_recovery_ms", _first_metric_value(window_records, "workload_recovery_ms", derived.get("recovery_duration_ms", "MISSING"))),
        "node_count": node_count,
        "source_status": status,
        "source_refs": [
            {
                "artifact": metadata_path.as_posix(),
                "sha256": _sha256_file(metadata_path),
                "line": metadata_line_no,
                "pointer": f"{spec.key_field}={entity_id}",
            },
            {
                "artifact": windows_path.as_posix(),
                "sha256": _sha256_file(windows_path),
                "pointer": f"{spec.key_field}={entity_id}",
            },
        ],
        "window_refs": {name: record["source_ref"] for name, record in window_records.items()},
        "windows": window_records,
        "profile": _first_window_value(window_records, "profile", "MISSING"),
        "workload_mode": _first_window_value(window_records, "workload_mode", "MISSING"),
        "key_slot_coverage": _first_window_value(window_records, "key_slot_coverage", {}),
        "derived": derived,
        "error_taxonomy": _error_taxonomy(window_records),
    }


def _derived_metrics(
    row_id: str,
    window_records: dict[str, Any],
    missing_reasons: dict[str, str],
    missing_items: list[dict[str, Any]],
    source_capability: str,
    windows_path: Path,
    entity_id: str,
) -> dict[str, Any]:
    baseline = window_records.get("baseline", {}).get("metrics", {})
    event = window_records.get("event", {}).get("metrics", {})
    recovery = window_records.get("recovery", {}).get("metrics", {})
    post = window_records.get("post_recovery", {}).get("metrics", {})

    derived = {
        "fault_or_operation_qps_ratio": _ratio(event.get("achieved_qps"), baseline.get("achieved_qps"), row_id, "fault_or_operation_qps_ratio", missing_items, source_capability, windows_path, entity_id),
        "post_recovery_qps_ratio": _ratio(post.get("achieved_qps"), baseline.get("achieved_qps"), row_id, "post_recovery_qps_ratio", missing_items, source_capability, windows_path, entity_id),
        "latency_p50_delta_ms": _delta(event.get("latency_p50_ms"), baseline.get("latency_p50_ms"), row_id, "latency_p50_delta_ms", missing_items, source_capability, windows_path, entity_id),
        "latency_p95_delta_ms": _delta(event.get("latency_p95_ms"), baseline.get("latency_p95_ms"), row_id, "latency_p95_delta_ms", missing_items, source_capability, windows_path, entity_id),
        "latency_p99_delta_ms": _delta(event.get("latency_p99_ms"), baseline.get("latency_p99_ms"), row_id, "latency_p99_delta_ms", missing_items, source_capability, windows_path, entity_id),
        "error_rate_delta": _delta(event.get("error_rate"), baseline.get("error_rate"), row_id, "error_rate_delta", missing_items, source_capability, windows_path, entity_id),
        "recovery_duration_ms": _duration_ms(recovery, row_id, "recovery_duration_ms", missing_items, source_capability, windows_path, entity_id),
        "missing_reasons": missing_reasons,
    }
    for field, value in list(derived.items()):
        if field != "missing_reasons" and value == "MISSING":
            missing_reasons.setdefault(field, f"{field} could not be derived from source window metrics.")
    return derived


def _ratio(numerator: Any, denominator: Any, row_id: str, field: str, missing_items: list[dict[str, Any]], source_capability: str, path: Path, entity_id: str) -> float | str:
    if not _is_number(numerator) or not _is_number(denominator) or float(denominator) == 0.0:
        reason = f"{field} cannot be derived for {row_id}; numerator={numerator!r} denominator={denominator!r}"
        missing_items.append(_missing(source_capability, path.as_posix(), field, reason, entity_id=entity_id))
        return "MISSING"
    return round(float(numerator) / float(denominator), 6)


def _delta(current: Any, baseline: Any, row_id: str, field: str, missing_items: list[dict[str, Any]], source_capability: str, path: Path, entity_id: str) -> float | str:
    if not _is_number(current) or not _is_number(baseline):
        reason = f"{field} cannot be derived for {row_id}; current={current!r} baseline={baseline!r}"
        missing_items.append(_missing(source_capability, path.as_posix(), field, reason, entity_id=entity_id))
        return "MISSING"
    return round(float(current) - float(baseline), 6)


def _duration_ms(metrics: dict[str, Any], row_id: str, field: str, missing_items: list[dict[str, Any]], source_capability: str, path: Path, entity_id: str) -> float | str:
    seconds = metrics.get("duration_seconds")
    if _is_number(seconds):
        return round(float(seconds) * 1000.0, 6)
    reason = f"{field} cannot be derived for {row_id}; recovery.duration_seconds is {seconds!r}"
    missing_items.append(_missing(source_capability, path.as_posix(), field, reason, entity_id=entity_id))
    return "MISSING"


def _write_csv_exports(out_path: Path, rows: list[dict[str, Any]], capability_id: str, run_id: str) -> list[dict[str, Any]]:
    specs = [
        ("workload_impact_by_operation.csv", "operation", [row for row in rows if row.get("category") == "management"], _operation_csv_row),
        ("workload_impact_by_fault.csv", "fault", [row for row in rows if row.get("category") in {"failover", "fault"}], _fault_csv_row),
        ("latency_delta_table.csv", "latency", rows, _latency_csv_row),
        ("error_delta_table.csv", "error", rows, _error_csv_row),
        ("recovery_duration_table.csv", "recovery", rows, _recovery_csv_row),
    ]
    exports: list[dict[str, Any]] = []
    for filename, table_name, export_rows, row_func in specs:
        path = out_path / filename
        csv_rows = [row_func(row) for row in export_rows]
        fieldnames = sorted({key for csv_row in csv_rows for key in csv_row} | {"row_id"})
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)
        exports.append(
            {
                "table_name": table_name,
                "path": path.as_posix(),
                "row_count": len(csv_rows),
                "json_source_count": len(export_rows),
                "json_source_artifact": (out_path / "workload_impact_analysis.json").as_posix(),
                "sha256": _sha256_file(path),
                "capability_id": capability_id,
                "run_id": run_id,
            }
        )
    return exports


def _operation_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    derived = row["derived"]
    return {
        "row_id": row["row_id"],
        "source_capability_id": row["source_capability_id"],
        "operation_id": row["operation_id"],
        "operation_name": row["operation_name"],
        "node_count": row["node_count"],
        "status": row["status"],
        "fault_or_operation_qps_ratio": derived["fault_or_operation_qps_ratio"],
        "post_recovery_qps_ratio": derived["post_recovery_qps_ratio"],
    }


def _fault_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    derived = row["derived"]
    return {
        "row_id": row["row_id"],
        "source_capability_id": row["source_capability_id"],
        "sample_id": row["sample_id"],
        "fault_id": row["fault_id"],
        "fault_type": row["fault_type"],
        "node_count": row["node_count"],
        "status": row["status"],
        "fault_window_qps_ratio": derived["fault_or_operation_qps_ratio"],
        "post_recovery_qps_ratio": derived["post_recovery_qps_ratio"],
    }


def _latency_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    derived = row["derived"]
    return {
        "row_id": row["row_id"],
        "source_capability_id": row["source_capability_id"],
        "category": row["category"],
        "comparison_id": row["operation_id"] or row["sample_id"],
        "latency_p50_delta_ms": derived["latency_p50_delta_ms"],
        "latency_p95_delta_ms": derived["latency_p95_delta_ms"],
        "latency_p99_delta_ms": derived["latency_p99_delta_ms"],
        "status": row["status"],
    }


def _error_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_id": row["row_id"],
        "source_capability_id": row["source_capability_id"],
        "category": row["category"],
        "comparison_id": row["operation_id"] or row["sample_id"],
        "error_rate_delta": row["derived"]["error_rate_delta"],
        "event_error_ops": row["windows"].get("event", {}).get("metrics", {}).get("error_ops", "MISSING"),
        "event_cluster_down_error_count": row["windows"].get("event", {}).get("metrics", {}).get("cluster_down_error_count", "MISSING"),
        "status": row["status"],
    }


def _recovery_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_id": row["row_id"],
        "source_capability_id": row["source_capability_id"],
        "category": row["category"],
        "comparison_id": row["operation_id"] or row["sample_id"],
        "recovery_duration_ms": row["derived"]["recovery_duration_ms"],
        "post_recovery_qps_ratio": row["derived"]["post_recovery_qps_ratio"],
        "status": row["status"],
    }


def _error_taxonomy(window_records: dict[str, Any]) -> dict[str, dict[str, Any]]:
    taxonomy: dict[str, dict[str, Any]] = {}
    for window_name, record in window_records.items():
        metrics = record.get("metrics", {})
        taxonomy[window_name] = {field: metrics.get(field, "MISSING") for field in ERROR_TAXONOMY_FIELDS}
    return taxonomy


def _analysis_workload_windows(rows: list[dict[str, Any]], capability_id: str, run_id: str) -> dict[str, Any]:
    windows = []
    for index, name in enumerate(CANONICAL_WINDOWS, start=1):
        sample_count = sum(1 for row in rows if row.get("windows", {}).get(name, {}).get("status") == "PASS")
        metrics = {
            "requested_qps": "MISSING",
            "achieved_qps": "MISSING",
            "ok_ops": "MISSING",
            "error_ops": "MISSING",
            "error_rate": "MISSING",
            "latency_p50_ms": "MISSING",
            "latency_p90_ms": "MISSING",
            "latency_p95_ms": "MISSING",
            "latency_p99_ms": "MISSING",
            "latency_p999_ms": "MISSING",
            "timeout_count": "MISSING",
            "connection_error_count": "MISSING",
            "moved_redirection_count": "MISSING",
            "ask_redirection_count": "MISSING",
            "cluster_down_error_count": "MISSING",
            "readonly_error_count": "MISSING",
            "tryagain_error_count": "MISSING",
            "unknown_error_count": "MISSING",
            "sample_count": sample_count,
            "missing_reasons": {
                "requested_qps": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "achieved_qps": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "ok_ops": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "error_ops": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "error_rate": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "latency_p50_ms": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "latency_p90_ms": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "latency_p95_ms": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "latency_p99_ms": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "latency_p999_ms": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "timeout_count": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "connection_error_count": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "moved_redirection_count": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "ask_redirection_count": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "cluster_down_error_count": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "readonly_error_count": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "tryagain_error_count": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
                "unknown_error_count": "FAULT_WORKLOAD_IMPACT is a consolidated analysis and does not run a workload window itself.",
            },
        }
        windows.append(
            {
                "window_name": name,
                "start_event_id": f"fault_workload_impact-{name}-start",
                "end_event_id": f"fault_workload_impact-{name}-end",
                "status": "SKIPPED_WITH_REASON",
                "reason": "FAULT_WORKLOAD_IMPACT consolidates source workload windows instead of running new workload windows.",
                "metrics": metrics,
                "analysis_source_row_count": sample_count,
                "sequence": index,
            }
        )
    return {
        "schema_version": "v1",
        "artifact_type": "workload_windows",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "SKIPPED_WITH_REASON",
        "reason": "FAULT_WORKLOAD_IMPACT analysis derives from canonical management and fault capabilities workload windows and does not run its own workload workload.",
        "windows": windows,
    }


def _events(source_statuses: list[dict[str, Any]], rows: list[dict[str, Any]], capability_id: str, run_id: str) -> list[dict[str, Any]]:
    events = [
        _event("fault_workload_impact-analysis-started", "analysis_started", "analysis", "consolidated", "Started FAULT_WORKLOAD_IMPACT workload impact analysis.", 0, capability_id, run_id),
    ]
    for idx, status in enumerate(source_statuses, start=1):
        events.append(
            _event(
                f"fault_workload_impact-source-{idx:02d}",
                "source_capability_loaded" if status.get("status") == "PASS" else "source_capability_missing",
                "source_capability",
                str(status.get("capability_id")),
                f"Source capability {status.get('capability_id')} status {status.get('status')}.",
                idx,
                capability_id,
                run_id,
                metadata=status,
            )
        )
    events.append(
        _event(
            "fault_workload_impact-analysis-finished",
            "analysis_finished",
            "analysis",
            "consolidated",
            f"Finished FAULT_WORKLOAD_IMPACT workload impact analysis with {len(rows)} rows.",
            len(source_statuses) + 1,
            capability_id,
            run_id,
            metadata={"row_count": len(rows)},
        )
    )
    return events


def _metrics(source_statuses: list[dict[str, Any]], row_counts: dict[str, int], missing_summary: dict[str, Any], capability_id: str, run_id: str) -> list[dict[str, Any]]:
    metrics = []
    for name, value in row_counts.items():
        metrics.append(_metric(f"consolidated_{name}_row_count", value, "count", "consolidated", capability_id, run_id, {"scope": "fault_workload_impact"}))
    metrics.append(_metric("missing_data_item_count", missing_summary["item_count"], "count", "missing_data", capability_id, run_id, {"scope": "fault_workload_impact"}))
    for status in source_statuses:
        metrics.append(
            _metric(
                "source_capability_row_count",
                int(status.get("row_count", 0) or 0),
                "count",
                str(status.get("capability_id")),
                capability_id,
                run_id,
                {"source_capability_id": str(status.get("capability_id")), "status": str(status.get("status"))},
            )
        )
    return metrics


def _run_summary(row_counts: dict[str, int], missing_summary: dict[str, Any], capability_id: str, run_id: str) -> dict[str, Any]:
    required = [
        "run_summary.json",
        "events.jsonl",
        "metrics_timeseries.jsonl",
        "workload_windows.json",
        "quant_summary.json",
        "workload_impact_analysis.json",
        "workload_impact_by_operation.csv",
        "workload_impact_by_fault.csv",
        "latency_delta_table.csv",
        "error_delta_table.csv",
        "recovery_duration_table.csv",
        "csv_export_index.json",
        "missing_data_summary.json",
    ]
    return {
        "schema_version": "v1",
        "artifact_type": "run_summary",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "summary": f"FAULT_WORKLOAD_IMPACT consolidated {row_counts['total']} workload impact rows from canonical management and fault capabilities JSON/JSONL artifacts.",
        "required_artifacts": required,
        "missing_metrics": [
            {"metric": item["field"], "status": item["status"], "reason": item["reason"], "source_capability_id": item.get("source_capability_id", "")}
            for item in missing_summary["items"]
        ],
        "risks": [],
    }


def _quant_summary(
    row_counts: dict[str, int],
    missing_summary: dict[str, Any],
    events: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    exports: list[dict[str, Any]],
    source_artifacts: dict[str, dict[str, Any]],
    capability_id: str,
    run_id: str,
) -> dict[str, Any]:
    refs = [
        "run_summary.json",
        "valkey_e2e_evidence.json",
        "cleanup_report.json",
        "events.jsonl",
        "metrics_timeseries.jsonl",
        "workload_windows.json",
        "workload_impact_analysis.json",
        "csv_export_index.json",
        "missing_data_summary.json",
    ]
    refs.extend(Path(export["path"]).name for export in exports)
    refs.extend(sorted(source_artifacts))
    return {
        "schema_version": "v1",
        "artifact_type": "quant_summary",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "summary": "FAULT_WORKLOAD_IMPACT derived consolidated workload-impact tables from existing canonical management and fault capabilities artifacts only.",
        "artifact_refs": refs,
        "counts": {
            **row_counts,
            "event_count": len(events),
            "metric_count": len(metrics),
            "csv_export_count": len(exports),
            "missing_data_item_count": missing_summary["item_count"],
        },
        "missing_data": [
            {"field": item["field"], "status": item["status"], "reason": item["reason"], "source_capability_id": item.get("source_capability_id", "")}
            for item in missing_summary["items"]
        ],
        "runtime_claims": {
            "real_valkey_claimed": True,
            "management_runtime_claimed": False,
            "fault_runtime_claimed": False,
            "analysis_only": True,
            "real_valkey_claim_source": "FAULT_WORKLOAD_IMPACT manifest smoke gate writes valkey_e2e_evidence.json separately.",
            "source_runtime_behavior_rerun": False,
        },
    }


def _csv_index(exports: list[dict[str, Any]], capability_id: str, run_id: str) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": "csv_export_index",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "json_source_artifact": "workload_impact_analysis.json",
        "exports": exports,
    }


def _missing_summary(items: list[dict[str, Any]], rows: list[dict[str, Any]], capability_id: str, run_id: str) -> dict[str, Any]:
    deduped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in items:
        key = (str(item.get("source_capability_id")), str(item.get("artifact")), str(item.get("field")), str(item.get("entity_id", "")))
        deduped[key] = item
    summary_items = sorted(deduped.values(), key=lambda item: (item.get("source_capability_id", ""), item.get("artifact", ""), item.get("field", "")))
    return {
        "schema_version": "v1",
        "artifact_type": "missing_data_summary",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "item_count": len(summary_items),
        "affected_row_count": sum(1 for row in rows if row.get("status") != "PASS" or any(value == "MISSING" for key, value in row.get("derived", {}).items() if key != "missing_reasons")),
        "items": summary_items,
    }


def _missing_row(spec: SourceCapability, reason: str) -> dict[str, Any]:
    row_id = f"{spec.capability_id}:MISSING"
    return {
        "schema_version": "v1",
        "row_id": row_id,
        "source_capability_id": spec.capability_id,
        "category": spec.category,
        "status": "MISSING",
        "reason": reason,
        "operation_id": "MISSING" if spec.category == "management" else "",
        "operation_name": "MISSING" if spec.category == "management" else "",
        "sample_id": "MISSING" if spec.category != "management" else "",
        "fault_id": "",
        "fault_type": "MISSING" if spec.category != "management" else "",
        "node_count": "MISSING",
        "source_refs": [],
        "window_refs": {},
        "windows": {},
        "derived": {
            "fault_or_operation_qps_ratio": "MISSING",
            "post_recovery_qps_ratio": "MISSING",
            "latency_p50_delta_ms": "MISSING",
            "latency_p95_delta_ms": "MISSING",
            "latency_p99_delta_ms": "MISSING",
            "error_rate_delta": "MISSING",
            "recovery_duration_ms": "MISSING",
            "missing_reasons": {"source_capability": reason},
        },
        "error_taxonomy": {},
    }


def _missing(source_capability: str, artifact: str, field: str, reason: str, *, entity_id: str = "") -> dict[str, Any]:
    return {
        "source_capability_id": source_capability,
        "artifact": artifact,
        "field": field,
        "status": "MISSING",
        "reason": reason,
        "entity_id": entity_id,
    }


def _collect_metric_missing(source_capability: str, path: Path, entity_id: str, window_name: str, metrics: dict[str, Any], missing_items: list[dict[str, Any]]) -> None:
    reasons = metrics.get("missing_reasons", {})
    if not isinstance(reasons, dict):
        reasons = {}
    for key, value in metrics.items():
        if value == "MISSING":
            reason = str(reasons.get(key) or f"{key} was MISSING in source metrics.")
            missing_items.append(_missing(source_capability, path.as_posix(), f"{entity_id}.{window_name}.{key}", reason, entity_id=entity_id))


def _event(
    event_id: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    message: str,
    offset: int,
    capability_id: str,
    run_id: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "run_id": run_id,
        "capability_id": capability_id,
        "scenario_name": SCENARIO_NAME,
        "sample_id": "consolidated-analysis",
        "event_id": event_id,
        "event_type": event_type,
        "timestamp_unix_ms": TIMESTAMP_UNIX_MS + offset,
        "monotonic_ms": float(offset),
        "severity": "INFO",
        "subject_type": subject_type,
        "subject_id": subject_id,
        "operation_id": "",
        "fault_id": "",
        "message": message,
        "metadata": metadata or {},
    }


def _metric(metric_name: str, value: Any, unit: str, source_id: str, capability_id: str, run_id: str, labels: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "run_id": run_id,
        "capability_id": capability_id,
        "scenario_name": SCENARIO_NAME,
        "sample_id": "consolidated-analysis",
        "timestamp_unix_ms": TIMESTAMP_UNIX_MS,
        "monotonic_ms": 0.0,
        "source_type": "harness",
        "source_id": source_id,
        "metric_name": metric_name,
        "metric_value": value,
        "metric_unit": unit,
        "labels": labels,
        "missing_reason": "",
    }


def _first_window_value(windows: dict[str, dict[str, Any]], key: str, default: Any) -> Any:
    for window in windows.values():
        if key in window:
            return window[key]
    return default


def _first_metric_value(windows: dict[str, dict[str, Any]], key: str, default: Any) -> Any:
    for window in windows.values():
        metrics = window.get("metrics", {}) if isinstance(window, dict) else {}
        if isinstance(metrics, dict) and key in metrics:
            return metrics[key]
    return default


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkloadImpactError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(obj, dict):
        raise WorkloadImpactError(f"JSON artifact must contain an object: {path}")
    return obj


def _read_jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WorkloadImpactError(f"invalid JSONL in {path}:{lineno}: {exc}") from exc
        if not isinstance(obj, dict):
            raise WorkloadImpactError(f"JSONL row must be an object: {path}:{lineno}")
        rows.append((lineno, obj))
    return rows


def _artifact_record(path: Path) -> dict[str, Any]:
    return {"path": path.as_posix(), "sha256": _sha256_file(path), "artifact_type": path.name}


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
