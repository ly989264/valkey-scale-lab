#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valkey_scale_lab.management_matrix import REQUIRED_MANAGEMENT_OPERATIONS, RESHARD_REBALANCE_OPERATIONS, ROLLING_RESTART_OPERATIONS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-dir")
    parser.add_argument("--analysis")
    parser.add_argument("--report-index")
    parser.add_argument("--fixtures")
    args = parser.parse_args()
    errors: list[str] = []
    if args.fixtures:
        fixture_base = Path(args.fixtures)
        if not fixture_base.exists():
            errors.append(f"fixtures path missing: {fixture_base}")
        else:
            for case in sorted(path for path in fixture_base.iterdir() if path.is_dir()):
                expect_fail = case.name in {"empty", "missing_command_ref", "missing_required_operation"}
                case_errors = _validate_artifact_dir(case, validate_schema=True)
                if expect_fail and not case_errors:
                    errors.append(f"{case}: negative fixture unexpectedly passed")
                if not expect_fail and case_errors:
                    errors.extend(f"{case}: {error}" for error in case_errors)
    if args.artifacts_dir:
        errors.extend(_validate_artifact_dir(Path(args.artifacts_dir), validate_schema=True))
    if args.analysis:
        analysis = _load_json(Path(args.analysis), errors, "analysis")
        if analysis:
            management = analysis.get("management_ops")
            if not isinstance(management, dict):
                errors.append("analysis missing management_ops object")
            else:
                if management.get("operation_count") != len(REQUIRED_MANAGEMENT_OPERATIONS):
                    errors.append("analysis management_ops.operation_count does not cover all required operations")
                if management.get("missing_required_operations"):
                    errors.append(f"analysis has missing required management ops: {management.get('missing_required_operations')}")
                for key in ["duration_ranking_topN", "topology_diff_summary", "command_traceability", "reshard_rebalance_summary", "rolling_restart_summary"]:
                    if not management.get(key):
                        errors.append(f"analysis management_ops.{key} must be non-empty")
    if args.report_index:
        index_path = Path(args.report_index)
        report_index = _load_json(index_path, errors, "report index")
        if report_index:
            if "management_report_inputs" not in report_index:
                errors.append("report index missing management_report_inputs")
            report_dir = index_path.parent
            md = report_dir / "report.md"
            html = report_dir / "index.html"
            for path in [md, html]:
                if not path.exists():
                    errors.append(f"report output missing: {path}")
                else:
                    text = path.read_text(encoding="utf-8")
                    for needle in ["管理操作矩阵", "管理 topology diff 摘要"]:
                        if needle not in text:
                            errors.append(f"{path}: missing Chinese management section {needle}")
            report_names = {Path(item.get("path", "")).name for item in report_index.get("reports", []) if isinstance(item, dict)}
            for name in [
                "management_ops_matrix.csv",
                "management_operation_durations.csv",
                "management_topology_diffs.csv",
                "management_rolling_restart.csv",
                "management_reshard_rebalance.csv",
                "management_operation_duration.svg",
                "management_topology_diff.svg",
            ]:
                if name not in report_names:
                    errors.append(f"report index missing management output {name}")
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("PASS M1 management matrix contract")
    return 0


def _validate_artifact_dir(base: Path, *, validate_schema: bool) -> list[str]:
    errors: list[str] = []
    matrix = _load_json(base / "management_ops_matrix.json", errors, "management matrix")
    results = _load_jsonl(base / "management_operation_results.jsonl", errors, "management operation results")
    snapshots = _load_jsonl(base / "management_topology_snapshots.jsonl", errors, "management topology snapshots")
    diffs = _load_jsonl(base / "management_topology_diffs.jsonl", errors, "management topology diffs")
    command_rows = _load_jsonl(base / "command_log.jsonl", errors, "command log")
    workload = _load_json(base / "management_workload_impact.json", errors, "management workload impact")
    if validate_schema:
        _schema_check(ROOT / "schemas/artifact/management_ops_matrix.schema.json", base / "management_ops_matrix.json", errors)
        _schema_check(ROOT / "schemas/artifact/management_operation_result.schema.json", base / "management_operation_results.jsonl", errors)
        _schema_check(ROOT / "schemas/artifact/management_topology_diff.schema.json", base / "management_topology_diffs.jsonl", errors)
    if matrix:
        operations = matrix.get("operations")
        if not isinstance(operations, list) or not operations:
            errors.append(f"{base}: management_ops_matrix operations must be non-empty")
        observed = {row.get("operation_name") for row in operations if isinstance(row, dict)}
        missing = [name for name in REQUIRED_MANAGEMENT_OPERATIONS if name not in observed]
        if missing:
            errors.append(f"{base}: management_ops_matrix missing required operations: {missing}")
    if results:
        result_by_id = {row.get("operation_id"): row for row in results if isinstance(row, dict)}
        observed = {row.get("operation_name") for row in results if isinstance(row, dict)}
        missing = [name for name in REQUIRED_MANAGEMENT_OPERATIONS if name not in observed]
        if missing:
            errors.append(f"{base}: management_operation_results missing required operations: {missing}")
        snapshot_ids = {row.get("snapshot_id") for row in snapshots if isinstance(row, dict)}
        diff_ids = {row.get("operation_id") for row in diffs if isinstance(row, dict)}
        command_ids = {row.get("command_id") for row in command_rows if isinstance(row, dict)}
        workload_ids = {row.get("operation_id") for row in workload.get("operations", [])} if isinstance(workload.get("operations"), list) else set()
        for row in results:
            if not isinstance(row, dict):
                continue
            op = row.get("operation_name", "MISSING")
            opid = row.get("operation_id", "MISSING")
            for field in ["before_topology_snapshot", "after_topology_snapshot", "topology_diff", "slot_diff", "role_diff", "cleanup_ref", "workload_impact_ref"]:
                if not row.get(field):
                    errors.append(f"{base}: {opid} missing {field}")
            if row.get("operation_status") == "PASS" and int(row.get("command_count", 0) or 0) <= 0:
                errors.append(f"{base}: {opid} PASS operation has command_count <= 0")
            for ref in row.get("command_log_refs", []):
                command_id = str(ref).split("#", 1)[-1]
                if command_id not in command_ids:
                    errors.append(f"{base}: {opid} command ref does not resolve: {ref}")
            for ref_field in ["before_topology_snapshot_ref", "after_topology_snapshot_ref"]:
                snapshot_id = str(row.get(ref_field, "")).split("#", 1)[-1]
                if snapshot_id not in snapshot_ids:
                    errors.append(f"{base}: {opid} {ref_field} does not resolve: {row.get(ref_field)}")
            if opid not in diff_ids:
                errors.append(f"{base}: {opid} topology diff row missing")
            if opid not in workload_ids:
                errors.append(f"{base}: {opid} workload impact row missing")
            if op in RESHARD_REBALANCE_OPERATIONS:
                for field in ["slots_moved", "keys_moved", "bytes_migrated", "slot_balance_before", "slot_balance_after", "imbalance_delta"]:
                    if field not in row:
                        errors.append(f"{base}: {opid} reshard/rebalance missing {field}")
            if op in ROLLING_RESTART_OPERATIONS:
                for field in ["per_node_stop_ms", "per_node_restart_ms", "per_node_rejoin_ms", "per_node_unavailable_ms", "cluster_impact_ms"]:
                    if field not in row:
                        errors.append(f"{base}: {opid} rolling restart missing {field}")
        for matrix_row in matrix.get("operations", []) if isinstance(matrix, dict) else []:
            operation_id = matrix_row.get("operation_id")
            if operation_id not in result_by_id:
                errors.append(f"{base}: matrix row {operation_id} does not resolve to result")
    return errors


def _schema_check(schema: Path, instance: Path, errors: list[str]) -> None:
    if not instance.exists():
        errors.append(f"schema instance missing: {instance}")
        return
    cmd = [sys.executable, str(ROOT / "scripts/validate_json_schema.py"), "--schema", str(schema), "--instance", str(instance)]
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        errors.append(f"schema validation failed for {instance}: {result.stderr.strip() or result.stdout.strip()}")


def _load_json(path: Path, errors: list[str], label: str) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"{label} missing: {path}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{label} invalid JSON: {path}: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"{label} must be object: {path}")
        return {}
    return data


def _load_jsonl(path: Path, errors: list[str], label: str) -> list[dict[str, Any]]:
    if not path.exists():
        errors.append(f"{label} missing: {path}")
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                errors.append(f"{label} row {line_no} is not an object")
            else:
                rows.append(row)
    except json.JSONDecodeError as exc:
        errors.append(f"{label} invalid JSONL: {path}: {exc}")
    if not rows:
        errors.append(f"{label} must be non-empty: {path}")
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
