#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import phase_dir, print_errors, require_json  # noqa: E402

P38 = "P38_CROSS_SCALE_ANALYSIS_REGRESSION"
P39 = "P39_VISUAL_REPORT_QUALITY_GATE"
P40 = "P40_STRICT_FINAL_AUDIT_CLOSEOUT"
P38_TABLES = [
    "coverage_heatmap_table.csv",
    "management_latency_table.csv",
    "management_convergence_table.csv",
    "failover_curve_table.csv",
    "fault_impact_table.csv",
    "workload_window_table.csv",
    "resource_usage_table.csv",
    "cleanup_table.csv",
    "missing_data_table.csv",
]
P38_REQUIRED_JSON = [
    "phase_summary.json",
    "cross_scale_analysis_summary.json",
    "analysis_provenance.json",
    "regression_baseline.json",
    "quant_summary.json",
]
FORBIDDEN_STRINGS = {"nan", "infinity", "-infinity", "undefined", "null"}
ALLOWED_SOURCE_STAGES = {
    "P30_MANAGEMENT_MATRIX_50_REAL",
    "P31_MANAGEMENT_MATRIX_100_REAL",
    "P32_MANAGEMENT_MATRIX_200_REAL",
    "P33_FAULT_FAILOVER_MATRIX_50_REAL",
    "P34_FAULT_FAILOVER_MATRIX_100_REAL",
    "P35_FAULT_FAILOVER_MATRIX_200_REAL",
    "P36_FULL_FLOW_E2E_50_100_200_REAL",
    "P37_200_PLUS_DRY_RUN_SUPPORT",
    "coverage_registry",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--report-index")
    args = parser.parse_args()
    base = phase_dir(args.phase)
    errors: list[str] = []
    provenance = require_json(base / "analysis_provenance.json", errors, "analysis provenance")
    report_index = None
    if args.report_index:
        report_index = require_json(ROOT / args.report_index, errors, "report index")
    if provenance:
        refs = provenance.get("source_artifacts")
        if not isinstance(refs, list) or not refs:
            errors.append("analysis_provenance source_artifacts must be non-empty")
        for ref in refs or []:
            if isinstance(ref, str) and not (ROOT / ref).exists():
                errors.append(f"analysis source artifact missing: {ref}")
            elif isinstance(ref, dict):
                path_text = ref.get("path")
                sha = ref.get("sha256")
                if not isinstance(path_text, str) or not path_text:
                    errors.append("analysis source artifact object missing path")
                    continue
                path = ROOT / path_text
                if not path.exists():
                    errors.append(f"analysis source artifact missing: {path_text}")
                elif sha and sha != sha256_file(path):
                    errors.append(f"analysis source artifact sha256 mismatch: {path_text}")
                if path_text.endswith(".log"):
                    errors.append(f"analysis source must not be a raw log: {path_text}")
            else:
                errors.append("analysis_provenance source_artifacts must contain strings or objects")
        if provenance.get("invented_values_present") not in {False, 0}:
            errors.append("analysis_provenance must assert invented_values_present=false")
        if args.phase == P38:
            assert_p38_provenance(base, provenance, errors)
        if args.phase == P39:
            assert_p39_provenance(base, provenance, report_index, errors)
        if args.phase == P40:
            assert_p40_provenance(base, provenance, errors)
    if errors:
        return print_errors(errors)
    print(f"PASS analysis provenance phase={args.phase}")
    return 0


def assert_p39_provenance(
    base: Path,
    provenance: dict[str, Any],
    report_index: dict[str, Any] | None,
    errors: list[str],
) -> None:
    if provenance.get("analysis_only") is not True or provenance.get("runtime_started") is not False:
        errors.append("analysis_provenance.json: P39 must assert analysis_only=true and runtime_started=false")
    for key in ["docker_started", "valkey_gate_started", "fault_injection_started", "unvalidated_logs_read", "invented_values_present"]:
        if provenance.get(key) not in {False, 0}:
            errors.append(f"analysis_provenance.json: P39 must assert {key}=false")
    if provenance.get("report_only") is not True:
        errors.append("analysis_provenance.json: P39 must assert report_only=true")

    source_artifacts = provenance.get("source_artifacts")
    if not isinstance(source_artifacts, list) or not source_artifacts:
        errors.append("analysis_provenance.json: P39 source_artifacts must be non-empty objects")
        source_artifacts = []
    source_paths: set[str] = set()
    for index, artifact in enumerate(source_artifacts, start=1):
        if not isinstance(artifact, dict):
            errors.append(f"P39 source_artifacts[{index}] must be an object")
            continue
        path_text = artifact.get("path")
        stage = artifact.get("source_stage")
        sha = artifact.get("sha256")
        if not isinstance(path_text, str) or not path_text:
            errors.append(f"P39 source_artifacts[{index}] missing path")
            continue
        if not path_text.startswith(f"artifacts/phases/{P38}/"):
            errors.append(f"P39 source must be a P38 artifact: {path_text}")
        if path_text.endswith((".log", ".stdout", ".stderr")):
            errors.append(f"P39 source must not be a raw log/runtime stream: {path_text}")
        path = ROOT / path_text
        if not path.exists():
            errors.append(f"P39 source artifact missing: {path_text}")
        elif sha != sha256_file(path):
            errors.append(f"P39 source artifact sha256 mismatch: {path_text}")
        if stage != P38:
            errors.append(f"P39 source artifact source_stage must be {P38}: {path_text}")
        source_paths.add(path_text)

    required_sources = {f"artifacts/phases/{P38}/{name}" for name in [*P38_TABLES, *P38_REQUIRED_JSON]}
    missing_sources = sorted(required_sources - source_paths)
    if missing_sources:
        errors.append(f"P39 source_artifacts missing required P38 artifacts: {missing_sources}")

    preserved = provenance.get("preserved_p38_source_artifacts")
    if not isinstance(preserved, list) or not preserved:
        errors.append("analysis_provenance.json: P39 must preserve P38 P30-P37 source provenance")
    else:
        for index, artifact in enumerate(preserved, start=1):
            if not isinstance(artifact, dict):
                errors.append(f"preserved_p38_source_artifacts[{index}] must be an object")
                continue
            path_text = artifact.get("path")
            stage = artifact.get("source_stage")
            if not isinstance(path_text, str) or not path_text:
                errors.append(f"preserved_p38_source_artifacts[{index}] missing path")
                continue
            if path_text.endswith((".log", ".stdout", ".stderr")):
                errors.append(f"P39 preserved source must not be raw log/runtime stream: {path_text}")
            if stage not in ALLOWED_SOURCE_STAGES:
                errors.append(f"P39 preserved source has disallowed source_stage {stage!r}: {path_text}")
            if not (ROOT / path_text).exists():
                errors.append(f"P39 preserved source artifact missing: {path_text}")

    output_artifacts = provenance.get("output_artifacts")
    if not isinstance(output_artifacts, list):
        errors.append("analysis_provenance.json: P39 output_artifacts must be a list")
        output_artifacts = []
    output_paths = {item.get("path") for item in output_artifacts if isinstance(item, dict)}
    required_outputs = {
        f"artifacts/phases/{P39}/phase_summary.json",
        f"artifacts/phases/{P39}/report_index.json",
        f"artifacts/phases/{P39}/report_quality_report.json",
        f"artifacts/phases/{P39}/final_report.md",
        f"artifacts/phases/{P39}/final_report.html",
        f"artifacts/phases/{P39}/visual_qa.md",
        f"artifacts/phases/{P39}/analysis_provenance.json",
        f"artifacts/phases/{P39}/quant_summary.json",
    }
    if report_index:
        for chart in report_index.get("charts", []):
            if isinstance(chart, dict) and isinstance(chart.get("path"), str):
                required_outputs.add(chart["path"])
    missing_outputs = sorted(required_outputs - output_paths)
    if missing_outputs:
        errors.append(f"P39 output_artifacts missing required outputs: {missing_outputs}")
    for artifact in output_artifacts:
        if not isinstance(artifact, dict):
            errors.append("P39 output_artifacts entries must be objects")
            continue
        path_text = artifact.get("path")
        if not isinstance(path_text, str) or not path_text:
            errors.append("P39 output artifact missing path")
            continue
        path = ROOT / path_text
        if not path.exists():
            errors.append(f"P39 output artifact missing: {path_text}")
        if path_text.endswith("analysis_provenance.json"):
            if artifact.get("sha256_status") != "SKIPPED_WITH_REASON" or not artifact.get("reason"):
                errors.append("P39 self-referential analysis_provenance output hash must be skipped with reason")
        elif path.exists() and artifact.get("sha256") != sha256_file(path):
            errors.append(f"P39 output artifact sha256 mismatch: {path_text}")

    if not report_index:
        errors.append("P39 requires --report-index for provenance validation")
        return
    if report_index.get("phase_id") != P39:
        errors.append("P39 report index phase_id mismatch")
    declared_report_sources = set()
    for item in report_index.get("source_artifacts", []):
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            declared_report_sources.add(item["path"])
    if declared_report_sources != source_paths:
        errors.append("P39 report_index source_artifacts must match analysis_provenance source_artifacts")
    for collection_name in ["sections", "charts", "tables"]:
        collection = report_index.get(collection_name, [])
        if not isinstance(collection, list):
            errors.append(f"P39 report_index {collection_name} must be a list")
            continue
        for index, item in enumerate(collection, start=1):
            if not isinstance(item, dict):
                errors.append(f"P39 report_index {collection_name}[{index}] must be object")
                continue
            sources = item.get("source_artifacts")
            if not isinstance(sources, list) or not sources:
                errors.append(f"P39 report_index {collection_name}[{index}] missing source_artifacts")
                continue
            for source in sources:
                if source not in source_paths:
                    errors.append(f"P39 report_index {collection_name}[{index}] source not declared in provenance: {source}")

    p38_summary_path = ROOT / f"artifacts/phases/{P38}/cross_scale_analysis_summary.json"
    if p38_summary_path.exists() and isinstance(report_index.get("coverage_totals"), dict):
        p38_summary = require_json(p38_summary_path, errors, "P38 cross-scale summary")
        if p38_summary and report_index["coverage_totals"] != p38_summary.get("counts"):
            errors.append("P39 report_index coverage_totals must match P38 counts")


def assert_p40_provenance(base: Path, provenance: dict[str, Any], errors: list[str]) -> None:
    expected_flags = {
        "analysis_only": True,
        "audit_only": True,
        "runtime_started": False,
        "docker_started": False,
        "valkey_gate_started": False,
        "fault_injection_started": False,
        "workload_started": False,
        "unvalidated_logs_read": False,
        "raw_log_sources_present": False,
        "invented_values_present": False,
    }
    for key, expected in expected_flags.items():
        if provenance.get(key) is not expected:
            errors.append(f"analysis_provenance.json: P40 must assert {key}={expected}")

    source_artifacts = provenance.get("source_artifacts")
    if not isinstance(source_artifacts, list) or not source_artifacts:
        errors.append("analysis_provenance.json: P40 source_artifacts must be non-empty objects")
        source_artifacts = []
    source_paths: set[str] = set()
    for index, artifact in enumerate(source_artifacts, start=1):
        if not isinstance(artifact, dict):
            errors.append(f"P40 source_artifacts[{index}] must be an object")
            continue
        path_text = artifact.get("path")
        sha = artifact.get("sha256")
        if not isinstance(path_text, str) or not path_text:
            errors.append(f"P40 source_artifacts[{index}] missing path")
            continue
        if path_text.endswith((".log", ".stdout", ".stderr")) or "/stdout/" in path_text or "/stderr/" in path_text:
            errors.append(f"P40 source must not be a raw log/runtime stream: {path_text}")
        path = ROOT / path_text
        if not path.exists():
            errors.append(f"P40 source artifact missing: {path_text}")
        elif sha != sha256_file(path):
            errors.append(f"P40 source artifact sha256 mismatch: {path_text}")
        source_paths.add(path_text)

    required_sources = {
        "codex/phase_manifest.json",
        "codex/status/phase_state.json",
        "artifacts/coverage/strict_coverage_registry.json",
        "artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md",
        f"artifacts/phases/{P38}/cross_scale_analysis_summary.json",
        f"artifacts/phases/{P38}/analysis_provenance.json",
        f"artifacts/phases/{P39}/report_index.json",
        f"artifacts/phases/{P39}/report_quality_report.json",
        f"artifacts/phases/{P39}/analysis_provenance.json",
    }
    for stage_id in [
        "P27_STRICT_MATRIX_REBASE_HARNESS",
        "P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER",
        "P29_QUANT_TELEMETRY_COLLECTOR_HARDENING",
        "P30_MANAGEMENT_MATRIX_50_REAL",
        "P31_MANAGEMENT_MATRIX_100_REAL",
        "P32_MANAGEMENT_MATRIX_200_REAL",
        "P33_FAULT_FAILOVER_MATRIX_50_REAL",
        "P34_FAULT_FAILOVER_MATRIX_100_REAL",
        "P35_FAULT_FAILOVER_MATRIX_200_REAL",
        "P36_FULL_FLOW_E2E_50_100_200_REAL",
        "P37_200_PLUS_DRY_RUN_SUPPORT",
        P38,
        P39,
    ]:
        required_sources.update(
            {
                f"artifacts/gates/{stage_id}/gate_result.json",
                f"artifacts/goal_loop_strict/{stage_id}/REVIEW.md",
                f"artifacts/goal_loop_strict/{stage_id}/COMPLETION.md",
                f"audit/{stage_id}/audit_decision.json",
            }
        )
    missing_sources = sorted(required_sources - source_paths)
    if missing_sources:
        errors.append(f"P40 source_artifacts missing required sources: {missing_sources}")

    output_artifacts = provenance.get("output_artifacts")
    if not isinstance(output_artifacts, list):
        errors.append("analysis_provenance.json: P40 output_artifacts must be a list")
        output_artifacts = []
    output_paths = {item.get("path") for item in output_artifacts if isinstance(item, dict)}
    required_outputs = {
        f"artifacts/phases/{P40}/phase_summary.json",
        f"artifacts/phases/{P40}/final_strict_audit_report.json",
        f"artifacts/phases/{P40}/final_coverage_verdict.json",
        f"artifacts/phases/{P40}/final_artifact_manifest.json",
        f"artifacts/phases/{P40}/final_no_bypass_report.json",
        f"artifacts/phases/{P40}/final_report_quality_verdict.json",
        f"artifacts/phases/{P40}/analysis_provenance.json",
        f"artifacts/phases/{P40}/quant_summary.json",
        f"artifacts/phases/{P40}/FINAL_STRICT_SUMMARY.md",
    }
    missing_outputs = sorted(required_outputs - output_paths)
    if missing_outputs:
        errors.append(f"P40 output_artifacts missing required outputs: {missing_outputs}")
    for artifact in output_artifacts:
        if not isinstance(artifact, dict):
            errors.append("P40 output_artifacts entries must be objects")
            continue
        path_text = artifact.get("path")
        if not isinstance(path_text, str) or not path_text:
            errors.append("P40 output artifact missing path")
            continue
        path = ROOT / path_text
        if not path.exists():
            errors.append(f"P40 output artifact missing: {path_text}")
            continue
        if path_text.endswith("analysis_provenance.json"):
            if artifact.get("sha256_status") != "SKIPPED_WITH_REASON" or not artifact.get("reason"):
                errors.append("P40 self-referential analysis_provenance output hash must be skipped with reason")
        elif artifact.get("sha256") != sha256_file(path):
            errors.append(f"P40 output artifact sha256 mismatch: {path_text}")


def assert_p38_provenance(base: Path, provenance: dict[str, Any], errors: list[str]) -> None:
    if provenance.get("analysis_only") is not True or provenance.get("runtime_started") is not False:
        errors.append("analysis_provenance.json: P38 must assert analysis_only=true and runtime_started=false")
    if provenance.get("unvalidated_logs_read") is not False:
        errors.append("analysis_provenance.json: P38 must assert unvalidated_logs_read=false")

    source_artifacts = provenance.get("source_artifacts")
    if not isinstance(source_artifacts, list) or not source_artifacts:
        errors.append("analysis_provenance.json: P38 source_artifacts must be non-empty objects")
        source_artifacts = []
    source_paths: set[str] = set()
    for index, artifact in enumerate(source_artifacts, start=1):
        if not isinstance(artifact, dict):
            errors.append(f"analysis_provenance source_artifacts[{index}] must be an object")
            continue
        path_text = artifact.get("path")
        sha = artifact.get("sha256")
        stage = artifact.get("source_stage")
        if not isinstance(path_text, str) or not path_text:
            errors.append(f"analysis_provenance source_artifacts[{index}] missing path")
            continue
        if path_text.endswith(".log"):
            errors.append(f"analysis source must not be a raw log: {path_text}")
        if "artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT" in path_text and path_text.endswith((".stdout", ".stderr")):
            errors.append(f"P37 raw runtime output must not be a source: {path_text}")
        path = ROOT / path_text
        if not path.exists():
            errors.append(f"analysis source artifact missing: {path_text}")
        elif sha != sha256_file(path):
            errors.append(f"analysis source artifact sha256 mismatch: {path_text}")
        if stage not in ALLOWED_SOURCE_STAGES:
            errors.append(f"analysis source artifact has disallowed source_stage {stage!r}: {path_text}")
        source_paths.add(path_text)

    output_artifacts = provenance.get("output_artifacts")
    if not isinstance(output_artifacts, list):
        errors.append("analysis_provenance.json: output_artifacts must be a list")
        output_artifacts = []
    output_paths = {item.get("path") for item in output_artifacts if isinstance(item, dict)}
    for name in [*P38_TABLES, *P38_REQUIRED_JSON]:
        path_text = f"artifacts/phases/{P38}/{name}"
        if path_text not in output_paths:
            errors.append(f"analysis_provenance.json: output_artifacts missing {path_text}")
        if not (ROOT / path_text).exists():
            errors.append(f"P38 output missing: {path_text}")

    row_provenance = provenance.get("row_provenance")
    if not isinstance(row_provenance, list) or not row_provenance:
        errors.append("analysis_provenance.json: row_provenance must be non-empty")
        row_provenance = []
    provenance_keys = set()
    for index, row in enumerate(row_provenance, start=1):
        if not isinstance(row, dict):
            errors.append(f"row_provenance[{index}] must be an object")
            continue
        table = str(row.get("table", ""))
        coverage_id = str(row.get("coverage_id", ""))
        source_artifact = str(row.get("source_artifact", ""))
        method = str(row.get("method", ""))
        if table not in P38_TABLES:
            errors.append(f"row_provenance[{index}] has unexpected table {table!r}")
        if not coverage_id or coverage_id == "MISSING":
            errors.append(f"row_provenance[{index}] requires coverage_id")
        if source_artifact not in source_paths:
            errors.append(f"row_provenance[{index}] source_artifact not declared: {source_artifact}")
        if not method or method == "MISSING":
            errors.append(f"row_provenance[{index}] requires method")
        provenance_keys.add((table, coverage_id, source_artifact))

    for table in P38_TABLES:
        table_path = base / table
        rows = load_csv(table_path, errors)
        if not rows:
            errors.append(f"{table}: must be non-empty")
            continue
        for line_no, row in enumerate(rows, start=2):
            assert_no_forbidden_values(row, f"{table}:{line_no}", errors)
            coverage_id = row.get("coverage_id", "")
            source_artifact = row.get("source_artifact", "")
            method = row.get("method", "")
            if not coverage_id or coverage_id == "MISSING":
                errors.append(f"{table}:{line_no}: coverage_id required")
            if not source_artifact:
                errors.append(f"{table}:{line_no}: source_artifact required")
            elif source_artifact not in source_paths:
                errors.append(f"{table}:{line_no}: source_artifact not declared in provenance: {source_artifact}")
            if not method or method == "MISSING":
                errors.append(f"{table}:{line_no}: method required")
            if (table, coverage_id, source_artifact) not in provenance_keys:
                errors.append(f"{table}:{line_no}: matching row_provenance entry missing")

    for table in ["failover_curve_table.csv"]:
        for line_no, row in enumerate(load_csv(base / table, errors), start=2):
            if not row.get("percentile_method") or row.get("percentile_method") == "MISSING":
                errors.append(f"{table}:{line_no}: percentile_method required")
            if not row.get("delta_method") or row.get("delta_method") == "MISSING":
                errors.append(f"{table}:{line_no}: delta_method required")
    for line_no, row in enumerate(load_csv(base / "coverage_heatmap_table.csv", errors), start=2):
        scale = int(row.get("scale") or 0)
        mode = row.get("execution_mode")
        status = row.get("status")
        category = row.get("category")
        if scale in {50, 100, 200} and (mode != "real" or status != "PASS"):
            errors.append(f"coverage_heatmap_table.csv:{line_no}: real 50/100/200 rows must remain PASS real")
        if scale > 200 and (category != "dry_run" or mode != "dry_run" or status != "DRY_RUN_PASS"):
            errors.append(f"coverage_heatmap_table.csv:{line_no}: >200 rows must remain dry-run-only")


def load_csv(path: Path, errors: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        errors.append(f"missing P38 table: {path.relative_to(ROOT).as_posix()}")
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_no_forbidden_values(value: Any, label: str, errors: list[str]) -> None:
    if value is None:
        errors.append(f"{label}: null is forbidden")
    elif isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{label}: NaN/Infinity is forbidden")
    elif isinstance(value, str) and value.lower() in FORBIDDEN_STRINGS:
        errors.append(f"{label}: forbidden placeholder string {value!r}")
    elif isinstance(value, dict):
        for key, item in value.items():
            assert_no_forbidden_values(item, f"{label}.{key}", errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_forbidden_values(item, f"{label}[{index}]", errors)


if __name__ == "__main__":
    raise SystemExit(main())
