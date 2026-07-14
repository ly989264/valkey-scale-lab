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
    H09_RENDERED_REPORT_BASENAMES,
    H09_REPORT_REQUIRED_SOURCE_CLAIMS,
    _paths_contain_fixture,
    _paths_contain_legacy_only,
    _report_cited_claim_ids,
    _report_index_reasons,
    _report_required_sections_present,
    _report_source_artifact_refs,
    claim_id,
)

GATE = "assert_report_input_quality"
SCALES = {30, 50, 100, 200}


def evaluate_report_input_quality(root: Path, manifest_path: Path) -> tuple[str, list[dict[str, Any]], list[str], dict[str, Any]]:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        return "FAIL", [violation("manifest_unreadable", "Evidence manifest is missing or invalid JSON.", path=str(manifest_path))], [], {}
    claims = manifest.get("claims")
    if not isinstance(claims, list):
        return "FAIL", [violation("claims_not_list", "Evidence manifest claims must be a list.", path=str(manifest_path))], [], {}
    by_id = {str(claim.get("claim_id")): claim for claim in claims if isinstance(claim, dict)}
    report_claims = [claim for claim in claims if isinstance(claim, dict) and claim.get("capability") == "report"]
    by_scale = {int(claim.get("scale")): claim for claim in report_claims if isinstance(claim.get("scale"), int)}

    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    passed: list[str] = []
    blocked_claims: list[dict[str, Any]] = []

    for scale in sorted(SCALES):
        cid = claim_id("report", scale)
        claim = by_scale.get(scale)
        if not isinstance(claim, dict):
            violations.append(violation("claim_missing", "Required report claim is missing.", claim_id=cid))
            continue
        claim_violations, claim_blocked, claim_passed = _validate_report_claim(root, claim, by_id)
        violations.extend(claim_violations)
        if claim_passed:
            passed.append(cid)
        if claim_blocked:
            blocked.append(claim_blocked)
            blocked_claims.append({"claim_id": cid, "reason": claim_blocked})

    status = "FAIL" if violations else "PASS"
    extra = {
        "checked_claim_count": len(SCALES),
        "passed_report_claim_count": len(passed),
        "blocked_report_claim_count": len(blocked_claims),
        "passed_report_claims": passed,
        "blocked_report_claims": blocked_claims,
    }
    return status, violations, blocked, extra


def _validate_report_claim(root: Path, claim: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None, bool]:
    violations: list[dict[str, Any]] = []
    cid = str(claim.get("claim_id"))
    if not isinstance(claim.get("scale"), int):
        return [violation("report_scale_mismatch", "Report claim scale must be an integer.", claim_id=cid, details={"scale": claim.get("scale")})], None, False
    scale = int(claim.get("scale"))
    if scale not in H09_REPORT_REQUIRED_SOURCE_CLAIMS:
        return [violation("report_scale_mismatch", "Report claim scale is not an H09 exact-report scale.", claim_id=cid, details={"scale": scale})], None, False
    status = claim.get("status")
    diagnostics = claim.get("diagnostics") if isinstance(claim.get("diagnostics"), dict) else {}
    h09 = diagnostics.get("report_h09_acceptance") if isinstance(diagnostics, dict) else None
    if not isinstance(h09, dict):
        if status == "PASS":
            violations.append(violation("report_pass_without_h09_diagnostics", "Report PASS requires diagnostics.report_h09_acceptance.", claim_id=cid))
        else:
            violations.append(violation("report_h09_diagnostics_missing", "Report claim must include H09 source-quality diagnostics.", claim_id=cid))
        return violations, str(claim.get("reason", "missing H09 diagnostics")), False

    semantic = claim.get("semantic_checks") if isinstance(claim.get("semantic_checks"), dict) else {}
    accepted = h09.get("accepted") is True
    source_quality_status = h09.get("source_quality_status")
    render_status = h09.get("render_status")
    required_claim_ids = [claim_id(capability, scale) for capability in H09_REPORT_REQUIRED_SOURCE_CLAIMS[scale]]
    cited_claim_ids = _claim_ids_from_diagnostics(h09)
    missing_citations = sorted(set(required_claim_ids) - set(cited_claim_ids))
    source_artifact_refs = [str(item) for item in h09.get("source_artifact_refs", []) if isinstance(item, str)]
    source_artifacts = [str(item) for item in claim.get("source_artifacts", []) if isinstance(item, str)]

    if status == "PASS" and not accepted:
        violations.append(violation("report_render_pass_promoted_to_source_quality", "Report PASS requires H09 accepted source-quality diagnostics, not render status alone.", claim_id=cid, details={"render_status": render_status, "source_quality_status": source_quality_status}))
    if status == "PASS" and source_quality_status != "PASS":
        violations.append(violation("report_pass_without_accepted_source_claims", "Report PASS requires source_quality_status=PASS.", claim_id=cid, details={"source_quality_status": source_quality_status}))
    if status == "PASS" and claim.get("evidence_kind") not in ALLOWED_PASS_KINDS:
        violations.append(violation("report_pass_nonpromotable_kind", "Report PASS uses a non-promotable evidence kind.", claim_id=cid, details={"evidence_kind": claim.get("evidence_kind")}))
    if status == "PASS" and (semantic.get("hardening_stage_accepted") is not True or semantic.get("m1_format_fields_complete") is not True):
        violations.append(violation("report_pass_incomplete_semantics", "Report PASS requires complete H09 semantic checks.", claim_id=cid))
    if status == "PASS" and missing_citations:
        violations.append(violation("report_pass_without_accepted_source_claims", "Report PASS does not cite required accepted M1H source claims for the same scale.", claim_id=cid, details={"missing_claims": missing_citations}))

    blocked_dependencies = _blocked_dependencies(required_claim_ids, by_id)
    if status == "PASS" and blocked_dependencies:
        violations.append(violation("report_pass_with_blocked_source_claim", "Report PASS cites blocked, missing, or non-promotable source claims.", claim_id=cid, details={"blocked_dependencies": blocked_dependencies}))
    if status == "PASS" and all(Path(path).name in H09_RENDERED_REPORT_BASENAMES for path in source_artifacts):
        violations.append(violation("report_pass_backed_only_by_report_files", "Report PASS cannot be backed only by rendered report/index files.", claim_id=cid))
    if status == "PASS" and source_artifact_refs and all(Path(path).name in H09_RENDERED_REPORT_BASENAMES for path in source_artifact_refs):
        violations.append(violation("report_pass_backed_only_by_report_files", "Report PASS source refs cannot be only rendered report files.", claim_id=cid))
    if status == "PASS" and _paths_contain_fixture([*source_artifacts, *source_artifact_refs]):
        violations.append(violation("report_fixture_source_promoted", "Fixture-backed report source refs cannot satisfy report PASS.", claim_id=cid))
    if status == "PASS" and _paths_contain_legacy_only([*source_artifacts, *source_artifact_refs]):
        violations.append(violation("report_legacy_source_promoted", "Legacy-only report source refs cannot satisfy report PASS.", claim_id=cid))

    for index_path in _report_index_paths(root, source_artifacts):
        report_index = read_json(index_path)
        index_reasons = _report_index_reasons(root, index_path, report_index, scale)
        index_cited_claim_ids = _report_cited_claim_ids(report_index)
        index_source_refs = _report_source_artifact_refs(report_index)
        if status == "PASS" and index_reasons:
            _append_index_violations(violations, cid, index_path, index_reasons, report_index)
        if status == "PASS" and sorted(set(required_claim_ids) - set(index_cited_claim_ids)):
            violations.append(violation("report_pass_without_accepted_source_claims", "Report index does not cite every required accepted source claim.", claim_id=cid, path=str(index_path), details={"missing_claims": sorted(set(required_claim_ids) - set(index_cited_claim_ids))}))
        if status == "PASS" and _paths_contain_fixture(index_source_refs):
            violations.append(violation("report_fixture_source_promoted", "Report index source refs include fixtures.", claim_id=cid, path=str(index_path)))
        if status == "PASS" and _paths_contain_legacy_only(index_source_refs):
            violations.append(violation("report_legacy_source_promoted", "Report index source refs include legacy-only artifacts.", claim_id=cid, path=str(index_path)))
        if status == "PASS" and index_source_refs and all(Path(path).name in H09_RENDERED_REPORT_BASENAMES for path in index_source_refs):
            violations.append(violation("report_pass_backed_only_by_report_files", "Report index source refs cannot be only rendered report files.", claim_id=cid, path=str(index_path)))
    if status == "PASS" and not _report_index_paths(root, source_artifacts):
        violations.append(violation("report_index_missing", "Report PASS must cite a readable report_index.json or final_report_index.json.", claim_id=cid))

    blocked_reason = None
    if status == "BLOCKED_WITH_REASON":
        blocked_reason = str(claim.get("reason") or "; ".join(str(reason) for reason in h09.get("reasons", []) if isinstance(reason, str)) or "report source quality is blocked")
    return violations, blocked_reason, status == "PASS" and not violations


def _claim_ids_from_diagnostics(h09: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ["required_source_claims", "cited_source_claims", "accepted_source_claims"]:
        values.append(h09.get(key))
    claim_ids: list[str] = []
    for value in values:
        if isinstance(value, list):
            claim_ids.extend(str(item) for item in value if isinstance(item, str) and ".real_exact." in item)
    return sorted(set(claim_ids))


def _blocked_dependencies(required_claim_ids: list[str], by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    for cid in required_claim_ids:
        claim = by_id.get(cid)
        if not isinstance(claim, dict):
            blocked.append({"claim_id": cid, "reason": "missing required source claim"})
            continue
        semantic = claim.get("semantic_checks") if isinstance(claim.get("semantic_checks"), dict) else {}
        if (
            claim.get("status") != "PASS"
            or claim.get("evidence_kind") not in ALLOWED_PASS_KINDS
            or semantic.get("m1_format_fields_complete") is not True
            or semantic.get("hardening_stage_accepted") is not True
        ):
            blocked.append({"claim_id": cid, "status": claim.get("status"), "evidence_kind": claim.get("evidence_kind"), "reason": claim.get("reason", "source claim is not promotable")})
    return blocked


def _report_index_paths(root: Path, source_artifacts: list[str]) -> list[Path]:
    paths: list[Path] = []
    for source in source_artifacts:
        if Path(source).name not in {"report_index.json", "final_report_index.json"}:
            continue
        path = Path(source)
        if not path.is_absolute():
            path = root / path
        if path.exists():
            paths.append(path)
    return paths


def _append_index_violations(violations: list[dict[str, Any]], cid: str, index_path: Path, reasons: list[str], report_index: Any) -> None:
    for reason in reasons:
        code = "report_required_section_missing"
        if "offline_policy" in reason or "derivation_policy" in reason:
            code = "report_offline_policy_invalid"
        elif "source input refs" in reason:
            code = "report_view_source_ref_missing"
        elif "exact scale" in reason:
            code = "report_scale_mismatch"
        violations.append(violation(code, reason, claim_id=cid, path=str(index_path)))
    if isinstance(report_index, dict) and not _report_required_sections_present(report_index):
        violations.append(violation("report_required_section_missing", "Report index lacks required sections/source records.", claim_id=cid, path=str(index_path)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert H09 report input-quality hardening.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING")
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    status, violations, blocked, extra = evaluate_report_input_quality(root, manifest_path)
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
