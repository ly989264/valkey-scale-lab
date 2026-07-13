from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from valkey_scale_lab.analysis import (
    SURFACE_NAMES,
    ValidatedAnalysis,
    ValidatedAnalysisError,
    analyze_validated_evidence,
)
from valkey_scale_lab.evidence import (
    build_candidate_admission,
    validate_candidate_admission,
)


STARTED = 1_800_000_000_000
PRODUCT_DIGEST = "a" * 64
PROBE = {
    "cluster_state": "ok",
    "known_nodes": 50,
    "slots_assigned": 16384,
    "slots_ok": 16384,
}
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _support_module():
    path = PROJECT_ROOT / "tests/provenance/test_milestone1_gate_measured_sources.py"
    spec = importlib.util.spec_from_file_location("validated_analysis_support", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bundle(tmp_path: Path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    base = _support_module()._bundle(evidence)
    preflight_path = base / "runtime/resource_preflight.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    preflight["checks"] = [{"name": "memory", "status": "PASS"}]
    preflight_path.write_text(json.dumps(preflight) + "\n", encoding="utf-8")
    admission = build_candidate_admission(
        base,
        50,
        PRODUCT_DIGEST,
        run_started_unix_ms=STARTED,
        run_ended_unix_ms=STARTED + 1000,
        valkey_versions=["9.1.0"],
        independent_probe=PROBE,
        source_commit="b" * 40,
    )
    return validate_candidate_admission(
        base,
        50,
        expected_product_digest=PRODUCT_DIGEST,
        admission=admission,
    )


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_analyzer_requires_the_validated_bundle_capability(tmp_path: Path) -> None:
    output = tmp_path / "analysis.json"
    for invalid in ({}, tmp_path, {"status": "PASS"}):
        with pytest.raises(ValidatedAnalysisError, match="ValidatedEvidenceBundle"):
            analyze_validated_evidence(invalid, output)  # type: ignore[arg-type]
    assert not output.exists()


def test_validated_analysis_is_derived_complete_frozen_and_non_mutating(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    before = _tree_hashes(bundle.root)
    output = tmp_path / "derived/analysis.json"

    analysis = analyze_validated_evidence(bundle, output)

    assert isinstance(analysis, ValidatedAnalysis)
    assert analysis.evidence_root == bundle.root.resolve()
    assert analysis.path == output.resolve()
    assert analysis.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    assert analysis.admission_digest == bundle.admission_digest
    assert analysis.definition_digest == bundle.definition_digest
    assert analysis.product_digest == bundle.product_digest
    assert analysis.capture_digest == bundle.admission["capture_digest"]
    assert analysis.provenance_digest == bundle.admission["provenance"]["digest"]
    assert analysis.source_artifacts == bundle.artifacts
    assert _tree_hashes(bundle.root) == before

    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["status"] == "DERIVED"
    assert set(document["surfaces"]) == set(SURFACE_NAMES)
    assert document["surfaces"]["topology"]["observed_nodes"] == 50
    assert document["surfaces"]["lifecycle_timing"]["step_count"] == 12
    assert document["surfaces"]["resources"]["metrics"]["used_memory"]["max"] == 1.0
    assert len(document["surfaces"]["management_operations"]["scenario_results"]) == 4
    assert document["surfaces"]["cleanup"]["residual_resources"] == []
    assert document["surfaces"]["failover"]["details"]["status"] == "MISSING"
    assert all(
        item["status"] in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"}
        and item["reason"]
        for item in document["surfaces"]["missing_evidence"]["items"]
    )
    assert len(document["source_artifacts"]) == len(bundle.artifacts)
    assert {item["kind"] for item in document["source_artifacts"]} == {
        record.kind for record in bundle.artifacts
    }
    assert document["digests"]["admission"] == bundle.admission_digest
    assert document["digests"]["run"] == bundle.admission["capture_digest"]
    with pytest.raises(TypeError):
        analysis.document["status"] = "PASS"  # type: ignore[index]


def test_analyzer_rechecks_hash_confinement_and_protects_evidence_root(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    with pytest.raises(ValidatedAnalysisError, match="outside"):
        analyze_validated_evidence(bundle, bundle.root / "analysis.json")

    first = bundle.artifacts[0]
    path = bundle.root / first.path
    path.write_text("{}\n", encoding="utf-8")
    output = tmp_path / "tampered-analysis.json"
    with pytest.raises(ValidatedAnalysisError, match="hash changed"):
        analyze_validated_evidence(bundle, output)
    assert not output.exists()


def test_analyzer_rejects_a_forged_traversal_record(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    forged_record = dataclasses.replace(
        bundle.artifacts[0],
        path="../outside.json",
        sha256=hashlib.sha256(outside.read_bytes()).hexdigest(),
    )
    forged_bundle = dataclasses.replace(
        bundle,
        artifacts=(forged_record, *bundle.artifacts[1:]),
    )

    with pytest.raises(ValidatedAnalysisError, match="escapes"):
        analyze_validated_evidence(forged_bundle, tmp_path / "derived.json")
