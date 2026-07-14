#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject partial CLEAN_GATE_DIAGNOSTICS clean-gate layered coverage")
    parser.add_argument("--capability-id", required=True)
    parser.add_argument("--artifact-dir")
    parser.add_argument("--require-scales", default="30,50,100,200")
    parser.add_argument("--require-dry-run-gt-200", action="store_true")
    args = parser.parse_args()
    base = Path(args.artifact_dir) if args.artifact_dir else ROOT / "artifacts" / "capabilities" / args.capability_id
    required_scales = {int(item) for item in args.require_scales.split(",") if item}
    errors: list[str] = []
    samples = _load_jsonl(base / "failover_timeline_samples.jsonl", errors)
    rounds = _load_jsonl(base / "clean_gate_probe_rounds.jsonl", errors)
    real_by_scale: dict[int, list[dict[str, Any]]] = {scale: [] for scale in required_scales}
    round_sample_ids = {str(row.get("sample_id")) for row in rounds}
    for sample in samples:
        sample_id = str(sample.get("sample_id", "MISSING"))
        node_count = sample.get("node_count")
        if sample.get("capability_id") != args.capability_id:
            errors.append(f"{sample_id}: CLEAN_GATE_DIAGNOSTICS cannot pass with historical capability_id={sample.get('capability_id')}")
        if sample.get("execution_mode") in {"fake_schema", "unit_schema"} and sample.get("real_valkey") is True:
            errors.append(f"{sample_id}: fake/schema execution cannot claim real_valkey")
        if sample.get("real_valkey") is True and sample.get("status") == "PASS" and isinstance(node_count, int):
            if node_count in real_by_scale:
                real_by_scale[node_count].append(sample)
        if sample.get("status") == "PASS" and sample_id not in round_sample_ids:
            errors.append(f"{sample_id}: PASS sample lacks clean_gate_probe_rounds.jsonl coverage")
        for source_field in ["level_1_source", "level_2_source", "level_3_source"]:
            if not sample.get(source_field):
                errors.append(f"{sample_id}: missing {source_field}")
    missing = [scale for scale, rows in sorted(real_by_scale.items()) if not rows]
    if missing:
        errors.append(f"missing required real layered scales: {missing}")
    if len([scale for scale, rows in real_by_scale.items() if rows]) <= 1:
        errors.append("CLEAN_GATE_DIAGNOSTICS cannot pass with only one scale of layered evidence")
    if args.require_dry_run_gt_200:
        projection = _load_json(base / "dry_run_gt_200_projection.json", errors)
        if projection.get("dry_run") is not True:
            errors.append("greater-than-200 projection must declare dry_run=true")
        if projection.get("real_valkey") is not False:
            errors.append("greater-than-200 projection must declare real_valkey=false")
        if projection.get("runtime_resources_created") is not False:
            errors.append("greater-than-200 projection must not create runtime resources")
        planned = int(projection.get("node_count") or projection.get("cluster", {}).get("node_count") or 0)
        if planned <= 200:
            errors.append("greater-than-200 projection must be for a scale above 200")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS no clean-gate partial coverage capability_id={args.capability_id}")
    return 0


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"missing artifact: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"invalid JSON {path}: {exc}")
        return {}


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
