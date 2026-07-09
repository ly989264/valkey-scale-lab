#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import exit_code, print_gate_summary, read_json, violation, write_gate_result
from manifest import ALLOWED_PASS_KINDS, CAPABILITIES, EVIDENCE_KINDS, REQUIRED_CLAIMS, claim_id

GATE = "assert_evidence_taxonomy"


def validate_manifest(root: Path, manifest_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        return [violation("manifest_unreadable", "Evidence manifest is missing or invalid JSON.", path=str(manifest_path))], []
    for key, expected in {"schema_version": "v1", "artifact_type": "m1h_evidence_manifest"}.items():
        if manifest.get(key) != expected:
            violations.append(violation("manifest_bad_field", f"Manifest {key} must be {expected!r}.", details={"actual": manifest.get(key)}))
    claims = manifest.get("claims")
    if not isinstance(claims, list):
        violations.append(violation("claims_not_list", "Manifest claims must be a list."))
        return violations, blocked
    by_id: dict[str, dict[str, Any]] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            violations.append(violation("claim_not_object", "Each claim must be a JSON object."))
            continue
        cid = str(claim.get("claim_id", ""))
        by_id[cid] = claim
        _validate_claim(root, claim, violations, blocked)
    for capability, scale in REQUIRED_CLAIMS:
        cid = claim_id(capability, scale)
        if cid not in by_id:
            violations.append(violation("required_claim_missing", "Required exact-scale claim is missing.", claim_id=cid))
    return violations, blocked


def _validate_claim(root: Path, claim: dict[str, Any], violations: list[dict[str, Any]], blocked: list[str]) -> None:
    cid = str(claim.get("claim_id", ""))
    capability = claim.get("capability")
    evidence_kind = claim.get("evidence_kind")
    status = claim.get("status")
    if capability not in CAPABILITIES:
        violations.append(violation("unknown_capability", "Claim has an unknown capability.", claim_id=cid, details={"capability": capability}))
    if evidence_kind not in EVIDENCE_KINDS:
        violations.append(violation("unknown_evidence_kind", "Claim has an unknown evidence kind.", claim_id=cid, details={"evidence_kind": evidence_kind}))
    if status not in {"PASS", "FAIL", "BLOCKED_WITH_REASON"}:
        violations.append(violation("unknown_claim_status", "Claim has an unknown status.", claim_id=cid, details={"status": status}))
    sources = claim.get("source_artifacts")
    if not isinstance(sources, list):
        violations.append(violation("sources_not_list", "Claim source_artifacts must be a list.", claim_id=cid))
        sources = []
    if status != "BLOCKED_WITH_REASON" and not sources:
        violations.append(violation("sources_missing", "Non-blocked claim must cite source artifacts.", claim_id=cid))
    for source in sources:
        if not isinstance(source, str) or not source:
            violations.append(violation("source_invalid", "Source artifact path must be a non-empty string.", claim_id=cid))
        elif not (root / source).exists():
            violations.append(violation("source_missing", "Source artifact path does not exist.", claim_id=cid, path=source))
    semantic = claim.get("semantic_checks")
    if not isinstance(semantic, dict) or not semantic:
        violations.append(violation("semantic_checks_missing", "Claim must include semantic_checks.", claim_id=cid))
    elif set(semantic) <= {"file_exists", "metric_count", "row_count", "non_empty"}:
        violations.append(violation("semantic_checks_too_shallow", "Claim semantic checks must be capability-specific, not file/count-only.", claim_id=cid))
    if claim.get("required_for_milestone_pass") is True and status == "PASS":
        if evidence_kind not in ALLOWED_PASS_KINDS:
            violations.append(violation("required_pass_disallowed_kind", "Required claim passed with non-promotable evidence kind.", claim_id=cid, details={"evidence_kind": evidence_kind}))
        if isinstance(semantic, dict):
            failed = [name for name, value in semantic.items() if value is not True and not name.endswith("_count")]
            if failed:
                violations.append(violation("required_pass_failed_semantics", "Required PASS claim has failed semantic checks.", claim_id=cid, details={"failed_checks": failed}))
    if status == "BLOCKED_WITH_REASON":
        reason = claim.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            violations.append(violation("blocked_reason_missing", "Blocked claim must include a reason.", claim_id=cid))
        else:
            blocked.append(f"{cid}: {reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the M1 hardening evidence taxonomy.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="H00_BOOTSTRAP_HARD_GATES")
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    parser.add_argument("--allow-blocked", action="store_true")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    violations, blocked = validate_manifest(root, manifest_path)
    status = "FAIL" if violations else "PASS"
    result = write_gate_result(
        root=root,
        stage_id=args.stage,
        gate_name=GATE,
        status=status,
        inputs=[str(manifest_path)],
        violations=violations,
        blocked_reasons=blocked,
    )
    print_gate_summary(result)
    return exit_code(status, allow_blocked=args.allow_blocked)


if __name__ == "__main__":
    raise SystemExit(main())
