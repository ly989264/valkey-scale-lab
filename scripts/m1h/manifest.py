#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from common import read_json, read_jsonl, relpath, source_commit, utc_now

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
    "command_audit": ["command_audit_summary.json", "command_log.jsonl", "management_command_log.jsonl", "fault_command_log.jsonl"],
    "management_matrix": [
        "management_ops_matrix.json",
        "management_operation_results.jsonl",
        "management_topology_snapshots.jsonl",
        "management_workload_impact.json",
        "management_command_log.jsonl",
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
    "command_audit": ["exact_scale_observed", "command_log_present", "required_command_kinds_present"],
    "management_matrix": ["exact_scale_observed", "management_matrix_present", "operation_semantics_present", "workload_telemetry_present"],
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
    existing = [path for path in candidate_paths if path.exists() and (not path.is_file() or path.stat().st_size > 0)]
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
        checks["command_log_present"] = any(path.suffix == ".jsonl" and "command" in path.name for path in paths)
        checks["required_command_kinds_present"] = _jsonl_has_rows(paths, "command")
    elif capability == "management_matrix":
        matrix = read_json(by_name.get("management_ops_matrix.json", Path()))
        operations = matrix.get("operations", []) if isinstance(matrix, dict) else []
        checks["management_matrix_present"] = bool(operations)
        checks["operation_semantics_present"] = bool(operations) and all(
            isinstance(row, dict)
            and row.get("operation_status") == "PASS"
            and row.get("real_execution_verified") is True
            and row.get("command_log_ref")
            for row in operations
        )
        checks["workload_telemetry_present"] = any(path.name == "workload_windows.json" for path in paths)
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
