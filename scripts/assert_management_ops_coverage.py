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
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rows = load_jsonl(results)
    observed_ops = {row.get("operation_name") for row in rows}
    missing = sorted(required_ops - observed_ops)
    if missing:
        errors.append(f"missing required operation rows: {missing}")
    for row in rows:
        label = f"{row.get('operation_name')}[{row.get('node_count')}]"
        status = row.get("operation_status")
        if status == "PASS" and row.get("real_execution_verified") is not True:
            errors.append(f"{label}: PASS requires real_execution_verified=true")
        if status in {"SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON", "MISSING"} and not row.get("reason"):
            errors.append(f"{label}: {status} requires reason")
        if status == "PASS":
            for field in ["started_at_unix_ms", "ended_at_unix_ms", "wall_ms", "command_ms", "convergence_ms"]:
                if row.get(field) == "MISSING":
                    errors.append(f"{label}: PASS cannot have MISSING {field}")
        if not row.get("workload_window_ref"):
            errors.append(f"{label}: workload_window_ref required")
        if not isinstance(row.get("errors_by_type"), dict):
            errors.append(f"{label}: errors_by_type must be object")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS management operation coverage phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
