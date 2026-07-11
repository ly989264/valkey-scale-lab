from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from historical_schema_compat import (
    allowed_historical_report_commit,
    allowed_manifest_extension,
    allowed_phase_state_extension,
    validate_artifact,
)


ROOT = Path(__file__).parents[2]
REGISTRY = json.loads((ROOT / "codex/historical_schema_compat_registry.json").read_text(encoding="utf-8"))
ENTRY = next(entry for entry in REGISTRY["entries"] if entry["artifact_path"].endswith("P09_ANALYSIS_REPORTING/analysis_summary.json"))


def materialize(tmp_path: Path) -> tuple[Path, Path]:
    paths = [
        ENTRY["artifact_path"],
        ENTRY["current_schema_path"],
        ENTRY["historical_schema_path"],
        "artifacts/gates/P09_ANALYSIS_REPORTING/gate_result.json",
    ]
    for logical in paths:
        target = tmp_path / logical
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / logical, target)
    registry = {
        "schema_version": "v1",
        "artifact_type": "historical_schema_compat_registry",
        "entries": [ENTRY],
        "allowed_manifest_extensions": [],
    }
    target = tmp_path / "codex/historical_schema_compat_registry.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(registry), encoding="utf-8")
    return tmp_path / ENTRY["artifact_path"], tmp_path / ENTRY["current_schema_path"]


def test_exact_triple_binding_allows_versioned_historical_schema(tmp_path: Path) -> None:
    artifact, schema = materialize(tmp_path)
    result = validate_artifact(tmp_path, artifact, schema)
    assert result.errors == []
    assert result.compatibility_used is True
    assert result.schema_path == ENTRY["historical_schema_path"]


def test_artifact_mutation_is_not_accepted(tmp_path: Path) -> None:
    artifact, schema = materialize(tmp_path)
    artifact.write_bytes(artifact.read_bytes() + b"\n")
    result = validate_artifact(tmp_path, artifact, schema)
    assert result.errors
    assert result.compatibility_used is False
    assert "artifact SHA-256 binding mismatch" in result.compatibility_reason


def test_historical_schema_mutation_is_not_accepted(tmp_path: Path) -> None:
    artifact, schema = materialize(tmp_path)
    historical = tmp_path / ENTRY["historical_schema_path"]
    historical.write_bytes(historical.read_bytes() + b"\n")
    result = validate_artifact(tmp_path, artifact, schema)
    assert result.errors
    assert "historical schema SHA-256 binding mismatch" in result.compatibility_reason


def test_gate_manifest_mutation_is_not_accepted(tmp_path: Path) -> None:
    artifact, schema = materialize(tmp_path)
    gate = tmp_path / "artifacts/gates/P09_ANALYSIS_REPORTING/gate_result.json"
    payload = json.loads(gate.read_text(encoding="utf-8"))
    payload["manifest_sha256"] = "0" * 64
    gate.write_text(json.dumps(payload), encoding="utf-8")
    result = validate_artifact(tmp_path, artifact, schema)
    assert result.errors
    assert "gate manifest SHA-256 binding mismatch" in result.compatibility_reason


def test_unregistered_artifact_is_not_accepted(tmp_path: Path) -> None:
    artifact, schema = materialize(tmp_path)
    unregistered = artifact.with_name("unregistered.json")
    shutil.copyfile(artifact, unregistered)
    result = validate_artifact(tmp_path, unregistered, schema)
    assert result.errors
    assert "no exact historical binding" in result.compatibility_reason


def test_manifest_extension_allowlist_is_exact() -> None:
    entry = REGISTRY["allowed_manifest_extensions"][0]
    target = entry["targets"][0]
    assert allowed_manifest_extension(ROOT, target, entry["expected_historical_sha256"], entry["current_sha256"])
    assert not allowed_manifest_extension(ROOT, "artifacts/phases/P39/unlisted.json", entry["expected_historical_sha256"], entry["current_sha256"])
    assert not allowed_manifest_extension(ROOT, target, "0" * 64, entry["current_sha256"])
    assert not allowed_manifest_extension(ROOT, target, entry["expected_historical_sha256"], "0" * 64)


def test_phase_state_extension_allowlist_is_exact() -> None:
    entry = REGISTRY["allowed_phase_state_extensions"][0]
    target = entry["targets"][0]
    assert allowed_phase_state_extension(ROOT, target, entry["expected_historical_sha256"], entry["current_sha256"])
    assert not allowed_phase_state_extension(ROOT, "artifacts/phases/P39/unlisted.json", entry["expected_historical_sha256"], entry["current_sha256"])
    assert not allowed_phase_state_extension(ROOT, target, "0" * 64, entry["current_sha256"])
    assert not allowed_phase_state_extension(ROOT, target, entry["expected_historical_sha256"], "0" * 64)


def test_historical_report_binding_is_exact() -> None:
    entry = REGISTRY["allowed_historical_report_commit_bindings"][0]
    html = (ROOT / entry["html_path"]).read_text(encoding="utf-8")
    assert allowed_historical_report_commit(ROOT, entry["declared_root_commit_sha"], html)
    assert not allowed_historical_report_commit(ROOT, "0" * 40, html)
    assert not allowed_historical_report_commit(ROOT, entry["declared_root_commit_sha"], html + "modified")
