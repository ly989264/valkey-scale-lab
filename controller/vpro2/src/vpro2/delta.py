from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .gap_graph import GapGraph, GoalState


class DeltaKind(str, Enum):
    MATERIAL_PROGRESS = "MATERIAL_PROGRESS"
    REGRESSION = "REGRESSION"
    INFORMATION_GAIN = "INFORMATION_GAIN"
    NO_PROGRESS = "NO_PROGRESS"


@dataclass(frozen=True)
class GoalDelta:
    """Evaluator-grounded difference between two complete goal evaluations."""

    kind: DeltaKind
    newly_proven_condition_ids: tuple[str, ...]
    regressed_condition_ids: tuple[str, ...]
    information_changed: bool
    before_gap_digest: str
    after_gap_digest: str

    @property
    def is_material_progress(self) -> bool:
        return self.kind is DeltaKind.MATERIAL_PROGRESS

    @property
    def should_retain_work(self) -> bool:
        return self.kind is DeltaKind.MATERIAL_PROGRESS

    @classmethod
    def between(cls, before: GoalState, after: GoalState) -> "GoalDelta":
        return compare_goal_states(before, after)


def compare_goal_states(before: GoalState, after: GoalState) -> GoalDelta:
    before_by_id = {item.condition_id: item for item in before.evaluations}
    after_by_id = {item.condition_id: item for item in after.evaluations}
    if set(before_by_id) != set(after_by_id):
        raise ValueError("goal states must evaluate the same immutable success conditions")

    before_proven = {
        condition_id for condition_id, evaluation in before_by_id.items() if evaluation.is_proven_pass
    }
    after_proven = {
        condition_id for condition_id, evaluation in after_by_id.items() if evaluation.is_proven_pass
    }
    newly_proven = tuple(sorted(after_proven - before_proven))
    regressed = tuple(sorted(before_proven - after_proven))
    before_graph = GapGraph.from_goal_state(before)
    after_graph = GapGraph.from_goal_state(after)
    before_knowledge = _trusted_knowledge_entries(before)
    after_knowledge = _trusted_knowledge_entries(after)
    information_changed = bool(after_knowledge - before_knowledge)

    # A regression dominates simultaneous local gains. The controller must not
    # retain a patch that advances one condition by invalidating another.
    if regressed:
        kind = DeltaKind.REGRESSION
    elif newly_proven:
        kind = DeltaKind.MATERIAL_PROGRESS
    elif information_changed:
        kind = DeltaKind.INFORMATION_GAIN
    else:
        kind = DeltaKind.NO_PROGRESS
    return GoalDelta(
        kind=kind,
        newly_proven_condition_ids=newly_proven,
        regressed_condition_ids=regressed,
        information_changed=information_changed,
        before_gap_digest=before_graph.graph_digest,
        after_gap_digest=after_graph.graph_digest,
    )


def _trusted_knowledge_entries(state: GoalState) -> set[tuple[object, ...]]:
    entries = {
        (
            "condition",
            item.condition_id,
            item.status,
            item.evaluator_ids,
            item.evidence_digests,
        )
        for item in state.evaluations
        if item.trusted and item.current and item.evaluator_ids and item.evidence_digests
    }
    entries.update(
        (
            "fact",
            fact.evaluator_id,
            fact.relation,
            fact.source_condition_id,
            fact.target_condition_id,
            fact.evidence_digest,
        )
        for fact in state.evaluator_facts
        if fact.trusted and fact.current
    )
    return entries
