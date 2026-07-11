#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valkey_scale_lab.observer.failover_timeline import RTO_METRIC_FIELDS, derive_rto_metrics  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed P44 RTO metric semantic assertion")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--artifact-dir")
    args = parser.parse_args()

    base = Path(args.artifact_dir) if args.artifact_dir else ROOT / "artifacts" / "phases" / args.phase
    errors: list[str] = []
    samples = _load_jsonl(base / "failover_timeline_samples.jsonl", errors)
    for sample in samples:
        _check_sample(sample, errors)
    summary = _load_json(base / "failover_rto_summary.json", errors)
    _check_summary(summary, samples, errors)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS RTO metric semantics phase={args.phase}")
    return 0


def _check_sample(sample: dict[str, Any], errors: list[str]) -> None:
    sample_id = str(sample.get("sample_id", "MISSING"))
    try:
        expected = derive_rto_metrics(sample)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{sample_id}: cannot derive RTO metrics: {exc}")
        return
    for field in RTO_METRIC_FIELDS:
        value = sample.get(field)
        if not isinstance(value, (int, float)):
            errors.append(f"{sample_id}: {field} must be numeric")
            continue
        if round(float(value), 3) != expected[field]:
            errors.append(f"{sample_id}: {field}={value!r} does not match timestamp-derived {expected[field]}")
    pfail_to_ok = float(sample["pfail_to_cluster_ok_ms"])
    clean_tail = float(sample["cluster_ok_to_clean_snapshot_ms"])
    kill_to_clean = float(sample["kill_to_clean_snapshot_ms"])
    if round(pfail_to_ok, 3) == round(kill_to_clean, 3):
        errors.append(f"{sample_id}: pfail_to_cluster_ok_ms appears substituted by kill_to_clean_snapshot_ms")
    if pfail_to_ok >= kill_to_clean:
        errors.append(f"{sample_id}: pfail_to_cluster_ok_ms includes impossible clean-snapshot tail")
    if clean_tail <= 0:
        errors.append(f"{sample_id}: cluster_ok_to_clean_snapshot_ms must preserve clean-gate tail separately")
    if sample.get("first_client_success_source") != "client_recovery_samples.jsonl":
        errors.append(f"{sample_id}: first_client_success must cite client_recovery_samples.jsonl")
    if sample.get("clean_snapshot_endpoint") == "pfail_to_cluster_ok_ms":
        errors.append(f"{sample_id}: clean snapshot endpoint must not be used for pfail_to_cluster_ok_ms")


def _check_summary(summary: dict[str, Any], samples: list[dict[str, Any]], errors: list[str]) -> None:
    pass_samples = [sample for sample in samples if sample.get("status") == "PASS"]
    if summary.get("sample_count") != len(pass_samples):
        errors.append("summary sample_count must match PASS raw samples")
    derived = summary.get("derived_series")
    if not isinstance(derived, dict):
        errors.append("summary derived_series must be an object")
        return
    for metric in ["kill_to_pfail_ms", "pfail_to_cluster_ok_ms", "kill_to_client_recovered_ms", "cluster_ok_to_clean_snapshot_ms", "kill_to_clean_snapshot_ms"]:
        values = [float(sample[metric]) for sample in pass_samples if isinstance(sample.get(metric), (int, float))]
        series = derived.get(metric)
        if not isinstance(series, dict):
            errors.append(f"summary missing derived series for {metric}")
            continue
        if series.get("sample_count") != len(values):
            errors.append(f"summary {metric} sample_count mismatch")
        if values and round(float(series.get("max_ms", -1)), 3) != round(max(values), 3):
            errors.append(f"summary {metric} max_ms does not derive from raw samples")


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
    rows = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}:{lineno}: invalid JSON: {exc}")
    if not rows:
        errors.append(f"empty jsonl artifact: {path}")
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
