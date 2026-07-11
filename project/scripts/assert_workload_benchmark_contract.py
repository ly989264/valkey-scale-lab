#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from schema_validator import load_json, validate  # noqa: E402

PROFILES = {"smoke", "uniform", "hotspot", "mixed_rw", "write_heavy", "read_heavy"}
WINDOWS = {"baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"}
METRICS = {
    "requested_qps",
    "achieved_qps",
    "throughput_ratio",
    "ok_ops",
    "error_ops",
    "error_rate",
    "latency_p50_ms",
    "latency_p90_ms",
    "latency_p95_ms",
    "latency_p99_ms",
    "latency_p999_ms",
    "timeout_count",
    "connection_error_count",
    "moved_count",
    "ask_count",
    "cluster_down_count",
    "readonly_count",
    "tryagain_count",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures")
    parser.add_argument("--artifacts-dir")
    parser.add_argument("--analysis")
    parser.add_argument("--report-index")
    args = parser.parse_args()
    errors: list[str] = []
    if args.fixtures:
        errors.extend(validate_fixtures(Path(args.fixtures)))
    if args.artifacts_dir:
        errors.extend(validate_artifact_dir(Path(args.artifacts_dir), Path(args.analysis) if args.analysis else None, Path(args.report_index) if args.report_index else None, require_report=True))
    if not args.fixtures and not args.artifacts_dir:
        errors.append("one of --fixtures or --artifacts-dir is required")
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("workload benchmark contract PASS")
    return 0


def validate_fixtures(base: Path) -> list[str]:
    errors: list[str] = []
    observed: set[str] = set()
    for case in sorted(base.glob("*/")):
        if not case.is_dir():
            continue
        errors.extend(validate_artifact_dir(case, None, None, require_report=False))
        windows_path = case / "workload_windows.json"
        if windows_path.exists():
            for row in _load_json(windows_path).get("windows", []):
                if isinstance(row, dict) and row.get("profile") in PROFILES:
                    observed.add(str(row["profile"]))
    missing = sorted(PROFILES - observed)
    if missing:
        errors.append(f"{base}: missing fixture success coverage for profiles: {', '.join(missing)}")
    return errors


def validate_artifact_dir(base: Path, analysis_path: Path | None, report_index_path: Path | None, *, require_report: bool) -> list[str]:
    errors: list[str] = []
    windows_path = base / "workload_windows.json"
    if windows_path.exists():
        windows = _load_json(windows_path)
        errors.extend(f"{windows_path}: {err}" for err in validate(windows, load_json(ROOT / "schemas/artifact/workload_windows.schema.json")))
        errors.extend(_validate_windows(windows, windows_path))
    else:
        errors.append(f"{base}: missing workload_windows.json")
    report_path = base / "workload_report.json"
    if report_path.exists():
        report = _load_json(report_path)
        errors.extend(f"{report_path}: {err}" for err in validate(report, load_json(ROOT / "schemas/artifact/workload_report.schema.json")))
    elif require_report:
        errors.append(f"{base}: missing workload_report.json")
    for jsonl_name in ["events.jsonl", "metrics_timeseries.jsonl"]:
        path = base / jsonl_name
        if path.exists() and not path.read_text(encoding="utf-8").strip():
            errors.append(f"{path}: JSONL artifact is empty")
    if analysis_path and analysis_path.exists():
        analysis = _load_json(analysis_path)
        if "workload_benchmark" not in analysis:
            errors.append(f"{analysis_path}: missing workload_benchmark aggregate")
    if report_index_path and report_index_path.exists():
        index = _load_json(report_index_path)
        if "workload_report_inputs" not in index:
            errors.append(f"{report_index_path}: missing workload_report_inputs")
        names = {Path(item.get("path", "")).name for item in index.get("reports", []) if isinstance(item, dict)}
        for expected in ["workload_benchmark_windows.csv", "workload_profile_summary.csv", "workload_qps_p99_error.svg", "report.md", "index.html"]:
            if expected not in names:
                errors.append(f"{report_index_path}: missing rendered workload output {expected}")
    return errors


def _validate_windows(artifact: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    for idx, row in enumerate(artifact.get("windows", []), start=1):
        metrics = row.get("metrics", {}) if isinstance(row, dict) else {}
        missing = sorted(METRICS - set(metrics))
        if missing:
            errors.append(f"{path}: windows[{idx}] missing metrics {', '.join(missing)}")
        for name in METRICS:
            if metrics.get(name) == "MISSING" and not metrics.get("missing_reasons", {}).get(name):
                errors.append(f"{path}: windows[{idx}].metrics.{name} is MISSING without reason")
        coverage = row.get("key_slot_coverage", {}) if isinstance(row, dict) else {}
        if row.get("workload_mode") == "benchmark" and coverage.get("fixed_hash_tag_only") is True:
            errors.append(f"{path}: windows[{idx}] benchmark path is fixed-hash-tag-only")
    coverage = artifact.get("hash_slot_coverage", {})
    windows_by_profile: dict[str, set[str]] = {}
    for row in artifact.get("windows", []):
        if isinstance(row, dict) and row.get("profile") and row.get("window_name"):
            windows_by_profile.setdefault(str(row["profile"]), set()).add(str(row["window_name"]))
    for profile in artifact.get("profiles_covered", []):
        observed = windows_by_profile.get(str(profile), set())
        missing = sorted(WINDOWS - observed)
        if missing:
            errors.append(f"{path}: profile {profile} missing workload windows {', '.join(missing)}")
    if isinstance(coverage, dict):
        for profile, item in coverage.items():
            if isinstance(item, dict) and item.get("full_slot_requested") is True and item.get("full_slot_covered") is not True and item.get("status") not in {"SKIPPED_WITH_REASON", "MISSING"}:
                errors.append(f"{path}: {profile} requested full-slot coverage without coverage or skipped status")
    return errors


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
