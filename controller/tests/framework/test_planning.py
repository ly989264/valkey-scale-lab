from __future__ import annotations

import unittest

from controller.evaluation import build_goal_state
from controller.history import FailureHistory
from controller.models import Objective
from controller.planner import PlanError, validate_objective
from controller.contracts import parse_milestone


class PlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.milestone = parse_milestone(
            {
                "schema_version": "controller-milestone-v1",
                "milestone": {"id": "Plan", "title": "Plan", "goal": "Plan."},
                "success_conditions": [
                    {"id": "a", "statement": "A", "evidence_requirement_ids": []},
                    {"id": "b", "statement": "B", "evidence_requirement_ids": []},
                ],
                "evidence_requirements": [],
                "termination": {
                    "max_iterations": 3,
                    "max_stagnant_iterations": 2,
                    "max_environment_retries": 2,
                    "max_no_plan_rounds": 2,
                    "max_wall_seconds": 30,
                },
            }
        )
        self.state = build_goal_state(
            self.milestone,
            {
                "condition_results": [
                    {"id": "a", "status": "FAIL", "summary": "a"},
                    {"id": "b", "status": "FAIL", "summary": "b"},
                ],
                "evidence_results": [],
            },
            iteration=1,
        )

    def test_objective_must_target_current_gap_and_allowed_unprotected_path(self) -> None:
        history = FailureHistory()
        valid = Objective("a", "Fix A", "edit A", ("a",), ("src/a.py",))
        validate_objective(
            valid,
            goal_state=self.state,
            history=history,
            allowed_write_paths=("src",),
            protected_paths=("src/generated",),
        )
        invalid = (
            Objective("x", "Unknown", "x", ("x",), ("src/a.py",)),
            Objective("o", "Outside", "o", ("a",), ("docs/a.md",)),
            Objective("p", "Protected", "p", ("a",), ("src/generated",)),
        )
        for objective in invalid:
            with self.subTest(objective=objective.id), self.assertRaises(PlanError):
                validate_objective(
                    objective,
                    goal_state=self.state,
                    history=history,
                    allowed_write_paths=("src",),
                    protected_paths=("src/generated",),
                )

    def test_equivalent_failed_path_uses_strategy_targets_paths_and_current_state(self) -> None:
        history = FailureHistory()
        first = Objective("1", "First", " Edit A ", ("a",), ("src/a.py",))
        history.record(
            iteration=1,
            objective=first,
            goal_state=self.state,
            outcome="NO_PROGRESS",
            reason="no change",
        )
        renamed = Objective("2", "Renamed", "edit   a", ("a",), ("src/a.py",))
        with self.assertRaisesRegex(PlanError, "equivalent path"):
            validate_objective(
                renamed,
                goal_state=self.state,
                history=history,
                allowed_write_paths=("src",),
            )
        different = Objective("3", "Different", "rewrite A", ("a",), ("src/a.py",))
        validate_objective(
            different,
            goal_state=self.state,
            history=history,
            allowed_write_paths=("src",),
        )


if __name__ == "__main__":
    unittest.main()
