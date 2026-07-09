#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_acceptance_reset import build_acceptance_reset, validate_acceptance_report
from common import exit_code, print_gate_summary, read_json, relpath, violation, write_gate_result, write_json
from manifest import REQUIRED_CLAIMS, claim_id

GATE = "assert_final_milestone1_hardened"
DEFAULT_HISTORICAL_REPORT = "runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json"
H10_STAGE_ID = "H10_FINAL_HARDENING_ACCEPTANCE"
H10_ARTIFACT_TYPE = "milestone1_hardened_acceptance"
LEGACY_ACCEPTANCE_ARTIFACT_TYPE = "milestone1_acceptance_report"
FINAL_LIST_FIELDS = [
    "required_claims",
    "passed_claims",
    "blocked_claims",
    "failed_claims",
    "fixture_only_claims",
    "legacy_only_claims",
]
RENDERED_REPORT_BASENAMES = {
    "report_index.json",
    "final_report_index.json",
    "report.md",
    "index.html",
}


def evaluate_final(
    root: Path,
    manifest_path: Path,
    out_path: Path,
    *,
    stage_id: str,
    historical_acceptance_report: str | None = DEFAULT_HISTORICAL_REPORT,
) -> tuple[str, list[dict[str, Any]], list[str], dict[str, Any]]:
    manifest = read_json(manifest_path)
    artifact_type = artifact_type_for_stage(stage_id)
    if not isinstance(manifest, dict):
        report, build_violations = build_acceptance_reset(
            root,
            manifest_path,
            stage_id=stage_id,
            historical_acceptance_report=historical_acceptance_report,
            artifact_type=artifact_type,
        )
        if stage_id == H10_STAGE_ID:
            compact_nonpass_claim_details(report)
            enrich_final_handoff_lists(report)
        write_json(out_path, report)
        return "FAIL", build_violations or [violation("manifest_unreadable", "Evidence manifest is missing or invalid JSON.", path=relpath(root, manifest_path))], [], _extra(out_path, report)

    report, build_violations = build_acceptance_reset(
        root,
        manifest_path,
        stage_id=stage_id,
        historical_acceptance_report=historical_acceptance_report,
        artifact_type=artifact_type,
    )
    if stage_id == H10_STAGE_ID:
        compact_nonpass_claim_details(report)
        enrich_final_handoff_lists(report)
    write_json(out_path, report)
    validation_violations, blocked = validate_acceptance_report(
        root,
        report,
        report_path=out_path,
        expected_stage_id=stage_id,
        expected_artifact_type=artifact_type,
    )
    h10_violations = validate_hardened_acceptance_contract(root, report, report_path=out_path) if stage_id == H10_STAGE_ID else []
    violations = [*build_violations, *validation_violations, *h10_violations]
    milestone_status = report.get("milestone1_status")
    hardening_status = report.get("hardening_loop_status")
    if hardening_status == "PASS" and milestone_status in {"PASS", "BLOCKED_WITH_REASON"} and not violations:
        gate_status = "PASS"
    else:
        gate_status = "FAIL"
    return gate_status, violations, blocked, _extra(out_path, report)


def artifact_type_for_stage(stage_id: str) -> str:
    return H10_ARTIFACT_TYPE if stage_id == H10_STAGE_ID else LEGACY_ACCEPTANCE_ARTIFACT_TYPE


def default_acceptance_out_path(root: Path, stage_id: str) -> Path:
    filename = "milestone1_hardened_acceptance.json" if stage_id == H10_STAGE_ID else "milestone1_acceptance_report.json"
    return root / "runs" / "m1-hardening" / stage_id / "artifacts" / filename


def enrich_final_handoff_lists(report: dict[str, Any]) -> dict[str, Any]:
    claims = [claim for claim in report.get("claims", []) if isinstance(claim, dict)]
    required_ids = sorted(claim_id(capability, scale) for capability, scale in REQUIRED_CLAIMS)
    passed_claims = sorted(str(claim.get("claim_id")) for claim in claims if claim.get("acceptance_status") == "PASS")
    blocked_claims = [_claim_summary(claim) for claim in _claims_with_status(claims, "BLOCKED_WITH_REASON")]
    failed_claims = [_claim_summary(claim) for claim in _claims_with_status(claims, "FAIL")]
    fixture_claims = [_claim_source_summary(claim) for claim in claims if _claim_uses_fixture_only_evidence(claim)]
    legacy_claims = [_claim_source_summary(claim) for claim in claims if claim.get("evidence_kind") == "LEGACY_EVIDENCE_ONLY"]
    report.update(
        {
            "required_claims": required_ids,
            "passed_claims": passed_claims,
            "blocked_claims": blocked_claims,
            "failed_claims": failed_claims,
            "fixture_only_claims": fixture_claims,
            "legacy_only_claims": legacy_claims,
        }
    )
    return report


def compact_nonpass_claim_details(report: dict[str, Any]) -> dict[str, Any]:
    claims = [claim for claim in report.get("claims", []) if isinstance(claim, dict)]
    for claim in claims:
        if claim.get("acceptance_status") == "PASS":
            continue
        if isinstance(claim.get("reason"), str):
            claim["reason"] = _compact_reason(str(claim["reason"]))
        semantic = claim.get("semantic_checks")
        if isinstance(semantic, dict):
            claim["semantic_checks"] = _compact_semantic_checks(semantic)
    blocked = [claim for claim in claims if claim.get("acceptance_status") == "BLOCKED_WITH_REASON"]
    report["blocked_reasons"] = [
        str(claim.get("reason"))
        for claim in blocked
        if isinstance(claim.get("reason"), str) and str(claim.get("reason")).strip()
    ]
    return report


def _compact_reason(reason: str, *, limit: int = 600) -> str:
    normalized = " ".join(reason.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}... [truncated; see source evidence manifest for full diagnostics]"


def _compact_semantic_checks(semantic: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in semantic.items():
        if isinstance(value, (bool, int, float, str)) or value is None:
            compact[key] = value
    for key in ["m1_format_fields_complete", "hardening_stage_accepted", "exact_scale_observed"]:
        compact.setdefault(key, semantic.get(key, "MISSING"))
    return compact


def validate_hardened_acceptance_contract(
    root: Path,
    report: dict[str, Any],
    *,
    report_path: Path | None = None,
) -> list[dict[str, Any]]:
    path_text = relpath(root, report_path) if report_path else None
    violations: list[dict[str, Any]] = []
    claims = [claim for claim in report.get("claims", []) if isinstance(claim, dict)]
    expected = _expected_final_lists(claims)

    for field in FINAL_LIST_FIELDS:
        if field not in report:
            violations.append(violation("h10_final_field_missing", f"H10 hardened acceptance is missing {field}.", path=path_text))
        elif not isinstance(report.get(field), list):
            violations.append(violation("h10_final_field_not_list", f"H10 hardened acceptance field {field} must be a list.", path=path_text))
        elif report.get(field) != expected[field]:
            violations.append(
                violation(
                    "h10_final_list_mismatch",
                    f"H10 hardened acceptance field {field} does not match the acceptance claim ledger.",
                    path=path_text,
                    details={"expected": expected[field], "actual": report.get(field)},
                )
            )

    list_count_checks = {
        "required_claim_count": len(expected["required_claims"]),
        "passed_claim_count": len(expected["passed_claims"]),
        "blocked_claim_count": len(expected["blocked_claims"]),
        "failed_claim_count": len(expected["failed_claims"]),
    }
    for key, expected_count in list_count_checks.items():
        if report.get(key) != expected_count:
            violations.append(
                violation(
                    "h10_final_count_mismatch",
                    f"H10 hardened acceptance {key} does not match final claim lists.",
                    path=path_text,
                    details={"expected": expected_count, "actual": report.get(key)},
                )
            )

    if report.get("hardening_loop_status") != "PASS":
        violations.append(
            violation(
                "h10_hardening_not_pass",
                "H10 hardening loop status must be PASS for final hardened acceptance.",
                path=path_text,
                details={"actual": report.get("hardening_loop_status")},
            )
        )

    milestone = report.get("milestone1_status")
    blocked_count = len(expected["blocked_claims"])
    failed_count = len(expected["failed_claims"])
    passed_count = len(expected["passed_claims"])
    required_count = len(expected["required_claims"])
    if milestone == "PASS" and (blocked_count or failed_count or passed_count != required_count):
        violations.append(
            violation(
                "h10_false_milestone_pass",
                "H10 milestone PASS requires every required exact-scale claim to pass with no blocked or failed claims.",
                path=path_text,
            )
        )
    if blocked_count and milestone != "BLOCKED_WITH_REASON":
        violations.append(
            violation(
                "h10_blocked_status_required",
                "H10 milestone status must be BLOCKED_WITH_REASON when any required exact-scale claim is blocked.",
                path=path_text,
                details={"actual": milestone, "blocked_claim_count": blocked_count},
            )
        )
    if failed_count and milestone != "FAIL":
        violations.append(
            violation(
                "h10_failed_status_required",
                "H10 milestone status must be FAIL when any required exact-scale claim fails acceptance.",
                path=path_text,
                details={"actual": milestone, "failed_claim_count": failed_count},
            )
        )
    if milestone != "PASS" and report.get("false_pass_prevented") is not True:
        violations.append(violation("h10_false_pass_flag_missing", "H10 blocked or failed milestone must set false_pass_prevented true.", path=path_text))
    if milestone == "PASS" and report.get("false_pass_prevented") is not False:
        violations.append(violation("h10_false_pass_flag_bad", "H10 milestone PASS must not report that a false pass was prevented.", path=path_text))

    for claim in claims:
        if claim.get("acceptance_status") == "PASS" and claim.get("capability") == "report":
            sources = [str(source) for source in claim.get("source_artifacts", []) if isinstance(source, str)]
            non_rendered_sources = [source for source in sources if Path(source).name not in RENDERED_REPORT_BASENAMES]
            if not non_rendered_sources:
                violations.append(
                    violation(
                        "h10_report_rendered_only_pass",
                        "Report PASS must not be backed only by rendered report/index artifacts.",
                        path=path_text,
                        claim_id=str(claim.get("claim_id")),
                    )
                )
    return violations


def _expected_final_lists(claims: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "required_claims": sorted(claim_id(capability, scale) for capability, scale in REQUIRED_CLAIMS),
        "passed_claims": sorted(str(claim.get("claim_id")) for claim in claims if claim.get("acceptance_status") == "PASS"),
        "blocked_claims": [_claim_summary(claim) for claim in _claims_with_status(claims, "BLOCKED_WITH_REASON")],
        "failed_claims": [_claim_summary(claim) for claim in _claims_with_status(claims, "FAIL")],
        "fixture_only_claims": [_claim_source_summary(claim) for claim in claims if _claim_uses_fixture_only_evidence(claim)],
        "legacy_only_claims": [_claim_source_summary(claim) for claim in claims if claim.get("evidence_kind") == "LEGACY_EVIDENCE_ONLY"],
    }


def _claims_with_status(claims: list[dict[str, Any]], status: str) -> list[dict[str, Any]]:
    return sorted(
        [claim for claim in claims if claim.get("acceptance_status") == status],
        key=lambda claim: str(claim.get("claim_id")),
    )


def _claim_summary(claim: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_id": str(claim.get("claim_id", "MISSING")),
        "evidence_kind": str(claim.get("evidence_kind", "MISSING")),
        "source_status": str(claim.get("source_status", "MISSING")),
        "reason": str(claim.get("reason", "MISSING")),
    }


def _claim_source_summary(claim: dict[str, Any]) -> dict[str, Any]:
    sources = claim.get("source_artifacts") if isinstance(claim.get("source_artifacts"), list) else []
    return {
        "claim_id": str(claim.get("claim_id", "MISSING")),
        "evidence_kind": str(claim.get("evidence_kind", "MISSING")),
        "acceptance_status": str(claim.get("acceptance_status", "MISSING")),
        "source_artifacts": [str(source) for source in sources],
    }


def _claim_uses_fixture_only_evidence(claim: dict[str, Any]) -> bool:
    if claim.get("evidence_kind") == "FIXTURE_ONLY":
        return True
    sources = claim.get("source_artifacts") if isinstance(claim.get("source_artifacts"), list) else []
    return any("tests" in Path(str(source)).parts and "fixtures" in Path(str(source)).parts for source in sources)


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
    out_path = Path(args.out) if args.out else default_acceptance_out_path(root, args.stage)
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
