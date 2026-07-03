#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from schema_validator import load_json as load_schema_json, validate  # noqa: E402
from strict_harness_lib import load_jsonl, phase_dir, print_errors, rel, require_file, require_json  # noqa: E402


P29 = "P29_QUANT_TELEMETRY_COLLECTOR_HARDENING"
CANONICAL_WINDOWS = ["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]
STRICT_EVENT_FIELDS = [
    "schema_version",
    "run_id",
    "phase_id",
    "stage_id",
    "coverage_id",
    "scale",
    "node_count",
    "scenario_name",
    "sample_id",
    "event_id",
    "event_type",
    "timestamp_unix_ms",
    "monotonic_ms",
    "severity",
    "subject_type",
    "subject_id",
    "operation_id",
    "fault_id",
    "message",
    "metadata",
]
STRICT_METRIC_FIELDS = [
    "schema_version",
    "run_id",
    "phase_id",
    "stage_id",
    "coverage_id",
    "scale",
    "node_count",
    "scenario_name",
    "sample_id",
    "timestamp_unix_ms",
    "monotonic_ms",
    "source_type",
    "source_id",
    "metric_name",
    "metric_value",
    "metric_unit",
    "labels",
    "missing_reason",
]
WORKLOAD_METRICS = [
    "requested_qps",
    "achieved_qps",
    "ok_ops",
    "error_ops",
    "error_rate",
    "latency_p50_ms",
    "latency_p90_ms",
    "latency_p95_ms",
    "latency_p99_ms",
    "latency_p999_ms",
    "timeout_count",
    "connection_error_count",
    "moved_redirection_count",
    "ask_redirection_count",
    "cluster_down_error_count",
    "readonly_error_count",
    "tryagain_error_count",
    "unknown_error_count",
    "sample_count",
    "window_start_event_id",
    "window_end_event_id",
]
FORBIDDEN_STRINGS = {"nan", "infinity", "-infinity", "undefined", "null"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--category")
    parser.add_argument("--scale")
    args = parser.parse_args()
    base = phase_dir(args.phase)
    errors: list[str] = []
    summary = require_json(base / "quant_summary.json", errors, "quant summary")
    require_file(base / "events.jsonl", errors, "events")
    require_file(base / "metrics_timeseries.jsonl", errors, "metrics timeseries")
    require_json(base / "workload_windows.json", errors, "workload windows")
    if summary:
        claims = summary.get("runtime_claims", {})
        if args.category in {"management", "fault", "full_flow"} and claims.get("real_valkey_claimed") is not True:
            errors.append(f"{rel(base / 'quant_summary.json')}: real_valkey_claimed must be true for {args.category}")
        if args.category == "management" and claims.get("management_runtime_claimed") is not True:
            errors.append("management_runtime_claimed must be true")
        if args.category == "fault" and claims.get("fault_runtime_claimed") is not True:
            errors.append("fault_runtime_claimed must be true")
    if args.phase == P29:
        assert_p29_semantics(base, errors)
    if errors:
        return print_errors(errors)
    print(f"PASS quant completeness phase={args.phase}")
    return 0


def assert_p29_semantics(base: Path, errors: list[str]) -> None:
    phase = P29
    event_schema = load_schema_json(ROOT / "schemas" / "artifact" / "goal_loop_event.schema.json")
    metric_schema = load_schema_json(ROOT / "schemas" / "artifact" / "goal_loop_metric_sample.schema.json")
    events = _load_jsonl_required(base / "events.jsonl", errors)
    metrics = _load_jsonl_required(base / "metrics_timeseries.jsonl", errors)
    workload = require_json(base / "workload_windows.json", errors, "workload windows") or {}
    quant_summary = require_json(base / "quant_summary.json", errors, "quant summary") or {}
    telemetry_report = require_json(base / "telemetry_completeness_report.json", errors, "telemetry completeness report") or {}
    coverage_ledger = require_json(base / "coverage_ledger.json", errors, "coverage ledger") or {}
    evidence = require_json(base / "valkey_e2e_evidence.json", errors, "real Valkey evidence") or {}
    cleanup = require_json(base / "cleanup_report.json", errors, "cleanup report") or {}

    event_ids: set[str] = set()
    for index, row in enumerate(events, start=1):
        _validate_schema_row(row, event_schema, f"events.jsonl:{index}", errors)
        _assert_required_fields(row, STRICT_EVENT_FIELDS, f"events.jsonl:{index}", errors)
        _assert_strict_dimensions(row, phase, f"events.jsonl:{index}", errors)
        _assert_no_forbidden_values(row, f"events.jsonl:{index}", errors)
        event_id = str(row.get("event_id", ""))
        if not event_id:
            errors.append(f"events.jsonl:{index}: event_id must be non-empty")
        event_ids.add(event_id)

    metric_source_types = set()
    missing_metric_count = 0
    for index, row in enumerate(metrics, start=1):
        _validate_schema_row(row, metric_schema, f"metrics_timeseries.jsonl:{index}", errors)
        _assert_required_fields(row, STRICT_METRIC_FIELDS, f"metrics_timeseries.jsonl:{index}", errors)
        _assert_strict_dimensions(row, phase, f"metrics_timeseries.jsonl:{index}", errors)
        _assert_no_forbidden_values(row, f"metrics_timeseries.jsonl:{index}", errors)
        metric_source_types.add(str(row.get("source_type")))
        if row.get("metric_value") == "MISSING":
            missing_metric_count += 1
            if not row.get("missing_reason"):
                errors.append(f"metrics_timeseries.jsonl:{index}: MISSING metric requires missing_reason")
        elif row.get("missing_reason") not in {"", "SKIPPED_WITH_REASON"} and not isinstance(row.get("missing_reason"), str):
            errors.append(f"metrics_timeseries.jsonl:{index}: missing_reason must be a string")

    for source_type in ["valkey_info", "cluster_info", "cluster_nodes", "docker_stats", "workload"]:
        if source_type not in metric_source_types:
            errors.append(f"metrics_timeseries.jsonl: missing required source_type {source_type}")

    _assert_workload_windows(workload, event_ids, errors)
    _assert_quant_summary(quant_summary, len(events), len(metrics), missing_metric_count, errors)
    _assert_telemetry_report(telemetry_report, errors)
    _assert_coverage_ledger(coverage_ledger, errors)
    if evidence.get("status") != "PASS" or evidence.get("real_valkey") is not True:
        errors.append("valkey_e2e_evidence.json: P29 requires PASS real_valkey evidence")
    nodes_observed = evidence.get("nodes_observed")
    if not isinstance(nodes_observed, int) or nodes_observed < 6 or nodes_observed > 6:
        errors.append("valkey_e2e_evidence.json: P29 requires exactly 6 observed nodes")
    if cleanup.get("status") != "PASS":
        errors.append("cleanup_report.json: cleanup status must be PASS")


def _load_jsonl_required(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    try:
        rows = load_jsonl(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{rel(path)}: {exc}")
        return []
    objects: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            errors.append(f"{rel(path)}:{index}: expected object row")
            continue
        objects.append(row)
    return objects


def _validate_schema_row(row: dict[str, Any], schema: dict[str, Any], label: str, errors: list[str]) -> None:
    for error in validate(row, schema, "$"):
        errors.append(f"{label}: {error}")


def _assert_required_fields(row: dict[str, Any], fields: list[str], label: str, errors: list[str]) -> None:
    for field in fields:
        if field not in row:
            errors.append(f"{label}: missing required strict field {field}")
        elif field != "missing_reason" and row[field] == "":
            errors.append(f"{label}: strict field {field} must not be empty")


def _assert_strict_dimensions(row: dict[str, Any], phase: str, label: str, errors: list[str]) -> None:
    if row.get("phase_id") != phase:
        errors.append(f"{label}: phase_id must be {phase}")
    if row.get("stage_id") != phase:
        errors.append(f"{label}: stage_id must be {phase}")
    if row.get("coverage_id") != "p29.telemetry.strict_telemetry_small_real":
        errors.append(f"{label}: coverage_id must be p29.telemetry.strict_telemetry_small_real")
    if row.get("scale") != 6:
        errors.append(f"{label}: scale must be 6")
    if row.get("node_count") != 6:
        errors.append(f"{label}: node_count must be 6")


def _assert_no_forbidden_values(value: Any, label: str, errors: list[str]) -> None:
    if value is None:
        errors.append(f"{label}: null is forbidden")
    elif isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{label}: NaN/Infinity is forbidden")
    elif isinstance(value, str) and value.lower() in FORBIDDEN_STRINGS:
        errors.append(f"{label}: forbidden placeholder string {value!r}")
    elif isinstance(value, dict):
        for key, item in value.items():
            _assert_no_forbidden_values(item, f"{label}.{key}", errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_forbidden_values(item, f"{label}[{index}]", errors)


def _assert_workload_windows(workload: dict[str, Any], event_ids: set[str], errors: list[str]) -> None:
    windows = workload.get("windows")
    if not isinstance(windows, list):
        errors.append("workload_windows.json: windows must be a list")
        return
    names = [window.get("window_name") for window in windows if isinstance(window, dict)]
    if names != CANONICAL_WINDOWS:
        errors.append(f"workload_windows.json: windows must be canonical order {CANONICAL_WINDOWS}, got {names}")
    for window in windows:
        if not isinstance(window, dict):
            errors.append("workload_windows.json: each window must be an object")
            continue
        name = window.get("window_name", "MISSING")
        metrics = window.get("metrics")
        if not isinstance(metrics, dict):
            errors.append(f"workload_windows.json:{name}: metrics must be an object")
            continue
        for field in WORKLOAD_METRICS:
            if field not in metrics:
                errors.append(f"workload_windows.json:{name}: missing metric {field}")
            elif metrics[field] == "MISSING":
                reason = metrics.get("missing_reasons", {}).get(field)
                if not reason:
                    errors.append(f"workload_windows.json:{name}: MISSING metric {field} requires reason")
        start_id = metrics.get("window_start_event_id")
        end_id = metrics.get("window_end_event_id")
        if start_id != window.get("start_event_id") or start_id != window.get("window_start_event_id"):
            errors.append(f"workload_windows.json:{name}: start event IDs must agree")
        if end_id != window.get("end_event_id") or end_id != window.get("window_end_event_id"):
            errors.append(f"workload_windows.json:{name}: end event IDs must agree")
        if start_id not in event_ids:
            errors.append(f"workload_windows.json:{name}: window_start_event_id does not link to events.jsonl")
        if end_id not in event_ids:
            errors.append(f"workload_windows.json:{name}: window_end_event_id does not link to events.jsonl")
        if not isinstance(metrics.get("sample_count"), int) or metrics.get("sample_count", 0) <= 0:
            errors.append(f"workload_windows.json:{name}: sample_count must be observed and positive")
        for percentile in ["latency_p50_ms", "latency_p90_ms", "latency_p95_ms", "latency_p99_ms", "latency_p999_ms"]:
            value = metrics.get(percentile)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(f"workload_windows.json:{name}: {percentile} must be numeric when samples exist")


def _assert_quant_summary(summary: dict[str, Any], event_count: int, metric_count: int, missing_metric_count: int, errors: list[str]) -> None:
    claims = summary.get("runtime_claims", {})
    if claims.get("real_valkey_claimed") is not True:
        errors.append("quant_summary.json: real_valkey_claimed must be true")
    if claims.get("management_runtime_claimed") is not False:
        errors.append("quant_summary.json: management_runtime_claimed must be false for P29")
    if claims.get("fault_runtime_claimed") is not False:
        errors.append("quant_summary.json: fault_runtime_claimed must be false for P29")
    counts = summary.get("counts", {})
    if counts.get("event_count") != event_count:
        errors.append("quant_summary.json: event_count does not match events.jsonl")
    if counts.get("metric_count") != metric_count:
        errors.append("quant_summary.json: metric_count does not match metrics_timeseries.jsonl")
    if counts.get("node_count") != 6:
        errors.append("quant_summary.json: node_count must be 6")
    if counts.get("coverage_pass_count") != 0:
        errors.append("quant_summary.json: coverage_pass_count must be 0 for P29")
    if missing_metric_count and not summary.get("missing_data"):
        errors.append("quant_summary.json: missing metric rows require missing_data explanation")


def _assert_telemetry_report(report: dict[str, Any], errors: list[str]) -> None:
    if report.get("status") != "PASS":
        errors.append("telemetry_completeness_report.json: status must be PASS")
    if report.get("node_count") != 6 or report.get("scale") != 6:
        errors.append("telemetry_completeness_report.json: node_count and scale must be 6")
    for source_type in ["valkey_info", "cluster_info", "cluster_nodes", "docker_stats", "workload"]:
        coverage = report.get("source_type_coverage", {}).get(source_type)
        if not isinstance(coverage, dict) or coverage.get("status") != "PASS" or int(coverage.get("row_count", 0)) <= 0:
            errors.append(f"telemetry_completeness_report.json: source coverage for {source_type} must be PASS with rows")
    for validation in report.get("schema_validations", []):
        if validation.get("status") != "PASS":
            errors.append("telemetry_completeness_report.json: schema validations must be PASS")
    source_artifacts = report.get("provenance", {}).get("source_artifacts", [])
    if not isinstance(source_artifacts, list) or not source_artifacts:
        errors.append("telemetry_completeness_report.json: provenance.source_artifacts required")
    for artifact in source_artifacts:
        if not isinstance(artifact, dict) or artifact.get("status") != "PASS":
            errors.append("telemetry_completeness_report.json: all source artifacts must have PASS provenance")
            continue
        digest = artifact.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            errors.append("telemetry_completeness_report.json: source artifact sha256 hashes are required")
    provenance = report.get("provenance", {})
    if provenance.get("large_scale_coverage_claim") is not False:
        errors.append("telemetry_completeness_report.json: large_scale_coverage_claim must be false")
    if provenance.get("matrix_rows_remain_pending") is not True:
        errors.append("telemetry_completeness_report.json: matrix_rows_remain_pending must be true")
    if report.get("blocking_findings") not in ([], None):
        errors.append("telemetry_completeness_report.json: blocking_findings must be empty for PASS")


def _assert_coverage_ledger(ledger: dict[str, Any], errors: list[str]) -> None:
    if ledger.get("stage_id") != P29:
        errors.append("coverage_ledger.json: stage_id must be P29")
    summary = ledger.get("summary", {})
    if summary.get("real_runtime_claimed") is not False:
        errors.append("coverage_ledger.json: real_runtime_claimed must remain false")
    for row in ledger.get("rows", []):
        if row.get("status") != "PENDING":
            errors.append(f"coverage_ledger.json: {row.get('coverage_id')} must remain PENDING in P29")
        if row.get("node_count") not in {50, 100, 200, 201, 250, 300, 500, 1000}:
            errors.append("coverage_ledger.json: P29 must not add 6-node matrix coverage rows")


if __name__ == "__main__":
    raise SystemExit(main())
