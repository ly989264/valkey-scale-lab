from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from valkey_scale_lab.analysis import analyze_validated_evidence
from valkey_scale_lab.evidence import (
    build_candidate_admission,
    validate_candidate_admission,
)
from valkey_scale_lab.report import (
    REQUIRED_SURFACES,
    ValidatedReportError,
    render_validated_report,
)
from valkey_scale_lab.scenarios import load_local_full_flow_definition


ROOT = Path(__file__).resolve().parents[2]
STARTED = 1_800_000_000_000
PRODUCT_DIGEST = "a" * 64
PROBE = {
    "cluster_state": "ok",
    "known_nodes": 50,
    "slots_assigned": 16384,
    "slots_ok": 16384,
}
DEFINITION = load_local_full_flow_definition()


def _provenance_fixture_module():
    path = ROOT / "tests/provenance/test_exact_gate_measured_sources.py"
    spec = importlib.util.spec_from_file_location("report_provenance_support", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validated_bundle(tmp_path: Path):
    base = tmp_path / "evidence"
    base.mkdir()
    base = _provenance_fixture_module()._bundle(base)
    preflight_path = base / "runtime/resource_preflight.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    preflight["checks"] = [{"name": "memory", "status": "PASS"}]
    preflight_path.write_text(json.dumps(preflight) + "\n", encoding="utf-8")
    admission = build_candidate_admission(
        base,
        50,
        PRODUCT_DIGEST,
        definition=DEFINITION,
        run_started_unix_ms=STARTED,
        run_ended_unix_ms=STARTED + 1000,
        valkey_versions=["9.1.0"],
        independent_probe=PROBE,
        source_commit="b" * 40,
        run_owner="pytest-report",
    )
    return validate_candidate_admission(
        base,
        50,
        expected_product_digest=PRODUCT_DIGEST,
        admission=admission,
        definition=DEFINITION,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_validated_evidence_analysis_report_pipeline_is_derived_and_traceable(
    tmp_path: Path,
) -> None:
    bundle = _validated_bundle(tmp_path)
    evidence_before = {
        path: _sha256(path)
        for record in bundle.artifacts
        for path in (
            bundle.root / record.path,
            bundle.root / record.source_path,
        )
    }
    analysis = analyze_validated_evidence(
        bundle, tmp_path / "analysis/analysis.json"
    )

    report = render_validated_report(analysis, tmp_path / "report")

    assert report.document["status"] == "DERIVED"
    assert report.document["offline"] is True
    assert tuple(report.document["surface_statuses"]) == REQUIRED_SURFACES
    assert report.document["missing_data_taxonomy"] == (
        "MISSING",
        "SKIPPED_WITH_REASON",
        "UNSUPPORTED_WITH_REASON",
    )
    assert tuple(row["id"] for row in report.document["surfaces"]) == REQUIRED_SURFACES
    assert (report.root / report.document["analysis"]["path"]).resolve() == analysis.path
    assert report.document["digests"] == {
        "analysis": analysis.sha256,
        "admission": bundle.admission_digest,
        "definition": bundle.definition_digest,
        "product": bundle.product_digest,
        "run": report.run_digest,
        "capture": analysis.capture_digest,
        "provenance": analysis.provenance_digest,
    }
    assert report.document["provenance_refs"] == analysis.document["provenance_refs"]
    assert report.document["source_artifacts"] == tuple(
        {
            "artifact_id": record.artifact_id,
            "kind": record.kind,
            "path": record.path,
            "sha256": record.sha256,
            "source_path": record.source_path,
            "source_sha256": record.source_sha256,
            "transform_id": record.transform_id,
            "provenance_node_id": record.provenance_node_id,
        }
        for record in bundle.artifacts
    )
    assert {view["format"] for view in report.document["views"]} == {
        "json",
        "markdown",
        "html",
        "csv",
    }
    assert all(view["status"] == "DERIVED" for view in report.document["views"])
    assert all(
        _sha256(report.root / view["path"]) == view["sha256"]
        for view in report.document["views"]
    )
    assert _sha256(report.index_path) == report.index_sha256
    assert {
        path: _sha256(path)
        for record in bundle.artifacts
        for path in (
            bundle.root / record.path,
            bundle.root / record.source_path,
        )
    } == evidence_before


def test_report_views_are_deterministic_offline_and_preserve_missing_taxonomy(
    tmp_path: Path,
) -> None:
    bundle = _validated_bundle(tmp_path)
    analysis = analyze_validated_evidence(
        bundle, tmp_path / "analysis/analysis.json"
    )

    first = render_validated_report(analysis, tmp_path / "report-a")
    second = render_validated_report(analysis, tmp_path / "report-b")

    for name in ("report.json", "report.md", "index.html", "surfaces.csv", "report_index.json"):
        assert (first.root / name).read_bytes() == (second.root / name).read_bytes()
    html = (first.root / "index.html").read_text(encoding="utf-8").lower()
    assert "http://" not in html
    assert "https://" not in html
    assert "<script" not in html
    assert " src=" not in html
    view = json.loads((first.root / "report.json").read_text(encoding="utf-8"))
    assert set(view["surfaces"]) == set(REQUIRED_SURFACES)
    for surface in view["surfaces"].values():
        if surface["status"] in {
            "MISSING",
            "SKIPPED_WITH_REASON",
            "UNSUPPORTED_WITH_REASON",
        }:
            assert surface["reason"].strip()
    assert len((first.root / "surfaces.csv").read_text(encoding="utf-8").splitlines()) == len(REQUIRED_SURFACES) + 1


def test_report_rejects_non_capability_and_protected_evidence_output(
    tmp_path: Path,
) -> None:
    bundle = _validated_bundle(tmp_path)
    analysis = analyze_validated_evidence(
        bundle, tmp_path / "analysis/analysis.json"
    )

    with pytest.raises(TypeError, match="ValidatedAnalysis"):
        render_validated_report(dict(analysis.document), tmp_path / "dict-report")  # type: ignore[arg-type]
    with pytest.raises(ValidatedReportError, match="protected evidence root"):
        render_validated_report(analysis, bundle.root / "derived-report")


def test_report_rejects_stale_analysis_or_evidence_capability(tmp_path: Path) -> None:
    bundle = _validated_bundle(tmp_path)
    analysis = analyze_validated_evidence(
        bundle, tmp_path / "analysis/analysis.json"
    )
    analysis.path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValidatedReportError, match="analysis source hash mismatch"):
        render_validated_report(analysis, tmp_path / "stale-report")


def test_report_rejects_output_symlink_to_evidence_source(tmp_path: Path) -> None:
    bundle = _validated_bundle(tmp_path)
    analysis = analyze_validated_evidence(
        bundle, tmp_path / "analysis/analysis.json"
    )
    source = bundle.root / bundle.artifacts[0].path
    source_before = _sha256(source)
    output = tmp_path / "symlink-report"
    output.mkdir()
    (output / "report.json").symlink_to(source)

    with pytest.raises(ValidatedReportError, match="escapes through a symlink"):
        render_validated_report(analysis, output)

    assert _sha256(source) == source_before
