from __future__ import annotations

from pathlib import Path

from scripts import meta_m1_evidence_gate as gate
from test_meta_m1_evidence_gate import _rehash, build_complete_bundle


def test_rejects_same_commands_claimed_as_management_and_fault_evidence(tmp_path: Path) -> None:
    base = build_complete_bundle(tmp_path)
    management = base / "runtime/management_command_log.jsonl"
    fault = base / "runtime/fault_command_log.jsonl"
    combined = management.read_text(encoding="utf-8") + fault.read_text(encoding="utf-8")
    management.write_text(combined, encoding="utf-8")
    fault.write_text(combined, encoding="utf-8")
    _rehash(base, "command_log")
    _rehash(base, "fault_command_log")

    errors = gate.evaluate(50, tmp_path)
    assert any("management" in error and "fault" in error for error in errors), errors
