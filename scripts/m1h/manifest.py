#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from common import read_json, read_jsonl, relpath, source_commit, utc_now

REPO_ROOT = Path(__file__).resolve().parents[2]

EVIDENCE_KINDS = {
    "REAL_EXACT_SCALE",
    "REAL_SMALL_SMOKE",
    "M1_FORMAT_RECONSTRUCTED_FROM_REAL_RAW",
    "LEGACY_EVIDENCE_ONLY",
    "FIXTURE_ONLY",
    "DRY_RUN_ONLY",
    "BLOCKED_WITH_REASON",
    "INVALID",
}
ALLOWED_PASS_KINDS = {"REAL_EXACT_SCALE", "M1_FORMAT_RECONSTRUCTED_FROM_REAL_RAW"}
CAPABILITIES = {
    "setup_telemetry",
    "command_audit",
    "management_matrix",
    "workload_benchmark",
    "fault_timeline",
    "system_metrics",
    "report",
    "cleanup",
    "acceptance",
}

C06_SETUP_CORE_METRICS = [
    "nodehost_start_ms",
    "node_config_generate_ms",
    "node_config_distribute_ms",
    "process_start_ms",
    "process_ready_wait_ms",
    "cluster_meet_ms",
    "cluster_slots_assign_ms",
    "replica_replicate_ms",
    "cluster_convergence_probe_ms",
    "full_cluster_probe_ms",
    "cleanup_ms",
    "total_setup_ms",
]

C07_REQUIRED_COMMAND_KINDS = {
    "cluster_meet",
    "cluster_addslots",
    "cluster_replicate",
    "cluster_probe",
    "cleanup",
}
C07_COMMAND_ROW_REQUIRED_FIELDS = {
    "schema_version",
    "artifact_type",
    "phase_id",
    "run_id",
    "scenario",
    "operation_id",
    "step_id",
    "command_id",
    "command_kind",
    "host_id",
    "node_logical_id",
    "client_port",
    "argv",
    "started_at_unix_ms",
    "ended_at_unix_ms",
    "duration_ms",
    "exit_code",
    "stdout_path",
    "stdout_sha256",
    "stderr_path",
    "stderr_sha256",
    "retry_index",
    "timeout_ms",
    "status",
    "error_type",
    "host_network_mutated",
    "global_firewall_mutated",
}
H05_REQUIRED_MANAGEMENT_OPERATIONS = {
    "create_cluster",
    "meet_nodes",
    "add_replica",
    "remove_replica",
    "remove_primary_drained_or_safe_replaced",
    "remove_failed_node",
    "reshard_slot_range",
    "reshard_with_keys",
    "rebalance_after_imbalance",
    "rolling_restart_replica_first",
    "rolling_restart_primary_safe",
}
H06_REQUIRED_WORKLOAD_PROFILES = ["smoke", "uniform", "hotspot", "mixed_rw", "write_heavy", "read_heavy"]
H06_REQUIRED_WORKLOAD_WINDOWS = ["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]
H06_REQUIRED_WORKLOAD_METRICS = [
    "requested_qps",
    "achieved_qps",
    "throughput_ratio",
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
    "moved_count",
    "ask_count",
    "cluster_down_count",
    "readonly_count",
    "tryagain_count",
]
H06_MIN_OPERATIONS_PER_WINDOW = 6
H06_REQUIRED_METRIC_ROW_COUNT = len(H06_REQUIRED_WORKLOAD_PROFILES) * len(H06_REQUIRED_WORKLOAD_WINDOWS) * len(H06_REQUIRED_WORKLOAD_METRICS)
H07_REQUIRED_FAULT_TYPES = [
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
]
H07_REQUIRED_TIMELINE_EVENTS = [
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
]
H07_REQUIRED_TIMELINE_METRICS = [
    "apply_duration_ms",
    "effect_observed_delay_ms",
    "cluster_impact_ms",
    "failover_latency_ms",
    "promotion_latency_ms",
    "client_unavailability_ms",
    "workload_recovery_ms",
    "clear_duration_ms",
    "cleanup_duration_ms",
    "split_brain_window_ms",
    "cluster_down_window_ms",
]
H07_BLOCKED_EXECUTION_MODES = {"fake", "fixture", "dry-run", "dry_run", "dryrun", "legacy", "partial"}
H08_REQUIRED_SYSTEM_SCALES = {30, 50, 100, 200}
H08_BASE_LIFECYCLE_WINDOWS = ["setup", "workload", "cleanup"]
H08_MANAGEMENT_FAULT_SCALES = {50, 100, 200}
H08_ACCEPTED_SYSTEM_SOURCE_TYPES = {
    "system_process",
    "system_network",
    "container_stats",
    "docker_stats",
    "valkey_info",
    "cluster_info",
}
H08_HIGH_VALUE_METRIC_GROUPS = ["cpu", "rss_memory", "network_io", "valkey_info", "cluster_info"]
H08_BLOCKED_EXECUTION_MODES = {"fake", "fixture", "dry-run", "dry_run", "dryrun", "legacy", "partial"}

REQUIRED_CLAIMS: list[tuple[str, int]] = [
    ("setup_telemetry", 30),
    ("setup_telemetry", 50),
    ("setup_telemetry", 100),
    ("setup_telemetry", 200),
    ("command_audit", 50),
    ("command_audit", 100),
    ("command_audit", 200),
    ("management_matrix", 50),
    ("management_matrix", 100),
    ("management_matrix", 200),
    ("workload_benchmark", 30),
    ("workload_benchmark", 50),
    ("workload_benchmark", 100),
    ("workload_benchmark", 200),
    ("fault_timeline", 50),
    ("fault_timeline", 100),
    ("fault_timeline", 200),
    ("system_metrics", 30),
    ("system_metrics", 50),
    ("system_metrics", 100),
    ("system_metrics", 200),
    ("report", 30),
    ("report", 50),
    ("report", 100),
    ("report", 200),
    ("cleanup", 30),
    ("cleanup", 50),
    ("cleanup", 100),
    ("cleanup", 200),
]

SCALE_PHASES = {
    30: ["artifacts/phases/P12_SCALE_LADDER_10_30"],
    50: [
        "artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL",
        "artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL",
        "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_50",
    ],
    100: [
        "artifacts/phases/P31_MANAGEMENT_MATRIX_100_REAL",
        "artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL",
        "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_100",
    ],
    200: [
        "artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL",
        "artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL",
        "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_200",
    ],
}

CAPABILITY_FILES = {
    "setup_telemetry": ["setup_telemetry.json", "runtime_timing_breakdown_*.json", "valkey_e2e_evidence.json"],
    "command_audit": [
        "command_audit_summary.json",
        "command_log.jsonl",
        "management_command_log.jsonl",
        "fault_command_log.jsonl",
        "valkey_e2e_evidence.json",
    ],
    "management_matrix": [
        "management_ops_matrix.json",
        "management_operation_results.jsonl",
        "management_topology_snapshots.jsonl",
        "management_topology_diffs.jsonl",
        "management_workload_impact.json",
        "workload_windows.json",
        "management_command_log.jsonl",
        "valkey_e2e_evidence.json",
    ],
    "workload_benchmark": ["workload_windows.json", "metrics_timeseries.jsonl", "valkey_e2e_evidence.json"],
    "fault_timeline": [
        "fault_timeline_report.json",
        "fault_timeline_events.jsonl",
        "failover_latency_samples.jsonl",
        "fault_sequence.json",
        "fault_command_log.jsonl",
        "workload_windows.json",
        "metrics_timeseries.jsonl",
        "cleanup_report.json",
        "valkey_e2e_evidence.json",
    ],
    "system_metrics": ["system_metrics_report.json", "system_metrics_timeseries.jsonl", "metrics_timeseries.jsonl", "valkey_e2e_evidence.json"],
    "report": ["report_index.json", "report.md", "index.html"],
    "cleanup": ["cleanup_report.json"],
}

CAPABILITY_REQUIRED_CHECKS = {
    "setup_telemetry": [
        "real_valkey_verified",
        "exact_scale_observed",
        "valkey_9_1_verified",
        "setup_telemetry_artifact_present",
        "setup_telemetry_exact_scale",
        "setup_telemetry_status_pass",
        "setup_core_metrics_numeric",
        "setup_per_node_samples_complete",
    ],
    "command_audit": [
        "real_valkey_verified",
        "exact_scale_observed",
        "valkey_9_1_verified",
        "command_audit_summary_present",
        "command_audit_summary_schema_valid",
        "command_log_present",
        "command_log_non_empty",
        "command_log_schema_valid",
        "required_command_kinds_present",
        "no_placeholder_commands",
        "command_kind_argv_consistent",
        "command_output_refs_present",
        "output_hashes_verified",
        "retry_failure_timeout_summary_present",
        "operation_traceability_present",
        "failure_timeout_retry_rows_summarized",
        "summary_missing_or_skipped_empty",
        "empty_legacy_management_log_absent",
    ],
    "management_matrix": [
        "real_valkey_verified",
        "exact_scale_observed",
        "valkey_9_1_verified",
        "management_matrix_present",
        "management_matrix_schema_valid",
        "management_matrix_status_pass",
        "management_required_operations_present",
        "operation_results_present",
        "operation_results_schema_valid",
        "operation_results_exact_scale",
        "operation_semantics_present",
        "topology_refs_resolve",
        "topology_diff_present",
        "topology_diff_schema_valid",
        "topology_diff_refs_resolve",
        "workload_telemetry_present",
        "workload_artifacts_schema_valid",
        "workload_metrics_numeric",
        "workload_refs_resolve",
        "command_refs_resolve",
        "command_refs_c07_valid",
        "command_refs_operation_traceable",
        "topology_exact_health",
        "no_fixture_management_artifacts",
    ],
    "workload_benchmark": [
        "real_valkey_verified",
        "exact_scale_observed",
        "valkey_9_1_verified",
        "workload_windows_present",
        "workload_windows_schema_valid",
        "workload_windows_status_pass",
        "workload_profiles_complete",
        "workload_windows_complete",
        "workload_required_metrics_numeric",
        "metrics_timeseries_present",
        "metrics_timeseries_schema_valid",
        "metrics_row_count_sufficient",
        "metrics_rows_cover_required_matrix",
        "metrics_core_values_numeric",
        "operations_per_window_sufficient",
        "connection_evidence_observed",
        "pipeline_evidence_observed",
        "full_slot_coverage_non_smoke",
        "fake_or_partial_not_promoted",
        "no_fixture_workload_artifacts",
    ],
    "fault_timeline": [
        "real_valkey_verified",
        "exact_scale_observed",
        "valkey_9_1_verified",
        "same_directory_bundle",
        "fault_timeline_report_present",
        "fault_timeline_report_schema_valid",
        "fault_timeline_report_status_pass",
        "fault_timeline_events_present",
        "fault_timeline_events_schema_valid",
        "failover_latency_samples_present",
        "failover_latency_samples_schema_valid",
        "fault_required_types_present",
        "fault_required_events_present",
        "fault_required_metrics_numeric",
        "fault_rows_status_pass",
        "fault_rows_exact_scale",
        "fault_rows_real_valkey",
        "fault_execution_mode_real",
        "workload_refs_resolve",
        "workload_h06_dependency_accepted",
        "cleanup_refs_resolve",
        "clean_cluster_evidence",
        "no_fixture_fault_artifacts",
        "fake_or_partial_not_promoted",
        "no_legacy_fault_promotion",
    ],
    "system_metrics": [
        "real_valkey_verified",
        "exact_scale_observed",
        "valkey_9_1_verified",
        "same_directory_bundle",
        "system_metrics_report_present",
        "system_metrics_report_schema_valid",
        "system_metrics_report_status_pass",
        "system_metrics_report_semantics_valid",
        "system_metrics_timeseries_present",
        "system_metrics_timeseries_schema_valid",
        "system_rows_exact_scale",
        "lifecycle_windows_present",
        "node_coverage_complete",
        "high_value_numeric_coverage",
        "high_value_window_coverage",
        "missing_values_structured",
        "source_refs_resolve",
        "fake_or_partial_not_promoted",
        "no_fixture_system_artifacts",
    ],
    "report": ["exact_scale_observed", "report_index_present", "accepted_inputs_only"],
    "cleanup": ["exact_scale_observed", "cleanup_report_clean"],
}


def claim_id(capability: str, scale: int) -> str:
    return f"{capability}.real_exact.{scale}"


def build_manifest(root: Path) -> dict[str, Any]:
    claims = [build_claim(root, capability, scale) for capability, scale in REQUIRED_CLAIMS]
    return {
        "schema_version": "v1",
        "artifact_type": "m1h_evidence_manifest",
        "created_at": utc_now(),
        "source_commit": source_commit(root),
        "claims": claims,
    }


def build_claim(root: Path, capability: str, scale: int) -> dict[str, Any]:
    candidate_paths = _candidate_paths(root, capability, scale)
    existing = [
        path
        for path in candidate_paths
        if path.exists()
        and (
            not path.is_file()
            or path.stat().st_size > 0
            or (capability == "command_audit" and path.suffix == ".jsonl" and "command" in path.name)
        )
    ]
    non_fixture_existing = [path for path in existing if not _is_fixture_path(root, path)]
    if non_fixture_existing:
        existing = non_fixture_existing
    source_artifacts = [relpath(root, path) for path in existing]
    semantic_checks = _semantic_checks(root, capability, scale, existing)
    evidence_kind = _evidence_kind(capability, source_artifacts, semantic_checks)
    status = "PASS" if _claim_passes(evidence_kind, semantic_checks) else "BLOCKED_WITH_REASON"
    blocked_reason = None
    if status != "PASS":
        blocked_reason = _blocked_reason(capability, scale, evidence_kind, semantic_checks)
    diagnostics: dict[str, Any] = {}
    setup_diagnostics = semantic_checks.pop("setup_c06_acceptance", None)
    if setup_diagnostics is not None:
        diagnostics["setup_c06_acceptance"] = setup_diagnostics
    command_diagnostics = semantic_checks.pop("command_c07_acceptance", None)
    if command_diagnostics is not None:
        diagnostics["command_c07_acceptance"] = command_diagnostics
    management_diagnostics = semantic_checks.pop("management_h05_acceptance", None)
    if management_diagnostics is not None:
        diagnostics["management_h05_acceptance"] = management_diagnostics
    workload_diagnostics = semantic_checks.pop("workload_h06_acceptance", None)
    if workload_diagnostics is not None:
        diagnostics["workload_h06_acceptance"] = workload_diagnostics
    fault_diagnostics = semantic_checks.pop("fault_h07_acceptance", None)
    if fault_diagnostics is not None:
        diagnostics["fault_h07_acceptance"] = fault_diagnostics
    system_diagnostics = semantic_checks.pop("system_h08_acceptance", None)
    if system_diagnostics is not None:
        diagnostics["system_h08_acceptance"] = system_diagnostics
    claim: dict[str, Any] = {
        "claim_id": claim_id(capability, scale),
        "stage_id": "M1H",
        "capability": capability,
        "scale": scale,
        "evidence_kind": evidence_kind,
        "required_for_milestone_pass": True,
        "source_artifacts": source_artifacts,
        "semantic_checks": semantic_checks,
        "status": status,
    }
    if blocked_reason:
        claim["reason"] = blocked_reason
    if diagnostics:
        claim["diagnostics"] = diagnostics
    return claim


def _candidate_paths(root: Path, capability: str, scale: int) -> list[Path]:
    paths: list[Path] = []
    for phase in SCALE_PHASES.get(scale, []):
        base = root / phase
        for pattern in CAPABILITY_FILES[capability]:
            paths.extend(base.glob(pattern))
            paths.extend(base.glob(f"**/{pattern}"))
    fixture_base = root / "tests" / "fixtures"
    for pattern in CAPABILITY_FILES[capability]:
        paths.extend(fixture_base.glob(f"**/scale_{scale}/{pattern}"))
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _semantic_checks(root: Path, capability: str, scale: int, paths: list[Path]) -> dict[str, Any]:
    checks = {name: False for name in CAPABILITY_REQUIRED_CHECKS[capability]}
    checks["m1_format_fields_complete"] = False
    evidence = _best_evidence(root, paths)
    nodes_observed = int(evidence.get("nodes_observed", 0) or 0) if isinstance(evidence, dict) else 0
    checks["exact_scale_observed"] = nodes_observed >= scale
    checks["real_valkey_verified"] = isinstance(evidence, dict) and evidence.get("real_valkey") is True
    checks["valkey_9_1_verified"] = isinstance(evidence, dict) and any(str(v).startswith("9.1.") for v in evidence.get("valkey_versions", []))

    by_name = {path.name: path for path in paths}
    if capability == "setup_telemetry":
        setup_evaluation = evaluate_setup_telemetry_claim(root, scale, paths, evidence)
        checks.update(setup_evaluation["checks"])
        checks["setup_core_metrics_present"] = checks["setup_core_metrics_numeric"]
        checks["setup_c06_acceptance"] = setup_evaluation
    elif capability == "command_audit":
        command_evaluation = evaluate_command_audit_claim(root, scale, paths, evidence)
        checks.update(command_evaluation["checks"])
        checks["command_c07_acceptance"] = command_evaluation
    elif capability == "management_matrix":
        management_evaluation = evaluate_management_matrix_claim(root, scale, paths, evidence)
        checks.update(management_evaluation["checks"])
        checks["management_h05_acceptance"] = management_evaluation
    elif capability == "workload_benchmark":
        workload_evaluation = evaluate_workload_benchmark_claim(root, scale, paths)
        checks.update(workload_evaluation["checks"])
        checks["workload_h06_acceptance"] = workload_evaluation
    elif capability == "fault_timeline":
        fault_evaluation = evaluate_fault_timeline_claim(root, scale, paths)
        checks.update(fault_evaluation["checks"])
        checks["fault_h07_acceptance"] = fault_evaluation
    elif capability == "system_metrics":
        system_evaluation = evaluate_system_metrics_claim(root, scale, paths, evidence)
        checks.update(system_evaluation["checks"])
        checks["system_h08_acceptance"] = system_evaluation
    elif capability == "report":
        checks["report_index_present"] = "report_index.json" in by_name
        checks["accepted_inputs_only"] = False
    elif capability == "cleanup":
        cleanup = read_json(by_name.get("cleanup_report.json", Path()))
        checks["cleanup_report_clean"] = isinstance(cleanup, dict) and cleanup.get("status") == "PASS" and not cleanup.get("resources_remaining")

    checks["m1_format_fields_complete"] = all(bool(checks.get(name)) for name in CAPABILITY_REQUIRED_CHECKS[capability])
    checks["hardening_stage_accepted"] = (
        bool(checks.get("setup_c06_acceptance", {}).get("accepted"))
        if capability == "setup_telemetry"
        else bool(checks.get("command_c07_acceptance", {}).get("accepted"))
        if capability == "command_audit"
        else bool(checks.get("management_h05_acceptance", {}).get("accepted"))
        if capability == "management_matrix"
        else bool(checks.get("workload_h06_acceptance", {}).get("accepted"))
        if capability == "workload_benchmark"
        else bool(checks.get("fault_h07_acceptance", {}).get("accepted"))
        if capability == "fault_timeline"
        else bool(checks.get("system_h08_acceptance", {}).get("accepted"))
        if capability == "system_metrics"
        else False
    )
    return checks


def evaluate_setup_telemetry_claim(root: Path, scale: int, paths: list[Path], evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence = evidence if isinstance(evidence, dict) else _best_evidence(root, paths)
    setup_paths = [path for path in paths if path.name == "setup_telemetry.json"]
    non_fixture_setup_paths = [path for path in setup_paths if not _is_fixture_path(root, path)]
    real_exact = _real_valkey_exact_scale(evidence, scale)
    valkey_9_1 = isinstance(evidence, dict) and any(str(version).startswith("9.1.") for version in evidence.get("valkey_versions", []))
    best: dict[str, Any] | None = None
    best_path: Path | None = None
    best_checks: dict[str, bool] = {
        "setup_telemetry_artifact_present": bool(non_fixture_setup_paths),
        "setup_telemetry_exact_scale": False,
        "setup_telemetry_status_pass": False,
        "setup_core_metrics_numeric": False,
        "setup_per_node_samples_complete": False,
    }
    best_reasons: list[str] = []

    candidate_paths = non_fixture_setup_paths or setup_paths
    for path in candidate_paths:
        artifact = read_json(path)
        if not isinstance(artifact, dict):
            candidate_checks = dict(best_checks)
            candidate_reasons = [f"{relpath(root, path)} is not readable JSON."]
        else:
            candidate_checks, candidate_reasons = _evaluate_setup_telemetry_artifact(root, path, artifact, scale)
        candidate_score = sum(1 for value in candidate_checks.values() if value)
        best_score = sum(1 for value in best_checks.values() if value)
        if best is None or candidate_score > best_score:
            best = artifact if isinstance(artifact, dict) else None
            best_path = path
            best_checks = candidate_checks
            best_reasons = candidate_reasons

    reasons: list[str] = []
    if not setup_paths:
        reasons.append("M1-format setup_telemetry.json is missing for this exact-scale setup claim.")
    elif not non_fixture_setup_paths:
        reasons.append("Only fixture setup_telemetry.json artifacts were found; fixtures cannot satisfy exact-scale setup telemetry.")
    reasons.extend(best_reasons)
    if not real_exact:
        observed = evidence.get("nodes_observed") if isinstance(evidence, dict) else None
        reasons.append(f"Real Valkey evidence is not an exact-scale PASS for {scale} nodes (nodes_observed={observed!r}).")
    if not valkey_9_1:
        reasons.append("Real Valkey evidence does not prove a Valkey 9.1.x version.")
    if any(path.name.startswith("runtime_timing_breakdown") for path in paths) and not non_fixture_setup_paths:
        reasons.append("runtime_timing_breakdown artifacts are legacy timing evidence only and cannot satisfy C06 setup telemetry.")

    checks = {
        **best_checks,
        "real_valkey_exact_scale": real_exact,
        "valkey_9_1_verified": valkey_9_1,
    }
    accepted = real_exact and valkey_9_1 and all(best_checks.values())
    return {
        "accepted": accepted,
        "checks": checks,
        "reasons": _dedupe(reasons),
        "artifact_path": relpath(root, best_path) if best_path else None,
        "artifact_status": best.get("status") if isinstance(best, dict) else None,
        "artifact_node_count": best.get("node_count") if isinstance(best, dict) else None,
        "core_metrics": C06_SETUP_CORE_METRICS,
    }


def _evaluate_setup_telemetry_artifact(root: Path, path: Path, artifact: dict[str, Any], scale: int) -> tuple[dict[str, bool], list[str]]:
    metrics = artifact.get("metrics")
    per_node_samples = artifact.get("per_node_samples")
    metric_reasons = _numeric_c06_metric_reasons(metrics)
    node_reasons = _per_node_sample_reasons(per_node_samples, scale)
    checks = {
        "setup_telemetry_artifact_present": artifact.get("artifact_type") == "setup_telemetry" and not _is_fixture_path(root, path),
        "setup_telemetry_exact_scale": artifact.get("node_count") == scale,
        "setup_telemetry_status_pass": artifact.get("status") == "PASS",
        "setup_core_metrics_numeric": not metric_reasons,
        "setup_per_node_samples_complete": not node_reasons,
    }
    reasons: list[str] = []
    if artifact.get("artifact_type") != "setup_telemetry":
        reasons.append(f"{relpath(root, path)} artifact_type is not setup_telemetry.")
    if _is_fixture_path(root, path):
        reasons.append(f"{relpath(root, path)} is fixture evidence and cannot satisfy exact-scale setup telemetry.")
    if artifact.get("node_count") != scale:
        reasons.append(f"{relpath(root, path)} node_count {artifact.get('node_count')!r} does not equal required scale {scale}.")
    if artifact.get("status") != "PASS":
        reasons.append(f"{relpath(root, path)} status {artifact.get('status')!r} is not PASS.")
    reasons.extend(metric_reasons)
    reasons.extend(node_reasons)
    return checks, reasons


def _numeric_c06_metric_reasons(metrics: Any) -> list[str]:
    if not isinstance(metrics, dict):
        return ["setup_telemetry.metrics is missing or not an object."]
    reasons: list[str] = []
    for metric in C06_SETUP_CORE_METRICS:
        value = metrics.get(metric)
        if not _is_non_negative_number(value):
            if isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON"}:
                reasons.append(f"C06 core metric {metric} is {value.get('status')} for an exact-scale setup PASS.")
            else:
                reasons.append(f"C06 core metric {metric} is missing or non-numeric.")
    return reasons


def _per_node_sample_reasons(samples: Any, scale: int) -> list[str]:
    if not isinstance(samples, list):
        return ["setup_telemetry.per_node_samples is missing or not an array."]
    if len(samples) < scale:
        return [f"setup_telemetry.per_node_samples has {len(samples)} samples but exact-scale PASS requires at least {scale}."]
    reasons: list[str] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            reasons.append(f"per_node_samples[{index}] is not an object.")
            continue
        required_values = {
            "node_id": _first_present(sample, "logical_id", "node_id"),
            "role": _first_present(sample, "node_role", "role"),
            "nodehost_id": sample.get("nodehost_id"),
            "pid": _first_present(sample, "node_pid", "pid"),
            "ready_metric": _first_present(sample, "node_ready_ms", "node_ping_ready_ms"),
            "cluster_state": _first_present(sample, "node_cluster_state", "cluster_state"),
            "known_nodes": _first_present(sample, "node_cluster_known_nodes", "known_nodes"),
        }
        for field, value in required_values.items():
            if _is_missing_placeholder(value):
                reasons.append(f"per_node_samples[{index}].{field} is missing or skipped.")
        for numeric_field in ["pid", "ready_metric", "known_nodes"]:
            value = required_values[numeric_field]
            if not _is_missing_placeholder(value) and not _is_non_negative_number(value):
                reasons.append(f"per_node_samples[{index}].{numeric_field} is non-numeric.")
    return reasons


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _is_non_negative_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) >= 0


def _is_missing_placeholder(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value in {"", "MISSING", "SKIPPED_WITH_REASON"}:
        return True
    return isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON"}


def _real_valkey_exact_scale(evidence: dict[str, Any], scale: int) -> bool:
    if not isinstance(evidence, dict):
        return False
    return evidence.get("status") == "PASS" and evidence.get("real_valkey") is True and evidence.get("nodes_observed") == scale


def evaluate_system_metrics_claim(root: Path, scale: int, paths: list[Path], evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    non_fixture_paths = [path for path in paths if not _is_fixture_path(root, path)]
    candidate_dirs = sorted({path.parent for path in non_fixture_paths}) or sorted({path.parent for path in paths})
    best: dict[str, Any] | None = None
    for directory in candidate_dirs:
        bundle_paths = [path for path in paths if path.parent == directory]
        candidate = _evaluate_system_metrics_bundle(root, scale, bundle_paths)
        if best is None or _system_metrics_score(candidate["checks"]) > _system_metrics_score(best["checks"]):
            best = candidate
    if best is not None:
        return best
    evidence = evidence if isinstance(evidence, dict) else _best_evidence(root, paths)
    real_exact = _real_valkey_exact_scale(evidence, scale)
    valkey_9_1 = isinstance(evidence, dict) and any(str(version).startswith("9.1.") for version in evidence.get("valkey_versions", []))
    return {
        "accepted": False,
        "checks": _empty_system_metrics_checks(real_exact, valkey_9_1),
        "reasons": ["No same-directory H08 system_metrics_report.json, system_metrics_timeseries.jsonl, and valkey_e2e_evidence.json bundle was found."],
        "report_path": None,
        "timeseries_path": None,
        "valkey_evidence_path": None,
        "required_windows": _h08_required_windows(scale),
        "high_value_metric_groups": H08_HIGH_VALUE_METRIC_GROUPS,
        "system_row_count": 0,
        "rejected_non_system_row_count": 0,
        "unique_node_count": 0,
    }


def _system_metrics_score(checks: dict[str, bool]) -> int:
    return sum(1 for value in checks.values() if value is True)


def _h08_required_windows(scale: int) -> list[str]:
    windows = list(H08_BASE_LIFECYCLE_WINDOWS)
    if scale in H08_MANAGEMENT_FAULT_SCALES:
        windows.insert(1, "management")
        windows.insert(3, "fault_or_failover")
    return windows


def _empty_system_metrics_checks(real_exact: bool, valkey_9_1: bool) -> dict[str, bool]:
    return {
        "real_valkey_verified": real_exact,
        "exact_scale_observed": real_exact,
        "valkey_9_1_verified": valkey_9_1,
        "same_directory_bundle": False,
        "system_metrics_report_present": False,
        "system_metrics_report_schema_valid": False,
        "system_metrics_report_status_pass": False,
        "system_metrics_report_semantics_valid": False,
        "system_metrics_timeseries_present": False,
        "system_metrics_timeseries_schema_valid": False,
        "system_rows_exact_scale": False,
        "lifecycle_windows_present": False,
        "node_coverage_complete": False,
        "high_value_numeric_coverage": False,
        "high_value_window_coverage": False,
        "missing_values_structured": False,
        "source_refs_resolve": False,
        "fake_or_partial_not_promoted": False,
        "no_fixture_system_artifacts": False,
    }


def _evaluate_system_metrics_bundle(root: Path, scale: int, paths: list[Path]) -> dict[str, Any]:
    evidence = _best_evidence(root, paths)
    real_exact = _real_valkey_exact_scale(evidence, scale)
    valkey_9_1 = isinstance(evidence, dict) and any(str(version).startswith("9.1.") for version in evidence.get("valkey_versions", []))
    checks = _empty_system_metrics_checks(real_exact, valkey_9_1)
    all_by_name = {path.name: path for path in paths}
    non_fixture_paths = [path for path in paths if not _is_fixture_path(root, path)]
    non_fixture_by_name = {path.name: path for path in non_fixture_paths}
    by_name = non_fixture_by_name or all_by_name
    report_path = by_name.get("system_metrics_report.json")
    timeseries_path = by_name.get("system_metrics_timeseries.jsonl")
    generic_metrics_path = by_name.get("metrics_timeseries.jsonl")
    valkey_path = by_name.get("valkey_e2e_evidence.json")
    bundle_dir = next(iter(sorted({path.parent for path in paths})), None)
    report = read_json(report_path) if report_path else {}
    rows, row_jsonl_reasons = _read_system_metrics_jsonl_strict(root, timeseries_path)
    generic_rows, _generic_reasons = _read_system_metrics_jsonl_strict(root, generic_metrics_path)
    required_windows = _h08_required_windows(scale)
    reasons: list[str] = []
    has_fixture = any(_is_fixture_path(root, path) for path in paths)
    has_non_fixture = bool(non_fixture_paths)

    if not report_path:
        reasons.append("system_metrics_report.json is missing from the same directory as H08 system metrics evidence.")
    if not timeseries_path:
        reasons.append("system_metrics_timeseries.jsonl is missing from the same directory as H08 system metrics evidence; generic metrics_timeseries.jsonl cannot satisfy C10.")
    if not valkey_path:
        reasons.append("valkey_e2e_evidence.json is missing from the same directory as H08 system metrics evidence.")
    if generic_metrics_path and not timeseries_path:
        reasons.append(f"{relpath(root, generic_metrics_path)} contains generic metrics rows; workload/fault/management metrics_timeseries rows do not count as system metrics coverage.")
    if has_fixture and not has_non_fixture:
        reasons.append("Only fixture system metrics artifacts were found; fixtures cannot satisfy exact-scale H08 system metrics.")

    report_schema_reasons = _schema_reasons(root, report_path, report, "system_metrics_report.schema.json")
    report_checks, report_reasons = _system_metrics_report_reasons(root, report_path, report, rows, scale, required_windows, bundle_dir)
    row_checks, row_reasons, row_stats = _system_metric_row_reasons(root, scale, timeseries_path, rows, required_windows)
    fake_partial_reasons = _system_metrics_fake_or_partial_reasons(root, paths, report, rows)
    generic_rejected = sum(
        1
        for row in generic_rows
        if isinstance(row, dict) and str(row.get("source_type", "")) not in H08_ACCEPTED_SYSTEM_SOURCE_TYPES
    )

    reasons.extend(report_schema_reasons)
    reasons.extend(report_reasons)
    reasons.extend(row_jsonl_reasons)
    reasons.extend(row_reasons)
    reasons.extend(fake_partial_reasons)
    if not real_exact:
        observed = evidence.get("nodes_observed") if isinstance(evidence, dict) else None
        reasons.append(f"Real Valkey evidence is not an exact-scale PASS for {scale} nodes (nodes_observed={observed!r}).")
    if not valkey_9_1:
        reasons.append("Real Valkey evidence does not prove a Valkey 9.1.x version.")

    checks.update(
        {
            "real_valkey_verified": isinstance(evidence, dict) and evidence.get("real_valkey") is True,
            "exact_scale_observed": real_exact,
            "valkey_9_1_verified": valkey_9_1,
            "same_directory_bundle": all(path is not None and path.parent == bundle_dir for path in [report_path, timeseries_path, valkey_path]),
            "system_metrics_report_present": report_path is not None and isinstance(report, dict) and not _is_fixture_path(root, report_path),
            "system_metrics_report_schema_valid": not report_schema_reasons,
            "system_metrics_report_status_pass": isinstance(report, dict) and report.get("status") == "PASS",
            "system_metrics_report_semantics_valid": not report_reasons,
            "system_metrics_timeseries_present": timeseries_path is not None and bool(rows) and not _is_fixture_path(root, timeseries_path),
            "system_metrics_timeseries_schema_valid": bool(rows) and not row_jsonl_reasons and not row_reasons,
            **row_checks,
            **report_checks,
            "fake_or_partial_not_promoted": not fake_partial_reasons,
            "no_fixture_system_artifacts": not has_fixture or has_non_fixture,
        }
    )
    accepted = real_exact and valkey_9_1 and all(checks.values())
    return {
        "accepted": accepted,
        "checks": checks,
        "reasons": _dedupe(reasons),
        "report_path": relpath(root, report_path) if report_path else None,
        "timeseries_path": relpath(root, timeseries_path) if timeseries_path else None,
        "valkey_evidence_path": relpath(root, valkey_path) if valkey_path else None,
        "required_windows": required_windows,
        "high_value_metric_groups": H08_HIGH_VALUE_METRIC_GROUPS,
        "system_row_count": len(rows),
        "rejected_non_system_row_count": row_stats["rejected_non_system_row_count"] + generic_rejected,
        "unique_node_count": row_stats["unique_node_count"],
        "numeric_groups_covered": sorted(row_stats["numeric_groups_covered"]),
        "numeric_groups_by_window": {window: sorted(groups) for window, groups in row_stats["numeric_groups_by_window"].items()},
    }


def _read_system_metrics_jsonl_strict(root: Path, path: Path | None) -> tuple[list[Any], list[str]]:
    if path is None:
        return [], []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"{relpath(root, path)} could not be read: {exc}."]
    rows: list[Any] = []
    reasons: list[str] = []
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            reasons.append(f"{relpath(root, path)} line {line_no} is invalid JSON: {exc.msg}.")
            continue
        if not isinstance(value, dict):
            reasons.append(f"{relpath(root, path)} line {line_no} is not a JSON object.")
        rows.append(value)
    return rows, reasons


def _system_metric_row_reasons(root: Path, scale: int, path: Path | None, rows: list[Any], required_windows: list[str]) -> tuple[dict[str, bool], list[str], dict[str, Any]]:
    reasons: list[str] = []
    windows_observed: set[str] = set()
    node_ids: set[str] = set()
    row_counts_by_window: dict[str, int] = {}
    row_counts_by_node: dict[str, int] = {}
    numeric_groups: set[str] = set()
    numeric_groups_by_window: dict[str, set[str]] = {window: set() for window in required_windows}
    exact_scale_ok = bool(rows)
    missing_structured_ok = bool(rows)
    rejected_non_system_rows = 0
    for index, row in enumerate(rows):
        label = f"{relpath(root, path) if path else 'system_metrics_timeseries.jsonl'} line {index + 1}"
        if not isinstance(row, dict):
            reasons.append(f"{label} is not a JSON object.")
            exact_scale_ok = False
            missing_structured_ok = False
            continue
        if row.get("schema_version") != "v1":
            reasons.append(f"{label} schema_version is not v1.")
            exact_scale_ok = False
        row_scale = row.get("node_count", row.get("scale"))
        if row_scale != scale:
            reasons.append(f"{label} node_count/scale {row_scale!r} does not equal required scale {scale}.")
            exact_scale_ok = False
        labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
        node_id = _first_present(row, "node_id", "logical_node_id", "node_logical_id")
        if node_id is None:
            node_id = _first_present(labels, "logical_node_id", "node_id", "node_logical_id")
        if not isinstance(node_id, str) or not node_id.strip():
            reasons.append(f"{label} node_id/logical_node_id is missing from the row and labels.")
            exact_scale_ok = False
        else:
            node_ids.add(node_id)
            row_counts_by_node[node_id] = row_counts_by_node.get(node_id, 0) + 1
        window = row.get("lifecycle_window")
        if window is None:
            window = labels.get("lifecycle_window", labels.get("stage_window"))
        if not isinstance(window, str) or window not in required_windows:
            reasons.append(f"{label} lifecycle_window {window!r} is not one of required windows: {', '.join(required_windows)}.")
            exact_scale_ok = False
        else:
            windows_observed.add(window)
            row_counts_by_window[window] = row_counts_by_window.get(window, 0) + 1
        source_type = row.get("source_type")
        if source_type not in H08_ACCEPTED_SYSTEM_SOURCE_TYPES:
            rejected_non_system_rows += 1
            reasons.append(f"{label} source_type {source_type!r} is not accepted H08 system metrics source coverage.")
            exact_scale_ok = False
        metric_name = row.get("metric_name")
        if not isinstance(metric_name, str) or not metric_name.strip():
            reasons.append(f"{label} metric_name is missing.")
            exact_scale_ok = False
        if not _is_non_negative_number(row.get("timestamp_unix_ms")):
            reasons.append(f"{label} timestamp_unix_ms is missing or non-numeric.")
            exact_scale_ok = False
        if not _is_non_negative_number(row.get("monotonic_ms")):
            reasons.append(f"{label} monotonic_ms is missing or non-numeric.")
            exact_scale_ok = False
        value = row.get("metric_value")
        value_is_numeric = _is_non_negative_number(value)
        value_is_missing = _h08_value_is_missing(value)
        if not value_is_numeric:
            if value_is_missing:
                reason = row.get("missing_reason")
                dict_reason = value.get("reason") if isinstance(value, dict) else None
                if not ((isinstance(reason, str) and reason.strip()) or (isinstance(dict_reason, str) and dict_reason.strip())):
                    reasons.append(f"{label} metric_value is {value!r} without a non-empty missing_reason.")
                    missing_structured_ok = False
            else:
                reasons.append(f"{label} metric_value is neither numeric nor MISSING/SKIPPED_WITH_REASON.")
                missing_structured_ok = False
        if value_is_numeric and source_type in H08_ACCEPTED_SYSTEM_SOURCE_TYPES and isinstance(metric_name, str) and isinstance(window, str):
            group = _h08_metric_group(source_type, metric_name)
            if group:
                numeric_groups.add(group)
                if window in numeric_groups_by_window:
                    numeric_groups_by_window[window].add(group)

    missing_windows = [window for window in required_windows if window not in windows_observed]
    if missing_windows:
        reasons.append(f"system_metrics_timeseries.jsonl is missing lifecycle windows: {', '.join(missing_windows)}.")
    if len(node_ids) != scale:
        reasons.append(f"system_metrics_timeseries.jsonl covers {len(node_ids)} unique nodes but exact-scale H08 requires exactly {scale}.")
    missing_groups = [group for group in H08_HIGH_VALUE_METRIC_GROUPS if group not in numeric_groups]
    if missing_groups:
        reasons.append(f"system_metrics_timeseries.jsonl lacks numeric high-value metric groups: {', '.join(missing_groups)}.")
    missing_window_groups = {
        window: [group for group in H08_HIGH_VALUE_METRIC_GROUPS if group not in numeric_groups_by_window[window]]
        for window in required_windows
        if window in numeric_groups_by_window and any(group not in numeric_groups_by_window[window] for group in H08_HIGH_VALUE_METRIC_GROUPS)
    }
    if missing_window_groups:
        formatted = [f"{window}:{','.join(groups)}" for window, groups in missing_window_groups.items()]
        reasons.append(f"system_metrics_timeseries.jsonl lacks per-window high-value numeric coverage: {'; '.join(formatted)}.")

    checks = {
        "system_rows_exact_scale": exact_scale_ok,
        "lifecycle_windows_present": not missing_windows and bool(rows),
        "node_coverage_complete": len(node_ids) == scale,
        "high_value_numeric_coverage": not missing_groups,
        "high_value_window_coverage": not missing_window_groups,
        "missing_values_structured": missing_structured_ok,
    }
    return checks, _dedupe(reasons), {
        "unique_node_count": len(node_ids),
        "row_counts_by_window": row_counts_by_window,
        "row_counts_by_node": row_counts_by_node,
        "rejected_non_system_row_count": rejected_non_system_rows,
        "numeric_groups_covered": numeric_groups,
        "numeric_groups_by_window": numeric_groups_by_window,
    }


def _system_metrics_report_reasons(
    root: Path,
    path: Path | None,
    report: Any,
    rows: list[Any],
    scale: int,
    required_windows: list[str],
    bundle_dir: Path | None,
) -> tuple[dict[str, bool], list[str]]:
    if not isinstance(report, dict):
        return {"source_refs_resolve": False}, ["system_metrics_report.json is missing or invalid JSON."]
    reasons: list[str] = []
    if report.get("status") != "PASS":
        reasons.append(f"system_metrics_report.json status {report.get('status')!r} is not PASS.")
    report_scale = report.get("node_count", report.get("scale"))
    if report_scale != scale:
        reasons.append(f"system_metrics_report.json node_count/scale {report_scale!r} does not equal required scale {scale}.")
    if report.get("sample_count") != len(rows):
        reasons.append(f"system_metrics_report.json sample_count {report.get('sample_count')!r} does not match system_metrics_timeseries.jsonl row count {len(rows)}.")
    windows = report.get("lifecycle_windows")
    if not isinstance(windows, list):
        reasons.append("system_metrics_report.json lifecycle_windows is missing or not an array.")
        windows = []
    missing_windows = [window for window in required_windows if window not in windows]
    if missing_windows:
        reasons.append(f"system_metrics_report.json lifecycle_windows is missing required windows: {', '.join(missing_windows)}.")
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    rows_by_window = coverage.get("rows_by_window") if isinstance(coverage.get("rows_by_window"), dict) else {}
    report_missing_windows = [window for window in required_windows if not isinstance(rows_by_window.get(window), int) or rows_by_window.get(window, 0) <= 0]
    if report_missing_windows:
        reasons.append(f"system_metrics_report.json coverage.rows_by_window lacks positive counts for: {', '.join(report_missing_windows)}.")
    parsed_rows_by_window = _h08_row_counts_by_window(rows)
    for window in required_windows:
        expected = parsed_rows_by_window.get(window, 0)
        actual = rows_by_window.get(window)
        if actual != expected:
            reasons.append(f"system_metrics_report.json coverage.rows_by_window[{window!r}] {actual!r} does not match parsed row count {expected}.")
    rows_by_node = coverage.get("rows_by_node") if isinstance(coverage.get("rows_by_node"), dict) else {}
    if len(rows_by_node) != scale:
        reasons.append(f"system_metrics_report.json coverage.rows_by_node covers {len(rows_by_node)} nodes but exact-scale H08 requires exactly {scale}.")
    parsed_rows_by_node = _h08_row_counts_by_node(rows)
    if set(rows_by_node) != set(parsed_rows_by_node):
        reasons.append("system_metrics_report.json coverage.rows_by_node keys do not match parsed timeseries node ids.")
    for node_id, expected in sorted(parsed_rows_by_node.items()):
        actual = rows_by_node.get(node_id)
        if actual != expected:
            reasons.append(f"system_metrics_report.json coverage.rows_by_node[{node_id!r}] {actual!r} does not match parsed row count {expected}.")
    missing_metrics = report.get("missing_metrics")
    if not isinstance(missing_metrics, list):
        reasons.append("system_metrics_report.json missing_metrics is missing or not an array.")
    else:
        for index, item in enumerate(missing_metrics):
            if not isinstance(item, dict):
                reasons.append(f"system_metrics_report.json missing_metrics[{index}] is not an object.")
                continue
            if item.get("status") not in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"}:
                reasons.append(f"system_metrics_report.json missing_metrics[{index}] status {item.get('status')!r} is not structured.")
            if not isinstance(item.get("reason"), str) or not item.get("reason", "").strip():
                reasons.append(f"system_metrics_report.json missing_metrics[{index}] reason is missing.")
    ref_reasons = _h08_source_ref_reasons(root, bundle_dir, report.get("source_refs"))
    reasons.extend(ref_reasons)
    return {"source_refs_resolve": not ref_reasons}, _dedupe(reasons)


def _h08_row_counts_by_window(rows: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
        window = row.get("lifecycle_window")
        if window is None:
            window = labels.get("lifecycle_window", labels.get("stage_window"))
        if isinstance(window, str) and window:
            counts[window] = counts.get(window, 0) + 1
    return counts


def _h08_row_counts_by_node(rows: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
        node_id = _first_present(row, "node_id", "logical_node_id", "node_logical_id")
        if node_id is None:
            node_id = _first_present(labels, "logical_node_id", "node_id", "node_logical_id")
        if isinstance(node_id, str) and node_id:
            counts[node_id] = counts.get(node_id, 0) + 1
    return counts


def _h08_source_ref_reasons(root: Path, bundle_dir: Path | None, source_refs: Any) -> list[str]:
    if bundle_dir is None:
        return ["system_metrics_report.json source_refs cannot resolve without a bundle directory."]
    if not isinstance(source_refs, dict):
        return ["system_metrics_report.json source_refs is missing or not an object."]
    values: list[str] = []
    for value in source_refs.values():
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    reasons: list[str] = []
    for required in ["system_metrics_timeseries.jsonl", "valkey_e2e_evidence.json"]:
        matching = [value for value in values if Path(value).name == required]
        if not matching:
            reasons.append(f"system_metrics_report.json source_refs does not cite {required}.")
            continue
        if not any((bundle_dir / value).exists() for value in matching):
            reasons.append(f"system_metrics_report.json source_refs cites {required}, but it does not resolve within {relpath(root, bundle_dir)}.")
    return reasons


def _h08_value_is_missing(value: Any) -> bool:
    if isinstance(value, str):
        return value in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"}
    if isinstance(value, dict):
        return value.get("status") in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"}
    return False


def _h08_metric_group(source_type: str, metric_name: str) -> str | None:
    lowered = metric_name.lower()
    if source_type in {"system_process", "container_stats", "docker_stats"} and "cpu" in lowered:
        return "cpu"
    if source_type in {"system_process", "container_stats", "docker_stats", "valkey_info"} and any(token in lowered for token in ["rss", "resident", "memory", "mem", "used_memory"]):
        return "rss_memory"
    if source_type in {"system_network", "container_stats", "docker_stats", "valkey_info"} and any(token in lowered for token in ["network", "net_", "rx", "tx", "bytes_in", "bytes_out", "input_kbps", "output_kbps", "instantaneous_input", "instantaneous_output"]):
        return "network_io"
    if source_type == "valkey_info":
        return "valkey_info"
    if source_type == "cluster_info":
        return "cluster_info"
    return None


def _system_metrics_fake_or_partial_reasons(root: Path, paths: list[Path], report: Any, rows: list[Any]) -> list[str]:
    reasons: list[str] = []
    if _contains_fake_or_partial(root, paths):
        reasons.append("System metrics source path contains fake, partial, or fixture marker.")
    for payload in [report, *rows]:
        if not isinstance(payload, dict):
            continue
        for key in ["status", "evidence_kind", "evidence_class", "source_kind", "execution_mode", "workload_mode"]:
            value = payload.get(key)
            if isinstance(value, str) and value.lower() in H08_BLOCKED_EXECUTION_MODES:
                reasons.append(f"System metrics artifact contains {key}={value!r}; fake, partial, dry-run, or legacy evidence cannot promote.")
    return _dedupe(reasons)


def evaluate_command_audit_claim(root: Path, scale: int, paths: list[Path], evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence = evidence if isinstance(evidence, dict) else _best_evidence(root, paths)
    real_exact = _real_valkey_exact_scale(evidence, scale)
    valkey_9_1 = isinstance(evidence, dict) and any(str(version).startswith("9.1.") for version in evidence.get("valkey_versions", []))
    best_checks: dict[str, bool] = {
        "command_audit_summary_present": False,
        "command_audit_summary_schema_valid": False,
        "command_log_present": False,
        "command_log_non_empty": False,
        "command_log_schema_valid": False,
        "required_command_kinds_present": False,
        "no_placeholder_commands": False,
        "command_kind_argv_consistent": False,
        "command_output_refs_present": False,
        "output_hashes_verified": False,
        "retry_failure_timeout_summary_present": False,
        "operation_traceability_present": False,
        "failure_timeout_retry_rows_summarized": False,
        "summary_missing_or_skipped_empty": False,
        "empty_legacy_management_log_absent": False,
    }
    best_reasons: list[str] = []
    best_path: Path | None = None
    best_summary_path: Path | None = None

    command_paths = [path for path in paths if path.suffix == ".jsonl" and "command" in path.name]
    summary_paths = [path for path in paths if path.name == "command_audit_summary.json"]
    non_fixture_command_paths = [path for path in command_paths if not _is_fixture_path(root, path)]
    non_fixture_summary_paths = [path for path in summary_paths if not _is_fixture_path(root, path)]
    grouped_dirs = sorted({path.parent for path in non_fixture_command_paths + non_fixture_summary_paths})
    if not grouped_dirs and (command_paths or summary_paths):
        grouped_dirs = sorted({path.parent for path in command_paths + summary_paths})

    for directory in grouped_dirs:
        candidate_commands = [path for path in command_paths if path.parent == directory]
        candidate_summaries = [path for path in summary_paths if path.parent == directory]
        for command_path in candidate_commands or [None]:
            for summary_path in candidate_summaries or [None]:
                candidate_checks, candidate_reasons = _evaluate_command_audit_artifact_pair(root, command_path, summary_path)
                candidate_score = sum(1 for value in candidate_checks.values() if value)
                best_score = sum(1 for value in best_checks.values() if value)
                if candidate_score > best_score:
                    best_checks = candidate_checks
                    best_reasons = candidate_reasons
                    best_path = command_path
                    best_summary_path = summary_path

    reasons: list[str] = []
    if not command_paths:
        reasons.append("M1-format command log is missing for this exact-scale command audit claim.")
    elif not non_fixture_command_paths:
        reasons.append("Only fixture command logs were found; fixtures cannot satisfy exact-scale command audit.")
    if not summary_paths:
        reasons.append("M1-format command_audit_summary.json is missing for this exact-scale command audit claim.")
    elif not non_fixture_summary_paths:
        reasons.append("Only fixture command_audit_summary.json artifacts were found; fixtures cannot satisfy exact-scale command audit.")
    empty_management_reasons = _empty_management_command_log_reasons(root, non_fixture_command_paths)
    if grouped_dirs:
        best_checks["empty_legacy_management_log_absent"] = not empty_management_reasons
    reasons.extend(best_reasons)
    reasons.extend(empty_management_reasons)
    if not real_exact:
        observed = evidence.get("nodes_observed") if isinstance(evidence, dict) else None
        reasons.append(f"Real Valkey evidence is not an exact-scale PASS for {scale} nodes (nodes_observed={observed!r}).")
    if not valkey_9_1:
        reasons.append("Real Valkey evidence does not prove a Valkey 9.1.x version.")

    checks = {
        **best_checks,
        "real_valkey_exact_scale": real_exact,
        "valkey_9_1_verified": valkey_9_1,
    }
    accepted = real_exact and valkey_9_1 and all(best_checks.values())
    return {
        "accepted": accepted,
        "checks": checks,
        "reasons": _dedupe(reasons),
        "artifact_path": relpath(root, best_path) if best_path else None,
        "summary_path": relpath(root, best_summary_path) if best_summary_path else None,
        "required_command_kinds": sorted(C07_REQUIRED_COMMAND_KINDS),
    }


def _evaluate_command_audit_artifact_pair(root: Path, command_path: Path | None, summary_path: Path | None) -> tuple[dict[str, bool], list[str]]:
    rows, jsonl_reasons = _read_command_jsonl_strict(root, command_path)
    summary = read_json(summary_path) if summary_path else {}
    row_reasons = _command_row_reasons(root, command_path, rows)
    output_reasons = _output_hash_reasons(root, command_path, rows)
    kind_reasons = _command_kind_argv_reasons(rows)
    summary_reasons = _command_summary_reasons(root, summary_path, summary, rows)
    summary_schema_reasons = _command_summary_schema_reasons(root, summary_path, summary)
    summary_missing_reasons = _summary_missing_or_skipped_reasons(summary)
    event_summary_reasons = _failure_timeout_retry_rows_summarized_reasons(summary, rows)
    observed_kinds = {str(row.get("command_kind")) for row in rows if isinstance(row, dict)}
    checks = {
        "command_audit_summary_present": isinstance(summary, dict)
        and summary.get("artifact_type") == "command_audit_summary"
        and summary_path is not None
        and not _is_fixture_path(root, summary_path),
        "command_audit_summary_schema_valid": isinstance(summary, dict) and not summary_schema_reasons,
        "command_log_present": command_path is not None and not _is_fixture_path(root, command_path),
        "command_log_non_empty": bool(rows),
        "command_log_schema_valid": bool(rows) and not row_reasons and not jsonl_reasons,
        "required_command_kinds_present": C07_REQUIRED_COMMAND_KINDS.issubset(observed_kinds),
        "no_placeholder_commands": bool(rows) and not _placeholder_command_reasons(rows),
        "command_kind_argv_consistent": bool(rows) and not kind_reasons,
        "command_output_refs_present": bool(rows) and all(_row_has_output_refs(row) for row in rows if isinstance(row, dict)),
        "output_hashes_verified": bool(rows) and not output_reasons,
        "retry_failure_timeout_summary_present": not _summary_count_reasons(summary, rows),
        "operation_traceability_present": not _operation_traceability_reasons(summary, rows),
        "failure_timeout_retry_rows_summarized": not event_summary_reasons,
        "summary_missing_or_skipped_empty": not summary_missing_reasons,
        "empty_legacy_management_log_absent": True,
    }
    reasons: list[str] = []
    if command_path is None:
        reasons.append("command_log.jsonl, management_command_log.jsonl, or fault_command_log.jsonl is missing.")
    elif _is_fixture_path(root, command_path):
        reasons.append(f"{relpath(root, command_path)} is fixture evidence and cannot satisfy exact-scale command audit.")
    if summary_path is None:
        reasons.append("command_audit_summary.json is missing.")
    elif _is_fixture_path(root, summary_path):
        reasons.append(f"{relpath(root, summary_path)} is fixture evidence and cannot satisfy exact-scale command audit.")
    if command_path is not None and not rows:
        reasons.append(f"{relpath(root, command_path)} has no command rows.")
    absent = sorted(C07_REQUIRED_COMMAND_KINDS - observed_kinds)
    if absent:
        reasons.append(f"Command log is missing required C07 command kinds: {', '.join(absent)}.")
    reasons.extend(row_reasons)
    reasons.extend(jsonl_reasons)
    reasons.extend(_placeholder_command_reasons(rows))
    reasons.extend(kind_reasons)
    reasons.extend(output_reasons)
    reasons.extend(summary_reasons)
    reasons.extend(summary_schema_reasons)
    reasons.extend(summary_missing_reasons)
    reasons.extend(event_summary_reasons)
    return checks, _dedupe(reasons)


def _command_row_reasons(root: Path, command_path: Path | None, rows: list[Any]) -> list[str]:
    if not command_path:
        return []
    reasons: list[str] = []
    schema = _read_artifact_schema(root, "command_log_entry.schema.json")
    for index, row in enumerate(rows):
        prefix = f"{relpath(root, command_path)} line {index + 1}"
        if not isinstance(row, dict):
            reasons.append(f"{prefix} is not a JSON object.")
            continue
        if isinstance(schema, dict):
            reasons.extend(f"{prefix} schema: {error}" for error in _validate_json_schema(row, schema))
        missing = sorted(field for field in C07_COMMAND_ROW_REQUIRED_FIELDS if field not in row)
        if missing:
            reasons.append(f"{prefix} is missing schema fields: {', '.join(missing[:8])}.")
        for field in sorted(C07_COMMAND_ROW_REQUIRED_FIELDS):
            if field in row and _is_missing_placeholder(row.get(field)) and not (field == "error_type" and row.get(field) == ""):
                reasons.append(f"{prefix} required field {field} is MISSING or SKIPPED_WITH_REASON.")
        if row.get("schema_version") != "v1":
            reasons.append(f"{prefix} schema_version is not v1.")
        if row.get("artifact_type") != "runtime_command_log_entry":
            reasons.append(f"{prefix} artifact_type is not runtime_command_log_entry.")
        if not (isinstance(row.get("command_id"), str) and row["command_id"].startswith("cmd-")):
            reasons.append(f"{prefix} command_id {row.get('command_id')!r} is not M1 command-log format.")
        if not (isinstance(row.get("command_id"), str) and re.fullmatch(r"cmd-[0-9]{6}", row["command_id"])):
            reasons.append(f"{prefix} command_id {row.get('command_id')!r} does not match cmd-000000 format.")
        if row.get("status") not in {"PASS", "FAIL", "TIMEOUT", "RETRY", "SKIPPED_WITH_REASON", "MISSING"}:
            reasons.append(f"{prefix} status {row.get('status')!r} is not a valid command status.")
        if row.get("host_network_mutated") is not False or row.get("global_firewall_mutated") is not False:
            reasons.append(f"{prefix} reports forbidden host/global network mutation.")
        if not isinstance(row.get("argv"), list) or not row.get("argv"):
            reasons.append(f"{prefix} argv is missing or empty.")
        for numeric_field in ["started_at_unix_ms", "ended_at_unix_ms", "duration_ms", "retry_index", "timeout_ms"]:
            if numeric_field in row and not _is_non_negative_number(row.get(numeric_field)):
                reasons.append(f"{prefix} {numeric_field} is non-numeric.")
        for integer_field in ["started_at_unix_ms", "ended_at_unix_ms", "retry_index", "timeout_ms"]:
            if integer_field in row and not (isinstance(row.get(integer_field), int) and not isinstance(row.get(integer_field), bool)):
                reasons.append(f"{prefix} {integer_field} must be an integer.")
        if _is_non_negative_number(row.get("started_at_unix_ms")) and _is_non_negative_number(row.get("ended_at_unix_ms")):
            if float(row["ended_at_unix_ms"]) < float(row["started_at_unix_ms"]):
                reasons.append(f"{prefix} ended_at_unix_ms is earlier than started_at_unix_ms.")
        for hash_field in ["stdout_sha256", "stderr_sha256"]:
            value = row.get(hash_field)
            if not (isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)):
                reasons.append(f"{prefix} {hash_field} is missing or invalid.")
    return reasons


def _read_command_jsonl_strict(root: Path, command_path: Path | None) -> tuple[list[Any], list[str]]:
    if command_path is None:
        return [], []
    try:
        lines = command_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"{relpath(root, command_path)} could not be read: {exc}."]
    rows: list[Any] = []
    reasons: list[str] = []
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            reasons.append(f"{relpath(root, command_path)} line {line_no} is invalid JSON: {exc.msg}.")
            continue
        if not isinstance(value, dict):
            reasons.append(f"{relpath(root, command_path)} line {line_no} is not a JSON object.")
            rows.append(value)
            continue
        rows.append(value)
    return rows, reasons


def _command_summary_reasons(root: Path, summary_path: Path | None, summary: Any, rows: list[Any]) -> list[str]:
    if summary_path is None:
        return []
    prefix = relpath(root, summary_path)
    if not isinstance(summary, dict):
        return [f"{prefix} is not readable JSON."]
    reasons: list[str] = []
    required = {
        "schema_version",
        "artifact_type",
        "phase_id",
        "run_id",
        "status",
        "command_log_ref",
        "total_commands",
        "pass_count",
        "failure_count",
        "timeout_count",
        "retry_count",
        "slowest_commands_topN",
        "failed_commands",
        "retry_commands",
        "operation_traceability",
        "coverage",
        "missing_or_skipped",
    }
    missing = sorted(field for field in required if field not in summary)
    if missing:
        reasons.append(f"{prefix} is missing schema fields: {', '.join(missing)}.")
    if summary.get("artifact_type") != "command_audit_summary":
        reasons.append(f"{prefix} artifact_type is not command_audit_summary.")
    if summary.get("status") != "PASS":
        reasons.append(f"{prefix} status {summary.get('status')!r} is not PASS.")
    reasons.extend(_summary_count_reasons(summary, rows))
    reasons.extend(_operation_traceability_reasons(summary, rows))
    if rows and not summary.get("slowest_commands_topN"):
        reasons.append(f"{prefix} slowest_commands_topN is empty despite command rows.")
    return reasons


def _command_summary_schema_reasons(root: Path, summary_path: Path | None, summary: Any) -> list[str]:
    if summary_path is None:
        return ["command_audit_summary.json is missing, so summary schema cannot be validated."]
    if not isinstance(summary, dict):
        return [f"{relpath(root, summary_path)} is not readable JSON."]
    schema = _read_artifact_schema(root, "command_audit_summary.schema.json")
    if not isinstance(schema, dict):
        return ["schemas/artifact/command_audit_summary.schema.json is missing or invalid."]
    return [f"{relpath(root, summary_path)} schema: {error}" for error in _validate_json_schema(summary, schema)]


def _read_artifact_schema(root: Path, name: str) -> Any:
    local = root / "schemas" / "artifact" / name
    if local.exists():
        return read_json(local)
    return read_json(REPO_ROOT / "schemas" / "artifact" / name)


def _schema_reasons(root: Path, path: Path | None, payload: Any, schema_name: str, *, label: str | None = None) -> list[str]:
    if path is None:
        return [f"{schema_name} cannot be validated because its artifact is missing."]
    schema = _read_artifact_schema(root, schema_name)
    if not isinstance(schema, dict):
        return [f"schemas/artifact/{schema_name} is missing or invalid."]
    prefix = relpath(root, path)
    if label:
        prefix = f"{prefix} {label}"
    return [f"{prefix} schema: {error}" for error in _validate_json_schema(payload, schema)]


def evaluate_management_matrix_claim(root: Path, scale: int, paths: list[Path], evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    non_fixture_paths = [path for path in paths if not _is_fixture_path(root, path)]
    candidate_dirs = sorted({path.parent for path in non_fixture_paths}) or sorted({path.parent for path in paths})
    best: dict[str, Any] | None = None
    for directory in candidate_dirs:
        bundle_paths = [path for path in paths if path.parent == directory]
        candidate = _evaluate_management_matrix_bundle(root, scale, bundle_paths)
        if best is None or _management_score(candidate["checks"]) > _management_score(best["checks"]):
            best = candidate
    if best is None:
        evidence = evidence if isinstance(evidence, dict) else _best_evidence(root, paths)
        real_exact = _real_valkey_exact_scale(evidence, scale)
        valkey_9_1 = isinstance(evidence, dict) and any(str(version).startswith("9.1.") for version in evidence.get("valkey_versions", []))
        checks = {
            "management_matrix_present": False,
            "management_matrix_schema_valid": False,
            "management_matrix_status_pass": False,
            "management_required_operations_present": False,
            "operation_results_present": False,
            "operation_results_schema_valid": False,
            "operation_results_exact_scale": False,
            "operation_semantics_present": False,
            "topology_refs_resolve": False,
            "topology_diff_present": False,
            "topology_diff_schema_valid": False,
            "topology_diff_refs_resolve": False,
            "workload_telemetry_present": False,
            "workload_artifacts_schema_valid": False,
            "workload_metrics_numeric": False,
            "workload_refs_resolve": False,
            "command_refs_resolve": False,
            "command_refs_c07_valid": False,
            "command_refs_operation_traceable": False,
            "topology_exact_health": False,
            "no_fixture_management_artifacts": False,
            "real_valkey_exact_scale": real_exact,
            "valkey_9_1_verified": valkey_9_1,
        }
        return {
            "accepted": False,
            "checks": checks,
            "reasons": ["No management matrix artifact bundle was found for this exact-scale claim."],
            "matrix_path": None,
            "results_path": None,
            "required_operations": sorted(H05_REQUIRED_MANAGEMENT_OPERATIONS),
        }
    return best


def _management_score(checks: dict[str, bool]) -> int:
    return sum(1 for value in checks.values() if value is True)


def _evaluate_management_matrix_bundle(root: Path, scale: int, paths: list[Path]) -> dict[str, Any]:
    evidence = _best_evidence(root, paths)
    real_exact = _real_valkey_exact_scale(evidence, scale)
    valkey_9_1 = isinstance(evidence, dict) and any(str(version).startswith("9.1.") for version in evidence.get("valkey_versions", []))
    non_fixture_paths = [path for path in paths if not _is_fixture_path(root, path)]
    by_name = {path.name: path for path in non_fixture_paths}
    matrix_path = by_name.get("management_ops_matrix.json")
    results_path = by_name.get("management_operation_results.jsonl")
    topology_path = by_name.get("management_topology_snapshots.jsonl")
    topology_diff_path = by_name.get("management_topology_diffs.jsonl")
    impact_path = by_name.get("management_workload_impact.json")
    workload_windows_path = by_name.get("workload_windows.json")
    command_log_path = by_name.get("management_command_log.jsonl")

    matrix = read_json(matrix_path) if matrix_path else {}
    results = _read_management_jsonl_strict(root, results_path)[0] if results_path else []
    result_jsonl_reasons = _read_management_jsonl_strict(root, results_path)[1] if results_path else []
    topology_rows, topology_reasons = _read_management_jsonl_strict(root, topology_path)
    topology_diff_rows, topology_diff_jsonl_reasons = _read_management_jsonl_strict(root, topology_diff_path)
    command_rows, command_reasons = _read_command_jsonl_strict(root, command_log_path)
    impact = read_json(impact_path) if impact_path else {}
    workload_windows = read_json(workload_windows_path) if workload_windows_path else {}

    reasons: list[str] = []
    if not matrix_path:
        reasons.append("management_ops_matrix.json is missing for this exact-scale management claim.")
    if not results_path:
        reasons.append("management_operation_results.jsonl is missing for this exact-scale management claim.")
    if not topology_path:
        reasons.append("management_topology_snapshots.jsonl is missing for this exact-scale management claim.")
    if not topology_diff_path:
        reasons.append("management_topology_diffs.jsonl is missing for this exact-scale management claim.")
    if not impact_path:
        reasons.append("management_workload_impact.json is missing for this exact-scale management claim.")
    if not workload_windows_path:
        reasons.append("workload_windows.json is missing for this exact-scale management claim.")
    if not command_log_path:
        reasons.append("management_command_log.jsonl is missing for this exact-scale management claim.")
    has_fixture = any(_is_fixture_path(root, path) for path in paths)
    has_non_fixture = any(not _is_fixture_path(root, path) for path in paths)
    if has_fixture and not has_non_fixture:
        reasons.append("Fixture management artifacts were found and cannot satisfy exact-scale management matrix.")

    matrix_checks, matrix_reasons = _management_matrix_reasons(root, matrix_path, matrix, scale)
    result_checks, result_reasons = _management_result_reasons(root, results_path, results, scale)
    topology_ok, topology_health_ok, topology_ref_reasons = _management_topology_ref_reasons(results, topology_rows, scale)
    matrix_operations = matrix.get("operations", []) if isinstance(matrix, dict) and isinstance(matrix.get("operations"), list) else []
    topology_diff_ok, topology_diff_schema_ok, topology_diff_ref_ok, topology_diff_reasons = _management_topology_diff_reasons(root, topology_diff_path, topology_diff_rows, results, matrix_operations)
    workload_ok, workload_metrics_ok, workload_schema_ok, workload_reasons = _management_workload_reasons(root, impact_path, impact, workload_windows_path, workload_windows, results)
    command_ok, command_c07_ok, command_trace_ok, command_ref_reasons = _management_command_ref_reasons(root, command_log_path, command_rows, matrix, results)
    reasons.extend(matrix_reasons)
    reasons.extend(result_reasons)
    reasons.extend(result_jsonl_reasons)
    reasons.extend(topology_reasons)
    reasons.extend(topology_diff_jsonl_reasons)
    reasons.extend(topology_diff_reasons)
    reasons.extend(workload_reasons)
    reasons.extend(command_reasons)
    reasons.extend(command_ref_reasons)
    reasons.extend(topology_ref_reasons)
    if not real_exact:
        observed = evidence.get("nodes_observed") if isinstance(evidence, dict) else None
        reasons.append(f"Real Valkey evidence is not an exact-scale PASS for {scale} nodes (nodes_observed={observed!r}).")
    if not valkey_9_1:
        reasons.append("Real Valkey evidence does not prove a Valkey 9.1.x version.")

    checks = {
        **matrix_checks,
        **result_checks,
        "topology_refs_resolve": topology_ok,
        "topology_diff_present": topology_diff_ok,
        "topology_diff_schema_valid": topology_diff_schema_ok,
        "topology_diff_refs_resolve": topology_diff_ref_ok,
        "workload_telemetry_present": bool(impact_path and workload_windows_path),
        "workload_artifacts_schema_valid": workload_schema_ok,
        "workload_metrics_numeric": workload_metrics_ok,
        "workload_refs_resolve": workload_ok,
        "command_refs_resolve": command_ok,
        "command_refs_c07_valid": command_c07_ok,
        "command_refs_operation_traceable": command_trace_ok,
        "topology_exact_health": topology_health_ok,
        "no_fixture_management_artifacts": not has_fixture or has_non_fixture,
        "real_valkey_exact_scale": real_exact,
        "valkey_9_1_verified": valkey_9_1,
    }
    accepted = real_exact and valkey_9_1 and all(checks.values())
    return {
        "accepted": accepted,
        "checks": checks,
        "reasons": _dedupe(reasons),
        "matrix_path": relpath(root, matrix_path) if matrix_path else None,
        "results_path": relpath(root, results_path) if results_path else None,
        "required_operations": sorted(H05_REQUIRED_MANAGEMENT_OPERATIONS),
    }


def evaluate_workload_benchmark_claim(root: Path, scale: int, paths: list[Path]) -> dict[str, Any]:
    non_fixture_paths = [path for path in paths if not _is_fixture_path(root, path)]
    candidate_dirs = sorted({path.parent for path in non_fixture_paths}) or sorted({path.parent for path in paths})
    best: dict[str, Any] | None = None
    for directory in candidate_dirs:
        bundle_paths = [path for path in paths if path.parent == directory]
        candidate = _evaluate_workload_benchmark_bundle(root, scale, bundle_paths)
        if best is None or _workload_score(candidate["checks"]) > _workload_score(best["checks"]):
            best = candidate
    if best is not None:
        return best
    checks = _empty_workload_checks(_real_valkey_exact_scale({}, scale), False)
    return {
        "accepted": False,
        "checks": checks,
        "reasons": ["No same-directory workload benchmark artifact bundle was found for this exact-scale claim."],
        "workload_windows_path": None,
        "metrics_path": None,
        "required_profiles": H06_REQUIRED_WORKLOAD_PROFILES,
        "required_windows": H06_REQUIRED_WORKLOAD_WINDOWS,
        "required_metrics": H06_REQUIRED_WORKLOAD_METRICS,
        "minimum_metric_rows": H06_REQUIRED_METRIC_ROW_COUNT,
        "minimum_operations_per_window": H06_MIN_OPERATIONS_PER_WINDOW,
    }


def _workload_score(checks: dict[str, bool]) -> int:
    return sum(1 for value in checks.values() if value is True)


def _empty_workload_checks(real_exact: bool, valkey_9_1: bool) -> dict[str, bool]:
    return {
        "workload_windows_present": False,
        "workload_windows_schema_valid": False,
        "workload_windows_status_pass": False,
        "workload_profiles_complete": False,
        "workload_windows_complete": False,
        "workload_required_metrics_numeric": False,
        "metrics_timeseries_present": False,
        "metrics_timeseries_schema_valid": False,
        "metrics_row_count_sufficient": False,
        "metrics_rows_cover_required_matrix": False,
        "metrics_core_values_numeric": False,
        "operations_per_window_sufficient": False,
        "connection_evidence_observed": False,
        "pipeline_evidence_observed": False,
        "full_slot_coverage_non_smoke": False,
        "fake_or_partial_not_promoted": False,
        "no_fixture_workload_artifacts": False,
        "real_valkey_exact_scale": real_exact,
        "valkey_9_1_verified": valkey_9_1,
    }


def _evaluate_workload_benchmark_bundle(root: Path, scale: int, paths: list[Path]) -> dict[str, Any]:
    evidence = _best_evidence(root, paths)
    real_exact = _real_valkey_exact_scale(evidence, scale)
    valkey_9_1 = isinstance(evidence, dict) and any(str(version).startswith("9.1.") for version in evidence.get("valkey_versions", []))
    non_fixture_paths = [path for path in paths if not _is_fixture_path(root, path)]
    by_name = {path.name: path for path in non_fixture_paths}
    workload_path = by_name.get("workload_windows.json")
    metrics_path = by_name.get("metrics_timeseries.jsonl")
    workload = read_json(workload_path) if workload_path else {}
    metric_rows, metric_jsonl_reasons = _read_workload_jsonl_strict(root, metrics_path)

    reasons: list[str] = []
    has_fixture = any(_is_fixture_path(root, path) for path in paths)
    has_non_fixture = bool(non_fixture_paths)
    if not workload_path:
        reasons.append("workload_windows.json is missing from the same directory as exact-scale workload benchmark evidence.")
    if not metrics_path:
        reasons.append("metrics_timeseries.jsonl is missing from the same directory as exact-scale workload benchmark evidence.")
    if not any(path.name == "valkey_e2e_evidence.json" and not _is_fixture_path(root, path) for path in paths):
        reasons.append("valkey_e2e_evidence.json is missing from the same directory as workload benchmark artifacts.")
    if has_fixture and not has_non_fixture:
        reasons.append("Only fixture workload benchmark artifacts were found; fixtures cannot satisfy exact-scale workload benchmark.")

    schema_reasons = _schema_reasons(root, workload_path, workload, "workload_windows.schema.json")
    metric_schema_reasons: list[str] = []
    for index, row in enumerate(metric_rows):
        metric_schema_reasons.extend(_schema_reasons(root, metrics_path, row, "goal_loop_metric_sample.schema.json", label=f"row {index + 1}"))
    window_checks, window_reasons = _workload_window_reasons(root, workload_path, workload, scale)
    metric_checks, metric_reasons, metric_stats = _workload_metric_row_reasons(root, metrics_path, metric_rows)
    connection_ok = _workload_observed_connection_evidence(workload, metric_rows)
    pipeline_ok = _workload_observed_pipeline_evidence(workload, metric_rows)
    fake_partial_reasons = _workload_fake_or_partial_reasons(root, paths, workload, metric_rows)

    reasons.extend(schema_reasons)
    reasons.extend(metric_jsonl_reasons)
    reasons.extend(metric_schema_reasons)
    reasons.extend(window_reasons)
    reasons.extend(metric_reasons)
    reasons.extend(fake_partial_reasons)
    if not connection_ok:
        reasons.append("Observed connection evidence is missing; config-only connection settings cannot satisfy H06.")
    if not pipeline_ok:
        reasons.append("Observed pipeline evidence is missing; config-only pipeline settings cannot satisfy H06.")
    if not real_exact:
        observed = evidence.get("nodes_observed") if isinstance(evidence, dict) else None
        reasons.append(f"Real Valkey evidence is not an exact-scale PASS for {scale} nodes (nodes_observed={observed!r}).")
    if not valkey_9_1:
        reasons.append("Real Valkey evidence does not prove a Valkey 9.1.x version.")

    checks = {
        "workload_windows_present": workload_path is not None and isinstance(workload, dict) and not _is_fixture_path(root, workload_path),
        "workload_windows_schema_valid": not schema_reasons,
        **window_checks,
        "metrics_timeseries_present": metrics_path is not None and bool(metric_rows) and not _is_fixture_path(root, metrics_path),
        "metrics_timeseries_schema_valid": bool(metric_rows) and not metric_jsonl_reasons and not metric_schema_reasons,
        **metric_checks,
        "connection_evidence_observed": connection_ok,
        "pipeline_evidence_observed": pipeline_ok,
        "fake_or_partial_not_promoted": not fake_partial_reasons,
        "no_fixture_workload_artifacts": not has_fixture or has_non_fixture,
        "real_valkey_exact_scale": real_exact,
        "valkey_9_1_verified": valkey_9_1,
    }
    accepted = real_exact and valkey_9_1 and all(checks.values())
    return {
        "accepted": accepted,
        "checks": checks,
        "reasons": _dedupe(reasons),
        "workload_windows_path": relpath(root, workload_path) if workload_path else None,
        "metrics_path": relpath(root, metrics_path) if metrics_path else None,
        "metric_row_count": metric_stats["core_row_count"],
        "minimum_metric_rows": H06_REQUIRED_METRIC_ROW_COUNT,
        "minimum_operations_per_window": H06_MIN_OPERATIONS_PER_WINDOW,
        "required_profiles": H06_REQUIRED_WORKLOAD_PROFILES,
        "required_windows": H06_REQUIRED_WORKLOAD_WINDOWS,
        "required_metrics": H06_REQUIRED_WORKLOAD_METRICS,
    }


def _workload_window_reasons(root: Path, path: Path | None, workload: Any, scale: int) -> tuple[dict[str, bool], list[str]]:
    reasons: list[str] = []
    if not isinstance(workload, dict):
        return {
            "workload_windows_status_pass": False,
            "workload_profiles_complete": False,
            "workload_windows_complete": False,
            "workload_required_metrics_numeric": False,
            "operations_per_window_sufficient": False,
            "full_slot_coverage_non_smoke": False,
        }, ["workload_windows.json is missing or invalid JSON."]
    if workload.get("status") != "PASS":
        reasons.append(f"workload_windows.json status {workload.get('status')!r} is not PASS.")
    windows = workload.get("windows")
    if not isinstance(windows, list) or not windows:
        reasons.append("workload_windows.json windows is missing or empty.")
        windows = []
    profiles_covered = {str(item) for item in workload.get("profiles_covered", []) if isinstance(item, str)}
    profile_windows: dict[tuple[str, str], dict[str, Any]] = {}
    observed_profiles: set[str] = set(profiles_covered)
    metrics_numeric_ok = True
    operations_ok = True
    full_slot_ok = True
    for index, item in enumerate(windows):
        label = f"workload_windows.json windows[{index}]"
        if not isinstance(item, dict):
            reasons.append(f"{label} is not an object.")
            metrics_numeric_ok = False
            operations_ok = False
            continue
        profile = _workload_profile_from_window(item)
        window_name = str(item.get("window_name", ""))
        if profile:
            observed_profiles.add(profile)
        if profile and window_name:
            profile_windows[(profile, window_name)] = item
        if item.get("status") != "PASS":
            reasons.append(f"{label} status {item.get('status')!r} is not PASS.")
        metrics = item.get("metrics")
        if not isinstance(metrics, dict):
            reasons.append(f"{label} metrics is missing or not an object.")
            metrics_numeric_ok = False
            operations_ok = False
            continue
        for metric in H06_REQUIRED_WORKLOAD_METRICS:
            value = metrics.get(metric)
            if not _is_non_negative_number(value):
                metrics_numeric_ok = False
                if _is_missing_placeholder(value):
                    reasons.append(f"{label} metric {metric} is MISSING or SKIPPED_WITH_REASON.")
                else:
                    reasons.append(f"{label} metric {metric} is missing or non-numeric.")
        ok_ops = metrics.get("ok_ops")
        error_ops = metrics.get("error_ops")
        if _is_non_negative_number(ok_ops) and _is_non_negative_number(error_ops):
            if float(ok_ops) + float(error_ops) < H06_MIN_OPERATIONS_PER_WINDOW:
                operations_ok = False
                reasons.append(f"{label} operations {float(ok_ops) + float(error_ops):g} is below H06 minimum {H06_MIN_OPERATIONS_PER_WINDOW}.")
        else:
            operations_ok = False
        if profile in set(H06_REQUIRED_WORKLOAD_PROFILES) - {"smoke"}:
            coverage = item.get("key_slot_coverage") if isinstance(item.get("key_slot_coverage"), dict) else {}
            if not _coverage_is_full_slot(coverage):
                full_slot_ok = False
                reasons.append(f"{label} profile {profile} lacks full-slot coverage.")
    missing_profiles = sorted(set(H06_REQUIRED_WORKLOAD_PROFILES) - observed_profiles)
    if missing_profiles:
        reasons.append(f"workload benchmark is missing required profiles: {', '.join(missing_profiles)}.")
    missing_windows: list[str] = []
    for profile in H06_REQUIRED_WORKLOAD_PROFILES:
        for window_name in H06_REQUIRED_WORKLOAD_WINDOWS:
            if (profile, window_name) not in profile_windows:
                missing_windows.append(f"{profile}:{window_name}")
    if missing_windows:
        reasons.append(f"workload benchmark is missing required profile windows: {', '.join(missing_windows[:12])}.")
    coverage_by_profile = workload.get("hash_slot_coverage") if isinstance(workload.get("hash_slot_coverage"), dict) else {}
    for profile in H06_REQUIRED_WORKLOAD_PROFILES:
        if profile == "smoke":
            continue
        coverage = coverage_by_profile.get(profile) if isinstance(coverage_by_profile, dict) else None
        if not _coverage_is_full_slot(coverage):
            full_slot_ok = False
            reasons.append(f"workload profile {profile} lacks top-level full-slot coverage.")
    return {
        "workload_windows_status_pass": workload.get("status") == "PASS",
        "workload_profiles_complete": not missing_profiles,
        "workload_windows_complete": not missing_windows,
        "workload_required_metrics_numeric": metrics_numeric_ok and bool(windows),
        "operations_per_window_sufficient": operations_ok and bool(windows),
        "full_slot_coverage_non_smoke": full_slot_ok and bool(windows),
    }, _dedupe(reasons)


def _workload_metric_row_reasons(root: Path, path: Path | None, rows: list[Any]) -> tuple[dict[str, bool], list[str], dict[str, int]]:
    reasons: list[str] = []
    required_pairs = {
        (profile, window_name, metric)
        for profile in H06_REQUIRED_WORKLOAD_PROFILES
        for window_name in H06_REQUIRED_WORKLOAD_WINDOWS
        for metric in H06_REQUIRED_WORKLOAD_METRICS
    }
    observed_pairs: set[tuple[str, str, str]] = set()
    core_row_count = 0
    values_numeric_ok = True
    for index, row in enumerate(rows):
        label = f"{relpath(root, path) if path else 'metrics_timeseries.jsonl'} line {index + 1}"
        if not isinstance(row, dict):
            reasons.append(f"{label} is not a JSON object.")
            values_numeric_ok = False
            continue
        metric = str(row.get("metric_name", ""))
        if metric not in H06_REQUIRED_WORKLOAD_METRICS:
            continue
        profile = _workload_profile_from_metric_row(row)
        window_name = _workload_window_from_metric_row(row)
        value = row.get("metric_value")
        core_row_count += 1
        if profile and window_name:
            observed_pairs.add((profile, window_name, metric))
        if not _is_non_negative_number(value):
            values_numeric_ok = False
            if _is_missing_placeholder(value) or str(row.get("missing_reason", "")).strip():
                reasons.append(f"{label} {profile}:{window_name}:{metric} is MISSING or SKIPPED_WITH_REASON.")
            else:
                reasons.append(f"{label} {profile}:{window_name}:{metric} metric_value is missing or non-numeric.")
    missing_pairs = sorted(required_pairs - observed_pairs)
    if missing_pairs:
        formatted = [":".join(item) for item in missing_pairs[:12]]
        reasons.append(f"metrics_timeseries.jsonl is missing required metric rows: {', '.join(formatted)}.")
    if core_row_count < H06_REQUIRED_METRIC_ROW_COUNT:
        reasons.append(f"metrics_timeseries.jsonl has {core_row_count} H06 core metric rows but requires at least {H06_REQUIRED_METRIC_ROW_COUNT}.")
    return {
        "metrics_row_count_sufficient": core_row_count >= H06_REQUIRED_METRIC_ROW_COUNT,
        "metrics_rows_cover_required_matrix": not missing_pairs,
        "metrics_core_values_numeric": values_numeric_ok and bool(rows),
    }, _dedupe(reasons), {"core_row_count": core_row_count}


def _read_workload_jsonl_strict(root: Path, path: Path | None) -> tuple[list[Any], list[str]]:
    if path is None:
        return [], []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"{relpath(root, path)} could not be read: {exc}."]
    rows: list[Any] = []
    reasons: list[str] = []
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            reasons.append(f"{relpath(root, path)} line {line_no} is invalid JSON: {exc.msg}.")
            continue
        if not isinstance(value, dict):
            reasons.append(f"{relpath(root, path)} line {line_no} is not a JSON object.")
        rows.append(value)
    return rows, reasons


def _workload_profile_from_window(item: dict[str, Any]) -> str:
    profile = item.get("profile")
    return str(profile) if isinstance(profile, str) and profile else ""


def _workload_profile_from_metric_row(row: dict[str, Any]) -> str:
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    profile = labels.get("profile")
    if isinstance(profile, str) and profile:
        return profile
    source_id = row.get("source_id")
    if isinstance(source_id, str) and ":" in source_id:
        return source_id.split(":", 1)[0]
    return ""


def _workload_window_from_metric_row(row: dict[str, Any]) -> str:
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    window_name = labels.get("window_name")
    if isinstance(window_name, str) and window_name:
        return window_name
    source_id = row.get("source_id")
    if isinstance(source_id, str) and ":" in source_id:
        return source_id.split(":", 1)[1]
    return ""


def _coverage_is_full_slot(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("fixed_hash_tag_only") is True:
        return False
    if value.get("hash_slot_distribution") in {"single_tag", "fixed_hash_tag"}:
        return False
    return value.get("full_slot_requested") is True and value.get("full_slot_covered") is True and value.get("slot_count_observed") == 16384


def _workload_observed_connection_evidence(workload: Any, rows: list[Any]) -> bool:
    return _observed_evidence(workload, rows, top_keys=("observed_connections", "connections_observed"), evidence_key="connection_evidence", row_metrics={"observed_connections", "connections_observed", "active_connections", "client_connections"})


def _workload_observed_pipeline_evidence(workload: Any, rows: list[Any]) -> bool:
    return _observed_evidence(workload, rows, top_keys=("observed_pipeline", "pipeline_observed", "max_pipeline_depth_observed"), evidence_key="pipeline_evidence", row_metrics={"observed_pipeline", "pipeline_observed", "pipeline_depth_observed", "max_pipeline_depth_observed"})


def _workload_fake_or_partial_reasons(root: Path, paths: list[Path], workload: Any, rows: list[Any]) -> list[str]:
    reasons: list[str] = []
    if _contains_fake_or_partial(root, paths):
        reasons.append("Workload benchmark source path contains fake, partial, or fixture marker.")
    payloads: list[Any] = [workload, *rows]
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in ["status", "evidence_kind", "evidence_class", "source_kind", "workload_mode"]:
            value = payload.get(key)
            if isinstance(value, str) and value.upper() in {"FAKE", "PARTIAL"}:
                reasons.append(f"Workload benchmark artifact contains {key}={value!r}; fake or partial evidence cannot promote.")
    return _dedupe(reasons)


def evaluate_fault_timeline_claim(root: Path, scale: int, paths: list[Path]) -> dict[str, Any]:
    non_fixture_paths = [path for path in paths if not _is_fixture_path(root, path)]
    candidate_dirs = sorted({path.parent for path in non_fixture_paths}) or sorted({path.parent for path in paths})
    best: dict[str, Any] | None = None
    for directory in candidate_dirs:
        bundle_paths = [path for path in paths if path.parent == directory]
        candidate = _evaluate_fault_timeline_bundle(root, scale, bundle_paths)
        if best is None or _fault_score(candidate["checks"]) > _fault_score(best["checks"]):
            best = candidate
    if best is not None:
        return best
    return {
        "accepted": False,
        "checks": _empty_fault_checks(False, False),
        "reasons": ["No same-directory C09 fault timeline artifact bundle was found for this exact-scale claim."],
        "report_path": None,
        "events_path": None,
        "samples_path": None,
        "required_fault_types": H07_REQUIRED_FAULT_TYPES,
        "required_timeline_events": H07_REQUIRED_TIMELINE_EVENTS,
        "required_metrics": H07_REQUIRED_TIMELINE_METRICS,
    }


def _fault_score(checks: dict[str, bool]) -> int:
    return sum(1 for value in checks.values() if value is True)


def _empty_fault_checks(real_exact: bool, valkey_9_1: bool) -> dict[str, bool]:
    return {
        "same_directory_bundle": False,
        "fault_timeline_report_present": False,
        "fault_timeline_report_schema_valid": False,
        "fault_timeline_report_status_pass": False,
        "fault_timeline_events_present": False,
        "fault_timeline_events_schema_valid": False,
        "failover_latency_samples_present": False,
        "failover_latency_samples_schema_valid": False,
        "fault_required_types_present": False,
        "fault_required_events_present": False,
        "fault_required_metrics_numeric": False,
        "fault_rows_status_pass": False,
        "fault_rows_exact_scale": False,
        "fault_rows_real_valkey": False,
        "fault_execution_mode_real": False,
        "workload_refs_resolve": False,
        "workload_h06_dependency_accepted": False,
        "cleanup_refs_resolve": False,
        "clean_cluster_evidence": False,
        "no_fixture_fault_artifacts": False,
        "fake_or_partial_not_promoted": False,
        "no_legacy_fault_promotion": False,
        "real_valkey_exact_scale": real_exact,
        "valkey_9_1_verified": valkey_9_1,
    }


def _evaluate_fault_timeline_bundle(root: Path, scale: int, paths: list[Path]) -> dict[str, Any]:
    evidence = _best_evidence(root, paths)
    real_exact = _real_valkey_exact_scale(evidence, scale)
    valkey_9_1 = isinstance(evidence, dict) and any(str(version).startswith("9.1.") for version in evidence.get("valkey_versions", []))
    checks = _empty_fault_checks(real_exact, valkey_9_1)
    non_fixture_paths = [path for path in paths if not _is_fixture_path(root, path)]
    by_name = {path.name: path for path in non_fixture_paths}
    report_path = by_name.get("fault_timeline_report.json")
    events_path = by_name.get("fault_timeline_events.jsonl")
    samples_path = by_name.get("failover_latency_samples.jsonl")
    workload_path = by_name.get("workload_windows.json")
    metrics_path = by_name.get("metrics_timeseries.jsonl")
    cleanup_path = by_name.get("cleanup_report.json")
    valkey_path = by_name.get("valkey_e2e_evidence.json")
    bundle_dir = next(iter(sorted({path.parent for path in paths})), None)
    report = read_json(report_path) if report_path else {}
    events, event_jsonl_reasons = _read_workload_jsonl_strict(root, events_path)
    samples, sample_jsonl_reasons = _read_workload_jsonl_strict(root, samples_path)
    cleanup = read_json(cleanup_path) if cleanup_path else {}
    reasons: list[str] = []
    has_fixture = any(_is_fixture_path(root, path) for path in paths)
    has_non_fixture = bool(non_fixture_paths)

    if not report_path:
        reasons.append("fault_timeline_report.json is missing from the same directory as C09 fault timeline evidence.")
    if not events_path:
        reasons.append("fault_timeline_events.jsonl is missing from the same directory as C09 fault timeline evidence.")
    if not samples_path:
        reasons.append("failover_latency_samples.jsonl is missing from the same directory as C09 fault timeline evidence.")
    if not valkey_path:
        reasons.append("valkey_e2e_evidence.json is missing from the same directory as C09 fault timeline evidence.")
    if not workload_path:
        reasons.append("workload_windows.json is missing from the same directory as C09 fault timeline evidence.")
    if not metrics_path:
        reasons.append("metrics_timeseries.jsonl is missing from the same directory as C09 fault timeline evidence.")
    if not cleanup_path:
        reasons.append("cleanup_report.json is missing from the same directory as C09 fault timeline evidence.")
    if has_fixture and not has_non_fixture:
        reasons.append("Only fixture fault timeline artifacts were found; fixtures cannot satisfy exact-scale C09 fault timeline.")

    report_schema_reasons = _schema_reasons(root, report_path, report, "fault_timeline_report.schema.json")
    event_schema_reasons: list[str] = []
    for index, event in enumerate(events):
        event_schema_reasons.extend(_schema_reasons(root, events_path, event, "fault_timeline_event.schema.json", label=f"row {index + 1}"))
    sample_schema_reasons: list[str] = []
    for index, sample in enumerate(samples):
        sample_schema_reasons.extend(_schema_reasons(root, samples_path, sample, "failover_latency_sample.schema.json", label=f"row {index + 1}"))

    row_checks, row_reasons = _fault_row_reasons(root, scale, bundle_dir, report_path, report, events, samples)
    event_checks, event_reasons = _fault_event_reasons(root, scale, events_path, events, report)
    sample_checks, sample_reasons = _fault_sample_reasons(root, scale, samples_path, samples, report)
    ref_checks, ref_reasons = _fault_ref_reasons(root, scale, bundle_dir, report, cleanup)
    workload_eval = evaluate_workload_benchmark_claim(root, scale, paths)
    cleanup_ok = isinstance(cleanup, dict) and cleanup.get("status") == "PASS" and cleanup.get("resources_remaining") == []
    fake_partial_reasons = _fault_fake_or_partial_reasons(root, paths, report, events, samples)
    legacy_reasons = _fault_legacy_reasons(paths, report, events, samples)

    reasons.extend(report_schema_reasons)
    reasons.extend(event_jsonl_reasons)
    reasons.extend(event_schema_reasons)
    reasons.extend(sample_jsonl_reasons)
    reasons.extend(sample_schema_reasons)
    reasons.extend(row_reasons)
    reasons.extend(event_reasons)
    reasons.extend(sample_reasons)
    reasons.extend(ref_reasons)
    reasons.extend(fake_partial_reasons)
    reasons.extend(legacy_reasons)
    if workload_eval.get("accepted") is not True:
        reasons.append("Same-directory workload refs do not have an accepted H06 workload benchmark dependency.")
        reasons.extend(str(reason) for reason in workload_eval.get("reasons", [])[:12])
    if not cleanup_ok:
        reasons.append("cleanup_report.json must be PASS with an empty resources_remaining array for exact-scale C09 fault timeline PASS.")
    if not real_exact:
        observed = evidence.get("nodes_observed") if isinstance(evidence, dict) else None
        reasons.append(f"Real Valkey evidence is not an exact-scale PASS for {scale} nodes (nodes_observed={observed!r}).")
    if not valkey_9_1:
        reasons.append("Real Valkey evidence does not prove a Valkey 9.1.x version.")

    checks.update(
        {
            "same_directory_bundle": all(path is not None for path in [report_path, events_path, samples_path, workload_path, metrics_path, cleanup_path, valkey_path]),
            "fault_timeline_report_present": report_path is not None and isinstance(report, dict) and not _is_fixture_path(root, report_path),
            "fault_timeline_report_schema_valid": not report_schema_reasons,
            "fault_timeline_report_status_pass": isinstance(report, dict) and report.get("status") == "PASS",
            "fault_timeline_events_present": events_path is not None and bool(events) and not _is_fixture_path(root, events_path),
            "fault_timeline_events_schema_valid": bool(events) and not event_jsonl_reasons and not event_schema_reasons,
            "failover_latency_samples_present": samples_path is not None and bool(samples) and not _is_fixture_path(root, samples_path),
            "failover_latency_samples_schema_valid": bool(samples) and not sample_jsonl_reasons and not sample_schema_reasons and sample_checks["failover_latency_samples_schema_valid"],
            **row_checks,
            **event_checks,
            **ref_checks,
            "fault_execution_mode_real": row_checks["fault_execution_mode_real"] and not any("execution_mode" in reason for reason in event_reasons),
            "workload_h06_dependency_accepted": workload_eval.get("accepted") is True,
            "clean_cluster_evidence": cleanup_ok and ref_checks["clean_cluster_evidence"],
            "no_fixture_fault_artifacts": not has_fixture or has_non_fixture,
            "fake_or_partial_not_promoted": not fake_partial_reasons,
            "no_legacy_fault_promotion": not legacy_reasons,
            "real_valkey_exact_scale": real_exact,
            "valkey_9_1_verified": valkey_9_1,
        }
    )
    accepted = real_exact and valkey_9_1 and all(checks.values())
    return {
        "accepted": accepted,
        "checks": checks,
        "reasons": _dedupe(reasons),
        "report_path": relpath(root, report_path) if report_path else None,
        "events_path": relpath(root, events_path) if events_path else None,
        "samples_path": relpath(root, samples_path) if samples_path else None,
        "workload_h06_acceptance": workload_eval,
        "required_fault_types": H07_REQUIRED_FAULT_TYPES,
        "required_timeline_events": H07_REQUIRED_TIMELINE_EVENTS,
        "required_metrics": H07_REQUIRED_TIMELINE_METRICS,
    }


def _fault_row_reasons(root: Path, scale: int, bundle_dir: Path | None, report_path: Path | None, report: Any, events: list[Any], samples: list[Any]) -> tuple[dict[str, bool], list[str]]:
    reasons: list[str] = []
    rows = report.get("fault_rows") if isinstance(report, dict) else None
    if not isinstance(rows, list) or not rows:
        return {
            "fault_required_types_present": False,
            "fault_required_metrics_numeric": False,
            "fault_rows_status_pass": False,
            "fault_rows_exact_scale": False,
            "fault_rows_real_valkey": False,
            "fault_execution_mode_real": False,
        }, ["fault_timeline_report.json fault_rows must be a non-empty array."]
    observed_fault_types = {str(row.get("fault_type")) for row in rows if isinstance(row, dict)}
    missing_fault_types = sorted(set(H07_REQUIRED_FAULT_TYPES) - observed_fault_types)
    if missing_fault_types:
        reasons.append(f"fault_timeline_report.json is missing required C09 fault types: {', '.join(missing_fault_types)}.")
    event_sample_ids = {str(event.get("sample_id")) for event in events if isinstance(event, dict)}
    sample_ids = {str(sample.get("sample_id")) for sample in samples if isinstance(sample, dict)}
    metrics_ok = True
    rows_status_ok = True
    exact_scale_ok = True
    real_valkey_ok = True
    execution_mode_ok = True
    for index, row in enumerate(rows):
        label = f"fault_timeline_report.json fault_rows[{index}]"
        if not isinstance(row, dict):
            reasons.append(f"{label} is not an object.")
            metrics_ok = False
            rows_status_ok = False
            exact_scale_ok = False
            real_valkey_ok = False
            execution_mode_ok = False
            continue
        sample_id = str(row.get("sample_id", "MISSING"))
        if row.get("status", row.get("timeline_status")) != "PASS" or row.get("timeline_status") != "PASS":
            reasons.append(f"{label} {sample_id} status/timeline_status must both be PASS, not {row.get('status')!r}/{row.get('timeline_status')!r}.")
            rows_status_ok = False
        if row.get("node_count") != scale or row.get("scale_rung") != str(scale):
            reasons.append(f"{label} {sample_id} does not match exact scale {scale}.")
            exact_scale_ok = False
        if row.get("real_valkey") is not True:
            reasons.append(f"{label} {sample_id} real_valkey must be true.")
            real_valkey_ok = False
        mode = row.get("execution_mode")
        if _fault_execution_mode_blocked(mode):
            reasons.append(f"{label} {sample_id} execution_mode {mode!r} is not real C09 execution.")
            execution_mode_ok = False
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            reasons.append(f"{label} {sample_id} metrics must be an object.")
            metrics_ok = False
        else:
            for metric in H07_REQUIRED_TIMELINE_METRICS:
                value = metrics.get(metric)
                if not _is_non_negative_number(value):
                    metrics_ok = False
                    if _is_missing_placeholder(value):
                        reasons.append(f"{label} {sample_id} metric {metric} is MISSING or SKIPPED_WITH_REASON.")
                    else:
                        reasons.append(f"{label} {sample_id} metric {metric} is missing or non-numeric.")
        if sample_id not in event_sample_ids:
            reasons.append(f"{label} {sample_id} has no matching fault_timeline_events.jsonl rows.")
            rows_status_ok = False
        if sample_id not in sample_ids:
            reasons.append(f"{label} {sample_id} has no matching failover_latency_samples.jsonl row.")
            rows_status_ok = False
        for field in ["cleanup_ref", "valkey_e2e_evidence_ref"]:
            if not _ref_resolves_to_bundle_file(root, bundle_dir, row.get(field)):
                reasons.append(f"{label} {sample_id} {field} {row.get(field)!r} does not resolve in the same C09 bundle directory.")
    return {
        "fault_required_types_present": not missing_fault_types,
        "fault_required_metrics_numeric": metrics_ok,
        "fault_rows_status_pass": rows_status_ok,
        "fault_rows_exact_scale": exact_scale_ok,
        "fault_rows_real_valkey": real_valkey_ok,
        "fault_execution_mode_real": execution_mode_ok,
    }, _dedupe(reasons)


def _fault_event_reasons(root: Path, scale: int, events_path: Path | None, events: list[Any], report: Any) -> tuple[dict[str, bool], list[str]]:
    reasons: list[str] = []
    rows = report.get("fault_rows") if isinstance(report, dict) and isinstance(report.get("fault_rows"), list) else []
    events_by_sample: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if isinstance(event, dict):
            events_by_sample.setdefault(str(event.get("sample_id", "MISSING")), []).append(event)
    required_events_ok = bool(events_by_sample)
    for row in rows:
        if not isinstance(row, dict):
            continue
        sample_id = str(row.get("sample_id", "MISSING"))
        row_events = events_by_sample.get(sample_id, [])
        observed_events = {str(event.get("event_name")) for event in row_events if event.get("event_status") == "OBSERVED"}
        missing_events = sorted(set(H07_REQUIRED_TIMELINE_EVENTS) - observed_events)
        if missing_events:
            required_events_ok = False
            reasons.append(f"fault_timeline_events.jsonl sample {sample_id} is missing observed C09 lifecycle events: {', '.join(missing_events)}.")
    for index, event in enumerate(events):
        label = f"{relpath(root, events_path) if events_path else 'fault_timeline_events.jsonl'} line {index + 1}"
        if not isinstance(event, dict):
            reasons.append(f"{label} is not a JSON object.")
            required_events_ok = False
            continue
        if event.get("node_count") != scale or event.get("scale_rung") != str(scale):
            reasons.append(f"{label} does not match exact scale {scale}.")
            required_events_ok = False
        if event.get("event_status") != "OBSERVED":
            reasons.append(f"{label} event_status {event.get('event_status')!r} is not OBSERVED.")
            required_events_ok = False
        if event.get("real_valkey") is not True:
            reasons.append(f"{label} real_valkey must be true.")
            required_events_ok = False
        if _fault_execution_mode_blocked(event.get("execution_mode")):
            reasons.append(f"{label} execution_mode {event.get('execution_mode')!r} is not real C09 execution.")
            required_events_ok = False
        if not isinstance(event.get("timestamp_unix_ms"), int) or isinstance(event.get("timestamp_unix_ms"), bool):
            reasons.append(f"{label} timestamp_unix_ms must be an integer for real C09 PASS.")
            required_events_ok = False
        if not _is_non_negative_number(event.get("monotonic_ms")):
            reasons.append(f"{label} monotonic_ms must be numeric for real C09 PASS.")
            required_events_ok = False
    return {"fault_required_events_present": required_events_ok}, _dedupe(reasons)


def _fault_sample_reasons(root: Path, scale: int, samples_path: Path | None, samples: list[Any], report: Any) -> tuple[dict[str, bool], list[str]]:
    reasons: list[str] = []
    rows = report.get("fault_rows") if isinstance(report, dict) and isinstance(report.get("fault_rows"), list) else []
    row_sample_ids = {str(row.get("sample_id")) for row in rows if isinstance(row, dict)}
    schema_ok = bool(samples)
    for index, sample in enumerate(samples):
        label = f"{relpath(root, samples_path) if samples_path else 'failover_latency_samples.jsonl'} line {index + 1}"
        if not isinstance(sample, dict):
            reasons.append(f"{label} is not a JSON object.")
            schema_ok = False
            continue
        if sample.get("sample_id") not in row_sample_ids:
            reasons.append(f"{label} sample_id {sample.get('sample_id')!r} is not present in fault_timeline_report.json.")
            schema_ok = False
        if sample.get("node_count") != scale:
            reasons.append(f"{label} node_count {sample.get('node_count')!r} does not equal exact scale {scale}.")
            schema_ok = False
        if sample.get("derived_from_timeline") is not True:
            reasons.append(f"{label} derived_from_timeline must be true; legacy latency samples cannot satisfy H07.")
            schema_ok = False
        for field in ["fault_injected_at_ms", "replica_promoted_at_ms", "slot_coverage_ok_at_ms", "first_successful_read_at_ms", "first_successful_write_at_ms"]:
            if not (isinstance(sample.get(field), int) and not isinstance(sample.get(field), bool)):
                reasons.append(f"{label} {field} must be an integer for real C09 PASS.")
                schema_ok = False
        for field in ["promotion_latency_ms", "cluster_recovery_latency_ms", "read_unavailability_ms", "write_unavailability_ms"]:
            if not _is_non_negative_number(sample.get(field)):
                reasons.append(f"{label} {field} must be numeric for real C09 PASS.")
                schema_ok = False
        for field in ["timeline_ref", "fault_type", "fault_id", "source_event_start", "source_event_end", "workload_recovery_ref", "workload_impact_ref"]:
            if _is_missing_placeholder(sample.get(field)):
                reasons.append(f"{label} {field} is missing.")
                schema_ok = False
    return {"failover_latency_samples_schema_valid": schema_ok}, _dedupe(reasons)


def _fault_ref_reasons(root: Path, scale: int, bundle_dir: Path | None, report: Any, cleanup: Any) -> tuple[dict[str, bool], list[str]]:
    reasons: list[str] = []
    rows = report.get("fault_rows") if isinstance(report, dict) and isinstance(report.get("fault_rows"), list) else []
    workload_refs_ok = bool(rows)
    cleanup_refs_ok = bool(rows)
    clean_cluster_ok = bool(rows)
    for top_ref, expected_name in [
        (report.get("timeline_events_ref") if isinstance(report, dict) else None, "fault_timeline_events.jsonl"),
        (report.get("failover_latency_samples_ref") if isinstance(report, dict) else None, "failover_latency_samples.jsonl"),
        (report.get("fault_workload_impact_ref") if isinstance(report, dict) else None, "workload_windows.json"),
    ]:
        if not _ref_resolves_to_bundle_file(root, bundle_dir, top_ref):
            reasons.append(f"fault_timeline_report.json top-level ref {top_ref!r} does not resolve in the same C09 bundle directory.")
        elif expected_name != "workload_windows.json" and Path(str(top_ref).split("#", 1)[0]).name != expected_name:
            reasons.append(f"fault_timeline_report.json top-level ref {top_ref!r} must point to {expected_name}.")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        label = f"fault_timeline_report.json fault_rows[{index}] {row.get('sample_id', 'MISSING')}"
        workload_refs = row.get("workload_window_refs")
        if not isinstance(workload_refs, list) or not workload_refs:
            reasons.append(f"{label} workload_window_refs is missing.")
            workload_refs_ok = False
        else:
            for ref in workload_refs:
                if not isinstance(ref, str) or not _ref_resolves_to_bundle_file(root, bundle_dir, ref):
                    reasons.append(f"{label} workload ref {ref!r} does not resolve in the same C09 bundle directory.")
                    workload_refs_ok = False
        if not _ref_resolves_to_bundle_file(root, bundle_dir, row.get("cleanup_ref")):
            reasons.append(f"{label} cleanup_ref {row.get('cleanup_ref')!r} does not resolve in the same C09 bundle directory.")
            cleanup_refs_ok = False
        clean = row.get("clean_cluster_evidence")
        if not isinstance(clean, dict) or clean.get("status") != "PASS" or not _ref_resolves_to_bundle_file(root, bundle_dir, clean.get("ref")):
            reasons.append(f"{label} clean_cluster_evidence must be PASS and resolve in the same C09 bundle directory.")
            clean_cluster_ok = False
    if not isinstance(cleanup, dict) or cleanup.get("status") != "PASS" or cleanup.get("resources_remaining") != []:
        cleanup_refs_ok = False
        clean_cluster_ok = False
    return {
        "workload_refs_resolve": workload_refs_ok,
        "cleanup_refs_resolve": cleanup_refs_ok,
        "clean_cluster_evidence": clean_cluster_ok,
    }, _dedupe(reasons)


def _fault_fake_or_partial_reasons(root: Path, paths: list[Path], report: Any, events: list[Any], samples: list[Any]) -> list[str]:
    reasons: list[str] = []
    if _contains_fake_or_partial(root, paths):
        reasons.append("Fault timeline source path contains fake, partial, or fixture marker.")
    payloads: list[Any] = [report, *events, *samples]
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in ["status", "timeline_status", "evidence_kind", "evidence_class", "source_kind", "execution_mode"]:
            value = payload.get(key)
            if isinstance(value, str) and value.upper() in {"FAKE", "PARTIAL", "FIXTURE", "DRY_RUN", "DRY-RUN", "LEGACY"}:
                reasons.append(f"Fault timeline artifact contains {key}={value!r}; fake, fixture, legacy, dry-run, or PARTIAL evidence cannot promote.")
    return _dedupe(reasons)


def _fault_legacy_reasons(paths: list[Path], report: Any, events: list[Any], samples: list[Any]) -> list[str]:
    reasons: list[str] = []
    path_names = {path.name for path in paths}
    if "fault_sequence.json" in path_names and not {"fault_timeline_report.json", "fault_timeline_events.jsonl", "failover_latency_samples.jsonl"}.issubset(path_names):
        reasons.append("Legacy fault_sequence.json evidence cannot satisfy H07 without a complete C09 timeline bundle.")
    if not events and samples:
        reasons.append("Legacy failover latency samples without C09 timeline events cannot satisfy H07.")
    if isinstance(report, dict) and report.get("artifact_type") not in {None, "fault_timeline_report"}:
        reasons.append("Fault report artifact is legacy or not a C09 fault_timeline_report.")
    for sample in samples:
        if isinstance(sample, dict) and sample.get("derived_from_timeline") is not True:
            reasons.append("Legacy failover latency sample without derived_from_timeline=true cannot satisfy H07.")
    return _dedupe(reasons)


def _fault_execution_mode_blocked(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return True
    normalized = value.strip().lower()
    return normalized in H07_BLOCKED_EXECUTION_MODES or any(token in normalized for token in H07_BLOCKED_EXECUTION_MODES)


def _ref_resolves_to_bundle_file(root: Path, bundle_dir: Path | None, ref: Any) -> bool:
    if bundle_dir is None or not isinstance(ref, str) or not ref.strip():
        return False
    ref_path = ref.split("#", 1)[0]
    if not ref_path:
        return False
    candidate = Path(ref_path)
    if not candidate.is_absolute():
        if len(candidate.parts) >= 2 and candidate.parts[0] in {"artifacts", "runs", "tests"}:
            candidate = root / candidate
        else:
            candidate = bundle_dir / candidate
    try:
        candidate.resolve().relative_to(bundle_dir.resolve())
    except ValueError:
        return False
    return candidate.exists() and candidate.is_file()


def _observed_evidence(workload: Any, rows: list[Any], *, top_keys: tuple[str, ...], evidence_key: str, row_metrics: set[str]) -> bool:
    if isinstance(workload, dict):
        if any(_positive_number(workload.get(key)) for key in top_keys):
            return True
        evidence = workload.get(evidence_key)
        if isinstance(evidence, dict) and evidence.get("status") == "PASS":
            observed_flag = evidence.get("observed") is True or bool(evidence.get("source") or evidence.get("source_artifacts") or evidence.get("probe"))
            if observed_flag and any(_positive_number(evidence.get(key)) for key in top_keys + ("count", "value")):
                return True
        windows = workload.get("windows")
        if isinstance(windows, list):
            for item in windows:
                if isinstance(item, dict) and any(_positive_number(item.get(key)) for key in top_keys):
                    return True
    for row in rows:
        if isinstance(row, dict) and row.get("metric_name") in row_metrics and _positive_number(row.get("metric_value")):
            return True
    return False


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) > 0


def _read_management_jsonl_strict(root: Path, path: Path | None) -> tuple[list[Any], list[str]]:
    if path is None:
        return [], []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"{relpath(root, path)} could not be read: {exc}."]
    rows: list[Any] = []
    reasons: list[str] = []
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            reasons.append(f"{relpath(root, path)} line {line_no} is invalid JSON: {exc.msg}.")
            continue
        if not isinstance(value, dict):
            reasons.append(f"{relpath(root, path)} line {line_no} is not a JSON object.")
        rows.append(value)
    return rows, reasons


def _management_matrix_reasons(root: Path, path: Path | None, matrix: Any, scale: int) -> tuple[dict[str, bool], list[str]]:
    operations = matrix.get("operations", []) if isinstance(matrix, dict) else []
    observed = {str(row.get("operation_name")) for row in operations if isinstance(row, dict)}
    missing = sorted(H05_REQUIRED_MANAGEMENT_OPERATIONS - observed)
    reasons: list[str] = []
    schema_reasons = _schema_reasons(root, path, matrix, "management_ops_matrix.schema.json")
    reasons.extend(schema_reasons)
    if not isinstance(matrix, dict):
        reasons.append("management_ops_matrix.json is missing or invalid JSON.")
    else:
        if matrix.get("artifact_type") != "management_ops_matrix":
            reasons.append("management_ops_matrix.json artifact_type is not management_ops_matrix.")
        if matrix.get("status") != "PASS":
            reasons.append(f"management_ops_matrix.json status {matrix.get('status')!r} is not PASS.")
        if missing:
            reasons.append(f"management_ops_matrix.json is missing required operations: {', '.join(missing)}.")
    for row in operations if isinstance(operations, list) else []:
        if not isinstance(row, dict):
            reasons.append("management_ops_matrix.operations contains a non-object row.")
            continue
        op = str(row.get("operation_name"))
        if row.get("node_count") != scale:
            reasons.append(f"matrix operation {op} node_count {row.get('node_count')!r} does not equal {scale}.")
        if row.get("coverage_id") != f"{scale}.management.{op}":
            reasons.append(f"matrix operation {op} coverage_id does not match exact scale {scale}.")
        if row.get("operation_status") != "PASS":
            reasons.append(f"matrix operation {op} operation_status {row.get('operation_status')!r} is not PASS.")
        if row.get("real_execution_verified") is not True:
            reasons.append(f"matrix operation {op} real_execution_verified is not true.")
        if _is_missing_placeholder(row.get("command_log_ref")):
            reasons.append(f"matrix operation {op} command_log_ref is missing.")
        if not isinstance(row.get("topology_refs"), list) or not row.get("topology_refs"):
            reasons.append(f"matrix operation {op} topology_refs is missing.")
        if _is_missing_placeholder(row.get("workload_window_ref")):
            reasons.append(f"matrix operation {op} workload_window_ref is missing.")
    checks = {
        "management_matrix_present": bool(operations),
        "management_matrix_schema_valid": not schema_reasons,
        "management_matrix_status_pass": isinstance(matrix, dict) and matrix.get("status") == "PASS",
        "management_required_operations_present": not missing and bool(operations),
    }
    return checks, reasons


def _management_result_reasons(root: Path, path: Path | None, rows: list[Any], scale: int) -> tuple[dict[str, bool], list[str]]:
    observed = {str(row.get("operation_name")) for row in rows if isinstance(row, dict)}
    missing = sorted(H05_REQUIRED_MANAGEMENT_OPERATIONS - observed)
    reasons: list[str] = []
    schema_reasons: list[str] = []
    for index, row in enumerate(rows):
        schema_reasons.extend(_schema_reasons(root, path, row, "management_operation_result.schema.json", label=f"row {index + 1}"))
    reasons.extend(schema_reasons)
    if not rows:
        reasons.append("management_operation_results.jsonl has no operation rows.")
    if missing:
        reasons.append(f"management_operation_results.jsonl is missing required operations: {', '.join(missing)}.")
    required_fields = {
        "operation_id",
        "operation_name",
        "coverage_id",
        "node_count",
        "scale",
        "operation_status",
        "real_execution_verified",
        "started_at_unix_ms",
        "ended_at_unix_ms",
        "duration_ms",
        "command_ms",
        "convergence_ms",
        "cleanup_ms",
        "cluster_state_before",
        "cluster_state_after",
        "cluster_known_nodes_before",
        "cluster_known_nodes_after",
        "slots_before",
        "slots_after",
        "workload_window_ref",
        "topology_before_ref",
        "topology_after_ref",
        "command_log_ref",
        "source_evidence_refs",
    }
    semantics_ok = bool(rows) and not missing
    exact_scale_ok = bool(rows)
    for index, row in enumerate(rows):
        label = f"management_operation_results.jsonl row {index + 1}"
        if not isinstance(row, dict):
            reasons.append(f"{label} is not an object.")
            semantics_ok = False
            exact_scale_ok = False
            continue
        op = str(row.get("operation_name"))
        for field in sorted(required_fields):
            if field not in row or _is_missing_placeholder(row.get(field)):
                reasons.append(f"{label} {op} required field {field} is missing.")
                semantics_ok = False
        if row.get("node_count") != scale or row.get("scale") != scale:
            reasons.append(f"{label} {op} does not match exact scale {scale}.")
            exact_scale_ok = False
        if row.get("coverage_id") != f"{scale}.management.{op}":
            reasons.append(f"{label} {op} coverage_id does not match exact scale {scale}.")
            semantics_ok = False
        if row.get("operation_status") != "PASS" or row.get("real_execution_verified") is not True:
            reasons.append(f"{label} {op} is not a real PASS operation.")
            semantics_ok = False
        if row.get("cluster_state_before") != "ok" or row.get("cluster_state_after") != "ok":
            reasons.append(f"{label} {op} cluster state before/after is not ok.")
            semantics_ok = False
        if row.get("cluster_known_nodes_before") != scale or row.get("cluster_known_nodes_after") != scale:
            reasons.append(f"{label} {op} known nodes before/after do not equal exact scale {scale}.")
            semantics_ok = False
        if row.get("slots_before") != 16384 or row.get("slots_after") != 16384:
            reasons.append(f"{label} {op} slots_before/after are not 16384.")
            semantics_ok = False
        for field in ["started_at_unix_ms", "ended_at_unix_ms"]:
            if not (isinstance(row.get(field), int) and not isinstance(row.get(field), bool)):
                reasons.append(f"{label} {op} {field} must be an integer.")
                semantics_ok = False
        if isinstance(row.get("started_at_unix_ms"), int) and isinstance(row.get("ended_at_unix_ms"), int):
            if row["ended_at_unix_ms"] < row["started_at_unix_ms"]:
                reasons.append(f"{label} {op} ended_at_unix_ms is earlier than started_at_unix_ms.")
                semantics_ok = False
        for field in ["duration_ms", "command_ms", "convergence_ms", "cleanup_ms"]:
            if not _is_non_negative_number(row.get(field)):
                reasons.append(f"{label} {op} {field} is missing or non-numeric.")
                semantics_ok = False
        if not isinstance(row.get("source_evidence_refs"), list) or not row.get("source_evidence_refs"):
            reasons.append(f"{label} {op} source_evidence_refs is missing.")
            semantics_ok = False
    return {"operation_results_present": bool(rows), "operation_results_schema_valid": not schema_reasons, "operation_results_exact_scale": exact_scale_ok, "operation_semantics_present": semantics_ok}, reasons


def _management_topology_ref_reasons(results: list[Any], topology_rows: list[Any], scale: int) -> tuple[bool, bool, list[str]]:
    labels = {str(row.get("label")) for row in topology_rows if isinstance(row, dict) and row.get("label")}
    labels.update(
        f"{row.get('operation_id')}:{row.get('label')}"
        for row in topology_rows
        if isinstance(row, dict) and row.get("operation_id") and row.get("label")
    )
    labels.update(
        f"{row.get('operation_id')}-{row.get('label')}"
        for row in topology_rows
        if isinstance(row, dict) and row.get("operation_id") and row.get("label")
    )
    reasons: list[str] = []
    if not labels:
        reasons.append("management_topology_snapshots.jsonl has no labelled snapshots.")
    health_ok = True
    for index, snapshot in enumerate(topology_rows):
        if not isinstance(snapshot, dict):
            health_ok = False
            reasons.append(f"management_topology_snapshots.jsonl row {index + 1} is not an object.")
            continue
        nodes = snapshot.get("nodes")
        if not isinstance(nodes, list) or len(nodes) != scale:
            health_ok = False
            reasons.append(f"topology snapshot {snapshot.get('operation_id')}:{snapshot.get('label')} has {len(nodes) if isinstance(nodes, list) else 'MISSING'} nodes, expected {scale}.")
        slots = snapshot.get("slots")
        slots_ok = slots == 16384 or (isinstance(slots, dict) and slots.get("assigned") == 16384 and slots.get("ok") == 16384 and slots.get("known_nodes") == scale and slots.get("cluster_state") == "ok")
        if not slots_ok:
            health_ok = False
            reasons.append(f"topology snapshot {snapshot.get('operation_id')}:{snapshot.get('label')} slots is not 16384.")
        for node in nodes if isinstance(nodes, list) else []:
            if not isinstance(node, dict):
                health_ok = False
                continue
            flags = node.get("flags", [])
            if isinstance(flags, list) and any(str(flag).lower() in {"fail", "fail?", "pfail", "handshake", "noaddr"} for flag in flags):
                health_ok = False
                reasons.append(f"topology snapshot {snapshot.get('operation_id')}:{snapshot.get('label')} contains unhealthy node flags.")
            if node.get("link_state") not in {None, "connected"}:
                health_ok = False
                reasons.append(f"topology snapshot {snapshot.get('operation_id')}:{snapshot.get('label')} contains non-connected link state.")
    for row in results:
        if not isinstance(row, dict):
            continue
        op = str(row.get("operation_name"))
        for field in ["topology_before_ref", "topology_after_ref"]:
            ref = row.get(field)
            if not isinstance(ref, str) or ref not in labels:
                reasons.append(f"management operation {op} {field} {ref!r} does not resolve to a topology snapshot label.")
    ref_ok = not [reason for reason in reasons if "topology_before_ref" in reason or "topology_after_ref" in reason or "no labelled" in reason]
    return ref_ok, health_ok, reasons


def _management_workload_reasons(root: Path, impact_path: Path | None, impact: Any, workload_windows_path: Path | None, workload_windows: Any, results: list[Any]) -> tuple[bool, bool, bool, list[str]]:
    reasons: list[str] = []
    schema_reasons = [
        *_schema_reasons(root, impact_path, impact, "workload_impact_report.schema.json"),
        *_schema_reasons(root, workload_windows_path, workload_windows, "workload_windows.schema.json"),
    ]
    reasons.extend(schema_reasons)
    if not isinstance(impact, dict) or impact.get("status") != "PASS":
        reasons.append("management_workload_impact.json is missing or status is not PASS.")
    if not isinstance(workload_windows, dict):
        reasons.append("workload_windows.json is missing or invalid JSON.")
        window_ids: set[str] = set()
        metrics_ok = False
    else:
        windows = workload_windows.get("windows", [])
        window_ids = set()
        metrics_ok = isinstance(windows, list) and bool(windows)
        for item in windows if isinstance(windows, list) else []:
            if not isinstance(item, dict):
                metrics_ok = False
                continue
            if item.get("window_id") or item.get("id"):
                window_ids.add(str(item.get("window_id") or item.get("id")))
            if item.get("operation_id") and item.get("window_name"):
                window_ids.add(f"{item['operation_id']}:{item['window_name']}")
            metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else item
            for field in [
                "achieved_qps",
                "latency_p95_ms",
                "error_rate",
                "timeout_count",
                "moved_count",
                "ask_count",
                "cluster_down_count",
                "readonly_count",
                "tryagain_count",
                "connection_error_count",
            ]:
                if not _is_non_negative_number(metrics.get(field) if isinstance(metrics, dict) else None):
                    metrics_ok = False
                    reasons.append(f"workload window {item.get('operation_id')}:{item.get('window_name')} metric {field} is missing or non-numeric.")
    impact_ops = {str(row.get("operation_id")) for row in impact.get("operations", [])} if isinstance(impact, dict) else set()
    for row in results:
        if not isinstance(row, dict):
            continue
        op_id = str(row.get("operation_id"))
        ref = row.get("workload_window_ref")
        if op_id not in impact_ops:
            reasons.append(f"management operation {op_id} is missing from management_workload_impact operations.")
        if not isinstance(ref, str) or ref not in window_ids:
            reasons.append(f"management operation {op_id} workload_window_ref {ref!r} does not resolve to workload_windows.json.")
    ref_reasons = [reason for reason in reasons if "workload_window_ref" in reason or "workload_impact" in reason or "workload_windows" in reason]
    return not ref_reasons, metrics_ok, not schema_reasons, reasons


def _management_topology_diff_reasons(root: Path, path: Path | None, diff_rows: list[Any], results: list[Any], matrix_operations: list[Any]) -> tuple[bool, bool, bool, list[str]]:
    reasons: list[str] = []
    schema_reasons: list[str] = []
    if path is None:
        return False, False, False, ["management_topology_diffs.jsonl is missing."]
    if not diff_rows:
        return False, False, False, ["management_topology_diffs.jsonl has no rows."]
    by_operation = {str(row.get("operation_id")): row for row in diff_rows if isinstance(row, dict)}
    for index, row in enumerate(diff_rows):
        schema_reasons.extend(_schema_reasons(root, path, row, "management_topology_diff.schema.json", label=f"row {index + 1}"))
    reasons.extend(schema_reasons)
    result_by_operation = {str(row.get("operation_id")): row for row in results if isinstance(row, dict)}
    for matrix_row in matrix_operations:
        if not isinstance(matrix_row, dict):
            continue
        op_id = str(matrix_row.get("operation_id"))
        diff_ref = matrix_row.get("topology_diff_ref")
        if op_id not in by_operation:
            reasons.append(f"management matrix topology diff missing operation_id {op_id}.")
            continue
        if diff_ref != f"management_topology_diffs.jsonl#{op_id}":
            reasons.append(f"management matrix operation {op_id} topology_diff_ref {diff_ref!r} does not resolve to required diff ref.")
        result = result_by_operation.get(op_id)
        if isinstance(result, dict) and result.get("topology_diff_ref") != diff_ref:
            reasons.append(f"management matrix operation {op_id} topology_diff_ref does not match operation result topology_diff_ref.")
    for result in results:
        if not isinstance(result, dict):
            continue
        op_id = str(result.get("operation_id"))
        diff_ref = result.get("topology_diff_ref")
        matrix_ref_ok = isinstance(diff_ref, str) and diff_ref
        if op_id not in by_operation:
            reasons.append(f"management topology diff missing operation_id {op_id}.")
            continue
        diff = by_operation[op_id]
        if matrix_ref_ok and diff_ref != f"management_topology_diffs.jsonl#{op_id}":
            reasons.append(f"management operation {op_id} topology_diff_ref {diff_ref!r} does not match required diff ref.")
        if diff.get("before_snapshot_ref") != result.get("before_topology_snapshot_ref") or diff.get("after_snapshot_ref") != result.get("after_topology_snapshot_ref"):
            reasons.append(f"management topology diff {op_id} before/after refs do not match operation result refs.")
    ref_reasons = [reason for reason in reasons if "topology diff" in reason or "topology_diff_ref" in reason]
    return bool(diff_rows), not schema_reasons, not ref_reasons, reasons


def _management_command_ref_reasons(root: Path, command_log_path: Path | None, command_rows: list[Any], matrix: Any, results: list[Any]) -> tuple[bool, bool, bool, list[str]]:
    command_by_id = {str(row.get("command_id")): row for row in command_rows if isinstance(row, dict) and row.get("command_id")}
    command_ids = set(command_by_id)
    reasons: list[str] = []
    row_reasons = _command_row_reasons(root, command_log_path, command_rows)
    jsonl_reasons = _read_command_jsonl_strict(root, command_log_path)[1]
    output_reasons = _output_hash_reasons(root, command_log_path, command_rows)
    placeholder_reasons = _placeholder_command_reasons(command_rows)
    kind_reasons = _command_kind_argv_reasons(command_rows)
    c07_ok = bool(command_rows) and not row_reasons and not jsonl_reasons and not output_reasons and not placeholder_reasons and not kind_reasons
    reasons.extend(row_reasons)
    reasons.extend(jsonl_reasons)
    reasons.extend(output_reasons)
    reasons.extend(placeholder_reasons)
    reasons.extend(kind_reasons)
    if not command_ids:
        reasons.append("management_command_log.jsonl has no command ids.")
    rows: list[Any] = []
    if isinstance(matrix, dict) and isinstance(matrix.get("operations"), list):
        rows.extend(matrix["operations"])
    rows.extend(results)
    for row in rows:
        if not isinstance(row, dict):
            continue
        op = str(row.get("operation_name"))
        ref = row.get("command_log_ref")
        refs = row.get("command_log_refs") if isinstance(row.get("command_log_refs"), list) else []
        all_refs = [ref] if isinstance(ref, str) else []
        all_refs.extend(str(item) for item in refs if isinstance(item, str))
        if not all_refs:
            reasons.append(f"management operation {op} has no command refs.")
            continue
        for item in all_refs:
            if "#" not in item:
                reasons.append(f"management operation {op} command ref {item!r} is file-level only; exact PASS requires a command id fragment.")
                continue
            command_id = item.rsplit("#", 1)[1]
            if command_id not in command_ids:
                reasons.append(f"management operation {op} command ref {item!r} does not resolve to management_command_log.jsonl.")
                continue
            command_operation = str(command_by_id[command_id].get("operation_id"))
            row_operation = str(row.get("operation_id"))
            if command_operation != row_operation:
                reasons.append(f"management operation {op} command ref {item!r} points to operation_id {command_operation!r}, expected {row_operation!r}.")
    ref_reasons = [reason for reason in reasons if "command ref" in reason or "no command ids" in reason]
    trace_reasons = [reason for reason in reasons if "points to operation_id" in reason]
    return not ref_reasons, c07_ok, not trace_reasons, reasons


def _summary_missing_or_skipped_reasons(summary: Any) -> list[str]:
    if not isinstance(summary, dict):
        return ["command_audit_summary.json is missing or invalid, so missing_or_skipped cannot be checked."]
    missing_or_skipped = summary.get("missing_or_skipped")
    if missing_or_skipped:
        return ["command_audit_summary.missing_or_skipped must be empty for exact-scale command audit PASS."]
    return []


def _summary_count_reasons(summary: Any, rows: list[Any]) -> list[str]:
    if not isinstance(summary, dict):
        return ["command_audit_summary.json is missing or invalid, so retry/failure/timeout summaries cannot be checked."]
    typed_rows = [row for row in rows if isinstance(row, dict)]
    expected = {
        "total_commands": len(typed_rows),
        "pass_count": sum(1 for row in typed_rows if row.get("status") == "PASS"),
        "failure_count": sum(1 for row in typed_rows if row.get("status") == "FAIL"),
        "timeout_count": sum(1 for row in typed_rows if row.get("status") == "TIMEOUT"),
        "retry_count": sum(1 for row in typed_rows if int(row.get("retry_index", 0) or 0) > 0 or row.get("status") == "RETRY"),
    }
    reasons: list[str] = []
    for field, value in expected.items():
        if summary.get(field) != value:
            reasons.append(f"command_audit_summary.{field} {summary.get(field)!r} does not match command log value {value}.")
    for array_field in ["failed_commands", "timeout_commands", "retry_commands"]:
        if array_field in summary and not isinstance(summary.get(array_field), list):
            reasons.append(f"command_audit_summary.{array_field} is not an array.")
    return reasons


def _failure_timeout_retry_rows_summarized_reasons(summary: Any, rows: list[Any]) -> list[str]:
    if not isinstance(summary, dict):
        return ["command_audit_summary.json is missing or invalid, so failed/timeout/retry row summaries cannot be checked."]
    typed_rows = [row for row in rows if isinstance(row, dict)]
    expectations = [
        ("failed_commands", {str(row.get("command_id")) for row in typed_rows if row.get("status") == "FAIL"}),
        ("timeout_commands", {str(row.get("command_id")) for row in typed_rows if row.get("status") == "TIMEOUT"}),
        (
            "retry_commands",
            {
                str(row.get("command_id"))
                for row in typed_rows
                if int(row.get("retry_index", 0) or 0) > 0 or row.get("status") == "RETRY"
            },
        ),
    ]
    reasons: list[str] = []
    for field, expected_ids in expectations:
        actual = summary.get(field, [])
        actual_ids = {str(item.get("command_id")) for item in actual if isinstance(item, dict)}
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - {str(row.get("command_id")) for row in typed_rows})
        if missing:
            reasons.append(f"command_audit_summary.{field} is missing command ids: {', '.join(missing[:8])}.")
        if extra:
            reasons.append(f"command_audit_summary.{field} references unknown command ids: {', '.join(extra[:8])}.")
    return reasons


def _operation_traceability_reasons(summary: Any, rows: list[Any]) -> list[str]:
    typed_rows = [row for row in rows if isinstance(row, dict)]
    command_ids = {str(row.get("command_id")) for row in typed_rows}
    if not typed_rows:
        return ["No command rows exist for operation traceability."]
    if not isinstance(summary, dict):
        return ["command_audit_summary.json is missing or invalid, so operation traceability cannot be checked."]
    traceability = summary.get("operation_traceability")
    if not isinstance(traceability, list) or not traceability:
        return ["command_audit_summary.operation_traceability is missing or empty."]
    traced_ids: set[str] = set()
    reasons: list[str] = []
    for item in traceability:
        if not isinstance(item, dict):
            reasons.append("command_audit_summary.operation_traceability item is not an object.")
            continue
        refs = item.get("command_log_refs")
        if not isinstance(refs, list) or not refs:
            reasons.append(f"operation_traceability entry {item.get('operation_id')!r} has no command_log_refs.")
            continue
        for ref in refs:
            if not isinstance(ref, str) or "#" not in ref:
                reasons.append(f"operation_traceability ref {ref!r} is not a command-log fragment.")
                continue
            traced_ids.add(ref.rsplit("#", 1)[1])
    missing = sorted(command_ids - traced_ids)
    if missing:
        reasons.append(f"operation_traceability is missing command ids: {', '.join(missing[:8])}.")
    return reasons


def _placeholder_command_reasons(rows: list[Any]) -> list[str]:
    placeholders = {
        "create_cluster",
        "meet_nodes",
        "add_replica",
        "remove_replica",
        "remove_primary_drained_or_safe_replaced",
        "remove_failed_node",
        "reshard_slot_range",
        "reshard_with_keys",
        "rebalance_after_imbalance",
        "rolling_restart_replica_first",
        "rolling_restart_primary_safe",
    }
    reasons: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        argv = row.get("argv", row.get("command"))
        if not isinstance(argv, list):
            continue
        joined = " ".join(str(item).lower() for item in argv)
        matched = sorted(token for token in placeholders if token in joined)
        if matched:
            reasons.append(f"Command row {index + 1} uses placeholder command token(s): {', '.join(matched)}.")
    return reasons


def _command_kind_argv_reasons(rows: list[Any]) -> list[str]:
    reasons: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        kind = str(row.get("command_kind", ""))
        argv = row.get("argv")
        if not isinstance(argv, list):
            continue
        expected = _classify_command_kind_for_c07([str(item) for item in argv])
        if kind in C07_REQUIRED_COMMAND_KINDS and expected is None:
            reasons.append(f"Command row {index + 1} command_kind {kind!r} is not supported by argv shape.")
        if expected and kind != expected:
            reasons.append(f"Command row {index + 1} command_kind {kind!r} does not match argv-derived kind {expected!r}.")
    return reasons


def _classify_command_kind_for_c07(argv: list[str]) -> str | None:
    upper = [item.upper() for item in argv]
    joined = " ".join(upper)
    if "CLUSTER MEET" in joined:
        return "cluster_meet"
    if "CLUSTER ADDSLOTS" in joined:
        return "cluster_addslots"
    if "CLUSTER REPLICATE" in joined:
        return "cluster_replicate"
    if "CLUSTER INFO" in joined or "CLUSTER NODES" in joined or upper[-1:] == ["PING"] or " PING" in joined:
        return "cluster_probe"
    if any(item in {"RM", "STOP", "KILL"} for item in upper) or upper[:2] == ["DOCKER", "NETWORK"]:
        return "cleanup"
    return None


def _row_has_output_refs(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    stdout_ref = row.get("stdout_path") or row.get("stdout_ref")
    stderr_ref = row.get("stderr_path") or row.get("stderr_ref")
    stdout_hash = row.get("stdout_sha256")
    stderr_hash = row.get("stderr_sha256")
    return bool(stdout_ref and stderr_ref and stdout_hash and stderr_hash)


def _output_hash_reasons(root: Path, command_path: Path | None, rows: list[Any]) -> list[str]:
    reasons: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        for stream in ["stdout", "stderr"]:
            path_value = row.get(f"{stream}_path")
            digest = row.get(f"{stream}_sha256")
            prefix = f"{relpath(root, command_path) if command_path else 'command log'} line {index + 1} {stream}"
            if not isinstance(path_value, str) or not path_value:
                reasons.append(f"{prefix}_path is missing.")
                continue
            if not isinstance(digest, str) or len(digest) != 64:
                reasons.append(f"{prefix}_sha256 is missing or invalid.")
                continue
            output_path = Path(path_value)
            if not output_path.is_absolute():
                output_path = root / output_path
            try:
                output_path.relative_to(root)
            except ValueError:
                reasons.append(f"{prefix}_path {path_value!r} is outside the repository root.")
                continue
            if not output_path.exists():
                reasons.append(f"{prefix}_path {path_value!r} does not exist for hash verification.")
                continue
            actual = hashlib.sha256(output_path.read_bytes()).hexdigest()
            if actual != digest:
                reasons.append(f"{prefix}_sha256 does not match {path_value!r}.")
    return reasons


def _empty_management_command_log_reasons(root: Path, paths: list[Path]) -> list[str]:
    reasons: list[str] = []
    for path in paths:
        if path.name != "management_command_log.jsonl":
            continue
        if not read_jsonl(path):
            reasons.append(f"{relpath(root, path)} is an empty management command log and cannot coexist with exact-scale command audit PASS.")
    return reasons


def _validate_json_schema(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    if "allOf" in schema:
        for index, subschema in enumerate(schema["allOf"]):
            if isinstance(subschema, dict):
                errors.extend(_validate_json_schema(instance, subschema, f"{path}.allOf[{index}]"))
    if "oneOf" in schema:
        options = schema.get("oneOf", [])
        matches = 0
        option_errors: list[str] = []
        for index, subschema in enumerate(options):
            if not isinstance(subschema, dict):
                continue
            current_errors = _validate_json_schema(instance, subschema, path)
            if not current_errors:
                matches += 1
            elif index < 2:
                option_errors.extend(current_errors[:2])
        if matches != 1:
            detail = f"; examples: {'; '.join(option_errors[:3])}" if option_errors else ""
            errors.append(f"{path}: expected exactly one oneOf match, got {matches}{detail}")
            return errors
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']!r}, got {instance!r}")
    if "type" in schema:
        expected_type = schema["type"]
        expected = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_schema_type_matches(instance, str(item)) for item in expected):
            errors.append(f"{path}: expected type {expected_type!r}, got {type(instance).__name__}")
            return errors
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required key {key!r}")
        props = schema.get("properties", {})
        if isinstance(props, dict):
            for key, subschema in props.items():
                if key in instance and isinstance(subschema, dict):
                    errors.extend(_validate_json_schema(instance[key], subschema, f"{path}.{key}"))
        if schema.get("additionalProperties") is False and isinstance(props, dict):
            for key in sorted(set(instance) - set(props)):
                errors.append(f"{path}: additional property not allowed: {key!r}")
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < int(schema["minItems"]):
            errors.append(f"{path}: expected at least {schema['minItems']} items, got {len(instance)}")
        if "maxItems" in schema and len(instance) > int(schema["maxItems"]):
            errors.append(f"{path}: expected at most {schema['maxItems']} items, got {len(instance)}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                errors.extend(_validate_json_schema(item, item_schema, f"{path}[{index}]"))
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < int(schema["minLength"]):
            errors.append(f"{path}: string shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(str(schema["pattern"]), instance):
            errors.append(f"{path}: string {instance!r} does not match pattern {schema['pattern']!r}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: number {instance!r} below minimum {schema['minimum']!r}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: number {instance!r} above maximum {schema['maximum']!r}")
    return errors


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _is_fixture_path(root: Path, path: Path) -> bool:
    return "tests/fixtures/" in relpath(root, path).replace("\\", "/")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _best_evidence(root: Path, paths: list[Path]) -> dict[str, Any]:
    for path in paths:
        if path.name == "valkey_e2e_evidence.json":
            value = read_json(path)
            if isinstance(value, dict):
                return value
    for path in paths:
        if path.suffix == ".json":
            value = read_json(path)
            if isinstance(value, dict) and "nodes_observed" in value:
                return value
    return {}


def _jsonl_has_rows(paths: list[Path], hint: str) -> bool:
    for path in paths:
        if path.suffix != ".jsonl":
            continue
        if hint not in path.name and hint not in path.as_posix():
            continue
        if read_jsonl(path):
            return True
    return False


def _contains_fake_or_partial(root: Path, paths: list[Path]) -> bool:
    needles = ("fake", "partial", "fixture")
    for path in paths:
        rel = relpath(root, path).lower()
        if any(needle in rel for needle in needles):
            return True
    return False


def _evidence_kind(capability: str, source_artifacts: list[str], semantic_checks: dict[str, Any]) -> str:
    if not source_artifacts:
        return "BLOCKED_WITH_REASON"
    lowered = [path.lower() for path in source_artifacts]
    if all("tests/fixtures/" in path for path in lowered):
        return "FIXTURE_ONLY"
    if all("dryrun" in path or "dry_run" in path for path in lowered):
        return "DRY_RUN_ONLY"
    if capability == "setup_telemetry" and semantic_checks.get("setup_c06_acceptance", {}).get("accepted") is True:
        return "REAL_EXACT_SCALE"
    if capability == "command_audit" and semantic_checks.get("command_c07_acceptance", {}).get("accepted") is True:
        return "REAL_EXACT_SCALE"
    if capability == "management_matrix" and semantic_checks.get("management_h05_acceptance", {}).get("accepted") is True:
        return "REAL_EXACT_SCALE"
    if capability == "workload_benchmark" and semantic_checks.get("workload_h06_acceptance", {}).get("accepted") is True:
        return "REAL_EXACT_SCALE"
    if capability == "fault_timeline" and semantic_checks.get("fault_h07_acceptance", {}).get("accepted") is True:
        return "REAL_EXACT_SCALE"
    if capability == "system_metrics" and semantic_checks.get("system_h08_acceptance", {}).get("accepted") is True:
        return "REAL_EXACT_SCALE"
    if semantic_checks.get("real_valkey_verified") and semantic_checks.get("exact_scale_observed"):
        return "LEGACY_EVIDENCE_ONLY"
    if semantic_checks.get("real_valkey_verified"):
        return "REAL_SMALL_SMOKE"
    return "INVALID"


def _claim_passes(evidence_kind: str, semantic_checks: dict[str, Any]) -> bool:
    return (
        evidence_kind in ALLOWED_PASS_KINDS
        and semantic_checks.get("m1_format_fields_complete") is True
        and semantic_checks.get("hardening_stage_accepted") is True
    )


def _blocked_reason(capability: str, scale: int, evidence_kind: str, semantic_checks: dict[str, Any]) -> str:
    if capability == "setup_telemetry":
        setup = semantic_checks.get("setup_c06_acceptance")
        reasons = setup.get("reasons", []) if isinstance(setup, dict) else []
        if reasons:
            return f"{claim_id(capability, scale)} lacks C06 exact-scale setup telemetry: {'; '.join(str(reason) for reason in reasons)}"
    if capability == "command_audit":
        command = semantic_checks.get("command_c07_acceptance")
        reasons = command.get("reasons", []) if isinstance(command, dict) else []
        if reasons:
            return f"{claim_id(capability, scale)} lacks C07 exact-scale command audit evidence: {'; '.join(str(reason) for reason in reasons)}"
    if capability == "management_matrix":
        management = semantic_checks.get("management_h05_acceptance")
        reasons = management.get("reasons", []) if isinstance(management, dict) else []
        if reasons:
            return f"{claim_id(capability, scale)} lacks H05 exact-scale management matrix evidence: {'; '.join(str(reason) for reason in reasons)}"
    if capability == "workload_benchmark":
        workload = semantic_checks.get("workload_h06_acceptance")
        reasons = workload.get("reasons", []) if isinstance(workload, dict) else []
        if reasons:
            return f"{claim_id(capability, scale)} lacks H06 exact-scale workload benchmark evidence: {'; '.join(str(reason) for reason in reasons)}"
    if capability == "fault_timeline":
        fault = semantic_checks.get("fault_h07_acceptance")
        reasons = fault.get("reasons", []) if isinstance(fault, dict) else []
        if reasons:
            return f"{claim_id(capability, scale)} lacks H07/C09 exact-scale fault timeline evidence: {'; '.join(str(reason) for reason in reasons)}"
    if capability == "system_metrics":
        system = semantic_checks.get("system_h08_acceptance")
        reasons = system.get("reasons", []) if isinstance(system, dict) else []
        if reasons:
            return f"{claim_id(capability, scale)} lacks H08/C10 exact-scale system metrics evidence: {'; '.join(str(reason) for reason in reasons)}"
    missing = [name for name in CAPABILITY_REQUIRED_CHECKS[capability] if semantic_checks.get(name) is not True]
    if evidence_kind == "LEGACY_EVIDENCE_ONLY":
        return f"{claim_id(capability, scale)} has historical real evidence, but it has not been accepted by the M1 hardening gate."
    if evidence_kind in {"FIXTURE_ONLY", "DRY_RUN_ONLY", "REAL_SMALL_SMOKE", "INVALID"}:
        return f"{claim_id(capability, scale)} only has non-promotable {evidence_kind} evidence."
    if missing:
        return f"{claim_id(capability, scale)} is missing semantic checks: {', '.join(missing)}."
    return f"{claim_id(capability, scale)} has no M1 hardening-accepted exact-scale evidence."


def claims_by_capability(manifest: dict[str, Any], capability: str) -> list[dict[str, Any]]:
    claims = manifest.get("claims", [])
    if not isinstance(claims, list):
        return []
    return [claim for claim in claims if isinstance(claim, dict) and claim.get("capability") == capability]
