#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import STRICT_STAGE_IDS, load_json, phase_dir, print_errors, rel, require_json, strict_handoff_dir  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    errors: list[str] = []
    state_path = ROOT / "codex" / "status" / "phase_state.json"
    state = require_json(state_path, errors, "phase state")
    completed = set(state.get("completed_phases", [])) if state else set()
    for stage_id in STRICT_STAGE_IDS[:-1]:
        if stage_id not in completed:
            errors.append(f"{stage_id}: not marked complete")
        gate_path = ROOT / "artifacts" / "gates" / stage_id / "gate_result.json"
        if gate_path.exists():
            try:
                gate = load_json(gate_path)
                if gate.get("status") != "PASS":
                    errors.append(f"{rel(gate_path)}: status must be PASS")
            except Exception as exc:
                errors.append(f"{rel(gate_path)}: invalid JSON: {exc}")
        else:
            errors.append(f"gate result missing: {rel(gate_path)}")
        review = strict_handoff_dir(stage_id) / "REVIEW.md"
        if not review.exists() or "Decision: PASS" not in review.read_text(encoding="utf-8", errors="replace"):
            errors.append(f"{stage_id}: strict review Decision: PASS missing")
        completion = strict_handoff_dir(stage_id) / "COMPLETION.md"
        if not completion.exists():
            errors.append(f"{stage_id}: completion record missing")
    closeout = require_json(phase_dir(args.phase) / "final_strict_audit_report.json", errors, "final strict audit report")
    if closeout and closeout.get("status") != "PASS":
        errors.append("final_strict_audit_report status must be PASS")
    if errors:
        return print_errors(errors)
    print(f"PASS final strict closeout phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

