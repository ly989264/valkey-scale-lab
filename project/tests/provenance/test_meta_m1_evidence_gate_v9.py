from __future__ import annotations

import json
from pathlib import Path

from scripts import meta_m1_evidence_gate_v9 as v9_gate
import test_meta_m1_evidence_gate as bundle_support


def _bundle(root: Path, monkeypatch) -> Path:
    monkeypatch.setattr(bundle_support, "gate", v9_gate)
    return bundle_support.build_complete_bundle(root)


def test_v9_self_contained_evaluator_accepts_complete_bundle(tmp_path: Path, monkeypatch) -> None:
    _bundle(tmp_path, monkeypatch)
    assert v9_gate.evaluate(50, tmp_path) == []


def test_v9_self_contained_evaluator_rejects_stale_product(tmp_path: Path, monkeypatch) -> None:
    base = _bundle(tmp_path, monkeypatch)
    admission_path = base / "admission.json"
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    admission["product_digest"] = "0" * 64
    bundle_support._write_json(admission_path, admission)
    assert any("product_digest" in error for error in v9_gate.evaluate(50, tmp_path))


def test_v9_self_contained_evaluator_rejects_artifact_hash_mutation(tmp_path: Path, monkeypatch) -> None:
    base = _bundle(tmp_path, monkeypatch)
    (base / "runtime/analysis_summary.json").write_text("{}\n", encoding="utf-8")
    assert any("hash mismatch" in error for error in v9_gate.evaluate(50, tmp_path))


def test_v9_rejects_null_telemetry_without_missing_taxonomy(
    tmp_path: Path, monkeypatch
) -> None:
    base = _bundle(tmp_path, monkeypatch)
    admission_path = base / "admission.json"
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    artifact = next(row for row in admission["artifacts"] if row["kind"] == "metrics")
    metrics_path = base / artifact["path"]
    rows = [
        json.loads(line)
        for line in metrics_path.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["metric_value"] = None
    metrics_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    artifact["sha256"] = v9_gate._sha256(metrics_path)
    bundle_support._write_json(admission_path, admission)

    assert any(
        "missing-data taxonomy" in error
        for error in v9_gate.evaluate(50, tmp_path)
    )
