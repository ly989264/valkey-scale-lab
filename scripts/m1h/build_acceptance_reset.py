#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import exit_code, print_gate_summary, read_json, relpath, violation, write_gate_result, write_json
from manifest import ALLOWED_PASS_KINDS, CAPABILITY_REQUIRED_CHECKS, REQUIRED_CLAIMS, claim_id

GATE = "build_acceptance_reset"
DEFAULT_HISTORICAL_REPORT = "runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json"


def build_acceptance_reset(
    root: Path,
    manifest_path: Path,
    *,
    stage_id: str,
    historical_acceptance_report: str | None = DEFAULT_HISTORICAL_REPORT,
    artifact_type: str = "milestone1_acceptance_reset",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        report = _empty_report(
            stage_id=stage_id,
            manifest_path=relpath(root, manifest_path),
            artifact_type=artifact_type,
            reason="Evidence manifest is missing or invalid JSON.",
            historical_acceptance_report=historical_acceptance_report,
        )
        return report, [violation("manifest_unreadable", "Evidence manifest is missing or invalid JSON.", path=relpath(root, manifest_path))]

    required_ids = {claim_id(capability, scale) for capability, scale in REQUIRED_CLAIMS}
    manifest_claims = [claim for claim in manifest.get("claims", []) if isinstance(claim, dict)]
    by_id = {str(claim.get("claim_id")): claim for claim in manifest_claims}
    reset_claims: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    for cid in sorted(required_ids):
        source = by_id.get(cid)
        if source is None:
            reset_claims.append(_missing_claim(cid))
            violations.append(violation("required_claim_missing", "Required exact-scale claim is missing from evidence manifest.", claim_id=cid))
            continue
        reset_claim, claim_violations = _reset_claim(root, source)
        reset_claims.append(reset_claim)
        violations.extend(claim_violations)

    unexpected_required_pass = [
        str(claim.get("claim_id"))
        for claim in manifest_claims
        if claim.get("required_for_milestone_pass") is True
        and str(claim.get("claim_id")) not in required_ids
        and claim.get("status") == "PASS"
    ]
    for cid in unexpected_required_pass:
        violations.append(violation("unknown_required_pass", "Unknown required claim cannot contribute to milestone PASS.", claim_id=cid))

    passed = [claim for claim in reset_claims if claim["acceptance_status"] == "PASS"]
    failed = [claim for claim in reset_claims if claim["acceptance_status"] == "FAIL"]
    blocked = [claim for claim in reset_claims if claim["acceptance_status"] == "BLOCKED_WITH_REASON"]
    if failed:
        milestone_status = "FAIL"
    elif len(passed) == len(required_ids) and not blocked:
        milestone_status = "PASS"
    else:
        milestone_status = "BLOCKED_WITH_REASON"

    report: dict[str, Any] = {
        "schema_version": "v1",
        "artifact_type": artifact_type,
        "stage_id": stage_id,
        "hardening_loop_status": "FAIL" if violations else "PASS",
        "milestone1_status": milestone_status,
        "false_pass_prevented": milestone_status != "PASS",
        "required_claim_count": len(required_ids),
        "passed_claim_count": len(passed),
        "blocked_claim_count": len(blocked),
        "failed_claim_count": len(failed),
        "claims": reset_claims,
        "missing_claims": [claim["claim_id"] for claim in blocked],
        "blocked_reasons": [claim["reason"] for claim in blocked if claim.get("reason")],
        "source_manifest": relpath(root, manifest_path),
    }
    if historical_acceptance_report:
        report["supersedes"] = [historical_acceptance_report]
        report["superseded_reason"] = (
            "Historical M1-S09 acceptance is suspect for hardening because fixture, legacy, skipped, "
            "and shallow-count evidence cannot satisfy required exact-scale M1-format claims."
        )
    return report, violations


def validate_acceptance_report(
    root: Path,
    report: dict[str, Any],
    *,
    report_path: Path | None = None,
    expected_stage_id: str | None = None,
    expected_artifact_type: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate the C03 acceptance ledger and fail closed on unsafe PASS claims."""
    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    path_text = relpath(root, report_path) if report_path else None
    required_ids = {claim_id(capability, scale) for capability, scale in REQUIRED_CLAIMS}

    expected_fields = {
        "schema_version": "v1",
        "hardening_loop_status": None,
        "milestone1_status": None,
        "false_pass_prevented": None,
        "required_claim_count": None,
        "passed_claim_count": None,
        "blocked_claim_count": None,
        "failed_claim_count": None,
        "claims": None,
    }
    if expected_artifact_type is not None:
        expected_fields["artifact_type"] = expected_artifact_type
    if expected_stage_id is not None:
        expected_fields["stage_id"] = expected_stage_id
    for key, expected in expected_fields.items():
        if key not in report:
            violations.append(violation("acceptance_missing_c03_field", f"Acceptance report is missing C03 field {key}.", path=path_text))
        elif expected is not None and report.get(key) != expected:
            violations.append(
                violation(
                    "acceptance_bad_field",
                    f"Acceptance report field {key} must be {expected!r}.",
                    path=path_text,
                    details={"actual": report.get(key)},
                )
            )

    if report.get("hardening_loop_status") not in {"PASS", "FAIL", "BLOCKED_WITH_REASON"}:
        violations.append(violation("acceptance_bad_status", "Acceptance report has invalid hardening_loop_status.", path=path_text))
    if report.get("milestone1_status") not in {"PASS", "FAIL", "BLOCKED_WITH_REASON"}:
        violations.append(violation("acceptance_bad_status", "Acceptance report has invalid milestone1_status.", path=path_text))

    claims = report.get("claims")
    if not isinstance(claims, list):
        violations.append(violation("acceptance_claims_not_list", "Acceptance report claims must be a list.", path=path_text))
        return violations, blocked

    by_id: dict[str, dict[str, Any]] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            violations.append(violation("acceptance_claim_not_object", "Acceptance claim must be an object.", path=path_text))
            continue
        cid = str(claim.get("claim_id", ""))
        if cid in by_id:
            violations.append(violation("acceptance_duplicate_claim", "Acceptance report repeats a required claim.", path=path_text, claim_id=cid))
        by_id[cid] = claim

    missing = sorted(required_ids - set(by_id))
    extra_required = sorted(
        cid
        for cid, claim in by_id.items()
        if claim.get("required_for_milestone_pass") is True and cid not in required_ids
    )
    if missing:
        violations.append(
            violation(
                "acceptance_required_claims_missing",
                "Acceptance report omits required exact-scale claims.",
                path=path_text,
                details={"missing": missing},
            )
        )
    if extra_required:
        violations.append(
            violation(
                "acceptance_unknown_required_claims",
                "Acceptance report contains unknown required milestone claims.",
                path=path_text,
                details={"unknown": extra_required},
            )
        )

    counted = {"PASS": 0, "BLOCKED_WITH_REASON": 0, "FAIL": 0}
    for cid in sorted(required_ids & set(by_id)):
        claim = by_id[cid]
        status = str(claim.get("acceptance_status", claim.get("status", "")))
        if status not in counted:
            violations.append(
                violation(
                    "acceptance_claim_bad_status",
                    "Acceptance claim has invalid status.",
                    path=path_text,
                    claim_id=cid,
                    details={"actual": status},
                )
            )
            continue
        counted[status] += 1
        if claim.get("required_for_milestone_pass") is not True:
            violations.append(violation("acceptance_required_flag_bad", "Required claim must be marked required_for_milestone_pass.", path=path_text, claim_id=cid))
        if status == "PASS":
            violations.extend(_pass_claim_violations(root, claim, path_text))
        elif status == "BLOCKED_WITH_REASON":
            reason = claim.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                violations.append(violation("acceptance_blocked_reason_missing", "Blocked acceptance claim must include a reason.", path=path_text, claim_id=cid))
            else:
                blocked.append(f"{cid}: {reason}")

    expected_counts = {
        "required_claim_count": len(required_ids),
        "passed_claim_count": counted["PASS"],
        "blocked_claim_count": counted["BLOCKED_WITH_REASON"],
        "failed_claim_count": counted["FAIL"],
    }
    for key, expected in expected_counts.items():
        if report.get(key) != expected:
            violations.append(
                violation(
                    "acceptance_count_mismatch",
                    f"Acceptance report {key} does not match claim ledger.",
                    path=path_text,
                    details={"expected": expected, "actual": report.get(key)},
                )
            )

    milestone = report.get("milestone1_status")
    if milestone == "PASS" and counted["PASS"] != len(required_ids):
        violations.append(violation("acceptance_false_pass", "Milestone PASS requires every required exact-scale claim to pass.", path=path_text))
    if milestone == "BLOCKED_WITH_REASON" and counted["BLOCKED_WITH_REASON"] == 0:
        violations.append(violation("acceptance_bad_blocked_status", "Blocked milestone status requires blocked claim reasons.", path=path_text))
    if milestone == "FAIL" and counted["FAIL"] == 0:
        violations.append(violation("acceptance_bad_fail_status", "Failed milestone status requires failed claims.", path=path_text))
    if milestone != "PASS" and report.get("false_pass_prevented") is not True:
        violations.append(violation("false_pass_not_prevented", "Blocked or failed milestone acceptance must set false_pass_prevented true.", path=path_text))
    if milestone == "PASS" and report.get("false_pass_prevented") is not False:
        violations.append(violation("false_pass_flag_bad", "Milestone PASS must set false_pass_prevented false.", path=path_text))

    hardening = report.get("hardening_loop_status")
    if violations and hardening == "PASS":
        violations.append(violation("hardening_status_false_pass", "Hardening status cannot be PASS when acceptance violations are present.", path=path_text))
    if counted["FAIL"] and hardening == "PASS":
        violations.append(violation("hardening_status_false_pass", "Hardening status cannot be PASS when required claims failed.", path=path_text))
    return violations, blocked


def _reset_claim(root: Path, source: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cid = str(source.get("claim_id", ""))
    kind = str(source.get("evidence_kind", ""))
    source_status = str(source.get("status", ""))
    semantic = source.get("semantic_checks") if isinstance(source.get("semantic_checks"), dict) else {}
    sources = source.get("source_artifacts") if isinstance(source.get("source_artifacts"), list) else []
    reason = source.get("reason") if isinstance(source.get("reason"), str) and source.get("reason").strip() else ""
    violations: list[dict[str, Any]] = []

    failed_pass_checks = _failed_pass_checks(root, cid, kind, source_status, semantic, sources)
    pass_allowed = source_status == "PASS" and not failed_pass_checks
    if pass_allowed:
        acceptance_status = "PASS"
        acceptance_reason = "Required exact-scale M1-format claim passed with promotable evidence."
    elif source_status == "PASS":
        acceptance_status = "FAIL"
        acceptance_reason = (
            f"{cid} attempted PASS with non-promotable or incomplete evidence "
            f"({kind or 'MISSING'}); false milestone PASS prevented."
        )
        violations.append(
            violation(
                "nonpromotable_required_pass",
                "Required exact-scale claim cannot pass with this evidence kind or incomplete semantics.",
                claim_id=cid,
                details={"evidence_kind": kind, "source_status": source_status},
            )
        )
        for check in failed_pass_checks:
            violations.append(
                violation(
                    "required_pass_failed_semantics",
                    "Required exact-scale claim attempted PASS without all mandatory semantics.",
                    claim_id=cid,
                    details=check,
                )
            )
    else:
        acceptance_status = "BLOCKED_WITH_REASON"
        acceptance_reason = reason or f"{cid} is missing required exact-scale M1-format evidence."
        if not reason:
            violations.append(violation("blocked_reason_missing", "Blocked required claim must include a reason.", claim_id=cid))

    reset_claim = {
        "claim_id": cid,
        "capability": source.get("capability", "MISSING"),
        "scale": source.get("scale", "MISSING"),
        "required_for_milestone_pass": source.get("required_for_milestone_pass") is True,
        "evidence_kind": kind or "MISSING",
        "source_status": source_status or "MISSING",
        "acceptance_status": acceptance_status,
        "reason": acceptance_reason,
        "semantic_checks": semantic,
        "source_artifacts": sources,
    }
    return reset_claim, violations


def _missing_claim(cid: str) -> dict[str, Any]:
    return {
        "claim_id": cid,
        "capability": cid.split(".")[0] if "." in cid else "MISSING",
        "scale": "MISSING",
        "required_for_milestone_pass": True,
        "evidence_kind": "MISSING",
        "source_status": "MISSING",
        "acceptance_status": "BLOCKED_WITH_REASON",
        "reason": f"{cid} is absent from the evidence manifest.",
        "semantic_checks": {},
        "source_artifacts": [],
    }


def _empty_report(
    *,
    stage_id: str,
    manifest_path: str,
    artifact_type: str,
    reason: str,
    historical_acceptance_report: str | None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "v1",
        "artifact_type": artifact_type,
        "stage_id": stage_id,
        "hardening_loop_status": "FAIL",
        "milestone1_status": "BLOCKED_WITH_REASON",
        "false_pass_prevented": True,
        "required_claim_count": len(REQUIRED_CLAIMS),
        "passed_claim_count": 0,
        "blocked_claim_count": len(REQUIRED_CLAIMS),
        "failed_claim_count": 0,
        "claims": [_missing_claim(claim_id(capability, scale)) for capability, scale in REQUIRED_CLAIMS],
        "missing_claims": [claim_id(capability, scale) for capability, scale in REQUIRED_CLAIMS],
        "blocked_reasons": [reason],
        "source_manifest": manifest_path,
    }
    if historical_acceptance_report:
        report["supersedes"] = [historical_acceptance_report]
        report["superseded_reason"] = "Historical acceptance cannot substitute for the missing hardening manifest."
    return report


def _is_fixture_source(source: str) -> bool:
    return "tests" in Path(source).parts and "fixtures" in Path(source).parts


def _pass_claim_violations(root: Path, claim: dict[str, Any], path_text: str | None) -> list[dict[str, Any]]:
    cid = str(claim.get("claim_id", ""))
    kind = str(claim.get("evidence_kind", ""))
    source_status = str(claim.get("source_status", claim.get("status", "PASS")))
    semantic = claim.get("semantic_checks") if isinstance(claim.get("semantic_checks"), dict) else {}
    sources = claim.get("source_artifacts") if isinstance(claim.get("source_artifacts"), list) else []
    violations: list[dict[str, Any]] = []
    for check in _failed_pass_checks(root, cid, kind, source_status, semantic, sources):
        violations.append(
            violation(
                "acceptance_nonpromotable_pass",
                "Acceptance PASS uses non-promotable evidence or incomplete semantics.",
                path=path_text,
                claim_id=cid,
                details=check,
            )
        )
    return violations


def _failed_pass_checks(
    root: Path,
    cid: str,
    kind: str,
    source_status: str,
    semantic: dict[str, Any],
    sources: list[Any],
) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    if source_status != "PASS":
        failed.append({"check": "source_status", "expected": "PASS", "actual": source_status or "MISSING"})
    if kind not in ALLOWED_PASS_KINDS:
        failed.append({"check": "evidence_kind", "expected": sorted(ALLOWED_PASS_KINDS), "actual": kind or "MISSING"})
    for check in ["m1_format_fields_complete", "hardening_stage_accepted", "exact_scale_observed"]:
        if semantic.get(check) is not True:
            failed.append({"check": check, "expected": True, "actual": semantic.get(check, "MISSING")})
    capability = cid.split(".real_exact.", 1)[0] if ".real_exact." in cid else str(cid).split(".", 1)[0]
    for check in CAPABILITY_REQUIRED_CHECKS.get(capability, []):
        if semantic.get(check) is not True:
            failed.append({"check": check, "expected": True, "actual": semantic.get(check, "MISSING")})
    fixture_sources = [str(source) for source in sources if _is_fixture_source(str(source))]
    if fixture_sources:
        failed.append({"check": "no_fixture_path", "expected": True, "actual": False, "source_artifacts": fixture_sources})
    skipped = [
        name
        for name, value in semantic.items()
        if value in {"SKIPPED_WITH_REASON", "MISSING", "SKIPPED", "BLOCKED_WITH_REASON"}
    ]
    if skipped:
        failed.append({"check": "no_skipped_semantics", "expected": True, "actual": skipped})
    return failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a C03-shaped blocked M1 hardening acceptance reset.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET")
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    parser.add_argument(
        "--out",
        default="runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/artifacts/milestone1_acceptance_reset.json",
    )
    parser.add_argument("--historical-acceptance-report", default=DEFAULT_HISTORICAL_REPORT)
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out

    report, violations = build_acceptance_reset(
        root,
        manifest_path,
        stage_id=args.stage,
        historical_acceptance_report=args.historical_acceptance_report,
    )
    write_json(out, report)
    status = "FAIL" if violations else "PASS"
    result = write_gate_result(
        root=root,
        stage_id=args.stage,
        gate_name=GATE,
        status=status,
        inputs=[relpath(root, manifest_path), relpath(root, out)],
        violations=violations,
        blocked_reasons=report.get("blocked_reasons", []),
        extra={
            "milestone1_status": report["milestone1_status"],
            "required_claim_count": report["required_claim_count"],
            "passed_claim_count": report["passed_claim_count"],
            "blocked_claim_count": report["blocked_claim_count"],
            "failed_claim_count": report["failed_claim_count"],
        },
    )
    print_gate_summary(result)
    return exit_code(status)


if __name__ == "__main__":
    raise SystemExit(main())
