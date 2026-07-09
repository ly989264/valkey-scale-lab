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
    H06_MIN_OPERATIONS_PER_WINDOW,
    H06_REQUIRED_METRIC_ROW_COUNT,
    H06_REQUIRED_WORKLOAD_METRICS,
    H06_REQUIRED_WORKLOAD_PROFILES,
    H06_REQUIRED_WORKLOAD_WINDOWS,
    claim_id,
    claims_by_capability,
)

GATE = "assert_workload_benchmark_strength"
REQUIRED_SCALES = {30, 50, 100, 200}


def evaluate_workload_benchmark_strength(manifest_path: Path) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        return [violation("manifest_unreadable", "Evidence manifest is missing or invalid JSON.", path=str(manifest_path))], [], {
            "workload_claim_status": "FAIL",
            "passed_claims": [],
        }
    claims = claims_by_capability(manifest, "workload_benchmark")
    by_scale = {int(claim.get("scale")): claim for claim in claims if isinstance(claim.get("scale"), int)}
    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    passed: list[str] = []
    blocked_claims: list[dict[str, Any]] = []
    for scale in sorted(REQUIRED_SCALES):
        cid = claim_id("workload_benchmark", scale)
        claim = by_scale.get(scale)
        if claim is None:
            violations.append(violation("workload_claim_missing", "Required workload benchmark claim is missing.", claim_id=cid))
            continue
        status = claim.get("status")
        semantic = claim.get("semantic_checks") if isinstance(claim.get("semantic_checks"), dict) else {}
        diagnostics = claim.get("diagnostics") if isinstance(claim.get("diagnostics"), dict) else {}
        h06 = diagnostics.get("workload_h06_acceptance") if isinstance(diagnostics.get("workload_h06_acceptance"), dict) else {}
        if status == "PASS":
            errors = _unsafe_pass_errors(claim, semantic, h06)
            if errors:
                violations.extend(errors)
            else:
                passed.append(cid)
        elif status == "BLOCKED_WITH_REASON":
            reason = claim.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                violations.append(violation("workload_blocked_reason_missing", "Blocked workload benchmark claim must include a reason.", claim_id=cid))
            else:
                h06_reasons = h06.get("reasons", []) if isinstance(h06.get("reasons"), list) else []
                blocked.append(f"{cid}: {_truncate_text(reason)}")
                blocked_claims.append(
                    {
                        "claim_id": cid,
                        "scale": scale,
                        "reason": _truncate_text(reason),
                        "failed_h06_reasons": _summarize_reasons(h06_reasons),
                        "failed_h06_reason_count": len(h06_reasons),
                    }
                )
            _validate_blocked_claim_is_explicit(claim, semantic, h06, violations)
        else:
            violations.append(violation("workload_claim_bad_status", "Workload benchmark claim has invalid status.", claim_id=cid, details={"status": status}))
    return violations, blocked, {
        "workload_claim_status": "PASS" if len(passed) == len(REQUIRED_SCALES) else "BLOCKED_WITH_REASON",
        "passed_claims": passed,
        "blocked_claims": blocked_claims,
        "checked_claim_count": len(REQUIRED_SCALES),
        "h06_required_profiles": H06_REQUIRED_WORKLOAD_PROFILES,
        "h06_required_windows": H06_REQUIRED_WORKLOAD_WINDOWS,
        "h06_required_metrics": H06_REQUIRED_WORKLOAD_METRICS,
        "h06_minimum_metric_rows": H06_REQUIRED_METRIC_ROW_COUNT,
        "h06_minimum_operations_per_window": H06_MIN_OPERATIONS_PER_WINDOW,
    }


def _unsafe_pass_errors(claim: dict[str, Any], semantic: dict[str, Any], h06: dict[str, Any]) -> list[dict[str, Any]]:
    cid = str(claim.get("claim_id"))
    errors: list[dict[str, Any]] = []
    if claim.get("evidence_kind") not in ALLOWED_PASS_KINDS:
        errors.append(violation("workload_pass_nonpromotable_kind", "Workload benchmark PASS used non-promotable evidence.", claim_id=cid, details={"evidence_kind": claim.get("evidence_kind")}))
    sources = [str(source) for source in claim.get("source_artifacts", []) if isinstance(source, str)]
    for required in ["workload_windows.json", "metrics_timeseries.jsonl", "valkey_e2e_evidence.json"]:
        if not any(source.endswith("/" + required) for source in sources):
            errors.append(violation("workload_pass_missing_artifact", f"Workload benchmark PASS did not cite {required}.", claim_id=cid))
    if any(_is_fixture_source(source) for source in sources):
        errors.append(violation("workload_pass_fixture_source", "Workload benchmark PASS cited fixture evidence.", claim_id=cid))
    for check in ["m1_format_fields_complete", "hardening_stage_accepted", *CAPABILITY_REQUIRED_CHECKS["workload_benchmark"]]:
        if semantic.get(check) is not True:
            errors.append(violation("workload_pass_failed_h06_semantic", "Workload benchmark PASS failed a required H06 semantic check.", claim_id=cid, details={"check": check, "actual": semantic.get(check, "MISSING")}))
    if h06 and h06.get("accepted") is not True:
        errors.append(violation("workload_pass_h06_not_accepted", "Workload benchmark PASS was not accepted by the H06 evaluator.", claim_id=cid, details={"reasons": h06.get("reasons", [])}))
    if int(h06.get("metric_row_count", 0) or 0) < H06_REQUIRED_METRIC_ROW_COUNT:
        errors.append(violation("workload_pass_row_count_shallow", "Workload benchmark PASS has too few required metric rows.", claim_id=cid, details={"metric_row_count": h06.get("metric_row_count")}))
    return errors


def _validate_blocked_claim_is_explicit(claim: dict[str, Any], semantic: dict[str, Any], h06: dict[str, Any], violations: list[dict[str, Any]]) -> None:
    cid = str(claim.get("claim_id"))
    if claim.get("evidence_kind") in ALLOWED_PASS_KINDS and semantic.get("m1_format_fields_complete") is True and semantic.get("hardening_stage_accepted") is True:
        violations.append(violation("workload_blocked_but_promotable", "Workload benchmark claim is blocked even though manifest semantics look promotable.", claim_id=cid))
    if not isinstance(h06, dict) or not h06:
        violations.append(violation("workload_h06_diagnostics_missing", "Blocked workload benchmark claim must include H06 diagnostics.", claim_id=cid))
        return
    if h06.get("accepted") is True:
        violations.append(violation("workload_blocked_h06_accepted", "Blocked workload benchmark claim has accepted H06 diagnostics.", claim_id=cid))
    reasons = h06.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        violations.append(violation("workload_blocked_h06_reason_missing", "Blocked workload benchmark claim must name missing workload evidence.", claim_id=cid))


def _is_fixture_source(source: str) -> bool:
    parts = Path(source).parts
    return "tests" in parts and "fixtures" in parts


def _summarize_reasons(reasons: list[Any], limit: int = 50) -> list[str]:
    summary = [_truncate_text(str(reason)) for reason in reasons[:limit]]
    omitted = len(reasons) - len(summary)
    if omitted > 0:
        summary.append(f"... {omitted} additional H06 diagnostic reasons omitted; see evidence_manifest.json for full claim diagnostics.")
    return summary


def _truncate_text(value: str, limit: int = 1000) -> str:
    cleaned = value.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert H06 workload benchmark hardening.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="H06_WORKLOAD_BENCHMARK_HARDENING")
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    violations, blocked, extra = evaluate_workload_benchmark_strength(manifest_path)
    status = "FAIL" if violations else "PASS"
    result = write_gate_result(root=root, stage_id=args.stage, gate_name=GATE, status=status, inputs=[str(manifest_path)], violations=violations, blocked_reasons=blocked, extra=extra)
    print_gate_summary(result)
    return exit_code(status)


if __name__ == "__main__":
    raise SystemExit(main())
