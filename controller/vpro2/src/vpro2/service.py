from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from .budgets import BudgetError, BudgetLedger
from .contracts import ContractError, load_contract
from .delta import DeltaKind, GoalDelta
from .evaluation import build_goal_state, goal_state_from_dict, goal_state_to_dict
from .gap_graph import GapGraph, GoalState
from .history import PathLedger, PathOutcome
from .integrity import (
    IntegrityError,
    canonical_digest,
    changed_paths,
    file_digest,
    manifest_diff,
    prepare_write_parents,
    resolve_inside,
    restore_workspace,
    snapshot_workspace,
    tree_manifest,
    unauthorized_changes,
)
from .models import MilestoneContract
from .planner import ObjectiveProposal, ProposalAudit, audit_and_rank
from .roles import Authority, AuthorityError, AuthorityVerifier, VerifiedEnvelope
from .runner import EvaluatorError, EvaluatorRun, EvaluatorRunner, ToolSeal, new_evaluation_id
from .store import StateStore, StateStoreError


STATE_SCHEMA = "vpro2-state-v1"
TERMINAL_SCHEMA = "vpro2-terminal-receipt-v1"
TERMINAL_STATUSES = frozenset(
    {
        "SUCCESS",
        "FAILED_STAGNATION",
        "FAILED_NO_LEGAL_PLAN",
        "FAILED_ENVIRONMENT_BLOCKED",
        "FAILED_BUDGET_EXHAUSTED",
        "FAILED_INTEGRITY",
        "FAILED_OPERATOR_ABORT",
    }
)


class VPro2ServiceError(RuntimeError):
    pass


class VPro2Controller:
    """Goal-driven VPRO2 state machine over one immutable milestone contract."""

    def __init__(
        self,
        *,
        project_root: Path,
        workspace_root: Path,
        contract_path: Path,
        run_root: Path,
        framework_digest: str,
        state_seal_key: bytes,
        authority_keys: Mapping[Authority | str, bytes],
    ):
        self.project_root = Path(project_root).resolve()
        self.workspace_root = Path(workspace_root).resolve()
        self.contract_path = Path(contract_path).resolve()
        self.run_root = Path(run_root).resolve()
        self.framework_digest = framework_digest
        if not self.project_root.is_relative_to(self.workspace_root):
            raise VPro2ServiceError("project root must be inside the worker workspace")
        if self.run_root.is_relative_to(self.workspace_root) or self.workspace_root.is_relative_to(self.run_root):
            raise VPro2ServiceError("controller run root and worker workspace must be disjoint")
        if self.contract_path.is_relative_to(self.workspace_root):
            raise VPro2ServiceError("milestone contract must be outside the worker workspace")
        if self.contract_path.is_relative_to(self.run_root):
            raise VPro2ServiceError("milestone contract must be outside the controller run root")
        if len(framework_digest) != 64 or any(character not in "0123456789abcdef" for character in framework_digest):
            raise VPro2ServiceError("framework digest must be a SHA-256 hex digest")
        if any(state_seal_key == value for value in authority_keys.values()):
            raise VPro2ServiceError("state and role authorities must use distinct keys")
        self.authorities = AuthorityVerifier(authority_keys)
        self.store = StateStore(self.run_root, seal_key=state_seal_key)

    def bind_challenge(self, *, run_id: str) -> dict[str, Any]:
        contract = self._contract()
        return {
            "contract_digest": file_digest(self.contract_path),
            "milestone_id": contract.milestone.id,
            "product_digest": self._product_digest(contract),
            "framework_digest": self.framework_digest,
        }

    def bind(self, *, run_id: str, operator_envelope: Mapping[str, Any]) -> dict[str, Any]:
        if not run_id or len(run_id) > 128:
            raise VPro2ServiceError("run_id is invalid")
        contract = self._contract()
        challenge = self.bind_challenge(run_id=run_id)
        verified = self.authorities.verify(
            operator_envelope,
            run_id=run_id,
            expected_role=Authority.OPERATOR,
            expected_action="BIND",
        )
        if verified.payload != challenge:
            raise VPro2ServiceError("operator bind approval does not match the current authorities")
        tools = EvaluatorRunner.seal_tools(
            contract.safety.allowed_tools,
            workspace_root=self.workspace_root,
            run_root=self.run_root,
        )
        with self.store.locked():
            if self.store.exists():
                raise VPro2ServiceError("run is already bound")
            unexpected = [
                path
                for path in self.run_root.rglob("*")
                if (path.is_file() or path.is_symlink()) and path != self.store.lock_path
            ]
            if unexpected:
                raise VPro2ServiceError("bind requires a new empty run root")
            created = int(time.time())
            state: dict[str, Any] = {
                "schema_version": STATE_SCHEMA,
                "run_id": run_id,
                "milestone_id": contract.milestone.id,
                "milestone_version": contract.milestone.version,
                "framework_digest": self.framework_digest,
                "contract_digest": challenge["contract_digest"],
                "product_digest": challenge["product_digest"],
                "evaluator_digest": self._evaluator_digest(contract),
                "authority_key_ids": self.authorities.key_ids,
                "state_seal_key_id": self.store.seal_key_id,
                "tool_seals": {name: asdict(seal) for name, seal in tools.items()},
                "created_at_unix": created,
                "phase": "PRE_EVALUATE",
                "iteration": 0,
                "goal_states": [],
                "gap_graphs": [],
                "goal_deltas": [],
                "evaluation_history": [],
                "path_ledger": [],
                "candidate": None,
                "active_objective": None,
                "used_authority_nonces": [verified.nonce],
                "reviews": [],
                "budget": BudgetLedger.fresh(now=created).as_dict(),
                "planning_rounds_current_iteration": 0,
                "consecutive_no_material_progress": 0,
                "consecutive_environment_blocked": 0,
                "environment_blocked_condition_ids": [],
                "no_legal_plan_rounds": 0,
                "capability_uses": {},
                "terminal": None,
                "events": [],
                "last_event_hash": None,
            }
            sealed_contract = {
                "schema_version": contract.schema_version,
                "contract_digest": state["contract_digest"],
                "milestone_id": contract.milestone.id,
                "framework_digest": self.framework_digest,
            }
            self.store.save_contract(sealed_contract)
            self._event(state, "RUN_BOUND", Authority.OPERATOR, {"nonce": verified.nonce})
            self.store.save(state)
            return self._status_view(state)

    def status(self) -> dict[str, Any]:
        contract = self._contract()
        with self.store.locked():
            state = self._state(contract)
            return self._status_view(state)

    def audit(self) -> dict[str, Any]:
        contract = self._contract()
        with self.store.locked():
            state = self._state(contract)
            artifact_errors = self._audit_evaluation_artifacts(state, contract)
            if artifact_errors:
                self._terminal(state, contract, "FAILED_INTEGRITY", "; ".join(artifact_errors))
                self.store.save(state)
                raise VPro2ServiceError("evaluation history integrity failure")
            return {
                "status": "PASS",
                "run_id": state["run_id"],
                "phase": state["phase"],
                "event_count": len(state["events"]),
                "last_event_hash": state["last_event_hash"],
                "contract_digest": state["contract_digest"],
                "product_digest": state["product_digest"],
                "evaluator_digest": state["evaluator_digest"],
                "goal_state_count": len(state["goal_states"]),
                "goal_delta_count": len(state["goal_deltas"]),
                "path_attempt_count": len(state["path_ledger"]),
            }

    def verify_terminal(self) -> dict[str, Any]:
        contract = self._contract()
        with self.store.locked():
            try:
                state = self._state(contract)
            except VPro2ServiceError:
                emergency = self._verify_emergency_receipt()
                if emergency is not None:
                    return emergency
                raise
            if state.get("terminal") is None or not self.store.terminal_path.is_file():
                raise VPro2ServiceError("run has no terminal receipt")
            try:
                receipt = json.loads(self.store.terminal_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise VPro2ServiceError(f"terminal receipt is unreadable: {exc}") from exc
            if not isinstance(receipt, dict):
                raise VPro2ServiceError("terminal receipt must be an object")
            claimed = receipt.get("receipt_tag")
            unsigned = {key: value for key, value in receipt.items() if key != "receipt_tag"}
            expected = self.store.authentication_tag("vpro2-terminal-receipt-v1", unsigned)
            if claimed != expected:
                raise VPro2ServiceError("terminal receipt authentication failed")
            if receipt.get("last_event_hash") != state.get("last_event_hash"):
                raise VPro2ServiceError("terminal receipt event binding mismatch")
            if receipt.get("state_payload_digest") != self.store.payload_digest(state):
                raise VPro2ServiceError("terminal receipt state binding mismatch")
            for key, value in state["terminal"].items():
                if receipt.get(key) != value:
                    raise VPro2ServiceError(f"terminal receipt field drift: {key}")
            if (
                state["terminal"]["status"] == "SUCCESS"
                and receipt.get("product_digest") != self._product_digest(contract)
            ):
                raise VPro2ServiceError("terminal receipt product binding is no longer current")
            artifact_errors = self._audit_evaluation_artifacts(
                state,
                contract,
                require_current=state["terminal"]["status"] == "SUCCESS",
            )
            if artifact_errors:
                raise VPro2ServiceError(f"terminal evaluation artifacts drifted: {artifact_errors}")
            if state["terminal"]["status"] == "SUCCESS":
                if state.get("active_objective") is not None:
                    raise VPro2ServiceError("successful terminal state retains active work")
                goal_state = self._current_goal_state(state)
                if not self._completion_eligible(goal_state):
                    raise VPro2ServiceError("successful terminal state lacks complete current evidence")
            return {
                "status": "PASS",
                "run_id": state["run_id"],
                "terminal_status": state["terminal"]["status"],
                "receipt_tag": claimed,
                "last_event_hash": state["last_event_hash"],
            }

    def _verify_emergency_receipt(self) -> dict[str, Any] | None:
        if not self.store.terminal_path.is_file():
            return None
        try:
            receipt = json.loads(self.store.terminal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(receipt, dict) or receipt.get("status") != "FAILED_INTEGRITY":
            return None
        if not isinstance(receipt.get("errors"), list) or not receipt["errors"]:
            return None
        claimed = receipt.get("receipt_tag")
        unsigned = {key: value for key, value in receipt.items() if key != "receipt_tag"}
        expected = self.store.authentication_tag("vpro2-emergency-integrity-v1", unsigned)
        if claimed != expected:
            raise VPro2ServiceError("emergency integrity receipt authentication failed")
        return {
            "status": "PASS",
            "run_id": receipt.get("run_id"),
            "terminal_status": "FAILED_INTEGRITY",
            "receipt_tag": claimed,
            "emergency": True,
        }

    def evaluate(self) -> dict[str, Any]:
        contract = self._contract()
        with self.store.locked():
            state = self._state(contract)
            if state["terminal"] is not None:
                return self._status_view(state)
            if state["phase"] not in {"PRE_EVALUATE", "POST_EVALUATE", "FINAL_EVALUATE"}:
                raise VPro2ServiceError(f"evaluation is not allowed in phase {state['phase']}")
            phase = state["phase"]
            try:
                if phase == "POST_EVALUATE":
                    self._verify_worker_candidate(state)
                goal_state = self._run_evaluation(state, contract, phase)
                if phase == "POST_EVALUATE":
                    self._verify_worker_candidate(state)
            except BudgetError as exc:
                self._terminate_after_rollback(
                    state, contract, "FAILED_BUDGET_EXHAUSTED", str(exc)
                )
                self.store.save(state)
                return self._status_view(state)
            except (EvaluatorError, IntegrityError, OSError, subprocess.SubprocessError) as exc:
                self._terminate_after_rollback(state, contract, "FAILED_INTEGRITY", str(exc))
                self.store.save(state)
                return self._status_view(state)

            state["goal_states"].append(goal_state_to_dict(goal_state))
            self._event(
                state,
                "GOAL_STATE_SEALED",
                Authority.EVALUATOR,
                {"phase": phase, "goal_state_digest": goal_state.state_digest},
            )
            if phase == "POST_EVALUATE":
                self._decide_objective(state, contract, goal_state)
            elif phase == "FINAL_EVALUATE":
                if self._completion_eligible(goal_state):
                    state["product_digest"] = self._product_digest(contract)
                    self._terminal(state, contract, "SUCCESS", "all required conditions have current trusted evidence")
                else:
                    self._observe_environment_state(state, contract, goal_state)
                    if state["terminal"] is None:
                        self._install_gap_graph(state, goal_state)
                        state["phase"] = "PLANNING"
            elif self._completion_eligible(goal_state):
                state["phase"] = "FINAL_EVALUATE"
                self._event(state, "FINAL_REEVALUATION_REQUIRED", Authority.CONTROLLER, {})
            else:
                self._observe_environment_state(state, contract, goal_state)
                if state["terminal"] is None:
                    self._install_gap_graph(state, goal_state)
                    state["phase"] = "PLANNING"
            if state["terminal"] is None:
                self._event(
                    state,
                    "EVALUATION_PHASE_COMMITTED",
                    Authority.CONTROLLER,
                    {"phase": state["phase"], "goal_state_digest": goal_state.state_digest},
                )
            self.store.save(state)
            return self._status_view(state)

    def submit_plan(self, controller_envelope: Mapping[str, Any]) -> dict[str, Any]:
        contract = self._contract()
        with self.store.locked():
            state = self._state(contract)
            self._require_phase(state, "PLANNING")
            verified = self._verify_envelope(
                state,
                controller_envelope,
                role=Authority.CONTROLLER,
                action="PROPOSE_OBJECTIVES",
            )
            if (
                state["planning_rounds_current_iteration"]
                >= contract.resource_budget.max_planning_rounds_per_iteration
            ):
                self._terminal(
                    state,
                    contract,
                    "FAILED_BUDGET_EXHAUSTED",
                    "per-iteration planning round budget exhausted",
                )
                self.store.save(state)
                return self._status_view(state)
            payload = verified.payload
            if set(payload) != {"goal_state_digest", "proposals"}:
                raise VPro2ServiceError("controller plan payload fields are invalid")
            current_goal = self._current_goal_state(state)
            if payload["goal_state_digest"] != current_goal.state_digest:
                raise VPro2ServiceError("controller plan is stale for the current Goal State")
            raw_proposals = payload["proposals"]
            if not isinstance(raw_proposals, list):
                raise VPro2ServiceError("controller proposals must be an array")
            if len(raw_proposals) > 64:
                raise VPro2ServiceError("a planning round may contain at most 64 proposals")
            if len(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()) > contract.resource_budget.max_context_bytes:
                raise VPro2ServiceError("controller plan exceeds the context budget")
            proposals = tuple(self._parse_proposal(item) for item in raw_proposals)
            budget = BudgetLedger.from_dict(state["budget"])
            try:
                budget.charge_planning_round(contract.resource_budget)
            except BudgetError as exc:
                self._terminal(state, contract, "FAILED_BUDGET_EXHAUSTED", str(exc))
                self.store.save(state)
                return self._status_view(state)
            state["planning_rounds_current_iteration"] += 1
            ledger = PathLedger.from_list(state["path_ledger"])
            graph = GapGraph.from_goal_state(current_goal)
            result = audit_and_rank(
                proposals,
                contract=contract,
                graph=graph,
                ledger=ledger,
                evidence_basis_digest=current_goal.evidence_basis_digest,
                limits=budget.remaining_limits(
                    contract.resource_budget,
                    capability_uses=tuple(sorted(state["capability_uses"].items())),
                ),
            )
            state["budget"] = budget.as_dict()
            rejected = [self._audit_to_dict(item) for item in result.rejected]
            if not result.ranked:
                state["no_legal_plan_rounds"] += 1
                self._event(
                    state,
                    "NO_LEGAL_OBJECTIVE",
                    Authority.CONTROLLER,
                    {"rejected": rejected, "proposal_count": len(proposals)},
                )
                if state["no_legal_plan_rounds"] >= contract.termination.max_no_legal_plan_rounds:
                    self._terminal(
                        state,
                        contract,
                        "FAILED_NO_LEGAL_PLAN",
                        "no legal non-repeated objective remained",
                    )
                self.store.save(state)
                return self._status_view(state)

            selected = result.ranked[0]
            state["candidate"] = {
                "proposal": self._proposal_to_dict(selected.proposal),
                "audit": self._audit_to_dict(selected),
                "goal_state_digest": current_goal.state_digest,
                "gap_graph_digest": graph.graph_digest,
                "evidence_basis_digest": current_goal.evidence_basis_digest,
                "plan_nonce": verified.nonce,
                "rejected_candidates": rejected,
            }
            state["phase"] = "PLAN_REVIEW"
            self._event(
                state,
                "TEMPORARY_OBJECTIVE_SELECTED",
                Authority.CONTROLLER,
                {
                    "objective_id": selected.proposal.objective_id,
                    "path_fingerprint": selected.path_assessment.fingerprint,
                    "impact_score": selected.impact_score,
                },
            )
            self.store.save(state)
            return self._status_view(state)

    def review_plan(self, reviewer_envelope: Mapping[str, Any]) -> dict[str, Any]:
        contract = self._contract()
        with self.store.locked():
            state = self._state(contract)
            self._require_phase(state, "PLAN_REVIEW")
            verified = self._verify_envelope(
                state,
                reviewer_envelope,
                role=Authority.REVIEWER,
                action="REVIEW_PLAN",
            )
            candidate = self._candidate(state)
            proposal = self._parse_proposal(candidate["proposal"])
            payload = verified.payload
            required = {
                "objective_id",
                "goal_state_digest",
                "gap_graph_digest",
                "decision",
                "reason",
            }
            if set(payload) != required:
                raise VPro2ServiceError("plan review payload fields are invalid")
            if (
                payload["objective_id"] != proposal.objective_id
                or payload["goal_state_digest"] != candidate["goal_state_digest"]
                or payload["gap_graph_digest"] != candidate["gap_graph_digest"]
            ):
                raise VPro2ServiceError("plan review is stale or bound to another objective")
            if payload["decision"] not in {"APPROVE", "REJECT"}:
                raise VPro2ServiceError("plan review decision must be APPROVE or REJECT")
            if (
                not isinstance(payload["reason"], str)
                or not payload["reason"].strip()
                or len(payload["reason"].encode()) > 4096
            ):
                raise VPro2ServiceError("plan review reason is required")
            review = {
                **payload,
                "stage": "PLAN",
                "nonce": verified.nonce,
                "reviewer_key_id": verified.key_id,
            }
            state["reviews"].append(review)
            if payload["decision"] == "REJECT":
                self._record_path(state, proposal, PathOutcome.REJECTED)
                state["candidate"] = None
                state["phase"] = "PLANNING"
                self._event(
                    state,
                    "PLAN_REJECTED",
                    Authority.REVIEWER,
                    {"objective_id": proposal.objective_id, "reason": payload["reason"]},
                )
            else:
                audit = candidate["audit"]
                if audit.get("requires_operator_approval"):
                    state["phase"] = "OPERATOR_APPROVAL"
                    self._event(
                        state,
                        "OPERATOR_APPROVAL_REQUIRED",
                        Authority.REVIEWER,
                        self._approval_binding(state, candidate),
                    )
                else:
                    self._activate_objective(state, contract)
            self.store.save(state)
            return self._status_view(state)

    def approve_objective(self, operator_envelope: Mapping[str, Any]) -> dict[str, Any]:
        contract = self._contract()
        with self.store.locked():
            state = self._state(contract)
            self._require_phase(state, "OPERATOR_APPROVAL")
            verified = self._verify_envelope(
                state,
                operator_envelope,
                role=Authority.OPERATOR,
                action="APPROVE_OBJECTIVE",
            )
            candidate = self._candidate(state)
            if verified.payload != self._approval_binding(state, candidate):
                raise VPro2ServiceError("operator approval does not match the selected objective")
            budget = BudgetLedger.from_dict(state["budget"])
            try:
                budget.charge_operator_run(contract.resource_budget)
            except BudgetError as exc:
                self._terminal(state, contract, "FAILED_BUDGET_EXHAUSTED", str(exc))
                self.store.save(state)
                return self._status_view(state)
            state["budget"] = budget.as_dict()
            self._event(
                state,
                "OBJECTIVE_APPROVED",
                Authority.OPERATOR,
                {"objective_id": candidate["proposal"]["objective_id"], "nonce": verified.nonce},
            )
            self._activate_objective(state, contract)
            self.store.save(state)
            return self._status_view(state)

    def submit_worker_result(self, worker_envelope: Mapping[str, Any]) -> dict[str, Any]:
        contract = self._contract()
        with self.store.locked():
            state = self._state(contract)
            self._require_phase(state, "WORKER_ACTIVE")
            verified = self._verify_envelope(
                state,
                worker_envelope,
                role=Authority.WORKER,
                action="COMPLETE_OBJECTIVE",
            )
            active = self._active(state)
            payload = verified.payload
            required = {"objective_id", "work_item_id", "transaction_id", "work_token", "summary"}
            if set(payload) != required:
                raise VPro2ServiceError("worker result payload fields are invalid")
            for key in ("objective_id", "work_item_id", "transaction_id", "work_token"):
                if payload[key] != active[key]:
                    raise VPro2ServiceError(f"worker result has stale or false {key}")
            if (
                not isinstance(payload["summary"], str)
                or not payload["summary"].strip()
                or len(payload["summary"].encode()) > 4096
            ):
                raise VPro2ServiceError("worker summary is required")
            try:
                before = self._load_manifest_record(active["baseline_manifest"])
                after = tree_manifest(self.workspace_root)
                diff = manifest_diff(before, after)
                unauthorized = unauthorized_changes(
                    diff,
                    self._workspace_relative_paths(active["proposal"]["write_paths"]),
                )
                if unauthorized:
                    raise IntegrityError(f"worker changed unauthorized paths: {list(unauthorized)}")
                changed_size = self._changed_size(after, changed_paths(diff))
                if changed_size > active["proposal"]["estimated_write_bytes"]:
                    raise IntegrityError("worker exceeded the objective write-byte reservation")
                elapsed = max(0, int(time.time()) - active["issued_at_unix"])
                if elapsed > active["proposal"]["estimated_worker_seconds"]:
                    raise IntegrityError("worker exceeded the objective time reservation")
                result_manifest = self._write_manifest_record(
                    Path(active["transaction_root"]) / "worker-result-manifest.json",
                    after,
                )
            except (IntegrityError, OSError, ValueError) as exc:
                self._terminate_after_rollback(state, contract, "FAILED_INTEGRITY", str(exc))
                self.store.save(state)
                return self._status_view(state)
            active["worker_result"] = {
                "summary": payload["summary"],
                "nonce": verified.nonce,
                "worker_key_id": verified.key_id,
                "workspace_diff": diff,
                "changed_bytes": changed_size,
                "result_manifest": result_manifest,
            }
            state["phase"] = "CHANGE_REVIEW"
            self._event(
                state,
                "WORKER_RESULT_SCOPED",
                Authority.WORKER,
                {"objective_id": active["objective_id"], "changed_paths": list(changed_paths(diff))},
            )
            self.store.save(state)
            return self._status_view(state)

    def review_change(self, reviewer_envelope: Mapping[str, Any]) -> dict[str, Any]:
        contract = self._contract()
        with self.store.locked():
            state = self._state(contract)
            self._require_phase(state, "CHANGE_REVIEW")
            verified = self._verify_envelope(
                state,
                reviewer_envelope,
                role=Authority.REVIEWER,
                action="REVIEW_CHANGE",
            )
            active = self._active(state)
            try:
                self._verify_worker_candidate(state)
            except IntegrityError as exc:
                self._terminate_after_rollback(state, contract, "FAILED_INTEGRITY", str(exc))
                self.store.save(state)
                return self._status_view(state)
            payload = verified.payload
            required = {"objective_id", "work_item_id", "decision", "reason"}
            if set(payload) != required:
                raise VPro2ServiceError("change review payload fields are invalid")
            if payload["objective_id"] != active["objective_id"] or payload["work_item_id"] != active["work_item_id"]:
                raise VPro2ServiceError("change review is bound to another objective")
            if payload["decision"] not in {"ACCEPT_FOR_EVALUATION", "INTEGRITY_REJECT"}:
                raise VPro2ServiceError("invalid change review decision")
            if (
                not isinstance(payload["reason"], str)
                or not payload["reason"].strip()
                or len(payload["reason"].encode()) > 4096
            ):
                raise VPro2ServiceError("change review reason is required")
            state["reviews"].append(
                {
                    **payload,
                    "stage": "CHANGE",
                    "nonce": verified.nonce,
                    "reviewer_key_id": verified.key_id,
                }
            )
            if payload["decision"] == "INTEGRITY_REJECT":
                self._terminate_after_rollback(
                    state, contract, "FAILED_INTEGRITY", payload["reason"]
                )
            else:
                state["phase"] = "POST_EVALUATE"
                self._event(
                    state,
                    "CHANGE_ACCEPTED_FOR_EVALUATION",
                    Authority.REVIEWER,
                    {"objective_id": active["objective_id"]},
                )
            self.store.save(state)
            return self._status_view(state)

    def abort(self, operator_envelope: Mapping[str, Any]) -> dict[str, Any]:
        contract = self._contract()
        with self.store.locked():
            state = self._state(contract)
            if state["terminal"] is not None:
                return self._status_view(state)
            verified = self._verify_envelope(
                state,
                operator_envelope,
                role=Authority.OPERATOR,
                action="ABORT",
            )
            if (
                set(verified.payload) != {"reason"}
                or not isinstance(verified.payload["reason"], str)
                or not verified.payload["reason"].strip()
                or len(verified.payload["reason"].encode()) > 4096
            ):
                raise VPro2ServiceError("operator abort requires a reason")
            self._terminate_after_rollback(
                state, contract, "FAILED_OPERATOR_ABORT", verified.payload["reason"]
            )
            self.store.save(state)
            return self._status_view(state)

    def _contract(self) -> MilestoneContract:
        try:
            return load_contract(self.contract_path, project_root=self.project_root)
        except ContractError as exc:
            raise VPro2ServiceError(str(exc)) from exc

    def _state(self, contract: MilestoneContract) -> dict[str, Any]:
        try:
            state = self.store.load()
        except StateStoreError as exc:
            raise VPro2ServiceError(str(exc)) from exc
        errors = self.store.verify(state)
        if errors:
            self._emergency_integrity_receipt(state, errors)
            raise VPro2ServiceError(f"controller state authentication failed: {errors}")
        expected = {
            "schema_version": STATE_SCHEMA,
            "framework_digest": self.framework_digest,
            "contract_digest": file_digest(self.contract_path),
            "evaluator_digest": self._evaluator_digest(contract),
            "state_seal_key_id": self.store.seal_key_id,
            "authority_key_ids": self.authorities.key_ids,
        }
        drift = [key for key, value in expected.items() if state.get(key) != value]
        if drift:
            if state.get("terminal") is not None:
                raise VPro2ServiceError(f"terminal immutable authority drift: {sorted(drift)}")
            self._terminal(
                state,
                contract,
                "FAILED_INTEGRITY",
                f"immutable authority drift: {sorted(drift)}",
            )
            self.store.save(state)
        if state.get("schema_version") != STATE_SCHEMA:
            raise VPro2ServiceError("unsupported VPRO2 state schema")
        if state.get("terminal") is None and self._remaining_wall_seconds(state, contract) <= 0:
            self._terminate_after_rollback(
                state,
                contract,
                "FAILED_BUDGET_EXHAUSTED",
                "absolute run wall-clock deadline expired",
            )
            self.store.save(state)
            return state
        if state.get("terminal") is None and state.get("active_objective") is None:
            product_digest = self._product_digest(contract)
            if product_digest != state.get("product_digest"):
                self._terminal(state, contract, "FAILED_INTEGRITY", "product changed outside a temporary objective")
                self.store.save(state)
        return state

    def _run_evaluation(
        self,
        state: dict[str, Any],
        contract: MilestoneContract,
        phase: str,
    ) -> GoalState:
        ledger = BudgetLedger.from_dict(state["budget"])
        ledger.ensure_run_available(contract.resource_budget)
        declared_seconds = sum(item.timeout_seconds for item in contract.evaluators)
        declared_cost = sum(item.cost_units for item in contract.evaluators)
        if declared_seconds > self._remaining_wall_seconds(state, contract):
            raise BudgetError("complete evaluation cannot fit the remaining wall-clock budget")
        evidence_root = self.run_root / "evidence"
        evidence_root.mkdir(parents=True, exist_ok=True)
        evidence_manifest = tree_manifest(evidence_root)
        raw_evidence_bytes = sum(
            item["size"] for item in evidence_manifest.values() if item["kind"] == "file"
        )
        reservation = None
        if phase == "POST_EVALUATE" and state.get("active_objective") is not None:
            reservation = state["active_objective"]["proposal"]
            if declared_seconds > reservation["estimated_evaluator_seconds"]:
                raise BudgetError("post-objective evaluator timeout exceeds its reservation")
            if declared_cost > reservation["estimated_cost_units"]:
                raise BudgetError("post-objective evaluator cost exceeds its reservation")
        else:
            if ledger.evaluator_seconds + declared_seconds > contract.resource_budget.max_evaluator_seconds:
                raise BudgetError("complete evaluation cannot fit the remaining evaluator time budget")
            if ledger.cost_units + declared_cost > contract.resource_budget.max_cost_units:
                raise BudgetError("complete evaluation cannot fit the remaining cost budget")
        if raw_evidence_bytes + ledger.evidence_bytes > contract.resource_budget.max_evidence_bytes:
            raise BudgetError("raw evidence cannot fit the remaining evidence budget")
        evaluation_id = new_evaluation_id(state["iteration"], phase)
        current_product = self._product_digest(contract)
        runner = EvaluatorRunner(
            project_root=self.project_root,
            workspace_root=self.workspace_root,
            run_root=self.run_root,
            contract=contract,
            tool_seals={name: ToolSeal(**value) for name, value in state["tool_seals"].items()},
        )
        runs = tuple(
            runner.run(
                evaluator,
                run_id=state["run_id"],
                product_digest=current_product,
                evaluation_id=evaluation_id,
            )
            for evaluator in contract.evaluators
        )
        if self._remaining_wall_seconds(state, contract) <= 0:
            raise BudgetError("complete evaluation crossed the absolute wall-clock deadline")
        elapsed = sum(run.duration_seconds for run in runs)
        cost = sum(contract.evaluator(run.evaluator_id).cost_units for run in runs)
        evidence_bytes = self._evaluation_artifact_bytes(runs)
        if reservation is not None:
            if elapsed > reservation["estimated_evaluator_seconds"]:
                raise BudgetError("post-objective evaluator time exceeded its reservation")
            if cost > reservation["estimated_cost_units"]:
                raise BudgetError("post-objective evaluator cost exceeded its reservation")
            if evidence_bytes + ledger.evidence_bytes > contract.resource_budget.max_evidence_bytes:
                raise BudgetError("post-objective evidence exceeded the global budget")
            ledger.evidence_bytes += evidence_bytes
        else:
            ledger.charge_evaluation(
                seconds=elapsed,
                cost_units=cost,
                evidence_bytes=evidence_bytes,
                budget=contract.resource_budget,
            )
        state["budget"] = ledger.as_dict()
        goal_state = build_goal_state(
            contract,
            runs,
            iteration=state["iteration"],
            evidence_root=self.run_root / "evidence",
        )
        history = {
            "evaluation_id": evaluation_id,
            "phase": phase,
            "iteration": state["iteration"],
            "product_digest": current_product,
            "goal_state_digest": goal_state.state_digest,
            "runs": [self._run_to_dict(run) for run in runs],
        }
        history["history_digest"] = canonical_digest(history)
        state["evaluation_history"].append(history)
        return goal_state

    def _decide_objective(
        self,
        state: dict[str, Any],
        contract: MilestoneContract,
        after: GoalState,
    ) -> None:
        active = self._active(state)
        if len(state["goal_states"]) < 2:
            raise VPro2ServiceError("post evaluation has no baseline Goal State")
        before = goal_state_from_dict(state["goal_states"][-2])
        if before.state_digest != active["baseline_goal_state_digest"]:
            raise VPro2ServiceError("active objective baseline Goal State drifted")
        delta = GoalDelta.between(before, after)
        delta_record = {
            "iteration": state["iteration"],
            "objective_id": active["objective_id"],
            "before_goal_state_digest": before.state_digest,
            "after_goal_state_digest": after.state_digest,
            "kind": delta.kind.value,
            "newly_proven_condition_ids": list(delta.newly_proven_condition_ids),
            "regressed_condition_ids": list(delta.regressed_condition_ids),
            "information_changed": delta.information_changed,
            "before_gap_digest": delta.before_gap_digest,
            "after_gap_digest": delta.after_gap_digest,
            "product_digest": self._product_digest(contract),
        }
        delta_record["delta_digest"] = canonical_digest(delta_record)
        state["goal_deltas"].append(delta_record)
        state["iteration"] += 1
        budget = BudgetLedger.from_dict(state["budget"])
        budget.iterations += 1
        state["budget"] = budget.as_dict()
        proposal = self._parse_proposal(active["proposal"])

        if delta.kind is DeltaKind.MATERIAL_PROGRESS:
            self._record_path(state, proposal, PathOutcome.MATERIAL_PROGRESS)
            state["product_digest"] = self._product_digest(contract)
            state["consecutive_no_material_progress"] = 0
            state["no_legal_plan_rounds"] = 0
            decision = "RETAINED"
        else:
            outcome = {
                DeltaKind.INFORMATION_GAIN: PathOutcome.INFORMATION_GAIN,
                DeltaKind.NO_PROGRESS: PathOutcome.NO_PROGRESS,
                DeltaKind.REGRESSION: PathOutcome.REGRESSION,
            }[delta.kind]
            self._record_path(state, proposal, outcome)
            rollback_error = self._rollback_active(state)
            if rollback_error is not None:
                state["candidate"] = None
                self._event(
                    state,
                    "GOAL_DELTA_DECIDED",
                    Authority.CONTROLLER,
                    {
                        "objective_id": proposal.objective_id,
                        "delta_kind": delta.kind.value,
                        "decision": "ROLLBACK_FAILED",
                        "delta_digest": delta_record["delta_digest"],
                    },
                )
                self._terminal(state, contract, "FAILED_INTEGRITY", rollback_error)
                return
            state["product_digest"] = self._product_digest(contract)
            state["consecutive_no_material_progress"] += 1
            decision = "ROLLED_BACK_AND_ELIMINATED"
        state["candidate"] = None
        state["active_objective"] = None
        self._event(
            state,
            "GOAL_DELTA_DECIDED",
            Authority.CONTROLLER,
            {
                "objective_id": proposal.objective_id,
                "delta_kind": delta.kind.value,
                "decision": decision,
                "delta_digest": delta_record["delta_digest"],
            },
        )
        if state["terminal"] is not None:
            return
        if state["consecutive_no_material_progress"] >= contract.termination.max_consecutive_no_material_progress:
            self._terminal(
                state,
                contract,
                "FAILED_STAGNATION",
                "consecutive complete iterations produced no material Goal Delta",
            )
            return
        if budget.iterations >= contract.resource_budget.max_iterations:
            self._terminal(state, contract, "FAILED_BUDGET_EXHAUSTED", "iteration budget exhausted")
            return
        state["phase"] = "PRE_EVALUATE"
        state["planning_rounds_current_iteration"] = 0

    def _install_gap_graph(self, state: dict[str, Any], goal_state: GoalState) -> None:
        graph = GapGraph.from_goal_state(goal_state)
        record = {
            "goal_state_digest": goal_state.state_digest,
            "graph_digest": graph.graph_digest,
            "nodes": [asdict(item) for item in graph.nodes],
            "edges": [asdict(item) for item in graph.edges],
            "root_blockers": [asdict(item) for item in graph.root_blockers()],
        }
        state["gap_graphs"].append(record)
        self._event(
            state,
            "GAP_GRAPH_BUILT",
            Authority.CONTROLLER,
            {
                "graph_digest": graph.graph_digest,
                "root_condition_ids": list(graph.root_condition_ids),
            },
        )

    def _observe_environment_state(
        self,
        state: dict[str, Any],
        contract: MilestoneContract,
        goal_state: GoalState,
    ) -> None:
        required = [item for item in goal_state.evaluations if item.required]
        blocked = sorted(item.condition_id for item in required if item.status == "BLOCKED_ENV")
        if blocked and blocked == state.get("environment_blocked_condition_ids", []):
            state["consecutive_environment_blocked"] += 1
        elif blocked:
            state["consecutive_environment_blocked"] = 1
        else:
            state["consecutive_environment_blocked"] = 0
        state["environment_blocked_condition_ids"] = blocked
        if state["consecutive_environment_blocked"] >= contract.termination.max_consecutive_environment_blocked:
            self._terminal(
                state,
                contract,
                "FAILED_ENVIRONMENT_BLOCKED",
                "environment blocked consecutive milestone evaluations",
            )

    @staticmethod
    def _completion_eligible(goal_state: GoalState) -> bool:
        return all(item.is_proven_pass for item in goal_state.evaluations if item.required)

    def _activate_objective(self, state: dict[str, Any], contract: MilestoneContract) -> None:
        candidate = self._candidate(state)
        proposal = self._parse_proposal(candidate["proposal"])
        try:
            context_bytes = self._paths_size(proposal.context_paths)
        except (IntegrityError, OSError) as exc:
            self._terminal(state, contract, "FAILED_INTEGRITY", str(exc))
            return
        if context_bytes > proposal.estimated_context_bytes:
            self._terminal(
                state,
                contract,
                "FAILED_BUDGET_EXHAUSTED",
                "actual objective context exceeds its reservation",
            )
            return
        budget = BudgetLedger.from_dict(state["budget"])
        required_wall = proposal.estimated_worker_seconds + proposal.estimated_evaluator_seconds
        if required_wall > self._remaining_wall_seconds(state, contract):
            self._terminal(
                state,
                contract,
                "FAILED_BUDGET_EXHAUSTED",
                "objective and its full evaluation cannot fit the run wall-clock deadline",
            )
            return
        try:
            budget.reserve_objective(
                proposal,
                contract.resource_budget,
                diagnostic=not proposal.write_paths,
            )
        except BudgetError as exc:
            self._terminal(state, contract, "FAILED_BUDGET_EXHAUSTED", str(exc))
            return
        transaction_id = uuid.uuid4().hex
        transaction_root = self.run_root / "transactions" / transaction_id
        snapshot_root = transaction_root / "snapshot"
        snapshot_ready = False
        try:
            pre_snapshot = tree_manifest(self.workspace_root)
            transaction_bytes = sum(
                item["size"] for item in pre_snapshot.values() if item["kind"] == "file"
            )
            if budget.transaction_bytes + transaction_bytes > contract.resource_budget.max_transaction_bytes:
                raise BudgetError("workspace snapshot exceeds the transaction storage budget")
            snapshot_workspace(self.workspace_root, snapshot_root)
            if tree_manifest(snapshot_root) != pre_snapshot:
                raise IntegrityError("workspace changed while its rollback snapshot was captured")
            snapshot_ready = True
            snapshot_manifest_record = self._write_manifest_record(
                transaction_root / "snapshot-manifest.json", pre_snapshot
            )
            prepare_write_parents(self.project_root, proposal.write_paths)
            baseline = tree_manifest(self.workspace_root)
            baseline_record = self._write_manifest_record(
                transaction_root / "baseline-manifest.json", baseline
            )
        except BudgetError as exc:
            shutil.rmtree(transaction_root, ignore_errors=True)
            self._terminal(state, contract, "FAILED_BUDGET_EXHAUSTED", str(exc))
            return
        except (IntegrityError, OSError, ValueError) as exc:
            if snapshot_ready:
                restore_workspace(self.workspace_root, snapshot_root)
            shutil.rmtree(transaction_root, ignore_errors=True)
            self._terminal(state, contract, "FAILED_INTEGRITY", str(exc))
            return
        if self._remaining_wall_seconds(state, contract) <= 0:
            restore_workspace(self.workspace_root, snapshot_root)
            shutil.rmtree(transaction_root, ignore_errors=True)
            self._terminal(
                state,
                contract,
                "FAILED_BUDGET_EXHAUSTED",
                "workspace snapshot crossed the absolute wall-clock deadline",
            )
            return
        budget.transaction_bytes += transaction_bytes
        policies = {item.id: item for item in contract.safety.capability_policies}
        for capability in proposal.capabilities:
            used = state["capability_uses"].get(capability, 0)
            if used >= policies[capability].max_uses:
                self._terminal(
                    state,
                    contract,
                    "FAILED_BUDGET_EXHAUSTED",
                    f"capability use budget exhausted: {capability}",
                )
                return
        for capability in proposal.capabilities:
            state["capability_uses"][capability] = state["capability_uses"].get(capability, 0) + 1
        work_item_id = uuid.uuid4().hex
        token_material = {
            "run_id": state["run_id"],
            "objective_id": proposal.objective_id,
            "work_item_id": work_item_id,
            "transaction_id": transaction_id,
            "goal_state_digest": candidate["goal_state_digest"],
            "product_digest": state["product_digest"],
            "baseline_manifest_digest": baseline_record["sha256"],
            "strategy_fingerprint": candidate["audit"]["path_fingerprint"],
            "context_paths": list(proposal.context_paths),
            "context_digest": self._paths_digest(proposal.context_paths),
            "context_bytes": context_bytes,
            "write_paths": list(proposal.write_paths),
            "capabilities": list(proposal.capabilities),
            "forbidden_effects": list(contract.safety.forbidden_effects),
            "budget_reservation": {
                "cost_units": proposal.estimated_cost_units,
                "context_bytes": proposal.estimated_context_bytes,
                "write_bytes": proposal.estimated_write_bytes,
                "worker_seconds": proposal.estimated_worker_seconds,
                "evaluator_seconds": proposal.estimated_evaluator_seconds,
            },
        }
        work_token = self.store.authentication_tag("vpro2-work-token-v1", token_material)
        state["budget"] = budget.as_dict()
        state["active_objective"] = {
            **token_material,
            "work_token": work_token,
            "issued_at_unix": int(time.time()),
            "transaction_root": str(transaction_root),
            "snapshot_root": str(snapshot_root),
            "snapshot_manifest": snapshot_manifest_record,
            "baseline_manifest": baseline_record,
            "baseline_goal_state_digest": candidate["goal_state_digest"],
            "proposal": self._proposal_to_dict(proposal),
            "worker_result": None,
            "rolled_back": False,
        }
        state["phase"] = "WORKER_ACTIVE"
        self._event(
            state,
            "TEMPORARY_OBJECTIVE_ISSUED",
            Authority.CONTROLLER,
            {
                "objective_id": proposal.objective_id,
                "work_item_id": work_item_id,
                "transaction_id": transaction_id,
                "write_paths": list(proposal.write_paths),
                "capabilities": list(proposal.capabilities),
            },
        )

    def _rollback_active(self, state: dict[str, Any]) -> str | None:
        active = state.get("active_objective")
        if not isinstance(active, dict) or active.get("rolled_back"):
            return None
        try:
            expected_snapshot = self._load_manifest_record(active["snapshot_manifest"])
            if tree_manifest(Path(active["snapshot_root"])) != expected_snapshot:
                raise IntegrityError("rollback snapshot manifest drifted")
            restore_workspace(self.workspace_root, Path(active["snapshot_root"]))
        except (IntegrityError, OSError, ValueError) as exc:
            message = f"objective rollback failed: {exc}"
            active["rollback_error"] = message
            self._event(
                state,
                "OBJECTIVE_ROLLBACK_FAILED",
                Authority.CONTROLLER,
                {
                    "objective_id": active["objective_id"],
                    "transaction_id": active["transaction_id"],
                    "error": str(exc),
                },
            )
            return message
        active["rolled_back"] = True
        self._event(
            state,
            "OBJECTIVE_ROLLED_BACK",
            Authority.CONTROLLER,
            {
                "objective_id": active["objective_id"],
                "transaction_id": active["transaction_id"],
            },
        )
        return None

    def _terminate_after_rollback(
        self,
        state: dict[str, Any],
        contract: MilestoneContract,
        intended_status: str,
        reason: str,
    ) -> None:
        rollback_error = self._rollback_active(state)
        if rollback_error is not None:
            self._terminal(
                state,
                contract,
                "FAILED_INTEGRITY",
                f"{reason}; {rollback_error}",
            )
        else:
            self._terminal(state, contract, intended_status, reason)

    def _verify_worker_candidate(self, state: Mapping[str, Any]) -> None:
        active = self._active(state)
        result = active.get("worker_result")
        if not isinstance(result, dict) or not isinstance(result.get("result_manifest"), dict):
            raise IntegrityError("active objective has no sealed Worker result manifest")
        expected = self._load_manifest_record(result["result_manifest"])
        current = tree_manifest(self.workspace_root)
        diff = manifest_diff(expected, current)
        if any(diff.values()):
            raise IntegrityError(f"Worker candidate drifted after scope audit: {diff}")

    def _terminal(
        self,
        state: dict[str, Any],
        contract: MilestoneContract,
        status: str,
        reason: str,
    ) -> None:
        if status not in TERMINAL_STATUSES:
            raise VPro2ServiceError(f"unknown terminal status {status}")
        if state.get("terminal") is not None:
            return
        state["phase"] = "TERMINAL"
        try:
            terminal_product_digest = self._product_digest(contract)
        except (IntegrityError, OSError, ValueError) as exc:
            status = "FAILED_INTEGRITY"
            reason = f"{reason}; terminal product digest unavailable: {exc}"
            terminal_product_digest = state.get("product_digest", "0" * 64)
        terminal = {
            "schema_version": TERMINAL_SCHEMA,
            "status": status,
            "reason": reason,
            "run_id": state["run_id"],
            "milestone_id": state["milestone_id"],
            "framework_digest": state["framework_digest"],
            "contract_digest": state["contract_digest"],
            "evaluator_digest": state["evaluator_digest"],
            "product_digest": terminal_product_digest,
            "iteration": state["iteration"],
            "budget": dict(state["budget"]),
            "last_goal_state_digest": (
                state["goal_states"][-1]["state_digest"] if state["goal_states"] else None
            ),
            "last_goal_delta_digest": (
                state["goal_deltas"][-1]["delta_digest"] if state["goal_deltas"] else None
            ),
            "path_ledger_digest": canonical_digest(state["path_ledger"]),
            "evaluation_history_digest": canonical_digest(state["evaluation_history"]),
            "created_at_unix": int(time.time()),
        }
        terminal["terminal_tag"] = self.store.authentication_tag("vpro2-terminal-v1", terminal)
        state["terminal"] = terminal
        self._event(
            state,
            "RUN_TERMINATED",
            Authority.CONTROLLER,
            {"status": status, "reason": reason, "terminal_tag": terminal["terminal_tag"]},
        )
        receipt = {
            **terminal,
            "state_payload_digest": self.store.payload_digest(state),
            "last_event_hash": state["last_event_hash"],
        }
        receipt["receipt_tag"] = self.store.authentication_tag("vpro2-terminal-receipt-v1", receipt)
        if not self.store.terminal_path.exists():
            self.store.save_terminal(receipt)

    def _emergency_integrity_receipt(self, state: Mapping[str, Any], errors: Iterable[str]) -> None:
        if self.store.terminal_path.exists():
            return
        receipt = {
            "schema_version": TERMINAL_SCHEMA,
            "status": "FAILED_INTEGRITY",
            "reason": "controller state authentication failed",
            "errors": list(errors),
            "run_id": state.get("run_id"),
            "observed_state_digest": canonical_digest(dict(state)),
            "created_at_unix": int(time.time()),
        }
        receipt["receipt_tag"] = self.store.authentication_tag("vpro2-emergency-integrity-v1", receipt)
        self.store.save_terminal(receipt)

    def _status_view(self, state: dict[str, Any]) -> dict[str, Any]:
        view: dict[str, Any] = {
            "run_id": state["run_id"],
            "milestone_id": state["milestone_id"],
            "phase": state["phase"],
            "iteration": state["iteration"],
            "budget": dict(state["budget"]),
            "counters": {
                "no_material_progress": state["consecutive_no_material_progress"],
                "environment_blocked": state["consecutive_environment_blocked"],
                "no_legal_plan": state["no_legal_plan_rounds"],
            },
            "terminal": state["terminal"],
        }
        if state["goal_states"]:
            view["goal_state"] = state["goal_states"][-1]
        if state["gap_graphs"]:
            view["gap_graph"] = state["gap_graphs"][-1]
        if isinstance(state.get("candidate"), dict):
            view["candidate"] = state["candidate"]
            if state["phase"] == "OPERATOR_APPROVAL":
                view["approval_challenge"] = self._approval_binding(state, state["candidate"])
        if isinstance(state.get("active_objective"), dict):
            active = state["active_objective"]
            view["work_item"] = {
                key: active[key]
                for key in (
                    "objective_id",
                    "work_item_id",
                    "transaction_id",
                    "work_token",
                    "goal_state_digest",
                    "product_digest",
                    "baseline_manifest_digest",
                    "strategy_fingerprint",
                    "context_paths",
                    "context_digest",
                    "context_bytes",
                    "write_paths",
                    "capabilities",
                    "forbidden_effects",
                    "budget_reservation",
                    "proposal",
                )
            }
        return view

    def _verify_envelope(
        self,
        state: dict[str, Any],
        envelope: Mapping[str, Any],
        *,
        role: Authority,
        action: str,
    ) -> VerifiedEnvelope:
        try:
            verified = self.authorities.verify(
                envelope,
                run_id=state["run_id"],
                expected_role=role,
                expected_action=action,
            )
        except AuthorityError as exc:
            raise VPro2ServiceError(str(exc)) from exc
        if verified.nonce in state["used_authority_nonces"]:
            raise VPro2ServiceError("authority envelope nonce was already consumed")
        state["used_authority_nonces"].append(verified.nonce)
        return verified

    @staticmethod
    def _require_phase(state: Mapping[str, Any], phase: str) -> None:
        if state.get("terminal") is not None:
            raise VPro2ServiceError("run is terminal")
        if state.get("phase") != phase:
            raise VPro2ServiceError(f"operation requires phase {phase}, current phase is {state.get('phase')}")

    @staticmethod
    def _candidate(state: Mapping[str, Any]) -> dict[str, Any]:
        candidate = state.get("candidate")
        if not isinstance(candidate, dict):
            raise VPro2ServiceError("state has no selected temporary objective")
        return candidate

    @staticmethod
    def _active(state: Mapping[str, Any]) -> dict[str, Any]:
        active = state.get("active_objective")
        if not isinstance(active, dict):
            raise VPro2ServiceError("state has no active temporary objective")
        return active

    @staticmethod
    def _current_goal_state(state: Mapping[str, Any]) -> GoalState:
        values = state.get("goal_states")
        if not isinstance(values, list) or not values:
            raise VPro2ServiceError("planning requires a sealed Goal State")
        try:
            return goal_state_from_dict(values[-1])
        except (KeyError, TypeError, ValueError) as exc:
            raise VPro2ServiceError(f"stored Goal State is invalid: {exc}") from exc

    @staticmethod
    def _parse_proposal(value: Any) -> ObjectiveProposal:
        if not isinstance(value, dict):
            raise VPro2ServiceError("objective proposal must be an object")
        fields = {
            "objective_id",
            "title",
            "root_gap_id",
            "strategy_key",
            "context_paths",
            "write_paths",
            "capabilities",
            "evaluator_ids",
            "expected_condition_ids",
            "estimated_cost_units",
            "estimated_context_bytes",
            "estimated_write_bytes",
            "estimated_worker_seconds",
            "estimated_evaluator_seconds",
        }
        if set(value) != fields:
            raise VPro2ServiceError(
                f"objective proposal fields mismatch: missing={sorted(fields - set(value))}, "
                f"extra={sorted(set(value) - fields)}"
            )
        text_fields = ("objective_id", "title", "root_gap_id", "strategy_key")
        sequence_fields = ("context_paths", "write_paths", "capabilities", "evaluator_ids", "expected_condition_ids")
        numeric_fields = (
            "estimated_cost_units",
            "estimated_context_bytes",
            "estimated_write_bytes",
            "estimated_worker_seconds",
            "estimated_evaluator_seconds",
        )
        if any(not isinstance(value[field], str) for field in text_fields):
            raise VPro2ServiceError("objective proposal text fields are invalid")
        if (
            len(value["objective_id"].encode()) > 128
            or len(value["title"].encode()) > 512
            or len(value["root_gap_id"].encode()) > 128
            or len(value["strategy_key"].encode()) > 4096
        ):
            raise VPro2ServiceError("objective proposal text exceeds fixed safety bounds")
        if any(
            not isinstance(value[field], (list, tuple))
            or not all(isinstance(item, str) for item in value[field])
            for field in sequence_fields
        ):
            raise VPro2ServiceError("objective proposal path/id lists are invalid")
        if any(isinstance(value[field], bool) or not isinstance(value[field], int) for field in numeric_fields):
            raise VPro2ServiceError("objective proposal estimates must be integers")
        try:
            return ObjectiveProposal(
                objective_id=value["objective_id"],
                title=value["title"],
                root_gap_id=value["root_gap_id"],
                strategy_key=value["strategy_key"],
                context_paths=tuple(value["context_paths"]),
                write_paths=tuple(value["write_paths"]),
                capabilities=tuple(value["capabilities"]),
                evaluator_ids=tuple(value["evaluator_ids"]),
                expected_condition_ids=tuple(value["expected_condition_ids"]),
                estimated_cost_units=value["estimated_cost_units"],
                estimated_context_bytes=value["estimated_context_bytes"],
                estimated_write_bytes=value["estimated_write_bytes"],
                estimated_worker_seconds=value["estimated_worker_seconds"],
                estimated_evaluator_seconds=value["estimated_evaluator_seconds"],
            )
        except ValueError as exc:
            raise VPro2ServiceError(str(exc)) from exc

    @staticmethod
    def _proposal_to_dict(proposal: ObjectiveProposal) -> dict[str, Any]:
        return {
            "objective_id": proposal.objective_id,
            "title": proposal.title,
            "root_gap_id": proposal.root_gap_id,
            "strategy_key": proposal.strategy_key,
            "context_paths": list(proposal.context_paths),
            "write_paths": list(proposal.write_paths),
            "capabilities": list(proposal.capabilities),
            "evaluator_ids": list(proposal.evaluator_ids),
            "expected_condition_ids": list(proposal.expected_condition_ids),
            "estimated_cost_units": proposal.estimated_cost_units,
            "estimated_context_bytes": proposal.estimated_context_bytes,
            "estimated_write_bytes": proposal.estimated_write_bytes,
            "estimated_worker_seconds": proposal.estimated_worker_seconds,
            "estimated_evaluator_seconds": proposal.estimated_evaluator_seconds,
        }

    @staticmethod
    def _audit_to_dict(audit: ProposalAudit) -> dict[str, Any]:
        return {
            "proposal": VPro2Controller._proposal_to_dict(audit.proposal),
            "reasons": list(audit.reasons),
            "path_decision": audit.path_assessment.decision.value,
            "path_fingerprint": audit.path_assessment.fingerprint,
            "impact_score": audit.impact_score,
            "minimum_cost_units": audit.minimum_cost_units,
            "approval_required_capabilities": list(audit.approval_required_capabilities),
            "operator_cost_approval_required": audit.operator_cost_approval_required,
            "requires_operator_approval": audit.requires_operator_approval,
        }

    @staticmethod
    def _approval_binding(state: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "objective_id": candidate["proposal"]["objective_id"],
            "goal_state_digest": candidate["goal_state_digest"],
            "gap_graph_digest": candidate["gap_graph_digest"],
            "path_fingerprint": candidate["audit"]["path_fingerprint"],
            "capabilities": candidate["audit"]["approval_required_capabilities"],
            "cost_units": candidate["proposal"]["estimated_cost_units"],
            "contract_digest": state["contract_digest"],
            "product_digest": state["product_digest"],
        }

    def _record_path(
        self,
        state: dict[str, Any],
        proposal: ObjectiveProposal,
        outcome: PathOutcome,
    ) -> None:
        ledger = PathLedger.from_list(state["path_ledger"])
        evidence_basis = (
            state["active_objective"]["baseline_goal_state_digest"]
            if isinstance(state.get("active_objective"), dict)
            else self._current_goal_state(state).evidence_basis_digest
        )
        if isinstance(state.get("candidate"), dict):
            evidence_basis = state["candidate"]["evidence_basis_digest"]
        ledger = ledger.record(
            proposal.strategy,
            evidence_basis_digest=evidence_basis,
            outcome=outcome,
            iteration=state["iteration"],
            objective_id=proposal.objective_id,
        )
        state["path_ledger"] = ledger.as_list()

    def _event(
        self,
        state: dict[str, Any],
        transition: str,
        authority: Authority,
        details: Mapping[str, Any],
    ) -> None:
        self.store.append_event(
            state,
            {
                "sequence": len(state.get("events", [])) + 1,
                "transition": transition,
                "authority": authority.value,
                "iteration": state.get("iteration", 0),
                "timestamp_unix": int(time.time()),
                "details": dict(details),
            },
        )

    def _product_digest(self, contract: MilestoneContract) -> str:
        return self._paths_digest(contract.safety.product_roots)

    def _evaluator_digest(self, contract: MilestoneContract) -> str:
        return self._paths_digest(
            tuple(sorted(set((*contract.safety.evaluator_roots, *contract.safety.authority_roots))))
        )

    def _paths_digest(self, relative_paths: Iterable[str]) -> str:
        values: dict[str, Any] = {}
        for relative in sorted(set(relative_paths)):
            path = resolve_inside(self.project_root, relative)
            if not path.exists():
                values[relative] = {"kind": "missing"}
            elif path.is_file():
                values[relative] = {"kind": "file", "sha256": file_digest(path)}
            elif path.is_dir():
                values[relative] = {"kind": "directory", "manifest": tree_manifest(path)}
            else:
                raise IntegrityError(f"controlled path is not a regular file or directory: {relative}")
        return canonical_digest(values)

    def _paths_size(self, relative_paths: Iterable[str]) -> int:
        total = 0
        for relative in sorted(set(relative_paths)):
            path = resolve_inside(self.project_root, relative)
            if not path.exists():
                continue
            if path.is_file():
                total += path.stat().st_size
            elif path.is_dir():
                total += sum(
                    child.stat().st_size
                    for child in path.rglob("*")
                    if child.is_file() and not child.is_symlink()
                )
            else:
                raise IntegrityError(f"unsupported controlled path: {relative}")
        return total

    def _workspace_relative_paths(self, project_paths: Iterable[str]) -> tuple[str, ...]:
        prefix = self.project_root.relative_to(self.workspace_root).as_posix()
        return tuple(
            f"{prefix}/{relative}" if prefix != "." else relative
            for relative in project_paths
        )

    def _changed_size(self, manifest: Mapping[str, Mapping[str, Any]], paths: Iterable[str]) -> int:
        return sum(
            int(manifest[path].get("size", 0))
            for path in paths
            if path in manifest and manifest[path].get("kind") == "file"
        )

    @staticmethod
    def _write_manifest_record(path: Path, manifest: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        path.write_text(payload, encoding="utf-8")
        return {"path": str(path), "sha256": file_digest(path)}

    @staticmethod
    def _load_manifest_record(record: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        if set(record) != {"path", "sha256"}:
            raise IntegrityError("manifest record is invalid")
        path = Path(record["path"])
        if not path.is_file() or path.is_symlink() or file_digest(path) != record["sha256"]:
            raise IntegrityError("manifest record drifted")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntegrityError(f"manifest record is unreadable: {exc}") from exc
        if not isinstance(value, dict):
            raise IntegrityError("manifest record must contain an object")
        return value

    @staticmethod
    def _run_to_dict(run: EvaluatorRun) -> dict[str, Any]:
        return {
            "evaluator_id": run.evaluator_id,
            "report_digest": run.report_digest,
            "input_digest": run.input_digest,
            "return_code": run.return_code,
            "duration_seconds": run.duration_seconds,
            "report_path": run.report_path,
            "log_path": run.log_path,
            "log_digest": run.log_digest,
            "evidence_artifacts": list(run.evidence_artifacts),
        }

    @staticmethod
    def _evaluation_artifact_bytes(runs: Iterable[EvaluatorRun]) -> int:
        total = 0
        for run in runs:
            total += Path(run.report_path).stat().st_size
            total += Path(run.log_path).stat().st_size
            total += sum(Path(item["path"]).stat().st_size for item in run.evidence_artifacts)
        return total

    def _audit_evaluation_artifacts(
        self,
        state: Mapping[str, Any],
        contract: MilestoneContract,
        *,
        require_current: bool = False,
    ) -> list[str]:
        errors: list[str] = []
        histories = list(state.get("evaluation_history", []))
        for index, history in enumerate(histories):
            claimed_history = history.get("history_digest")
            unsigned = {key: value for key, value in history.items() if key != "history_digest"}
            if claimed_history != canonical_digest(unsigned):
                errors.append(f"evaluation history digest mismatch: {history.get('evaluation_id')}")
            current_history = require_current and index == len(histories) - 1
            for run in history.get("runs", []):
                log_path = Path(run.get("log_path", ""))
                report_path = Path(run.get("report_path", ""))
                if not log_path.is_file() or log_path.is_symlink():
                    errors.append(f"evaluation log missing: {log_path}")
                elif file_digest(log_path) != run.get("log_digest"):
                    errors.append(f"evaluation log digest mismatch: {log_path}")
                if not report_path.is_file() or report_path.is_symlink():
                    errors.append(f"evaluator report missing: {report_path}")
                    continue
                try:
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    errors.append(f"evaluator report unreadable: {report_path}")
                else:
                    if canonical_digest(report) != run.get("report_digest"):
                        errors.append(f"evaluator report digest mismatch: {report_path}")
                for artifact in run.get("evidence_artifacts", []):
                    artifact_path = Path(artifact.get("path", ""))
                    try:
                        relative = artifact_path.relative_to(self.run_root / "evaluations")
                    except ValueError:
                        errors.append(f"evidence artifact escaped evaluation archive: {artifact_path}")
                        continue
                    if len(relative.parts) != 4 or relative.parts[1] != "admitted-evidence":
                        errors.append(f"evidence artifact is outside its immutable archive: {artifact_path}")
                        continue
                    if not artifact_path.is_file() or artifact_path.is_symlink():
                        errors.append(f"evidence artifact missing: {artifact_path}")
                        continue
                    if file_digest(artifact_path) != artifact.get("sha256"):
                        errors.append(f"evidence artifact digest mismatch: {artifact_path}")
                    requirement_id = artifact.get("requirement_id")
                    try:
                        requirement = contract.evidence_requirement(requirement_id)
                    except KeyError:
                        errors.append(f"unknown evidence requirement in history: {requirement_id}")
                        continue
                    if artifact.get("capture_class") != requirement.capture_class:
                        errors.append(f"evidence capture class drift: {requirement_id}")
                    if artifact.get("run_id") != state.get("run_id"):
                        errors.append(f"evidence run binding mismatch: {requirement_id}")
                    if artifact.get("product_digest") != history.get("product_digest"):
                        errors.append(f"evidence product binding mismatch: {requirement_id}")
                    if current_history:
                        captured = artifact.get("captured_at_unix")
                        terminal_time = state.get("terminal", {}).get("created_at_unix")
                        if (
                            not isinstance(captured, int)
                            or not isinstance(terminal_time, int)
                            or terminal_time - captured > requirement.freshness.max_age_seconds
                        ):
                            errors.append(f"evidence is no longer current: {requirement_id}")
        if require_current:
            if not histories:
                errors.append("terminal Goal State has no final evaluation history")
            else:
                final_history = histories[-1]
                terminal = state.get("terminal", {})
                if final_history.get("goal_state_digest") != terminal.get("last_goal_state_digest"):
                    errors.append("terminal Goal State does not match the final evaluation history")
                if final_history.get("phase") != "FINAL_EVALUATE":
                    errors.append("successful terminal history is not a final evaluation")
                if final_history.get("product_digest") != terminal.get("product_digest"):
                    errors.append("successful terminal history is bound to another product")
        return errors

    @staticmethod
    def _remaining_wall_seconds(
        state: Mapping[str, Any], contract: MilestoneContract, *, now: int | None = None
    ) -> int:
        current = int(time.time()) if now is None else now
        created = int(state["budget"]["created_at_unix"])
        return contract.resource_budget.max_wall_seconds - (current - created)
