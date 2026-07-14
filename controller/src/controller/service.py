from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from .contracts import load_milestone
from .delta import compare_goal_states
from .evaluation import EnvironmentBlocked, EvaluationError, build_goal_state
from .history import FailureHistory
from .models import GoalState, Milestone, Objective, PlanContext, RunResult, TerminalStatus
from .planner import PlanError, normalize_paths, path_is_covered, path_overlaps_any, validate_objective
from .runner import GitWorkspace
from .store import StateStore


Evaluator = Callable[[Milestone, Path], Mapping[str, Any]]
Planner = Callable[[PlanContext], Optional[Objective]]
Worker = Callable[[Objective, Path], object]


class ControllerError(RuntimeError):
    pass


class Controller:
    """Automatic Milestone loop for one Goal session in one controlled workspace."""

    def __init__(
        self,
        *,
        milestone_path: Path,
        project_root: Path,
        allowed_write_paths: tuple[str, ...],
        evaluator: Evaluator,
        protected_paths: tuple[str, ...] = (),
        state_path: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.milestone_path = Path(milestone_path).resolve()
        self.project_root = Path(project_root).resolve()
        self.milestone = load_milestone(self.milestone_path)
        self._milestone_bytes = self.milestone_path.read_bytes()
        self.allowed_write_paths = normalize_paths(allowed_write_paths)
        self.protected_paths = normalize_paths(protected_paths)
        if not self.allowed_write_paths:
            raise ControllerError("at least one allowed write path is required")
        for allowed in self.allowed_write_paths:
            if path_is_covered(allowed, self.protected_paths):
                raise ControllerError(
                    f"allowed write path overlaps a protected path: {allowed}"
                )
        self._reject_mutable_milestone_path()
        self.evaluator = evaluator
        self.workspace = GitWorkspace(self.project_root)
        self.store = None if state_path is None else StateStore(state_path)
        self.clock = clock
        self.history = FailureHistory()
        self._last_status: dict[str, Any] = {"status": "NOT_STARTED"}

    def run(self, planner: Planner, worker: Worker) -> RunResult:
        self.workspace.ensure_clean()
        started = self.clock()
        termination = self.milestone.termination
        stagnant = 0
        environment_retries = 0
        no_plan_rounds = 0
        retained_commits: list[str] = []
        current_state: GoalState | None = None

        for iteration in range(1, termination.max_iterations + 1):
            if self._remaining_wall(started) <= 0:
                return self._terminal(
                    TerminalStatus.BUDGET_EXHAUSTED,
                    "wall-clock budget exhausted",
                    current_state,
                    retained_commits,
                )
            self._assert_milestone_unchanged()
            try:
                current_state = self._evaluate(iteration)
            except (EnvironmentBlocked, EvaluationError) as exc:
                environment_retries += 1
                self._save_running(
                    iteration=iteration,
                    goal_state=current_state,
                    reason=str(exc),
                    retained_commits=retained_commits,
                )
                if environment_retries >= termination.max_environment_retries:
                    return self._terminal(
                        TerminalStatus.ENVIRONMENT_BLOCKED,
                        str(exc),
                        current_state,
                        retained_commits,
                    )
                continue

            if self._remaining_wall(started) <= 0:
                return self._terminal(
                    TerminalStatus.BUDGET_EXHAUSTED,
                    "wall-clock budget exhausted during evaluation",
                    current_state,
                    retained_commits,
                )

            self._save_running(
                iteration=iteration,
                goal_state=current_state,
                reason="full Milestone evaluation complete",
                retained_commits=retained_commits,
            )
            if current_state.complete:
                return self._terminal(
                    TerminalStatus.SUCCESS,
                    "all success conditions and evidence requirements pass the current full evaluation",
                    current_state,
                    retained_commits,
                )

            actionable_gaps = [
                gap
                for gap in current_state.gaps
                if gap.status.value not in {"BLOCKED_ENV", "ERROR"}
            ]
            if current_state.blocked_ids and not actionable_gaps:
                environment_retries += 1
                if environment_retries >= termination.max_environment_retries:
                    return self._terminal(
                        TerminalStatus.ENVIRONMENT_BLOCKED,
                        "required checks remain blocked by the environment",
                        current_state,
                        retained_commits,
                    )
                continue
            environment_retries = 0

            context = PlanContext(
                goal_state=current_state,
                failed_attempts=self.history.as_tuple(),
                remaining_iterations=termination.max_iterations - iteration + 1,
                remaining_wall_seconds=self._remaining_wall(started),
            )
            objective: Objective | None = None
            plan_reason = "Planner returned no objective"
            try:
                candidate = planner(context)
                if candidate is not None and not isinstance(candidate, Objective):
                    raise PlanError("Planner must return one Objective or None")
                objective = candidate
                if objective is not None:
                    validate_objective(
                        objective,
                        goal_state=current_state,
                        history=self.history,
                        allowed_write_paths=self.allowed_write_paths,
                        protected_paths=self.protected_paths,
                    )
            except (PlanError, ValueError) as exc:
                plan_reason = str(exc)
                if objective is not None:
                    self.history.record(
                        iteration=iteration,
                        objective=objective,
                        goal_state=current_state,
                        outcome="REJECTED_PLAN",
                        reason=plan_reason,
                    )
                objective = None

            if self._remaining_wall(started) <= 0:
                return self._terminal(
                    TerminalStatus.BUDGET_EXHAUSTED,
                    "wall-clock budget exhausted during planning",
                    current_state,
                    retained_commits,
                )

            if objective is None:
                no_plan_rounds += 1
                self._save_running(
                    iteration=iteration,
                    goal_state=current_state,
                    reason=plan_reason,
                    retained_commits=retained_commits,
                )
                if no_plan_rounds >= termination.max_no_plan_rounds:
                    return self._terminal(
                        TerminalStatus.NO_LEGAL_PLAN,
                        plan_reason,
                        current_state,
                        retained_commits,
                    )
                continue
            no_plan_rounds = 0

            checkpoint = self.workspace.checkpoint()
            worker_error: Exception | None = None
            try:
                worker(objective, self.project_root)
            except Exception as exc:  # Worker failure is a failed path, not evaluator evidence.
                worker_error = exc

            if self._remaining_wall(started) <= 0:
                self.workspace.rollback(checkpoint)
                return self._terminal(
                    TerminalStatus.BUDGET_EXHAUSTED,
                    "wall-clock budget exhausted during Worker execution",
                    current_state,
                    retained_commits,
                )

            try:
                self._assert_milestone_unchanged()
            except ControllerError:
                self.workspace.rollback(checkpoint)
                raise

            changes = self.workspace.changed_paths()
            violations = self.workspace.validate_changes(
                changes,
                allowed_write_paths=self.allowed_write_paths,
                objective_write_paths=objective.write_paths,
                protected_paths=self.protected_paths,
            )
            if worker_error is not None or violations:
                self.workspace.rollback(checkpoint)
                if worker_error is not None:
                    outcome = "WORKER_ERROR"
                    reason = f"Worker failed: {worker_error}"
                else:
                    outcome = "OUT_OF_SCOPE"
                    reason = "Worker changed paths outside the objective: " + ", ".join(violations)
                self.history.record(
                    iteration=iteration,
                    objective=objective,
                    goal_state=current_state,
                    outcome=outcome,
                    reason=reason,
                )
                stagnant += 1
                if stagnant >= termination.max_stagnant_iterations:
                    return self._terminal(
                        TerminalStatus.STAGNATED,
                        reason,
                        current_state,
                        retained_commits,
                    )
                continue

            try:
                candidate_state = self._evaluate(iteration)
            except (EnvironmentBlocked, EvaluationError) as exc:
                self.workspace.rollback(checkpoint)
                environment_retries += 1
                if environment_retries >= termination.max_environment_retries:
                    return self._terminal(
                        TerminalStatus.ENVIRONMENT_BLOCKED,
                        str(exc),
                        current_state,
                        retained_commits,
                    )
                continue
            if self._remaining_wall(started) <= 0:
                self.workspace.rollback(checkpoint)
                return self._terminal(
                    TerminalStatus.BUDGET_EXHAUSTED,
                    "wall-clock budget exhausted during post-Worker evaluation",
                    current_state,
                    retained_commits,
                )
            delta = compare_goal_states(current_state, candidate_state)
            if delta.retain:
                commit = self.workspace.retain(objective.id)
                if commit is not None:
                    retained_commits.append(commit)
                stagnant = 0
                current_state = candidate_state
                if current_state.complete:
                    return self._terminal(
                        TerminalStatus.SUCCESS,
                        "the current code passes the full independent Milestone evaluation",
                        current_state,
                        retained_commits,
                    )
                continue

            self.workspace.rollback(checkpoint)
            if delta.regressed:
                outcome = "REGRESSION"
                reason = "previously passing checks regressed: " + ", ".join(delta.regressed)
            elif delta.newly_blocked:
                outcome = "ENVIRONMENT_REGRESSION"
                reason = "the candidate introduced blocked checks: " + ", ".join(delta.newly_blocked)
            else:
                outcome = "NO_PROGRESS"
                reason = "the full evaluation found no new passing condition or evidence"
            self.history.record(
                iteration=iteration,
                objective=objective,
                goal_state=current_state,
                outcome=outcome,
                reason=reason,
            )
            stagnant += 1
            if stagnant >= termination.max_stagnant_iterations:
                return self._terminal(
                    TerminalStatus.STAGNATED,
                    reason,
                    current_state,
                    retained_commits,
                )

        return self._terminal(
            TerminalStatus.BUDGET_EXHAUSTED,
            "iteration budget exhausted",
            current_state,
            retained_commits,
        )

    def status(self) -> dict[str, Any]:
        if self.store is not None and self.store.path.exists():
            return self.store.load()
        return dict(self._last_status)

    def _evaluate(self, iteration: int) -> GoalState:
        self._assert_milestone_unchanged()
        try:
            raw = self.evaluator(self.milestone, self.project_root)
        except (EnvironmentBlocked, EvaluationError):
            raise
        except Exception as exc:
            raise EvaluationError(f"evaluator failed: {exc}") from exc
        return build_goal_state(self.milestone, raw, iteration=iteration)

    def _remaining_wall(self, started: float) -> float:
        return max(0.0, self.milestone.termination.max_wall_seconds - (self.clock() - started))

    def _assert_milestone_unchanged(self) -> None:
        try:
            current = self.milestone_path.read_bytes()
        except OSError as exc:
            raise ControllerError(f"Milestone became unavailable during the run: {exc}") from exc
        if current != self._milestone_bytes:
            raise ControllerError("Milestone changed during the run")

    def _reject_mutable_milestone_path(self) -> None:
        try:
            relative = self.milestone_path.relative_to(self.project_root).as_posix()
        except ValueError:
            return
        if path_is_covered(relative, self.allowed_write_paths):
            raise ControllerError("Milestone must be outside Worker write paths")

    def _save_running(
        self,
        *,
        iteration: int,
        goal_state: GoalState | None,
        reason: str,
        retained_commits: list[str],
    ) -> None:
        value = {
            "status": "RUNNING",
            "reason": reason,
            "iteration": iteration,
            "goal_state": None if goal_state is None else goal_state.as_dict(),
            "failed_attempts": [item.as_dict() for item in self.history.attempts],
            "retained_commits": list(retained_commits),
        }
        self._write_status(value)

    def _terminal(
        self,
        status: TerminalStatus,
        reason: str,
        goal_state: GoalState | None,
        retained_commits: list[str],
    ) -> RunResult:
        result = RunResult(
            milestone_id=self.milestone.id,
            status=status,
            reason=reason,
            goal_state=goal_state,
            failed_attempts=self.history.as_tuple(),
            retained_commits=tuple(retained_commits),
        )
        self._write_status(result.as_dict())
        return result

    def _write_status(self, value: dict[str, Any]) -> None:
        self._last_status = value
        if self.store is not None:
            self.store.save(value)
