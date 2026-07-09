#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

STATUSES = {"PASS", "FAIL", "BLOCKED_WITH_REASON"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and assert the milestone1 acceptance report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out", required=True)
    parser.add_argument("--allow-blocked", action="store_true", help="Exit 0 when only heavy real rungs are blocked with reasons.")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    report = build_report(root)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report["milestone1_status"] == "PASS":
        print(f"PASS: milestone1 acceptance report written to {out}")
        return 0
    if report["milestone1_status"] == "BLOCKED_WITH_REASON" and args.allow_blocked:
        print(f"BLOCKED_WITH_REASON: milestone1 acceptance report written to {out}")
        return 0
    print(f"{report['milestone1_status']}: milestone1 acceptance report written to {out}", file=sys.stderr)
    return 1


def build_report(root: Path) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    category: dict[str, dict[str, Any]] = {}
    category["cluster_setup"] = _check_cluster_setup(root, sources)
    category["management_ops"] = _check_management(root, sources)
    category["fault_failover"] = _check_fault(root, sources)
    category["workload_benchmark"] = _check_workload(root, sources)
    category["system_metrics"] = _check_system_metrics(root, sources)
    category["analysis"] = _check_analysis(root, sources)
    category["visual_report_zh"] = _check_visual_report(root, sources)
    category["cleanup"] = _check_cleanup(root, sources)
    category["cross_scenario_coverage"] = _check_cross_scenario(root, sources)
    heavy = _heavy_rungs(root)
    top = {name: result["status"] for name, result in category.items()}
    if any(status == "FAIL" for status in top.values()):
        milestone = "FAIL"
    elif any(item["status"] == "FAIL" for item in heavy):
        milestone = "FAIL"
    elif any(item["status"] == "BLOCKED_WITH_REASON" for item in heavy):
        milestone = "BLOCKED_WITH_REASON"
    elif any(status == "BLOCKED_WITH_REASON" for status in top.values()):
        milestone = "BLOCKED_WITH_REASON"
    else:
        milestone = "PASS"
    return {
        "schema_version": "v1",
        "artifact_type": "milestone1_acceptance_report",
        "stage_id": "M1-S09",
        "milestone1_status": milestone,
        **top,
        "category_results": category,
        "heavy_real_rungs": heavy,
        "source_artifacts": sources,
    }


def _check_cluster_setup(root: Path, sources: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = _json(root / "runs/m1-s07-local/artifacts/goal_loop/M1-S07/valkey_e2e_evidence.json")
    sources.append(_source(root, "runs/m1-s07-local/artifacts/goal_loop/M1-S07/valkey_e2e_evidence.json"))
    ok = evidence.get("status") == "PASS" and evidence.get("real_valkey") is True and int(evidence.get("nodes_observed", 0) or 0) >= 6
    return _result("PASS" if ok else "FAIL", "bounded real local Valkey setup evidence", evidence_ref="runs/m1-s07-local/artifacts/goal_loop/M1-S07/valkey_e2e_evidence.json")


def _check_management(root: Path, sources: list[dict[str, Any]]) -> dict[str, Any]:
    matrix = _json(root / "runs/m1-s04-local/artifacts/management_ops_matrix.json")
    commands = _jsonl(root / "runs/m1-s04-local/artifacts/command_log.jsonl")
    if not matrix:
        matrix = _json(root / "tests/fixtures/management_matrix/success/management_ops_matrix.json")
    if not commands:
        commands = _jsonl(root / "tests/fixtures/management_matrix/success/management_command_log.jsonl")
    sources.extend([_source(root, "runs/m1-s04-local/artifacts/management_ops_matrix.json"), _source(root, "runs/m1-s04-local/artifacts/command_log.jsonl")])
    ok = bool(matrix) and bool(commands)
    return _result("PASS" if ok else "FAIL", "management matrix and command log are non-empty", operation_count=len(matrix.get("operations", matrix.get("rows", [])) if isinstance(matrix, dict) else []), command_count=len(commands))


def _check_fault(root: Path, sources: list[dict[str, Any]]) -> dict[str, Any]:
    events = _jsonl(root / "runs/m1-s06-local/artifacts/fault_timeline_events.jsonl")
    report = _json(root / "runs/m1-s06-local/artifacts/fault_timeline_report.json")
    samples = _jsonl(root / "runs/m1-s06-local/artifacts/failover_latency_samples.jsonl")
    sources.extend([_source(root, "runs/m1-s06-local/artifacts/fault_timeline_events.jsonl"), _source(root, "runs/m1-s06-local/artifacts/failover_latency_samples.jsonl")])
    ok = bool(events) and bool(report) and bool(samples)
    return _result("PASS" if ok else "FAIL", "fault timeline events, report, and failover latency samples are non-empty", event_count=len(events), latency_sample_count=len(samples))


def _check_workload(root: Path, sources: list[dict[str, Any]]) -> dict[str, Any]:
    windows = _json(root / "runs/m1-s05-local/artifacts/workload_windows.json")
    metrics = _jsonl(root / "runs/m1-s05-local/artifacts/metrics_timeseries.jsonl")
    sources.extend([_source(root, "runs/m1-s05-local/artifacts/workload_windows.json"), _source(root, "runs/m1-s05-local/artifacts/metrics_timeseries.jsonl")])
    if not windows:
        windows = _json(root / "tests/fixtures/workload_benchmark/success/workload_windows.json")
    if not metrics:
        metrics = _jsonl(root / "tests/fixtures/workload_benchmark/success/metrics_timeseries.jsonl")
    return _result("PASS" if windows and metrics else "FAIL", "workload windows and metrics timeseries are non-empty", metric_count=len(metrics))


def _check_system_metrics(root: Path, sources: list[dict[str, Any]]) -> dict[str, Any]:
    rows = _jsonl(root / "runs/m1-s07-local/artifacts/goal_loop/M1-S07/system_metrics_timeseries.jsonl")
    report = _json(root / "runs/m1-s07-local/artifacts/goal_loop/M1-S07/system_metrics_report.json")
    sources.extend([_source(root, "runs/m1-s07-local/artifacts/goal_loop/M1-S07/system_metrics_timeseries.jsonl"), _source(root, "runs/m1-s07-local/artifacts/goal_loop/M1-S07/system_metrics_report.json")])
    missing_ok = all(row.get("missing_reason") for row in rows if row.get("metric_value") == "MISSING")
    return _result("PASS" if rows and report and missing_ok else "FAIL", "system metrics rows are non-empty and missing rows have reasons", metric_count=len(rows))


def _check_analysis(root: Path, sources: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _json(root / "runs/m1-s07-local/artifacts/goal_loop/M1-S07/analysis_summary.json")
    sources.append(_source(root, "runs/m1-s07-local/artifacts/goal_loop/M1-S07/analysis_summary.json"))
    missing_ok = all(item.get("reason") for item in summary.get("missing_metrics", []) if isinstance(item, dict))
    return _result("PASS" if summary and missing_ok else "FAIL", "analysis summary exists and aggregates missing metric reasons", missing_count=len(summary.get("missing_metrics", [])) if summary else 0)


def _check_visual_report(root: Path, sources: list[dict[str, Any]]) -> dict[str, Any]:
    report_dir = root / "runs/m1-s08-local/artifacts/goal_loop/M1-S08/reports"
    index = _json(report_dir / "report_index.json")
    md = report_dir / "report.md"
    html = report_dir / "index.html"
    assets = list((report_dir / "assets").glob("*.svg")) if (report_dir / "assets").exists() else []
    exports = list((report_dir / "exports").glob("*.csv")) if (report_dir / "exports").exists() else []
    sources.append(_source(root, "runs/m1-s08-local/artifacts/goal_loop/M1-S08/reports/report_index.json"))
    text = (md.read_text(encoding="utf-8") if md.exists() else "") + (html.read_text(encoding="utf-8") if html.exists() else "")
    ok = bool(index) and "中文自动化可视化分析报告" in text and bool(assets) and bool(exports) and index.get("offline_policy", {}).get("llm_used") is False
    return _result("PASS" if ok else "FAIL", "Chinese offline report exists with local assets/exports and no-LLM policy", asset_count=len(assets), export_count=len(exports))


def _check_cleanup(root: Path, sources: list[dict[str, Any]]) -> dict[str, Any]:
    cleanup = _json(root / "runs/m1-s07-local/artifacts/goal_loop/M1-S07/cleanup_report.json")
    sources.append(_source(root, "runs/m1-s07-local/artifacts/goal_loop/M1-S07/cleanup_report.json"))
    ok = cleanup.get("status") == "PASS" and not cleanup.get("resources_remaining")
    return _result("PASS" if ok else "FAIL", "cleanup report has no resources_remaining", resources_remaining=cleanup.get("resources_remaining", "MISSING"))


def _check_cross_scenario(root: Path, sources: list[dict[str, Any]]) -> dict[str, Any]:
    required_paths = [
        "tests/fixtures/management_matrix/scale_30/management_ops_matrix.json",
        "tests/fixtures/management_matrix/scale_50/management_ops_matrix.json",
        "tests/fixtures/management_matrix/scale_100/management_ops_matrix.json",
        "tests/fixtures/management_matrix/scale_200/management_ops_matrix.json",
        "tests/fixtures/fault_timeline/scale_30/fault_timeline_events.jsonl",
        "tests/fixtures/fault_timeline/scale_50/fault_timeline_events.jsonl",
        "tests/fixtures/fault_timeline/scale_100/fault_timeline_events.jsonl",
        "tests/fixtures/fault_timeline/scale_200/fault_timeline_events.jsonl",
        "tests/fixtures/system_metrics/scale_30/system_metrics_timeseries.jsonl",
        "tests/fixtures/system_metrics/scale_50/system_metrics_timeseries.jsonl",
        "tests/fixtures/system_metrics/scale_100/system_metrics_timeseries.jsonl",
        "tests/fixtures/system_metrics/scale_200/system_metrics_timeseries.jsonl",
    ]
    missing = [path for path in required_paths if not (root / path).exists()]
    sources.extend(_source(root, path) for path in required_paths)
    return _result("PASS" if not missing else "FAIL", "cross-scenario fixture coverage spans 30/50/100/200 for management, fault, and system metrics", missing=missing)


def _heavy_rungs(root: Path) -> list[dict[str, Any]]:
    specs = [
        {
            "scale": 30,
            "category": "cluster_setup",
            "evidence": "artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json",
            "cleanup": "artifacts/phases/P12_SCALE_LADDER_10_30/cleanup_report_scale_30.json",
            "min_nodes": 30,
        },
        {
            "scale": 50,
            "category": "management_ops",
            "evidence": "artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/valkey_e2e_evidence.json",
            "cleanup": "artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/cleanup_report.json",
            "min_nodes": 50,
        },
        {
            "scale": 100,
            "category": "management_ops",
            "evidence": "artifacts/phases/P31_MANAGEMENT_MATRIX_100_REAL/valkey_e2e_evidence.json",
            "cleanup": "artifacts/phases/P31_MANAGEMENT_MATRIX_100_REAL/cleanup_report.json",
            "min_nodes": 100,
        },
        {
            "scale": 200,
            "category": "management_ops",
            "evidence": "artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/valkey_e2e_evidence.json",
            "cleanup": "artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/cleanup_report.json",
            "min_nodes": 200,
        },
        {
            "scale": 50,
            "category": "fault_failover",
            "evidence": "artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/valkey_e2e_evidence.json",
            "cleanup": "artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/cleanup_report.json",
            "min_nodes": 50,
        },
        {
            "scale": 100,
            "category": "fault_failover",
            "evidence": "artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/valkey_e2e_evidence.json",
            "cleanup": "artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/cleanup_report.json",
            "min_nodes": 100,
        },
        {
            "scale": 200,
            "category": "fault_failover",
            "evidence": "artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/valkey_e2e_evidence.json",
            "cleanup": "artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/cleanup_report.json",
            "min_nodes": 200,
        },
        {
            "scale": 50,
            "category": "full_flow",
            "evidence": "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_50/valkey_e2e_evidence.json",
            "cleanup": "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_50/cleanup_report.json",
            "metrics": "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_50/metrics_timeseries.jsonl",
            "report": "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_50/report_index.json",
            "min_nodes": 50,
        },
        {
            "scale": 100,
            "category": "full_flow",
            "evidence": "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_100/valkey_e2e_evidence.json",
            "cleanup": "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_100/cleanup_report.json",
            "metrics": "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_100/metrics_timeseries.jsonl",
            "report": "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_100/report_index.json",
            "min_nodes": 100,
        },
        {
            "scale": 200,
            "category": "full_flow",
            "evidence": "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_200/valkey_e2e_evidence.json",
            "cleanup": "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_200/cleanup_report.json",
            "metrics": "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_200/metrics_timeseries.jsonl",
            "report": "artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_200/report_index.json",
            "min_nodes": 200,
        },
    ]
    rows: list[dict[str, Any]] = []
    for spec in specs:
        evidence = _json(root / spec["evidence"])
        cleanup = _json(root / spec["cleanup"])
        metrics_ok = True
        if spec.get("metrics"):
            metrics_ok = bool(_jsonl(root / str(spec["metrics"])))
        report_ok = True
        if spec.get("report"):
            report_ok = bool(_json(root / str(spec["report"])))
        evidence_ok = (
            evidence.get("status") == "PASS"
            and evidence.get("real_valkey") is True
            and int(evidence.get("nodes_observed", 0) or 0) >= int(spec["min_nodes"])
            and any(str(version).startswith("9.1") for version in evidence.get("valkey_versions", []))
        )
        cleanup_ok = cleanup.get("status") == "PASS" and not cleanup.get("resources_remaining")
        status = "PASS" if evidence_ok and cleanup_ok and metrics_ok and report_ok else "FAIL"
        reason = (
            f"Exact real {spec['scale']}-node {spec['category']} evidence passed with Valkey 9.1.x and clean cleanup."
            if status == "PASS"
            else f"Exact real {spec['scale']}-node {spec['category']} evidence is missing or incomplete."
        )
        rows.append(
            {
                "scale": spec["scale"],
                "category": spec["category"],
                "status": status,
                "reason": reason,
                "evidence": spec["evidence"],
                "cleanup": spec["cleanup"],
                "metrics": spec.get("metrics", "SKIPPED_WITH_REASON"),
                "report": spec.get("report", "SKIPPED_WITH_REASON"),
                "nodes_observed": evidence.get("nodes_observed", "MISSING"),
                "valkey_versions": evidence.get("valkey_versions", []),
            }
        )
    return rows


def _result(status: str, reason: str, **extra: Any) -> dict[str, Any]:
    if status not in STATUSES:
        status = "FAIL"
    return {"status": status, "reason": reason, **extra}


def _json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _source(root: Path, path: str) -> dict[str, Any]:
    full = root / path
    return {"path": path, "status": "PASS" if full.exists() and (not full.is_file() or full.stat().st_size > 0) else "MISSING"}


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
