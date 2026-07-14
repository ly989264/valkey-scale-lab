#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import exit_code, print_gate_summary, read_json, violation, write_gate_result
from manifest import (
    ALLOWED_PASS_KINDS,
    CAPABILITY_REQUIRED_CHECKS,
    H08_HIGH_VALUE_METRIC_GROUPS,
    H08_REQUIRED_SYSTEM_SCALES,
    claim_id,
    claims_by_capability,
)

GATE = "assert_system_metrics_real_windows"
REQUIRED_SCALES = H08_REQUIRED_SYSTEM_SCALES


def evaluate_system_metrics_real_windows(manifest_path: Path) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        return [violation("manifest_unreadable", "Evidence manifest is missing or invalid JSON.", path=str(manifest_path))], [], {
            "system_metrics_claim_status": "FAIL",
            "passed_claims": [],
        }
    claims = claims_by_capability(manifest, "system_metrics")
    by_scale = {int(claim.get("scale")): claim for claim in claims if isinstance(claim.get("scale"), int)}
    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    passed: list[str] = []
    blocked_claims: list[dict[str, Any]] = []
    rejected_non_system_row_count = 0
    for scale in sorted(REQUIRED_SCALES):
        cid = claim_id("system_metrics", scale)
        claim = by_scale.get(scale)
        if claim is None:
            violations.append(violation("system_metrics_claim_missing", "Required system metrics claim is missing.", claim_id=cid))
            continue
        status = claim.get("status")
        semantic = claim.get("semantic_checks") if isinstance(claim.get("semantic_checks"), dict) else {}
        diagnostics = claim.get("diagnostics") if isinstance(claim.get("diagnostics"), dict) else {}
        h08 = diagnostics.get("system_h08_acceptance") if isinstance(diagnostics.get("system_h08_acceptance"), dict) else {}
        rejected_non_system_row_count += int(h08.get("rejected_non_system_row_count", 0) or 0) if isinstance(h08, dict) else 0
        if status == "PASS":
            errors = _unsafe_pass_errors(claim, semantic, h08)
            if errors:
                violations.extend(errors)
            else:
                passed.append(cid)
        elif status == "BLOCKED_WITH_REASON":
            reason = claim.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                violations.append(violation("system_metrics_blocked_reason_missing", "Blocked system metrics claim must include a reason.", claim_id=cid))
            else:
                h08_reasons = h08.get("reasons", []) if isinstance(h08.get("reasons"), list) else []
                blocked.append(f"{cid}: {_truncate_text(reason)}")
                blocked_claims.append(
                    {
                        "claim_id": cid,
                        "scale": scale,
                        "reason": _truncate_text(reason),
                        "failed_h08_reasons": _summarize_reasons(h08_reasons),
                        "failed_h08_reason_count": len(h08_reasons),
                    }
                )
            _validate_blocked_claim_is_explicit(claim, semantic, h08, violations)
        else:
            violations.append(violation("system_metrics_claim_bad_status", "System metrics claim has invalid status.", claim_id=cid, details={"status": status}))
    return violations, blocked, {
        "system_metrics_claim_status": "PASS" if len(passed) == len(REQUIRED_SCALES) else "BLOCKED_WITH_REASON",
        "passed_claims": passed,
        "blocked_claims": blocked_claims,
        "checked_claim_count": len(REQUIRED_SCALES),
        "h08_required_scales": sorted(REQUIRED_SCALES),
        "h08_high_value_metric_groups": H08_HIGH_VALUE_METRIC_GROUPS,
        "rejected_non_system_row_count": rejected_non_system_row_count,
    }


def _unsafe_pass_errors(claim: dict[str, Any], semantic: dict[str, Any], h08: dict[str, Any]) -> list[dict[str, Any]]:
    cid = str(claim.get("claim_id"))
    errors: list[dict[str, Any]] = []
    if claim.get("evidence_kind") not in ALLOWED_PASS_KINDS:
        errors.append(violation("system_metrics_pass_nonpromotable_kind", "System metrics PASS used non-promotable evidence.", claim_id=cid, details={"evidence_kind": claim.get("evidence_kind")}))
    sources = [str(source) for source in claim.get("source_artifacts", []) if isinstance(source, str)]
    for required in ["system_metrics_report.json", "system_metrics_timeseries.jsonl", "valkey_e2e_evidence.json"]:
        if not any(source.endswith("/" + required) for source in sources):
            errors.append(violation("system_metrics_pass_missing_artifact", f"System metrics PASS did not cite {required}.", claim_id=cid))
    if any(_is_fixture_source(source) for source in sources):
        errors.append(violation("system_metrics_pass_fixture_source", "System metrics PASS cited fixture evidence.", claim_id=cid))
    if any(_is_fake_partial_or_dry_source(source) for source in sources):
        errors.append(violation("system_metrics_pass_fake_or_dry_source", "System metrics PASS cited fake, partial, dry-run, or legacy evidence path.", claim_id=cid))
    for check in ["m1_format_fields_complete", "hardening_stage_accepted", *CAPABILITY_REQUIRED_CHECKS["system_metrics"]]:
        if semantic.get(check) is not True:
            errors.append(violation("system_metrics_pass_failed_h08_semantic", "System metrics PASS failed a required H08 semantic check.", claim_id=cid, details={"check": check, "actual": semantic.get(check, "MISSING")}))
    if h08.get("accepted") is not True:
        errors.append(violation("system_metrics_pass_h08_not_accepted", "System metrics PASS was not accepted by the H08 evaluator.", claim_id=cid, details={"reasons": h08.get("reasons", [])}))
    return errors


def _validate_blocked_claim_is_explicit(claim: dict[str, Any], semantic: dict[str, Any], h08: dict[str, Any], violations: list[dict[str, Any]]) -> None:
    cid = str(claim.get("claim_id"))
    if claim.get("evidence_kind") in ALLOWED_PASS_KINDS and semantic.get("m1_format_fields_complete") is True and semantic.get("hardening_stage_accepted") is True:
        violations.append(violation("system_metrics_blocked_but_promotable", "System metrics claim is blocked even though manifest semantics look promotable.", claim_id=cid))
    if not isinstance(h08, dict) or not h08:
        violations.append(violation("system_metrics_h08_diagnostics_missing", "Blocked system metrics claim must include H08 diagnostics.", claim_id=cid))
        return
    if h08.get("accepted") is True:
        violations.append(violation("system_metrics_blocked_h08_accepted", "Blocked system metrics claim has accepted H08 diagnostics.", claim_id=cid))
    reasons = h08.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        violations.append(violation("system_metrics_blocked_h08_reason_missing", "Blocked system metrics claim must name missing C10 evidence.", claim_id=cid))


def _is_fixture_source(source: str) -> bool:
    parts = Path(source).parts
    return "tests" in parts and "fixtures" in parts


def _is_fake_partial_or_dry_source(source: str) -> bool:
    lowered = source.lower()
    return any(token in lowered for token in ["fake", "partial", "dry-run", "dry_run", "dryrun", "legacy"])


def _summarize_reasons(reasons: list[Any], limit: int = 50) -> list[str]:
    summary = [_truncate_text(str(reason)) for reason in reasons[:limit]]
    omitted = len(reasons) - len(summary)
    if omitted > 0:
        summary.append(f"... {omitted} additional H08 diagnostic reasons omitted; see evidence_manifest.json for full claim diagnostics.")
    return summary


def _truncate_text(value: str, limit: int = 1000) -> str:
    cleaned = value.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert H08 system metrics real lifecycle-window hardening.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING")
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    violations, blocked, extra = evaluate_system_metrics_real_windows(manifest_path)
    status = "FAIL" if violations else "PASS"
    result = write_gate_result(root=root, stage_id=args.stage, gate_name=GATE, status=status, inputs=[str(manifest_path)], violations=violations, blocked_reasons=blocked, extra=extra)
    print_gate_summary(result)
    return exit_code(status)


if __name__ == "__main__":
    raise SystemExit(main())
