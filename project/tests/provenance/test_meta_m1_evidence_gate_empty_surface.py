from __future__ import annotations

import json
from pathlib import Path

from test_meta_m1_evidence_gate import _rehash, _write_json, build_complete_bundle, gate


def test_rejects_empty_required_report_surface(tmp_path: Path) -> None:
    base = build_complete_bundle(tmp_path)
    path = base / "runtime/analysis_summary.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    for surface in gate.REPORT_SURFACES - {"missing_evidence"}:
        value[surface] = {"observed": True}
    value["missing_evidence"] = []
    value["resources"] = {}
    _write_json(path, value)
    _rehash(base, "analysis_summary")

    assert any("resources" in error for error in gate.evaluate(50, tmp_path))
