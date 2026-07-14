#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_METRICS = {
    "config_parse_ms",
    "config_validate_ms",
    "resource_preflight_ms",
    "plan_build_ms",
    "port_check_ms",
    "nodehost_start_ms",
    "node_config_generate_ms",
    "node_config_distribute_ms",
    "process_start_ms",
    "process_ready_wait_ms",
    "cluster_meet_ms",
    "cluster_slots_assign_ms",
    "replica_replicate_ms",
    "cluster_convergence_probe_ms",
    "full_cluster_probe_ms",
    "cleanup_ms",
    "total_setup_ms",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-dir", default="tests/fixtures/setup_telemetry/success")
    parser.add_argument("--analysis", default="")
    parser.add_argument("--report-index", default="")
    parser.add_argument("--fixture-suite", default="")
    args = parser.parse_args()
    base = ROOT / args.artifacts_dir
    errors: list[str] = []
    telemetry = load_json(base / "setup_telemetry.json", errors, "setup telemetry")
    if telemetry:
        assert_telemetry(telemetry, errors)
    if args.analysis:
        analysis = load_json(ROOT / args.analysis, errors, "analysis summary")
        setup = analysis.get("setup_aggregates", {}) if isinstance(analysis, dict) else {}
        if not setup.get("stage_duration_ranking"):
            errors.append("analysis setup_aggregates.stage_duration_ranking must be non-empty")
        if "slowest_nodes_topN" not in setup:
            errors.append("analysis setup_aggregates missing slowest_nodes_topN")
    if args.report_index:
        index = load_json(ROOT / args.report_index, errors, "report index")
        reports = {Path(item.get("path", "")).name for item in index.get("reports", []) if isinstance(item, dict)}
        for name in ["setup_lifecycle_durations.csv", "setup_slowest_nodes.csv", "setup_waterfall.svg", "report.md", "index.html"]:
            if name not in reports:
                errors.append(f"report_index missing setup output {name}")
        report_dir = (ROOT / args.report_index).parent
        markdown = (report_dir / "report.md").read_text(encoding="utf-8") if (report_dir / "report.md").exists() else ""
        html = (report_dir / "index.html").read_text(encoding="utf-8") if (report_dir / "index.html").exists() else ""
        for heading in ["集群拉起瀑布图", "阶段耗时排序", "慢节点 TopN"]:
            if heading not in markdown or heading not in html:
                errors.append(f"report markdown/html missing Chinese setup section {heading}")
    if args.fixture_suite:
        assert_fixture_suite(ROOT / args.fixture_suite, errors)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("PASS: setup timeline coverage")
    return 0


def load_json(path: Path, errors: list[str], label: str) -> dict:
    if not path.exists():
        errors.append(f"missing {label}: {path}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"invalid {label}: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"{label} must be object")
        return {}
    return data


def assert_telemetry(telemetry: dict, errors: list[str]) -> None:
    if telemetry.get("artifact_type") != "setup_telemetry":
        errors.append("setup telemetry artifact_type must be setup_telemetry")
    metrics = telemetry.get("metrics", {})
    missing = REQUIRED_METRICS - set(metrics)
    if missing:
        errors.append(f"setup telemetry missing required metrics: {sorted(missing)}")
    for name in REQUIRED_METRICS & set(metrics):
        value = metrics[name]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            continue
        if not (isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON"} and value.get("reason")):
            errors.append(f"metric {name} must be numeric or structured missing/skipped reason")
    for field in ["per_node_samples", "per_nodehost_samples", "slowest_nodes_topN", "slowest_replica_replicate_topN"]:
        if not telemetry.get(field):
            errors.append(f"{field} must be non-empty")
    rungs = set(telemetry.get("same_schema_scale_rungs", []))
    if not {30, 50, 100, 200}.issubset(rungs):
        errors.append("same_schema_scale_rungs must include 30/50/100/200")
    cleanup = telemetry.get("cleanup", {})
    if "cleanup_ms" not in metrics or not isinstance(cleanup, dict):
        errors.append("cleanup timing and residual summary must be present")


def assert_fixture_suite(path: Path, errors: list[str]) -> None:
    required = {
        "success",
        "blocked",
        "dry_run",
        "missing_metric",
        "cleanup_residual",
        "timeout",
    }
    for name in sorted(required):
        telemetry = load_json(path / name / "setup_telemetry.json", errors, f"{name} setup telemetry fixture")
        if telemetry:
            before = len(errors)
            assert_telemetry(telemetry, errors)
            if name == "timeout":
                assert_timeout_fixture(telemetry, errors)
            if name == "success" and len(errors) == before and telemetry.get("missing_metrics"):
                errors.append("success fixture must not rely on missing setup metrics")


def assert_timeout_fixture(telemetry: dict, errors: list[str]) -> None:
    status = telemetry.get("status")
    if status not in {"FAIL", "SKIPPED_WITH_REASON", "BLOCKED_WITH_REASON"}:
        errors.append("timeout fixture status must encode a non-pass timeout outcome")
    timeout_text = json.dumps(telemetry, sort_keys=True).lower()
    if "timeout" not in timeout_text:
        errors.append("timeout fixture must include a structured timeout reason")
    missing = telemetry.get("missing_metrics", [])
    if not any(
        isinstance(item, dict)
        and item.get("status") in {"MISSING", "SKIPPED_WITH_REASON"}
        and "timeout" in str(item.get("reason", "")).lower()
        for item in missing
    ):
        errors.append("timeout fixture must carry a timeout missing/skipped metric reason")


if __name__ == "__main__":
    raise SystemExit(main())
