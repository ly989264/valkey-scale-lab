#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import exit_code, print_gate_summary, read_json, violation, write_gate_result
from manifest import ALLOWED_PASS_KINDS, CAPABILITY_REQUIRED_CHECKS, H05_REQUIRED_MANAGEMENT_OPERATIONS, claim_id, claims_by_capability

GATE = "assert_management_exact_scale"
REQUIRED_SCALES = {50, 100, 200}


def evaluate_management_exact_scale(manifest_path: Path) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        return [violation("manifest_unreadable", "Evidence manifest is missing or invalid JSON.", path=str(manifest_path))], [], {
            "management_claim_status": "FAIL",
            "passed_claims": [],
        }
    claims = claims_by_capability(manifest, "management_matrix")
    by_scale = {int(claim.get("scale")): claim for claim in claims if isinstance(claim.get("scale"), int)}
    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    passed: list[str] = []
    blocked_claims: list[dict[str, Any]] = []
    for scale in sorted(REQUIRED_SCALES):
        cid = claim_id("management_matrix", scale)
        claim = by_scale.get(scale)
        if claim is None:
            violations.append(violation("management_claim_missing", "Required management matrix claim is missing.", claim_id=cid))
            continue
        status = claim.get("status")
        semantic = claim.get("semantic_checks") if isinstance(claim.get("semantic_checks"), dict) else {}
        diagnostics = claim.get("diagnostics") if isinstance(claim.get("diagnostics"), dict) else {}
        h05 = diagnostics.get("management_h05_acceptance") if isinstance(diagnostics.get("management_h05_acceptance"), dict) else {}
        if status == "PASS":
            errors = _unsafe_pass_errors(claim, semantic, h05)
            if errors:
                violations.extend(errors)
            else:
                passed.append(cid)
        elif status == "BLOCKED_WITH_REASON":
            reason = claim.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                violations.append(violation("management_blocked_reason_missing", "Blocked management matrix claim must include a reason.", claim_id=cid))
            else:
                h05_reasons = h05.get("reasons", []) if isinstance(h05.get("reasons"), list) else []
                blocked.append(f"{cid}: {_truncate_text(reason)}")
                blocked_claims.append(
                    {
                        "claim_id": cid,
                        "scale": scale,
                        "reason": _truncate_text(reason),
                        "failed_h05_reasons": _summarize_reasons(h05_reasons),
                        "failed_h05_reason_count": len(h05_reasons),
                    }
                )
            _validate_blocked_claim_is_explicit(claim, semantic, h05, violations)
        else:
            violations.append(violation("management_claim_bad_status", "Management matrix claim has invalid status.", claim_id=cid, details={"status": status}))
    return violations, blocked, {
        "management_claim_status": "PASS" if len(passed) == len(REQUIRED_SCALES) else "BLOCKED_WITH_REASON",
        "passed_claims": passed,
        "blocked_claims": blocked_claims,
        "checked_claim_count": len(REQUIRED_SCALES),
        "h05_required_operations": sorted(H05_REQUIRED_MANAGEMENT_OPERATIONS),
    }


def _unsafe_pass_errors(claim: dict[str, Any], semantic: dict[str, Any], h05: dict[str, Any]) -> list[dict[str, Any]]:
    cid = str(claim.get("claim_id"))
    errors: list[dict[str, Any]] = []
    if claim.get("evidence_kind") not in ALLOWED_PASS_KINDS:
        errors.append(violation("management_pass_nonpromotable_kind", "Management matrix PASS used non-promotable evidence.", claim_id=cid, details={"evidence_kind": claim.get("evidence_kind")}))
    sources = [str(source) for source in claim.get("source_artifacts", []) if isinstance(source, str)]
    for required in ["management_ops_matrix.json", "management_operation_results.jsonl", "management_workload_impact.json", "management_command_log.jsonl", "valkey_e2e_evidence.json"]:
        if not any(source.endswith("/" + required) for source in sources):
            errors.append(violation("management_pass_missing_artifact", f"Management matrix PASS did not cite {required}.", claim_id=cid))
    if any(_is_fixture_source(source) for source in sources):
        errors.append(violation("management_pass_fixture_source", "Management matrix PASS cited fixture evidence.", claim_id=cid))
    for check in ["m1_format_fields_complete", "hardening_stage_accepted", *CAPABILITY_REQUIRED_CHECKS["management_matrix"]]:
        if semantic.get(check) is not True:
            errors.append(violation("management_pass_failed_h05_semantic", "Management matrix PASS failed a required H05 semantic check.", claim_id=cid, details={"check": check, "actual": semantic.get(check, "MISSING")}))
    if h05 and h05.get("accepted") is not True:
        errors.append(violation("management_pass_h05_not_accepted", "Management matrix PASS was not accepted by the H05 evaluator.", claim_id=cid, details={"reasons": h05.get("reasons", [])}))
    return errors


def _validate_blocked_claim_is_explicit(claim: dict[str, Any], semantic: dict[str, Any], h05: dict[str, Any], violations: list[dict[str, Any]]) -> None:
    cid = str(claim.get("claim_id"))
    if claim.get("evidence_kind") in ALLOWED_PASS_KINDS and semantic.get("m1_format_fields_complete") is True and semantic.get("hardening_stage_accepted") is True:
        violations.append(violation("management_blocked_but_promotable", "Management matrix claim is blocked even though manifest semantics look promotable.", claim_id=cid))
    if not isinstance(h05, dict) or not h05:
        violations.append(violation("management_h05_diagnostics_missing", "Blocked management matrix claim must include H05 diagnostics.", claim_id=cid))
        return
    if h05.get("accepted") is True:
        violations.append(violation("management_blocked_h05_accepted", "Blocked management matrix claim has accepted H05 diagnostics.", claim_id=cid))
    reasons = h05.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        violations.append(violation("management_blocked_h05_reason_missing", "Blocked management matrix claim must name missing management evidence.", claim_id=cid))


def _is_fixture_source(source: str) -> bool:
    parts = Path(source).parts
    return "tests" in parts and "fixtures" in parts


def _summarize_reasons(reasons: list[Any], limit: int = 50) -> list[str]:
    summary = [_truncate_text(str(reason)) for reason in reasons[:limit]]
    omitted = len(reasons) - len(summary)
    if omitted > 0:
        summary.append(f"... {omitted} additional H05 diagnostic reasons omitted; see evidence_manifest.json for full claim diagnostics.")
    return summary


def _truncate_text(value: str, limit: int = 1000) -> str:
    cleaned = value.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit - 3] + "..."


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert H05 management matrix exact-scale hardening.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING")
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    violations, blocked, extra = evaluate_management_exact_scale(manifest_path)
    status = "FAIL" if violations else "PASS"
    result = write_gate_result(root=root, stage_id=args.stage, gate_name=GATE, status=status, inputs=[str(manifest_path)], violations=violations, blocked_reasons=blocked, extra=extra)
    print_gate_summary(result)
    return exit_code(status)


if __name__ == "__main__":
    raise SystemExit(main())
