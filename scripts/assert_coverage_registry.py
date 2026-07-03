#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_coverage_defs import (  # noqa: E402
    CSV_COLUMNS,
    DRY_RUN_SCALES,
    EXPECTED_COUNTS,
    EXPECTED_TOTAL_ROWS,
    REAL_SCALES,
    STRICT_COVERAGE_STAGE,
    expected_rows_by_id,
)
from strict_harness_lib import load_json, print_errors, rel, split_csv, strict_stage_doc  # noqa: E402

DEFAULT_REGISTRY = ROOT / "artifacts" / "coverage" / "strict_coverage_registry.json"
DEFAULT_SCENARIO_PLAN = ROOT / "artifacts" / "coverage" / "strict_scenario_plan.json"
DEFAULT_MATRIX_CSV = ROOT / "artifacts" / "coverage" / "strict_required_matrix.csv"
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
ID_RE = re.compile(r"^(50|100|200|201|250|300|500|1000)\.(lifecycle|management|fault|dry_run)\.[a-z0-9_]+$")
ALLOWED_STATUSES = {"PENDING", "PASS", "FAIL", "BLOCKED", "DRY_RUN_PASS", "MISSING"}
IMMUTABLE_FIELDS = {
    "coverage_id",
    "scale",
    "node_count",
    "category",
    "row_name",
    "stage_owner",
    "required",
    "execution_mode",
}


def bootstrap_errors() -> list[str]:
    errors: list[str] = []
    for stage_id in BOOTSTRAP_STAGE_IDS:
        doc = strict_stage_doc(stage_id)
        if not doc.exists():
            errors.append(f"strict stage doc missing: {rel(doc)}")
    return errors


def repo_path_errors(value: str, row_id: str, key: str) -> list[str]:
    if not value:
        return []
    p = Path(value)
    if p.is_absolute() or ".." in p.parts:
        return [f"{row_id}: {key} must be repository-relative and cannot escape repo: {value}"]
    return []


def load_registry(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.exists():
        return None, [f"coverage registry missing: {rel(path)}"]
    try:
        registry = load_json(path)
    except Exception as exc:
        return None, [f"{rel(path)}: invalid JSON: {exc}"]
    if not isinstance(registry, dict):
        return None, [f"{rel(path)}: expected JSON object"]
    rows = registry.get("rows")
    if not isinstance(rows, list) or not rows:
        return None, [f"{rel(path)}: rows must be a non-empty array"]
    return registry, []


def row_shape_errors(row: Any) -> list[str]:
    if not isinstance(row, dict):
        return ["registry row is not an object"]
    row_id = str(row.get("coverage_id", "<unknown>"))
    required = [
        "coverage_id",
        "scale",
        "node_count",
        "category",
        "row_name",
        "stage_owner",
        "required",
        "execution_mode",
        "status",
        "status_reason",
        "source_artifacts",
        "validation_artifacts",
        "metric_refs",
        "cleanup_ref",
        "review_ref",
        "commit_sha",
    ]
    errors: list[str] = []
    for key in required:
        if key not in row:
            errors.append(f"{row_id}: missing {key}")
    if errors:
        return errors
    if not isinstance(row["coverage_id"], str) or not ID_RE.match(row["coverage_id"]):
        errors.append(f"{row_id}: malformed deterministic coverage_id")
    if row["coverage_id"] != f"{row['scale']}.{row['category']}.{row['row_name']}":
        errors.append(f"{row_id}: coverage_id does not match scale/category/row_name")
    if row["scale"] != row["node_count"]:
        errors.append(f"{row_id}: node_count must equal scale")
    if row["category"] not in {"lifecycle", "management", "fault", "dry_run"}:
        errors.append(f"{row_id}: unsupported category {row['category']!r}")
    if row["execution_mode"] not in {"real", "dry_run"}:
        errors.append(f"{row_id}: invalid execution_mode {row['execution_mode']!r}")
    if row["status"] not in ALLOWED_STATUSES:
        errors.append(f"{row_id}: invalid status {row['status']!r}")
    if not isinstance(row["required"], bool) or row["required"] is not True:
        errors.append(f"{row_id}: required must be true for strict required rows")
    if not isinstance(row["stage_owner"], str) or not row["stage_owner"].startswith("P"):
        errors.append(f"{row_id}: stage_owner must be a strict stage id")
    if not isinstance(row["status_reason"], str) or not row["status_reason"].strip():
        errors.append(f"{row_id}: status_reason must be non-empty")
    for key in ["source_artifacts", "validation_artifacts", "metric_refs"]:
        value = row[key]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append(f"{row_id}: {key} must be an array of strings")
            continue
        for item in value:
            errors.extend(repo_path_errors(item, row_id, key))
    for key in ["cleanup_ref", "review_ref", "commit_sha"]:
        if not isinstance(row[key], str):
            errors.append(f"{row_id}: {key} must be a string")
    errors.extend(repo_path_errors(row["cleanup_ref"], row_id, "cleanup_ref"))
    errors.extend(repo_path_errors(row["review_ref"], row_id, "review_ref"))
    if row["execution_mode"] == "real" and row["status"] == "DRY_RUN_PASS":
        errors.append(f"{row_id}: real row cannot use DRY_RUN_PASS")
    if row["execution_mode"] == "dry_run" and row["status"] == "PASS":
        errors.append(f"{row_id}: dry-run row must use DRY_RUN_PASS, not PASS")
    if row["execution_mode"] == "real" and int(row["node_count"]) not in REAL_SCALES:
        errors.append(f"{row_id}: real execution is allowed only at 50, 100, or 200 nodes")
    if int(row["node_count"]) > 200 and row["execution_mode"] != "dry_run":
        errors.append(f"{row_id}: >200 rows must be dry_run")
    if row["status"] == "PASS" and (not row["source_artifacts"] or not row["validation_artifacts"]):
        errors.append(f"{row_id}: PASS requires source_artifacts and validation_artifacts")
    if row["status"] == "DRY_RUN_PASS" and (not row["validation_artifacts"] or not row["review_ref"]):
        errors.append(f"{row_id}: DRY_RUN_PASS requires validation_artifacts and review_ref")
    return errors


def expected_row_errors(rows: list[dict[str, Any]], require_all: bool, registry_stage: str | None) -> list[str]:
    errors: list[str] = []
    expected = expected_rows_by_id()
    observed = {row["coverage_id"]: row for row in rows if isinstance(row.get("coverage_id"), str)}
    if require_all:
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        if missing:
            errors.append(f"missing required coverage rows: {', '.join(missing)}")
        if extra:
            errors.append(f"unexpected coverage rows for strict registry: {', '.join(extra)}")
        if len(rows) != EXPECTED_TOTAL_ROWS:
            errors.append(f"registry must contain exactly {EXPECTED_TOTAL_ROWS} rows, found {len(rows)}")
    for coverage_id, spec in expected.items():
        row = observed.get(coverage_id)
        if not row:
            continue
        for key, expected_value in {
            "scale": spec.scale,
            "node_count": spec.scale,
            "category": spec.category,
            "row_name": spec.row_name,
            "stage_owner": spec.stage_owner,
            "execution_mode": spec.execution_mode,
        }.items():
            if row.get(key) != expected_value:
                errors.append(f"{coverage_id}: wrong {key}: expected {expected_value!r} got {row.get(key)!r}")
        if registry_stage == STRICT_COVERAGE_STAGE:
            if row.get("execution_mode") == "real" and row.get("status") != "PENDING":
                errors.append(f"{coverage_id}: P28 real rows must start PENDING")
            if row.get("execution_mode") == "dry_run" and row.get("status") != "PENDING":
                errors.append(f"{coverage_id}: P28 >200 dry-run rows must start PENDING until P37 proof exists")
    counts = {category: 0 for category in EXPECTED_COUNTS}
    for row in rows:
        category = row.get("category")
        if category in counts:
            counts[category] += 1
    for category, expected_count in EXPECTED_COUNTS.items():
        if require_all and counts[category] != expected_count:
            errors.append(f"{category}: expected {expected_count} rows, found {counts[category]}")
    return errors


def duplicate_errors(rows: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    errors: list[str] = []
    for row in rows:
        coverage_id = row.get("coverage_id")
        if not isinstance(coverage_id, str):
            continue
        if coverage_id in seen:
            errors.append(f"duplicate coverage_id: {coverage_id}")
        seen.add(coverage_id)
    return errors


def selected_rows(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    scales = set(split_csv(args.scales) or ([str(args.scale)] if args.scale else []))
    selected = []
    for row in rows:
        if args.phase and row.get("stage_owner") != args.phase:
            continue
        if args.category and row.get("category") != args.category:
            continue
        if scales and str(row.get("scale")) not in scales:
            continue
        selected.append(row)
    return selected


def final_status_errors(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[str]:
    errors: list[str] = []
    if args.phase or args.category or args.scale or args.scales:
        if not selected_rows(rows, args):
            errors.append("coverage selection matched no rows")
    if args.require_final_real_scales:
        for row in rows:
            if row.get("execution_mode") == "real" and row.get("category") in {"lifecycle", "management", "fault"}:
                if row.get("status") != "PASS":
                    errors.append(f"{row['coverage_id']}: final real scale row must be PASS")
                if not row.get("source_artifacts") or not row.get("validation_artifacts") or not row.get("review_ref"):
                    errors.append(f"{row['coverage_id']}: final PASS requires source, validation, and review refs")
    if args.require_dry_run_200_plus:
        for row in rows:
            if int(row.get("node_count", 0)) > 200:
                if row.get("execution_mode") != "dry_run":
                    errors.append(f"{row['coverage_id']}: >200 row must be dry_run")
                if row.get("status") != "DRY_RUN_PASS":
                    errors.append(f"{row['coverage_id']}: final >200 row must be DRY_RUN_PASS")
                joined = " ".join(row.get("validation_artifacts", []))
                if "no_runtime" not in joined:
                    errors.append(f"{row['coverage_id']}: DRY_RUN_PASS requires no-runtime proof artifact")
    return errors


def scenario_plan_errors(path: Path, rows: list[dict[str, Any]], require_all: bool) -> list[str]:
    if not path.exists():
        return [f"scenario plan missing: {rel(path)}"]
    try:
        plan = load_json(path)
    except Exception as exc:
        return [f"{rel(path)}: invalid JSON: {exc}"]
    scenarios = plan.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return [f"{rel(path)}: scenarios must be a non-empty array"]
    errors: list[str] = []
    covered: set[str] = set()
    scenario_ids: set[str] = set()
    required_fields = [
        "scenario_id",
        "stage_owner",
        "node_count",
        "execution_mode",
        "config_path",
        "resource_preflight_required",
        "workload_profile",
        "telemetry_policy",
        "operation_sequence",
        "fault_sequence",
        "timeout_policy",
        "cleanup_policy",
        "expected_artifacts",
        "coverage_ids",
        "safety_constraints",
    ]
    kinds = {"management": 0, "fault": 0, "full_flow": 0, "dry_run": 0}
    for scenario in scenarios:
        sid = str(scenario.get("scenario_id", "<unknown>"))
        if sid in scenario_ids:
            errors.append(f"{sid}: duplicate scenario_id")
        scenario_ids.add(sid)
        for key in required_fields:
            if key not in scenario:
                errors.append(f"{sid}: missing scenario field {key}")
        if errors and any(f"{sid}: missing scenario field" in e for e in errors):
            continue
        node_count = int(scenario["node_count"])
        if node_count > 200 and scenario["execution_mode"] != "dry_run":
            errors.append(f"{sid}: >200 scenarios must be dry_run")
        if scenario["execution_mode"] == "dry_run" and node_count <= 200:
            errors.append(f"{sid}: dry-run scenario must target >200")
        if scenario["resource_preflight_required"] is not True:
            errors.append(f"{sid}: resource_preflight_required must be true")
        for key in ["workload_profile", "telemetry_policy", "timeout_policy", "cleanup_policy"]:
            if not isinstance(scenario[key], dict) or not scenario[key]:
                errors.append(f"{sid}: {key} must be a non-empty object")
        for key in ["expected_artifacts", "coverage_ids", "safety_constraints"]:
            if not isinstance(scenario[key], list) or not scenario[key]:
                errors.append(f"{sid}: {key} must be a non-empty array")
        covered.update(str(item) for item in scenario["coverage_ids"])
        if sid.startswith("management_matrix_"):
            kinds["management"] += 1
        elif sid.startswith("fault_failover_matrix_"):
            kinds["fault"] += 1
        elif sid.startswith("full_flow_e2e_"):
            kinds["full_flow"] += 1
        elif sid.startswith("dry_run_"):
            kinds["dry_run"] += 1
        telemetry = scenario["telemetry_policy"]
        expected_artifacts = set(str(item) for item in scenario["expected_artifacts"])
        if scenario["execution_mode"] == "real":
            for key in ["required", "events_jsonl_required", "metrics_timeseries_jsonl_required", "workload_windows_required"]:
                if telemetry.get(key) is not True:
                    errors.append(f"{sid}: real scenario telemetry_policy.{key} must be true")
            for suffix in ["events.jsonl", "metrics_timeseries.jsonl", "workload_windows.json"]:
                expected = f"artifacts/phases/{scenario['stage_owner']}/{suffix}"
                if expected not in expected_artifacts:
                    errors.append(f"{sid}: expected_artifacts must include telemetry artifact {expected}")
        else:
            for key in ["required", "events_jsonl_required", "metrics_timeseries_jsonl_required", "workload_windows_required"]:
                if telemetry.get(key) is not False:
                    errors.append(f"{sid}: dry-run scenario telemetry_policy.{key} must be false")
    if require_all:
        expected_ids = {row["coverage_id"] for row in rows}
        missing = sorted(expected_ids - covered)
        unknown = sorted(covered - expected_ids)
        if missing:
            errors.append(f"scenario plan omits coverage IDs: {', '.join(missing)}")
        if unknown:
            errors.append(f"scenario plan references unknown coverage IDs: {', '.join(unknown)}")
        expected_kinds = {"management": 3, "fault": 3, "full_flow": 3, "dry_run": 5}
        for kind, expected_count in expected_kinds.items():
            if kinds[kind] != expected_count:
                errors.append(f"scenario plan expected {expected_count} {kind} scenarios, found {kinds[kind]}")
    return errors


def matrix_csv_errors(path: Path, rows: list[dict[str, Any]], require_all: bool) -> list[str]:
    if not path.exists():
        return [f"required matrix CSV missing: {rel(path)}"]
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            csv_rows = list(reader)
            fieldnames = reader.fieldnames or []
    except Exception as exc:
        return [f"{rel(path)}: invalid CSV: {exc}"]
    errors: list[str] = []
    if fieldnames != CSV_COLUMNS:
        errors.append(f"{rel(path)}: CSV columns must be exactly {CSV_COLUMNS}")
    if require_all and len(csv_rows) != len(rows):
        errors.append(f"{rel(path)}: expected {len(rows)} data rows, found {len(csv_rows)}")
    registry_ids = [row["coverage_id"] for row in rows]
    csv_ids = [row.get("coverage_id") for row in csv_rows]
    if require_all and csv_ids != registry_ids:
        errors.append(f"{rel(path)}: CSV coverage_id ordering must match registry rows")
    return errors


def registry_errors(args: argparse.Namespace) -> list[str]:
    registry_path = ROOT / args.registry if args.registry else DEFAULT_REGISTRY
    scenario_plan_path = ROOT / args.scenario_plan if args.scenario_plan else DEFAULT_SCENARIO_PLAN
    matrix_csv_path = ROOT / args.matrix_csv if args.matrix_csv else DEFAULT_MATRIX_CSV
    registry, errors = load_registry(registry_path)
    if errors or registry is None:
        return errors
    rows = registry["rows"]
    errors.extend(duplicate_errors(rows))
    for row in rows:
        errors.extend(row_shape_errors(row))
    errors.extend(expected_row_errors(rows, args.require_all, registry.get("stage_id")))
    errors.extend(final_status_errors(rows, args))
    errors.extend(scenario_plan_errors(scenario_plan_path, rows, args.require_all))
    errors.extend(matrix_csv_errors(matrix_csv_path, rows, args.require_all))
    return errors


def transition_errors(previous_path: Path, updated_path: Path) -> list[str]:
    previous, errors = load_registry(previous_path)
    updated, updated_errors = load_registry(updated_path)
    errors.extend(updated_errors)
    if errors or previous is None or updated is None:
        return errors
    prev_rows = {row["coverage_id"]: row for row in previous["rows"] if isinstance(row, dict) and "coverage_id" in row}
    next_rows = {row["coverage_id"]: row for row in updated["rows"] if isinstance(row, dict) and "coverage_id" in row}
    if set(prev_rows) != set(next_rows):
        return ["transition cannot add or remove coverage rows"]
    for coverage_id, before in prev_rows.items():
        after = next_rows[coverage_id]
        for field in IMMUTABLE_FIELDS:
            if before.get(field) != after.get(field):
                errors.append(f"{coverage_id}: immutable field changed: {field}")
        old = before.get("status")
        new = after.get("status")
        mode = before.get("execution_mode")
        if mode == "real" and new == "DRY_RUN_PASS":
            errors.append(f"{coverage_id}: real row cannot transition to DRY_RUN_PASS")
        if mode == "dry_run" and new == "PASS":
            errors.append(f"{coverage_id}: dry-run row cannot transition to PASS")
        if old == "PENDING":
            allowed = {"PENDING", "PASS", "FAIL", "BLOCKED", "MISSING"} if mode == "real" else {"PENDING", "DRY_RUN_PASS", "FAIL", "BLOCKED", "MISSING"}
            if new not in allowed:
                errors.append(f"{coverage_id}: forbidden transition {old}->{new}")
        if new in {"PASS", "DRY_RUN_PASS"}:
            if not after.get("validation_artifacts") or not after.get("review_ref"):
                errors.append(f"{coverage_id}: pass transition requires validation_artifacts and review_ref")
            if new == "PASS" and not after.get("source_artifacts"):
                errors.append(f"{coverage_id}: PASS transition requires source_artifacts")
        if old in {"PASS", "DRY_RUN_PASS"} and new != old and not after.get("status_reason"):
            errors.append(f"{coverage_id}: pass-state regression requires status_reason")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap-only", action="store_true")
    parser.add_argument("--phase")
    parser.add_argument("--scale")
    parser.add_argument("--scales")
    parser.add_argument("--category")
    parser.add_argument("--registry")
    parser.add_argument("--scenario-plan")
    parser.add_argument("--matrix-csv")
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--require-final-real-scales", action="store_true")
    parser.add_argument("--require-dry-run-200-plus", action="store_true")
    parser.add_argument("--previous")
    parser.add_argument("--updated")
    args = parser.parse_args()

    if args.previous or args.updated:
        if not args.previous or not args.updated:
            return print_errors(["transition validation requires both --previous and --updated"])
        errors = transition_errors(ROOT / args.previous, ROOT / args.updated)
    else:
        errors = bootstrap_errors() if args.bootstrap_only else registry_errors(args)
    if errors:
        return print_errors(errors)
    mode = "bootstrap" if args.bootstrap_only else "registry"
    if args.previous:
        mode = "transition"
    print(f"PASS coverage {mode} assertion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
