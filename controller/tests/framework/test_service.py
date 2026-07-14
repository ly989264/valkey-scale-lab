from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from controller import Controller, ControllerError, EnvironmentBlocked, Objective, TerminalStatus


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr)
    return completed.stdout.strip()


class LoopFixture:
    def __init__(self, root: Path, **termination: int):
        self.root = root
        self.project = root / "project"
        self.project.mkdir()
        (self.project / "src").mkdir()
        (self.project / "other").mkdir()
        (self.project / "acceptance").mkdir()
        (self.project / "src/work.txt").write_text("todo\n", encoding="utf-8")
        (self.project / "src/second.txt").write_text("todo\n", encoding="utf-8")
        (self.project / "other/out.txt").write_text("clean\n", encoding="utf-8")
        (self.project / "acceptance/rules.txt").write_text("fixed\n", encoding="utf-8")
        _git(self.project, "init", "-q")
        _git(self.project, "add", "-A")
        _git(
            self.project,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "initial",
        )
        limits = {
            "max_iterations": 5,
            "max_stagnant_iterations": 2,
            "max_environment_retries": 2,
            "max_no_plan_rounds": 2,
            "max_wall_seconds": 60,
        }
        limits.update(termination)
        self.milestone_path = root / "milestone.json"
        self.milestone_path.write_text(
            json.dumps(
                {
                    "schema_version": "controller-milestone-v1",
                    "milestone": {"id": "Synthetic", "title": "Synthetic", "goal": "Finish."},
                    "success_conditions": [
                        {"id": "first", "statement": "First passes.", "evidence_requirement_ids": []},
                        {"id": "second", "statement": "Second passes.", "evidence_requirement_ids": []},
                    ],
                    "evidence_requirements": [],
                    "termination": limits,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.state_path = root / "run/state.json"

    def evaluator(self, events: list[str]):
        def evaluate(milestone, project_root: Path):
            events.append("evaluate")
            first = (project_root / "src/work.txt").read_text().strip() == "done"
            second = (project_root / "src/second.txt").read_text().strip() == "done"
            return {
                "condition_results": [
                    {"id": "first", "status": "PASS" if first else "FAIL", "summary": "first"},
                    {"id": "second", "status": "PASS" if second else "FAIL", "summary": "second"},
                ],
                "evidence_results": [],
            }

        return evaluate

    def controller(self, evaluator, **kwargs):
        return Controller(
            milestone_path=self.milestone_path,
            project_root=self.project,
            allowed_write_paths=("src",),
            protected_paths=("acceptance",),
            evaluator=evaluator,
            state_path=self.state_path,
            **kwargs,
        )


class ControllerLoopTests(unittest.TestCase):
    def fixture(self, **termination: int) -> LoopFixture:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return LoopFixture(Path(temporary.name), **termination)

    def test_evaluate_first_planner_sees_all_gaps_and_each_objective_is_committed(self) -> None:
        fixture = self.fixture()
        events: list[str] = []
        seen_contexts = []

        def planner(context):
            events.append("plan")
            seen_contexts.append(context)
            gap = context.goal_state.gaps[0].id
            path = "src/work.txt" if gap == "first" else "src/second.txt"
            return Objective(gap, f"Fix {gap}", f"fix {gap}", (gap,), (path,))

        def worker(objective, project_root: Path):
            events.append("work")
            (project_root / objective.write_paths[0]).write_text("done\n", encoding="utf-8")
            return {"claimed_status": "SUCCESS"}

        result = fixture.controller(fixture.evaluator(events)).run(planner, worker)
        self.assertEqual(result.status, TerminalStatus.SUCCESS)
        self.assertEqual(events[0:2], ["evaluate", "plan"])
        self.assertEqual({gap.id for gap in seen_contexts[0].goal_state.gaps}, {"first", "second"})
        self.assertEqual(len(result.retained_commits), 2)
        self.assertEqual(len(_git(fixture.project, "log", "--format=%s").splitlines()), 3)
        self.assertEqual(json.loads(fixture.state_path.read_text())["status"], "SUCCESS")

    def test_no_progress_rolls_back_and_equivalent_path_is_not_repeated(self) -> None:
        fixture = self.fixture(max_no_plan_rounds=1, max_stagnant_iterations=3)
        calls = 0

        def planner(context):
            return Objective("same", "Try same", "same strategy", ("first",), ("src/work.txt",))

        def worker(objective, project_root: Path):
            nonlocal calls
            calls += 1
            (project_root / "src/work.txt").write_text("still failing\n", encoding="utf-8")

        result = fixture.controller(fixture.evaluator([])).run(planner, worker)
        self.assertEqual(result.status, TerminalStatus.NO_LEGAL_PLAN)
        self.assertEqual(calls, 1)
        self.assertEqual((fixture.project / "src/work.txt").read_text(), "todo\n")
        self.assertEqual(result.failed_attempts[0].outcome, "NO_PROGRESS")

    def test_regression_and_out_of_scope_changes_roll_back(self) -> None:
        fixture = self.fixture(max_stagnant_iterations=1)
        (fixture.project / "src/work.txt").write_text("done\n", encoding="utf-8")
        _git(fixture.project, "add", "-A")
        _git(
            fixture.project,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "first passes",
        )

        def planner(context):
            return Objective("regress", "Fix second", "replace both", ("second",), ("src",))

        def worker(objective, project_root: Path):
            (project_root / "src/work.txt").write_text("broken\n", encoding="utf-8")
            (project_root / "src/second.txt").write_text("done\n", encoding="utf-8")

        result = fixture.controller(fixture.evaluator([])).run(planner, worker)
        self.assertEqual(result.status, TerminalStatus.STAGNATED)
        self.assertEqual(result.failed_attempts[0].outcome, "REGRESSION")
        self.assertEqual((fixture.project / "src/work.txt").read_text(), "done\n")
        self.assertEqual((fixture.project / "src/second.txt").read_text(), "todo\n")

        other = self.fixture(max_stagnant_iterations=1)

        def narrow_plan(context):
            return Objective("scope", "Fix first", "write one file", ("first",), ("src/work.txt",))

        def broad_worker(objective, project_root: Path):
            (project_root / "src/work.txt").write_text("done\n", encoding="utf-8")
            (project_root / "other/out.txt").write_text("changed\n", encoding="utf-8")

        scoped = other.controller(other.evaluator([])).run(narrow_plan, broad_worker)
        self.assertEqual(scoped.status, TerminalStatus.STAGNATED)
        self.assertEqual(scoped.failed_attempts[0].outcome, "OUT_OF_SCOPE")
        self.assertEqual((other.project / "other/out.txt").read_text(), "clean\n")

    def test_worker_claim_cannot_replace_complete_evaluator_evidence(self) -> None:
        fixture = self.fixture(max_stagnant_iterations=1)

        def planner(context):
            return Objective("claim", "Claim success", "claim", ("first",), ("src/work.txt",))

        def worker(objective, project_root):
            return {"status": "SUCCESS", "all_checks_pass": True}

        result = fixture.controller(fixture.evaluator([])).run(planner, worker)
        self.assertEqual(result.status, TerminalStatus.STAGNATED)
        self.assertFalse(result.goal_state.complete)

    def test_terminal_states_are_explicit(self) -> None:
        blocked = self.fixture(max_environment_retries=1)

        def blocked_evaluator(milestone, project_root):
            return {
                "condition_results": [
                    {"id": "first", "status": "BLOCKED_ENV", "summary": "tool unavailable"},
                    {"id": "second", "status": "BLOCKED_ENV", "summary": "tool unavailable"},
                ],
                "evidence_results": [],
            }

        result = blocked.controller(blocked_evaluator).run(lambda context: None, lambda *args: None)
        self.assertEqual(result.status, TerminalStatus.ENVIRONMENT_BLOCKED)

        no_plan = self.fixture(max_no_plan_rounds=1)
        result = no_plan.controller(no_plan.evaluator([])).run(lambda context: None, lambda *args: None)
        self.assertEqual(result.status, TerminalStatus.NO_LEGAL_PLAN)

        budget = self.fixture(max_iterations=1, max_no_plan_rounds=2)
        result = budget.controller(budget.evaluator([])).run(lambda context: None, lambda *args: None)
        self.assertEqual(result.status, TerminalStatus.BUDGET_EXHAUSTED)

        stagnant = self.fixture(max_stagnant_iterations=1)
        result = stagnant.controller(stagnant.evaluator([])).run(
            lambda context: Objective("idle", "Idle", "idle", ("first",), ("src/work.txt",)),
            lambda objective, root: None,
        )
        self.assertEqual(result.status, TerminalStatus.STAGNATED)

    def test_environment_exception_and_milestone_mutation_are_not_progress(self) -> None:
        fixture = self.fixture(max_environment_retries=1)
        result = fixture.controller(
            lambda milestone, root: (_ for _ in ()).throw(EnvironmentBlocked("missing runtime"))
        ).run(lambda context: None, lambda *args: None)
        self.assertEqual(result.status, TerminalStatus.ENVIRONMENT_BLOCKED)

        mutated = self.fixture()
        controller = mutated.controller(mutated.evaluator([]))

        def worker(objective, project_root):
            (project_root / "src/work.txt").write_text("done\n", encoding="utf-8")
            mutated.milestone_path.write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(ControllerError, "Milestone changed"):
            controller.run(
                lambda context: Objective(
                    "mutate", "Mutate", "mutate milestone", ("first",), ("src/work.txt",)
                ),
                worker,
            )
        self.assertEqual((mutated.project / "src/work.txt").read_text(), "todo\n")

    def test_post_worker_environment_block_rolls_back_before_termination(self) -> None:
        fixture = self.fixture(max_environment_retries=1)
        calls = 0

        def evaluator(milestone, root):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise EnvironmentBlocked("evaluator unavailable after Worker")
            return fixture.evaluator([])(milestone, root)

        result = fixture.controller(evaluator).run(
            lambda context: Objective(
                "first", "Fix first", "write done", ("first",), ("src/work.txt",)
            ),
            lambda objective, root: (root / "src/work.txt").write_text("done\n"),
        )
        self.assertEqual(result.status, TerminalStatus.ENVIRONMENT_BLOCKED)
        self.assertEqual((fixture.project / "src/work.txt").read_text(), "todo\n")
        self.assertEqual(_git(fixture.project, "status", "--porcelain"), "")

    def test_post_worker_unexpected_evaluator_error_rolls_back_before_termination(self) -> None:
        fixture = self.fixture(max_environment_retries=1)
        calls = 0

        def evaluator(milestone, root):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("unexpected evaluator crash")
            return fixture.evaluator([])(milestone, root)

        result = fixture.controller(evaluator).run(
            lambda context: Objective(
                "first", "Fix first", "write done", ("first",), ("src/work.txt",)
            ),
            lambda objective, root: (root / "src/work.txt").write_text("done\n"),
        )
        self.assertEqual(result.status, TerminalStatus.ENVIRONMENT_BLOCKED)
        self.assertIn("unexpected evaluator crash", result.reason)
        self.assertEqual((fixture.project / "src/work.txt").read_text(), "todo\n")
        self.assertEqual(_git(fixture.project, "status", "--porcelain"), "")

    def test_wall_budget_crossed_by_worker_rolls_back_instead_of_succeeding(self) -> None:
        fixture = self.fixture(max_wall_seconds=5)
        now = [0.0]

        def worker(objective, root):
            (root / "src/work.txt").write_text("done\n")
            now[0] = 10.0

        result = fixture.controller(fixture.evaluator([]), clock=lambda: now[0]).run(
            lambda context: Objective(
                "first", "Fix first", "write done", ("first",), ("src/work.txt",)
            ),
            worker,
        )
        self.assertEqual(result.status, TerminalStatus.BUDGET_EXHAUSTED)
        self.assertEqual((fixture.project / "src/work.txt").read_text(), "todo\n")

    def test_actionable_gap_is_planned_even_when_another_gap_is_environment_blocked(self) -> None:
        fixture = self.fixture(max_environment_retries=1)
        planned = []

        def evaluator(milestone, root):
            first = (root / "src/work.txt").read_text().strip() == "done"
            return {
                "condition_results": [
                    {"id": "first", "status": "PASS" if first else "FAIL", "summary": "first"},
                    {"id": "second", "status": "BLOCKED_ENV", "summary": "external tool"},
                ],
                "evidence_results": [],
            }

        result = fixture.controller(evaluator).run(
            lambda context: planned.append(context.goal_state) or Objective(
                "first", "Fix first", "write done", ("first",), ("src/work.txt",)
            ),
            lambda objective, root: (root / "src/work.txt").write_text("done\n"),
        )
        self.assertTrue(planned)
        self.assertEqual(result.status, TerminalStatus.ENVIRONMENT_BLOCKED)


if __name__ == "__main__":
    unittest.main()
