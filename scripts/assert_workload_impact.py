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
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS workload impact phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
