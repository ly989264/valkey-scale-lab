#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import load_json, print_errors, rel, split_csv, strict_stage_doc  # noqa: E402

REGISTRY = ROOT / "artifacts" / "coverage" / "strict_coverage_registry.json"
BOOTSTRAP_STAGE_IDS = [
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
    "P38_CROSS_SCALE_ANALYSIS_REGRESSION",
    "P39_VISUAL_REPORT_QUALITY_GATE",
    "P40_STRICT_FINAL_AUDIT_CLOSEOUT",
]


def bootstrap_errors() -> list[str]:
    errors: list[str] = []
    for stage_id in BOOTSTRAP_STAGE_IDS:
        doc = strict_stage_doc(stage_id)
        if not doc.exists():
            errors.append(f"strict stage doc missing: {rel(doc)}")
    return errors


def registry_errors(args: argparse.Namespace) -> list[str]:
    errors: list[str] = []
    if not REGISTRY.exists():
        return [f"coverage registry missing: {rel(REGISTRY)}"]
    try:
        registry = load_json(REGISTRY)
    except Exception as exc:
        return [f"{rel(REGISTRY)}: invalid JSON: {exc}"]
    rows = registry.get("rows")
    if not isinstance(rows, list) or not rows:
        return [f"{rel(REGISTRY)}: rows must be a non-empty array"]
    scales = set(split_csv(args.scales) or ([str(args.scale)] if args.scale else []))
    for row in rows:
        required = ["coverage_id", "stage_id", "scale", "category", "execution_mode", "status", "source_artifacts", "validation_artifacts"]
        for key in required:
            if key not in row:
                errors.append(f"{row.get('coverage_id', '<unknown>')}: missing {key}")
        if args.phase and row.get("stage_id") == args.phase:
            if args.category and row.get("category") != args.category:
                continue
            if scales and str(row.get("scale")) not in scales:
                continue
            status = row.get("status")
            if row.get("execution_mode") == "real" and status == "PASS" and not row.get("source_artifacts"):
                errors.append(f"{row.get('coverage_id')}: PASS real row requires source artifacts")
            if row.get("execution_mode") == "dry_run" and status == "PASS":
                errors.append(f"{row.get('coverage_id')}: dry-run row must use DRY_RUN_PASS, not PASS")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap-only", action="store_true")
    parser.add_argument("--phase")
    parser.add_argument("--scale")
    parser.add_argument("--scales")
    parser.add_argument("--category")
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--require-final-real-scales", action="store_true")
    args = parser.parse_args()

    errors = bootstrap_errors() if args.bootstrap_only else registry_errors(args)
    if errors:
        return print_errors(errors)
    mode = "bootstrap" if args.bootstrap_only else "registry"
    print(f"PASS coverage {mode} assertion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

