from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_COVERAGE = {
    "lifecycle",
    "stability",
    "management",
    "fault_failover",
    "telemetry",
    "artifact_validation",
    "analysis",
    "report",
    "cleanup",
}


def self_check(milestone: int) -> bool:
    return milestone in {1, 2, 3} and len(REQUIRED_COVERAGE) == 9


def evaluate(
    *,
    milestone: int,
    scale: int,
    capture_root: Path,
    product_digest: str,
    prior_decision: dict[str, Any] | None,
) -> dict[str, Any]:
    errors: list[str] = []
    if not _digest(product_digest):
        errors.append("controller product digest is invalid")
    if milestone == 1:
        candidate = _evaluate_m1(capture_root, scale, product_digest, errors)
    else:
        candidate = _evaluate_distributed(
            milestone,
            capture_root,
            scale,
            product_digest,
            prior_decision,
            errors,
        )
    prior_digest = prior_decision.get("decision_digest") if prior_decision else None
    decision: dict[str, Any] = {
        "schema_version": "vpro-milestone-admission-decision-v1",
        "milestone": milestone,
        "scale": scale,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "product_digest": product_digest,
        "capture_admission_digest": candidate.get("admission_digest") if candidate else None,
        "prior_decision_digest": prior_digest,
    }
    decision["decision_digest"] = _canonical_digest(decision)
    return decision


def _evaluate_m1(
    capture_root: Path,
    scale: int,
    product_digest: str,
    errors: list[str],
) -> dict[str, Any]:
    try:
        from valkey_scale_lab.evidence import EvidenceValidationError, validate_candidate_admission

        validated = validate_candidate_admission(
            capture_root,
            scale,
            expected_product_digest=product_digest,
        )
    except (OSError, ValueError, EvidenceValidationError) as exc:
        errors.append(f"Milestone 1 evidence admission failed: {exc}")
        return {}
    return dict(validated.admission)


def _evaluate_distributed(
    milestone: int,
    capture_root: Path,
    scale: int,
    product_digest: str,
    prior_decision: dict[str, Any] | None,
    errors: list[str],
) -> dict[str, Any]:
    candidate = _object(capture_root / "admission.json", errors)
    if not candidate:
        return {}
    expected = {
        "schema_version": "vpro-distributed-admission-v1",
        "execution_kind": "REAL_VALKEY_EXACT_SCALE",
        "runtime_backend": "NATIVE_MULTI_ECS",
        "requested_nodes": scale,
        "observed_nodes": scale,
        "status": "PASS",
        "product_digest": product_digest,
    }
    for key, value in expected.items():
        if candidate.get(key) != value:
            errors.append(f"admission.{key} must be {value!r}")
    placement = candidate.get("placement")
    if not isinstance(placement, dict):
        errors.append("admission.placement is required")
    else:
        hosts = placement.get("hosts")
        azs = placement.get("availability_zones")
        if not isinstance(hosts, list) or len(set(hosts)) < 2:
            errors.append("admission placement must prove at least two ECS hosts")
        if not isinstance(azs, list) or len(set(azs)) < 2:
            errors.append("admission placement must prove at least two availability zones")
    offsets = candidate.get("clock_offsets_ms")
    if not isinstance(offsets, dict) or not offsets:
        errors.append("admission.clock_offsets_ms must cover distributed hosts")
    coverage = candidate.get("coverage")
    passed = {
        key
        for key, value in coverage.items()
        if isinstance(coverage, dict) and value == "PASS"
    } if isinstance(coverage, dict) else set()
    if passed != REQUIRED_COVERAGE:
        errors.append(f"admission coverage mismatch: {sorted(REQUIRED_COVERAGE - passed)}")
    cleanup = candidate.get("cleanup")
    if not isinstance(cleanup, dict) or cleanup.get("status") != "PASS" or cleanup.get("residual_owned_resources") != 0:
        errors.append("admission cleanup must prove zero owned residue")
    claimed = candidate.get("admission_digest")
    unsigned = dict(candidate)
    unsigned.pop("admission_digest", None)
    if claimed != _canonical_digest(unsigned):
        errors.append("admission digest is invalid")
    if prior_decision is not None:
        prior_digest = prior_decision.get("decision_digest")
        if candidate.get("promoted_from_admission_digest") != prior_digest:
            errors.append("scale promotion is not bound to the prior admitted rung")
    return candidate


def _object(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"capture admission is unreadable: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append("capture admission must be a JSON object")
        return {}
    return value


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)
