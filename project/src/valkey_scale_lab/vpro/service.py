from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from .contracts import ContractError, load_bundle, parse_check
from .digests import canonical_json_digest, file_digest, workspace_minus_allowed_digest
from .integrity import FrameworkRelease
from .milestone import execution_readiness
from .models import BundleDefinition, CheckDefinition, GateDefinition, ObjectiveDefinition, ResolvedProfile
from .runner import ProgramRunner, ProgramRunnerError
from .store import StateStore, StateStoreError


class VProServiceError(RuntimeError):
    pass


class VProController:
    """Fixed VPRO v1 state machine over an operator-sealed milestone bundle."""

    STATE_SCHEMA = "vpro-state-v1"

    def __init__(
        self,
        *,
        project_root: Path,
        workspace_root: Path,
        bundle_path: Path,
        profile_id: str,
        state_root: Path,
        release: FrameworkRelease,
        state_seal_key: bytes,
        approval_key: bytes,
        secret_paths: Iterable[Path] = (),
    ):
        self.project_root = project_root.resolve()
        self.workspace_root = workspace_root.resolve()
        self.bundle_path = bundle_path.resolve()
        self.profile_id = profile_id
        self.state_root = state_root.resolve()
        self.release = release
        if not isinstance(state_seal_key, bytes) or len(state_seal_key) < 32:
            raise VProServiceError("controller state seal key must contain at least 32 bytes")
        if not isinstance(approval_key, bytes) or len(approval_key) < 32:
            raise VProServiceError("gate approval key must contain at least 32 bytes")
        self._approval_key = approval_key
        self.secret_paths = tuple(Path(path).resolve() for path in secret_paths)
        if not self.project_root.is_relative_to(self.workspace_root):
            raise VProServiceError("project root must be inside workspace root")
        if _absolute_path_overlap(self.state_root, self.workspace_root):
            raise VProServiceError("state root must be outside the worker workspace")
        if _absolute_path_overlap(self.release.root, self.workspace_root):
            raise VProServiceError("framework root must be outside the worker workspace")
        if self.bundle_path.is_relative_to(self.workspace_root):
            raise VProServiceError("bound bundle must be outside the worker workspace")
        if _absolute_path_overlap(self.state_root, self.release.root) or _absolute_path_overlap(
            self.state_root, self.bundle_path
        ):
            raise VProServiceError("state root must not overlap framework or bundle authority")
        for path in self.secret_paths:
            if not path.is_file() or path.is_symlink():
                raise VProServiceError("HMAC secret paths must be real files")
            if (
                _absolute_path_overlap(path, self.workspace_root)
                or _absolute_path_overlap(path, self.state_root)
                or _absolute_path_overlap(path, self.release.root)
                or path == self.bundle_path
            ):
                raise VProServiceError("HMAC secret paths must not overlap runtime authority roots")
        self.store = StateStore(self.state_root, seal_key=state_seal_key)

    def doctor(self) -> dict[str, Any]:
        bundle, resolved = self._definition()
        if not self.store.exists():
            readiness = execution_readiness(bundle, self.project_root)
            if readiness["status"] != "READY":
                return {
                    "status": "BLOCKED",
                    "milestone_id": bundle.milestone.id,
                    "profile_id": resolved.profile.id,
                    "execution_readiness": readiness,
                    "errors": [self._readiness_error(readiness)],
                }
            return {
                "status": "READY_FOR_BIND",
                "framework_digest": self.release.digest,
                "bundle_digest": file_digest(self.bundle_path),
                "milestone_id": bundle.milestone.id,
                "profile_id": resolved.profile.id,
                "errors": [],
            }
        try:
            state = self._state(bundle, resolved)
        except (ContractError, VProServiceError, StateStoreError, ProgramRunnerError) as exc:
            return {"status": "FAIL", "errors": [str(exc)]}
        return {"status": "PASS", "run_id": state["run_id"], "errors": []}

    def bind(self, *, actor: str) -> dict[str, Any]:
        bundle, resolved = self._definition()
        readiness = execution_readiness(bundle, self.project_root)
        if readiness["status"] != "READY":
            raise VProServiceError(self._readiness_error(readiness))
        plan = self._resolved_plan(bundle, resolved)
        tool_seals = ProgramRunner.seal_tools(
            bundle.integrity.allowed_tools,
            workspace_root=self.workspace_root,
            state_root=self.state_root,
        )
        sandbox_seal = ProgramRunner.seal_sandbox(
            workspace_root=self.workspace_root,
            state_root=self.state_root,
        )
        with self.store.locked():
            if self.store.exists():
                raise VProServiceError("run is already bound")
            unexpected = [
                path
                for path in self.state_root.rglob("*")
                if (path.is_file() or path.is_symlink()) and path.resolve() != self.store.lock_path.resolve()
            ]
            if unexpected:
                raise VProServiceError("bind requires a new empty run root")
            state = {
                "schema_version": self.STATE_SCHEMA,
                "run_id": uuid.uuid4().hex,
                "ownership_token": uuid.uuid4().hex,
                "milestone_id": bundle.milestone.id,
                "bundle_version": bundle.milestone.version,
                "profile_id": resolved.profile.id,
                "completion_claim": resolved.profile.claim,
                "framework_version": self.release.version,
                "framework_digest": self.release.digest,
                "bundle_digest": file_digest(self.bundle_path),
                "resolved_plan_digest": canonical_json_digest(plan),
                "evaluator_digest": self._paths_digest(bundle.integrity.evaluator_paths, bundle),
                "evaluator_generation": 0,
                "acceptance_digest": self._paths_digest(bundle.integrity.authoritative_check_paths, bundle),
                "tool_seals": tool_seals,
                "sandbox_seal": sandbox_seal,
                "toolchain_digest": canonical_json_digest(
                    {"tools": tool_seals, "sandbox": sandbox_seal}
                ),
                "state_seal_key_id": self.store.seal_key_id,
                "approval_key_id": hashlib.sha256(self._approval_key).hexdigest(),
                "created_at_unix": int(time.time()),
                "iteration": 0,
                "active_work_item": None,
                "cache": {},
                "run_counts": {},
                "approvals": {},
                "objectives": {objective.id: _new_progress() for objective in resolved.objectives},
                "gates": {gate.id: _new_gate_progress() for gate in resolved.gates},
                "completion": None,
                "events": [],
                "last_event_hash": None,
            }
            self.store.save_plan(plan)
            self._event(state, "RUN_BOUND", actor, {"profile_id": resolved.profile.id})
            self.store.save(state)
            return self._status_view(state, resolved)

    @staticmethod
    def _readiness_error(readiness: dict[str, Any]) -> str:
        return (
            "milestone execution readiness is BLOCKED: "
            f"missing_authority_paths={readiness.get('missing_authority_paths', [])}, "
            f"missing_tools={readiness.get('missing_tools', [])}"
        )

    def status(self) -> dict[str, Any]:
        bundle, resolved = self._definition()
        with self.store.locked():
            return self._status_view(self._state(bundle, resolved), resolved)

    def audit(self) -> dict[str, Any]:
        bundle, resolved = self._definition()
        with self.store.locked():
            state = self._state(bundle, resolved)
            return {
                "status": "PASS",
                "run_id": state["run_id"],
                "framework_digest": state["framework_digest"],
                "bundle_digest": state["bundle_digest"],
                "resolved_plan_digest": state["resolved_plan_digest"],
                "evaluator_digest": state["evaluator_digest"],
                "acceptance_digest": state["acceptance_digest"],
                "toolchain_digest": state["toolchain_digest"],
                "last_event_hash": state["last_event_hash"],
                "event_count": len(state["events"]),
            }

    def next_work_item(self, *, actor: str) -> dict[str, Any]:
        bundle, resolved = self._definition()
        policy = bundle.acceptance.budgets
        with self.store.locked():
            state = self._state(bundle, resolved)
            active = state.get("active_work_item")
            if isinstance(active, dict):
                return active
            while True:
                objective = self._ready_objective(resolved, state)
                if objective is None:
                    if any(progress["status"] == "BLOCKED" for progress in state["objectives"].values()):
                        return {"type": "BLOCKED", "reason": "an objective is blocked", "summary": self._summary(state, resolved)}
                    if not all(progress["status"] == "COMPLETE" for progress in state["objectives"].values()):
                        return {"type": "BLOCKED", "reason": "no objective is ready", "summary": self._summary(state, resolved)}
                    stale = next(
                        (
                            objective
                            for objective in resolved.objectives
                            if not self._program_inputs_current(state, bundle, objective, state["objectives"][objective.id])
                        ),
                        None,
                    )
                    if stale is not None:
                        progress = state["objectives"][stale.id]
                        progress.update({"status": "REVERIFY", "completion_reason": None})
                        for gate_progress in state["gates"].values():
                            gate_progress.update(_new_gate_progress())
                        state["approvals"] = {}
                        state["completion"] = None
                        self._event(state, "OBJECTIVE_RESULT_STALE", actor, {"objective_id": stale.id})
                        self.store.save(state)
                        continue
                    gate_item = self._next_gate(state, bundle, resolved, actor)
                    if gate_item is not None:
                        return gate_item
                    if any(progress["status"] == "BLOCKED" for progress in state["gates"].values()):
                        return {"type": "BLOCKED", "reason": "a completion gate is blocked", "summary": self._summary(state, resolved)}
                    if not all(progress["status"] == "COMPLETE" for progress in state["gates"].values()):
                        return {"type": "BLOCKED", "reason": "no completion gate is ready", "summary": self._summary(state, resolved)}
                    stale_gate = next((gate for gate in resolved.gates if not self._gate_inputs_current(state, bundle, gate)), None)
                    if stale_gate is not None:
                        state["gates"][stale_gate.id]["status"] = "BLOCKED"
                        self._event(state, "GATE_RESULT_STALE", actor, {"gate_id": stale_gate.id})
                        self.store.save(state)
                        return {"type": "BLOCKED", "reason": "completion gate evidence is stale", "gate_id": stale_gate.id}
                    return self._complete(state, bundle, resolved, actor)

                progress = state["objectives"][objective.id]
                if progress["status"] == "EVALUATOR_REPAIR_REQUIRED":
                    gap = progress.get("active_gap")
                    if not isinstance(gap, dict):
                        raise VProServiceError("evaluator repair state has no active gap")
                    if gap.get("repair_attempts", 0) >= policy["max_attempts"]:
                        progress["status"] = "BLOCKED"
                        self._event(state, "OBJECTIVE_BLOCKED", actor, {"objective_id": objective.id, "reason": "evaluator repair budget exhausted"})
                        self.store.save(state)
                        continue
                    gap["repair_attempts"] = int(gap.get("repair_attempts", 0)) + 1
                    gap["repair_started"] = True
                    self._prepare_write_parents(
                        self.project_root,
                        bundle.integrity.evaluator_repair_paths,
                        "evaluator repair",
                    )
                    work = self._work_item(
                        state,
                        bundle,
                        actor,
                        "EVALUATOR_REPAIR",
                        objective_id=objective.id,
                        allowed_write_paths=list(bundle.integrity.evaluator_repair_paths),
                        program_check=gap["program_check"],
                        instruction="Change only evaluator repair paths, then accept the repair.",
                    )
                    return self._issue(state, work, bundle, actor)
                if progress["status"] == "REVERIFY":
                    work = self._work_item(
                        state,
                        bundle,
                        actor,
                        "VERIFY",
                        objective_id=objective.id,
                        allowed_write_paths=[],
                        instruction="Run evaluate without editing product files.",
                    )
                    return self._issue(state, work, bundle, actor)
                if progress["status"] == "PROGRAM_PASS":
                    if not self._program_inputs_current(state, bundle, objective, progress):
                        progress.update({"status": "PENDING", "last_result": {"status": "STALE"}})
                        self._event(state, "PROGRAM_RESULT_STALE", actor, {"objective_id": objective.id})
                        self.store.save(state)
                        continue
                    if progress["review_rounds"] >= policy["max_review_rounds"]:
                        progress["status"] = "BLOCKED"
                        self._event(
                            state,
                            "OBJECTIVE_BLOCKED",
                            actor,
                            {
                                "objective_id": objective.id,
                                "reason": "acceptance review budget exhausted without NO_GAP",
                            },
                        )
                        self.store.save(state)
                        continue
                    if actor == progress.get("last_worker_actor"):
                        raise VProServiceError("acceptance review requires a fresh actor")
                    work = self._work_item(
                        state,
                        bundle,
                        actor,
                        "REVIEW_ACCEPTANCE",
                        objective_id=objective.id,
                        contract_clause_ids=list(objective.clause_ids),
                        review_round=progress["review_rounds"] + 1,
                    )
                    return self._issue(state, work, bundle, actor)

                exhausted = progress["attempts_used"] >= policy["max_attempts"]
                stagnant = progress["stagnant_attempts"] >= policy["stagnation_limit"]
                if exhausted or stagnant:
                    if progress["replans"] >= policy["max_replans"]:
                        progress["status"] = "BLOCKED"
                        self._event(state, "OBJECTIVE_BLOCKED", actor, {"objective_id": objective.id, "reason": "work budget exhausted"})
                        self.store.save(state)
                        continue
                    if actor == progress.get("last_worker_actor"):
                        raise VProServiceError("replan review requires a fresh actor")
                    work = self._work_item(
                        state,
                        bundle,
                        actor,
                        "REVIEW_REPLAN",
                        objective_id=objective.id,
                        contract_clause_ids=list(objective.clause_ids),
                    )
                    return self._issue(state, work, bundle, actor)

                self._prepare_write_parents(
                    self.project_root,
                    objective.worker_write_paths,
                    f"objective {objective.id}",
                )
                progress["attempts_used"] += 1
                progress["status"] = "WORKING"
                work = self._objective_work_item(state, bundle, actor, objective, progress)
                return self._issue(state, work, bundle, actor)

    def evaluate_active(self, *, actor: str, work_item_id: str) -> dict[str, Any]:
        bundle, resolved = self._definition()
        with self.store.locked():
            state = self._state(bundle, resolved)
            work = self._active_for_actor(
                state,
                actor,
                {
                    "WORK",
                    "VERIFY",
                    "GATE_GUARD",
                    "GATE_PREFLIGHT",
                    "GATE_CAPTURE",
                    "GATE_ADMISSION",
                },
                work_item_id=work_item_id,
            )
            allowed = tuple(work.get("allowed_write_paths", []))
            self._verify_authorization(work, allowed)
            if work["type"].startswith("GATE_"):
                return self._evaluate_gate(state, bundle, resolved, work, actor)
            objective = bundle.objective(str(work["objective_id"]))
            progress = state["objectives"][objective.id]
            checks = self._check_plan(bundle, objective, progress)
            results = self._run_checks(checks, state, bundle)
            self._verify_authorization(work, allowed)
            passed = len(results) == len(checks) and all(result["status"] == "PASS" for result in results)
            report = self._evaluation(bundle, objective.id, results, len(checks), passed)
            failed = next((result for result in results if result["status"] != "PASS"), None)
            if failed is not None:
                fingerprint = canonical_json_digest(
                    {
                        key: failed.get(key)
                        for key in ("check_id", "definition_digest", "input_digest", "status", "returncode")
                    }
                )
                if fingerprint != progress.get("failure_fingerprint"):
                    progress.update({"failure_fingerprint": fingerprint, "stagnant_attempts": 0, "best_score": report["score"]})
                elif report["score"] > progress["best_score"]:
                    progress.update({"best_score": report["score"], "stagnant_attempts": 0})
                else:
                    progress["stagnant_attempts"] += 1
            else:
                progress.update({"failure_fingerprint": None, "stagnant_attempts": 0, "best_score": report["score"], "active_gap": None})
            progress["last_result"] = report
            progress["last_worker_actor"] = actor
            progress["status"] = "PROGRAM_PASS" if passed else "PENDING"
            state["active_work_item"] = None
            self._event(state, "PROGRAM_EVALUATED", actor, {"objective_id": objective.id, "status": report["status"]})
            self.store.save(state)
            return self._compact(report)

    def submit_review(self, report: dict[str, Any], *, actor: str) -> dict[str, Any]:
        bundle, resolved = self._definition()
        with self.store.locked():
            state = self._state(bundle, resolved)
            work = self._active_for_actor(
                state,
                actor,
                {"REVIEW_ACCEPTANCE", "REVIEW_REPLAN"},
                work_item_id=report.get("work_item_id"),
            )
            if set(report) - {"work_item_id", "decision", "diagnosis", "contract_clause_id", "gap_kind", "program_check"}:
                raise VProServiceError("review report contains unknown fields")
            if report.get("work_item_id") != work["work_item_id"]:
                raise VProServiceError("review work_item_id does not match")
            self._verify_authorization(work, ())
            objective = bundle.objective(str(work["objective_id"]))
            progress = state["objectives"][objective.id]
            if work["type"] == "REVIEW_REPLAN":
                diagnosis = report.get("diagnosis")
                if report.get("decision") != "REPLAN" or not isinstance(diagnosis, str) or not diagnosis.strip():
                    raise VProServiceError("replan review requires decision REPLAN and a diagnosis")
                if len(diagnosis.encode()) > bundle.acceptance.budgets["failure_excerpt_bytes"]:
                    raise VProServiceError("replan diagnosis exceeds failure excerpt budget")
                preview_progress = {
                    **progress,
                    "budget_epoch": progress["budget_epoch"] + 1,
                    "attempts_used": 1,
                    "last_result": {"status": "REPLAN", "diagnosis": diagnosis},
                }
                preview = self._objective_work_item(
                    state,
                    bundle,
                    "A" * 64,
                    objective,
                    preview_progress,
                )
                try:
                    self._verify_work_item_context(preview, bundle)
                except VProServiceError as exc:
                    raise VProServiceError(
                        "replan diagnosis does not fit next work item context budget"
                    ) from exc
                progress.update({
                    "status": "PENDING",
                    "budget_epoch": progress["budget_epoch"] + 1,
                    "attempts_used": 0,
                    "replans": progress["replans"] + 1,
                    "stagnant_attempts": 0,
                    "last_result": {"status": "REPLAN", "diagnosis": diagnosis},
                })
                event = {"objective_id": objective.id, "decision": "REPLAN", "report_digest": canonical_json_digest(report)}
            else:
                decision = report.get("decision")
                if decision not in {"NO_GAP", "GAP"}:
                    raise VProServiceError("acceptance decision must be NO_GAP or GAP")
                progress["review_rounds"] += 1
                if decision == "NO_GAP":
                    if not self._program_inputs_current(state, bundle, objective, progress):
                        raise VProServiceError("program inputs changed before review")
                    progress.update({"status": "COMPLETE", "completion_reason": "PROGRAM_PASS_AND_REVIEW_FOUND_NO_GAP"})
                    event = {"objective_id": objective.id, "decision": "NO_GAP", "report_digest": canonical_json_digest(report)}
                else:
                    if report.get("contract_clause_id") not in objective.clause_ids:
                        raise VProServiceError("review gap must cite an exact objective clause id")
                    gap_kind = report.get("gap_kind")
                    if gap_kind not in {"PRODUCT_GAP", "EVALUATOR_GAP"}:
                        raise VProServiceError("review gap kind must be PRODUCT_GAP or EVALUATOR_GAP")
                    try:
                        check = parse_check(
                            report.get("program_check"),
                            tiers=bundle.tiers,
                            integrity=bundle.integrity,
                            project_root=self.project_root,
                            location="review.program_check",
                        )
                    except ContractError as exc:
                        raise VProServiceError(f"invalid reviewer check: {exc}") from exc
                    tier = bundle.tier(check.tier)
                    if not tier.reviewer_admissible or tier.cost != "cheap" or check.mode != "standard" or check.capabilities:
                        raise VProServiceError("review check must be reviewer-admissible, cheap, and standard mode")
                    if check.id in self._all_check_ids(bundle, progress):
                        raise VProServiceError("review check id is not novel")
                    evaluator_covered = _paths_intersect(check.inputs, bundle.integrity.evaluator_paths)
                    if (gap_kind == "EVALUATOR_GAP") != evaluator_covered:
                        raise VProServiceError("gap classification does not match evaluator coverage")
                    expected_authority = "evaluator" if gap_kind == "EVALUATOR_GAP" else "bundle"
                    if check.authority != expected_authority:
                        raise VProServiceError("gap classification does not match check authority")
                    if not _paths_intersect(check.inputs, bundle.integrity.authoritative_check_paths):
                        raise VProServiceError("review check must use a sealed authoritative check input")
                    if not self._review_executor_is_authoritative(check, bundle):
                        raise VProServiceError("review check executor must be a sealed authoritative path")
                    before = self._workspace_authorization_digest(())
                    evidence_before = self._evidence_authorization_digest(())
                    reproduction = self._runner(bundle, state).run(check, state["cache"])
                    after = self._workspace_authorization_digest(())
                    if before != after or evidence_before != self._evidence_authorization_digest(()) :
                        raise VProServiceError("review reproduction changed unauthorized files")
                    if reproduction["status"] != "FAIL":
                        raise VProServiceError("review gap was not reproduced")
                    progress["added_checks"].append(check.as_dict())
                    progress["check_anchors"][check.id] = {
                        "definition_digest": ProgramRunner.definition_digest(check),
                        "acceptance_digest": state["acceptance_digest"],
                    }
                    progress["active_gap"] = {
                        "kind": gap_kind,
                        "program_check": check.as_dict(),
                        "repair_attempts": 0,
                        "repair_started": False,
                    }
                    progress.update({
                        "status": "EVALUATOR_REPAIR_REQUIRED" if gap_kind == "EVALUATOR_GAP" else "PENDING",
                        "budget_epoch": progress["budget_epoch"] + 1,
                        "attempts_used": 0,
                        "stagnant_attempts": 0,
                        "last_result": {"status": "REVIEW_GAP", "reproduction": reproduction},
                    })
                    event = {
                        "objective_id": objective.id,
                        "decision": "GAP",
                        "gap_kind": gap_kind,
                        "check_id": check.id,
                        "report_digest": canonical_json_digest(report),
                    }
            self._verify_authorization(work, ())
            state["active_work_item"] = None
            self._event(state, "REVIEW_SUBMITTED", actor, event)
            self.store.save(state)
            return self._status_view(state, resolved)

    def accept_evaluator_repair(self, *, actor: str, work_item_id: str) -> dict[str, Any]:
        bundle, resolved = self._definition()
        with self.store.locked():
            state = self._state(bundle, resolved, allow_evaluator_change=True)
            work = self._active_for_actor(
                state,
                actor,
                {"EVALUATOR_REPAIR"},
                work_item_id=work_item_id,
            )
            objective = bundle.objective(str(work["objective_id"]))
            progress = state["objectives"][objective.id]
            gap = progress.get("active_gap")
            if not isinstance(gap, dict) or gap.get("kind") != "EVALUATOR_GAP":
                raise VProServiceError("active evaluator gap is missing")
            self._verify_authorization(work, tuple(work["allowed_write_paths"]))
            if self._product_digest(bundle, state) != work["baseline_product_digest"]:
                raise VProServiceError("product inputs changed during evaluator repair")
            check = parse_check(
                gap["program_check"],
                tiers=bundle.tiers,
                integrity=bundle.integrity,
                project_root=self.project_root,
                location="active_gap.program_check",
            )
            checks = (check, *(bundle.check(check_id) for check_id in bundle.acceptance.evaluator_guard_check_ids))
            results = self._run_checks(checks, state, bundle, cache_allowed=False)
            self._verify_authorization(work, tuple(work["allowed_write_paths"]))
            passed = len(results) == len(checks) and all(result["status"] == "PASS" for result in results)
            report = self._evaluation(bundle, objective.id, results, len(checks), passed)
            state["active_work_item"] = None
            if passed:
                state["evaluator_digest"] = self._paths_digest(bundle.integrity.evaluator_paths, bundle)
                state["evaluator_generation"] += 1
                progress.update({"status": "REVERIFY", "active_gap": None, "last_result": {"status": "EVALUATOR_REPAIRED"}})
            else:
                gap["pending_evaluator_digest"] = self._paths_digest(bundle.integrity.evaluator_paths, bundle)
                gap["repair_started"] = False
                progress.update({"status": "EVALUATOR_REPAIR_REQUIRED", "last_result": report})
            self._event(state, "EVALUATOR_REPAIR_EVALUATED", actor, {"objective_id": objective.id, "status": report["status"]})
            self.store.save(state)
            return self._compact(report)

    def approve_gate(self, approval: dict[str, Any], *, actor: str) -> dict[str, Any]:
        bundle, resolved = self._definition()
        expected_keys = {
            "schema_version",
            "run_id",
            "gate_id",
            "bundle_digest",
            "product_digest",
            "approval_challenge_digest",
            "cost_acknowledged",
            "expires_at_unix",
            "nonce",
            "operator_id",
            "hmac_sha256",
        }
        if set(approval) != expected_keys:
            raise VProServiceError("gate approval fields differ from the fixed schema")
        unsigned = {key: value for key, value in approval.items() if key != "hmac_sha256"}
        claimed_hmac = approval.get("hmac_sha256")
        expected_hmac = self._approval_authentication_tag(unsigned)
        if not isinstance(claimed_hmac, str) or not hmac.compare_digest(claimed_hmac, expected_hmac):
            raise VProServiceError("gate approval signature is invalid")
        if approval.get("operator_id") != actor:
            raise VProServiceError("gate approval signer does not match actor")
        with self.store.locked():
            state = self._state(bundle, resolved)
            gate_id = approval.get("gate_id")
            if gate_id not in state["gates"] or gate_id not in resolved.gate_ids:
                raise VProServiceError("approval references an unknown selected gate")
            progress = state["gates"][gate_id]
            if progress["status"] != "WAITING_APPROVAL":
                raise VProServiceError("gate is not waiting for approval")
            if approval.get("schema_version") != "vpro-gate-approval-v2" or approval.get("run_id") != state["run_id"]:
                raise VProServiceError("gate approval is for another run")
            if approval.get("bundle_digest") != state["bundle_digest"]:
                raise VProServiceError("gate approval bundle digest mismatch")
            if approval.get("product_digest") != self._product_digest(bundle, state):
                raise VProServiceError("gate approval product digest mismatch")
            if approval.get("approval_challenge_digest") != progress.get("approval_challenge_digest"):
                raise VProServiceError("gate approval challenge digest mismatch")
            if approval.get("cost_acknowledged") is not True or not isinstance(approval.get("expires_at_unix"), int):
                raise VProServiceError("gate approval lacks cost acknowledgement or expiry")
            if approval["expires_at_unix"] <= int(time.time()) or not isinstance(approval.get("nonce"), str) or not approval["nonce"]:
                raise VProServiceError("gate approval is expired or lacks a nonce")
            digest = canonical_json_digest(approval)
            if digest in state["approvals"] or any(
                item.get("nonce") == approval["nonce"]
                for item in state["approvals"].values()
                if isinstance(item, dict)
            ):
                raise VProServiceError("gate approval was already used")
            state["approvals"][digest] = dict(approval)
            next_status = "PREFLIGHT_AUTHORIZED" if progress.get("approval_before_preflight") else "APPROVED"
            progress.update({"status": next_status, "approval_digest": digest})
            self._event(state, "GATE_APPROVED", actor, {"gate_id": gate_id, "approval_digest": digest})
            self.store.save(state)
            return self._status_view(state, resolved)

    def verify_completion(self) -> dict[str, Any]:
        bundle, resolved = self._definition()
        with self.store.locked():
            state = self._state(bundle, resolved)
            if not isinstance(state.get("completion"), dict):
                raise VProServiceError("run has no completion seal")
            expected = self._completion_payload(state, bundle, resolved, basis_event_hash=state["completion"].get("basis_event_hash"))
            if state["completion"] != expected:
                raise VProServiceError("completion seal is stale")
            return {"status": "PASS", "run_id": state["run_id"], "claim": state["completion"]["claim"], "completion_digest": canonical_json_digest(expected)}

    def _definition(self) -> tuple[BundleDefinition, ResolvedProfile]:
        bundle = load_bundle(self.bundle_path, project_root=self.project_root)
        self._verify_framework_boundaries(bundle)
        try:
            resolved = bundle.resolve_profile(self.profile_id)
        except KeyError as exc:
            raise VProServiceError(f"unknown milestone profile: {self.profile_id}") from exc
        return bundle, resolved

    def _verify_framework_boundaries(self, bundle: BundleDefinition) -> None:
        protected = [self.release.root / path for path in self.release.protected_paths]
        protected.append(self.release.manifest_path)
        writable = [
            *bundle.integrity.product_roots,
            *(path for objective in bundle.objectives for path in objective.worker_write_paths),
            *bundle.integrity.evaluator_repair_paths,
            *bundle.integrity.authoritative_check_paths,
        ]
        for path in writable:
            absolute = self.project_root / path
            if any(_absolute_path_overlap(absolute, fixed) for fixed in protected):
                raise VProServiceError(f"bundle write authority overlaps fixed framework path: {path}")

    def _review_executor_is_authoritative(self, check: CheckDefinition, bundle: BundleDefinition) -> bool:
        targets: list[str] = []
        for argument in check.argv[1:]:
            candidate = argument.split("=", 1)[1] if argument.startswith("--") and "=" in argument else argument
            candidate = candidate.split("::", 1)[0]
            if candidate.startswith("-"):
                continue
            target = candidate if check.cwd == "." else f"{check.cwd}/{candidate}"
            if (self.project_root / target).exists():
                targets.append(target)
        return bool(targets) and all(
            any(_path_overlap(target, root) for root in bundle.integrity.authoritative_check_paths)
            for target in targets
        )

    def _state(self, bundle: BundleDefinition, resolved: ResolvedProfile, *, allow_evaluator_change: bool = False) -> dict[str, Any]:
        if not self.store.exists():
            raise VProServiceError("run is not bound")
        state = self.store.load()
        if state.get("schema_version") != self.STATE_SCHEMA:
            raise VProServiceError("state schema version mismatch")
        expected = {
            "framework_digest": self.release.digest,
            "bundle_digest": file_digest(self.bundle_path),
            "resolved_plan_digest": canonical_json_digest(self._resolved_plan(bundle, resolved)),
            "milestone_id": bundle.milestone.id,
            "bundle_version": bundle.milestone.version,
            "profile_id": resolved.profile.id,
            "state_seal_key_id": self.store.seal_key_id,
            "approval_key_id": hashlib.sha256(self._approval_key).hexdigest(),
        }
        for key, value in expected.items():
            if state.get(key) != value:
                raise VProServiceError(f"sealed {key} changed after bind")
        try:
            stored_plan = json.loads(self.store.plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VProServiceError(f"cannot load resolved plan: {exc}") from exc
        if stored_plan != self._resolved_plan(bundle, resolved):
            raise VProServiceError("resolved plan file changed after bind")
        current_evaluator = self._paths_digest(bundle.integrity.evaluator_paths, bundle)
        if state.get("evaluator_digest") != current_evaluator and not (
            allow_evaluator_change or self._evaluator_drift_authorized(state, current_evaluator)
        ):
            raise VProServiceError("evaluator changed outside controlled repair")
        if state.get("acceptance_digest") != self._paths_digest(bundle.integrity.authoritative_check_paths, bundle):
            raise VProServiceError("authoritative acceptance assets changed after bind")
        ProgramRunner.verify_tool_seals(
            state.get("tool_seals"),
            bundle.integrity.allowed_tools,
            workspace_root=self.workspace_root,
            state_root=self.state_root,
        )
        ProgramRunner.verify_sandbox_seal(
            state.get("sandbox_seal"),
            workspace_root=self.workspace_root,
            state_root=self.state_root,
        )
        if state.get("toolchain_digest") != canonical_json_digest(
            {"tools": state["tool_seals"], "sandbox": state["sandbox_seal"]}
        ):
            raise VProServiceError("sealed toolchain identity changed after bind")
        errors = self.store.verify(state)
        if errors:
            raise VProServiceError("state integrity failure: " + "; ".join(errors))
        self._verify_review_anchors(state)
        if isinstance(state.get("completion"), dict):
            completion = state["completion"]
            expected_completion = self._completion_payload(
                state,
                bundle,
                resolved,
                basis_event_hash=completion.get("basis_event_hash"),
            )
            if completion != expected_completion:
                raise VProServiceError("terminal completion seal is stale")
            if any(not self._program_inputs_current(state, bundle, objective, state["objectives"][objective.id]) for objective in resolved.objectives):
                raise VProServiceError("terminal objective evidence is stale")
            if any(not self._gate_inputs_current(state, bundle, gate) for gate in resolved.gates):
                raise VProServiceError("terminal gate evidence is stale")
            expected_file_payload = {
                "completion": completion,
                "last_event_hash": state["last_event_hash"],
                "state_payload_digest": StateStore.payload_digest(state),
            }
            expected_file = {
                **expected_file_payload,
                "hmac_sha256": self.store.authentication_tag(expected_file_payload),
            }
            try:
                actual_file = json.loads(self.store.completion_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise VProServiceError(f"cannot load completion seal file: {exc}") from exc
            if actual_file != expected_file:
                raise VProServiceError("completion seal file does not match terminal state")
        return state

    def _runner(self, bundle: BundleDefinition, state: dict[str, Any]) -> ProgramRunner:
        runner = ProgramRunner(
            project_root=self.project_root,
            workspace_root=self.workspace_root,
            state_root=self.state_root,
            logs_root=self.state_root / "logs",
            excerpt_bytes=bundle.acceptance.budgets["failure_excerpt_bytes"],
            allowed_tools=bundle.integrity.allowed_tools,
            tool_seals=state["tool_seals"],
            sandbox_seal=state["sandbox_seal"],
            evidence_roots=bundle.integrity.evidence_roots,
            run_context={
                "run_id": state["run_id"],
                "bundle_digest": state["bundle_digest"],
                "framework_digest": state["framework_digest"],
                "ownership_token": state["ownership_token"],
            },
            secret_paths=self.secret_paths,
        )
        runner.run_context["product_digest"] = runner.input_digest(bundle.integrity.product_roots)
        if bundle.integrity.evidence_roots:
            runner.run_context["evidence_root"] = str((self.state_root / bundle.integrity.evidence_roots[0]).resolve())
        return runner

    def _paths_digest(self, paths: Iterable[str], bundle: BundleDefinition) -> str:
        runner = ProgramRunner(
            project_root=self.project_root,
            workspace_root=self.workspace_root,
            state_root=self.state_root,
            logs_root=self.state_root / "logs",
            excerpt_bytes=bundle.acceptance.budgets["failure_excerpt_bytes"],
            allowed_tools=bundle.integrity.allowed_tools,
            tool_seals=None,
            sandbox_seal=None,
            evidence_roots=bundle.integrity.evidence_roots,
            run_context={},
        )
        return runner.input_digest(paths)

    def _product_digest(self, bundle: BundleDefinition, state: dict[str, Any]) -> str:
        return self._runner(bundle, state).input_digest(bundle.integrity.product_roots)

    def _approval_authentication_tag(self, value: Any) -> str:
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return hmac.new(
            self._approval_key,
            b"vpro-gate-approval-v2\0" + encoded,
            hashlib.sha256,
        ).hexdigest()

    def _work_item(self, state: dict[str, Any], bundle: BundleDefinition, actor: str, kind: str, **values: Any) -> dict[str, Any]:
        allowed = tuple(values.get("allowed_write_paths", ()))
        evidence_allowed = tuple(values.get("evidence_write_paths", ()))
        baseline_allowed = allowed
        work = {
            "type": kind,
            "work_item_id": uuid.uuid4().hex,
            "actor": actor,
            "authorization_digest": self._workspace_authorization_digest(baseline_allowed),
            "evidence_authorization_digest": self._evidence_authorization_digest(evidence_allowed),
            "baseline_product_digest": self._product_digest(bundle, state),
            **values,
        }
        return work

    def _objective_work_item(
        self,
        state: dict[str, Any],
        bundle: BundleDefinition,
        actor: str,
        objective: ObjectiveDefinition,
        progress: dict[str, Any],
    ) -> dict[str, Any]:
        return self._work_item(
            state,
            bundle,
            actor,
            "WORK",
            objective_id=objective.id,
            title=objective.title,
            attempt=progress["attempts_used"],
            budget_epoch=progress["budget_epoch"],
            contract_clause_ids=list(objective.clause_ids),
            context_paths=list(objective.context_paths),
            allowed_write_paths=list(objective.worker_write_paths),
            last_program_result=self._compact(progress.get("last_result")),
            instruction="Implement only this objective within the authorized write paths, then run evaluate.",
        )

    @staticmethod
    def _verify_work_item_context(work: dict[str, Any], bundle: BundleDefinition) -> None:
        size = len(json.dumps(work, ensure_ascii=True).encode())
        if size > bundle.acceptance.budgets["max_context_bytes"]:
            raise VProServiceError(f"work item context is {size} bytes, over budget")

    def _issue(self, state: dict[str, Any], work: dict[str, Any], bundle: BundleDefinition, actor: str) -> dict[str, Any]:
        self._verify_work_item_context(work, bundle)
        state["iteration"] += 1
        state["active_work_item"] = work
        self._event(state, "WORK_ISSUED", actor, {"type": work["type"], "work_item_id": work["work_item_id"], "objective_id": work.get("objective_id"), "gate_id": work.get("gate_id")})
        self.store.save(state)
        return work

    def _verify_authorization(self, work: dict[str, Any], allowed: Iterable[str]) -> None:
        actual = self._workspace_authorization_digest(allowed)
        if actual != work.get("authorization_digest"):
            raise VProServiceError("files outside the work-item authorization changed")
        evidence_actual = self._evidence_authorization_digest(tuple(work.get("evidence_write_paths", ())))
        if evidence_actual != work.get("evidence_authorization_digest"):
            raise VProServiceError("run evidence changed outside the work-item authorization")

    def _evidence_authorization_digest(self, allowed: Iterable[str]) -> str:
        return workspace_minus_allowed_digest(
            self.state_root,
            ("state", "logs", "pycache", "scratch", *tuple(allowed)),
        )

    def _workspace_authorization_digest(self, allowed: Iterable[str]) -> str:
        project_relative = self.project_root.relative_to(self.workspace_root)
        translated = tuple(
            (project_relative / path).as_posix() if project_relative != Path(".") else Path(path).as_posix()
            for path in allowed
        )
        return workspace_minus_allowed_digest(self.workspace_root, translated)

    def _run_checks(
        self,
        checks: tuple[CheckDefinition, ...],
        state: dict[str, Any],
        bundle: BundleDefinition,
        *,
        cache_allowed: bool = True,
    ) -> list[dict[str, Any]]:
        runner = self._runner(bundle, state)
        results: list[dict[str, Any]] = []
        for check in checks:
            tier = bundle.tier(check.tier)
            definition = runner.definition_digest(check)
            input_digest = runner.input_digest(check.inputs)
            count_key = hashlib.sha256(f"{definition}:{input_digest}".encode()).hexdigest()
            costly = tier.cost in {"expensive", "operator"}
            if costly and state["run_counts"].get(count_key, 0) >= bundle.acceptance.budgets["max_expensive_runs_per_input"]:
                cached = runner.cached_result(check, state["cache"])
                if cached is None:
                    results.append({"check_id": check.id, "tier": check.tier, "status": "BLOCKED", "reason": "expensive run budget exhausted"})
                    break
            result = runner.run(check, state["cache"], cache_allowed=cache_allowed)
            if costly and not result.get("cached"):
                state["run_counts"][count_key] = int(state["run_counts"].get(count_key, 0)) + 1
            results.append(result)
            if result["status"] != "PASS":
                break
        return results

    def _check_plan(self, bundle: BundleDefinition, objective: ObjectiveDefinition, progress: dict[str, Any]) -> tuple[CheckDefinition, ...]:
        added = tuple(
            parse_check(raw, tiers=bundle.tiers, integrity=bundle.integrity, project_root=self.project_root, location="state.added_check")
            for raw in progress.get("added_checks", [])
        )
        base_ids = (*bundle.acceptance.common_check_ids, *objective.check_ids)
        base = tuple(bundle.check(check_id) for check_id in base_ids) + added
        cheap = sorted((check for check in base if bundle.tier(check.tier).cost in {"cheap", "normal"}), key=lambda check: bundle.tier(check.tier).rank)
        expensive = sorted((check for check in base if bundle.tier(check.tier).cost in {"expensive", "operator"}), key=lambda check: bundle.tier(check.tier).rank)
        closure = tuple(sorted((bundle.check(check_id) for check_id in bundle.acceptance.closure_check_ids), key=lambda check: bundle.tier(check.tier).rank))
        return (*cheap, *closure, *expensive)

    def _program_inputs_current(self, state: dict[str, Any], bundle: BundleDefinition, objective: ObjectiveDefinition, progress: dict[str, Any]) -> bool:
        report = progress.get("last_result")
        if not isinstance(report, dict) or report.get("status") != "PASS":
            return False
        checks = self._check_plan(bundle, objective, progress)
        results = report.get("results")
        by_id = {item.get("check_id"): item for item in results if isinstance(item, dict)} if isinstance(results, list) else {}
        runner = self._runner(bundle, state)
        if len(by_id) != len(checks):
            return False
        for check in checks:
            result = by_id.get(check.id, {})
            if result.get("input_digest") != runner.input_digest(check.inputs) or result.get("definition_digest") != runner.definition_digest(check):
                return False
            log_path = Path(str(result.get("log_path", "")))
            if not log_path.is_file() or result.get("log_digest") != file_digest(log_path):
                return False
        return True

    def _gate_inputs_current(self, state: dict[str, Any], bundle: BundleDefinition, gate: GateDefinition) -> bool:
        progress = state["gates"][gate.id]
        phases = progress.get("phase_results")
        if not isinstance(phases, dict):
            return False
        expected: dict[str, tuple[str, ...]] = {}
        if gate.kind == "program":
            expected["GATE_ADMISSION"] = gate.check_ids
        else:
            expected["GATE_GUARD"] = self._gate_guard_check_ids(bundle, gate)
            expected["GATE_PREFLIGHT"] = self._gate_preflight_check_ids(bundle, gate)
            if gate.capture_check_id is not None:
                expected["GATE_CAPTURE"] = (gate.capture_check_id,)
            if gate.admission_check_ids:
                expected["GATE_ADMISSION"] = gate.admission_check_ids
        runner = self._runner(bundle, state)
        for phase, check_ids in expected.items():
            report = phases.get(phase)
            if not isinstance(report, dict) or report.get("status") != "PASS":
                return False
            results = report.get("results")
            if not isinstance(results, list) or len(results) != len(check_ids):
                return False
            by_id = {result.get("check_id"): result for result in results if isinstance(result, dict)}
            for check_id in check_ids:
                check = bundle.check(check_id)
                result = by_id.get(check_id)
                if not isinstance(result, dict):
                    return False
                if result.get("definition_digest") != runner.definition_digest(check):
                    return False
                if result.get("input_digest") != runner.input_digest(check.inputs):
                    return False
                expected_output = runner.input_digest(check.outputs) if check.outputs else None
                if result.get("output_digest") != expected_output:
                    return False
                log_path = Path(str(result.get("log_path", "")))
                if not log_path.is_file() or result.get("log_digest") != file_digest(log_path):
                    return False
        return True

    def _next_gate(self, state: dict[str, Any], bundle: BundleDefinition, resolved: ResolvedProfile, actor: str) -> dict[str, Any] | None:
        for gate in resolved.gates:
            progress = state["gates"][gate.id]
            if progress["status"] in {"COMPLETE", "BLOCKED"}:
                continue
            if not all(state["objectives"][objective_id]["status"] == "COMPLETE" for objective_id in gate.after_objective_ids):
                continue
            if progress["status"] == "APPROVED":
                self._validate_gate_approval_current(state, bundle, gate.id)
            if gate.kind == "program":
                if progress["status"] == "PENDING" and gate.operator_approval_required:
                    progress["status"] = "WAITING_APPROVAL"
                    progress["approval_before_preflight"] = False
                    progress["approval_challenge_digest"] = canonical_json_digest(
                        self._gate_approval_challenge(state, bundle, gate)
                    )
                    self._event(state, "GATE_WAITING_APPROVAL", actor, {"gate_id": gate.id})
                    self.store.save(state)
                if progress["status"] == "WAITING_APPROVAL":
                    return self._gate_approval_item(state, bundle, gate)
                if progress["status"] in {"PENDING", "APPROVED"}:
                    return self._issue_gate(state, bundle, gate, actor, "GATE_ADMISSION", gate.check_ids)
            if progress["status"] == "PENDING":
                return self._issue_gate(
                    state,
                    bundle,
                    gate,
                    actor,
                    "GATE_GUARD",
                    self._gate_guard_check_ids(bundle, gate),
                )
            if progress["status"] == "GUARD_PASS":
                if gate.operator_approval_required and self._preflight_requires_approval(bundle, gate):
                    progress["status"] = "WAITING_APPROVAL"
                    progress["approval_before_preflight"] = True
                    progress["approval_challenge_digest"] = canonical_json_digest(
                        self._gate_approval_challenge(
                            state,
                            bundle,
                            gate,
                            before_preflight=True,
                        )
                    )
                    self._event(state, "GATE_WAITING_APPROVAL", actor, {"gate_id": gate.id})
                    self.store.save(state)
                    return self._gate_approval_item(state, bundle, gate)
                return self._issue_gate(
                    state,
                    bundle,
                    gate,
                    actor,
                    "GATE_PREFLIGHT",
                    self._gate_preflight_check_ids(bundle, gate),
                )
            if progress["status"] == "PREFLIGHT_AUTHORIZED":
                self._validate_gate_approval_current(state, bundle, gate.id)
                return self._issue_gate(
                    state,
                    bundle,
                    gate,
                    actor,
                    "GATE_PREFLIGHT",
                    self._gate_preflight_check_ids(bundle, gate),
                )
            if progress["status"] == "PREFLIGHT_PASS":
                if gate.operator_approval_required and not progress.get("approval_before_preflight"):
                    progress["status"] = "WAITING_APPROVAL"
                    progress["approval_before_preflight"] = False
                    progress["approval_challenge_digest"] = canonical_json_digest(
                        self._gate_approval_challenge(state, bundle, gate)
                    )
                    self._event(state, "GATE_WAITING_APPROVAL", actor, {"gate_id": gate.id})
                    self.store.save(state)
                    return self._gate_approval_item(state, bundle, gate)
                if gate.operator_approval_required:
                    self._validate_gate_approval_current(state, bundle, gate.id)
                progress["status"] = "APPROVED"
            if progress["status"] == "WAITING_APPROVAL":
                return self._gate_approval_item(state, bundle, gate)
            if progress["status"] == "APPROVED":
                if gate.capture_check_id is None:
                    progress["status"] = "CAPTURE_PASS"
                    self._event(state, "GATE_CAPTURE_SKIPPED", actor, {"gate_id": gate.id})
                    self.store.save(state)
                    return self._next_gate(state, bundle, resolved, actor)
                return self._issue_gate(state, bundle, gate, actor, "GATE_CAPTURE", (gate.capture_check_id,))
            if progress["status"] == "CAPTURE_PASS":
                if progress.get("capture_product_digest") != self._product_digest(bundle, state):
                    raise VProServiceError("product changed after gate capture; admission is stale")
                runner = self._runner(bundle, state)
                for path, digest in progress.get("capture_outputs", {}).items():
                    if runner.input_digest((path,)) != digest:
                        raise VProServiceError("raw capture changed before admission")
                if gate.operator_approval_required:
                    self._validate_gate_approval_current(state, bundle, gate.id)
                if not gate.admission_check_ids:
                    progress["status"] = "COMPLETE"
                    self._event(state, "GATE_COMPLETE", actor, {"gate_id": gate.id})
                    self.store.save(state)
                    return self._next_gate(state, bundle, resolved, actor)
                return self._issue_gate(state, bundle, gate, actor, "GATE_ADMISSION", gate.admission_check_ids)
        return None

    def _preflight_requires_approval(self, bundle: BundleDefinition, gate: GateDefinition) -> bool:
        return any(
            bundle.check(check_id).capabilities
            or bundle.tier(bundle.check(check_id).tier).cost in {"expensive", "operator"}
            for check_id in self._gate_preflight_check_ids(bundle, gate)
        )

    @staticmethod
    def _gate_guard_check_ids(
        bundle: BundleDefinition,
        gate: GateDefinition,
    ) -> tuple[str, ...]:
        if gate.kind != "evidence":
            return ()
        return bundle.acceptance.evaluator_guard_check_ids

    @staticmethod
    def _gate_preflight_check_ids(
        bundle: BundleDefinition,
        gate: GateDefinition,
    ) -> tuple[str, ...]:
        if gate.kind != "evidence":
            return ()
        return gate.preflight_check_ids

    def _issue_gate(self, state: dict[str, Any], bundle: BundleDefinition, gate: GateDefinition, actor: str, kind: str, check_ids: Iterable[str]) -> dict[str, Any]:
        ids = tuple(check_ids)
        evidence_writes = tuple(output for check_id in ids for output in bundle.check(check_id).outputs)
        self._prepare_write_parents(self.state_root, evidence_writes, "evidence output")
        work = self._work_item(state, bundle, actor, kind, gate_id=gate.id, check_ids=list(ids), allowed_write_paths=[], evidence_write_paths=list(evidence_writes), instruction="Run the controller-owned gate checks without editing product files.")
        return self._issue(state, work, bundle, actor)

    @staticmethod
    def _prepare_write_parents(root: Path, paths: Iterable[str], label: str) -> None:
        for raw in paths:
            current = root
            for part in Path(raw).parent.parts:
                current = current / part
                if current.is_symlink():
                    raise VProServiceError(f"{label} parent traverses a symlink: {raw}")
                try:
                    current.mkdir(exist_ok=True)
                except OSError as exc:
                    raise VProServiceError(f"cannot prepare {label} parent: {raw}: {exc}") from exc
                if current.is_symlink() or not current.is_dir():
                    raise VProServiceError(f"{label} parent is not a directory: {raw}")

    def _validate_gate_approval_current(self, state: dict[str, Any], bundle: BundleDefinition, gate_id: str) -> None:
        progress = state["gates"][gate_id]
        digest = progress.get("approval_digest")
        approval = state.get("approvals", {}).get(digest)
        if not isinstance(approval, dict):
            raise VProServiceError("gate approval record is missing")
        unsigned = {key: value for key, value in approval.items() if key != "hmac_sha256"}
        claimed_hmac = approval.get("hmac_sha256")
        if not isinstance(claimed_hmac, str) or not hmac.compare_digest(
            claimed_hmac,
            self._approval_authentication_tag(unsigned),
        ):
            raise VProServiceError("gate approval signature became invalid")
        if approval.get("expires_at_unix", 0) <= int(time.time()):
            raise VProServiceError("gate approval expired")
        if approval.get("bundle_digest") != state["bundle_digest"]:
            raise VProServiceError("gate approval bundle digest changed")
        if approval.get("product_digest") != self._product_digest(bundle, state):
            raise VProServiceError("gate approval product digest changed")
        gate = bundle.gate(gate_id)
        expected_challenge = canonical_json_digest(
            self._gate_approval_challenge(
                state,
                bundle,
                gate,
                before_preflight=bool(progress.get("approval_before_preflight")),
            )
        )
        if progress.get("approval_challenge_digest") != expected_challenge or approval.get("approval_challenge_digest") != expected_challenge:
            raise VProServiceError("gate approval challenge became stale")

    def _gate_approval_item(self, state: dict[str, Any], bundle: BundleDefinition, gate: GateDefinition) -> dict[str, Any]:
        return {
            "type": "GATE_APPROVAL_REQUIRED",
            "gate_id": gate.id,
            "run_id": state["run_id"],
            "bundle_digest": state["bundle_digest"],
            "product_digest": self._product_digest(bundle, state),
            "approval_challenge_digest": state["gates"][gate.id]["approval_challenge_digest"],
        }

    def _gate_approval_challenge(
        self,
        state: dict[str, Any],
        bundle: BundleDefinition,
        gate: GateDefinition,
        *,
        before_preflight: bool = False,
    ) -> dict[str, Any]:
        runner = self._runner(bundle, state)
        all_check_ids = tuple(
            dict.fromkeys(
                (
                    *self._gate_guard_check_ids(bundle, gate),
                    *self._gate_preflight_check_ids(bundle, gate),
                    *gate.all_check_ids,
                )
            )
        )
        checks = tuple(bundle.check(check_id) for check_id in all_check_ids)
        input_bound_ids = (
            gate.check_ids
            if gate.kind == "program"
            else (
                *self._gate_guard_check_ids(bundle, gate),
                *self._gate_preflight_check_ids(bundle, gate),
                *((gate.capture_check_id,) if gate.capture_check_id else ()),
            )
        )
        return {
            "schema_version": "vpro-gate-approval-challenge-v1",
            "run_id": state["run_id"],
            "gate_id": gate.id,
            "framework_digest": state["framework_digest"],
            "toolchain_digest": state["toolchain_digest"],
            "bundle_digest": state["bundle_digest"],
            "product_digest": self._product_digest(bundle, state),
            "evaluator_digest": self._paths_digest(bundle.integrity.evaluator_paths, bundle),
            "guard_result_digest": canonical_json_digest(
                state["gates"][gate.id]["phase_results"].get("GATE_GUARD")
            ),
            "preflight_result_digest": canonical_json_digest(
                None if before_preflight else state["gates"][gate.id]["phase_results"].get("GATE_PREFLIGHT")
            ),
            "check_definition_digests": {check.id: runner.definition_digest(check) for check in checks},
            "bound_input_digests": {check_id: runner.input_digest(bundle.check(check_id).inputs) for check_id in input_bound_ids},
            "capabilities": sorted({capability for check in checks for capability in check.capabilities}),
            "costs": sorted({bundle.tier(check.tier).cost for check in checks}),
        }

    def _evaluate_gate(self, state: dict[str, Any], bundle: BundleDefinition, resolved: ResolvedProfile, work: dict[str, Any], actor: str) -> dict[str, Any]:
        gate = bundle.gate(str(work["gate_id"]))
        progress = state["gates"][gate.id]
        if gate.operator_approval_required and work["type"] != "GATE_GUARD" and (
            work["type"] != "GATE_PREFLIGHT" or progress.get("approval_before_preflight")
        ):
            self._validate_gate_approval_current(state, bundle, gate.id)
        checks = tuple(bundle.check(check_id) for check_id in work["check_ids"])
        results = self._run_checks(checks, state, bundle)
        self._verify_authorization(work, tuple(work.get("allowed_write_paths", ())))
        passed = len(results) == len(checks) and all(result["status"] == "PASS" for result in results)
        report = {"status": "PASS" if passed else "FAIL", "gate_id": gate.id, "phase": work["type"], "results": results}
        state["active_work_item"] = None
        if not passed:
            progress.update({"status": "BLOCKED", "last_result": report})
        elif work["type"] == "GATE_GUARD":
            progress.update({"status": "GUARD_PASS", "last_result": report})
        elif work["type"] == "GATE_PREFLIGHT":
            progress.update({"status": "PREFLIGHT_PASS", "last_result": report})
        elif work["type"] == "GATE_CAPTURE":
            runner = self._runner(bundle, state)
            outputs = {
                path: runner.input_digest((path,))
                for check in checks
                for path in check.outputs
            }
            progress.update({"status": "CAPTURE_PASS", "last_result": report, "capture_product_digest": self._product_digest(bundle, state), "capture_outputs": outputs})
        else:
            progress.update({"status": "COMPLETE", "last_result": report})
        progress["phase_results"][work["type"]] = report
        self._event(state, "GATE_EVALUATED", actor, {"gate_id": gate.id, "phase": work["type"], "status": report["status"]})
        self.store.save(state)
        return self._compact(report)

    def _complete(self, state: dict[str, Any], bundle: BundleDefinition, resolved: ResolvedProfile, actor: str) -> dict[str, Any]:
        if state.get("completion") is None:
            state["completion"] = self._completion_payload(
                state,
                bundle,
                resolved,
                basis_event_hash=state.get("last_event_hash"),
            )
            self._event(state, "RUN_COMPLETE", actor, {"claim": resolved.profile.claim})
            self.store.save(state)
            completion_file = {
                "completion": state["completion"],
                "last_event_hash": state["last_event_hash"],
                "state_payload_digest": StateStore.payload_digest(state),
            }
            self.store.save_completion(
                {**completion_file, "hmac_sha256": self.store.authentication_tag(completion_file)}
            )
        return {"type": "DONE", "run_id": state["run_id"], "claim": resolved.profile.claim, "summary": self._summary(state, resolved)}

    def _completion_payload(
        self,
        state: dict[str, Any],
        bundle: BundleDefinition,
        resolved: ResolvedProfile,
        *,
        basis_event_hash: Any,
    ) -> dict[str, Any]:
        runner = self._runner(bundle, state)
        return {
            "schema_version": "vpro-completion-v1",
            "run_id": state["run_id"],
            "claim": resolved.profile.claim,
            "framework_digest": state["framework_digest"],
            "toolchain_digest": state["toolchain_digest"],
            "bundle_digest": state["bundle_digest"],
            "resolved_plan_digest": state["resolved_plan_digest"],
            "evaluator_digest": state["evaluator_digest"],
            "evaluator_generation": state["evaluator_generation"],
            "acceptance_digest": state["acceptance_digest"],
            "state_seal_key_id": state["state_seal_key_id"],
            "approval_key_id": state["approval_key_id"],
            "product_digest": self._product_digest(bundle, state),
            "evidence_digest": runner.input_digest(bundle.integrity.evidence_roots),
            "objective_result_digest": canonical_json_digest({objective.id: state["objectives"][objective.id]["last_result"] for objective in resolved.objectives}),
            "gate_result_digest": canonical_json_digest({gate.id: state["gates"][gate.id]["phase_results"] for gate in resolved.gates}),
            "basis_event_hash": basis_event_hash,
            "objective_ids": list(resolved.objective_ids),
            "gate_ids": list(resolved.gate_ids),
        }

    def _resolved_plan(self, bundle: BundleDefinition, resolved: ResolvedProfile) -> dict[str, Any]:
        return {
            "schema_version": "vpro-resolved-plan-v1",
            "milestone_id": bundle.milestone.id,
            "bundle_version": bundle.milestone.version,
            "profile_id": resolved.profile.id,
            "claim": resolved.profile.claim,
            "objective_ids": list(resolved.objective_ids),
            "gate_ids": list(resolved.gate_ids),
        }

    def _verify_review_anchors(self, state: dict[str, Any]) -> None:
        for objective_id, progress in state.get("objectives", {}).items():
            added = progress.get("added_checks")
            anchors = progress.get("check_anchors")
            if not isinstance(added, list) or not isinstance(anchors, dict):
                raise VProServiceError(f"invalid review anchor state for {objective_id}")
            ids = {raw.get("id") for raw in added if isinstance(raw, dict)}
            if ids != set(anchors):
                raise VProServiceError(f"review anchors do not match added checks for {objective_id}")
            for raw in added:
                check_id = raw["id"]
                if anchors[check_id].get("definition_digest") != canonical_json_digest(raw):
                    raise VProServiceError(f"review check definition changed: {check_id}")
                if anchors[check_id].get("acceptance_digest") != state.get("acceptance_digest"):
                    raise VProServiceError(f"review acceptance anchor changed: {check_id}")

    @staticmethod
    def _ready_objective(resolved: ResolvedProfile, state: dict[str, Any]) -> ObjectiveDefinition | None:
        for objective in resolved.objectives:
            progress = state["objectives"][objective.id]
            if progress["status"] in {"COMPLETE", "BLOCKED"}:
                continue
            if all(state["objectives"][dependency]["status"] == "COMPLETE" for dependency in objective.depends_on):
                return objective
        return None

    @staticmethod
    def _active_for_actor(
        state: dict[str, Any],
        actor: str,
        kinds: set[str],
        *,
        work_item_id: Any,
    ) -> dict[str, Any]:
        work = state.get("active_work_item")
        if not isinstance(work, dict) or work.get("type") not in kinds:
            raise VProServiceError(f"active work item must be one of {sorted(kinds)}")
        if work.get("actor") != actor:
            raise VProServiceError("active work item belongs to another actor")
        if not isinstance(work_item_id, str) or work.get("work_item_id") != work_item_id:
            raise VProServiceError("active work item id does not match")
        return work

    def _event(self, state: dict[str, Any], kind: str, actor: str, payload: dict[str, Any]) -> None:
        event = {"schema_version": "vpro-event-v1", "event": kind, "actor": actor, "iteration": state["iteration"], "at_unix": int(time.time()), **payload}
        self.store.append_event(state, event)

    @staticmethod
    def _evaluation(bundle: BundleDefinition, objective_id: str, results: list[dict[str, Any]], total: int, passed: bool) -> dict[str, Any]:
        ranks = {tier.id: tier.rank for tier in bundle.tiers}
        highest = max((ranks.get(str(result.get("tier")), -1) for result in results if result.get("status") == "PASS"), default=-1)
        failed = sum(result.get("status") != "PASS" for result in results)
        return {"status": "PASS" if passed else "FAIL", "objective_id": objective_id, "score": (highest + 1) * 100 - failed, "highest_rank_passed": highest, "checks_run": len(results), "checks_total": total, "results": results}

    @staticmethod
    def _all_check_ids(bundle: BundleDefinition, progress: dict[str, Any]) -> set[str]:
        return {check.id for check in bundle.checks} | {str(raw.get("id")) for raw in progress.get("added_checks", []) if isinstance(raw, dict)}

    @staticmethod
    def _compact(report: Any) -> Any:
        if not isinstance(report, dict):
            return report
        results = report.get("results")
        failed = next((result for result in results if isinstance(result, dict) and result.get("status") != "PASS"), None) if isinstance(results, list) else None
        return {
            key: report.get(key)
            for key in ("status", "objective_id", "gate_id", "phase", "checks_run", "checks_total", "diagnosis")
        } | {"failed_check": failed}

    @staticmethod
    def _summary(state: dict[str, Any], resolved: ResolvedProfile) -> list[dict[str, Any]]:
        return [{"id": objective.id, "status": state["objectives"][objective.id]["status"], "attempts_used": state["objectives"][objective.id]["attempts_used"], "budget_epoch": state["objectives"][objective.id]["budget_epoch"], "review_rounds": state["objectives"][objective.id]["review_rounds"]} for objective in resolved.objectives]

    def _status_view(self, state: dict[str, Any], resolved: ResolvedProfile) -> dict[str, Any]:
        summary = self._summary(state, resolved)
        completed = sum(item["status"] == "COMPLETE" for item in summary)
        blocked = any(item["status"] == "BLOCKED" for item in summary) or any(item["status"] == "BLOCKED" for item in state["gates"].values())
        status = "BLOCKED" if blocked else "COMPLETE" if state.get("completion") else "ACTIVE"
        return {"run_id": state["run_id"], "milestone_id": state["milestone_id"], "profile_id": state["profile_id"], "status": status, "progress": {"completed": completed, "total": len(summary)}, "active_work_item": state.get("active_work_item"), "objectives": summary, "gates": state["gates"], "completion": state.get("completion")}

    @staticmethod
    def _evaluator_drift_authorized(state: dict[str, Any], current_digest: str) -> bool:
        active = state.get("active_work_item")
        if isinstance(active, dict) and active.get("type") == "EVALUATOR_REPAIR":
            return True
        return any(
            isinstance(progress, dict)
            and progress.get("status") in {"EVALUATOR_REPAIR_REQUIRED", "BLOCKED"}
            and isinstance(progress.get("active_gap"), dict)
            and progress["active_gap"].get("kind") == "EVALUATOR_GAP"
            and progress["active_gap"].get("pending_evaluator_digest") == current_digest
            for progress in state.get("objectives", {}).values()
        )


def _new_progress() -> dict[str, Any]:
    return {
        "status": "PENDING",
        "budget_epoch": 0,
        "attempts_used": 0,
        "replans": 0,
        "review_rounds": 0,
        "added_checks": [],
        "check_anchors": {},
        "best_score": -1,
        "stagnant_attempts": 0,
        "failure_fingerprint": None,
        "active_gap": None,
        "last_result": None,
        "last_worker_actor": None,
        "completion_reason": None,
    }


def _new_gate_progress() -> dict[str, Any]:
    return {
        "status": "PENDING",
        "last_result": None,
        "phase_results": {},
        "approval_digest": None,
        "approval_challenge_digest": None,
        "approval_before_preflight": False,
        "capture_product_digest": None,
        "capture_outputs": {},
    }


def _paths_intersect(left: Iterable[str], right: Iterable[str]) -> bool:
    return any(_path_overlap(a, b) for a in left for b in right)


def _path_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right.rstrip("/") + "/") or right.startswith(left.rstrip("/") + "/")


def _absolute_path_overlap(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)
