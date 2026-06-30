from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_metric_coverage_matrix.py"

spec = importlib.util.spec_from_file_location("build_metric_coverage_matrix", SCRIPT)
build_metric_coverage_matrix = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(build_metric_coverage_matrix)


def entry_by_key(matrix: dict, layer: str, surface: str) -> dict:
    return next(entry for entry in matrix["entries"] if entry["layer"] == layer and entry["surface"] == surface)


def test_coverage_matrix_has_required_layers_surfaces_and_cells() -> None:
    _, matrix = build_metric_coverage_matrix.build_reports(REPO_ROOT)

    assert matrix["status"] == "PASS"
    assert matrix["layers"] == build_metric_coverage_matrix.LAYERS
    assert matrix["surfaces"] == build_metric_coverage_matrix.SURFACES
    assert matrix["summary"]["entry_count"] == len(matrix["layers"]) * len(matrix["surfaces"])
    assert len(matrix["entries"]) == matrix["summary"]["entry_count"]


def test_small_real_surface_entries_include_real_valkey_coverage() -> None:
    _, matrix = build_metric_coverage_matrix.build_reports(REPO_ROOT)

    for surface in [
        "cluster_build",
        "management",
        "workload",
        "observability",
        "fault",
        "failover",
        "stability",
        "scale",
        "report_visualization",
    ]:
        entry = entry_by_key(matrix, "small-real", surface)
        assert entry["status"] == "COVERED"
        assert entry["evidence_class"] == "real_valkey"
        assert entry["real_valkey_coverage"] is True
        assert entry["dry_run_only"] is False
        assert any("valkey_e2e_evidence" in path for path in entry["source_artifacts"])


def test_scale_ladder_entries_use_real_evidence_for_30_50_and_100() -> None:
    _, matrix = build_metric_coverage_matrix.build_reports(REPO_ROOT)

    expected = {
        "30": "artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json",
        "50": "artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_50.json",
        "100": "artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json",
    }
    for layer, evidence_path in expected.items():
        entry = entry_by_key(matrix, layer, "scale")
        assert entry["status"] == "COVERED"
        assert entry["evidence_class"] == "real_valkey"
        assert entry["real_valkey_coverage"] is True
        assert entry["dry_run_only"] is False
        assert evidence_path in entry["source_artifacts"]


def test_1000_dryrun_layer_is_never_real_coverage() -> None:
    _, matrix = build_metric_coverage_matrix.build_reports(REPO_ROOT)

    dry_entries = [entry for entry in matrix["entries"] if entry["layer"] == "1000-dry-run"]
    assert len(dry_entries) == len(build_metric_coverage_matrix.SURFACES)
    assert all(entry["real_valkey_coverage"] is False for entry in dry_entries)
    assert all(entry["dry_run_only"] is True for entry in dry_entries)
    assert not any(entry["real_valkey_coverage"] for entry in dry_entries)

    scale = entry_by_key(matrix, "1000-dry-run", "scale")
    assert scale["status"] == "COVERED"
    assert scale["evidence_class"] == "dry_run_planner"
    assert scale["source_artifacts"] == ["artifacts/phases/P02_PLANNER/scale_1000_dryrun_plan.json"]


def test_p14_boundary_records_skipped_opt_in_contract() -> None:
    _, matrix = build_metric_coverage_matrix.build_reports(REPO_ROOT)

    assert matrix["p14_boundary"]["phase_id"] == "P14_SCALE_1000_OPTIN_DRYRUN"
    assert matrix["p14_boundary"]["status"] == "SKIPPED_WITH_REASON"
    assert matrix["p14_boundary"]["real_valkey_coverage"] is False
    assert matrix["p14_boundary"]["dry_run_only"] is True
    assert "not executed" in matrix["p14_boundary"]["reason"]
