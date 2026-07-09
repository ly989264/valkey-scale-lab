#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import exit_code, print_gate_summary, read_json, violation, write_gate_result
from manifest import ALLOWED_PASS_KINDS, C07_REQUIRED_COMMAND_KINDS, CAPABILITY_REQUIRED_CHECKS, claim_id, claims_by_capability

GATE = "assert_command_audit_real"
REQUIRED_SCALES = {50, 100, 200}


def evaluate_command_audit_real(manifest_path: Path) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        return [violation("manifest_unreadable", "Evidence manifest is missing or invalid JSON.", path=str(manifest_path))], [], {
            "command_claim_status": "FAIL",
            "passed_claims": [],
        }

    claims = claims_by_capability(manifest, "command_audit")
    by_scale = {int(claim.get("scale")): claim for claim in claims if isinstance(claim.get("scale"), int)}
    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    passed: list[str] = []
    blocked_claims: list[dict[str, Any]] = []

    for scale in sorted(REQUIRED_SCALES):
        cid = claim_id("command_audit", scale)
        claim = by_scale.get(scale)
        if claim is None:
            violations.append(violation("command_claim_missing", "Required command audit claim is missing.", claim_id=cid))
            continue
        status = claim.get("status")
        semantic = claim.get("semantic_checks") if isinstance(claim.get("semantic_checks"), dict) else {}
        diagnostics = claim.get("diagnostics") if isinstance(claim.get("diagnostics"), dict) else {}
        c07 = diagnostics.get("command_c07_acceptance") if isinstance(diagnostics.get("command_c07_acceptance"), dict) else {}
        if status == "PASS":
            pass_errors = _unsafe_pass_errors(claim, semantic, c07)
            if pass_errors:
                violations.extend(pass_errors)
            else:
                passed.append(cid)
        elif status == "BLOCKED_WITH_REASON":
            reason = claim.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                violations.append(violation("command_blocked_reason_missing", "Blocked command audit claim must include a reason.", claim_id=cid))
            else:
                blocked.append(f"{cid}: {reason}")
                blocked_claims.append(
                    {
                        "claim_id": cid,
                        "scale": scale,
                        "reason": reason,
                        "failed_c07_reasons": c07.get("reasons", []) if isinstance(c07.get("reasons"), list) else [],
                    }
                )
            _validate_blocked_claim_is_explicit(claim, semantic, c07, violations)
        else:
            violations.append(violation("command_claim_bad_status", "Command audit claim has invalid status.", claim_id=cid, details={"status": status}))

    command_claim_status = "PASS" if len(passed) == len(REQUIRED_SCALES) else "BLOCKED_WITH_REASON"
    extra = {
        "command_claim_status": command_claim_status,
        "passed_claims": passed,
        "blocked_claims": blocked_claims,
        "checked_claim_count": len(REQUIRED_SCALES),
        "c07_required_command_kinds": sorted(C07_REQUIRED_COMMAND_KINDS),
    }
    return violations, blocked, extra


def _unsafe_pass_errors(claim: dict[str, Any], semantic: dict[str, Any], c07: dict[str, Any]) -> list[dict[str, Any]]:
    cid = str(claim.get("claim_id"))
    errors: list[dict[str, Any]] = []
    kind = claim.get("evidence_kind")
    if kind not in ALLOWED_PASS_KINDS:
        errors.append(violation("command_pass_nonpromotable_kind", "Command audit PASS used non-promotable evidence.", claim_id=cid, details={"evidence_kind": kind}))
    sources = [str(source) for source in claim.get("source_artifacts", []) if isinstance(source, str)]
    if not any(source.endswith("/command_log.jsonl") or source.endswith("/management_command_log.jsonl") or source.endswith("/fault_command_log.jsonl") for source in sources):
        errors.append(violation("command_pass_missing_log_artifact", "Command audit PASS did not cite a command log artifact.", claim_id=cid))
    if not any(source.endswith("/command_audit_summary.json") for source in sources):
        errors.append(violation("command_pass_missing_summary_artifact", "Command audit PASS did not cite command_audit_summary.json.", claim_id=cid))
    if any(_is_fixture_source(source) for source in sources):
        errors.append(violation("command_pass_fixture_source", "Command audit PASS cited fixture evidence.", claim_id=cid))
    for check in ["m1_format_fields_complete", "hardening_stage_accepted", *CAPABILITY_REQUIRED_CHECKS["command_audit"]]:
        if semantic.get(check) is not True:
            errors.append(violation("command_pass_failed_c07_semantic", "Command audit PASS failed a required C07 semantic check.", claim_id=cid, details={"check": check, "actual": semantic.get(check, "MISSING")}))
    if c07 and c07.get("accepted") is not True:
        errors.append(violation("command_pass_c07_not_accepted", "Command audit PASS was not accepted by the C07 evaluator.", claim_id=cid, details={"reasons": c07.get("reasons", [])}))
    return errors


def _validate_blocked_claim_is_explicit(claim: dict[str, Any], semantic: dict[str, Any], c07: dict[str, Any], violations: list[dict[str, Any]]) -> None:
    cid = str(claim.get("claim_id"))
    kind = claim.get("evidence_kind")
    if kind in ALLOWED_PASS_KINDS and semantic.get("m1_format_fields_complete") is True and semantic.get("hardening_stage_accepted") is True:
        violations.append(violation("command_blocked_but_promotable", "Command audit claim is blocked even though manifest semantics look promotable.", claim_id=cid))
    if not isinstance(c07, dict) or not c07:
        violations.append(violation("command_c07_diagnostics_missing", "Blocked command audit claim must include C07 diagnostics.", claim_id=cid))
        return
    reasons = c07.get("reasons")
    if c07.get("accepted") is True:
        violations.append(violation("command_blocked_c07_accepted", "Blocked command audit claim has accepted C07 diagnostics.", claim_id=cid))
    if not isinstance(reasons, list) or not reasons:
        violations.append(violation("command_blocked_c07_reason_missing", "Blocked command audit claim must name the missing command audit evidence.", claim_id=cid))


def _is_fixture_source(source: str) -> bool:
    parts = Path(source).parts
    return "tests" in parts and "fixtures" in parts


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert C07 command audit exact-scale hardening.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="H04_COMMAND_AUDIT_REAL_PATH_HARDENING")
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    violations, blocked, extra = evaluate_command_audit_real(manifest_path)
    status = "FAIL" if violations else "PASS"
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
    return exit_code(status)


if __name__ == "__main__":
    raise SystemExit(main())
