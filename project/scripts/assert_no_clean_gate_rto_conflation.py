#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject CLEAN_GATE_DIAGNOSTICS clean-gate/RTO conflation")
    parser.add_argument("--capability-id", required=True)
    parser.add_argument("--artifact-dir")
    args = parser.parse_args()
    base = Path(args.artifact_dir) if args.artifact_dir else ROOT / "artifacts" / "capabilities" / args.capability_id
    errors: list[str] = []
    samples = _load_jsonl(base / "failover_timeline_samples.jsonl", errors)
    for sample in samples:
        sample_id = str(sample.get("sample_id", "MISSING"))
        if sample.get("level_1_source") in {"clean_gate", "clean_snapshot", "clean_gate_probe_rounds", "report_only"}:
            errors.append(f"{sample_id}: Level 1 cannot be sourced from clean gate or report-only fields")
        if sample.get("clean_snapshot_endpoint") == "pfail_to_cluster_ok_ms":
            errors.append(f"{sample_id}: clean snapshot endpoint cannot be used for pfail_to_cluster_ok_ms")
        pfail_to_ok = sample.get("pfail_to_cluster_ok_ms")
        kill_to_clean = sample.get("kill_to_clean_snapshot_ms")
        if isinstance(pfail_to_ok, (int, float)) and isinstance(kill_to_clean, (int, float)) and round(float(pfail_to_ok), 3) == round(float(kill_to_clean), 3):
            same_endpoint = (
                sample.get("first_pfail_seen_at_ms") == sample.get("fault_apply_at_ms")
                and sample.get("first_cluster_ok_at_ms") == sample.get("clean_snapshot_passed_at_ms")
            )
            if not same_endpoint:
                errors.append(f"{sample_id}: pfail_to_cluster_ok_ms equals kill_to_clean_snapshot_ms without identical timestamp endpoints")
        if sample.get("first_cluster_ok_at_ms") == sample.get("clean_snapshot_passed_at_ms"):
            if sample.get("level_3_source") != "clean_gate":
                errors.append(f"{sample_id}: identical Level 1/3 endpoint requires explicit clean-gate round source")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS no clean-gate RTO conflation capability_id={args.capability_id}")
    return 0


def _load_jsonl(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    if not path.exists():
        errors.append(f"missing artifact: {path}")
        return []
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception as exc:
            errors.append(f"{path}:{lineno}: invalid JSON: {exc}")
    if not rows:
        errors.append(f"empty jsonl artifact: {path}")
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
