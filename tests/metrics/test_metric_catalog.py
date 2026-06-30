from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_metric_coverage_matrix.py"
REPORT_VIEW_SUFFIXES = {".csv", ".html", ".md", ".svg"}

spec = importlib.util.spec_from_file_location("build_metric_coverage_matrix", SCRIPT)
build_metric_coverage_matrix = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(build_metric_coverage_matrix)


def metric_by_name(catalog: dict, name: str) -> list[dict]:
    return [metric for metric in catalog["metrics"] if metric["name"] == name]


def test_current_repo_metric_catalog_passes_without_blocking_findings() -> None:
    catalog, _ = build_metric_coverage_matrix.build_reports(REPO_ROOT)

    assert catalog["status"] == "PASS"
    assert catalog["summary"]["blocking_findings_count"] == 0
    assert set(catalog["summary"]["surfaces"]) == set(build_metric_coverage_matrix.SURFACES)
    assert catalog["summary"]["layers"] == build_metric_coverage_matrix.LAYERS


def test_all_metric_catalog_entries_have_required_source_fields() -> None:
    catalog, _ = build_metric_coverage_matrix.build_reports(REPO_ROOT)
    required = {
        "name",
        "surface",
        "unit",
        "source_artifact",
        "source_sha256",
        "source_artifact_type",
        "source_kind",
        "source_pointer",
        "phase_id",
        "node_count_scope",
        "evidence_layer",
        "evidence_class",
        "real_valkey_coverage",
        "dry_run_only",
        "value_status",
        "missing_semantics",
    }

    assert catalog["metrics"]
    for metric in catalog["metrics"]:
        assert required <= set(metric)
        assert metric["surface"] in build_metric_coverage_matrix.SURFACES
        assert metric["evidence_layer"] in build_metric_coverage_matrix.LAYERS


def test_missing_skipped_and_no_baseline_semantics_are_explicit() -> None:
    catalog, _ = build_metric_coverage_matrix.build_reports(REPO_ROOT)

    split_brain = metric_by_name(catalog, "failover.split_brain_duration_ms")
    assert split_brain
    assert split_brain[0]["value_status"] == "MISSING"
    assert split_brain[0]["value"] is None
    assert split_brain[0]["missing_semantics"]["reason"]

    skipped = [
        metric
        for metric in catalog["metrics"]
        if metric["value_status"] == "SKIPPED_WITH_REASON"
        and (
            metric["name"].startswith("workload.timing_window.")
            or metric["name"].startswith("management.operation.")
            or metric["name"].endswith("real_evidence.data_path_result")
        )
    ]
    assert skipped
    assert all(metric["missing_semantics"]["reason"] for metric in skipped)

    no_baseline = [metric for metric in catalog["metrics"] if metric["value_status"] == "NO_BASELINE_YET"]
    assert no_baseline
    assert all(metric["missing_semantics"]["reason"] for metric in no_baseline)


def test_rendered_views_are_not_used_as_measured_metric_sources() -> None:
    catalog, _ = build_metric_coverage_matrix.build_reports(REPO_ROOT)

    measured = [metric for metric in catalog["metrics"] if metric["value_status"] in {"MEASURED", "PASS"}]
    for metric in measured:
        suffix = Path(metric["source_artifact"]).suffix
        assert suffix not in REPORT_VIEW_SUFFIXES


def test_p02_1000_dryrun_metric_never_counts_as_real() -> None:
    catalog, _ = build_metric_coverage_matrix.build_reports(REPO_ROOT)
    dryrun = metric_by_name(catalog, "scale.dryrun_1000.planned_node_count")

    assert len(dryrun) == 1
    metric = dryrun[0]
    assert metric["phase_id"] == "P02_PLANNER"
    assert metric["evidence_layer"] == "1000-dry-run"
    assert metric["evidence_class"] == "dry_run_planner"
    assert metric["real_valkey_coverage"] is False
    assert metric["dry_run_only"] is True
    assert metric["value"] == 1000
