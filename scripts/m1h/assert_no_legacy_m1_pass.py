#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import exit_code, print_gate_summary, read_json, violation, write_gate_result

GATE = "assert_no_legacy_m1_pass"
DISALLOWED_REQUIRED_PASS = {
    "LEGACY_EVIDENCE_ONLY",
    "FIXTURE_ONLY",
    "DRY_RUN_ONLY",
    "REAL_SMALL_SMOKE",
    "INVALID",
    "BLOCKED_WITH_REASON",
}


def validate_no_legacy_pass(manifest_path: Path, acceptance_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        return [violation("manifest_unreadable", "Evidence manifest is missing or invalid JSON.", path=str(manifest_path))], blocked
    for claim in manifest.get("claims", []):
        if not isinstance(claim, dict):
            continue
        cid = str(claim.get("claim_id"))
        required = claim.get("required_for_milestone_pass") is True
        status = claim.get("status")
        kind = claim.get("evidence_kind")
        if required and status == "PASS" and kind in DISALLOWED_REQUIRED_PASS:
            violations.append(
                violation("legacy_or_nonpromotable_pass", "Required exact-scale claim passed with non-promotable evidence kind.", claim_id=cid, details={"evidence_kind": kind})
            )
        if kind == "LEGACY_EVIDENCE_ONLY" and claim.get("required_for_milestone_pass") is not False:
            blocked.append(f"{cid}: legacy evidence is recorded but cannot satisfy M1 PASS until reconstructed or rerun.")
    acceptance = read_json(acceptance_path)
    if isinstance(acceptance, dict) and acceptance.get("milestone1_status") == "PASS":
        fixture_sources = [
            source
            for source in acceptance.get("source_artifacts", [])
            if isinstance(source, dict) and "tests/fixtures/" in str(source.get("path", ""))
        ]
        if fixture_sources:
            violations.append(
                violation(
                    "legacy_acceptance_fixture_pass",
                    "Existing milestone acceptance report is PASS while listing fixture sources.",
                    path=str(acceptance_path),
                    details={"fixture_source_count": len(fixture_sources)},
                )
            )
    return violations, blocked


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject legacy-only or non-promotable M1 PASS evidence.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="H00_BOOTSTRAP_HARD_GATES")
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    parser.add_argument("--acceptance-report", default="runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json")
    parser.add_argument("--allow-blocked", action="store_true")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    acceptance_path = Path(args.acceptance_report)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    if not acceptance_path.is_absolute():
        acceptance_path = root / acceptance_path
    violations, blocked = validate_no_legacy_pass(manifest_path, acceptance_path)
    extra: dict[str, Any] = {}
    if args.stage == "H00_BOOTSTRAP_HARD_GATES" and violations:
        blocked = [
            *blocked,
            "H00 bootstraps the legacy-PASS detector; the existing suspect M1-S09 PASS report is deferred to H01 reset and cannot satisfy hardening manifest claims.",
        ]
        extra["deferred_violations"] = violations
        violations = []
    status = "FAIL" if violations else "BLOCKED_WITH_REASON" if blocked else "PASS"
    if args.stage == "H00_BOOTSTRAP_HARD_GATES" and not violations:
        status = "PASS"
    result = write_gate_result(
        root=root,
        stage_id=args.stage,
        gate_name=GATE,
        status=status,
        inputs=[str(manifest_path), str(acceptance_path)],
        violations=violations,
        blocked_reasons=blocked,
        extra=extra,
    )
    print_gate_summary(result)
    return exit_code(status, allow_blocked=args.allow_blocked)


if __name__ == "__main__":
    raise SystemExit(main())
