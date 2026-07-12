from __future__ import annotations

import json
from pathlib import Path

from scripts import meta_m1_evidence_gate as gate
from test_meta_m1_evidence_gate import _rehash, build_complete_bundle


def _stamp_single_operation(path: Path) -> None:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row["operation_id"] = "one-observed-operation"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_rejects_one_operation_relabelled_as_every_required_scenario(tmp_path: Path) -> None:
    base = build_complete_bundle(tmp_path)
    for filename, kind in (
        ("management_command_log.jsonl", "command_log"),
        ("fault_command_log.jsonl", "fault_command_log"),
        ("events.jsonl", "events"),
    ):
        _stamp_single_operation(base / "runtime" / filename)
        _rehash(base, kind)

    errors = gate.evaluate(50, tmp_path)
    assert any("operation" in error and "scenario" in error for error in errors), errors
