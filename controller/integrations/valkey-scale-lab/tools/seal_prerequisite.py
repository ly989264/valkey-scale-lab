#!/usr/bin/env python3
"""Build an operator-reviewed prerequisite completion snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


HEX64 = re.compile(r"[0-9a-f]{64}")


class SealError(RuntimeError):
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
        raise SealError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SealError(f"{path} must contain an object")
    return value


def seal(
    *,
    milestone_path: Path,
    terminal_path: Path,
    final_admission_path: Path,
    output_dir: Path,
    terminal_verified: bool,
) -> dict[str, Any]:
    if not terminal_verified:
        raise SealError("operator must first verify the terminal receipt with its CONTROLLER run authority")
    milestone = load_json(milestone_path)
    terminal = load_json(terminal_path)
    admission = load_json(final_admission_path)
    identity = milestone.get("milestone")
    gates = milestone.get("evidence_gates")
    if not isinstance(identity, dict) or not isinstance(gates, list) or not gates:
        raise SealError("milestone has no final evidence gate")
    milestone_id = identity.get("id")
    final_gate = gates[-1]
    if (
        terminal.get("schema_version") != "controller-terminal-receipt-v1"
        or terminal.get("status") != "SUCCESS"
        or terminal.get("milestone_id") != f"ValkeyScaleLab.{milestone_id}"
        or HEX64.fullmatch(str(terminal.get("receipt_tag", ""))) is None
    ):
        raise SealError("terminal receipt is not a successful authenticated milestone receipt")
    unsigned_admission = dict(admission)
    claimed_admission = unsigned_admission.pop("admission_digest", None)
    if claimed_admission != canonical_digest(unsigned_admission):
        raise SealError("final admission digest is invalid")
    expected_nodes = final_gate.get("parameters", {}).get("nodes")
    if (
        admission.get("status") != "PASS"
        or admission.get("requested_nodes") != expected_nodes
        or admission.get("observed_nodes") != expected_nodes
        or admission.get("product_digest") != terminal.get("product_digest")
        or admission.get("invocation_run_id") != terminal.get("run_id")
    ):
        raise SealError("final admission does not bind the terminal product, run, and exact gate")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    copied_terminal = output / "terminal.json"
    shutil.copy2(terminal_path, copied_terminal)
    completion: dict[str, Any] = {
        "schema_version": "valkey-prerequisite-completion-v1",
        "milestone_id": milestone_id,
        "controller_milestone_id": f"ValkeyScaleLab.{milestone_id}",
        "terminal_status": "SUCCESS",
        "product_digest": terminal["product_digest"],
        "completed_at_unix": terminal["created_at_unix"],
        "final_gate_id": final_gate["id"],
        "final_admission_digest": claimed_admission,
        "terminal_receipt": {
            "path": "terminal.json",
            "sha256": file_digest(copied_terminal),
        },
    }
    completion["attestation_digest"] = canonical_digest(completion)
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
    parser.add_argument("--terminal-verified", action="store_true")
    args = parser.parse_args()
    try:
        seal(
            milestone_path=args.milestone,
            terminal_path=args.terminal,
            final_admission_path=args.final_admission,
            output_dir=args.output_dir,
            terminal_verified=args.terminal_verified,
        )
        return 0
    except (SealError, OSError, ValueError) as exc:
        print(f"ERROR: prerequisite seal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
