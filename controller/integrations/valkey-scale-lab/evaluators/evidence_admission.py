#!/usr/bin/env python3
"""Independently admit complete exact-scale evidence without product imports."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from _common import (
    EvaluationError,
    environment_bindings,
    load_json,
    safe_file,
    write_result,
)
from _evidence_contract import validate_exact_evidence
from _prerequisite import load_completion


def _definition_for_requirement(
    product_root: Path,
    requirement: Mapping[str, Any],
    errors: list[str],
) -> dict[str, Any] | None:
    parameters = requirement.get("parameters")
    relative = parameters.get("definition") if isinstance(parameters, Mapping) else None
    path = safe_file(product_root, relative)
    if path is None:
        errors.append(
            "real evidence requirement has no sealed, supported scenario definition"
        )
        return None
    try:
        value = load_json(path)
    except EvaluationError as exc:
        errors.append(str(exc))
        return None
    if value.get("schema_version") != "gate-scenario-v3":
        errors.append("scenario definition uses an unsupported schema")
        return None
    return value


def _evaluate_requirement(
    *,
    requirement: dict[str, Any],
    requirement_by_id: dict[str, dict[str, Any]],
    evidence_root: Path,
    product_root: Path,
    candidate_schema: dict[str, Any],
    prerequisites: Sequence[dict[str, Any]],
    controller_run_id: str,
    product_digest: str,
    now_unix: int,
    max_age_seconds: int,
) -> dict[str, Any]:
    source_id = requirement["id"]
    requirement_id = f"evidence.{source_id}"
    artifact = f"{source_id}/admission.json"
    root = (evidence_root / source_id).resolve()
    errors: list[str] = []
    candidate_path = safe_file(evidence_root, artifact)
    candidate: dict[str, Any] = {}
    missing = candidate_path is None
    if missing:
        errors.append("candidate admission is missing or unsafe")
    else:
        try:
            candidate = load_json(candidate_path)
        except EvaluationError as exc:
            errors.append(str(exc))
    parameters = requirement.get("parameters")
    scale = parameters.get("nodes") if isinstance(parameters, Mapping) else None
    if not isinstance(scale, int) or isinstance(scale, bool):
        errors.append("real evidence requirement has no exact node count")
    definition = _definition_for_requirement(product_root, requirement, errors)
    if isinstance(scale, int) and not isinstance(scale, bool) and definition is not None and candidate:
        errors.extend(
            validate_exact_evidence(
                root=root,
                candidate=candidate,
                definition=definition,
                candidate_schema=candidate_schema,
                scale=scale,
                invocation_run_id=controller_run_id,
                product_digest=product_digest,
            )
        )
    serialized = json.dumps(candidate, sort_keys=True).lower()
    if any(marker in serialized for marker in ("fixture", "dry-run", "dry_run", "simulated")):
        errors.append("fixture, dry-run, or simulated evidence is forbidden")
    ended_ms = candidate.get("run_ended_unix_ms")
    captured_at = ended_ms // 1000 if isinstance(ended_ms, int) else 0
    if captured_at > now_unix + 60 or now_unix - captured_at > max_age_seconds:
        errors.append("admission evidence is stale")

    promotion_source_id = requirement.get("promotion_source_id")
    promotion = candidate.get("promoted_from_admission_digest")
    if promotion_source_id is not None:
        if promotion_source_id not in requirement_by_id:
            errors.append("real evidence promotion source is unknown")
        else:
            prior_path = safe_file(
                evidence_root, f"{promotion_source_id}/admission.json"
            )
            try:
                prior = load_json(prior_path) if prior_path is not None else {}
            except EvaluationError:
                prior = {}
            if promotion != prior.get("admission_digest"):
                errors.append(
                    "promotion does not bind the admitted source requirement"
                )
    elif prerequisites:
        if len(prerequisites) != 1:
            errors.append("cross-milestone promotion chain is ambiguous")
        elif promotion != prerequisites[0].get("final_admission_digest"):
            errors.append(
                "first real evidence requirement does not bind the sealed prerequisite admission"
            )
    elif promotion is not None:
        errors.append(
            "first real evidence requirement must not claim an unrequested promotion"
        )

    status = "PASS"
    if errors:
        status = (
            "MISSING"
            if missing
            else "STALE"
            if any("stale" in error for error in errors)
            else "UNTRUSTED"
        )
    claimed = candidate.get("admission_digest")
    return {
        "requirement_id": requirement_id,
        "status": status,
        "artifact": artifact if not missing else "",
        "capture_class": "REAL",
        "provenance": (
            {
                "admission_digest": claimed,
                "capture_digest": candidate.get("capture_digest"),
                "provenance_digest": candidate.get("provenance", {}).get("digest")
                if isinstance(candidate.get("provenance"), Mapping)
                else None,
            }
            if not errors
            else {"errors": errors}
        ),
        "captured_at_unix": captured_at,
        "run_id": controller_run_id,
        "product_digest": product_digest,
        "substituted": False,
    }


def evaluate(
    *,
    milestone_path: Path,
    evidence_root: Path,
    product_root: Path,
    candidate_schema_path: Path,
    prerequisite_paths: Sequence[Path],
    run_id: str,
    product_digest: str,
    now_unix: int | None = None,
    max_age_seconds: int = 86400,
) -> list[dict[str, Any]]:
    milestone = load_json(milestone_path)
    candidate_schema = load_json(candidate_schema_path)
    if milestone.get("schema_version") != "valkey-milestone-v2":
        raise EvaluationError("unsupported milestone schema")
    requirements = milestone.get("real_evidence_requirements")
    if not isinstance(requirements, list):
        raise EvaluationError(
            "milestone real_evidence_requirements must be an array"
        )
    requirement_by_id = {
        requirement.get("id"): requirement
        for requirement in requirements
        if isinstance(requirement, dict)
    }
    if len(requirement_by_id) != len(requirements) or any(
        not isinstance(key, str) for key in requirement_by_id
    ):
        raise EvaluationError(
            "milestone real evidence requirement ids must be unique strings"
        )
    prerequisite_ids = milestone.get("prerequisite_milestone_ids")
    if not isinstance(prerequisite_ids, list) or len(prerequisite_ids) != len(prerequisite_paths):
        raise EvaluationError("sealed prerequisite inputs do not match the milestone")
    prerequisites = [
        load_completion(Path(path), prerequisite_id)
        for prerequisite_id, path in zip(prerequisite_ids, prerequisite_paths)
    ]
    current = int(time.time()) if now_unix is None else now_unix
    return [
        _evaluate_requirement(
            requirement=requirement,
            requirement_by_id=requirement_by_id,
            evidence_root=Path(evidence_root).resolve(),
            product_root=Path(product_root).resolve(),
            candidate_schema=candidate_schema,
            prerequisites=prerequisites,
            controller_run_id=run_id,
            product_digest=product_digest,
            now_unix=current,
            max_age_seconds=max_age_seconds,
        )
        for requirement in requirements
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--milestone", type=Path, required=True)
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--candidate-schema", type=Path, required=True)
    parser.add_argument("--prerequisite", action="append", type=Path, default=[])
    return parser


def main() -> int:
    args = _parser().parse_args()
    evaluator_id, run_id, product_digest, input_digest, result_path, evidence_root = (
        environment_bindings()
    )
    evidence = evaluate(
        milestone_path=args.milestone,
        evidence_root=evidence_root,
        product_root=args.product_root,
        candidate_schema_path=args.candidate_schema,
        prerequisite_paths=args.prerequisite,
        run_id=run_id,
        product_digest=product_digest,
    )
    return write_result(
        evaluator_id=evaluator_id,
        run_id=run_id,
        product_digest=product_digest,
        input_digest=input_digest,
        result_path=result_path,
        condition_results=[],
        evidence_results=evidence,
    )


if __name__ == "__main__":
    raise SystemExit(main())
