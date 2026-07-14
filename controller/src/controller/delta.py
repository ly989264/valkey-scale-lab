from __future__ import annotations

from dataclasses import dataclass

from .models import GoalState


@dataclass(frozen=True)
class GoalDelta:
    newly_passed: tuple[str, ...]
    regressed: tuple[str, ...]
    newly_blocked: tuple[str, ...]

    @property
    def retain(self) -> bool:
        return bool(self.newly_passed) and not self.regressed and not self.newly_blocked


def compare_goal_states(before: GoalState, after: GoalState) -> GoalDelta:
    before_ids = {
        *(f"condition:{item.id}" for item in before.condition_results),
        *(f"evidence:{item.id}" for item in before.evidence_results),
    }
    after_ids = {
        *(f"condition:{item.id}" for item in after.condition_results),
        *(f"evidence:{item.id}" for item in after.evidence_results),
    }
    if before_ids != after_ids:
        raise ValueError("goal states must cover the same immutable milestone")
    return GoalDelta(
        newly_passed=tuple(sorted(after.passed_ids - before.passed_ids)),
        regressed=tuple(sorted(before.passed_ids - after.passed_ids)),
        newly_blocked=tuple(sorted(after.blocked_ids - before.blocked_ids)),
    )
