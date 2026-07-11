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
NETWORK_ROWS = {
    "network_delay",
    "network_loss",
    "network_flap",
    "network_partition",
    "minority_partition",
    "majority_partition",
}
PARTITION_ROWS = {"network_partition", "minority_partition", "majority_partition"}
ALLOWED_NETWORK_PATHS = {"sandbox_proxy", "container_netns_tc"}
STRICT_FAULT_STAGES = {
    "P33_FAULT_FAILOVER_MATRIX_50_REAL": 50,
    "P34_FAULT_FAILOVER_MATRIX_100_REAL": 100,
    "P35_FAULT_FAILOVER_MATRIX_200_REAL": 200,
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
    workload = require_json(base / "fault_workload_impact.json", errors, "fault workload impact")
    split_brain = require_json(base / "split_brain_report.json", errors, "split brain report")
    partition = require_json(base / "partition_report.json", errors, "partition report")
    try:
        rows = load_jsonl(base / "fault_operation_results.jsonl")
    except Exception as exc:
        rows = []
        errors.append(f"{rel(base / 'fault_operation_results.jsonl')}: {exc}")
    if report:
        if args.phase in STRICT_FAULT_STAGES and STRICT_FAULT_STAGES[args.phase] != args.scale:
            errors.append(f"{args.phase} requires --scale {STRICT_FAULT_STAGES[args.phase]}")
        if int(report.get("node_count", 0) or 0) != args.scale or int(report.get("scale", 0) or 0) != args.scale:
            errors.append("fault_matrix_report scale and node_count must match requested scale")
        if report.get("status") != "PASS":
            errors.append("fault_matrix_report status must be PASS")
        entries = report.get("fault_rows") or report.get("faults") or report.get("rows")
        if not isinstance(entries, list) or not entries:
            errors.append("fault_matrix_report rows must be non-empty")
        observed = {str(row.get("fault_type") or row.get("fault_name") or row.get("row_name")) for row in entries if row}
        if args.require_all_rows:
            missing = sorted(REQUIRED_ROWS - observed)
            if missing:
                errors.append(f"missing fault rows for scale {args.scale}: {missing}")
            extra = sorted(observed - REQUIRED_ROWS)
            if extra:
                errors.append(f"unexpected fault rows for scale {args.scale}: {extra}")
    rows_by_name = {str(row.get("row_name") or row.get("fault_type")): row for row in rows}
    if args.require_all_rows:
        for name in REQUIRED_ROWS:
            if name not in rows_by_name:
                errors.append(f"fault_operation_results missing row {name}")
    for row in rows:
        row_name = str(row.get("row_name") or row.get("fault_type") or "")
        coverage_id = str(row.get("coverage_id", ""))
        expected_coverage = f"{args.scale}.fault.{row_name}"
        if row_name not in REQUIRED_ROWS:
            errors.append(f"{row.get('fault_id', '<unknown>')}: unexpected row_name {row_name!r}")
        if coverage_id != expected_coverage:
            errors.append(f"{row.get('fault_id', '<unknown>')}: coverage_id must be {expected_coverage}, got {coverage_id!r}")
        if int(row.get("scale", 0) or 0) != args.scale:
            errors.append(f"{row.get('fault_id', '<unknown>')}: scale must be {args.scale}")
        if int(row.get("node_count", 0)) != args.scale:
            errors.append(f"{row.get('fault_id', '<unknown>')}: node_count must be {args.scale}")
        if row.get("status") != "PASS":
            errors.append(f"{row.get('fault_id', '<unknown>')}: status must be PASS")
        if row.get("real_execution_verified") is not True:
            errors.append(f"{row.get('fault_id', '<unknown>')}: real_execution_verified must be true")
        implementation = str(row.get("implementation_path", ""))
        if row_name in NETWORK_ROWS:
            if implementation not in ALLOWED_NETWORK_PATHS:
                errors.append(f"{row.get('fault_id', '<unknown>')}: network fault implementation_path must be sandbox_proxy or container_netns_tc")
        elif implementation not in {"owned_runtime_control", "owned_container_control", "project_fault_api_node_stop_owned_runtime_control"}:
            errors.append(f"{row.get('fault_id', '<unknown>')}: non-network implementation_path is not an owned runtime/container path")
        refs = row.get("source_evidence_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"{row.get('fault_id', '<unknown>')}: source_evidence_refs required")
        if not row.get("workload_impact_ref"):
            errors.append(f"{row.get('fault_id', '<unknown>')}: workload_impact_ref required")
        if row.get("cleanup_verified") is not True:
            errors.append(f"{row.get('fault_id', '<unknown>')}: cleanup_verified must be true")
        if row_name in PARTITION_ROWS and not row.get("partition_report_ref"):
            errors.append(f"{row.get('fault_id', '<unknown>')}: partition_report_ref required")
        if row_name == "split_brain_window_detection" and not row.get("split_brain_report_ref"):
            errors.append("split_brain_window_detection requires split_brain_report_ref")
    if workload and workload.get("status") != "PASS":
        errors.append("fault_workload_impact status must be PASS")
    if split_brain and split_brain.get("status") != "PASS":
        errors.append("split_brain_report status must be PASS")
    if partition:
        partition_rows = partition.get("partition_rows", [])
        if not isinstance(partition_rows, list) or len(partition_rows) < 3:
            errors.append("partition_report must include partition rows for network/minority/majority partitions")
        for index, entry in enumerate(partition_rows):
            if not isinstance(entry, dict) or entry.get("implementation_path") not in ALLOWED_NETWORK_PATHS:
                errors.append(f"partition_report.partition_rows[{index}] must use sandbox_proxy or container_netns_tc")
            if not entry.get("majority_group") or not entry.get("minority_group"):
                errors.append(f"partition_report.partition_rows[{index}] must include majority_group and minority_group")
    if errors:
        return print_errors(errors)
    print(f"PASS strict fault matrix phase={args.phase} scale={args.scale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
