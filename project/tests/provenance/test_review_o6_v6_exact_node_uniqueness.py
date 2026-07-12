from __future__ import annotations

import json
from pathlib import Path

from test_meta_m1_evidence_gate import _rehash, _write_json, build_complete_bundle, gate


def test_rejects_200_node_admission_with_duplicate_logical_nodes(tmp_path: Path) -> None:
    base = build_complete_bundle(tmp_path, scale=200)
    path = base / "runtime/run_state.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["nodes"] = [{"logical_id": "node-0"} for _ in range(200)]
    _write_json(path, value)
    _rehash(base, "run_metadata")

    errors = gate.evaluate(200, tmp_path)

    assert any("unique" in error and "logical" in error for error in errors), errors
