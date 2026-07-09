#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import exit_code, print_gate_summary, read_json, violation, write_gate_result
from manifest import ALLOWED_PASS_KINDS

GATE = "assert_final_milestone1_hardened"


def evaluate_final(manifest_path: Path) -> tuple[str, list[dict[str, Any]], list[str], dict[str, Any]]:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        return "FAIL", [violation("manifest_unreadable", "Evidence manifest is missing or invalid JSON.", path=str(manifest_path))], [], {}
    required = [claim for claim in manifest.get("claims", []) if isinstance(claim, dict) and claim.get("required_for_milestone_pass") is True]
    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    passed = 0
    failed = 0
    for claim in required:
        cid = str(claim.get("claim_id"))
        if claim.get("status") == "PASS" and claim.get("evidence_kind") in ALLOWED_PASS_KINDS:
            passed += 1
        elif claim.get("status") == "BLOCKED_WITH_REASON":
            blocked.append(f"{cid}: {claim.get('reason', 'blocked without detailed reason')}")
        else:
            failed += 1
            violations.append(violation("required_claim_not_passed", "Required final claim is neither PASS nor blocked with reason.", claim_id=cid))
    final_status = "FAIL" if violations else "BLOCKED_WITH_REASON" if blocked else "PASS"
    return final_status, violations, blocked, {
        "hardening_loop_status": "PASS" if final_status in {"PASS", "BLOCKED_WITH_REASON"} else "FAIL",
        "milestone1_status": final_status,
        "false_pass_prevented": final_status != "PASS",
        "required_claim_count": len(required),
        "passed_claim_count": passed,
        "blocked_claim_count": len(blocked),
        "failed_claim_count": failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert final hardened M1 acceptance.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="H00_BOOTSTRAP_HARD_GATES")
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    parser.add_argument("--allow-blocked", action="store_true")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    status, violations, blocked, extra = evaluate_final(manifest_path)
    result = write_gate_result(
        root=root,
        stage_id=args.stage,
        gate_name=GATE,
        status=status,
        inputs=[str(manifest_path)],
        violations=violations,
        blocked_reasons=blocked,
        extra=extra,
    )
    print_gate_summary(result)
    return exit_code(status, allow_blocked=args.allow_blocked)


if __name__ == "__main__":
    raise SystemExit(main())
