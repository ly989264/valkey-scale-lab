#!/usr/bin/env python3
"""Build a prerequisite record from a successful run and final admission."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


class BuildError(RuntimeError):
    pass


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"{path} must contain an object")
    return value


def final_requirement(requirements: Any) -> dict[str, Any]:
    if not isinstance(requirements, list) or not requirements:
        raise BuildError("milestone has no final real evidence requirement")
    by_id = {
        item.get("id"): item
        for item in requirements
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if len(by_id) != len(requirements):
        raise BuildError("real evidence requirement ids must be unique strings")
    sources = {item.get("promotion_source_id") for item in requirements if item.get("promotion_source_id") is not None}
    terminal_ids = set(by_id) - sources
    if len(terminal_ids) != 1:
        raise BuildError("real evidence requirements must form one promotion chain")
    return by_id[terminal_ids.pop()]


def build(
    *,
    milestone_path: Path,
    terminal_path: Path,
    final_admission_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    milestone = load_json(milestone_path)
    terminal = load_json(terminal_path)
    admission = load_json(final_admission_path)
    identity = milestone.get("milestone")
    if milestone.get("schema_version") != "valkey-milestone-v2" or not isinstance(identity, dict):
        raise BuildError("invalid product milestone")
    milestone_id = identity.get("id")
    requirement = final_requirement(milestone.get("real_evidence_requirements"))
    if (
        terminal.get("schema_version") != "controller-run-result-v1"
        or terminal.get("status") != "SUCCESS"
        or terminal.get("milestone_id") != milestone_id
        or terminal.get("goal_state", {}).get("complete") is not True
    ):
        raise BuildError("terminal result is not a successful current Milestone run")
    unsigned_admission = dict(admission)
    admission_digest = unsigned_admission.pop("admission_digest", None)
    if admission_digest != canonical_digest(unsigned_admission):
        raise BuildError("final admission digest is invalid")
    parameters = requirement.get("parameters")
    expected_nodes = parameters.get("nodes") if isinstance(parameters, dict) else None
    evidence_rows = terminal.get("goal_state", {}).get("evidence_results", [])
    terminal_evidence = next(
        (
            item
            for item in evidence_rows
            if isinstance(item, dict) and item.get("id") == f"evidence.{requirement['id']}"
        ),
        {},
    )
    terminal_provenance = terminal_evidence.get("provenance", {})
    if (
        admission.get("status") != "PASS"
        or admission.get("requested_nodes") != expected_nodes
        or admission.get("observed_nodes") != expected_nodes
        or terminal_evidence.get("status") != "PASS"
        or terminal_provenance.get("admission_digest") != admission_digest
        or terminal_provenance.get("product_digest") != admission.get("product_digest")
        or terminal_provenance.get("run_id") != admission.get("invocation_run_id")
    ):
        raise BuildError("final admission does not match the terminal product, run, and exact scale")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    copied_terminal = output / "terminal.json"
    shutil.copy2(terminal_path, copied_terminal)
    completion: dict[str, Any] = {
        "schema_version": "valkey-prerequisite-completion-v1",
        "milestone_id": milestone_id,
        "terminal_status": "SUCCESS",
        "product_digest": admission["product_digest"],
        "completed_at_unix": terminal_provenance["captured_at_unix"],
        "final_evidence_requirement_id": requirement["id"],
        "final_admission_digest": admission_digest,
        "terminal_result": {"path": "terminal.json", "sha256": file_digest(copied_terminal)},
    }
    completion["completion_digest"] = canonical_digest(completion)
    (output / "completion.json").write_text(
        json.dumps(completion, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return completion


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--milestone", type=Path, required=True)
    parser.add_argument("--terminal", type=Path, required=True)
    parser.add_argument("--final-admission", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        build(
            milestone_path=args.milestone,
            terminal_path=args.terminal,
            final_admission_path=args.final_admission,
            output_dir=args.output_dir,
        )
        return 0
    except (BuildError, OSError, ValueError) as exc:
        print(f"ERROR: prerequisite: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
