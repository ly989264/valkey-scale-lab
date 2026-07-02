#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from codex_gate import validate_artifact  # noqa: E402
from schema_validator import load_json  # noqa: E402

REQUIRED_OPS = {
    "P17_MANAGEMENT_REMOVE_NODE": {"remove_replica", "remove_primary_drained", "remove_failed_node"},
    "P18_MANAGEMENT_RESHARD_REBALANCE": {"reshard_slot_range", "reshard_with_keys", "rebalance_after_imbalance"},
    "P19_MANAGEMENT_ROLLING_RESTART": {"rolling_restart_replica_first", "rolling_restart_primary_safe"},
}

REQUIRED_ROWS = {
    "P17_MANAGEMENT_REMOVE_NODE": {
        ("remove_replica", 6),
        ("remove_replica", 10),
        ("remove_primary_drained", 6),
        ("remove_primary_drained", 10),
        ("remove_failed_node", 6),
        ("remove_failed_node", 10),
    },
    "P18_MANAGEMENT_RESHARD_REBALANCE": {
        ("reshard_slot_range", 6),
        ("reshard_slot_range", 10),
        ("reshard_with_keys", 6),
        ("reshard_with_keys", 10),
        ("rebalance_after_imbalance", 6),
        ("rebalance_after_imbalance", 10),
    }
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    required_ops = REQUIRED_OPS.get(args.phase)
    if not required_ops:
        print(f"PASS management coverage not required for phase={args.phase}")
        return 0

    base = ROOT / "artifacts" / "phases" / args.phase
    errors: list[str] = []
    matrix = base / "management_ops_matrix.json"
    results = base / "management_operation_results.jsonl"
    errors.extend(validate_artifact(matrix, ROOT / "schemas/artifact/management_ops_matrix.schema.json"))
    errors.extend(validate_artifact(results, ROOT / "schemas/artifact/management_operation_result.schema.json"))
    slot_movements_path = base / "reshard_slot_movements.jsonl"
    rebalance_path = base / "rebalance_summary.json"
    if args.phase == "P18_MANAGEMENT_RESHARD_REBALANCE":
        errors.extend(validate_artifact(slot_movements_path, ROOT / "schemas/artifact/slot_movement.schema.json"))
        errors.extend(validate_artifact(rebalance_path, ROOT / "schemas/artifact/rebalance_summary.schema.json"))
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rows = load_jsonl(results)
    slot_movements = load_jsonl(slot_movements_path) if args.phase == "P18_MANAGEMENT_RESHARD_REBALANCE" and slot_movements_path.exists() else []
    required_rows = REQUIRED_ROWS.get(args.phase)
    if required_rows:
        observed_rows = {(row.get("operation_name"), row.get("node_count")) for row in rows}
        missing_rows = sorted(required_rows - observed_rows)
        if missing_rows:
            errors.append(f"missing required operation/node_count rows: {missing_rows}")
        matrix_rows = {
            (row.get("operation_name"), row.get("node_count"))
            for row in load_json(matrix).get("operations", [])
        }
        matrix_missing = sorted(required_rows - matrix_rows)
        if matrix_missing:
            errors.append(f"management_ops_matrix missing required rows: {matrix_missing}")
    else:
        observed_ops = {row.get("operation_name") for row in rows}
        missing = sorted(required_ops - observed_ops)
        if missing:
            errors.append(f"missing required operation rows: {missing}")
    for row in rows:
        label = f"{row.get('operation_name')}[{row.get('node_count')}]"
        status = row.get("operation_status")
        if required_rows and (row.get("operation_name"), row.get("node_count")) in required_rows and status != "PASS":
            errors.append(f"{label}: required P17 row must PASS, got {status}")
        if status == "PASS" and row.get("real_execution_verified") is not True:
            errors.append(f"{label}: PASS requires real_execution_verified=true")
        if status in {"SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON", "MISSING"} and not row.get("reason"):
            errors.append(f"{label}: {status} requires reason")
        if status == "PASS":
            for field in ["started_at_unix_ms", "ended_at_unix_ms", "wall_ms", "command_ms", "convergence_ms"]:
                if row.get(field) == "MISSING":
                    errors.append(f"{label}: PASS cannot have MISSING {field}")
            if required_rows and (row.get("operation_name"), row.get("node_count")) in required_rows:
                if row.get("removed_node_absent") is not True:
                    if args.phase == "P17_MANAGEMENT_REMOVE_NODE":
                        errors.append(f"{label}: removed_node_absent must be true")
                if row.get("cluster_state_before") != "ok":
                    errors.append(f"{label}: cluster_state_before must be ok")
                if row.get("cluster_state_after") != "ok":
                    errors.append(f"{label}: cluster_state_after must be ok")
                if row.get("slots_before") != 16384:
                    errors.append(f"{label}: slots_before must be 16384")
                if row.get("slots_after") != 16384:
                    errors.append(f"{label}: slots_after must be 16384")
                if row.get("sidecar_cleanup_status") != "PASS":
                    errors.append(f"{label}: sidecar_cleanup_status must be PASS")
                if args.phase == "P17_MANAGEMENT_REMOVE_NODE":
                    if row.get("observed_nodes_after") != int(row.get("node_count", 0)) - 1:
                        errors.append(f"{label}: observed_nodes_after must equal node_count - 1")
                    cleanup = row.get("removed_resource_cleanup")
                    if not isinstance(cleanup, dict) or cleanup.get("status") != "PASS":
                        errors.append(f"{label}: removed_resource_cleanup.status must be PASS")
                    if not row.get("removed_node_id"):
                        errors.append(f"{label}: removed_node_id required")
                    if not row.get("target_logical_id"):
                        errors.append(f"{label}: target_logical_id required")
                if args.phase == "P18_MANAGEMENT_RESHARD_REBALANCE":
                    if int(row.get("slots_moved", 0) or 0) <= 0:
                        errors.append(f"{label}: slots_moved must be > 0")
                    if row.get("slot_coverage_complete") is not True:
                        errors.append(f"{label}: slot_coverage_complete must be true")
                    if row.get("post_move_writable") is not True:
                        errors.append(f"{label}: post_move_writable must be true")
                    if not row.get("source_node_id") or not row.get("target_node_id"):
                        errors.append(f"{label}: source_node_id and target_node_id required")
                    if not row.get("movement_ids"):
                        errors.append(f"{label}: movement_ids required")
                    if row.get("operation_name") == "reshard_with_keys":
                        if int(row.get("keys_moved", 0) or 0) <= 0:
                            errors.append(f"{label}: keys_moved must be > 0")
                        if row.get("moved_keys_readable") is not True:
                            errors.append(f"{label}: moved_keys_readable must be true")
                    if row.get("operation_name") == "rebalance_after_imbalance":
                        before = row.get("imbalance_before")
                        after = row.get("imbalance_after")
                        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)) or not before > after:
                            errors.append(f"{label}: imbalance_before must be greater than imbalance_after")
        if not row.get("workload_window_ref"):
            errors.append(f"{label}: workload_window_ref required")
        if not isinstance(row.get("errors_by_type"), dict):
            errors.append(f"{label}: errors_by_type must be object")

    if args.phase == "P18_MANAGEMENT_RESHARD_REBALANCE":
        if not slot_movements:
            errors.append("P18 requires non-empty reshard_slot_movements.jsonl")
        movement_ops = {row.get("operation_id") for row in slot_movements}
        expected_ops = {f"{op}-{count:02d}" for op, count in REQUIRED_ROWS[args.phase]}
        missing_movement_ops = sorted(expected_ops - movement_ops)
        if missing_movement_ops:
            errors.append(f"P18 slot movements missing operation ids: {missing_movement_ops}")
        for movement in slot_movements:
            label = str(movement.get("movement_id", "unknown"))
            if movement.get("status") != "PASS":
                errors.append(f"{label}: slot movement status must be PASS")
            if int(movement.get("slot_count", 0) or 0) <= 0:
                errors.append(f"{label}: slot_count must be > 0")
            if not movement.get("source_node_id") or not movement.get("target_node_id"):
                errors.append(f"{label}: source_node_id and target_node_id required")
        if rebalance_path.exists():
            rebalance = load_json(rebalance_path)
            if rebalance.get("status") != "PASS":
                errors.append("rebalance_summary status must be PASS")
            before = rebalance.get("imbalance_before")
            after = rebalance.get("imbalance_after")
            if not isinstance(before, (int, float)) or not isinstance(after, (int, float)) or not before > after:
                errors.append("rebalance_summary imbalance_before must be greater than imbalance_after")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS management operation coverage phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
