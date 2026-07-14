from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from _common import EvaluationError, canonical_digest, file_digest, load_json


HEX64 = re.compile(r"[0-9a-f]{64}", re.ASCII)


def load_completion(path: Path, expected_milestone_id: str) -> dict[str, Any]:
    value = load_json(path)
    expected = {
        "schema_version": "valkey-prerequisite-completion-v1",
        "milestone_id": expected_milestone_id,
        "terminal_status": "SUCCESS",
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise EvaluationError(f"prerequisite {expected_milestone_id} has invalid {field}")
    for field in ("product_digest", "final_admission_digest"):
        if HEX64.fullmatch(str(value.get(field, ""))) is None:
            raise EvaluationError(f"prerequisite {expected_milestone_id} has invalid {field}")
    if not isinstance(value.get("completed_at_unix"), int):
        raise EvaluationError(f"prerequisite {expected_milestone_id} has no completion timestamp")
    if not isinstance(value.get("final_evidence_requirement_id"), str) or not value["final_evidence_requirement_id"]:
        raise EvaluationError(f"prerequisite {expected_milestone_id} has no final evidence requirement")
    reference = value.get("terminal_result")
    if not isinstance(reference, dict) or reference.get("path") != "terminal.json":
        raise EvaluationError(f"prerequisite {expected_milestone_id} has an unsafe terminal result reference")
    terminal_path = path.parent / "terminal.json"
    if (
        not terminal_path.is_file()
        or terminal_path.is_symlink()
        or reference.get("sha256") != file_digest(terminal_path)
    ):
        raise EvaluationError(f"prerequisite {expected_milestone_id} terminal result digest mismatch")
    terminal = load_json(terminal_path)
    evidence_rows = terminal.get("goal_state", {}).get("evidence_results", [])
    final_evidence = next(
        (
            item
            for item in evidence_rows
            if isinstance(item, dict)
            and item.get("id") == f"evidence.{value['final_evidence_requirement_id']}"
        ),
        {},
    )
    provenance = final_evidence.get("provenance", {})
    if (
        terminal.get("schema_version") != "controller-run-result-v1"
        or terminal.get("status") != "SUCCESS"
        or terminal.get("milestone_id") != expected_milestone_id
        or terminal.get("goal_state", {}).get("complete") is not True
        or final_evidence.get("status") != "PASS"
        or provenance.get("product_digest") != value.get("product_digest")
        or provenance.get("admission_digest") != value.get("final_admission_digest")
    ):
        raise EvaluationError(f"prerequisite {expected_milestone_id} terminal result is not SUCCESS")
    claimed = value.get("completion_digest")
    unsigned = dict(value)
    unsigned.pop("completion_digest", None)
    if claimed != canonical_digest(unsigned):
        raise EvaluationError(f"prerequisite {expected_milestone_id} completion digest mismatch")
    return value
