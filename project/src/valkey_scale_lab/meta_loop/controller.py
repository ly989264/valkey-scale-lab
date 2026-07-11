from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from .contracts import ContractError, load_json, sha256_file, validate_control_block
from .runner import ProgramRunner, ProgramRunnerError
from .store import StateStore, StateStoreError


class MetaLoopError(RuntimeError):
    pass


class MetaLoopController:
    """Bounded scheduler around free-form Codex work and executable checks."""

    def __init__(self, project_root: Path, control_path: Path, state_root: Path, workspace_root: Path):
        self.project_root = project_root.resolve()
        self.workspace_root = workspace_root.resolve()
        self.control_path = control_path.resolve()
        self.state_root = state_root.resolve()
        self.store = StateStore(self.state_root)

    def doctor(self) -> dict[str, Any]:
        control = self._control()
        errors: list[str] = []
        if self.store.exists():
            state = self.store.load()
            if state.get("control_digest") != sha256_file(self.control_path):
                errors.append("control block changed after bootstrap; start a new run instead of changing the goal in flight")
            if state.get("harness_digest") != self._harness_digest():
                errors.append("controller or exact-scale evaluator changed after bootstrap; start a new run")
            errors.extend(self.store.verify_event_chain(state))
        return {
            "status": "PASS" if not errors else "FAIL",
            "goal_id": control["goal_id"],
            "objective_count": len(control["objectives"]),
            "errors": errors,
        }

    def bootstrap(self) -> dict[str, Any]:
        control = self._control()
        with self.store.locked():
            if self.store.exists():
                state = self._state()
                return self._status_view(state, control)
            state = {
                "schema_version": "v2",
                "goal_id": control["goal_id"],
                "control_digest": sha256_file(self.control_path),
                "harness_digest": self._harness_digest(),
                "created_at_unix": int(time.time()),
                "iteration": 0,
                "active_work_item": None,
                "last_event_hash": None,
                "events": [],
                "cache": {},
                "objectives": {
                    objective["id"]: {
                        "status": "PENDING",
                        "attempts": 0,
                        "replans": 0,
                        "review_rounds": 0,
                        "added_checks": [],
                        "best_score": -1,
                        "stagnant_attempts": 0,
                        "last_result": None,
                        "completion_reason": None,
                    }
                    for objective in control["objectives"]
                },
            }
            self._event(state, "BOOTSTRAP", {"goal_id": control["goal_id"]})
            self.store.save(state)
            return self._status_view(state, control)

    def status(self) -> dict[str, Any]:
        control = self._control()
        with self.store.locked():
            return self._status_view(self._state(), control)

    def next_work_item(self) -> dict[str, Any]:
        control = self._control()
        policy = control["controller_policy"]
        with self.store.locked():
            state = self._state()
            active = state.get("active_work_item")
            if isinstance(active, dict):
                return active

            while True:
                objective = self._next_ready_objective(state, control)
                if objective is None:
                    if all(item["status"] == "COMPLETE" for item in state["objectives"].values()):
                        return {"type": "DONE", "goal_id": control["goal_id"], "summary": self._compact_summary(state, control)}
                    return {"type": "BLOCKED", "reason": "No objective is ready; inspect blocked dependencies.", "summary": self._compact_summary(state, control)}

                oid = objective["id"]
                progress = state["objectives"][oid]
                if progress["status"] == "PROGRAM_PASS":
                    if not self._program_inputs_current(control, objective, progress):
                        progress["status"] = "PENDING"
                        progress["attempts"] = max(0, progress["attempts"] - 1)
                        progress["last_result"] = {"status": "STALE", "reason": "program inputs changed after PASS"}
                        self._event(state, "PROGRAM_RESULT_STALE", {"objective_id": oid})
                        self.store.save(state)
                        continue
                    if progress["review_rounds"] >= policy["max_review_rounds_per_objective"]:
                        progress["status"] = "COMPLETE"
                        progress["completion_reason"] = "PROGRAM_PASS_AND_REVIEW_BUDGET_EXHAUSTED"
                        self._event(state, "OBJECTIVE_COMPLETE", {"objective_id": oid, "reason": progress["completion_reason"]})
                        self.store.save(state)
                        continue
                    work = self._review_item(objective, progress, "ACCEPTANCE", policy)
                    break

                exhausted = progress["attempts"] >= policy["max_attempts_per_objective"]
                stagnant = progress["stagnant_attempts"] >= policy["stagnation_limit"]
                if exhausted or stagnant:
                    if progress["replans"] >= policy["max_replans_per_objective"]:
                        progress["status"] = "BLOCKED"
                        self._event(state, "OBJECTIVE_BLOCKED", {"objective_id": oid, "reason": "attempt and replan budget exhausted"})
                        self.store.save(state)
                        continue
                    work = self._review_item(objective, progress, "REPLAN", policy)
                    break

                progress["attempts"] += 1
                progress["status"] = "WORKING"
                work = {
                    "type": "WORK",
                    "work_item_id": uuid.uuid4().hex,
                    "objective_id": oid,
                    "title": objective["title"],
                    "attempt": progress["attempts"],
                    "attempts_remaining_after_this": policy["max_attempts_per_objective"] - progress["attempts"],
                    "contract_clauses": objective["clauses"],
                    "context_paths": objective["context_paths"],
                    "last_program_result": self._compact_result(progress["last_result"]),
                    "instruction": "Choose the best implementation approach. Change product code and focused tests; do not edit controller state or weaken checks. Then run evaluate.",
                }
                break

            state["iteration"] += 1
            state["active_work_item"] = work
            self._enforce_context_budget(work, policy)
            self._event(state, "WORK_ISSUED", {"type": work["type"], "objective_id": work["objective_id"], "work_item_id": work["work_item_id"]})
            self.store.save(state)
            return work

    def evaluate_active(self) -> dict[str, Any]:
        control = self._control()
        with self.store.locked():
            state = self._state()
            work = state.get("active_work_item")
            if not isinstance(work, dict) or work.get("type") != "WORK":
                raise MetaLoopError("evaluate requires an active WORK item from next")
            objective = self._objective(control, work["objective_id"])
            progress = state["objectives"][objective["id"]]
            checks = [*control["common_checks"], *objective["checks"], *progress["added_checks"]]
            checks = sorted(enumerate(checks), key=lambda pair: (pair[1]["level"], pair[0]))
            runner = self._runner(control)
            results: list[dict[str, Any]] = []
            for _, check in checks:
                result = runner.run(check, state["cache"])
                results.append(result)
                if result["status"] != "PASS":
                    break

            passed = bool(results) and all(result["status"] == "PASS" for result in results) and len(results) == len(checks)
            highest_level = max((result["level"] for result in results if result["status"] == "PASS"), default=-1)
            failed_count = sum(result["status"] != "PASS" for result in results)
            score = (highest_level + 1) * 100 - failed_count
            if score > progress["best_score"]:
                progress["best_score"] = score
                progress["stagnant_attempts"] = 0
            else:
                progress["stagnant_attempts"] += 1
            report = {
                "status": "PASS" if passed else "FAIL",
                "objective_id": objective["id"],
                "score": score,
                "highest_level_passed": highest_level,
                "checks_run": len(results),
                "checks_total": len(checks),
                "results": results,
            }
            progress["last_result"] = report
            progress["status"] = "PROGRAM_PASS" if passed else "PENDING"
            state["active_work_item"] = None
            self._event(state, "PROGRAM_EVALUATED", {"objective_id": objective["id"], "status": report["status"], "score": score, "failed_check": self._failed_check_id(report)})
            self.store.save(state)
            return self._compact_evaluation(report)

    def submit_review(self, report: dict[str, Any]) -> dict[str, Any]:
        control = self._control()
        with self.store.locked():
            state = self._state()
            work = state.get("active_work_item")
            if not isinstance(work, dict) or work.get("type") not in {"REVIEW_ACCEPTANCE", "REVIEW_REPLAN"}:
                raise MetaLoopError("review requires an active reviewer item from next")
            if report.get("work_item_id") != work["work_item_id"]:
                raise MetaLoopError("review work_item_id does not match the active item")
            objective = self._objective(control, work["objective_id"])
            progress = state["objectives"][objective["id"]]

            if work["type"] == "REVIEW_REPLAN":
                diagnosis = report.get("diagnosis")
                focus = report.get("recommended_focus")
                if not isinstance(diagnosis, str) or not diagnosis.strip() or not isinstance(focus, list) or not focus:
                    raise MetaLoopError("replan review requires a diagnosis and non-empty recommended_focus")
                progress["replans"] += 1
                progress["attempts"] = 0
                progress["stagnant_attempts"] = 0
                progress["best_score"] = -1
                progress["status"] = "PENDING"
                progress["last_result"] = {"status": "REPLAN", "diagnosis": diagnosis, "recommended_focus": focus}
                event = {"objective_id": objective["id"], "decision": "REPLAN"}
            else:
                decision = report.get("decision")
                if decision not in {"NO_GAP", "GAP"}:
                    raise MetaLoopError("acceptance review decision must be NO_GAP or GAP")
                progress["review_rounds"] += 1
                if decision == "NO_GAP":
                    if not self._program_inputs_current(control, objective, progress):
                        progress["review_rounds"] -= 1
                        progress["status"] = "PENDING"
                        progress["attempts"] = max(0, progress["attempts"] - 1)
                        progress["last_result"] = {"status": "STALE", "reason": "program inputs changed after PASS"}
                        state["active_work_item"] = None
                        self._event(state, "PROGRAM_RESULT_STALE", {"objective_id": objective["id"]})
                        self.store.save(state)
                        return {"status": "STALE_PROGRAM_RESULT", "action": "run next, then evaluate again"}
                    progress["status"] = "COMPLETE"
                    progress["completion_reason"] = "PROGRAM_PASS_AND_REVIEW_FOUND_NO_UNCHECKED_GAP"
                    event = {"objective_id": objective["id"], "decision": "NO_GAP"}
                else:
                    check = self._validate_review_gap(report, objective)
                    reproduction = self._runner(control).run(check, state["cache"])
                    if reproduction["status"] != "FAIL":
                        raise MetaLoopError("review gap was not reproduced: its program check already passes")
                    if any(existing["id"] == check["id"] for existing in [*control["common_checks"], *objective["checks"], *progress["added_checks"]]):
                        raise MetaLoopError("review check id is not novel")
                    progress["added_checks"].append(check)
                    progress["attempts"] = 0
                    progress["stagnant_attempts"] = 0
                    progress["best_score"] = -1
                    progress["status"] = "PENDING"
                    progress["last_result"] = {
                        "status": "REVIEW_GAP",
                        "contract_clause": report["contract_clause"],
                        "finding": report.get("finding"),
                        "reproduction": reproduction,
                    }
                    event = {"objective_id": objective["id"], "decision": "GAP", "check_id": check["id"]}

            state["active_work_item"] = None
            self._event(state, "REVIEW_SUBMITTED", event)
            self.store.save(state)
            return self._status_view(state, control)

    def _control(self) -> dict[str, Any]:
        control = load_json(self.control_path)
        validate_control_block(control)
        return control

    def _state(self) -> dict[str, Any]:
        if not self.store.exists():
            raise MetaLoopError("loop is not bootstrapped")
        state = self.store.load()
        if state.get("control_digest") != sha256_file(self.control_path):
            raise MetaLoopError("control block changed after bootstrap; start a new run")
        if state.get("harness_digest") != self._harness_digest():
            raise MetaLoopError("controller or exact-scale evaluator changed after bootstrap; start a new run")
        chain_errors = self.store.verify_event_chain(state)
        if chain_errors:
            raise MetaLoopError("state/event integrity failure: " + "; ".join(chain_errors))
        return state

    def _harness_digest(self) -> str:
        digest = hashlib.sha256()
        paths = sorted(Path(__file__).resolve().parent.glob("*.py"))
        paths.extend(sorted((self.project_root / "scripts").glob("meta_m1_*gate.py")))
        for path in paths:
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def _runner(self, control: dict[str, Any]) -> ProgramRunner:
        return ProgramRunner(
            self.project_root,
            self.workspace_root,
            self.state_root / "logs",
            int(control["controller_policy"]["failure_excerpt_bytes"]),
        )

    def _program_inputs_current(
        self,
        control: dict[str, Any],
        objective: dict[str, Any],
        progress: dict[str, Any],
    ) -> bool:
        report = progress.get("last_result")
        if not isinstance(report, dict) or report.get("status") != "PASS":
            return False
        results = report.get("results")
        if not isinstance(results, list):
            return False
        by_id = {result.get("check_id"): result for result in results if isinstance(result, dict)}
        checks = [*control["common_checks"], *objective["checks"], *progress["added_checks"]]
        runner = self._runner(control)
        return len(results) == len(checks) and all(
            check["id"] in by_id and by_id[check["id"]].get("input_digest") == runner.input_digest(check["inputs"])
            for check in checks
        )

    @staticmethod
    def _objective(control: dict[str, Any], objective_id: str) -> dict[str, Any]:
        for objective in control["objectives"]:
            if objective["id"] == objective_id:
                return objective
        raise MetaLoopError(f"unknown objective: {objective_id}")

    @staticmethod
    def _next_ready_objective(state: dict[str, Any], control: dict[str, Any]) -> dict[str, Any] | None:
        for objective in control["objectives"]:
            progress = state["objectives"][objective["id"]]
            if progress["status"] in {"COMPLETE", "BLOCKED"}:
                continue
            if all(state["objectives"][dep]["status"] == "COMPLETE" for dep in objective["depends_on"]):
                return objective
        return None

    @staticmethod
    def _review_item(objective: dict[str, Any], progress: dict[str, Any], purpose: str, policy: dict[str, Any]) -> dict[str, Any]:
        item_type = f"REVIEW_{purpose}"
        instruction = (
            "Fresh reviewer: inspect the diff and program evidence. Return NO_GAP, or one demonstrated in-scope GAP with a failing level 0-2 program check. Do not broaden the frozen milestone."
            if purpose == "ACCEPTANCE"
            else "Fresh reviewer: diagnose the repeated failure and identify a materially different focus. Do not implement the fix or broaden scope."
        )
        return {
            "type": item_type,
            "work_item_id": uuid.uuid4().hex,
            "objective_id": objective["id"],
            "title": objective["title"],
            "contract_clauses": objective["clauses"],
            "review_round": progress["review_rounds"] + 1,
            "review_rounds_remaining_after_this": max(0, policy["max_review_rounds_per_objective"] - progress["review_rounds"] - 1),
            "last_program_result": MetaLoopController._compact_result(progress["last_result"]),
            "instruction": instruction,
        }

    @staticmethod
    def _validate_review_gap(report: dict[str, Any], objective: dict[str, Any]) -> dict[str, Any]:
        clause = report.get("contract_clause")
        if clause not in objective["clauses"]:
            raise MetaLoopError("review gap must cite one exact frozen contract clause")
        finding = report.get("finding")
        if not isinstance(finding, str) or not finding.strip():
            raise MetaLoopError("review gap requires a concrete finding")
        check = report.get("program_check")
        if not isinstance(check, dict):
            raise MetaLoopError("review gap requires program_check")
        from .contracts import _check_errors

        errors = _check_errors(check, "review.program_check")
        if errors:
            raise MetaLoopError("invalid review program check: " + "; ".join(errors))
        if check["level"] > 2:
            raise MetaLoopError("review-created checks must be level 0-2; real-scale gates stay controller-owned")
        return check

    def _event(self, state: dict[str, Any], kind: str, payload: dict[str, Any]) -> None:
        self.store.append_event(
            state,
            {"schema_version": "v2", "event": kind, "iteration": state["iteration"], "at_unix": int(time.time()), **payload},
        )

    @staticmethod
    def _failed_check_id(report: dict[str, Any]) -> str | None:
        for result in report.get("results", []):
            if result.get("status") == "FAIL":
                return str(result.get("check_id"))
        return None

    @staticmethod
    def _compact_result(result: Any) -> Any:
        if not isinstance(result, dict):
            return result
        if result.get("status") == "REPLAN":
            return result
        if result.get("status") == "STALE":
            return result
        if result.get("status") == "REVIEW_GAP":
            reproduction = result.get("reproduction", {})
            return {
                "status": "REVIEW_GAP",
                "contract_clause": result.get("contract_clause"),
                "finding": result.get("finding"),
                "failed_check": reproduction.get("check_id"),
                "excerpt": reproduction.get("excerpt"),
            }
        return MetaLoopController._compact_evaluation(result)

    @staticmethod
    def _compact_evaluation(report: dict[str, Any]) -> dict[str, Any]:
        failed = next((result for result in report.get("results", []) if result.get("status") == "FAIL"), None)
        return {
            "status": report.get("status"),
            "objective_id": report.get("objective_id"),
            "score": report.get("score"),
            "highest_level_passed": report.get("highest_level_passed"),
            "checks_run": report.get("checks_run"),
            "checks_total": report.get("checks_total"),
            "failed_check": failed,
        }

    @staticmethod
    def _compact_summary(state: dict[str, Any], control: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "id": objective["id"],
                "status": state["objectives"][objective["id"]]["status"],
                "attempts": state["objectives"][objective["id"]]["attempts"],
                "replans": state["objectives"][objective["id"]]["replans"],
                "review_rounds": state["objectives"][objective["id"]]["review_rounds"],
            }
            for objective in control["objectives"]
        ]

    def _status_view(self, state: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
        summary = self._compact_summary(state, control)
        completed = sum(item["status"] == "COMPLETE" for item in summary)
        return {
            "goal_id": control["goal_id"],
            "status": "COMPLETE" if completed == len(summary) else "ACTIVE",
            "progress": {"completed": completed, "total": len(summary)},
            "active_work_item": state.get("active_work_item"),
            "objectives": summary,
        }

    @staticmethod
    def _enforce_context_budget(work: dict[str, Any], policy: dict[str, Any]) -> None:
        size = len(json.dumps(work, ensure_ascii=True).encode())
        if size > policy["max_context_bytes"]:
            raise MetaLoopError(f"work item context is {size} bytes, over {policy['max_context_bytes']} byte budget")
