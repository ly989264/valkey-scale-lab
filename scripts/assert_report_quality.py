#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import phase_dir, print_errors, require_json  # noqa: E402

P38 = "P38_CROSS_SCALE_ANALYSIS_REGRESSION"
P39 = "P39_VISUAL_REPORT_QUALITY_GATE"
BAD_TEXT = ["NaN", "Infinity", "undefined", "Traceback", "TODO", "PLACEHOLDER", "BROKEN_CHART"]
REQUIRED_SECTIONS = {
    "executive_summary",
    "strict_coverage_heatmap",
    "resource_preflight_and_scale_feasibility",
    "cluster_lifecycle_summary",
    "management_operation_matrix",
    "management_latency_and_convergence_charts",
    "fault_failover_matrix",
    "failover_latency_curves_for_50_100_200",
    "fault_period_workload_impact",
    "partition_and_split_brain_findings",
    "telemetry_completeness",
    "cleanup_and_leftover_resource_summary",
    "above_200_dry_run_support_summary",
    "missing_data_and_blocked_row_appendix",
    "source_artifact_provenance_index",
}
REQUIRED_CHARTS = {
    "coverage_heatmap",
    "management_wall_ms_by_operation_and_scale",
    "management_convergence_ms_by_operation_and_scale",
    "failover_promotion_latency_curve_50_100_200",
    "failover_cluster_recovery_latency_curve_50_100_200",
    "workload_qps_ratio_by_fault_and_scale",
    "workload_p99_delta_by_fault_and_scale",
    "error_rate_delta_by_fault_and_scale",
    "resource_usage_by_scale",
    "cleanup_status_by_stage",
}
MISSING_MARKERS = ("MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON")


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ref_path(ref: str) -> Path:
    return ROOT / ref


def path_from_ref(ref: Any, errors: list[str], label: str) -> str | None:
    if isinstance(ref, str):
        return ref
    if isinstance(ref, dict) and isinstance(ref.get("path"), str):
        return ref["path"]
    errors.append(f"{label} must be a string path or object with path")
    return None


def assert_path_and_hash(ref: dict[str, Any], errors: list[str], label: str) -> None:
    path_text = path_from_ref(ref, errors, label)
    if not path_text:
        return
    path = ref_path(path_text)
    if not path.exists():
        errors.append(f"{label} missing: {path_text}")
        return
    if path.is_file() and path.stat().st_size <= 0:
        errors.append(f"{label} is empty: {path_text}")
    expected = ref.get("sha256") if isinstance(ref, dict) else None
    if expected and sha256_file(path) != expected:
        errors.append(f"{label} sha256 mismatch: {path_text}")


def assert_bad_text(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for bad in BAD_TEXT:
        if bad in text:
            errors.append(f"{path.relative_to(ROOT).as_posix()}: report contains forbidden marker {bad}")
    if any(marker in text for marker in MISSING_MARKERS):
        reason_tokens = ["reason", "Reason", "P38 provides", "does not substitute", "Source:"]
        if not any(token in text for token in reason_tokens):
            errors.append(f"{path.relative_to(ROOT).as_posix()}: missing-data markers require visible reasons")


def assert_missing_reasons(obj: Any, errors: list[str], label: str = "$") -> None:
    if isinstance(obj, dict):
        status = obj.get("status")
        if status in MISSING_MARKERS and not obj.get("reason"):
            errors.append(f"{label}: {status} requires reason")
        for key, value in obj.items():
            assert_missing_reasons(value, errors, f"{label}.{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            assert_missing_reasons(value, errors, f"{label}[{index}]")


def assert_report_links(report_path: Path, errors: list[str]) -> None:
    text = report_path.read_text(encoding="utf-8", errors="replace")
    if report_path.suffix == ".md":
        for alt, target in re.findall(r"!\[([^\]]+)\]\(([^)]+)\)", text):
            linked = report_path.parent / target
            if not linked.exists():
                errors.append(f"{report_path.relative_to(ROOT).as_posix()}: broken image {alt}: {target}")
    if report_path.suffix == ".html":
        for target in re.findall(r'<img[^>]+src="([^"]+)"', text):
            linked = report_path.parent / target
            if not linked.exists():
                errors.append(f"{report_path.relative_to(ROOT).as_posix()}: broken image src: {target}")


def assert_p39_quality(index: dict[str, Any], errors: list[str]) -> None:
    if index.get("phase_id") != P39:
        errors.append(f"report index phase_id must be {P39}")
    policy = index.get("derivation_policy", {})
    if policy.get("artifact_only") is not True or policy.get("runtime_started") is not False:
        errors.append("P39 report index must assert artifact_only=true and runtime_started=false")
    if policy.get("log_parsing") is not False or policy.get("source_scenarios_rerun") is not False:
        errors.append("P39 report index must reject log parsing and source scenario reruns")

    reports = index.get("reports")
    if not isinstance(reports, list) or len(reports) < 2:
        errors.append("P39 report index requires Markdown and HTML reports")
        reports = []
    report_paths: list[Path] = []
    for ref in reports:
        if not isinstance(ref, dict):
            errors.append("P39 reports entries must be objects")
            continue
        assert_path_and_hash(ref, errors, "report")
        path_text = ref.get("path")
        if isinstance(path_text, str):
            report_paths.append(ref_path(path_text))

    for report_path in report_paths:
        if report_path.exists() and report_path.suffix.lower() in {".md", ".html"}:
            assert_bad_text(report_path, errors)
            assert_report_links(report_path, errors)

    sections = index.get("sections")
    if not isinstance(sections, list):
        errors.append("P39 report index sections must be a list")
        sections = []
    observed_sections = {section.get("section_id") for section in sections if isinstance(section, dict)}
    missing_sections = sorted(REQUIRED_SECTIONS - observed_sections)
    if missing_sections:
        errors.append(f"P39 required sections missing from report_index: {missing_sections}")
    md_reports = [path for path in report_paths if path.suffix == ".md" and path.exists()]
    if md_reports:
        markdown = md_reports[0].read_text(encoding="utf-8", errors="replace")
        for section in sections:
            if isinstance(section, dict):
                title = str(section.get("title", ""))
                if title and f"## {title}" not in markdown:
                    errors.append(f"final_report.md missing section heading: {title}")
    for section in sections:
        if not isinstance(section, dict):
            errors.append("P39 section entry must be object")
            continue
        sources = section.get("source_artifacts")
        if not isinstance(sources, list) or not sources:
            errors.append(f"section {section.get('section_id')}: source_artifacts required")
        for source in sources or []:
            if not isinstance(source, str) or not ref_path(source).exists():
                errors.append(f"section {section.get('section_id')}: source missing: {source}")

    charts = index.get("charts")
    if not isinstance(charts, list):
        errors.append("P39 report index charts must be a list")
        charts = []
    observed_charts = {chart.get("chart_id") for chart in charts if isinstance(chart, dict)}
    missing_charts = sorted(REQUIRED_CHARTS - observed_charts)
    if missing_charts:
        errors.append(f"P39 required charts missing from report_index: {missing_charts}")
    for chart in charts:
        if not isinstance(chart, dict):
            errors.append("P39 chart entry must be object")
            continue
        if chart.get("chart_id") not in REQUIRED_CHARTS:
            errors.append(f"unexpected P39 chart id: {chart.get('chart_id')}")
        assert_path_and_hash(chart, errors, f"chart {chart.get('chart_id')}")
        path_text = chart.get("path")
        if isinstance(path_text, str):
            path = ref_path(path_text)
            if path.exists():
                assert_bad_text(path, errors)
        sources = chart.get("source_artifacts")
        if not isinstance(sources, list) or not sources:
            errors.append(f"chart {chart.get('chart_id')}: source_artifacts required")
        for source in sources or []:
            if not isinstance(source, str) or not ref_path(source).exists():
                errors.append(f"chart {chart.get('chart_id')}: source missing: {source}")
        if int(chart.get("row_count", 0) or 0) <= 0:
            errors.append(f"chart {chart.get('chart_id')}: row_count must be positive")

    assets = index.get("assets")
    if not isinstance(assets, list) or len(assets) < len(REQUIRED_CHARTS):
        errors.append("P39 assets list must include all chart assets")
        assets = []
    for asset in assets:
        if isinstance(asset, dict):
            assert_path_and_hash(asset, errors, f"asset {asset.get('chart_id')}")
        else:
            path_text = path_from_ref(asset, errors, "asset")
            if path_text and (not ref_path(path_text).exists() or ref_path(path_text).stat().st_size <= 0):
                errors.append(f"asset missing or empty: {path_text}")

    coverage = index.get("coverage_totals")
    p38_summary_path = phase_dir(P38) / "cross_scale_analysis_summary.json"
    if not isinstance(coverage, dict):
        errors.append("P39 coverage_totals must be an object")
    elif p38_summary_path.exists():
        p38_summary = json.loads(p38_summary_path.read_text(encoding="utf-8"))
        if coverage != p38_summary.get("counts"):
            errors.append("P39 coverage_totals must exactly match P38 counts")

    assert_missing_reasons(index, errors, "report_index")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase")
    parser.add_argument("--report-index", required=True)
    args = parser.parse_args()
    errors: list[str] = []
    index = require_json(ROOT / args.report_index, errors, "report index")
    if index:
        if args.phase == P39:
            assert_p39_quality(index, errors)
        else:
            assets = index.get("assets", [])
            reports = index.get("reports", [])
            for ref in list(assets) + list(reports):
                path_text = path_from_ref(ref, errors, "report index ref")
                if not path_text:
                    continue
                path = ROOT / path_text
                if not path.exists():
                    errors.append(f"report asset missing: {path_text}")
                    continue
                if path.suffix.lower() in {".html", ".md", ".json", ".js"}:
                    assert_bad_text(path, errors)
        quality_path = phase_dir(args.phase) / "report_quality_report.json" if args.phase else None
        if quality_path:
            quality = require_json(quality_path, errors, "report quality")
            if quality and quality.get("status") != "PASS":
                errors.append("report_quality_report status must be PASS")
            if args.phase == P39 and quality:
                assert_missing_reasons(quality, errors, "report_quality_report")
    if errors:
        return print_errors(errors)
    print("PASS report quality")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
