from __future__ import annotations

import json
from pathlib import Path

from scripts import meta_m1_evidence_gate as gate
from test_meta_m1_evidence_gate import _rehash, _write_json, build_complete_bundle


def test_rejects_200_node_preflight_that_finishes_after_runtime_starts(tmp_path: Path) -> None:
    base = build_complete_bundle(tmp_path, scale=200)
    path = base / "runtime/lifecycle_timeline.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    steps = {step["id"]: step for step in value["steps"]}
    steps["runtime_start"]["started_monotonic_ms"] = 100
    steps["runtime_start"]["ended_monotonic_ms"] = 105
    steps["resource_preflight"]["started_monotonic_ms"] = 200
    steps["resource_preflight"]["ended_monotonic_ms"] = 205
    _write_json(path, value)
    _rehash(base, "lifecycle_timeline")

    errors = gate.evaluate(200, tmp_path)
    assert any("resource_preflight" in error and "runtime_start" in error for error in errors), errors
