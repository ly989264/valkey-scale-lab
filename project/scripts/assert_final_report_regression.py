#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from codex_gate import phase_by_id, validate_artifact  # noqa: E402
from schema_validator import load_json  # noqa: E402

PHASE_ID = "P26_FINAL_REPORT_REGRESSION"
REQUIRED_REPORTS = {
    "reports/management_ops_matrix.md",
    "reports/failover_latency_curve.md",
    "reports/fault_matrix.md",
    "reports/workload_impact.md",
    "reports/final_goal_loop_report.md",
}
REQUIRED_EXPORTS = {
    "exports/management_ops_matrix.csv",
    "exports/failover_latency_curve.csv",
    "exports/fault_matrix.csv",
    "exports/workload_impact.csv",
}
REQUIRED_MANAGEMENT = {
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
}
REQUIRED_FAULTS = {
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
}
RENDERED_SOURCE_SUFFIXES = {".md", ".html", ".svg", ".csv", ".log"}
ALLOWED_SOURCE_SUFFIXES = {".json", ".jsonl"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        try:
            return path.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            return path.as_posix()


def read_csv_rows(path: Path, errors: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        errors.append(f"CSV missing: {rel(path)}")
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def assert_reasoned_missing(obj: Any, label: str, errors: list[str]) -> None:
    if isinstance(obj, dict):
        status = obj.get("status")
        value = obj.get("metric_value")
        if status in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"} and not obj.get("reason"):
            errors.append(f"{label}: {status} requires reason")
        if value == "MISSING" and not obj.get("missing_reason"):
            errors.append(f"{label}: MISSING metric_value requires missing_reason")
        for key, value_obj in obj.items():
            if isinstance(value_obj, str) and value_obj in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"}:
                reasons = obj.get("missing_reasons")
                if key != "status" and not obj.get("reason") and not (isinstance(reasons, dict) and reasons.get(key)):
                    errors.append(f"{label}.{key}: {value_obj} requires reason")
            assert_reasoned_missing(value_obj, f"{label}.{key}", errors)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            assert_reasoned_missing(item, f"{label}[{idx}]", errors)


def assert_final_report(phase_dir: Path, manifest_path: Path = ROOT / "codex" / "phase_manifest.json") -> list[str]:
    errors: list[str] = []
    final_index_path = phase_dir / "final_report_index.json"
    report_index_path = phase_dir / "report_index.json"
    csv_index_path = phase_dir / "csv_export_index.json"
    quant_path = phase_dir / "quant_summary.json"
    cleanup_path = phase_dir / "cleanup_report.json"

    manifest = load_json(manifest_path)
    phase = phase_by_id(manifest, PHASE_ID)
    default_phase_dir = ROOT / "artifacts" / "phases" / PHASE_ID
    for artifact in phase.get("required_artifacts", []):
        if artifact.get("required", True):
            artifact_path = ROOT / artifact["path"]
            if phase_dir.resolve() != default_phase_dir.resolve():
                artifact_path = phase_dir / Path(artifact["path"]).name
            errors.extend(validate_artifact(artifact_path, ROOT / artifact["schema"]))

    missing_core = []
    for path in [final_index_path, report_index_path, csv_index_path, quant_path, cleanup_path]:
        if not path.exists():
            missing_core.append(f"required P26 artifact missing: {rel(path)}")
    errors.extend(missing_core)
    if missing_core:
        return errors

    final_index = load_json(final_index_path)
    report_index = load_json(report_index_path)
    csv_index = load_json(csv_index_path)
    quant = load_json(quant_path)
    cleanup = load_json(cleanup_path)

    if report_index != final_index:
        errors.append("report_index.json must match final_report_index.json for P26")
    policy = final_index.get("derivation_policy", {})
    if policy.get("artifact_only") is not True:
        errors.append("final report derivation_policy.artifact_only must be true")
    if policy.get("log_parsing") is not False:
        errors.append("final report derivation_policy.log_parsing must be false")
    if policy.get("rendered_views_as_metric_sources") is not False:
        errors.append("rendered views must not be metric sources")
    if policy.get("source_scenarios_rerun") is not False:
        errors.append("P26 must record source_scenarios_rerun=false")

    report_paths = {_indexed_suffix(str(record.get("path", "")), "reports") for record in final_index.get("reports", [])}
    export_paths = {_indexed_suffix(str(record.get("path", "")), "exports") for record in final_index.get("exports", [])}
    if not REQUIRED_REPORTS.issubset(report_paths):
        errors.append(f"final index missing reports: {sorted(REQUIRED_REPORTS - report_paths)}")
    if not REQUIRED_EXPORTS.issubset(export_paths):
        errors.append(f"final index missing exports: {sorted(REQUIRED_EXPORTS - export_paths)}")

    for record in final_index.get("reports", []) + final_index.get("exports", []):
        path = ROOT / str(record.get("path", ""))
        if not path.exists():
            errors.append(f"indexed output missing: {record.get('path')}")
            continue
        if record.get("sha256") != sha256_file(path):
            errors.append(f"indexed output sha256 mismatch: {record.get('path')}")

    source_paths: set[str] = set()
    for idx, record in enumerate(final_index.get("source_artifacts", [])):
        path_text = str(record.get("path", ""))
        path = ROOT / path_text
        source_paths.add(path_text)
        if Path(path_text).suffix in RENDERED_SOURCE_SUFFIXES:
            errors.append(f"source_artifacts[{idx}] uses rendered/log source: {path_text}")
        if Path(path_text).suffix not in ALLOWED_SOURCE_SUFFIXES:
            errors.append(f"source_artifacts[{idx}] must be JSON/JSONL: {path_text}")
        if "P14_SCALE_1000_OPTIN_DRYRUN" in path_text:
            errors.append("P26 final report must not consume P14 real evidence")
        if not path.exists():
            errors.append(f"source_artifacts[{idx}] missing: {path_text}")
            continue
        if record.get("sha256") != sha256_file(path):
            errors.append(f"source_artifacts[{idx}] sha256 mismatch: {path_text}")

    management_csv = read_csv_rows(phase_dir / "exports" / "management_ops_matrix.csv", errors)
    management_present = {row.get("operation_name") for row in management_csv if row.get("status") == "PASS"}
    if not REQUIRED_MANAGEMENT.issubset(management_present):
        errors.append(f"management report missing rows: {sorted(REQUIRED_MANAGEMENT - management_present)}")

    failover_csv = read_csv_rows(phase_dir / "exports" / "failover_latency_curve.csv", errors)
    rung_counts: dict[int, int] = {}
    for row in failover_csv:
        try:
            rung = int(row.get("rung", "0"))
            sample_count = int(row.get("sample_count", "0"))
        except ValueError:
            errors.append(f"failover CSV has non-integer rung/sample_count: {row}")
            continue
        rung_counts[rung] = max(rung_counts.get(rung, 0), sample_count)
        if rung in {30, 50, 100, 200} and sample_count < 3:
            errors.append(f"failover rung {rung} requires at least 3 samples for every metric row")
    for rung in [30, 50, 100, 200]:
        if rung_counts.get(rung, 0) < 3:
            errors.append(f"failover rung {rung} requires at least 3 samples")

    fault_csv = read_csv_rows(phase_dir / "exports" / "fault_matrix.csv", errors)
    fault_present = {row.get("fault_row") for row in fault_csv if row.get("status") == "PASS"}
    if not REQUIRED_FAULTS.issubset(fault_present):
        errors.append(f"fault report missing rows: {sorted(REQUIRED_FAULTS - fault_present)}")

    workload_csv = read_csv_rows(phase_dir / "exports" / "workload_impact.csv", errors)
    if len(workload_csv) < 49:
        errors.append(f"workload impact export requires at least 49 rows, got {len(workload_csv)}")
    p24_rows = [row for row in workload_csv if row.get("source_stage_id") == "P24_PARTITION_SPLIT_BRAIN_MATRIX"]
    if len(p24_rows) < 6:
        errors.append("workload impact export must preserve at least 6 P24 rows")
    coverage = final_index.get("coverage_summary", {})
    if coverage.get("workload", {}).get("p24_error_taxonomy_present") is not True:
        errors.append("coverage summary must preserve P24 error taxonomy")

    export_tables = {record.get("table_name"): record for record in csv_index.get("exports", []) if isinstance(record, dict)}
    if set(export_tables) != {"management_ops_matrix", "failover_latency_curve", "fault_matrix", "workload_impact"}:
        errors.append(f"csv_export_index has wrong table set: {sorted(str(item) for item in export_tables)}")
    for table, record in export_tables.items():
        if record.get("row_count") != record.get("json_source_count"):
            errors.append(f"csv export {table}: row_count must equal json_source_count")
        path = ROOT / str(record.get("path", ""))
        if not path.exists():
            errors.append(f"csv export {table}: output missing")
        elif record.get("sha256") != sha256_file(path):
            errors.append(f"csv export {table}: sha256 mismatch")

    refs = {str(ref) for ref in quant.get("artifact_refs", [])}
    for required in [
        "final_report_index.json",
        "report_index.json",
        "csv_export_index.json",
        "reports/management_ops_matrix.md",
        "exports/workload_impact.csv",
        "P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/workload_impact_cross_stage.json",
    ]:
        if not any(required in ref for ref in refs):
            errors.append(f"quant_summary artifact_refs missing {required}")
    claims = quant.get("runtime_claims", {})
    if claims.get("real_valkey_claimed") is not True:
        errors.append("P26 quant_summary must claim current-stage real Valkey smoke evidence")
    if claims.get("management_runtime_claimed") is not False or claims.get("fault_runtime_claimed") is not False:
        errors.append("P26 quant_summary must not claim management/fault reruns")
    if claims.get("source_runtime_behavior_rerun") is not False:
        errors.append("P26 quant_summary must record source_runtime_behavior_rerun=false")

    assert_reasoned_missing(final_index, "final_report_index", errors)
    assert_reasoned_missing(quant, "quant_summary", errors)
    if cleanup.get("status") != "PASS":
        errors.append("cleanup_report status must be PASS")
    if cleanup.get("resources_remaining"):
        errors.append("cleanup_report resources_remaining must be empty")

    by_id = {item.get("id"): item for item in manifest.get("phases", [])}
    p14 = by_id.get("P14_SCALE_1000_OPTIN_DRYRUN")
    if not p14 or p14.get("automatic") is not False:
        errors.append("P14_SCALE_1000_OPTIN_DRYRUN must remain non-automatic")
    if manifest.get("default_max_nodes") != 100:
        errors.append("manifest default_max_nodes must remain 100")
    p26 = by_id.get(PHASE_ID)
    if not p26 or p26.get("max_nodes") != 100:
        errors.append("P26 max_nodes must remain 100")
    if manifest.get("automatic_stop_after") != PHASE_ID:
        errors.append("automatic_stop_after must remain P26_FINAL_REPORT_REGRESSION")
    return errors


def _indexed_suffix(path_text: str, dirname: str) -> str:
    parts = Path(path_text).parts
    if dirname in parts:
        idx = parts.index(dirname)
        return "/".join(parts[idx:])
    return path_text.split(f"{PHASE_ID}/", 1)[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--phase-dir")
    parser.add_argument("--manifest", default=str(ROOT / "codex" / "phase_manifest.json"))
    args = parser.parse_args()
    if args.phase != PHASE_ID:
        print(f"SKIP final report regression assertion not required for {args.phase}")
        return 0
    phase_dir = Path(args.phase_dir) if args.phase_dir else ROOT / "artifacts" / "phases" / args.phase
    errors = assert_final_report(phase_dir, Path(args.manifest))
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS final report regression phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
