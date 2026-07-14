from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import CheckResult, CheckStatus, Gap, GoalState, Milestone


class EvaluationError(RuntimeError):
    pass


class EnvironmentBlocked(EvaluationError):
    pass


def build_goal_state(milestone: Milestone, raw: Any, *, iteration: int) -> GoalState:
    """Validate one complete evaluator result and derive the complete gap list."""

    if not isinstance(raw, Mapping):
        raise EvaluationError("evaluator result must be an object")
    allowed = {"condition_results", "evidence_results"}
    if set(raw) - allowed:
        raise EvaluationError(f"unknown evaluator result fields: {sorted(set(raw) - allowed)}")
    conditions = _results(raw.get("condition_results"), "condition_results")
    evidence = _results(
        raw.get("evidence_results"), "evidence_results", require_artifact=True
    )

    expected_conditions = {item.id for item in milestone.success_conditions}
    expected_evidence = {item.id for item in milestone.evidence_requirements}
    _require_exact_ids(conditions, expected_conditions, "condition")
    _require_exact_ids(evidence, expected_evidence, "evidence")

    condition_by_id = {item.id: item for item in conditions}
    evidence_by_id = {item.id: item for item in evidence}
    gaps: list[Gap] = []
    for definition in milestone.success_conditions:
        result = condition_by_id[definition.id]
        if result.status is not CheckStatus.PASS:
            gaps.append(
                Gap(definition.id, "condition", definition.statement, result.status, result.summary)
            )
    for definition in milestone.evidence_requirements:
        result = evidence_by_id[definition.id]
        if result.status is not CheckStatus.PASS:
            gaps.append(
                Gap(definition.id, "evidence", definition.statement, result.status, result.summary)
            )

    # A condition linked to missing evidence cannot be complete even if its
    # functional check passes. The evidence gap remains explicit for Planner.
    for definition in milestone.success_conditions:
        if condition_by_id[definition.id].status is not CheckStatus.PASS:
            continue
        missing = [
            requirement_id
            for requirement_id in definition.evidence_requirement_ids
            if evidence_by_id[requirement_id].status is not CheckStatus.PASS
        ]
        if missing:
            result = condition_by_id[definition.id]
            gaps.append(
                Gap(
                    definition.id,
                    "condition",
                    definition.statement,
                    CheckStatus.MISSING,
                    "required evidence is not accepted: " + ", ".join(sorted(missing)),
                )
            )
            condition_by_id[definition.id] = CheckResult(
                id=result.id,
                status=CheckStatus.MISSING,
                summary="required evidence is not accepted: " + ", ".join(sorted(missing)),
            )

    return GoalState(
        iteration=iteration,
        condition_results=tuple(condition_by_id[item.id] for item in milestone.success_conditions),
        evidence_results=tuple(evidence_by_id[item.id] for item in milestone.evidence_requirements),
        gaps=tuple(gaps),
    )


def _results(
    raw: Any, label: str, *, require_artifact: bool = False
) -> tuple[CheckResult, ...]:
    if not isinstance(raw, list):
        raise EvaluationError(f"{label} must be an array")
    values: list[CheckResult] = []
    for index, item in enumerate(raw):
        location = f"{label}[{index}]"
        if not isinstance(item, Mapping):
            raise EvaluationError(f"{location} must be an object")
        required = {"id", "status", "summary"}
        optional = {"artifact", "provenance"}
        unknown = set(item) - required - optional
        missing = required - set(item)
        if unknown or missing:
            raise EvaluationError(
                f"{location} fields differ: missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        identifier = item["id"]
        summary = item["summary"]
        if not isinstance(identifier, str) or not identifier:
            raise EvaluationError(f"{location}.id must be nonempty text")
        if not isinstance(summary, str) or not summary:
            raise EvaluationError(f"{location}.summary must be nonempty text")
        try:
            status = CheckStatus(item["status"])
        except (TypeError, ValueError) as exc:
            raise EvaluationError(f"{location}.status is invalid") from exc
        artifact = item.get("artifact")
        provenance = item.get("provenance", {})
        if artifact is not None and not isinstance(artifact, str):
            raise EvaluationError(f"{location}.artifact must be text")
        if not isinstance(provenance, Mapping):
            raise EvaluationError(f"{location}.provenance must be an object")
        if require_artifact and status is CheckStatus.PASS and (
            not artifact or not provenance
        ):
            status = CheckStatus.UNTRUSTED
            summary = "PASS evidence requires a nonempty artifact and provenance"
        values.append(CheckResult(identifier, status, summary, artifact, dict(provenance)))
    return tuple(values)


def _require_exact_ids(
    results: tuple[CheckResult, ...], expected: set[str], label: str
) -> None:
    actual = [item.id for item in results]
    if len(actual) != len(set(actual)):
        raise EvaluationError(f"duplicate {label} result id")
    if set(actual) != expected:
        raise EvaluationError(
            f"{label} result set mismatch: missing={sorted(expected - set(actual))}, "
            f"unknown={sorted(set(actual) - expected)}"
        )
