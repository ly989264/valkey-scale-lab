#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from common import read_json, violation
from manifest import ALLOWED_PASS_KINDS, claims_by_capability


def evaluate_capability(root: Path, manifest_path: Path, capability: str, required_scales: set[int]) -> tuple[str, list[dict[str, Any]], list[str], dict[str, Any]]:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        return "FAIL", [violation("manifest_unreadable", "Evidence manifest is missing or invalid JSON.", path=str(manifest_path))], [], {"passed_claims": []}
    claims = claims_by_capability(manifest, capability)
    by_scale = {int(claim.get("scale")): claim for claim in claims if isinstance(claim.get("scale"), int)}
    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    passed: list[str] = []
    for scale in sorted(required_scales):
        claim = by_scale.get(scale)
        if claim is None:
            violations.append(violation("claim_missing", "Required capability claim is missing.", claim_id=f"{capability}.real_exact.{scale}"))
            continue
        cid = str(claim.get("claim_id"))
        evidence_kind = claim.get("evidence_kind")
        status = claim.get("status")
        semantic = claim.get("semantic_checks")
        if status == "PASS":
            if evidence_kind not in ALLOWED_PASS_KINDS:
                violations.append(violation("disallowed_pass_kind", "Capability claim passed with non-promotable evidence.", claim_id=cid, details={"evidence_kind": evidence_kind}))
            elif not isinstance(semantic, dict) or any(value is not True for key, value in semantic.items() if not key.endswith("_count")):
                violations.append(violation("incomplete_semantics", "Capability claim passed without complete semantic checks.", claim_id=cid))
            else:
                passed.append(cid)
        elif status == "BLOCKED_WITH_REASON":
            blocked.append(f"{cid}: {claim.get('reason', 'blocked without detailed reason')}")
        else:
            violations.append(violation("claim_failed", "Capability claim failed.", claim_id=cid, details={"status": status}))
    if violations:
        status = "FAIL"
    elif blocked:
        status = "BLOCKED_WITH_REASON"
    else:
        status = "PASS"
    return status, violations, blocked, {"passed_claims": passed, "checked_claim_count": len(required_scales)}
