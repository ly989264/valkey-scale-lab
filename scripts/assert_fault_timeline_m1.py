#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from valkey_scale_lab.observer.failover_timeline import M1_REQUIRED_FAULT_TYPES, M1_REQUIRED_SCALE_RUNGS, M1_REQUIRED_TIMELINE_EVENTS, M1_REQUIRED_TIMELINE_METRICS


def main() -> int:
    args = parse_args()
    failures: list[str] = []
    roots: list[Path] = []
    if args.fixtures:
        roots.extend(path for path in sorted(args.fixtures.iterdir()) if path.is_dir())
    if args.artifacts_dir:
        roots.append(args.artifacts_dir)
    if not roots:
        failures.append("at least one --fixtures or --artifacts-dir input is required")
    for root in roots:
        check_root(root, failures)
    if args.analysis:
        analysis = load_json(args.analysis, failures)
        if analysis and "fault_timeline" not in analysis:
            failures.append(f"{args.analysis}: analysis_summary.json missing fault_timeline aggregate")
    if args.report_index:
        report_index = load_json(args.report_index, failures)
        if report_index and "fault_timeline_report_inputs" not in report_index:
            failures.append(f"{args.report_index}: report_index missing fault_timeline_report_inputs")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print(f"PASS: validated {len(roots)} fault timeline root(s)")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert M1-S06 fault timeline contract.")
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--report-index", type=Path)
    return parser.parse_args()


def check_root(root: Path, failures: list[str]) -> None:
    events_path = root / "fault_timeline_events.jsonl"
    report_path = root / "fault_timeline_report.json"
    samples_path = root / "failover_latency_samples.jsonl"
    if not events_path.exists():
        failures.append(f"{root}: missing fault_timeline_events.jsonl")
        return
    events = read_jsonl(events_path, failures)
    if not events:
        failures.append(f"{events_path}: timeline JSONL must not be empty")
    if not report_path.exists():
        failures.append(f"{root}: missing fault_timeline_report.json")
        return
    report = load_json(report_path, failures)
    if not report:
        return
    rows = report.get("fault_rows", [])
    if not isinstance(rows, list) or not rows:
        failures.append(f"{report_path}: fault_rows must be non-empty")
        rows = []
    observed_fault_types = {str(row.get("fault_type")) for row in rows if isinstance(row, dict)}
    observed_scales = {str(row.get("scale_rung")) for row in rows if isinstance(row, dict)}
    if root.name in {"success", "scale_30", "scale_50", "scale_100", "scale_200"}:
        missing_faults = [name for name in M1_REQUIRED_FAULT_TYPES if name not in observed_fault_types]
        if missing_faults:
            failures.append(f"{report_path}: missing required fault types: {', '.join(missing_faults)}")
    if root.name == "success":
        missing_scales = [name for name in M1_REQUIRED_SCALE_RUNGS if name not in observed_scales]
        if missing_scales:
            failures.append(f"{report_path}: missing required scale rungs: {', '.join(missing_scales)}")
    events_by_sample: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        events_by_sample.setdefault(str(event.get("sample_id", "MISSING")), []).append(event)
        if event.get("event_name") not in M1_REQUIRED_TIMELINE_EVENTS:
            failures.append(f"{events_path}: unsupported event_name {event.get('event_name')}")
        status = event.get("event_status")
        if status in {"MISSING", "SKIPPED_WITH_REASON", "BLOCKED_WITH_REASON", "FAIL"} and not event.get("reason"):
            failures.append(f"{events_path}: {event.get('sample_id')} {event.get('event_name')} {status} missing reason")
    for row in rows:
        if not isinstance(row, dict):
            continue
        sample_id = str(row.get("sample_id", "MISSING"))
        names = {str(event.get("event_name")) for event in events_by_sample.get(sample_id, [])}
        missing_events = [name for name in M1_REQUIRED_TIMELINE_EVENTS if name not in names]
        if missing_events:
            failures.append(f"{report_path}: {sample_id} missing timeline events {', '.join(missing_events)}")
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            failures.append(f"{report_path}: {sample_id} metrics must be object")
            continue
        for metric in M1_REQUIRED_TIMELINE_METRICS:
            if metric not in metrics:
                failures.append(f"{report_path}: {sample_id} missing metric {metric}")
            elif isinstance(metrics[metric], dict) and not metrics[metric].get("reason"):
                failures.append(f"{report_path}: {sample_id} structured metric {metric} missing reason")
        if row.get("host_network_mutation") is True:
            failures.append(f"{report_path}: {sample_id} host_network_mutation must never be true")
    if samples_path.exists():
        for sample in read_jsonl(samples_path, failures):
            if sample.get("derived_from_timeline") is not True:
                failures.append(f"{samples_path}: sample {sample.get('sample_id')} must be derived_from_timeline=true")
            for field in ["timeline_ref", "fault_type", "fault_id", "source_event_start", "source_event_end", "workload_recovery_ref"]:
                if not sample.get(field):
                    failures.append(f"{samples_path}: sample {sample.get('sample_id')} missing {field}")
    cleanup_path = root / "cleanup_report.json"
    if cleanup_path.exists():
        cleanup = load_json(cleanup_path, failures)
        if cleanup and cleanup.get("status") != "PASS" and root.name not in {"blocked", "dry_run_200_plus", "cleanup_residual"}:
            failures.append(f"{cleanup_path}: cleanup must PASS unless fixture is blocked/dry-run/cleanup_residual")


def load_json(path: Path, failures: list[str]) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(f"{path}: cannot read JSON: {exc}")
        return {}
    if not isinstance(data, dict):
        failures.append(f"{path}: JSON must be object")
        return {}
    return data


def read_jsonl(path: Path, failures: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                failures.append(f"{path}:{lineno}: row must be object")
                continue
            rows.append(row)
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(f"{path}: cannot read JSONL: {exc}")
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
