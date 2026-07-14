from __future__ import annotations

import json
from pathlib import Path

from scripts import meta_m1_evidence_gate_v8 as v8_gate
import test_meta_m1_evidence_gate as bundle_support


def _bundle(root: Path, monkeypatch) -> Path:
    monkeypatch.setattr(bundle_support, "gate", v8_gate)
    return bundle_support.build_complete_bundle(root)


def test_v8_self_contained_evaluator_accepts_complete_bundle(tmp_path: Path, monkeypatch) -> None:
    _bundle(tmp_path, monkeypatch)
    assert v8_gate.evaluate(50, tmp_path) == []


def test_v8_self_contained_evaluator_rejects_stale_product(tmp_path: Path, monkeypatch) -> None:
    base = _bundle(tmp_path, monkeypatch)
    admission_path = base / "admission.json"
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    admission["product_digest"] = "0" * 64
    bundle_support._write_json(admission_path, admission)
    assert any("product_digest" in error for error in v8_gate.evaluate(50, tmp_path))


def test_v8_self_contained_evaluator_rejects_artifact_hash_mutation(tmp_path: Path, monkeypatch) -> None:
    base = _bundle(tmp_path, monkeypatch)
    (base / "runtime/analysis_summary.json").write_text("{}\n", encoding="utf-8")
    assert any("hash mismatch" in error for error in v8_gate.evaluate(50, tmp_path))
