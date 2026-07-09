#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import exit_code, print_gate_summary, read_json, relpath, violation, write_gate_result
from manifest import ALLOWED_PASS_KINDS, REQUIRED_CLAIMS, claim_id

GATE = "assert_no_legacy_m1_pass"
H00_STAGE = "H00_BOOTSTRAP_HARD_GATES"
H01_STAGE = "H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET"
H02_STAGE = "H02_ACCEPTANCE_GATE_FAIL_CLOSED"
H03_STAGE = "H03_SETUP_TELEMETRY_REAL_PATH_HARDENING"
DEFAULT_HISTORICAL_REPORT = "runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json"
DISALLOWED_REQUIRED_PASS = {
    "LEGACY_EVIDENCE_ONLY",
    "FIXTURE_ONLY",
    "DRY_RUN_ONLY",
    "REAL_SMALL_SMOKE",
    "INVALID",
    "BLOCKED_WITH_REASON",
}


def validate_no_legacy_pass(
    manifest_path: Path,
    acceptance_path: Path,
    *,
    historical_acceptance_path: Path | None = None,
    root: Path | None = None,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    extra: dict[str, Any] = {}
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        return [violation("manifest_unreadable", "Evidence manifest is missing or invalid JSON.", path=str(manifest_path))], blocked, extra

    for claim in manifest.get("claims", []):
        if not isinstance(claim, dict):
            continue
        cid = str(claim.get("claim_id"))
        required = claim.get("required_for_milestone_pass") is True
        status = claim.get("status")
        kind = claim.get("evidence_kind")
        if required and status == "PASS" and kind in DISALLOWED_REQUIRED_PASS:
            violations.append(
                violation(
                    "legacy_or_nonpromotable_pass",
                    "Required exact-scale claim passed with non-promotable evidence kind.",
                    claim_id=cid,
                    details={"evidence_kind": kind},
                )
            )
        if kind == "LEGACY_EVIDENCE_ONLY" and claim.get("required_for_milestone_pass") is not False:
            blocked.append(f"{cid}: legacy evidence is recorded but cannot satisfy M1 PASS until reconstructed or rerun.")

    acceptance = read_json(acceptance_path)
    if not isinstance(acceptance, dict):
        violations.append(violation("acceptance_unreadable", "Current acceptance report is missing or invalid JSON.", path=str(acceptance_path)))
        return violations, blocked, extra

    current_violations, current_blocked = validate_current_acceptance(acceptance, acceptance_path)
    violations.extend(current_violations)
    blocked.extend(current_blocked)

    historical = read_json(historical_acceptance_path) if historical_acceptance_path else None
    if isinstance(historical, dict):
        historical_violations = _legacy_pass_violations(historical, historical_acceptance_path)
        if historical_violations:
            supersedes = {str(item) for item in acceptance.get("supersedes", []) if isinstance(item, str)}
            historical_path_text = historical_acceptance_path.as_posix() if historical_acceptance_path else ""
            historical_rel = relpath(root, historical_acceptance_path) if root and historical_acceptance_path else ""
            if historical_path_text in supersedes or historical_rel in supersedes or any(historical_path_text.endswith(item) for item in supersedes):
                extra["superseded_inputs"] = [
                    {
                        "path": historical_rel or historical_path_text,
                        "reason": "Historical PASS report is superseded by current blocked hardening acceptance reset.",
                        "violation_count": len(historical_violations),
                    }
                ]
            else:
                violations.extend(historical_violations)
    elif historical_acceptance_path:
        blocked.append(f"{historical_acceptance_path.as_posix()} is unavailable as historical suspect input.")
    return violations, blocked, extra


def validate_current_acceptance(acceptance: dict[str, Any], acceptance_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    required_ids = {claim_id(capability, scale) for capability, scale in REQUIRED_CLAIMS}
    for key in [
        "hardening_loop_status",
        "milestone1_status",
        "false_pass_prevented",
        "required_claim_count",
        "passed_claim_count",
        "blocked_claim_count",
        "failed_claim_count",
        "claims",
    ]:
        if key not in acceptance:
            violations.append(violation("acceptance_missing_c03_field", f"Current acceptance report is missing C03 field {key}.", path=str(acceptance_path)))
    if acceptance.get("milestone1_status") not in {"PASS", "FAIL", "BLOCKED_WITH_REASON"}:
        violations.append(
            violation(
                "acceptance_bad_status",
                "Current acceptance report has invalid milestone1_status.",
                path=str(acceptance_path),
                details={"actual": acceptance.get("milestone1_status")},
            )
        )
    claims = acceptance.get("claims")
    if not isinstance(claims, list):
        violations.append(violation("acceptance_claims_not_list", "Current acceptance claims must be a list.", path=str(acceptance_path)))
        return violations, blocked

    by_id = {str(claim.get("claim_id")): claim for claim in claims if isinstance(claim, dict)}
    missing = sorted(required_ids - set(by_id))
    if missing:
        violations.append(
            violation(
                "acceptance_required_claims_missing",
                "Current acceptance report omits required exact-scale claims.",
                path=str(acceptance_path),
                details={"missing": missing},
            )
        )

    counted = {"PASS": 0, "BLOCKED_WITH_REASON": 0, "FAIL": 0}
    for cid in sorted(required_ids & set(by_id)):
        claim = by_id[cid]
        status = str(claim.get("acceptance_status", claim.get("status", "")))
        kind = str(claim.get("evidence_kind", ""))
        counted[status] = counted.get(status, 0) + 1
        sources = claim.get("source_artifacts") if isinstance(claim.get("source_artifacts"), list) else []
        if status == "PASS":
            semantic = claim.get("semantic_checks") if isinstance(claim.get("semantic_checks"), dict) else {}
            if kind not in ALLOWED_PASS_KINDS or semantic.get("m1_format_fields_complete") is not True or semantic.get("hardening_stage_accepted") is not True:
                violations.append(
                    violation(
                        "acceptance_nonpromotable_pass",
                        "Current acceptance PASS uses non-promotable evidence or incomplete semantics.",
                        path=str(acceptance_path),
                        claim_id=cid,
                        details={"evidence_kind": kind},
                    )
                )
            if any(_is_fixture_source(str(source)) for source in sources):
                violations.append(violation("acceptance_fixture_pass", "Current acceptance PASS cites fixture evidence.", path=str(acceptance_path), claim_id=cid))
        elif status == "BLOCKED_WITH_REASON":
            reason = claim.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                violations.append(violation("acceptance_blocked_reason_missing", "Blocked current acceptance claim must include a reason.", path=str(acceptance_path), claim_id=cid))
            else:
                blocked.append(f"{cid}: {reason}")
        elif status != "FAIL":
            violations.append(
                violation(
                    "acceptance_claim_bad_status",
                    "Current acceptance claim has invalid status.",
                    path=str(acceptance_path),
                    claim_id=cid,
                    details={"actual": status},
                )
            )

    expected_counts = {
        "required_claim_count": len(required_ids),
        "passed_claim_count": counted.get("PASS", 0),
        "blocked_claim_count": counted.get("BLOCKED_WITH_REASON", 0),
        "failed_claim_count": counted.get("FAIL", 0),
    }
    for key, expected in expected_counts.items():
        if acceptance.get(key) != expected:
            violations.append(
                violation(
                    "acceptance_count_mismatch",
                    f"Current acceptance {key} does not match claim ledger.",
                    path=str(acceptance_path),
                    details={"expected": expected, "actual": acceptance.get(key)},
                )
            )

    milestone = acceptance.get("milestone1_status")
    if milestone == "PASS" and counted.get("PASS", 0) != len(required_ids):
        violations.append(violation("acceptance_false_pass", "Milestone PASS requires every required exact-scale claim to pass.", path=str(acceptance_path)))
    if milestone != "PASS" and acceptance.get("false_pass_prevented") is not True:
        violations.append(violation("false_pass_not_prevented", "Blocked or failed current acceptance must set false_pass_prevented true.", path=str(acceptance_path)))
    _validate_legacy_report_body(acceptance, acceptance_path, violations)
    return violations, blocked


def _legacy_pass_violations(report: dict[str, Any], report_path: Path | None) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    if report.get("milestone1_status") == "PASS":
        _validate_legacy_report_body(report, report_path, violations)
    return violations


def _validate_legacy_report_body(report: dict[str, Any], report_path: Path | None, violations: list[dict[str, Any]]) -> None:
    fixture_sources = [
        source
        for source in report.get("source_artifacts", [])
        if isinstance(source, dict) and _is_fixture_source(str(source.get("path", "")))
    ]
    if report.get("milestone1_status") == "PASS" and fixture_sources:
        violations.append(
            violation(
                "legacy_acceptance_fixture_pass",
                "Milestone acceptance report is PASS while listing fixture sources.",
                path=str(report_path) if report_path else None,
                details={"fixture_source_count": len(fixture_sources)},
            )
        )
    skipped_pass_rows = [
        row
        for row in report.get("heavy_real_rungs", [])
        if isinstance(row, dict)
        and row.get("status") == "PASS"
        and (row.get("metrics") == "SKIPPED_WITH_REASON" or row.get("report") == "SKIPPED_WITH_REASON")
    ]
    if report.get("milestone1_status") == "PASS" and skipped_pass_rows:
        violations.append(
            violation(
                "legacy_acceptance_skipped_fields_pass",
                "Milestone acceptance report is PASS while PASS rows contain skipped metric or report fields.",
                path=str(report_path) if report_path else None,
                details={"row_count": len(skipped_pass_rows)},
            )
        )


def _is_fixture_source(source: str) -> bool:
    parts = Path(source).parts
    return "tests" in parts and "fixtures" in parts


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject legacy-only or non-promotable M1 PASS evidence.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default=H00_STAGE)
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    parser.add_argument("--acceptance-report")
    parser.add_argument("--historical-acceptance-report")
    parser.add_argument("--allow-blocked", action="store_true")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path

    if args.acceptance_report:
        acceptance_default = args.acceptance_report
    elif args.stage == H01_STAGE:
        acceptance_default = f"runs/m1-hardening/{H01_STAGE}/artifacts/milestone1_acceptance_reset.json"
    elif args.stage == H02_STAGE:
        acceptance_default = f"runs/m1-hardening/{H02_STAGE}/artifacts/milestone1_acceptance_report.json"
    elif args.stage == H03_STAGE:
        acceptance_default = f"runs/m1-hardening/{H02_STAGE}/artifacts/milestone1_acceptance_report.json"
    else:
        acceptance_default = DEFAULT_HISTORICAL_REPORT
    historical_default = args.historical_acceptance_report
    if historical_default is None and args.stage in {H01_STAGE, H02_STAGE, H03_STAGE}:
        historical_default = DEFAULT_HISTORICAL_REPORT

    acceptance_path = Path(acceptance_default)
    if not acceptance_path.is_absolute():
        acceptance_path = root / acceptance_path
    historical_path = Path(historical_default) if historical_default else None
    if historical_path is not None and not historical_path.is_absolute():
        historical_path = root / historical_path

    violations, blocked, extra = validate_no_legacy_pass(manifest_path, acceptance_path, historical_acceptance_path=historical_path, root=root)
    if args.stage == H00_STAGE and violations:
        blocked = [
            *blocked,
            "H00 bootstraps the legacy-PASS detector; the existing suspect M1-S09 PASS report is deferred to H01 reset and cannot satisfy hardening manifest claims.",
        ]
        extra["deferred_violations"] = violations
        violations = []
    status = "FAIL" if violations else "BLOCKED_WITH_REASON" if blocked else "PASS"
    if args.stage in {H00_STAGE, H01_STAGE, H02_STAGE, H03_STAGE} and not violations:
        status = "PASS"
    inputs = [str(manifest_path), str(acceptance_path)]
    if historical_path is not None:
        inputs.append(str(historical_path))
    result = write_gate_result(
        root=root,
        stage_id=args.stage,
        gate_name=GATE,
        status=status,
        inputs=inputs,
        violations=violations,
        blocked_reasons=blocked,
        extra=extra,
    )
    print_gate_summary(result)
    return exit_code(status, allow_blocked=args.allow_blocked)


if __name__ == "__main__":
    raise SystemExit(main())
