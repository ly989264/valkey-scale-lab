from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from .gap_graph import ConditionEvaluation, EvaluatorFact, GoalState
from .integrity import canonical_digest
from .models import MilestoneContract
from .runner import EvaluatorRun


STATUS_PRIORITY = {
    "PASS": 0,
    "FAIL": 1,
    "MISSING": 2,
    "STALE": 3,
    "BLOCKED_ENV": 4,
    "ERROR": 5,
}


def build_goal_state(
    contract: MilestoneContract,
    runs: Iterable[EvaluatorRun],
    *,
    iteration: int,
    evidence_root: Path,
) -> GoalState:
    by_id = {run.evaluator_id: run for run in runs}
    expected = {evaluator.id for evaluator in contract.evaluators}
    if set(by_id) != expected:
        raise ValueError(f"evaluation run set mismatch: missing={sorted(expected - set(by_id))}")

    evidence_status: dict[str, tuple[str, str | None]] = {}
    for requirement in contract.evidence_requirements:
        observations = []
        for evaluator_id in requirement.admission_evaluator_ids:
            run = by_id[evaluator_id]
            item = next(
                value
                for value in run.report["evidence_results"]
                if value["requirement_id"] == requirement.id
            )
            artifact_digest = None
            if item["status"] == "PASS":
                artifact = next(
                    value
                    for value in run.evidence_artifacts
                    if value["requirement_id"] == requirement.id
                )
                artifact_digest = artifact["sha256"]
            observations.append((item["status"], artifact_digest))
        status = max((item[0] for item in observations), key=lambda item: _evidence_priority(item))
        artifact_digests = sorted(item[1] for item in observations if item[1] is not None)
        if status == "PASS" and len(set(artifact_digests)) != 1:
            status = "UNTRUSTED"
        evidence_status[requirement.id] = (status, artifact_digests[0] if artifact_digests else None)

    evaluations: list[ConditionEvaluation] = []
    for condition in contract.success_conditions:
        result_statuses: list[str] = []
        report_digests: list[str] = []
        for evaluator_id in condition.evaluator_ids:
            run = by_id[evaluator_id]
            result = next(
                value
                for value in run.report["condition_results"]
                if value["condition_id"] == condition.id
            )
            result_statuses.append(result["status"])
            report_digests.append(
                canonical_digest(
                    {
                        "evaluator_id": run.evaluator_id,
                        "input_digest": run.input_digest,
                        "condition_id": condition.id,
                        "status": result["status"],
                    }
                )
            )
        requirement_digests: list[str] = []
        for requirement_id in condition.evidence_requirement_ids:
            status, digest = evidence_status[requirement_id]
            result_statuses.append("PASS" if status == "PASS" else "STALE" if status == "STALE" else "MISSING")
            if digest is not None:
                requirement_digests.append(digest)
        status = max(result_statuses, key=lambda item: STATUS_PRIORITY[item])
        evaluations.append(
            ConditionEvaluation(
                condition_id=condition.id,
                status=status,
                evaluator_ids=condition.evaluator_ids,
                evidence_digests=tuple(sorted((*report_digests, *requirement_digests))),
                trusted=True,
                current=status != "STALE",
                required=condition.required,
            )
        )

    facts: list[EvaluatorFact] = []
    for run in by_id.values():
        for fact in run.report["facts"]:
            facts.append(
                EvaluatorFact(
                    evaluator_id=run.evaluator_id,
                    relation=fact["relation"],
                    source_condition_id=fact["source_condition_id"],
                    target_condition_id=fact["target_condition_id"],
                    evidence_digest=canonical_digest(
                        {
                            "evaluator_id": run.evaluator_id,
                            "input_digest": run.input_digest,
                            "relation": fact["relation"],
                            "source_condition_id": fact["source_condition_id"],
                            "target_condition_id": fact["target_condition_id"],
                        }
                    ),
                    trusted=True,
                    current=True,
                )
            )
    return GoalState(iteration=iteration, evaluations=tuple(evaluations), evaluator_facts=tuple(facts))


def goal_state_to_dict(state: GoalState) -> dict[str, Any]:
    return {
        "iteration": state.iteration,
        "state_digest": state.state_digest,
        "evidence_basis_digest": state.evidence_basis_digest,
        "completion_eligible": all(item.is_proven_pass for item in state.evaluations if item.required),
        "evaluations": [item.__dict__ for item in state.evaluations],
        "evaluator_facts": [item.__dict__ for item in state.evaluator_facts],
    }


def goal_state_from_dict(value: Mapping[str, Any]) -> GoalState:
    state = GoalState(
        iteration=int(value["iteration"]),
        evaluations=tuple(ConditionEvaluation(**item) for item in value["evaluations"]),
        evaluator_facts=tuple(EvaluatorFact(**item) for item in value["evaluator_facts"]),
    )
    if value.get("state_digest") != state.state_digest:
        raise ValueError("stored Goal State digest mismatch")
    return state


def _evidence_priority(status: str) -> int:
    return {
        "PASS": 0,
        "MISSING": 1,
        "STALE": 2,
        "UNTRUSTED": 3,
        "SUBSTITUTED": 4,
        "ERROR": 5,
    }[status]
