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
    for row in results:
        if int(row.get("node_count", 0)) != args.scale:
            errors.append(f"{row.get('operation_id', '<unknown>')}: node_count must be {args.scale}")
        if row.get("operation_status") != "PASS":
            errors.append(f"{row.get('operation_id', '<unknown>')}: operation_status must be PASS")
        if row.get("real_execution_verified") is not True:
            errors.append(f"{row.get('operation_id', '<unknown>')}: real_execution_verified must be true")
    if errors:
        return print_errors(errors)
    print(f"PASS strict management matrix phase={args.phase} scale={args.scale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

