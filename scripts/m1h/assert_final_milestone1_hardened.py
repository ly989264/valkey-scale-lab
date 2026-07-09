#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_acceptance_reset import build_acceptance_reset, validate_acceptance_report
from common import exit_code, print_gate_summary, read_json, relpath, violation, write_gate_result, write_json

GATE = "assert_final_milestone1_hardened"
DEFAULT_HISTORICAL_REPORT = "runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json"


def evaluate_final(
    root: Path,
    manifest_path: Path,
    out_path: Path,
    *,
    stage_id: str,
    historical_acceptance_report: str | None = DEFAULT_HISTORICAL_REPORT,
) -> tuple[str, list[dict[str, Any]], list[str], dict[str, Any]]:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        report, build_violations = build_acceptance_reset(
            root,
            manifest_path,
            stage_id=stage_id,
            historical_acceptance_report=historical_acceptance_report,
            artifact_type="milestone1_acceptance_report",
        )
        write_json(out_path, report)
        return "FAIL", build_violations or [violation("manifest_unreadable", "Evidence manifest is missing or invalid JSON.", path=relpath(root, manifest_path))], [], _extra(out_path, report)

    report, build_violations = build_acceptance_reset(
        root,
        manifest_path,
        stage_id=stage_id,
        historical_acceptance_report=historical_acceptance_report,
        artifact_type="milestone1_acceptance_report",
    )
    write_json(out_path, report)
    validation_violations, blocked = validate_acceptance_report(
        root,
        report,
        report_path=out_path,
        expected_stage_id=stage_id,
        expected_artifact_type="milestone1_acceptance_report",
    )
    violations = [*build_violations, *validation_violations]
    milestone_status = report.get("milestone1_status")
    hardening_status = report.get("hardening_loop_status")
    if hardening_status == "PASS" and milestone_status in {"PASS", "BLOCKED_WITH_REASON"} and not violations:
        gate_status = "PASS"
    else:
        gate_status = "FAIL"
    return gate_status, violations, blocked, _extra(out_path, report)


def _extra(out_path: Path, report: dict[str, Any]) -> dict[str, Any]:
    return {
        "acceptance_report": str(out_path),
        "hardening_loop_status": report.get("hardening_loop_status", "MISSING"),
        "milestone1_status": report.get("milestone1_status", "MISSING"),
        "false_pass_prevented": report.get("false_pass_prevented", "MISSING"),
        "required_claim_count": report.get("required_claim_count", "MISSING"),
        "passed_claim_count": report.get("passed_claim_count", "MISSING"),
        "blocked_claim_count": report.get("blocked_claim_count", "MISSING"),
        "failed_claim_count": report.get("failed_claim_count", "MISSING"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert final hardened M1 acceptance.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="H00_BOOTSTRAP_HARD_GATES")
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    parser.add_argument("--out")
    parser.add_argument("--historical-acceptance-report", default=DEFAULT_HISTORICAL_REPORT)
    parser.add_argument("--allow-blocked", action="store_true")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    out_path = Path(args.out) if args.out else root / "runs" / "m1-hardening" / args.stage / "artifacts" / "milestone1_acceptance_report.json"
    if not out_path.is_absolute():
        out_path = root / out_path
    status, violations, blocked, extra = evaluate_final(
        root,
        manifest_path,
        out_path,
        stage_id=args.stage,
        historical_acceptance_report=args.historical_acceptance_report,
    )
    result = write_gate_result(
        root=root,
        stage_id=args.stage,
        gate_name=GATE,
        status=status,
        inputs=[relpath(root, manifest_path), relpath(root, out_path)],
        violations=violations,
        blocked_reasons=blocked,
        extra=extra,
    )
    print_gate_summary(result)
    return exit_code(status, allow_blocked=args.allow_blocked)


if __name__ == "__main__":
    raise SystemExit(main())
