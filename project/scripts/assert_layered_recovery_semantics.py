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
    parser = argparse.ArgumentParser(description="Fail-closed CLEAN_GATE_DIAGNOSTICS layered recovery semantic assertion")
    parser.add_argument("--capability-id", required=True)
    parser.add_argument("--artifact-dir")
    args = parser.parse_args()
    base = Path(args.artifact_dir) if args.artifact_dir else ROOT / "artifacts" / "capabilities" / args.capability_id
    errors: list[str] = []
    samples = _load_jsonl(base / "failover_timeline_samples.jsonl", errors)
    summary = _load_json(base / "layered_recovery_summary.json", errors)
    endpoints = _load_json(base / "recovery_endpoint_summary.json", errors)
    for sample in samples:
        _check_sample(sample, args.capability_id, errors)
    _check_summary(summary, samples, errors)
    _check_endpoint_summary(endpoints, samples, errors)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS layered recovery semantics capability_id={args.capability_id}")
    return 0


def _check_sample(sample: dict[str, Any], capability_id: str, errors: list[str]) -> None:
    sample_id = str(sample.get("sample_id", "MISSING"))
    if sample.get("capability_id") != capability_id:
        errors.append(f"{sample_id}: capability_id must be {capability_id}")
    expected_sources = {
        "level_1_source": "observer",
        "level_2_source": "client_probe",
        "level_3_source": "clean_gate",
    }
    for field, expected in expected_sources.items():
        if sample.get(field) != expected:
            errors.append(f"{sample_id}: {field} must be {expected}")
    for ref_field in ["observer_samples_ref", "client_recovery_samples_ref", "clean_gate_probe_rounds_ref"]:
        if not isinstance(sample.get(ref_field), str) or not sample.get(ref_field):
            errors.append(f"{sample_id}: {ref_field} is required")
    try:
        expected = derive_rto_metrics(sample)
    except Exception as exc:
        errors.append(f"{sample_id}: cannot derive layered metrics: {exc}")
        return
    for field in RTO_METRIC_FIELDS:
        if round(float(sample.get(field, -1)), 3) != expected[field]:
            errors.append(f"{sample_id}: {field} does not derive from raw timestamps")
    if sample.get("timeline_source") != "concurrent_failover_timeline_observer":
        errors.append(f"{sample_id}: Level 1 must be runtime observer sourced")
    if sample.get("first_client_success_source") != "client_recovery_samples.jsonl":
        errors.append(f"{sample_id}: Level 2 must cite client_recovery_samples.jsonl")


def _check_summary(summary: dict[str, Any], samples: list[dict[str, Any]], errors: list[str]) -> None:
    if summary.get("artifact_type") != "layered_recovery_summary":
        errors.append("layered_recovery_summary.json artifact_type mismatch")
    per_sample = summary.get("per_sample")
    if not isinstance(per_sample, list) or len(per_sample) != len(samples):
        errors.append("layered_recovery_summary.json per_sample must match raw sample count")
        return
    by_id = {str(row.get("sample_id")): row for row in samples}
    for row in per_sample:
        sample = by_id.get(str(row.get("sample_id")))
        if not sample:
            errors.append(f"summary has unknown sample {row.get('sample_id')}")
            continue
        for field in RTO_METRIC_FIELDS:
            if row.get(field) != sample.get(field):
                errors.append(f"{row.get('sample_id')}: summary {field} must derive from raw sample")
        for level, source in [("level_1", "observer"), ("level_2", "client_probe"), ("level_3", "clean_gate")]:
            if not isinstance(row.get(level), dict) or row[level].get("source") != source:
                errors.append(f"{row.get('sample_id')}: {level} source missing")


def _check_endpoint_summary(summary: dict[str, Any], samples: list[dict[str, Any]], errors: list[str]) -> None:
    endpoints = summary.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != len(samples):
        errors.append("recovery_endpoint_summary.json endpoints must match raw sample count")
        return
    for endpoint in endpoints:
        for level in ["level_1", "level_2", "level_3"]:
            record = endpoint.get(level)
            if not isinstance(record, dict) or not record.get("source_ref"):
                errors.append(f"{endpoint.get('sample_id')}: {level} requires source_ref")
            if record.get("start_at_ms") == "MISSING" or record.get("end_at_ms") == "MISSING":
                errors.append(f"{endpoint.get('sample_id')}: {level} requires timestamps")


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
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
