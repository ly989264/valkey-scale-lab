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

REQUIRED_FAULTS = {
    "P22_FAULT_REPLICA_HOST_AZ_STOP": {"replica_stop", "node_host_stop", "az_stop"},
    "P23_FAULT_NETWORK_DELAY_LOSS_FLAP": {"network_delay", "network_loss", "network_flap"},
    "P24_PARTITION_SPLIT_BRAIN_MATRIX": {"network_partition", "minority_partition", "majority_partition"},
}
SAFE_PATHS = {"container_netns_tc", "sandbox_proxy", "owned_container_control", "owned_runtime_control", "unsupported_skipped_with_reason"}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    required = REQUIRED_FAULTS.get(args.phase)
    if not required:
        print(f"PASS fault matrix not required for phase={args.phase}")
        return 0

    base = ROOT / "artifacts" / "phases" / args.phase
    path = base / "fault_results.jsonl"
    errors: list[str] = []
    errors.extend(validate_artifact(path, ROOT / "schemas/artifact/fault_result.schema.json"))
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rows = load_jsonl(path)
    observed = {row.get("fault_type") for row in rows}
    missing = sorted(required - observed)
    if missing:
        errors.append(f"missing required fault rows: {missing}")
    for row in rows:
        label = row.get("fault_id", row.get("fault_type"))
        if row.get("implementation_path") not in SAFE_PATHS:
            errors.append(f"{label}: unsafe or unknown implementation_path={row.get('implementation_path')!r}")
        if row.get("implementation_path") == "unsupported_skipped_with_reason" and not row.get("reason"):
            errors.append(f"{label}: unsupported implementation path requires reason")
        if row.get("safety_scope_verified") is not True:
            errors.append(f"{label}: safety_scope_verified must be true")
        if row.get("cleanup_verified") is not True:
            errors.append(f"{label}: cleanup_verified must be true")
        if not row.get("workload_impact_ref"):
            errors.append(f"{label}: workload_impact_ref required")
        if not row.get("targets"):
            errors.append(f"{label}: targets required")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS fault matrix coverage phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
