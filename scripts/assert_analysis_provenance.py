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
    if args.report_index:
        require_json(ROOT / args.report_index, errors, "report index")
    if provenance:
        refs = provenance.get("source_artifacts")
        if not isinstance(refs, list) or not refs:
            errors.append("analysis_provenance source_artifacts must be non-empty")
        for ref in refs or []:
            if isinstance(ref, str) and not (ROOT / ref).exists():
                errors.append(f"analysis source artifact missing: {ref}")
        if provenance.get("invented_values_present") not in {False, 0}:
            errors.append("analysis_provenance must assert invented_values_present=false")
        if args.phase == P38:
            assert_p38_provenance(base, provenance, errors)
    if errors:
        return print_errors(errors)
    print(f"PASS analysis provenance phase={args.phase}")
    return 0


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
