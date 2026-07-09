#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import exit_code, print_gate_summary, read_json, relpath, violation, write_gate_result, write_json
from manifest import ALLOWED_PASS_KINDS, REQUIRED_CLAIMS, claim_id

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


def _reset_claim(root: Path, source: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cid = str(source.get("claim_id", ""))
    kind = str(source.get("evidence_kind", ""))
    source_status = str(source.get("status", ""))
    semantic = source.get("semantic_checks") if isinstance(source.get("semantic_checks"), dict) else {}
    sources = source.get("source_artifacts") if isinstance(source.get("source_artifacts"), list) else []
    reason = source.get("reason") if isinstance(source.get("reason"), str) and source.get("reason").strip() else ""
    violations: list[dict[str, Any]] = []

    pass_allowed = (
        source_status == "PASS"
        and kind in ALLOWED_PASS_KINDS
        and semantic.get("m1_format_fields_complete") is True
        and semantic.get("hardening_stage_accepted") is True
        and not any(_is_fixture_source(str(item)) for item in sources)
    )
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
