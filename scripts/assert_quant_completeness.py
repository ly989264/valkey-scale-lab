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
P30 = "P30_MANAGEMENT_MATRIX_50_REAL"
P31 = "P31_MANAGEMENT_MATRIX_100_REAL"
P32 = "P32_MANAGEMENT_MATRIX_200_REAL"
P33 = "P33_FAULT_FAILOVER_MATRIX_50_REAL"
STRICT_MANAGEMENT_STAGES = {
    P30: {
        "scale": 50,
        "coverage_prefix": "50.management.",
        "timing_artifact": "runtime_timing_breakdown_strict_management_matrix_50.json",
    },
    P31: {
        "scale": 100,
        "coverage_prefix": "100.management.",
        "timing_artifact": "runtime_timing_breakdown_strict_management_matrix_100.json",
    },
    P32: {
        "scale": 200,
        "coverage_prefix": "200.management.",
        "timing_artifact": "runtime_timing_breakdown_strict_management_matrix_200.json",
    },
}
STRICT_FAULT_STAGES = {
    P33: {
        "scale": 50,
        "coverage_prefix": "50.fault.",
        "required_rows": {
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
            "split_brain_window_detection",
            "fault_period_workload_impact",
        },
        "min_failover_samples": 3,
    },
}
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
    if args.phase in STRICT_MANAGEMENT_STAGES and args.category == "management":
        assert_p30_management_semantics(base, args.phase, int(args.scale or 0), errors)
    if args.phase in STRICT_FAULT_STAGES and args.category == "fault":
        assert_strict_fault_semantics(base, args.phase, int(args.scale or 0), errors)
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


def assert_p30_management_semantics(base: Path, phase: str, scale: int, errors: list[str]) -> None:
    spec = STRICT_MANAGEMENT_STAGES[phase]
    expected_scale = int(spec["scale"])
    coverage_prefix = str(spec["coverage_prefix"])
    if scale != expected_scale:
        errors.append(f"{phase} quant completeness requires --scale {expected_scale}")
    events = _load_jsonl_required(base / "events.jsonl", errors)
    metrics = _load_jsonl_required(base / "metrics_timeseries.jsonl", errors)
    workload = require_json(base / "workload_windows.json", errors, "workload windows") or {}
    quant_summary = require_json(base / "quant_summary.json", errors, "quant summary") or {}
    coverage_ledger = require_json(base / "coverage_ledger.json", errors, "coverage ledger") or {}
    evidence = require_json(base / "valkey_e2e_evidence.json", errors, "real Valkey evidence") or {}
    cleanup = require_json(base / "cleanup_report.json", errors, "cleanup report") or {}
    for artifact_name in [
        "phase_summary.json",
        "resource_preflight.json",
        "cluster_plan.json",
        "run_state.json",
        "management_ops_matrix.json",
        "management_workload_impact.json",
        "rebalance_summary.json",
        "rolling_restart_plan.json",
        str(spec["timing_artifact"]),
    ]:
        artifact = require_json(base / artifact_name, errors, artifact_name) or {}
        _assert_no_forbidden_values(artifact, artifact_name, errors)
    for index, row in enumerate(events, start=1):
        _assert_required_fields(row, STRICT_EVENT_FIELDS, f"events.jsonl:{index}", errors)
        _assert_p30_dimensions(row, phase, expected_scale, coverage_prefix, f"events.jsonl:{index}", errors)
        _assert_no_forbidden_values(row, f"events.jsonl:{index}", errors)
    metric_source_types = set()
    for index, row in enumerate(metrics, start=1):
        _assert_required_fields(row, STRICT_METRIC_FIELDS, f"metrics_timeseries.jsonl:{index}", errors)
        _assert_p30_dimensions(row, phase, expected_scale, coverage_prefix, f"metrics_timeseries.jsonl:{index}", errors)
        _assert_no_forbidden_values(row, f"metrics_timeseries.jsonl:{index}", errors)
        metric_source_types.add(str(row.get("source_type")))
        if row.get("metric_value") == "MISSING" and not row.get("missing_reason"):
            errors.append(f"metrics_timeseries.jsonl:{index}: MISSING metric requires missing_reason")
    if "workload" not in metric_source_types:
        errors.append(f"metrics_timeseries.jsonl: {phase} requires workload metric rows")
    _assert_p30_workload_windows(workload, {str(row.get("event_id")) for row in events}, errors)
    claims = quant_summary.get("runtime_claims", {})
    if claims.get("real_valkey_claimed") is not True or claims.get("management_runtime_claimed") is not True:
        errors.append(f"quant_summary.json: {phase} requires real Valkey and management runtime claims")
    counts = quant_summary.get("counts", {})
    if counts.get("node_count") != expected_scale or counts.get("operation_count") != 11 or counts.get("coverage_pass_count") != 11:
        errors.append(f"quant_summary.json: {phase} counts must record {expected_scale} nodes, 11 operations, and 11 coverage passes")
    if evidence.get("status") != "PASS" or evidence.get("nodes_observed") != expected_scale or evidence.get("data_path_result") != "PASS":
        errors.append(f"valkey_e2e_evidence.json: {phase} requires PASS exact-{expected_scale} data-path evidence")
    if cleanup.get("status") != "PASS":
        errors.append("cleanup_report.json: cleanup status must be PASS")
    stage_rows = [
        row
        for row in coverage_ledger.get("rows", [])
        if isinstance(row, dict)
        and row.get("stage_owner") == phase
        and str(row.get("coverage_id", "")).startswith(coverage_prefix)
        and row.get("category") == "management"
    ]
    if coverage_ledger.get("stage_id") != phase or len(stage_rows) != 11 or any(row.get("status") != "PASS" for row in stage_rows):
        errors.append(f"coverage_ledger.json: {phase} ledger must contain exactly 11 PASS {coverage_prefix} rows")


def assert_strict_fault_semantics(base: Path, phase: str, scale: int, errors: list[str]) -> None:
    spec = STRICT_FAULT_STAGES[phase]
    expected_scale = int(spec["scale"])
    coverage_prefix = str(spec["coverage_prefix"])
    required_rows = set(spec["required_rows"])
    min_failover_samples = int(spec["min_failover_samples"])
    if scale != expected_scale:
        errors.append(f"{phase} quant completeness requires --scale {expected_scale}")
    events = _load_jsonl_required(base / "events.jsonl", errors)
    metrics = _load_jsonl_required(base / "metrics_timeseries.jsonl", errors)
    fault_results = _load_jsonl_required(base / "fault_operation_results.jsonl", errors)
    failover_samples = _load_jsonl_required(base / "failover_samples.jsonl", errors)
    topology = _load_jsonl_required(base / "fault_topology_snapshots.jsonl", errors)
    command_log = _load_jsonl_required(base / "fault_command_log.jsonl", errors)
    workload = require_json(base / "workload_windows.json", errors, "workload windows") or {}
    quant_summary = require_json(base / "quant_summary.json", errors, "quant summary") or {}
    coverage_ledger = require_json(base / "coverage_ledger.json", errors, "coverage ledger") or {}
    evidence = require_json(base / "valkey_e2e_evidence.json", errors, "real Valkey evidence") or {}
    cleanup = require_json(base / "cleanup_report.json", errors, "cleanup report") or {}
    required_json = {
        "phase_summary.json": require_json(base / "phase_summary.json", errors, "phase summary") or {},
        "resource_preflight.json": require_json(base / "resource_preflight.json", errors, "resource preflight") or {},
        "cluster_plan.json": require_json(base / "cluster_plan.json", errors, "cluster plan") or {},
        "run_state.json": require_json(base / "run_state.json", errors, "run state") or {},
        "fault_matrix_report.json": require_json(base / "fault_matrix_report.json", errors, "fault matrix report") or {},
        "failover_latency_curve.json": require_json(base / "failover_latency_curve.json", errors, "failover latency curve") or {},
        "partition_report.json": require_json(base / "partition_report.json", errors, "partition report") or {},
        "split_brain_report.json": require_json(base / "split_brain_report.json", errors, "split brain report") or {},
        "fault_workload_impact.json": require_json(base / "fault_workload_impact.json", errors, "fault workload impact") or {},
    }
    for artifact_name, artifact in required_json.items():
        _assert_no_forbidden_values(artifact, artifact_name, errors)

    event_ids: set[str] = set()
    for index, row in enumerate(events, start=1):
        _assert_required_fields(row, STRICT_EVENT_FIELDS, f"events.jsonl:{index}", errors)
        _assert_strict_fault_dimensions(row, phase, expected_scale, coverage_prefix, f"events.jsonl:{index}", errors)
        _assert_no_forbidden_values(row, f"events.jsonl:{index}", errors)
        event_ids.add(str(row.get("event_id", "")))

    metric_source_types = set()
    for index, row in enumerate(metrics, start=1):
        _assert_required_fields(row, STRICT_METRIC_FIELDS, f"metrics_timeseries.jsonl:{index}", errors)
        _assert_strict_fault_dimensions(row, phase, expected_scale, coverage_prefix, f"metrics_timeseries.jsonl:{index}", errors)
        _assert_no_forbidden_values(row, f"metrics_timeseries.jsonl:{index}", errors)
        metric_source_types.add(str(row.get("source_type")))
        if row.get("metric_value") == "MISSING" and not row.get("missing_reason"):
            errors.append(f"metrics_timeseries.jsonl:{index}: MISSING metric requires missing_reason")
    if "workload" not in metric_source_types:
        errors.append("metrics_timeseries.jsonl: strict fault stage requires workload metric rows")

    observed_rows = {str(row.get("row_name") or row.get("fault_type")) for row in fault_results}
    missing_rows = sorted(required_rows - observed_rows)
    if missing_rows:
        errors.append(f"fault_operation_results.jsonl missing rows: {missing_rows}")
    for index, row in enumerate(fault_results, start=1):
        label = f"fault_operation_results.jsonl:{index}:{row.get('row_name', row.get('fault_type', 'MISSING'))}"
        _assert_no_forbidden_values(row, label, errors)
        row_name = str(row.get("row_name") or row.get("fault_type") or "")
        if row_name not in required_rows:
            errors.append(f"{label}: unexpected fault row")
        if row.get("coverage_id") != f"{expected_scale}.fault.{row_name}":
            errors.append(f"{label}: coverage_id must be {expected_scale}.fault.{row_name}")
        if row.get("status") != "PASS" or row.get("real_execution_verified") is not True:
            errors.append(f"{label}: status PASS and real_execution_verified=true required")
        if row.get("scale") != expected_scale or row.get("node_count") != expected_scale:
            errors.append(f"{label}: scale and node_count must be {expected_scale}")
        if not row.get("workload_impact_ref") or row.get("cleanup_verified") is not True:
            errors.append(f"{label}: workload_impact_ref and cleanup_verified=true required")
        if not isinstance(row.get("source_evidence_refs"), list) or not row.get("source_evidence_refs"):
            errors.append(f"{label}: source_evidence_refs required")

    if len(failover_samples) < min_failover_samples:
        errors.append(f"failover_samples.jsonl requires at least {min_failover_samples} samples")
    for index, sample in enumerate(failover_samples, start=1):
        label = f"failover_samples.jsonl:{index}:{sample.get('sample_id', 'MISSING')}"
        _assert_no_forbidden_values(sample, label, errors)
        if sample.get("status") != "PASS" or sample.get("real_valkey") is not True:
            errors.append(f"{label}: status PASS and real_valkey=true required")
        if sample.get("scale") != expected_scale or sample.get("node_count") != expected_scale or sample.get("rung") != expected_scale:
            errors.append(f"{label}: scale, node_count, and rung must be {expected_scale}")
        for field in ["promotion_latency_ms", "cluster_recovery_latency_ms", "fault_injected_at_ms", "replica_promoted_at_ms", "slot_coverage_ok_at_ms"]:
            if not isinstance(sample.get(field), (int, float)):
                errors.append(f"{label}: {field} must be numeric")

    _assert_strict_fault_workload_windows(workload, event_ids, required_rows, errors)
    for index, row in enumerate(topology, start=1):
        for field in ["schema_version", "phase_id", "run_id", "snapshot_id", "timestamp_unix_ms", "nodes", "slots"]:
            if field not in row:
                errors.append(f"fault_topology_snapshots.jsonl:{index}: missing {field}")
        _assert_no_forbidden_values(row, f"fault_topology_snapshots.jsonl:{index}", errors)
    for index, row in enumerate(command_log, start=1):
        for field in ["schema_version", "phase_id", "run_id", "command_id", "command_kind", "started_at_unix_ms", "ended_at_unix_ms", "status"]:
            if field not in row:
                errors.append(f"fault_command_log.jsonl:{index}: missing {field}")
        _assert_no_forbidden_values(row, f"fault_command_log.jsonl:{index}", errors)

    if evidence.get("status") != "PASS" or evidence.get("nodes_observed") != expected_scale or evidence.get("data_path_result") != "PASS":
        errors.append(f"valkey_e2e_evidence.json: {phase} requires PASS evidence, exact {expected_scale} nodes, and data path PASS")
    if cleanup.get("status") != "PASS":
        errors.append("cleanup_report.json: cleanup status must be PASS")
    for artifact_name in ["fault_matrix_report.json", "failover_latency_curve.json", "partition_report.json", "split_brain_report.json", "fault_workload_impact.json"]:
        if required_json[artifact_name].get("status") != "PASS":
            errors.append(f"{artifact_name}: status must be PASS")
    claims = quant_summary.get("runtime_claims", {})
    if claims.get("real_valkey_claimed") is not True or claims.get("fault_runtime_claimed") is not True:
        errors.append("quant_summary.json: real Valkey and fault runtime claims required")
    counts = quant_summary.get("counts", {})
    if counts.get("node_count") != expected_scale or counts.get("fault_row_count") != len(required_rows) or counts.get("failover_sample_count", 0) < min_failover_samples:
        errors.append("quant_summary.json: counts must record exact scale, all fault rows, and enough failover samples")
    _assert_strict_fault_coverage_ledger(coverage_ledger, phase, expected_scale, required_rows, errors)


def _assert_p30_dimensions(row: dict[str, Any], phase: str, scale: int, coverage_prefix: str, label: str, errors: list[str]) -> None:
    if row.get("phase_id") != phase or row.get("stage_id") != phase:
        errors.append(f"{label}: phase_id and stage_id must be {phase}")
    coverage_id = str(row.get("coverage_id", ""))
    if not coverage_id.startswith(coverage_prefix):
        errors.append(f"{label}: coverage_id must be a {coverage_prefix}* row")
    if row.get("scale") != scale or row.get("node_count") != scale:
        errors.append(f"{label}: scale and node_count must be {scale}")


def _assert_strict_fault_dimensions(row: dict[str, Any], phase: str, scale: int, coverage_prefix: str, label: str, errors: list[str]) -> None:
    if row.get("phase_id") != phase or row.get("stage_id") != phase:
        errors.append(f"{label}: phase_id and stage_id must be {phase}")
    coverage_id = str(row.get("coverage_id", ""))
    if not coverage_id.startswith(coverage_prefix):
        errors.append(f"{label}: coverage_id must be a {coverage_prefix}* row")
    if row.get("scale") != scale or row.get("node_count") != scale:
        errors.append(f"{label}: scale and node_count must be {scale}")


def _assert_strict_fault_workload_windows(workload: dict[str, Any], event_ids: set[str], required_rows: set[str], errors: list[str]) -> None:
    windows = workload.get("windows")
    if not isinstance(windows, list):
        errors.append("workload_windows.json: windows must be a list")
        return
    rows_with_windows = set()
    for index, window in enumerate(windows, start=1):
        if not isinstance(window, dict):
            errors.append(f"workload_windows.json:{index}: each window must be an object")
            continue
        row_name = str(window.get("fault_type") or window.get("sample_id") or "")
        label = f"workload_windows.json:{index}:{row_name}"
        _assert_no_forbidden_values(window, label, errors)
        if row_name:
            rows_with_windows.add(row_name)
        if window.get("window_name") != "event":
            errors.append(f"{label}: strict fault row windows must record the event window")
        metrics = window.get("metrics")
        if not isinstance(metrics, dict):
            errors.append(f"{label}: metrics must be an object")
            metrics = {}
        for field in WORKLOAD_METRICS:
            if field not in window:
                errors.append(f"{label}: missing top-level workload metric {field}")
            if field not in metrics:
                errors.append(f"{label}: missing nested workload metric {field}")
            value = window.get(field)
            if value == "MISSING":
                reason = metrics.get("missing_reasons", {}).get(field) or window.get("missing_reasons", {}).get(field)
                if not reason:
                    errors.append(f"{label}: MISSING metric {field} requires reason")
        if window.get("window_start_event_id") not in event_ids or window.get("window_end_event_id") not in event_ids:
            errors.append(f"{label}: workload event IDs must link to events.jsonl")
        if not isinstance(window.get("sample_count"), int) or int(window.get("sample_count", 0)) <= 0:
            errors.append(f"{label}: sample_count must be positive")
    missing = sorted(required_rows - rows_with_windows)
    if missing:
        errors.append(f"workload_windows.json: missing workload event windows for rows {missing}")


def _assert_strict_fault_coverage_ledger(ledger: dict[str, Any], phase: str, scale: int, required_rows: set[str], errors: list[str]) -> None:
    rows = ledger.get("rows", [])
    if ledger.get("stage_id") != phase:
        errors.append(f"coverage_ledger.json: stage_id must be {phase}")
    stage_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("stage_owner") == phase
        and row.get("category") == "fault"
        and row.get("scale") == scale
    ]
    if len(stage_rows) != len(required_rows):
        errors.append(f"coverage_ledger.json: expected {len(required_rows)} P33 fault rows, got {len(stage_rows)}")
    for row in stage_rows:
        row_name = str(row.get("row_name", ""))
        if row_name not in required_rows:
            errors.append(f"coverage_ledger.json: unexpected row {row.get('coverage_id')}")
        if row.get("coverage_id") != f"{scale}.fault.{row_name}":
            errors.append(f"coverage_ledger.json: malformed coverage id for {row_name}")
        if row.get("status") != "PASS":
            errors.append(f"coverage_ledger.json: {row.get('coverage_id')} must be PASS")
        if not row.get("source_artifacts") or not row.get("validation_artifacts") or not row.get("metric_refs") or not row.get("cleanup_ref"):
            errors.append(f"coverage_ledger.json: {row.get('coverage_id')} requires source, validation, metric, and cleanup refs")


def _assert_p30_workload_windows(workload: dict[str, Any], event_ids: set[str], errors: list[str]) -> None:
    windows = workload.get("windows")
    if not isinstance(windows, list):
        errors.append("workload_windows.json: windows must be a list")
        return
    by_operation: dict[str, list[str]] = {}
    for index, window in enumerate(windows, start=1):
        if not isinstance(window, dict):
            errors.append(f"workload_windows.json:{index}: each window must be an object")
            continue
        label = f"workload_windows.json:{window.get('operation_id', index)}:{window.get('window_name', 'MISSING')}"
        _assert_no_forbidden_values(window, label, errors)
        op_id = str(window.get("operation_id", ""))
        by_operation.setdefault(op_id, []).append(str(window.get("window_name")))
        metrics = window.get("metrics")
        if not isinstance(metrics, dict):
            errors.append(f"{label}: metrics must be an object")
            metrics = {}
        for field in WORKLOAD_METRICS:
            if field not in window:
                errors.append(f"{label}: missing top-level workload metric {field}")
            if field not in metrics:
                errors.append(f"{label}: missing nested workload metric {field}")
            value = window.get(field)
            if value == "MISSING":
                reason = metrics.get("missing_reasons", {}).get(field) or window.get("missing_reasons", {}).get(field)
                if not reason:
                    errors.append(f"{label}: MISSING metric {field} requires reason")
        if window.get("window_start_event_id") not in event_ids or window.get("window_end_event_id") not in event_ids:
            errors.append(f"{label}: workload event IDs must link to events.jsonl")
        if not isinstance(window.get("sample_count"), int) or int(window.get("sample_count", 0)) <= 0:
            errors.append(f"{label}: sample_count must be positive")
    for operation_id, names in by_operation.items():
        if names != CANONICAL_WINDOWS:
            errors.append(f"workload_windows.json:{operation_id}: windows must be canonical order {CANONICAL_WINDOWS}, got {names}")


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
