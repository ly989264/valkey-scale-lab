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
    "workload_benchmark": ["workload_windows.json", "metrics_timeseries.jsonl"],
    "fault_timeline": ["fault_timeline_report.json", "fault_timeline_events.jsonl", "failover_latency_samples.jsonl", "fault_sequence.json", "fault_command_log.jsonl"],
    "system_metrics": ["system_metrics_report.json", "system_metrics_timeseries.jsonl", "metrics_timeseries.jsonl"],
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
    "workload_benchmark": ["exact_scale_observed", "workload_windows_present", "qps_latency_error_metrics_present"],
    "fault_timeline": ["exact_scale_observed", "fault_timeline_present", "real_fault_events_present", "fake_or_partial_not_promoted"],
    "system_metrics": ["exact_scale_observed", "system_windows_present", "core_metrics_present"],
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
        checks["workload_windows_present"] = "workload_windows.json" in by_name
        checks["qps_latency_error_metrics_present"] = _jsonl_has_rows(paths, "metric")
    elif capability == "fault_timeline":
        checks["fault_timeline_present"] = any("fault" in path.name for path in paths)
        checks["real_fault_events_present"] = _jsonl_has_rows(paths, "fault") or "fault_sequence.json" in by_name
        checks["fake_or_partial_not_promoted"] = not _contains_fake_or_partial(root, paths)
    elif capability == "system_metrics":
        checks["system_windows_present"] = any(path.name in {"system_metrics_timeseries.jsonl", "metrics_timeseries.jsonl"} for path in paths)
        checks["core_metrics_present"] = _jsonl_has_rows(paths, "metric")
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
