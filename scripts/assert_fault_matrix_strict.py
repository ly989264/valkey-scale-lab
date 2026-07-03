#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import load_jsonl, phase_dir, print_errors, rel, require_json  # noqa: E402

REQUIRED_ROWS = {
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
    "split_brain_window_detection",
    "fault_period_workload_impact",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--scale", type=int, required=True)
    parser.add_argument("--require-all-rows", action="store_true")
    args = parser.parse_args()
    base = phase_dir(args.phase)
    errors: list[str] = []
    report = require_json(base / "fault_matrix_report.json", errors, "fault matrix")
    try:
        rows = load_jsonl(base / "fault_operation_results.jsonl")
    except Exception as exc:
        rows = []
        errors.append(f"{rel(base / 'fault_operation_results.jsonl')}: {exc}")
    if report:
        entries = report.get("faults") or report.get("rows")
        if not isinstance(entries, list) or not entries:
            errors.append("fault_matrix_report rows must be non-empty")
        observed = {str(row.get("fault_name") or row.get("row_name")) for row in entries if row}
        if args.require_all_rows:
            missing = sorted(REQUIRED_ROWS - observed)
            if missing:
                errors.append(f"missing fault rows for scale {args.scale}: {missing}")
    for row in rows:
        if int(row.get("node_count", 0)) != args.scale:
            errors.append(f"{row.get('fault_id', '<unknown>')}: node_count must be {args.scale}")
        if row.get("status") != "PASS":
            errors.append(f"{row.get('fault_id', '<unknown>')}: status must be PASS")
        if row.get("real_execution_verified") is not True:
            errors.append(f"{row.get('fault_id', '<unknown>')}: real_execution_verified must be true")
    if errors:
        return print_errors(errors)
    print(f"PASS strict fault matrix phase={args.phase} scale={args.scale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

