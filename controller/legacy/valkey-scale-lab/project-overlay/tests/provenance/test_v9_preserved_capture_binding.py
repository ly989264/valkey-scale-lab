from __future__ import annotations

import json

from scripts import meta_m1_evidence_gate_v9 as v9_gate
from test_evidence_pipeline_v9 import _candidate, _complete_capture


def test_v9_rejects_changed_preserved_raw_capture(tmp_path) -> None:
    base = _complete_capture(tmp_path / "scale-50")
    _candidate(base)

    path = base / "runtime/run_state.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["nodes"][0]["logical_id"] = "forged-node"
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    errors = v9_gate.evaluate(50, tmp_path)
    assert any("capture" in error or "source hash" in error for error in errors)
