from __future__ import annotations

from dataclasses import dataclass

from .models import Attempt, GoalState, Objective


@dataclass
class FailureHistory:
    attempts: list[Attempt]

    def __init__(self) -> None:
        self.attempts = []

    def equivalent_failed(self, objective: Objective, goal_state: GoalState) -> bool:
        return any(
            attempt.goal_basis == goal_state.basis
            and attempt.objective.equivalence_key == objective.equivalence_key
            for attempt in self.attempts
        )

    def record(
        self,
        *,
        iteration: int,
        objective: Objective,
        goal_state: GoalState,
        outcome: str,
        reason: str,
    ) -> Attempt:
        attempt = Attempt(
            iteration=iteration,
            objective=objective,
            goal_basis=goal_state.basis,
            outcome=outcome,
            reason=reason,
        )
        self.attempts.append(attempt)
        return attempt

    def as_tuple(self) -> tuple[Attempt, ...]:
        return tuple(self.attempts)
