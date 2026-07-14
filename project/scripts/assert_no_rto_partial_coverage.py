#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject partial FAILOVER_TIMELINE failover RTO coverage")
    parser.add_argument("--capability-id", required=True)
    parser.add_argument("--artifact-dir")
    parser.add_argument("--require-scales", default="30,50,100,200")
    parser.add_argument("--require-dry-run-gt-200", action="store_true")
    args = parser.parse_args()

    base = Path(args.artifact_dir) if args.artifact_dir else ROOT / "artifacts" / "capabilities" / args.capability_id
    required_scales = {int(item) for item in args.require_scales.split(",") if item}
    errors: list[str] = []
    samples = _load_jsonl(base / "failover_timeline_samples.jsonl", errors)
    client_rows = _load_jsonl(base / "client_recovery_samples.jsonl", errors)
    workload_windows = _load_json(base / "workload_windows.json", errors)
    real_by_scale: dict[int, list[dict[str, Any]]] = {scale: [] for scale in required_scales}
    smoke_count = 0
    for sample in samples:
        node_count = sample.get("node_count")
        sample_id = sample.get("sample_id", "MISSING")
        if sample.get("real_valkey") is True and sample.get("status") == "PASS" and isinstance(node_count, int):
            if node_count in real_by_scale:
                real_by_scale[node_count].append(sample)
            if node_count < min(required_scales):
                smoke_count += 1
        if sample.get("execution_mode") in {"fake_schema", "unit_schema"} and sample.get("real_valkey") is True:
            errors.append(f"{sample_id}: fake/schema execution cannot claim real_valkey")
    missing = [scale for scale, rows in sorted(real_by_scale.items()) if not rows]
    if missing:
        errors.append(f"missing real observer-backed scales: {missing}")
    if len([scale for scale, rows in real_by_scale.items() if rows]) <= 1:
        errors.append("FAILOVER_TIMELINE cannot pass with only one scale of observer evidence")
    if samples and smoke_count == len(samples):
        errors.append("FAILOVER_TIMELINE cannot pass with smoke-only coverage")
    _check_workload_windows(samples, client_rows, workload_windows, errors)
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
    print(f"PASS no RTO partial coverage capability_id={args.capability_id}")
    return 0


def _check_workload_windows(
    samples: list[dict[str, Any]],
    client_rows: list[dict[str, Any]],
    artifact: dict[str, Any],
    errors: list[str],
) -> None:
    required_windows = {"baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"}
    rows_by_sample: dict[str, list[dict[str, Any]]] = {}
    for row in client_rows:
        rows_by_sample.setdefault(str(row.get("sample_id", "MISSING")), []).append(row)
    windows = artifact.get("windows")
    if not isinstance(windows, list):
        errors.append("workload_windows.json windows must be a list")
        return
    windows_by_sample: dict[str, dict[str, dict[str, Any]]] = {}
    for window in windows:
        sample_id = str(window.get("sample_id", "MISSING"))
        name = str(window.get("window_name", "MISSING"))
        windows_by_sample.setdefault(sample_id, {})[name] = window
    for sample in samples:
        if sample.get("status") != "PASS":
            continue
        sample_id = str(sample.get("sample_id", "MISSING"))
        sample_windows = windows_by_sample.get(sample_id, {})
        missing_windows = sorted(required_windows - set(sample_windows))
        if missing_windows:
            errors.append(f"{sample_id}: missing workload windows {missing_windows}")
            continue
        all_run_metrics = sample_windows["all_run"].get("metrics", {})
        observed_rows = [
            row
            for row in rows_by_sample.get(sample_id, [])
            if isinstance(row.get("timestamp_unix_ms"), int)
            and isinstance(sample.get("fault_apply_at_ms"), int)
            and isinstance(sample.get("clean_snapshot_passed_at_ms"), int)
            and sample["fault_apply_at_ms"] <= row["timestamp_unix_ms"] <= sample["clean_snapshot_passed_at_ms"]
        ]
        ok_ops = sum(1 for row in observed_rows if row.get("status") == "PASS")
        error_ops = len(observed_rows) - ok_ops
        if all_run_metrics.get("sample_count") != len(observed_rows):
            errors.append(f"{sample_id}: all_run sample_count does not derive from client_recovery_samples.jsonl")
        if all_run_metrics.get("ok_ops") != ok_ops:
            errors.append(f"{sample_id}: all_run ok_ops does not derive from client_recovery_samples.jsonl")
        if all_run_metrics.get("error_ops") != error_ops:
            errors.append(f"{sample_id}: all_run error_ops does not derive from client_recovery_samples.jsonl")
        expected_error_rate = round(error_ops / len(observed_rows), 6) if observed_rows else "MISSING"
        if all_run_metrics.get("error_rate") != expected_error_rate:
            errors.append(f"{sample_id}: all_run error_rate does not derive from client_recovery_samples.jsonl")


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"missing artifact: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
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
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}:{lineno}: invalid JSON: {exc}")
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
