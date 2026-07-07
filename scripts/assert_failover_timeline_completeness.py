#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valkey_scale_lab.observer.failover_timeline import REQUIRED_TIMESTAMPS, derive_rto_metrics  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed P44 failover timeline completeness assertion")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--artifact-dir")
    parser.add_argument("--require-scales", default="30,50,100,200")
    args = parser.parse_args()

    base = Path(args.artifact_dir) if args.artifact_dir else ROOT / "artifacts" / "phases" / args.phase
    required_scales = {int(item) for item in args.require_scales.split(",") if item}
    errors: list[str] = []
    samples = _load_jsonl(base / "failover_timeline_samples.jsonl", errors)
    client_rows = _load_jsonl(base / "client_recovery_samples.jsonl", errors)
    observer_rows = _load_jsonl(base / "observer_samples.jsonl", errors)
    summary = _load_json(base / "failover_rto_summary.json", errors)
    if not samples:
        errors.append("failover_timeline_samples.jsonl must contain at least one row")
    client_ids = {row.get("sample_id") for row in client_rows if row.get("status") == "PASS"}
    observer_ids = {row.get("sample_id") for row in observer_rows if row.get("status") == "PASS"}
    observed_scales: set[int] = set()
    for sample in samples:
        sample_id = str(sample.get("sample_id", "MISSING"))
        if sample.get("phase_id") != args.phase:
            errors.append(f"{sample_id}: phase_id must be {args.phase}")
        if sample.get("status") != "PASS":
            errors.append(f"{sample_id}: real timeline sample status must be PASS")
        if sample.get("real_valkey") is not True:
            errors.append(f"{sample_id}: real_valkey must be true for real P44 evidence")
        if sample.get("execution_mode") != "real_valkey":
            errors.append(f"{sample_id}: execution_mode must be real_valkey")
        if sample.get("timeline_source") != "concurrent_failover_timeline_observer":
            errors.append(f"{sample_id}: timeline_source must be concurrent observer")
        if sample.get("client_probe_source") != "continuous_fault_period_set_get":
            errors.append(f"{sample_id}: client recovery must come from continuous SET/GET probe")
        if sample_id not in client_ids:
            errors.append(f"{sample_id}: no passing client recovery samples")
        if sample_id not in observer_ids:
            errors.append(f"{sample_id}: no passing observer samples")
        node_count = sample.get("node_count")
        if isinstance(node_count, int):
            observed_scales.add(node_count)
        for field in REQUIRED_TIMESTAMPS:
            if not isinstance(sample.get(field), (int, float)):
                errors.append(f"{sample_id}: {field} must be numeric, got {sample.get(field)!r}")
        try:
            expected = derive_rto_metrics(sample)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{sample_id}: invalid RTO timeline: {exc}")
            continue
        for metric, value in expected.items():
            if round(float(sample.get(metric, -1)), 3) != value:
                errors.append(f"{sample_id}: {metric} must derive from timestamps")
    missing_scales = sorted(required_scales - observed_scales)
    if missing_scales:
        errors.append(f"missing required real observer scales: {missing_scales}")
    if summary.get("status") != "PASS":
        errors.append("failover_rto_summary.json status must be PASS")
    if set(summary.get("observed_real_scales", [])) & required_scales != required_scales:
        errors.append("summary observed_real_scales must include all required scales")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS failover timeline completeness phase={args.phase}")
    return 0


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
            obj = json.loads(line)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}:{lineno}: invalid JSON: {exc}")
            continue
        rows.append(obj)
    if not rows:
        errors.append(f"empty jsonl artifact: {path}")
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
