#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ROWS = {"fake_schema_unit", "smoke_6_or_10", "real_30", "real_50", "real_100", "real_200", "dry_run_gt_200"}
REAL_ROWS = {
    "smoke_6_or_10": 6,
    "real_30": 30,
    "real_50": 50,
    "real_100": 100,
    "real_200": 200,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    base = ROOT / "artifacts" / "phases" / args.phase
    errors: list[str] = []
    ledger_path = base / "coverage_ledger.json"
    if not ledger_path.exists():
        errors.append(f"coverage ledger missing: {ledger_path}")
        rows = []
    else:
        try:
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            rows = ledger.get("rows", [])
        except Exception as exc:
            errors.append(f"coverage ledger invalid JSON: {exc}")
            rows = []
    by_name = {row.get("coverage_id"): row for row in rows if isinstance(row, dict)}
    missing = sorted(REQUIRED_ROWS - set(by_name))
    if missing:
        errors.append(f"missing nodehost density coverage rows: {missing}")
    for coverage_id in REQUIRED_ROWS & set(by_name):
        row = by_name[coverage_id]
        status = row.get("status")
        if status not in {"PASS", "SKIPPED_WITH_REASON", "DRY_RUN_PASS"}:
            errors.append(f"{coverage_id}: invalid status {status!r}")
        if status in {"SKIPPED_WITH_REASON"} and not row.get("reason"):
            errors.append(f"{coverage_id}: skipped row requires reason")
        refs = row.get("artifact_refs", [])
        if not refs:
            errors.append(f"{coverage_id}: artifact_refs required")
        if coverage_id in REAL_ROWS:
            if status != "PASS":
                errors.append(f"{coverage_id}: real Valkey coverage must be PASS, got {status!r}")
            if row.get("execution_mode") != "real_valkey":
                errors.append(f"{coverage_id}: execution_mode must be real_valkey")
            expected_nodes = REAL_ROWS[coverage_id]
            if not any(_real_evidence_ok(ref, expected_nodes, errors, coverage_id) for ref in refs):
                errors.append(f"{coverage_id}: no artifact_ref contains valid real Valkey density evidence for {expected_nodes} nodes")
        if coverage_id == "dry_run_gt_200":
            if row.get("execution_mode") != "dry_run":
                errors.append("dry_run_gt_200: execution_mode must be dry_run")
            for ref in refs:
                path = ROOT / ref
                if path.exists() and path.suffix == ".json":
                    try:
                        obj = json.loads(path.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if obj.get("real_valkey") is True or obj.get("runtime_resources_created") is True:
                        errors.append(f"dry_run_gt_200: forbidden real runtime claim in {ref}")
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS no nodehost partial coverage phase={args.phase}")
    return 0


def _real_evidence_ok(ref: str, expected_nodes: int, errors: list[str], coverage_id: str) -> bool:
    path = ROOT / ref
    if not path.exists() or path.suffix != ".json":
        return False
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{coverage_id}: invalid JSON evidence {ref}: {exc}")
        return False
    if obj.get("artifact_type") != "valkey_e2e_evidence":
        return False
    if obj.get("status") != "PASS" or obj.get("probe_result") != "PASS":
        errors.append(f"{coverage_id}: evidence {ref} did not PASS")
        return False
    if obj.get("real_valkey") is not True:
        errors.append(f"{coverage_id}: evidence {ref} does not declare real_valkey=true")
        return False
    try:
        observed = int(obj.get("nodes_observed", 0) or 0)
    except (TypeError, ValueError):
        observed = 0
    if observed < expected_nodes:
        errors.append(f"{coverage_id}: evidence {ref} observed {observed}, expected at least {expected_nodes}")
        return False
    runtime = obj.get("runtime", {})
    if runtime.get("nodehost_strategy") != "density_limited":
        errors.append(f"{coverage_id}: evidence {ref} missing density_limited runtime strategy")
        return False
    try:
        actual = int(runtime.get("actual_nodehost_count", 0) or 0)
        max_nodehosts = int(runtime.get("max_nodehosts", 0) or 0)
        max_per_host = int(runtime.get("max_logical_nodes_per_nodehost", 0) or 0)
    except (TypeError, ValueError):
        errors.append(f"{coverage_id}: evidence {ref} has non-integer nodehost density fields")
        return False
    logical_counts = runtime.get("logical_nodes_per_nodehost", {})
    if not isinstance(logical_counts, dict) or len(logical_counts) != actual:
        errors.append(f"{coverage_id}: evidence {ref} logical_nodes_per_nodehost count does not match actual_nodehost_count")
        return False
    if actual <= 0 or actual > max_nodehosts:
        errors.append(f"{coverage_id}: evidence {ref} actual_nodehost_count outside max_nodehosts")
        return False
    if any(int(value) > max_per_host for value in logical_counts.values()):
        errors.append(f"{coverage_id}: evidence {ref} exceeds max_logical_nodes_per_nodehost")
        return False
    if expected_nodes == 200 and actual < 8:
        errors.append(f"{coverage_id}: evidence {ref} expected 200-node runtime to split to at least 8 nodehosts, got {actual}")
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
