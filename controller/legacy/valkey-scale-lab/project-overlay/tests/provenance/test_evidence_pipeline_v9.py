from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

from scripts import meta_m1_evidence_gate_v9 as frozen_evaluator
from valkey_scale_lab import milestone1_gate
from valkey_scale_lab.evidence import (
    ADMISSION_SCHEMA_VERSION,
    MISSING_STATUSES,
    build_candidate_admission,
    canonical_bundle_spec,
    validate_candidate_admission,
    validate_raw_sources,
)

from test_milestone1_gate_measured_sources import STARTED, _bundle


PRODUCT_DIGEST = frozen_evaluator.product_tree_digest(frozen_evaluator.PROJECT_ROOT)
SOURCE_COMMIT = "b" * 40
PROBE = {
    "cluster_state": "ok",
    "known_nodes": 50,
    "slots_assigned": 16384,
    "slots_ok": 16384,
}


def _complete_capture(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    base = _bundle(root)
    path = base / "runtime/resource_preflight.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["checks"] = [{"name": "memory", "status": "PASS"}]
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return base


def _raw_hashes(base: Path) -> dict[str, str]:
    spec = canonical_bundle_spec()
    return {
        name: hashlib.sha256((base / "runtime" / name).read_bytes()).hexdigest()
        for name in spec.raw_artifact_names
    }


def _candidate(base: Path) -> dict:
    return build_candidate_admission(
        base,
        50,
        PRODUCT_DIGEST,
        run_started_unix_ms=STARTED,
        run_ended_unix_ms=STARTED + 1000,
        valkey_versions=["9.1.0"],
        independent_probe=PROBE,
        source_commit=SOURCE_COMMIT,
    )


def test_capture_validation_and_candidate_admission_are_separate(tmp_path: Path) -> None:
    base = _complete_capture(tmp_path / "scale-50")
    before = _raw_hashes(base)

    assert not (base / "admission.json").exists()
    assert validate_raw_sources(base, 50) == ()
    assert not (base / "admission.json").exists()

    admission = _candidate(base)

    assert _raw_hashes(base) == before
    assert admission["schema_version"] == ADMISSION_SCHEMA_VERSION
    assert admission["requested_nodes"] == admission["observed_nodes"] == 50
    assert all(item["path"].startswith("runtime/admission_v2/") for item in admission["artifacts"])
    assert all(
        item["sha256"] == hashlib.sha256((base / item["path"]).read_bytes()).hexdigest()
        for item in admission["artifacts"]
    )

    validated = validate_candidate_admission(
        base,
        50,
        expected_product_digest=PRODUCT_DIGEST,
        admission=admission,
    )
    assert validated.run_id == "measured-source-run"
    assert validated.product_digest == PRODUCT_DIGEST
    assert validated.definition_digest == canonical_bundle_spec().definition_digest
    assert len(validated.artifacts) == len(admission["artifacts"])
    assert all(record.source_sha256 == before[Path(record.source_path).name] for record in validated.artifacts)
    assert frozen_evaluator.evaluate(50, tmp_path) == []


def test_legacy_gate_api_is_a_thin_canonical_compatibility_adapter(
    tmp_path: Path, monkeypatch
) -> None:
    base = _complete_capture(tmp_path)
    spec = canonical_bundle_spec()

    assert milestone1_gate.ADMISSION_SCHEMA_VERSION == ADMISSION_SCHEMA_VERSION
    assert milestone1_gate.LIFECYCLE == list(spec.lifecycle_ids)
    assert milestone1_gate.SCENARIOS == [
        *spec.management_scenario_ids,
        *spec.fault_scenario_ids,
    ]
    assert milestone1_gate.validate_admission_sources(base, 50) == list(
        validate_raw_sources(base, 50)
    )
    assert tuple(inspect.signature(milestone1_gate.run_real_gate).parameters) == (
        "scale",
        "evidence_dir",
    )
    assert tuple(
        inspect.signature(milestone1_gate.build_admission_from_sources).parameters
    ) == (
        "base",
        "scale",
        "product_digest",
        "run_started_unix_ms",
        "run_ended_unix_ms",
        "valkey_versions",
        "independent_probe",
    )

    sentinel = {"status": "delegated"}
    calls: list[tuple[tuple, dict]] = []

    def fake_builder(*args, **kwargs):
        calls.append((args, kwargs))
        return sentinel

    monkeypatch.setattr(milestone1_gate, "_build_candidate_admission", fake_builder)
    result = milestone1_gate.build_admission_from_sources(
        base,
        50,
        PRODUCT_DIGEST,
        run_started_unix_ms=STARTED,
        run_ended_unix_ms=STARTED + 1000,
        valkey_versions=["9.1.0"],
        independent_probe=PROBE,
    )

    assert result is sentinel
    assert calls == [
        (
            (base.resolve(), 50, PRODUCT_DIGEST),
            {
                "run_started_unix_ms": STARTED,
                "run_ended_unix_ms": STARTED + 1000,
                "valkey_versions": ["9.1.0"],
                "independent_probe": PROBE,
            },
        )
    ]


def test_missing_data_taxonomy_requires_an_explicit_reason(tmp_path: Path) -> None:
    assert MISSING_STATUSES == (
        "MISSING",
        "SKIPPED_WITH_REASON",
        "UNSUPPORTED_WITH_REASON",
    )
    base = _complete_capture(tmp_path)
    path = base / "runtime/analysis_summary.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["missing_evidence"] = [
        {"metric": "client_recovery_ms", "status": "SKIPPED_WITH_REASON"}
    ]
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    assert any("reason" in error for error in validate_raw_sources(base, 50))

    value["missing_evidence"][0]["reason"] = "probe was not supported by this run"
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    assert validate_raw_sources(base, 50) == ()
