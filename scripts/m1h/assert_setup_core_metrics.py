#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import exit_code, print_gate_summary, read_json, violation, write_gate_result
from manifest import ALLOWED_PASS_KINDS, C06_SETUP_CORE_METRICS, CAPABILITY_REQUIRED_CHECKS, claim_id, claims_by_capability

GATE = "assert_setup_core_metrics"
REQUIRED_SCALES = {30, 50, 100, 200}


def evaluate_setup_core_metrics(manifest_path: Path) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        return [violation("manifest_unreadable", "Evidence manifest is missing or invalid JSON.", path=str(manifest_path))], [], {
            "setup_claim_status": "FAIL",
            "passed_claims": [],
        }

    claims = claims_by_capability(manifest, "setup_telemetry")
    by_scale = {int(claim.get("scale")): claim for claim in claims if isinstance(claim.get("scale"), int)}
    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    passed: list[str] = []
    blocked_claims: list[dict[str, Any]] = []

    for scale in sorted(REQUIRED_SCALES):
        cid = claim_id("setup_telemetry", scale)
        claim = by_scale.get(scale)
        if claim is None:
            violations.append(violation("setup_claim_missing", "Required setup telemetry claim is missing.", claim_id=cid))
            continue
        status = claim.get("status")
        semantic = claim.get("semantic_checks") if isinstance(claim.get("semantic_checks"), dict) else {}
        diagnostics = claim.get("diagnostics") if isinstance(claim.get("diagnostics"), dict) else {}
        c06 = diagnostics.get("setup_c06_acceptance") if isinstance(diagnostics.get("setup_c06_acceptance"), dict) else {}
        if status == "PASS":
            passed_errors = _unsafe_pass_errors(claim, semantic, c06)
            if passed_errors:
                for item in passed_errors:
                    violations.append(item)
            else:
                passed.append(cid)
        elif status == "BLOCKED_WITH_REASON":
            reason = claim.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                violations.append(violation("setup_blocked_reason_missing", "Blocked setup telemetry claim must include a reason.", claim_id=cid))
            else:
                blocked.append(f"{cid}: {reason}")
                blocked_claims.append(
                    {
                        "claim_id": cid,
                        "scale": scale,
                        "reason": reason,
                        "failed_c06_reasons": c06.get("reasons", []) if isinstance(c06.get("reasons"), list) else [],
                    }
                )
            _validate_blocked_claim_is_explicit(claim, semantic, c06, violations)
        else:
            violations.append(violation("setup_claim_bad_status", "Setup telemetry claim has invalid status.", claim_id=cid, details={"status": status}))

    setup_claim_status = "PASS" if len(passed) == len(REQUIRED_SCALES) else "BLOCKED_WITH_REASON"
    extra = {
        "setup_claim_status": setup_claim_status,
        "passed_claims": passed,
        "blocked_claims": blocked_claims,
        "checked_claim_count": len(REQUIRED_SCALES),
        "c06_core_metrics": C06_SETUP_CORE_METRICS,
    }
    return violations, blocked, extra


def _unsafe_pass_errors(claim: dict[str, Any], semantic: dict[str, Any], c06: dict[str, Any]) -> list[dict[str, Any]]:
    cid = str(claim.get("claim_id"))
    errors: list[dict[str, Any]] = []
    kind = claim.get("evidence_kind")
    if kind not in ALLOWED_PASS_KINDS:
        errors.append(violation("setup_pass_nonpromotable_kind", "Setup telemetry PASS used non-promotable evidence.", claim_id=cid, details={"evidence_kind": kind}))
    sources = [str(source) for source in claim.get("source_artifacts", []) if isinstance(source, str)]
    if not any(source.endswith("/setup_telemetry.json") or source == "setup_telemetry.json" for source in sources):
        errors.append(violation("setup_pass_missing_m1_artifact", "Setup telemetry PASS did not cite a setup_telemetry.json artifact.", claim_id=cid))
    if any(_is_fixture_source(source) for source in sources):
        errors.append(violation("setup_pass_fixture_source", "Setup telemetry PASS cited fixture evidence.", claim_id=cid))
    if any("runtime_timing_breakdown" in source for source in sources) and not any(source.endswith("/setup_telemetry.json") for source in sources):
        errors.append(violation("setup_pass_legacy_timing_only", "Runtime timing breakdown alone cannot satisfy setup telemetry PASS.", claim_id=cid))
    for check in ["m1_format_fields_complete", "hardening_stage_accepted", *CAPABILITY_REQUIRED_CHECKS["setup_telemetry"]]:
        if semantic.get(check) is not True:
            errors.append(violation("setup_pass_failed_c06_semantic", "Setup telemetry PASS failed a required C06 semantic check.", claim_id=cid, details={"check": check, "actual": semantic.get(check, "MISSING")}))
    if c06 and c06.get("accepted") is not True:
        errors.append(violation("setup_pass_c06_not_accepted", "Setup telemetry PASS was not accepted by the C06 evaluator.", claim_id=cid, details={"reasons": c06.get("reasons", [])}))
    return errors


def _validate_blocked_claim_is_explicit(claim: dict[str, Any], semantic: dict[str, Any], c06: dict[str, Any], violations: list[dict[str, Any]]) -> None:
    cid = str(claim.get("claim_id"))
    kind = claim.get("evidence_kind")
    if kind in ALLOWED_PASS_KINDS and semantic.get("m1_format_fields_complete") is True and semantic.get("hardening_stage_accepted") is True:
        violations.append(violation("setup_blocked_but_promotable", "Setup telemetry claim is blocked even though manifest semantics look promotable.", claim_id=cid))
    if not isinstance(c06, dict) or not c06:
        violations.append(violation("setup_c06_diagnostics_missing", "Blocked setup telemetry claim must include C06 diagnostics.", claim_id=cid))
        return
    reasons = c06.get("reasons")
    if c06.get("accepted") is True:
        violations.append(violation("setup_blocked_c06_accepted", "Blocked setup telemetry claim has accepted C06 diagnostics.", claim_id=cid))
    if not isinstance(reasons, list) or not reasons:
        violations.append(violation("setup_blocked_c06_reason_missing", "Blocked setup telemetry claim must name the missing setup telemetry evidence.", claim_id=cid))


def _is_fixture_source(source: str) -> bool:
    parts = Path(source).parts
    return "tests" in parts and "fixtures" in parts


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert C06 setup telemetry exact-scale hardening.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="H03_SETUP_TELEMETRY_REAL_PATH_HARDENING")
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    violations, blocked, extra = evaluate_setup_core_metrics(manifest_path)
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
