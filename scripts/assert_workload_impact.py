#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from codex_gate import validate_artifact  # noqa: E402
from schema_validator import load_json  # noqa: E402

WINDOWS = {"baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"}
METRICS = {
    "requested_qps",
    "achieved_qps",
    "ok_ops",
    "error_ops",
    "error_rate",
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_p99_ms",
    "timeout_count",
    "moved_redirection_count",
    "ask_redirection_count",
}


def candidate_path(base: Path) -> Path | None:
    for name in ["workload_impact_report.json", "management_workload_impact.json", "workload_impact_cross_stage.json"]:
        path = base / name
        if path.exists():
            return path
    return None


def metric_missing_reason(metrics: dict[str, Any], field: str) -> bool:
    reasons = metrics.get("missing_reasons", {})
    return isinstance(reasons, dict) and bool(reasons.get(field))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    base = ROOT / "artifacts" / "phases" / args.phase
    path = candidate_path(base)
    if path is None:
        print(f"FAIL: no workload impact artifact found for {args.phase}", file=sys.stderr)
        return 1

    schema = ROOT / "schemas/artifact/workload_impact_cross_stage.schema.json" if path.name == "workload_impact_cross_stage.json" else ROOT / "schemas/artifact/workload_impact_report.schema.json"
    errors = validate_artifact(path, schema)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    report = load_json(path)
    rows = report.get("windows", report.get("rows", []))
    observed = {row.get("window_name") for row in rows}
    missing_windows = sorted(WINDOWS - observed)
    if missing_windows:
        errors.append(f"missing workload windows: {missing_windows}")
    for row in rows:
        name = row.get("window_name", "unknown")
        metrics = row.get("metrics", row)
        for field in METRICS:
            if field not in metrics:
                errors.append(f"{name}: missing metric {field}")
            elif metrics.get(field) == "MISSING" and not metric_missing_reason(metrics, field):
                errors.append(f"{name}: MISSING {field} requires missing_reasons.{field}")
    if args.phase == "P20_FAILOVER_LATENCY_CURVE_30_50_100":
        sample_ids = {row.get("sample_id") for row in rows if row.get("sample_id")}
        if len(sample_ids) != 9:
            errors.append(f"P20 workload impact must cover 9 sample IDs, got {len(sample_ids)}")
        for row in rows:
            if row.get("rung") not in {30, 50, 100}:
                errors.append(f"{row.get('window_name', 'unknown')}: invalid P20 rung {row.get('rung')!r}")
            if not row.get("sample_id"):
                errors.append(f"{row.get('window_name', 'unknown')}: P20 sample_id required")
        comparisons = report.get("comparisons", [])
        comparison_ids = {item.get("sample_id") for item in comparisons if isinstance(item, dict)}
        missing_comparisons = sorted(sample_ids - comparison_ids)
        if missing_comparisons:
            errors.append(f"P20 comparisons missing sample IDs: {missing_comparisons}")
    if args.phase == "P21_FAILOVER_LATENCY_CURVE_200":
        expected_ids = {f"rung-200-sample-{idx:02d}" for idx in [1, 2, 3]}
        sample_ids = {row.get("sample_id") for row in rows if row.get("sample_id")}
        if sample_ids != expected_ids:
            errors.append(f"P21 workload impact must cover exactly {sorted(expected_ids)}, got {sorted(sample_ids)}")
        windows_by_sample: dict[Any, set[Any]] = {}
        for row in rows:
            sid = row.get("sample_id")
            if row.get("rung") != 200 or row.get("node_count") != 200:
                errors.append(f"{row.get('window_name', 'unknown')}: invalid P21 rung/node_count {row.get('rung')!r}/{row.get('node_count')!r}")
            if sid not in expected_ids:
                errors.append(f"{row.get('window_name', 'unknown')}: unexpected P21 sample_id {sid!r}")
            windows_by_sample.setdefault(sid, set()).add(row.get("window_name"))
        for sid in expected_ids:
            missing = sorted(WINDOWS - windows_by_sample.get(sid, set()))
            if missing:
                errors.append(f"P21 sample {sid} missing workload windows: {missing}")
        comparisons = report.get("comparisons", [])
        comparison_ids = {item.get("sample_id") for item in comparisons if isinstance(item, dict)}
        missing_comparisons = sorted(expected_ids - comparison_ids)
        if missing_comparisons:
            errors.append(f"P21 comparisons missing sample IDs: {missing_comparisons}")
        for item in comparisons:
            if isinstance(item, dict) and (item.get("rung") != 200 or item.get("node_count") != 200):
                errors.append(f"P21 comparison {item.get('sample_id')}: rung/node_count must be 200")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS workload impact phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
