from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

import pytest

from scripts.schema_validator import validate as validate_schema
from valkey_scale_lab.evidence import (
    validate_raw_sources_by_kind,
    EvidenceBundleSpec,
    EvidenceValidationError,
    build_candidate_admission,
    canonical_bundle_spec,
    validate_candidate_admission,
    validate_raw_sources,
)
from valkey_scale_lab.scenarios import load_local_full_flow_definition


STARTED = 1_800_000_000_000
PRODUCT_DIGEST = "a" * 64
PROBE = {
    "cluster_state": "ok",
    "known_nodes": 50,
    "slots_assigned": 16384,
    "slots_ok": 16384,
}
ROOT = Path(__file__).resolve().parents[2]
DEFINITION = load_local_full_flow_definition()


def _support_module():
    path = ROOT / "tests/provenance/test_exact_gate_measured_sources.py"
    spec = importlib.util.spec_from_file_location("evidence_measured_support", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture(tmp_path: Path) -> Path:
    base = _support_module()._bundle(tmp_path)
    path = base / "runtime/resource_preflight.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["checks"] = [{"name": "memory", "status": "PASS"}]
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return base


def _candidate(base: Path) -> dict:
    return build_candidate_admission(
        base,
        50,
        PRODUCT_DIGEST,
        definition=DEFINITION,
        run_started_unix_ms=STARTED,
        run_ended_unix_ms=STARTED + 1000,
        valkey_versions=["9.1.0"],
        independent_probe=PROBE,
        source_commit="b" * 40,
        run_owner="pytest",
    )


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def test_bundle_spec_is_an_immutable_projection_of_the_scenario_definition() -> None:
    definition = DEFINITION
    spec = canonical_bundle_spec(definition)

    assert isinstance(spec, EvidenceBundleSpec)
    assert spec.definition_digest == definition.digest
    assert spec.raw_artifact_names == definition.raw_artifact_names
    assert spec.required_raw_artifact_names == definition.raw_artifact_names
    assert spec.admitted_artifact_kinds == definition.admitted_artifact_ids
    with pytest.raises(TypeError):
        spec.raw_formats["run_state.json"] = "jsonl"  # type: ignore[index]


def test_raw_validation_rejects_duplicate_nodes_cross_run_and_relabelling(
    tmp_path: Path,
) -> None:
    base = _capture(tmp_path)
    run_state_path = base / "runtime/run_state.json"
    run_state = json.loads(run_state_path.read_text(encoding="utf-8"))
    run_state["nodes"][1]["logical_id"] = run_state["nodes"][0]["logical_id"]
    _write_json(run_state_path, run_state)
    assert any("unique logical_id" in error for error in validate_raw_sources(base, 50, DEFINITION))

    run_state["nodes"][1]["logical_id"] = "node-1"
    _write_json(run_state_path, run_state)
    metrics_path = base / "runtime/metrics_timeseries.jsonl"
    metric = json.loads(metrics_path.read_text(encoding="utf-8"))
    metric["run_id"] = "another-run"
    metrics_path.write_text(json.dumps(metric) + "\n", encoding="utf-8")
    assert any("another run" in error for error in validate_raw_sources(base, 50, DEFINITION))

    metric["run_id"] = run_state["run_id"]
    metrics_path.write_text(json.dumps(metric) + "\n", encoding="utf-8")
    events_path = base / "runtime/events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    events[0]["scenario_id"] = "replica_stop"
    events_path.write_text("".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")
    assert any("event provenance" in error for error in validate_raw_sources(base, 50, DEFINITION))


def test_candidate_validation_binds_raw_hashes_paths_and_product_digest(
    tmp_path: Path,
) -> None:
    base = _capture(tmp_path)
    admission = _candidate(base)
    validated = validate_candidate_admission(
        base, 50, expected_product_digest=PRODUCT_DIGEST, admission=admission, definition=DEFINITION
    )
    assert validated.product_digest == PRODUCT_DIGEST
    assert all(record.source_sha256 for record in validated.artifacts)
    assert len({record.provenance_node_id for record in validated.artifacts}) == len(
        validated.artifacts
    )

    (base / "runtime/analysis_summary.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(EvidenceValidationError) as excinfo:
        validate_candidate_admission(base, 50, PRODUCT_DIGEST, admission=admission, definition=DEFINITION)
    assert any("source hash mismatch" in error for error in excinfo.value.errors)


def test_candidate_validation_rejects_escaping_artifact_and_stale_product(
    tmp_path: Path,
) -> None:
    base = _capture(tmp_path)
    admission = _candidate(base)
    admission["artifacts"][0]["path"] = "../escape.json"
    admission["product_digest"] = "c" * 64

    with pytest.raises(EvidenceValidationError) as excinfo:
        validate_candidate_admission(base, 50, PRODUCT_DIGEST, admission=admission, definition=DEFINITION)
    joined = "; ".join(excinfo.value.errors)
    assert "escapes evidence root" in joined
    assert "product_digest mismatch" in joined


def test_candidate_validation_rejects_cross_run_and_admission_source_relabelling(
    tmp_path: Path,
) -> None:
    base = _capture(tmp_path)
    admission = _candidate(base)
    admission["run_id"] = "relabeled-run"
    first = admission["artifacts"][0]
    false_source = base / "runtime/analysis_summary.json"
    first["source_path"] = "runtime/analysis_summary.json"
    first["source_sha256"] = hashlib.sha256(false_source.read_bytes()).hexdigest()

    with pytest.raises(EvidenceValidationError) as excinfo:
        validate_candidate_admission(base, 50, PRODUCT_DIGEST, admission=admission, definition=DEFINITION)
    joined = "; ".join(excinfo.value.errors)
    assert "raw capture run_id" in joined
    assert "canonical raw artifact" in joined
    assert "provenance_node_id mismatch" in joined


def test_candidate_validation_recomputes_capture_and_provenance_documents(
    tmp_path: Path,
) -> None:
    base = _capture(tmp_path)
    admission = _candidate(base)
    capture_path = base / admission["capture_manifest"]["path"]
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    capture["artifacts"][0]["sha256"] = "0" * 64
    _write_json(capture_path, capture)
    admission["capture_manifest"]["sha256"] = hashlib.sha256(
        capture_path.read_bytes()
    ).hexdigest()

    provenance_path = base / admission["provenance"]["path"]
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["admission_nodes"][0]["source_sha256"] = "0" * 64
    _write_json(provenance_path, provenance)
    admission["provenance"]["sha256"] = hashlib.sha256(
        provenance_path.read_bytes()
    ).hexdigest()

    with pytest.raises(EvidenceValidationError) as excinfo:
        validate_candidate_admission(base, 50, PRODUCT_DIGEST, admission=admission, definition=DEFINITION)
    joined = "; ".join(excinfo.value.errors)
    assert "capture_manifest does not match" in joined
    assert "provenance document does not match" in joined


def test_generated_capture_provenance_and_candidate_match_versioned_schemas(
    tmp_path: Path,
) -> None:
    base = _capture(tmp_path)
    admission = _candidate(base)
    cases = (
        (
            ROOT / "schemas/artifact/evidence_capture_manifest.schema.json",
            json.loads((base / admission["capture_manifest"]["path"]).read_text(encoding="utf-8")),
        ),
        (
            ROOT / "schemas/artifact/evidence_provenance.schema.json",
            json.loads((base / admission["provenance"]["path"]).read_text(encoding="utf-8")),
        ),
        (ROOT / "schemas/artifact/evidence_admission_candidate.schema.json", admission),
    )
    for schema_path, instance in cases:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert validate_schema(instance, schema) == []


def test_unreadable_evidence_is_a_tool_error_and_does_not_masquerade_as_a_failure(
    tmp_path: Path,
) -> None:
    """§12.1's 必要证据无法写入 sits on the collector's side of the line.

    This validator runs only after a passing gate, so by then every declared
    artifact should exist. One that is missing or unparseable at that point is the
    evidence layer breaking, not the cluster being observed and found wanting - and
    reporting it as a run failure told a reader something untrue.
    """

    base = _capture(tmp_path)
    assert not validate_raw_sources_by_kind(base, 50, DEFINITION)

    (base / "runtime/full_flow_result.json").write_text("{not json", encoding="utf-8")
    errors = validate_raw_sources_by_kind(base, 50, DEFINITION)

    assert errors.tool and all("full_flow_result.json" in row for row in errors.tool)
    # The bug this pairs with: every check below the load reads a missing name as
    # `{}`, so an unreadable file used to also produce `must PASS for the admitted
    # run` - a derived semantic error that would then outrank, and hide, the tool
    # error that caused it.
    assert errors.semantic == ()
    assert not any("must PASS" in row for row in errors.all)

    # A file that opens and parses but holds the wrong shape is the producer's
    # failure, and stays semantic.
    _write_json(base / "runtime/full_flow_result.json", {"status": "PASS"})
    reshaped = validate_raw_sources_by_kind(base, 50, DEFINITION)
    assert reshaped.tool == ()
    assert any("full_flow_result.json must PASS" in row for row in reshaped.semantic)

    # The flat helper every other caller uses still reports everything, in §12.2's
    # order, so nothing that only asks "is this admissible" had to change.
    (base / "runtime/full_flow_result.json").unlink()
    flat = validate_raw_sources(base, 50, DEFINITION)
    assert flat == validate_raw_sources_by_kind(base, 50, DEFINITION).all
    assert any("is missing or invalid" in row for row in flat)
