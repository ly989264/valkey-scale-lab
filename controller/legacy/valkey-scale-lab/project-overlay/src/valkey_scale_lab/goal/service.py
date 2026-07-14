from __future__ import annotations

import hashlib
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from .contracts import ContractError, load_json, parse_check, parse_goal_definition
from .digests import files_digest, product_tree_digest, repair_scope_digest, sha256_file
from .migration import verify_v6_terminal_state
from .models import CheckDefinition, GoalDefinition, KernelManifest, MigrationReceipt, ObjectiveDefinition
from .runner import ProgramRunner
from .scheduler import check_plan, issue, new_progress, ready_objective, work_item
from .store import StateStore


class GoalServiceError(RuntimeError):
    pass


MigrationVerifier = Callable[[Path, Path, Path], MigrationReceipt]


class GoalService:
    """Version-neutral Goal application service over typed definitions and ports."""

    def __init__(
        self,
        *,
        project_root: Path,
        workspace_root: Path,
        control_path: Path,
        state_root: Path,
        schema_version: str,
        kernel_manifest: KernelManifest,
        migration_verifier: MigrationVerifier = verify_v6_terminal_state,
    ):
        self.project_root = project_root.resolve()
        self.workspace_root = workspace_root.resolve()
        self.control_path = control_path.resolve()
        self.state_root = state_root.resolve()
        self.schema_version = schema_version
        self.kernel_manifest = kernel_manifest
        self.migration_verifier = migration_verifier
        self.store = StateStore(self.state_root)

    def doctor(self) -> dict[str, Any]:
        goal = self._goal()
        if not self.store.exists():
            try:
                evaluator_digest = self._evaluator_digest(goal)
            except (OSError, ValueError) as exc:
                return {"status": "FAIL", "goal_id": goal.goal_id, "errors": [str(exc)]}
            return {"status": "READY_FOR_MIGRATION", "goal_id": goal.goal_id, "evaluator_digest": evaluator_digest, "errors": []}
        try:
            self._state()
        except (GoalServiceError, ContractError) as exc:
            return {"status": "FAIL", "goal_id": goal.goal_id, "errors": [str(exc)]}
        return {"status": "PASS", "goal_id": goal.goal_id, "errors": []}

    def migrate_v6(self, source_state_path: Path) -> dict[str, Any]:
        goal = self._goal()
        with self.store.locked():
            if self.store.exists():
                return self._status_view(self._state(), goal)
            receipt = self.migration_verifier(self.project_root, self.workspace_root, source_state_path.resolve())
            state = self._new_state(goal)
            state["migration"] = {"status": "PASS", **asdict(receipt)}
            self._event(state, "MIGRATED_FROM_V6", {"source_state_sha256": receipt.source_state_sha256})
            self.store.save(state)
            return self._status_view(state, goal)

    def status(self) -> dict[str, Any]:
        goal = self._goal()
        with self.store.locked():
            return self._status_view(self._state(), goal)

    def next_work_item(self) -> dict[str, Any]:
        goal = self._goal()
        policy = goal.controller_policy
        with self.store.locked():
            state = self._state()
            active = state.get("active_work_item")
            if isinstance(active, dict):
                return active
            while True:
                objective = ready_objective(goal, state)
                if objective is None:
                    if all(item["status"] == "COMPLETE" for item in state["objectives"].values()):
                        return {"type": "DONE", "goal_id": goal.goal_id, "summary": self._summary(state, goal)}
                    return {"type": "BLOCKED", "reason": "No objective is ready", "summary": self._summary(state, goal)}
                progress = state["objectives"][objective.id]
                if progress["status"] == "EVALUATOR_REPAIR_REQUIRED":
                    if progress["attempts"] >= policy["max_attempts_per_objective"]:
                        progress["status"] = "BLOCKED"
                        self._event(state, "OBJECTIVE_BLOCKED", {"objective_id": objective.id, "reason": "evaluator repair budget exhausted"})
                        self.store.save(state)
                        continue
                    progress["attempts"] += 1
                    return self._issue(state, work_item(
                        "EVALUATOR_REPAIR",
                        objective_id=objective.id,
                        attempt=progress["attempts"],
                        allowed_paths=progress["active_gap"]["allowed_repair_paths"],
                        program_check=progress["active_gap"]["program_check"],
                        instruction="Change only the versioned evaluator and its hermetic tests, then accept the repair.",
                    ), goal)
                if progress["status"] == "REVERIFY":
                    return self._issue(state, work_item("VERIFY", objective_id=objective.id, instruction="Run evaluate without editing files."), goal)
                if progress["status"] == "PROGRAM_PASS":
                    if not self._program_inputs_current(state, goal, objective, progress):
                        progress.update({"status": "PENDING", "last_result": {"status": "STALE"}})
                        self._event(state, "PROGRAM_RESULT_STALE", {"objective_id": objective.id})
                        self.store.save(state)
                        continue
                    if progress["review_rounds"] >= policy["max_review_rounds_per_objective"]:
                        progress.update({"status": "COMPLETE", "completion_reason": "PROGRAM_PASS_AND_REVIEW_BUDGET_EXHAUSTED"})
                        self._event(state, "OBJECTIVE_COMPLETE", {"objective_id": objective.id, "reason": progress["completion_reason"]})
                        self.store.save(state)
                        continue
                    return self._issue(state, self._review_item(objective, progress, "ACCEPTANCE"), goal)
                cached_stagnation = self._last_failure_cached(progress) and progress["stagnant_attempts"] >= 1
                exhausted = progress["attempts"] >= policy["max_attempts_per_objective"]
                stagnant = progress["stagnant_attempts"] >= policy["stagnation_limit"] or cached_stagnation
                if exhausted or stagnant:
                    if progress["replans"] >= policy["max_replans_per_objective"]:
                        progress["status"] = "BLOCKED"
                        self._event(state, "OBJECTIVE_BLOCKED", {"objective_id": objective.id})
                        self.store.save(state)
                        continue
                    return self._issue(state, self._review_item(objective, progress, "REPLAN"), goal)
                progress["attempts"] += 1
                progress["status"] = "WORKING"
                return self._issue(state, work_item(
                    "WORK",
                    objective_id=objective.id,
                    title=objective.title,
                    attempt=progress["attempts"],
                    contract_clauses=list(objective.clauses),
                    context_paths=list(objective.context_paths),
                    last_program_result=self._compact(progress.get("last_result")),
                    instruction="Implement only this objective, then run evaluate.",
                ), goal)

    def evaluate_active(self) -> dict[str, Any]:
        goal = self._goal()
        with self.store.locked():
            state = self._state()
            work = state.get("active_work_item")
            if not isinstance(work, dict) or work.get("type") not in {"WORK", "VERIFY"}:
                raise GoalServiceError("evaluate requires active WORK or VERIFY")
            objective = goal.objective(str(work["objective_id"]))
            progress = state["objectives"][objective.id]
            checks = check_plan(goal, objective, self._added_checks(progress))
            results = self._run_checks(checks, state, goal)
            passed = len(results) == len(checks) and all(result["status"] == "PASS" for result in results)
            report = self._evaluation(objective.id, results, len(checks), passed)
            failed = next((result for result in results if result["status"] == "FAIL"), None)
            if failed is not None:
                fingerprint = hashlib.sha256(str(failed["check_id"]).encode()).hexdigest()
                if fingerprint != progress.get("failure_fingerprint"):
                    progress.update({"failure_fingerprint": fingerprint, "attempts": 1, "replans": 0, "stagnant_attempts": 0, "best_score": report["score"]})
                elif report["score"] > progress["best_score"]:
                    progress.update({"best_score": report["score"], "stagnant_attempts": 0})
                else:
                    progress["stagnant_attempts"] += 1
            else:
                progress.update({"failure_fingerprint": None, "stagnant_attempts": 0, "best_score": report["score"], "active_gap": None})
            progress["last_result"] = report
            progress["status"] = "PROGRAM_PASS" if passed else "PENDING"
            state["active_work_item"] = None
            self._event(state, "PROGRAM_EVALUATED", {"objective_id": objective.id, "status": report["status"]})
            self.store.save(state)
            return self._compact(report)

    def submit_review(self, report: dict[str, Any]) -> dict[str, Any]:
        goal = self._goal()
        with self.store.locked():
            state = self._state()
            work = state.get("active_work_item")
            if not isinstance(work, dict) or work.get("type") not in {"REVIEW_ACCEPTANCE", "REVIEW_REPLAN"}:
                raise GoalServiceError("review requires an active reviewer item")
            if report.get("work_item_id") != work["work_item_id"]:
                raise GoalServiceError("review work_item_id does not match")
            objective = goal.objective(str(work["objective_id"]))
            progress = state["objectives"][objective.id]
            if work["type"] == "REVIEW_REPLAN":
                if not isinstance(report.get("diagnosis"), str) or not report["diagnosis"].strip():
                    raise GoalServiceError("replan requires diagnosis")
                progress.update({"status": "PENDING", "attempts": 0, "replans": progress["replans"] + 1, "last_result": {"status": "REPLAN", "diagnosis": report["diagnosis"]}})
                event = {"objective_id": objective.id, "decision": "REPLAN"}
            else:
                decision = report.get("decision")
                if decision not in {"NO_GAP", "GAP"}:
                    raise GoalServiceError("acceptance decision must be NO_GAP or GAP")
                progress["review_rounds"] += 1
                if decision == "NO_GAP":
                    if not self._program_inputs_current(state, goal, objective, progress):
                        raise GoalServiceError("program inputs changed before review")
                    progress.update({"status": "COMPLETE", "completion_reason": "PROGRAM_PASS_AND_REVIEW_FOUND_NO_GAP"})
                    event = {"objective_id": objective.id, "decision": "NO_GAP"}
                else:
                    gap_kind = report.get("gap_kind")
                    if gap_kind not in {"PRODUCT_GAP", "EVALUATOR_GAP"}:
                        raise GoalServiceError("GAP requires PRODUCT_GAP or EVALUATOR_GAP")
                    check = self._review_check(report, objective, goal)
                    reproduction = self._runner(goal).run(check, state["cache"])
                    if reproduction["status"] != "FAIL":
                        raise GoalServiceError("review gap was not reproduced")
                    if check.id in self._all_check_ids(goal, progress):
                        raise GoalServiceError("review check id is not novel")
                    evaluator_inputs = set(goal.evaluator_paths)
                    if (gap_kind == "EVALUATOR_GAP") != bool(evaluator_inputs.intersection(check.inputs)):
                        raise GoalServiceError("gap classification does not match evaluator coverage")
                    progress["added_checks"].append(check.as_dict())
                    progress["check_anchors"][check.id] = self._review_check_anchor(check, goal)
                    allowed = goal.evaluator_repair_paths
                    progress["active_gap"] = {
                        "kind": gap_kind,
                        "program_check": check.as_dict(),
                        "baseline_product_digest": self._product_digest(goal),
                        "baseline_repair_scope_digest": repair_scope_digest(self.project_root, allowed),
                        "allowed_repair_paths": list(allowed),
                    }
                    progress.update({"status": "EVALUATOR_REPAIR_REQUIRED" if gap_kind == "EVALUATOR_GAP" else "PENDING", "attempts": 0, "replans": 0, "last_result": {"status": "REVIEW_GAP", "reproduction": reproduction}})
                    event = {"objective_id": objective.id, "decision": "GAP", "gap_kind": gap_kind, "check_id": check.id}
            state["active_work_item"] = None
            self._event(state, "REVIEW_SUBMITTED", event)
            self.store.save(state)
            return self._status_view(state, goal)

    def accept_evaluator_repair(self) -> dict[str, Any]:
        goal = self._goal()
        with self.store.locked():
            state = self._state(allow_evaluator_change=True)
            work = state.get("active_work_item")
            if not isinstance(work, dict) or work.get("type") != "EVALUATOR_REPAIR":
                raise GoalServiceError("accept requires active EVALUATOR_REPAIR")
            objective = goal.objective(str(work["objective_id"]))
            progress = state["objectives"][objective.id]
            gap = progress.get("active_gap")
            if not isinstance(gap, dict) or gap.get("kind") != "EVALUATOR_GAP":
                raise GoalServiceError("active evaluator gap is missing")
            if self._product_digest(goal) != gap["baseline_product_digest"]:
                raise GoalServiceError("product inputs changed during evaluator repair")
            allowed = tuple(gap["allowed_repair_paths"])
            if repair_scope_digest(self.project_root, allowed) != gap["baseline_repair_scope_digest"]:
                raise GoalServiceError("files outside evaluator repair scope changed")
            checks = (parse_check(gap["program_check"]), *goal.evaluator_guard_checks)
            results = self._run_checks(checks, state, goal)
            passed = len(results) == len(checks) and all(result["status"] == "PASS" for result in results)
            report = self._evaluation(objective.id, results, len(checks), passed)
            if passed:
                state["evaluator_digest"] = self._evaluator_digest(goal)
                state["active_work_item"] = None
                progress.update({"status": "REVERIFY", "attempts": 0, "active_gap": None, "last_result": {"status": "EVALUATOR_REPAIRED"}})
            else:
                state["active_work_item"] = None
                gap["repair_failures"] = int(gap.get("repair_failures", 0)) + 1
                progress.update({"status": "EVALUATOR_REPAIR_REQUIRED", "last_result": report})
            self._event(state, "EVALUATOR_REPAIR_EVALUATED", {"objective_id": objective.id, "status": report["status"]})
            self.store.save(state)
            return self._compact(report)

    def _goal(self) -> GoalDefinition:
        return parse_goal_definition(load_json(self.control_path), expected_version=self.schema_version)

    def _new_state(self, goal: GoalDefinition) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "goal_id": goal.goal_id,
            "control_digest": sha256_file(self.control_path),
            "kernel_digest": self._kernel_digest(),
            "evaluator_digest": self._evaluator_digest(goal),
            "created_at_unix": int(time.time()),
            "iteration": 0,
            "active_work_item": None,
            "last_event_hash": None,
            "events": [],
            "cache": {},
            "objectives": {objective.id: new_progress() for objective in goal.objectives},
        }

    def _state(self, *, allow_evaluator_change: bool = False) -> dict[str, Any]:
        if not self.store.exists():
            raise GoalServiceError("v7 loop is not migrated from terminal v6")
        state = self.store.load()
        if state.get("schema_version") != self.schema_version:
            raise GoalServiceError("state schema version mismatch")
        if state.get("control_digest") != sha256_file(self.control_path):
            raise GoalServiceError("control block changed after migration")
        if state.get("kernel_digest") != self._kernel_digest():
            raise GoalServiceError("controller kernel changed after migration")
        goal = self._goal()
        evaluator_changed = state.get("evaluator_digest") != self._evaluator_digest(goal)
        if evaluator_changed and not allow_evaluator_change and not self._sealed_evaluator_drift_authorized(state):
            raise GoalServiceError("evaluator changed outside controlled repair")
        errors = self.store.verify(state)
        if errors:
            raise GoalServiceError("state integrity failure: " + "; ".join(errors))
        anchor_errors = self._review_anchor_errors(state, goal)
        if anchor_errors:
            raise GoalServiceError("review check integrity failure: " + "; ".join(anchor_errors))
        return state

    @staticmethod
    def _sealed_evaluator_drift_authorized(state: dict[str, Any]) -> bool:
        active = state.get("active_work_item")
        if isinstance(active, dict) and active.get("type") == "EVALUATOR_REPAIR":
            progress = state.get("objectives", {}).get(active.get("objective_id"), {})
            gap = progress.get("active_gap") if isinstance(progress, dict) else None
            return isinstance(gap, dict) and gap.get("kind") == "EVALUATOR_GAP"
        for progress in state.get("objectives", {}).values():
            if not isinstance(progress, dict) or progress.get("status") not in {"EVALUATOR_REPAIR_REQUIRED", "BLOCKED"}:
                continue
            gap = progress.get("active_gap")
            if isinstance(gap, dict) and gap.get("kind") == "EVALUATOR_GAP" and int(gap.get("repair_failures", 0)) > 0:
                return True
        return False

    def _kernel_digest(self) -> str:
        return files_digest(self.project_root, (self.kernel_manifest.manifest_path, *self.kernel_manifest.paths))

    def _evaluator_digest(self, goal: GoalDefinition) -> str:
        return files_digest(self.project_root, goal.evaluator_paths)

    def _runner(self, goal: GoalDefinition) -> ProgramRunner:
        return ProgramRunner(
            self.project_root,
            self.workspace_root,
            self.state_root / "logs",
            int(goal.controller_policy["failure_excerpt_bytes"]),
            product_roots=goal.product_roots,
            product_excludes=goal.product_excludes,
        )

    def _product_digest(self, goal: GoalDefinition) -> str:
        return product_tree_digest(self.project_root, goal.product_roots, goal.product_excludes)

    def _run_checks(self, checks: tuple[CheckDefinition, ...], state: dict[str, Any], goal: GoalDefinition) -> list[dict[str, Any]]:
        runner = self._runner(goal)
        results: list[dict[str, Any]] = []
        for check in checks:
            result = runner.run(check, state["cache"])
            results.append(result)
            if result["status"] != "PASS":
                break
        return results

    def _issue(self, state: dict[str, Any], work: dict[str, Any], goal: GoalDefinition) -> dict[str, Any]:
        issue(state, work, int(goal.controller_policy["max_context_bytes"]))
        self._event(state, "WORK_ISSUED", {"type": work["type"], "objective_id": work.get("objective_id"), "work_item_id": work["work_item_id"]})
        self.store.save(state)
        return work

    def _event(self, state: dict[str, Any], kind: str, payload: dict[str, Any]) -> None:
        self.store.append_event(state, {"schema_version": self.schema_version, "event": kind, "iteration": state["iteration"], "at_unix": int(time.time()), **payload})

    def _review_item(self, objective: ObjectiveDefinition, progress: dict[str, Any], purpose: str) -> dict[str, Any]:
        return work_item(f"REVIEW_{purpose}", objective_id=objective.id, contract_clauses=list(objective.clauses), review_round=progress["review_rounds"] + 1)

    def _review_check(self, report: dict[str, Any], objective: ObjectiveDefinition, goal: GoalDefinition) -> CheckDefinition:
        if report.get("contract_clause") not in objective.clauses:
            raise GoalServiceError("review gap must cite an exact clause")
        check = parse_check(report.get("program_check"), "review.program_check")
        targets = tuple(value.split("::", 1)[0] for value in check.command[3:] if value.startswith("tests/"))
        if check.level > 2 or check.command[:3] != ("python3", "-m", "pytest") or not targets:
            raise GoalServiceError("review checks must be focused level 0-2 pytest commands")
        if any("../loop_evidence" in value for value in check.inputs):
            raise GoalServiceError("review checks must be hermetic")
        if any(not any(target == raw or target.startswith(raw.rstrip("/") + "/") for raw in check.inputs) for target in targets):
            raise GoalServiceError("review check inputs must cover pytest targets")
        return check

    @staticmethod
    def _review_targets(check: CheckDefinition) -> tuple[str, ...]:
        return tuple(sorted(value.split("::", 1)[0] for value in check.command[3:] if value.startswith("tests/")))

    def _review_check_anchor(self, check: CheckDefinition, goal: GoalDefinition) -> dict[str, Any]:
        targets = self._review_targets(check)
        return {"targets": list(targets), "digest": self._runner(goal).input_digest(targets)}

    def _review_anchor_errors(self, state: dict[str, Any], goal: GoalDefinition) -> list[str]:
        errors: list[str] = []
        runner = self._runner(goal)
        for objective_id, progress in state.get("objectives", {}).items():
            checks = {check.id: check for check in self._added_checks(progress)}
            anchors = progress.get("check_anchors")
            if not isinstance(anchors, dict) or set(anchors) != set(checks):
                errors.append(f"{objective_id} reviewer anchors do not match added checks")
                continue
            for check_id, check in checks.items():
                targets = self._review_targets(check)
                anchor = anchors.get(check_id)
                if not isinstance(anchor, dict) or anchor.get("targets") != list(targets) or anchor.get("digest") != runner.input_digest(targets):
                    errors.append(f"{objective_id}/{check_id} reviewer test content changed")
        return errors

    def _program_inputs_current(self, state: dict[str, Any], goal: GoalDefinition, objective: ObjectiveDefinition, progress: dict[str, Any]) -> bool:
        report = progress.get("last_result")
        if not isinstance(report, dict) or report.get("status") != "PASS":
            return False
        checks = check_plan(goal, objective, self._added_checks(progress))
        results = report.get("results")
        by_id = {result.get("check_id"): result for result in results if isinstance(result, dict)} if isinstance(results, list) else {}
        runner = self._runner(goal)
        return len(by_id) == len(checks) and all(by_id.get(check.id, {}).get("input_digest") == runner.check_input_digest(check) for check in checks)

    @staticmethod
    def _added_checks(progress: dict[str, Any]) -> tuple[CheckDefinition, ...]:
        return tuple(parse_check(raw) for raw in progress.get("added_checks", []))

    @staticmethod
    def _all_check_ids(goal: GoalDefinition, progress: dict[str, Any]) -> set[str]:
        return {check.id for check in (*goal.common_checks, *goal.closure_checks, *goal.evaluator_guard_checks, *(check for objective in goal.objectives for check in objective.checks), *GoalService._added_checks(progress))}

    @staticmethod
    def _evaluation(objective_id: str, results: list[dict[str, Any]], total: int, passed: bool) -> dict[str, Any]:
        highest = max((result["level"] for result in results if result["status"] == "PASS"), default=-1)
        failed_count = sum(result["status"] != "PASS" for result in results)
        return {"status": "PASS" if passed else "FAIL", "objective_id": objective_id, "score": (highest + 1) * 100 - failed_count, "highest_level_passed": highest, "checks_run": len(results), "checks_total": total, "results": results}

    @staticmethod
    def _compact(report: Any) -> Any:
        if not isinstance(report, dict):
            return report
        failed = next((result for result in report.get("results", []) if result.get("status") == "FAIL"), None)
        return {"status": report.get("status"), "objective_id": report.get("objective_id"), "checks_run": report.get("checks_run"), "checks_total": report.get("checks_total"), "failed_check": failed}

    @staticmethod
    def _summary(state: dict[str, Any], goal: GoalDefinition) -> list[dict[str, Any]]:
        return [{"id": objective.id, "status": state["objectives"][objective.id]["status"], "attempts": state["objectives"][objective.id]["attempts"], "review_rounds": state["objectives"][objective.id]["review_rounds"]} for objective in goal.objectives]

    @staticmethod
    def _last_failure_cached(progress: dict[str, Any]) -> bool:
        report = progress.get("last_result")
        return isinstance(report, dict) and any(result.get("status") == "FAIL" and result.get("cached") is True for result in report.get("results", []) if isinstance(result, dict))

    def _status_view(self, state: dict[str, Any], goal: GoalDefinition) -> dict[str, Any]:
        summary = self._summary(state, goal)
        complete = sum(item["status"] == "COMPLETE" for item in summary)
        overall = "BLOCKED" if any(item["status"] == "BLOCKED" for item in summary) else "COMPLETE" if complete == len(summary) else "ACTIVE"
        return {"goal_id": goal.goal_id, "status": overall, "progress": {"completed": complete, "total": len(summary)}, "migration": state.get("migration"), "active_work_item": state.get("active_work_item"), "objectives": summary}
