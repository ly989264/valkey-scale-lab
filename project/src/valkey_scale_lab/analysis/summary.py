from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__
from valkey_scale_lab.artifacts import artifact_record, load_json as load_artifact_json, resolve_artifact_input
from valkey_scale_lab.management_matrix import REQUIRED_MANAGEMENT_OPERATIONS
from valkey_scale_lab.observer.failover_timeline import M1_REQUIRED_FAULT_TYPES, M1_REQUIRED_SCALE_RUNGS, M1_REQUIRED_TIMELINE_METRICS

PHASE_ID = "P09_ANALYSIS_REPORTING"
RUN_ID = "P09_ANALYSIS_REPORTING-analysis-20260628"
CREATED_AT = "2026-06-28T00:00:00Z"


class AnalysisError(RuntimeError):
    pass


def create_analysis_summary(input_dir: str | Path, out_path: str | Path) -> dict[str, Any]:
    source_dir, run_manifest = resolve_artifact_input(input_dir)
    if not source_dir.exists():
        raise AnalysisError(f"input artifact directory does not exist: {source_dir}")

    phase_summary = _load_required(source_dir / "phase_summary.json")
    evidence = _load_required(source_dir / "valkey_e2e_evidence.json")
    failover = _load_required(source_dir / "failover_report.json")
    cleanup = _load_required(source_dir / "cleanup_report.json")
    setup_telemetry = _load_optional(source_dir / "setup_telemetry.json")
    command_rows = _load_optional_jsonl(source_dir / "command_log.jsonl")
    command_summary = _load_optional(source_dir / "command_audit_summary.json")
    command_audit = _command_audit_aggregates(command_rows, command_summary)
    management_matrix = _load_optional(source_dir / "management_ops_matrix.json")
    management_results = _load_optional_jsonl(source_dir / "management_operation_results.jsonl")
    management_diffs = _load_optional_jsonl(source_dir / "management_topology_diffs.jsonl")
    management_workload = _load_optional(source_dir / "management_workload_impact.json")
    management_ops = _management_aggregates(management_matrix, management_results, management_diffs, management_workload)
    workload_windows = _load_optional(source_dir / "workload_windows.json")
    workload_report = _load_optional(source_dir / "workload_report.json")
    workload_benchmark = _workload_aggregates(workload_windows, workload_report, management_workload)
    fault_timeline_report = _load_optional(source_dir / "fault_timeline_report.json")
    fault_timeline_events = _load_optional_jsonl(source_dir / "fault_timeline_events.jsonl")
    failover_latency_samples = _load_optional_jsonl(source_dir / "failover_latency_samples.jsonl")
    fault_workload_impact = _load_optional(source_dir / "fault_workload_impact.json")
    fault_timeline = _fault_timeline_aggregates(
        fault_timeline_report,
        fault_timeline_events,
        failover_latency_samples,
        fault_workload_impact,
    )
    system_metrics_report = _load_optional(source_dir / "system_metrics_report.json")
    system_metric_rows = _load_optional_jsonl(source_dir / "system_metrics_timeseries.jsonl")
    if not system_metric_rows:
        system_metric_rows = [
            row for row in _load_optional_jsonl(source_dir / "metrics_timeseries.jsonl")
            if row.get("source_type") in {"system_process", "system_network", "valkey_info", "cluster_info"}
            and isinstance(row.get("labels"), dict)
            and row.get("labels", {}).get("lifecycle_window")
        ]
    system_metrics = _system_metrics_aggregates(system_metrics_report, system_metric_rows)

    missing_metrics = _collect_missing_metrics(phase_summary, failover, setup_telemetry, command_audit, management_ops, workload_benchmark, fault_timeline, system_metrics)
    failovers = list(failover.get("failovers", []))
    primary_failover = failovers[0] if failovers else {}
    failover_latency = primary_failover.get("failover_latency_ms", "MISSING")
    versions = sorted(str(item) for item in evidence.get("valkey_versions", []) if item)

    metrics = [
        _metric("nodes_observed_after_fault", evidence.get("nodes_observed", "MISSING"), "count"),
        _metric("failover_latency_ms", failover_latency, "ms"),
        _metric_from_optional("split_brain_duration_ms", failover.get("summary", {}).get("split_brain_duration_ms"), "ms"),
        _metric("cleanup_resources_remaining", len(cleanup.get("resources_remaining", [])), "count"),
        _metric("workload_achieved_qps", workload_benchmark.get("aggregate", {}).get("achieved_qps", "MISSING"), "ops_per_second"),
        _metric("workload_latency_p99_ms", workload_benchmark.get("aggregate", {}).get("latency_p99_ms", "MISSING"), "ms"),
        _metric("workload_error_rate", workload_benchmark.get("aggregate", {}).get("error_rate", "MISSING"), "ratio"),
        _metric("fault_failover_latency_p95_ms", fault_timeline.get("failover_latency", {}).get("p95_ms", "MISSING"), "ms"),
        _metric("fault_client_unavailability_p95_ms", fault_timeline.get("client_unavailability", {}).get("p95_ms", "MISSING"), "ms"),
        _metric("fault_workload_recovery_p95_ms", fault_timeline.get("workload_recovery", {}).get("p95_ms", "MISSING"), "ms"),
        _metric("fault_split_brain_window_max_ms", fault_timeline.get("split_brain_window", {}).get("max_ms", "MISSING"), "ms"),
        _metric("fault_cluster_down_window_max_ms", fault_timeline.get("cluster_down_window", {}).get("max_ms", "MISSING"), "ms"),
        _metric("system_rss_bytes_max", system_metrics.get("aggregate", {}).get("rss_bytes", {}).get("max", "MISSING"), "bytes"),
        _metric("system_connected_clients_max", system_metrics.get("aggregate", {}).get("connected_clients", {}).get("max", "MISSING"), "count"),
        _metric("system_total_net_input_bytes_max", system_metrics.get("aggregate", {}).get("total_net_input_bytes", {}).get("max", "MISSING"), "bytes"),
    ]
    findings = [
        {
            "name": "source_phase",
            "status": phase_summary.get("status", "MISSING"),
            "source_phase_id": phase_summary.get("phase_id", "MISSING"),
            "source_run_id": phase_summary.get("run_id", "MISSING"),
        },
        {
            "name": "real_valkey_evidence",
            "status": evidence.get("status", "MISSING"),
            "real_valkey": evidence.get("real_valkey", False),
            "valkey_versions": versions,
            "cluster_state_observed": evidence.get("cluster_state_observed", "MISSING"),
            "nodes_observed": evidence.get("nodes_observed", "MISSING"),
        },
        {
            "name": "failover",
            "status": failover.get("status", "MISSING"),
            "target_logical_id": primary_failover.get("target_logical_id", "MISSING"),
            "old_primary_node_id": primary_failover.get("old_primary_node_id", "MISSING"),
            "promoted_node_id": primary_failover.get("promoted_node_id", "MISSING"),
            "failover_latency_ms": failover_latency,
        },
        {
            "name": "cleanup",
            "status": cleanup.get("status", "MISSING"),
            "resources_remaining": cleanup.get("resources_remaining", []),
        },
        {
            "name": "setup_telemetry",
            "status": setup_telemetry.get("status", "SKIPPED_WITH_REASON"),
            "node_count": setup_telemetry.get("node_count", "MISSING"),
            "total_setup_ms": setup_telemetry.get("metrics", {}).get("total_setup_ms", "MISSING") if isinstance(setup_telemetry.get("metrics"), dict) else "MISSING",
        },
        {
            "name": "command_audit",
            "status": command_audit.get("status", "MISSING"),
            "total_commands": command_audit.get("total_commands", 0),
            "failure_count": command_audit.get("failure_count", 0),
            "timeout_count": command_audit.get("timeout_count", 0),
            "retry_count": command_audit.get("retry_count", 0),
        },
        {
            "name": "management_ops",
            "status": management_ops.get("status", "MISSING"),
            "operation_count": management_ops.get("operation_count", 0),
            "missing_required_operations": management_ops.get("missing_required_operations", []),
        },
        {
            "name": "workload_benchmark",
            "status": workload_benchmark.get("status", "MISSING"),
            "profiles_covered": workload_benchmark.get("profiles_covered", []),
            "full_slot_covered": workload_benchmark.get("full_slot_covered", "MISSING"),
            "window_count": workload_benchmark.get("window_count", 0),
        },
        {
            "name": "fault_timeline",
            "status": fault_timeline.get("status", "MISSING"),
            "fault_type_coverage": fault_timeline.get("fault_type_coverage", {}),
            "scale_coverage": fault_timeline.get("scale_coverage", {}),
            "row_count": fault_timeline.get("row_count", 0),
        },
        {
            "name": "system_metrics",
            "status": system_metrics.get("status", "MISSING"),
            "sample_count": system_metrics.get("sample_count", 0),
            "node_count": system_metrics.get("node_count", 0),
            "windows": system_metrics.get("windows", []),
        },
    ]

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    baseline_path = out.parent / "baseline_comparison.json"
    metadata_refs = _metadata_refs(run_manifest)
    run_metadata = _load_run_metadata(run_manifest)
    output_run_id = _metadata_value(run_metadata, "run_id", RUN_ID)
    output_created_at = _metadata_value(run_metadata, "created_at", CREATED_AT)
    baseline = _baseline_comparison(metrics, source_dir, run_id=output_run_id, created_at=output_created_at)
    _write_json(baseline_path, baseline)

    summary = {
        "schema_version": "v1",
        "artifact_type": "analysis_summary",
        "phase_id": PHASE_ID,
        "run_id": output_run_id,
        "created_at": output_created_at,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "source": {
            "input_dir": source_dir.as_posix(),
            "input_kind": "run_manifest" if run_manifest else "artifact_dir",
            "phase_id": phase_summary.get("phase_id", "MISSING"),
            "run_id": phase_summary.get("run_id", "MISSING"),
        },
        "source_artifacts": [_artifact_record(path) for path in _source_artifact_paths(source_dir, out, baseline_path)],
        "run_manifest_ref": metadata_refs.get("run_manifest_ref"),
        "run_metadata_ref": metadata_refs.get("run_metadata_ref"),
        "run_metadata": run_metadata,
        "findings": findings,
        "metrics": metrics,
        "missing_metrics": missing_metrics,
        "setup_telemetry": setup_telemetry
        or {
            "status": "SKIPPED_WITH_REASON",
            "reason": "Input artifacts did not include setup_telemetry.json.",
        },
        "setup_aggregates": _setup_aggregates(setup_telemetry),
        "command_audit": command_audit,
        "management_ops": management_ops,
        "workload_benchmark": workload_benchmark,
        "fault_timeline": fault_timeline,
        "system_metrics": system_metrics,
        "baseline_comparison": baseline,
        "sidecars": [
            {
                "path": _rel(baseline_path),
                "artifact_type": "baseline_comparison",
                "sha256": _sha256_file(baseline_path),
            }
        ],
    }
    _write_json(out, summary)
    return summary


def _load_required(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AnalysisError(f"required source artifact missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AnalysisError(f"source artifact must be a JSON object: {path}")
    return data


def _load_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _load_required(path)


def _load_optional_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise AnalysisError(f"JSONL row {lineno} in {path} is not an object")
            rows.append(row)
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"invalid JSONL in {path}: {exc}") from exc
    return rows


def _metadata_refs(run_manifest: dict[str, Any] | None) -> dict[str, Any]:
    if not run_manifest:
        return {
            "run_manifest_ref": {
                "status": "SKIPPED_WITH_REASON",
                "reason": "Legacy artifact directory input did not include a run_manifest.json.",
            },
            "run_metadata_ref": {
                "status": "SKIPPED_WITH_REASON",
                "reason": "Legacy artifact directory input did not include a run_metadata.json.",
            },
        }
    manifest_path = Path(str(run_manifest["_manifest_path"]))
    metadata_ref = run_manifest.get("run_metadata_ref")
    if not isinstance(metadata_ref, dict):
        metadata_ref = {
            "status": "MISSING",
            "reason": "run_manifest.json did not include run_metadata_ref.",
            "impact": "Analysis cannot link report output back to run metadata.",
        }
    return {
        "run_manifest_ref": {
            "status": "SKIPPED_WITH_REASON",
            "reason": "The final run manifest is refreshed after analysis/report artifacts are written, so analysis records the manifest path without a pre-refresh hash.",
            "path": _rel(manifest_path),
        },
        "run_metadata_ref": metadata_ref,
    }


def _load_run_metadata(run_manifest: dict[str, Any] | None) -> dict[str, Any]:
    if not run_manifest:
        return {
            "status": "SKIPPED_WITH_REASON",
            "reason": "Legacy artifact directory input did not include run metadata.",
        }
    metadata_ref = run_manifest.get("run_metadata_ref")
    manifest_path = Path(str(run_manifest["_manifest_path"]))
    if not isinstance(metadata_ref, dict) or not isinstance(metadata_ref.get("path"), str):
        return {
            "status": "MISSING",
            "reason": "run_manifest.json did not include a readable run_metadata_ref.path.",
            "impact": "Analysis cannot display run-level provenance fields.",
        }
    metadata_path = Path(metadata_ref["path"])
    if not metadata_path.is_absolute():
        metadata_path = Path.cwd() / metadata_path
    try:
        return load_artifact_json(metadata_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "MISSING",
            "reason": f"Could not read run metadata: {exc}",
            "impact": "Analysis cannot display run-level provenance fields.",
        }


def _collect_missing_metrics(
    phase_summary: dict[str, Any],
    failover: dict[str, Any],
    setup_telemetry: dict[str, Any] | None = None,
    command_audit: dict[str, Any] | None = None,
    management_ops: dict[str, Any] | None = None,
    workload_benchmark: dict[str, Any] | None = None,
    fault_timeline: dict[str, Any] | None = None,
    system_metrics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for item in phase_summary.get("missing_metrics", []):
        if isinstance(item, dict) and item.get("metric"):
            found[str(item["metric"])] = dict(item)
    for name, value in failover.get("summary", {}).items():
        if isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON"}:
            metric = str(name)
            found.setdefault(
                metric,
                {
                    "metric": metric,
                    "status": value["status"],
                    "reason": str(value.get("reason", "source artifact reported metric unavailable")),
                    "source": "failover_report.summary",
                },
            )
    if setup_telemetry:
        for item in setup_telemetry.get("missing_metrics", []):
            if isinstance(item, dict) and item.get("metric"):
                metric = f"setup.{item['metric']}"
                found.setdefault(
                    metric,
                    {
                        "metric": metric,
                        "status": item.get("status", "MISSING"),
                        "reason": item.get("reason", "setup telemetry reported metric unavailable"),
                        "impact": item.get("impact", ""),
                        "source": "setup_telemetry.missing_metrics",
                    },
                )
    if command_audit and command_audit.get("status") in {"MISSING", "SKIPPED_WITH_REASON"}:
        for item in command_audit.get("missing_or_skipped", []):
            if isinstance(item, dict) and item.get("metric"):
                found.setdefault(
                    str(item["metric"]),
                    {
                        "metric": str(item["metric"]),
                        "status": item.get("status", "MISSING"),
                        "reason": item.get("reason", "command audit reported metric unavailable"),
                        "impact": item.get("impact", "Command traceability is incomplete."),
                        "source": "command_audit.missing_or_skipped",
                    },
                )
    if management_ops:
        for item in management_ops.get("missing_metrics", []):
            if isinstance(item, dict) and item.get("metric"):
                metric = f"management.{item['metric']}"
                found.setdefault(
                    metric,
                    {
                        "metric": metric,
                        "status": item.get("status", "MISSING"),
                        "reason": item.get("reason", "management operation artifact reported metric unavailable"),
                        "impact": item.get("impact", "Management operation analysis is incomplete."),
                        "source": "management_ops.missing_metrics",
                    },
                )
    if workload_benchmark:
        for item in workload_benchmark.get("missing_metrics", []):
            if isinstance(item, dict) and item.get("metric"):
                metric = f"workload.{item['metric']}"
                found.setdefault(
                    metric,
                    {
                        "metric": metric,
                        "status": item.get("status", "MISSING"),
                        "reason": item.get("reason", "workload benchmark artifact reported metric unavailable"),
                        "impact": item.get("impact", "Workload benchmark analysis is incomplete."),
                        "source": "workload_benchmark.missing_metrics",
                    },
                )
    if fault_timeline:
        for item in fault_timeline.get("missing_metrics", []):
            if isinstance(item, dict) and item.get("metric"):
                metric = f"fault_timeline.{item['metric']}"
                found.setdefault(
                    metric,
                    {
                        "metric": metric,
                        "status": item.get("status", "MISSING"),
                        "reason": item.get("reason", "fault timeline artifact reported metric unavailable"),
                        "impact": item.get("impact", "Fault timeline analysis is incomplete."),
                        "source": "fault_timeline.missing_metrics",
                    },
                )
    if system_metrics:
        for item in system_metrics.get("missing_metrics", []):
            if isinstance(item, dict) and item.get("metric"):
                metric = f"system.{item['metric']}"
                found.setdefault(
                    metric,
                    {
                        "metric": metric,
                        "status": item.get("status", "MISSING"),
                        "reason": item.get("reason", "system metrics reported unavailable metric"),
                        "impact": item.get("impact", "System resource trend analysis is incomplete."),
                        "source": "system_metrics.missing_metrics",
                    },
                )
    return [found[key] for key in sorted(found)]


def _system_metrics_aggregates(report: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return report or {
            "status": "SKIPPED_WITH_REASON",
            "reason": "Input artifacts did not include system_metrics_timeseries.jsonl.",
            "sample_count": 0,
            "node_count": 0,
            "windows": [],
            "per_node": [],
            "per_window": [],
            "aggregate": {},
            "abnormal_nodes_topN": [],
            "missing_metrics": [
                {
                    "metric": "system_metrics_timeseries",
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "System metrics artifact was not present.",
                    "impact": "Report cannot display resource trends or abnormal node TopN.",
                }
            ],
        }
    numeric_by_metric: dict[str, list[float]] = {}
    by_node: dict[str, dict[str, Any]] = {}
    by_window: dict[str, dict[str, Any]] = {}
    missing_metrics: list[dict[str, Any]] = []
    for row in rows:
        labels = row.get("labels", {}) if isinstance(row.get("labels"), dict) else {}
        node_id = str(labels.get("logical_node_id", row.get("source_id", "MISSING")))
        window = str(labels.get("lifecycle_window", labels.get("stage_window", "MISSING")))
        metric_name = str(row.get("metric_name", "MISSING"))
        value = row.get("metric_value", "MISSING")
        by_node.setdefault(node_id, {"node_id": node_id, "sample_count": 0, "missing_count": 0, "windows": set(), "numeric": {}})
        by_window.setdefault(window, {"window": window, "sample_count": 0, "missing_count": 0, "nodes": set(), "numeric": {}})
        by_node[node_id]["sample_count"] += 1
        by_node[node_id]["windows"].add(window)
        by_window[window]["sample_count"] += 1
        by_window[window]["nodes"].add(node_id)
        if value == "MISSING":
            by_node[node_id]["missing_count"] += 1
            by_window[window]["missing_count"] += 1
            missing_metrics.append(
                {
                    "node_id": node_id,
                    "metric": metric_name,
                    "status": "MISSING",
                    "reason": row.get("missing_reason", "metric was MISSING without a source reason"),
                    "window": window,
                    "impact": "This metric is excluded from numeric resource aggregation.",
                }
            )
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric_by_metric.setdefault(metric_name, []).append(float(value))
            by_node[node_id]["numeric"].setdefault(metric_name, []).append(float(value))
            by_window[window]["numeric"].setdefault(metric_name, []).append(float(value))
    aggregate = {name: _numeric_distribution(values) for name, values in sorted(numeric_by_metric.items())}
    per_node = [
        {
            "node_id": node_id,
            "sample_count": item["sample_count"],
            "missing_count": item["missing_count"],
            "windows": sorted(item["windows"]),
            "metrics": {name: _numeric_distribution(values) for name, values in sorted(item["numeric"].items())},
        }
        for node_id, item in sorted(by_node.items())
    ]
    per_window = [
        {
            "window": window,
            "sample_count": item["sample_count"],
            "missing_count": item["missing_count"],
            "node_count": len(item["nodes"]),
            "metrics": {name: _numeric_distribution(values) for name, values in sorted(item["numeric"].items())},
        }
        for window, item in sorted(by_window.items())
    ]
    abnormal_nodes = sorted(
        per_node,
        key=lambda item: (
            float(item.get("metrics", {}).get("rss_bytes", {}).get("max", 0) or 0),
            float(item.get("metrics", {}).get("connected_clients", {}).get("max", 0) or 0),
            item.get("missing_count", 0),
        ),
        reverse=True,
    )[:10]
    return {
        "status": report.get("status", "PASS") if report else "PASS",
        "sample_count": len(rows),
        "node_count": len(by_node),
        "windows": sorted(by_window),
        "aggregate": aggregate,
        "per_node": per_node,
        "per_window": per_window,
        "abnormal_nodes_topN": abnormal_nodes,
        "missing_metrics": missing_metrics + list(report.get("missing_metrics", []) if report else []),
        "source_refs": report.get("source_refs", {"system_metrics_timeseries": "system_metrics_timeseries.jsonl"}) if report else {"system_metrics_timeseries": "system_metrics_timeseries.jsonl"},
    }


def _numeric_distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"sample_count": 0, "status": "MISSING", "reason": "no numeric samples"}
    ordered = sorted(values)
    return {
        "sample_count": len(values),
        "min": round(ordered[0], 6),
        "max": round(ordered[-1], 6),
        "avg": round(sum(ordered) / len(ordered), 6),
        "p95": _nearest_rank(ordered, 0.95),
        "status": "PASS",
    }


def _fault_timeline_aggregates(
    report: dict[str, Any],
    events: list[dict[str, Any]],
    latency_samples: list[dict[str, Any]],
    workload_impact: dict[str, Any],
) -> dict[str, Any]:
    rows = report.get("fault_rows", []) if isinstance(report, dict) else []
    if not rows and not events:
        return {
            "status": "SKIPPED_WITH_REASON",
            "reason": "Input artifacts did not include fault_timeline_report.json or fault_timeline_events.jsonl.",
            "row_count": 0,
            "event_count": 0,
            "fault_type_coverage": {"required": M1_REQUIRED_FAULT_TYPES, "observed": [], "missing": M1_REQUIRED_FAULT_TYPES},
            "scale_coverage": {"required": M1_REQUIRED_SCALE_RUNGS, "observed": [], "missing": M1_REQUIRED_SCALE_RUNGS},
            "missing_metrics": [
                {
                    "metric": "row_count",
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "Fault timeline artifacts were not present.",
                    "impact": "Report cannot display fault timeline, failover distribution, split-brain windows, or fault-period workload impact.",
                }
            ],
        }
    row_fault_types = {str(row.get("fault_type")) for row in rows if isinstance(row, dict) and row.get("fault_type")}
    event_fault_types = {str(row.get("fault_type")) for row in events if row.get("fault_type")}
    observed_fault_types = sorted(row_fault_types | event_fault_types)
    row_scales = {str(row.get("scale_rung")) for row in rows if isinstance(row, dict) and row.get("scale_rung")}
    event_scales = {str(row.get("scale_rung")) for row in events if row.get("scale_rung")}
    observed_scales = sorted(row_scales | event_scales)
    metric_rows = [row.get("metrics", {}) for row in rows if isinstance(row, dict) and isinstance(row.get("metrics"), dict)]
    missing_metrics: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics", {})
        if not isinstance(metrics, dict):
            continue
        for name in M1_REQUIRED_TIMELINE_METRICS:
            value = metrics.get(name)
            if isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON", "BLOCKED_WITH_REASON"}:
                missing_metrics.append(
                    {
                        "sample_id": row.get("sample_id", "MISSING"),
                        "metric": name,
                        "status": value.get("status", "MISSING"),
                        "reason": value.get("reason", "fault timeline reported unavailable metric"),
                        "impact": value.get("impact", "Timeline percentile excludes this metric."),
                    }
                )
            elif name not in metrics:
                missing_metrics.append(
                    {
                        "sample_id": row.get("sample_id", "MISSING"),
                        "metric": name,
                        "status": "MISSING",
                        "reason": "metric key is absent from fault timeline row",
                        "impact": "Timeline percentile excludes this metric.",
                    }
                )
    event_names_by_sample: dict[str, set[str]] = {}
    bad_event_status_count = 0
    for event in events:
        sample_id = str(event.get("sample_id", "MISSING"))
        event_names_by_sample.setdefault(sample_id, set()).add(str(event.get("event_name", "MISSING")))
        if event.get("event_status") != "OBSERVED":
            bad_event_status_count += 1
    completeness = [
        {
            "sample_id": sample_id,
            "observed_event_count": len(names),
            "missing_events": [name for name in [
                "fault_planned",
                "fault_apply_started",
                "fault_apply_completed",
                "fault_effect_observed",
                "cluster_impact_started",
                "failover_started",
                "promotion_observed",
                "cluster_recovered",
                "workload_recovered",
                "fault_clear_started",
                "fault_clear_completed",
                "cleanup_verified",
            ] if name not in names],
        }
        for sample_id, names in sorted(event_names_by_sample.items())
    ]
    return {
        "status": report.get("status", "PASS") if isinstance(report, dict) and report else "PASS",
        "row_count": len(rows),
        "event_count": len(events),
        "latency_sample_count": len(latency_samples),
        "workload_impact_status": workload_impact.get("status", "SKIPPED_WITH_REASON") if isinstance(workload_impact, dict) else "SKIPPED_WITH_REASON",
        "fault_type_coverage": {
            "required": M1_REQUIRED_FAULT_TYPES,
            "observed": observed_fault_types,
            "missing": [name for name in M1_REQUIRED_FAULT_TYPES if name not in observed_fault_types],
        },
        "scale_coverage": {
            "required": M1_REQUIRED_SCALE_RUNGS,
            "observed": observed_scales,
            "missing": [name for name in M1_REQUIRED_SCALE_RUNGS if name not in observed_scales],
        },
        "event_completeness": completeness,
        "non_observed_event_count": bad_event_status_count,
        "failover_latency": _metric_distribution(metric_rows, "failover_latency_ms"),
        "promotion_latency": _metric_distribution(metric_rows, "promotion_latency_ms"),
        "client_unavailability": _metric_distribution(metric_rows, "client_unavailability_ms"),
        "workload_recovery": _metric_distribution(metric_rows, "workload_recovery_ms"),
        "split_brain_window": _metric_distribution(metric_rows, "split_brain_window_ms"),
        "cluster_down_window": _metric_distribution(metric_rows, "cluster_down_window_ms"),
        "cleanup_verification": {
            "pass_count": sum(1 for row in rows if isinstance(row, dict) and row.get("status") == "PASS"),
            "non_pass_count": sum(1 for row in rows if isinstance(row, dict) and row.get("status") != "PASS"),
        },
        "missing_metrics": missing_metrics + list(report.get("missing_metrics", []) if isinstance(report, dict) else []),
        "rows": rows[:50],
        "source_refs": {
            "fault_timeline_report": "fault_timeline_report.json",
            "fault_timeline_events": "fault_timeline_events.jsonl",
            "failover_latency_samples": "failover_latency_samples.jsonl",
            "fault_workload_impact": "fault_workload_impact.json",
        },
    }


def _metric_distribution(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    values = [float(row[metric]) for row in rows if isinstance(row.get(metric), (int, float)) and not isinstance(row.get(metric), bool)]
    if not values:
        return {
            "sample_count": 0,
            "p50_ms": "MISSING",
            "p95_ms": "MISSING",
            "max_ms": "MISSING",
            "status": "MISSING",
            "reason": f"{metric} had no numeric samples.",
        }
    values = sorted(values)
    return {
        "sample_count": len(values),
        "p50_ms": _nearest_rank(values, 0.50),
        "p95_ms": _nearest_rank(values, 0.95),
        "max_ms": round(max(values), 3),
        "status": "PASS",
    }


def _nearest_rank(values: list[float], percentile: float) -> float:
    index = min(len(values) - 1, max(0, round((len(values) - 1) * percentile)))
    return round(values[index], 3)


def _command_audit_aggregates(rows: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    if not rows:
        return summary or {
            "status": "SKIPPED_WITH_REASON",
            "reason": "Input artifacts did not include command_log.jsonl.",
            "total_commands": 0,
            "failure_count": 0,
            "timeout_count": 0,
            "retry_count": 0,
            "slowest_commands_topN": [],
            "failed_commands": [],
            "timeout_commands": [],
            "retry_commands": [],
            "by_command_kind": {},
            "operation_traceability": [],
            "missing_or_skipped": [
                {
                    "metric": "command_log.total_commands",
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "Input artifacts did not include command_log.jsonl.",
                    "impact": "Report cannot display command-level traceability.",
                }
            ],
        }
    by_kind: dict[str, int] = {}
    for row in rows:
        by_kind[str(row.get("command_kind", "MISSING"))] = by_kind.get(str(row.get("command_kind", "MISSING")), 0) + 1
    failures = [row for row in rows if row.get("status") == "FAIL"]
    timeouts = [row for row in rows if row.get("status") == "TIMEOUT"]
    retries = [row for row in rows if int(row.get("retry_index", 0) or 0) > 0 or row.get("status") == "RETRY"]
    operation_map: dict[str, list[str]] = {}
    for row in rows:
        operation_map.setdefault(str(row.get("operation_id", "MISSING")), []).append(str(row.get("command_id", "MISSING")))
    aggregate = {
        "status": summary.get("status", "PASS") if summary else "PASS",
        "command_log_ref": summary.get("command_log_ref", "command_log.jsonl") if summary else "command_log.jsonl",
        "total_commands": len(rows),
        "pass_count": sum(1 for row in rows if row.get("status") == "PASS"),
        "failure_count": len(failures),
        "timeout_count": len(timeouts),
        "retry_count": len(retries),
        "by_command_kind": by_kind,
        "slowest_commands_topN": [_command_summary_row(row) for row in sorted(rows, key=lambda row: float(row.get("duration_ms", 0) or 0), reverse=True)[:10]],
        "failed_commands": [_command_summary_row(row) for row in failures],
        "timeout_commands": [_command_summary_row(row) for row in timeouts],
        "retry_commands": [_command_summary_row(row) for row in retries],
        "operation_traceability": [
            {"operation_id": operation_id, "command_log_refs": [f"command_log.jsonl#{command_id}" for command_id in command_ids], "status": "PASS"}
            for operation_id, command_ids in sorted(operation_map.items())
        ],
        "missing_or_skipped": [],
    }
    if summary:
        aggregate["summary_artifact"] = summary
    return aggregate


def _command_summary_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "command_id": row.get("command_id", "MISSING"),
        "operation_id": row.get("operation_id", "MISSING"),
        "step_id": row.get("step_id", "MISSING"),
        "command_kind": row.get("command_kind", "MISSING"),
        "duration_ms": row.get("duration_ms", "MISSING"),
        "status": row.get("status", "MISSING"),
        "exit_code": row.get("exit_code", "MISSING"),
        "retry_index": row.get("retry_index", 0),
        "error_type": row.get("error_type", ""),
    }


def _setup_aggregates(setup_telemetry: dict[str, Any]) -> dict[str, Any]:
    if not setup_telemetry:
        return {
            "status": "SKIPPED_WITH_REASON",
            "reason": "setup_telemetry.json was not present in the input artifacts.",
        }
    metrics = setup_telemetry.get("metrics", {})
    numeric = [
        {"metric": name, "value_ms": round(float(value), 3)}
        for name, value in metrics.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ] if isinstance(metrics, dict) else []
    phase_duration_ranking = sorted(numeric, key=lambda item: item["value_ms"], reverse=True)
    return {
        "status": setup_telemetry.get("status", "MISSING"),
        "node_count": setup_telemetry.get("node_count", "MISSING"),
        "phase_duration_ranking": phase_duration_ranking,
        "slowest_nodes_topN": setup_telemetry.get("slowest_nodes_topN", []),
        "slowest_replica_replicate_topN": setup_telemetry.get("slowest_replica_replicate_topN", []),
        "cleanup": setup_telemetry.get("cleanup", {}),
        "same_schema_scale_rungs": setup_telemetry.get("same_schema_scale_rungs", []),
    }


def _management_aggregates(
    matrix: dict[str, Any],
    results: list[dict[str, Any]],
    diffs: list[dict[str, Any]],
    workload: dict[str, Any],
) -> dict[str, Any]:
    if not matrix and not results:
        return {
            "status": "SKIPPED_WITH_REASON",
            "reason": "Input artifacts did not include management_ops_matrix.json or management_operation_results.jsonl.",
            "operation_count": 0,
            "required_operations_observed": [],
            "missing_required_operations": REQUIRED_MANAGEMENT_OPERATIONS,
            "missing_metrics": [
                {
                    "metric": "operation_count",
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "Management operation artifacts were not present.",
                    "impact": "Report cannot display management operation timing or topology diff data.",
                }
            ],
        }
    observed = [str(row.get("operation_name", "MISSING")) for row in results if isinstance(row, dict)]
    missing_required = [name for name in REQUIRED_MANAGEMENT_OPERATIONS if name not in observed]
    duration_rows = [
        {
            "operation_name": row.get("operation_name", "MISSING"),
            "operation_id": row.get("operation_id", "MISSING"),
            "operation_status": row.get("operation_status", "MISSING"),
            "operation_duration_ms": row.get("operation_duration_ms", row.get("wall_ms", "MISSING")),
            "convergence_ms": row.get("convergence_ms", "MISSING"),
            "command_count": row.get("command_count", 0),
            "retry_count": row.get("retry_count", 0),
            "error_count": row.get("error_count", 0),
            "topology_diff_ref": row.get("topology_diff_ref", "MISSING"),
            "workload_impact_ref": row.get("workload_impact_ref", "MISSING"),
            "cleanup_ref": row.get("cleanup_ref", "MISSING"),
        }
        for row in results
        if isinstance(row, dict)
    ]
    duration_ranking = sorted(
        duration_rows,
        key=lambda row: float(row.get("operation_duration_ms", 0) or 0) if isinstance(row.get("operation_duration_ms"), (int, float)) else 0.0,
        reverse=True,
    )
    topology_summary = [
        {
            "operation_id": row.get("operation_id", "MISSING"),
            "known_nodes_delta": row.get("known_nodes_delta", "MISSING"),
            "moved_slot_range_count": row.get("slot_diff", {}).get("moved_slot_range_count", "MISSING") if isinstance(row.get("slot_diff"), dict) else "MISSING",
            "role_diff": row.get("role_diff", {}),
            "status": row.get("status", "MISSING"),
        }
        for row in diffs
        if isinstance(row, dict)
    ]
    missing_metrics: list[dict[str, Any]] = []
    if missing_required:
        missing_metrics.append(
            {
                "metric": "required_operations",
                "status": "MISSING",
                "reason": f"Missing required management operations: {', '.join(missing_required)}",
                "impact": "Milestone1 management matrix coverage is incomplete.",
            }
        )
    for row in results:
        for item in row.get("missing_fields", []):
            if isinstance(item, dict):
                missing_metrics.append(
                    {
                        "metric": f"{row.get('operation_name', 'MISSING')}.{item.get('field', 'missing_field')}",
                        "status": item.get("status", "MISSING"),
                        "reason": item.get("reason", "operation result reported missing field"),
                        "impact": item.get("impact", "Management operation result is incomplete."),
                    }
                )
    return {
        "status": "PASS" if not missing_required and all(row.get("operation_status") == "PASS" for row in results) else "FAIL",
        "operation_count": len(results),
        "required_operations_observed": observed,
        "missing_required_operations": missing_required,
        "duration_ranking_topN": duration_ranking[:10],
        "slow_operations_topN": duration_ranking[:5],
        "error_operations": [row for row in duration_rows if int(row.get("error_count", 0) or 0) > 0 or row.get("operation_status") == "FAIL"],
        "retry_operations": [row for row in duration_rows if int(row.get("retry_count", 0) or 0) > 0],
        "command_traceability": [
            {
                "operation_id": row.get("operation_id", "MISSING"),
                "operation_name": row.get("operation_name", "MISSING"),
                "command_count": row.get("command_count", 0),
                "command_log_refs": row.get("command_log_refs", []),
            }
            for row in results
        ],
        "topology_diff_summary": topology_summary,
        "reshard_rebalance_summary": [
            row for row in results if row.get("operation_name") in {"reshard_slot_range", "reshard_with_keys", "rebalance_after_imbalance"}
        ],
        "rolling_restart_summary": [
            row for row in results if row.get("operation_name") in {"rolling_restart_replica_first", "rolling_restart_primary_safe"}
        ],
        "workload_impact_status": workload.get("status", "MISSING") if isinstance(workload, dict) else "MISSING",
        "matrix": matrix,
        "missing_metrics": missing_metrics,
    }


def _workload_aggregates(windows_artifact: dict[str, Any], report: dict[str, Any], impact: dict[str, Any]) -> dict[str, Any]:
    windows = windows_artifact.get("windows", []) if isinstance(windows_artifact, dict) else []
    if not windows and not report:
        return {
            "status": "SKIPPED_WITH_REASON",
            "reason": "Input artifacts did not include workload_windows.json or workload_report.json.",
            "window_count": 0,
            "profiles_covered": [],
            "missing_metrics": [
                {
                    "metric": "window_count",
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "Workload benchmark artifacts were not present.",
                    "impact": "Report cannot display workload QPS, latency, error-rate, or slot coverage.",
                }
            ],
        }
    metrics = [row.get("metrics", {}) for row in windows if isinstance(row, dict)]
    ok_ops = sum(int(item.get("ok_ops", 0) or 0) for item in metrics if isinstance(item, dict))
    error_ops = sum(int(item.get("error_ops", 0) or 0) for item in metrics if isinstance(item, dict))
    requested = [float(item.get("requested_qps")) for item in metrics if isinstance(item, dict) and isinstance(item.get("requested_qps"), (int, float))]
    achieved = [float(item.get("achieved_qps")) for item in metrics if isinstance(item, dict) and isinstance(item.get("achieved_qps"), (int, float))]
    p99s = [float(item.get("latency_p99_ms")) for item in metrics if isinstance(item, dict) and isinstance(item.get("latency_p99_ms"), (int, float))]
    errors = [float(item.get("error_rate")) for item in metrics if isinstance(item, dict) and isinstance(item.get("error_rate"), (int, float))]
    profiles = sorted({str(row.get("profile")) for row in windows if isinstance(row, dict) and row.get("profile")})
    hash_slot_coverage = windows_artifact.get("hash_slot_coverage", {}) if isinstance(windows_artifact, dict) else {}
    full_slot_covered = any(isinstance(item, dict) and item.get("full_slot_covered") is True for item in hash_slot_coverage.values()) if isinstance(hash_slot_coverage, dict) else False
    missing_metrics: list[dict[str, Any]] = []
    for row in windows:
        if not isinstance(row, dict):
            continue
        row_metrics = row.get("metrics", {})
        if not isinstance(row_metrics, dict):
            continue
        for name, value in row_metrics.items():
            if value == "MISSING":
                missing_metrics.append(
                    {
                        "metric": f"{row.get('profile', 'unknown')}.{row.get('window_name', 'unknown')}.{name}",
                        "status": "MISSING",
                        "reason": row_metrics.get("missing_reasons", {}).get(name, "workload metric was MISSING without a source value"),
                        "impact": "Benchmark comparison may omit this metric.",
                    }
                )
    aggregate = {
        "requested_qps": round(sum(requested), 6) if requested else "MISSING",
        "achieved_qps": round(sum(achieved), 6) if achieved else "MISSING",
        "throughput_ratio": round(sum(achieved) / sum(requested), 6) if achieved and requested and sum(requested) else "MISSING",
        "ok_ops": ok_ops,
        "error_ops": error_ops,
        "error_rate": round(sum(errors) / len(errors), 6) if errors else "MISSING",
        "latency_p99_ms": round(sum(p99s) / len(p99s), 6) if p99s else "MISSING",
    }
    return {
        "status": windows_artifact.get("status", report.get("status", "PASS") if isinstance(report, dict) else "PASS"),
        "window_count": len(windows),
        "profiles_covered": profiles or (report.get("profiles", []) if isinstance(report, dict) else []),
        "workload_mode": windows_artifact.get("workload_mode", report.get("workload_mode", "MISSING") if isinstance(report, dict) else "MISSING"),
        "hash_slot_coverage": hash_slot_coverage or (report.get("hash_slot_coverage", {}) if isinstance(report, dict) else {}),
        "full_slot_covered": full_slot_covered,
        "aggregate": aggregate,
        "windows": [
            {
                "profile": row.get("profile", "MISSING"),
                "window_name": row.get("window_name", "MISSING"),
                "status": row.get("status", "MISSING"),
                "requested_qps": row.get("metrics", {}).get("requested_qps", "MISSING") if isinstance(row.get("metrics"), dict) else "MISSING",
                "achieved_qps": row.get("metrics", {}).get("achieved_qps", "MISSING") if isinstance(row.get("metrics"), dict) else "MISSING",
                "throughput_ratio": row.get("metrics", {}).get("throughput_ratio", "MISSING") if isinstance(row.get("metrics"), dict) else "MISSING",
                "latency_p99_ms": row.get("metrics", {}).get("latency_p99_ms", "MISSING") if isinstance(row.get("metrics"), dict) else "MISSING",
                "error_rate": row.get("metrics", {}).get("error_rate", "MISSING") if isinstance(row.get("metrics"), dict) else "MISSING",
                "key_slot_coverage": row.get("key_slot_coverage", {}),
            }
            for row in windows
            if isinstance(row, dict)
        ],
        "impact_status": impact.get("status", "MISSING") if isinstance(impact, dict) else "MISSING",
        "missing_metrics": missing_metrics,
    }


def _metric(name: str, value: Any, unit: str) -> dict[str, Any]:
    if value == "MISSING":
        return {"name": name, "status": "MISSING", "value": None, "unit": unit, "reason": "source artifact did not provide metric"}
    return {"name": name, "status": "PASS", "value": value, "unit": unit}


def _metric_from_optional(name: str, value: Any, unit: str) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON"}:
        return {
            "name": name,
            "status": value["status"],
            "value": value.get("value"),
            "unit": unit,
            "reason": value.get("reason", "source artifact reported metric unavailable"),
        }
    if isinstance(value, dict):
        return {"name": name, "status": "PASS", "value": value.get("value"), "unit": unit}
    return _metric(name, value if value is not None else "MISSING", unit)


def _metadata_value(metadata: dict[str, Any], key: str, fallback: str) -> str:
    value = metadata.get(key)
    if isinstance(value, str) and value:
        return value
    return fallback


def _baseline_comparison(metrics: list[dict[str, Any]], source_dir: Path, *, run_id: str = RUN_ID, created_at: str = CREATED_AT) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": "baseline_comparison",
        "phase_id": PHASE_ID,
        "run_id": run_id,
        "created_at": created_at,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "NO_BASELINE_YET",
        "baseline_source": {
            "status": "SKIPPED_WITH_REASON",
            "reason": "No versioned baseline artifact exists for the first analysis-reporting phase.",
        },
        "source_dir": source_dir.as_posix(),
        "comparisons": [
            {
                "metric": metric["name"],
                "current_value": metric.get("value"),
                "unit": metric.get("unit"),
                "status": "NO_BASELINE_YET" if metric.get("status") == "PASS" else metric.get("status"),
                "baseline_value": None,
                "delta": None,
            }
            for metric in metrics
        ],
    }


def _artifact_record(path: Path) -> dict[str, str]:
    return {"path": _rel(path), "sha256": _sha256_file(path)}


def _source_artifact_paths(source_dir: Path, out: Path, baseline_path: Path) -> list[Path]:
    excluded = {out.resolve(), baseline_path.resolve()}
    return [path for path in sorted(list(source_dir.glob("*.json")) + list(source_dir.glob("*.jsonl"))) if path.resolve() not in excluded]


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
