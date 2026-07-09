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
    "setup_telemetry": ["real_valkey_verified", "exact_scale_observed", "valkey_9_1_verified", "setup_core_metrics_present"],
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
    evidence_kind = _evidence_kind(source_artifacts, semantic_checks)
    status = "PASS" if _claim_passes(evidence_kind, semantic_checks) else "BLOCKED_WITH_REASON"
    blocked_reason = None
    if status != "PASS":
        blocked_reason = _blocked_reason(capability, scale, evidence_kind, semantic_checks)
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
        checks["setup_core_metrics_present"] = any("runtime_timing_breakdown" in path.name for path in paths)
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

    # H00 intentionally does not certify historical artifacts as complete M1 hardening evidence.
    checks["m1_format_fields_complete"] = all(bool(checks.get(name)) for name in CAPABILITY_REQUIRED_CHECKS[capability])
    checks["hardening_stage_accepted"] = False
    return checks


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


def _evidence_kind(source_artifacts: list[str], semantic_checks: dict[str, Any]) -> str:
    if not source_artifacts:
        return "BLOCKED_WITH_REASON"
    lowered = [path.lower() for path in source_artifacts]
    if all("tests/fixtures/" in path for path in lowered):
        return "FIXTURE_ONLY"
    if all("dryrun" in path or "dry_run" in path for path in lowered):
        return "DRY_RUN_ONLY"
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
