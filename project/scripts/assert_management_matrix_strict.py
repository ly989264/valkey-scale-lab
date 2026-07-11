#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import load_jsonl, phase_dir, print_errors, rel, require_json  # noqa: E402

REQUIRED_ROWS = {
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

REQUIRED_RESULT_FIELDS = [
    "coverage_id",
    "operation_name",
    "operation_id",
    "scale",
    "node_count",
    "operation_status",
    "status_reason",
    "started_at_unix_ms",
    "ended_at_unix_ms",
    "wall_ms",
    "prepare_ms",
    "command_ms",
    "convergence_ms",
    "cleanup_ms",
    "cluster_state_before",
    "cluster_state_after",
    "cluster_known_nodes_before",
    "cluster_known_nodes_after",
    "cluster_slots_assigned_before",
    "cluster_slots_assigned_after",
    "cluster_slots_ok_before",
    "cluster_slots_ok_after",
    "slots_before",
    "slots_after",
    "slots_moved",
    "keys_moved",
    "bytes_migrated",
    "slot_balance_before",
    "slot_balance_after",
    "workload_window_ref",
    "errors_by_type",
    "topology_before_ref",
    "topology_after_ref",
    "command_log_ref",
    "source_evidence_ref",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--scale", type=int, required=True)
    parser.add_argument("--require-all-rows", action="store_true")
    args = parser.parse_args()
    base = phase_dir(args.phase)
    errors: list[str] = []
    matrix = require_json(base / "management_ops_matrix.json", errors, "management matrix")
    try:
        results = load_jsonl(base / "management_operation_results.jsonl")
    except Exception as exc:
        results = []
        errors.append(f"{rel(base / 'management_operation_results.jsonl')}: {exc}")
    if matrix:
        operations = matrix.get("operations")
        if not isinstance(operations, list) or not operations:
            errors.append("management_ops_matrix operations must be non-empty")
        observed = {str(row.get("operation_name") or row.get("row_name")) for row in operations if row}
        if args.require_all_rows:
            missing = sorted(REQUIRED_ROWS - observed)
            if missing:
                errors.append(f"missing management rows for scale {args.scale}: {missing}")
        for row in operations if isinstance(operations, list) else []:
            op_name = str(row.get("operation_name") or row.get("row_name") or "<unknown>")
            coverage_id = row.get("coverage_id")
            if coverage_id != f"{args.scale}.management.{op_name}":
                errors.append(f"{op_name}: coverage_id must be {args.scale}.management.{op_name}")
            if int(row.get("node_count", 0) or 0) != args.scale:
                errors.append(f"{op_name}: matrix node_count must be {args.scale}")
            if row.get("operation_status") != "PASS":
                errors.append(f"{op_name}: matrix operation_status must be PASS")
            if row.get("real_execution_verified") is not True:
                errors.append(f"{op_name}: matrix real_execution_verified must be true")
    for row in results:
        op_name = str(row.get("operation_name") or "<unknown>")
        coverage_id = row.get("coverage_id")
        for field in REQUIRED_RESULT_FIELDS:
            if field not in row:
                errors.append(f"{row.get('operation_id', '<unknown>')}: missing required field {field}")
            elif row[field] is None or row[field] == "" or row[field] == "SKIPPED_WITH_REASON":
                errors.append(f"{row.get('operation_id', '<unknown>')}: required field {field} has invalid missing value")
        if coverage_id != f"{args.scale}.management.{op_name}":
            errors.append(f"{row.get('operation_id', '<unknown>')}: coverage_id must be {args.scale}.management.{op_name}")
        if int(row.get("node_count", 0)) != args.scale:
            errors.append(f"{row.get('operation_id', '<unknown>')}: node_count must be {args.scale}")
        if row.get("operation_status") != "PASS":
            errors.append(f"{row.get('operation_id', '<unknown>')}: operation_status must be PASS")
        if row.get("real_execution_verified") is not True:
            errors.append(f"{row.get('operation_id', '<unknown>')}: real_execution_verified must be true")
        if row.get("workload_window_ref") in {None, "", "MISSING", "SKIPPED_WITH_REASON"}:
            errors.append(f"{row.get('operation_id', '<unknown>')}: workload_window_ref must reference measured workload")
        if not row.get("source_evidence_refs"):
            errors.append(f"{row.get('operation_id', '<unknown>')}: source_evidence_refs must be non-empty")
        if row.get("command_log_ref") in {None, "", "MISSING"}:
            errors.append(f"{row.get('operation_id', '<unknown>')}: command_log_ref is required")
        if row.get("topology_ref") in {None, "", "MISSING"}:
            errors.append(f"{row.get('operation_id', '<unknown>')}: topology_ref is required")
        if row.get("source_evidence_ref") in {None, "", "MISSING"}:
            errors.append(f"{row.get('operation_id', '<unknown>')}: source_evidence_ref is required")
        for field in ["slot_balance_before", "slot_balance_after"]:
            value = row.get(field)
            if not isinstance(value, dict) or value.get("status") != "PASS" or not isinstance(value.get("imbalance"), int):
                errors.append(f"{row.get('operation_id', '<unknown>')}: {field} must include PASS slot balance with integer imbalance")
        bytes_migrated = row.get("bytes_migrated")
        if isinstance(bytes_migrated, dict):
            if bytes_migrated.get("status") != "MISSING" or not bytes_migrated.get("reason"):
                errors.append(f"{row.get('operation_id', '<unknown>')}: bytes_migrated MISSING object requires reason")
        elif not isinstance(bytes_migrated, (int, float)):
            errors.append(f"{row.get('operation_id', '<unknown>')}: bytes_migrated must be numeric or MISSING object with reason")
    if args.require_all_rows:
        result_rows = {str(row.get("operation_name")) for row in results if row}
        missing_results = sorted(REQUIRED_ROWS - result_rows)
        if missing_results:
            errors.append(f"management_operation_results missing required rows: {missing_results}")
    if errors:
        return print_errors(errors)
    print(f"PASS strict management matrix phase={args.phase} scale={args.scale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
