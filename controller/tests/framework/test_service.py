from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from controller.roles import AUTHORITY_DOMAIN, Authority, unsigned_envelope
from controller.gap_graph import ConditionEvaluation, GoalState
from controller.runner import EvaluatorRunner
from controller.service import Controller, ControllerServiceError


KEYS = {
    Authority.CONTROLLER: b"controller-authority-key-32-bytes-long",
    Authority.WORKER: b"worker-authority-key-material-32bytes",
    Authority.REVIEWER: b"reviewer-authority-key-32-bytes-long",
    Authority.EVALUATOR: b"evaluator-authority-key-32bytes!!",
    Authority.OPERATOR: b"operator-authority-key-32-bytes-long",
}


def _sign(
    *,
    run_id: str,
    role: Authority,
    action: str,
    nonce: str,
    payload: dict,
    key_role: Authority | None = None,
) -> dict:
    now = int(time.time())
    value = unsigned_envelope(
        run_id=run_id,
        role=role,
        action=action,
        nonce=nonce,
        payload=payload,
        issued_at_unix=now - 1,
        expires_at_unix=now + 300,
    )
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    value["hmac_sha256"] = hmac.new(
        KEYS[key_role or role],
        AUTHORITY_DOMAIN + encoded,
        hashlib.sha256,
    ).hexdigest()
    return value


class ControllerFixture:
    def __init__(
        self,
        root: Path,
        *,
        no_progress_limit: int = 2,
        no_plan_limit: int = 2,
        initial_value: str = "not-done",
        max_cost_units: int = 20,
        max_evidence_bytes: int = 10000,
        max_transaction_bytes: int = 10000,
        environment_block_limit: int = 2,
    ):
        self.root = root
        self.workspace = root / "worker"
        self.project = self.workspace / "project"
        self.operator = root / "operator"
        self.run_root = self.operator / "runs" / "run-1"
        self.contract_path = self.operator / "milestone.json"
        for relative in ("product", "evaluator", "authority", "runtime-evidence"):
            (self.project / relative).mkdir(parents=True, exist_ok=True)
        (self.project / "product/work.txt").write_text(initial_value + "\n", encoding="utf-8")
        (self.project / "product/other.txt").write_text("untouched\n", encoding="utf-8")
        (self.project / "authority/result.schema.json").write_text(
            '{"$id":"controller-evaluator-result-v1"}\n', encoding="utf-8"
        )
        (self.project / "evaluator/check.py").write_text(
            "import json, os\n"
            "from pathlib import Path\n"
            "value = Path('product/work.txt').read_text().strip()\n"
            "status = 'PASS' if value == 'done' else 'BLOCKED_ENV' if value == 'env-block' else 'FAIL'\n"
            "result = {\n"
            " 'schema_version': 'controller-evaluator-result-v1',\n"
            " 'evaluator_id': os.environ['CONTROLLER_EVALUATOR_ID'],\n"
            " 'run_id': os.environ['CONTROLLER_RUN_ID'],\n"
            " 'product_digest': os.environ['CONTROLLER_PRODUCT_DIGEST'],\n"
            " 'input_digest': os.environ['CONTROLLER_INPUT_DIGEST'],\n"
            " 'condition_results': [{'condition_id':'ArtifactReady','status':status,'summary':'checked artifact'}],\n"
            " 'evidence_results': [],\n"
            " 'facts': [],\n"
            "}\n"
            "Path(os.environ['CONTROLLER_RESULT_PATH']).write_text(json.dumps(result), encoding='utf-8')\n"
            "raise SystemExit(0 if status == 'PASS' else 75 if status == 'BLOCKED_ENV' else 1)\n",
            encoding="utf-8",
        )
        self.contract_path.parent.mkdir(parents=True, exist_ok=True)
        self.contract_path.write_text(
            json.dumps(
                self.contract(
                    no_progress_limit=no_progress_limit,
                    no_plan_limit=no_plan_limit,
                    max_cost_units=max_cost_units,
                    max_evidence_bytes=max_evidence_bytes,
                    max_transaction_bytes=max_transaction_bytes,
                    environment_block_limit=environment_block_limit,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
        self.controller = Controller(
            project_root=self.project,
            workspace_root=self.workspace,
            contract_path=self.contract_path,
            run_root=self.run_root,
            framework_digest="f" * 64,
            state_seal_key=b"state-seal-key-material-at-least-32-bytes",
            authority_keys=KEYS,
        )
        self.run_id = "synthetic-run"
        challenge = self.controller.bind_challenge(run_id=self.run_id)
        self.controller.bind(
            run_id=self.run_id,
            operator_envelope=_sign(
                run_id=self.run_id,
                role=Authority.OPERATOR,
                action="BIND",
                nonce="bind",
                payload=challenge,
            ),
        )

    @staticmethod
    def contract(
        *,
        no_progress_limit: int,
        no_plan_limit: int,
        max_cost_units: int = 20,
        max_evidence_bytes: int = 10000,
        max_transaction_bytes: int = 10000,
        environment_block_limit: int = 2,
    ) -> dict:
        return {
            "schema_version": "controller-milestone-v2",
            "milestone": {
                "id": "SyntheticArtifact",
                "version": "2.0.0",
                "title": "Synthetic artifact",
                "final_goal": "Produce the independently checked artifact.",
            },
            "success_conditions": [
                {
                    "id": "ArtifactReady",
                    "statement": "The artifact is ready.",
                    "evaluator_ids": ["artifact-evaluator"],
                    "evidence_requirement_ids": [],
                    "required": True,
                }
            ],
            "evaluators": [
                {
                    "id": "artifact-evaluator",
                    "mode": "milestone",
                    "authority": "independent_evaluator",
                    "trust_mode": "sealed_local",
                    "argv": ["python3", "evaluator/check.py"],
                    "cwd": ".",
                    "timeout_seconds": 5,
                    "inputs": [
                        "evaluator/check.py",
                        "authority/result.schema.json",
                        "product/work.txt",
                    ],
                    "output_schema": "authority/result.schema.json",
                    "cost": "cheap",
                    "cost_units": 1,
                    "capabilities": [],
                }
            ],
            "evidence_requirements": [],
            "safety": {
                "product_roots": ["product"],
                "context_roots": ["product"],
                "mutable_roots": ["product"],
                "immutable_roots": ["evaluator", "authority"],
                "evaluator_roots": ["evaluator"],
                "authority_roots": ["authority"],
                "evidence_roots": ["runtime-evidence"],
                "allowed_tools": ["python3"],
                "capability_policies": [],
                "forbidden_effects": ["goal_mutation", "evaluator_mutation", "evidence_fabrication"],
            },
            "resource_budget": {
                "max_iterations": 3,
                "max_objective_attempts": 3,
                "max_planning_rounds_per_iteration": 3,
                "max_wall_seconds": 600,
                "max_worker_seconds": 60,
                "max_evaluator_seconds": 60,
                "max_cost_units": max_cost_units,
                "max_context_bytes": 10000,
                "max_write_bytes": 10000,
                "max_evidence_bytes": max_evidence_bytes,
                "max_transaction_bytes": max_transaction_bytes,
                "max_capability_runs": 0,
                "max_operator_runs": 0,
                "max_diagnostic_iterations": 0,
            },
            "termination": {
                "max_consecutive_no_material_progress": no_progress_limit,
                "max_consecutive_environment_blocked": environment_block_limit,
                "max_no_legal_plan_rounds": no_plan_limit,
                "integrity_anomaly": "FAIL_IMMEDIATE",
                "budget_exhaustion": "FAIL",
                "operator_abort": "FAIL",
            },
        }

    def assess(self) -> dict:
        return self.controller.evaluate()

    def proposal(self, *, strategy: str = "write-done") -> dict:
        return {
            "objective_id": "temporary-1",
            "title": "Make the artifact pass",
            "root_gap_id": "ArtifactReady",
            "strategy_key": strategy,
            "context_paths": ["product/work.txt"],
            "write_paths": ["product/work.txt"],
            "capabilities": [],
            "evaluator_ids": ["artifact-evaluator"],
            "expected_condition_ids": ["ArtifactReady"],
            "estimated_cost_units": 2,
            "estimated_context_bytes": 100,
            "estimated_write_bytes": 100,
            "estimated_worker_seconds": 30,
            "estimated_evaluator_seconds": 10,
        }

    def plan_and_approve(self, proposal: dict | None = None) -> dict:
        status = self.controller.status()
        goal = status["goal_state"]
        self.controller.submit_plan(
            _sign(
                run_id=self.run_id,
                role=Authority.CONTROLLER,
                action="PROPOSE_OBJECTIVES",
                nonce=f"plan-{time.time_ns()}",
                payload={"goal_state_digest": goal["state_digest"], "proposals": [proposal or self.proposal()]},
            )
        )
        candidate = self.controller.status()["candidate"]
        return self.controller.review_plan(
            _sign(
                run_id=self.run_id,
                role=Authority.REVIEWER,
                action="REVIEW_PLAN",
                nonce=f"review-plan-{time.time_ns()}",
                payload={
                    "objective_id": candidate["proposal"]["objective_id"],
                    "goal_state_digest": candidate["goal_state_digest"],
                    "gap_graph_digest": candidate["gap_graph_digest"],
                    "decision": "APPROVE",
                    "reason": "bounded, measurable, and non-repeated",
                },
            )
        )

    def submit_worker(self) -> dict:
        work = self.controller.status()["work_item"]
        return self.controller.submit_worker_result(
            _sign(
                run_id=self.run_id,
                role=Authority.WORKER,
                action="COMPLETE_OBJECTIVE",
                nonce=f"worker-{time.time_ns()}",
                payload={
                    "objective_id": work["objective_id"],
                    "work_item_id": work["work_item_id"],
                    "transaction_id": work["transaction_id"],
                    "work_token": work["work_token"],
                    "summary": "implemented the bounded change",
                },
            )
        )

    def accept_change(self) -> dict:
        work = self.controller.status()["work_item"]
        return self.controller.review_change(
            _sign(
                run_id=self.run_id,
                role=Authority.REVIEWER,
                action="REVIEW_CHANGE",
                nonce=f"review-change-{time.time_ns()}",
                payload={
                    "objective_id": work["objective_id"],
                    "work_item_id": work["work_item_id"],
                    "decision": "ACCEPT_FOR_EVALUATION",
                    "reason": "scope and integrity audit passed",
                },
            )
        )


class ControllerTests(unittest.TestCase):
    def fixture(self, **kwargs) -> ControllerFixture:
        patcher = mock.patch.object(
            EvaluatorRunner,
            "_sandboxed_command",
            lambda self, command, *, cwd, **kwargs: (command, cwd),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return ControllerFixture(Path(temporary.name), **kwargs)

    def test_evaluate_first_dynamic_objective_goal_delta_and_final_fresh_success(self) -> None:
        fixture = self.fixture()
        initial = fixture.assess()
        self.assertEqual(initial["phase"], "PLANNING")
        self.assertEqual(initial["goal_state"]["evaluations"][0]["status"], "FAIL")
        self.assertEqual(initial["gap_graph"]["root_blockers"][0]["condition_ids"], ("ArtifactReady",))

        issued = fixture.plan_and_approve()
        self.assertEqual(issued["phase"], "WORKER_ACTIVE")
        self.assertEqual(
            issued["work_item"]["forbidden_effects"],
            ["goal_mutation", "evaluator_mutation", "evidence_fabrication"],
        )
        (fixture.project / "product/work.txt").write_text("done\n", encoding="utf-8")
        self.assertEqual(fixture.submit_worker()["phase"], "CHANGE_REVIEW")
        self.assertEqual(fixture.accept_change()["phase"], "POST_EVALUATE")
        self.assertEqual(fixture.controller.evaluate()["phase"], "PRE_EVALUATE")

        self.assertEqual(fixture.controller.evaluate()["phase"], "FINAL_EVALUATE")
        completed = fixture.controller.evaluate()
        self.assertEqual(completed["terminal"]["status"], "SUCCESS")
        self.assertEqual((fixture.project / "product/work.txt").read_text(), "done\n")
        self.assertEqual(fixture.controller.audit()["goal_delta_count"], 1)
        self.assertEqual(fixture.controller.verify_terminal()["terminal_status"], "SUCCESS")

    def test_no_progress_rolls_back_and_equivalent_path_is_eliminated(self) -> None:
        fixture = self.fixture()
        fixture.assess()
        fixture.plan_and_approve()
        (fixture.project / "product/work.txt").write_text("still-not-done\n", encoding="utf-8")
        fixture.submit_worker()
        fixture.accept_change()
        status = fixture.controller.evaluate()
        self.assertEqual(status["phase"], "PRE_EVALUATE")
        self.assertEqual((fixture.project / "product/work.txt").read_text(), "not-done\n")
        self.assertEqual(status["counters"]["no_material_progress"], 1)

        fixture.controller.evaluate()
        goal = fixture.controller.status()["goal_state"]
        failed = fixture.controller.submit_plan(
            _sign(
                run_id=fixture.run_id,
                role=Authority.CONTROLLER,
                action="PROPOSE_OBJECTIVES",
                nonce="repeat-plan",
                payload={"goal_state_digest": goal["state_digest"], "proposals": [fixture.proposal()]},
            )
        )
        self.assertEqual(failed["phase"], "PLANNING")
        self.assertEqual(failed["counters"]["no_legal_plan"], 1)

    def test_role_keys_cannot_be_switched_by_changing_actor_labels(self) -> None:
        fixture = self.fixture()
        fixture.assess()
        fixture.plan_and_approve()
        work = fixture.controller.status()["work_item"]
        forged = _sign(
            run_id=fixture.run_id,
            role=Authority.WORKER,
            key_role=Authority.REVIEWER,
            action="COMPLETE_OBJECTIVE",
            nonce="forged-worker",
            payload={
                "objective_id": work["objective_id"],
                "work_item_id": work["work_item_id"],
                "transaction_id": work["transaction_id"],
                "work_token": work["work_token"],
                "summary": "pretend",
            },
        )
        with self.assertRaisesRegex(ControllerServiceError, "authentication failed"):
            fixture.controller.submit_worker_result(forged)

    def test_no_legal_plan_emits_authenticated_failure_receipt(self) -> None:
        fixture = self.fixture(no_plan_limit=1)
        status = fixture.assess()
        terminal = fixture.controller.submit_plan(
            _sign(
                run_id=fixture.run_id,
                role=Authority.CONTROLLER,
                action="PROPOSE_OBJECTIVES",
                nonce="empty-plan",
                payload={"goal_state_digest": status["goal_state"]["state_digest"], "proposals": []},
            )
        )
        self.assertEqual(terminal["terminal"]["status"], "FAILED_NO_LEGAL_PLAN")
        receipt = json.loads(fixture.controller.store.terminal_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "FAILED_NO_LEGAL_PLAN")
        self.assertEqual(len(receipt["receipt_tag"]), 64)

    def test_unauthorized_worker_change_fails_integrity_and_rolls_back_authorized_path(self) -> None:
        fixture = self.fixture()
        fixture.assess()
        fixture.plan_and_approve()
        (fixture.project / "product/work.txt").write_text("done\n", encoding="utf-8")
        (fixture.project / "product/other.txt").write_text("tampered\n", encoding="utf-8")
        terminal = fixture.submit_worker()
        self.assertEqual(terminal["terminal"]["status"], "FAILED_INTEGRITY")
        self.assertEqual((fixture.project / "product/work.txt").read_text(), "not-done\n")
        self.assertEqual((fixture.project / "product/other.txt").read_text(), "untouched\n")

    def test_candidate_drift_after_worker_submission_is_rejected_before_review(self) -> None:
        fixture = self.fixture()
        fixture.assess()
        fixture.plan_and_approve()
        (fixture.project / "product/work.txt").write_text("done\n", encoding="utf-8")
        fixture.submit_worker()
        (fixture.project / "product/work.txt").write_text("drifted\n", encoding="utf-8")
        terminal = fixture.accept_change()
        self.assertEqual(terminal["terminal"]["status"], "FAILED_INTEGRITY")
        self.assertEqual((fixture.project / "product/work.txt").read_text(), "not-done\n")

    def test_corrupted_rollback_snapshot_becomes_an_auditable_integrity_failure(self) -> None:
        fixture = self.fixture()
        fixture.assess()
        fixture.plan_and_approve()
        (fixture.project / "product/work.txt").write_text("done\n", encoding="utf-8")
        fixture.submit_worker()
        active = fixture.controller.store.load()["active_objective"]
        shutil.rmtree(active["snapshot_root"])
        (fixture.project / "product/work.txt").write_text("drifted\n", encoding="utf-8")
        terminal = fixture.accept_change()
        self.assertEqual(terminal["terminal"]["status"], "FAILED_INTEGRITY")
        self.assertIn("rollback failed", terminal["terminal"]["reason"])
        self.assertEqual(fixture.controller.verify_terminal()["terminal_status"], "FAILED_INTEGRITY")

    def test_complete_evaluation_is_preflighted_before_spending_remaining_budget(self) -> None:
        fixture = self.fixture(initial_value="done", max_cost_units=1)
        self.assertEqual(fixture.assess()["phase"], "FINAL_EVALUATE")
        terminal = fixture.controller.evaluate()
        self.assertEqual(terminal["terminal"]["status"], "FAILED_BUDGET_EXHAUSTED")
        state = fixture.controller.store.load()
        self.assertEqual(len(state["evaluation_history"]), 1)

    def test_raw_evidence_is_rejected_before_evaluator_execution_when_storage_cannot_fit(self) -> None:
        fixture = self.fixture(max_evidence_bytes=16)
        evidence = fixture.run_root / "evidence/raw.bin"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_bytes(b"x" * 17)
        terminal = fixture.assess()
        self.assertEqual(terminal["terminal"]["status"], "FAILED_BUDGET_EXHAUSTED")
        self.assertEqual(fixture.controller.store.load()["evaluation_history"], [])

    def test_state_seal_key_cannot_reuse_a_role_authority_key(self) -> None:
        fixture = self.fixture()
        with self.assertRaisesRegex(ControllerServiceError, "distinct keys"):
            Controller(
                project_root=fixture.project,
                workspace_root=fixture.workspace,
                contract_path=fixture.contract_path,
                run_root=fixture.root / "another-run",
                framework_digest="f" * 64,
                state_seal_key=KEYS[Authority.WORKER],
                authority_keys=KEYS,
            )

    def test_workspace_snapshot_is_preflighted_against_transaction_storage_budget(self) -> None:
        fixture = self.fixture(max_transaction_bytes=1)
        fixture.assess()
        terminal = fixture.plan_and_approve()
        self.assertEqual(terminal["terminal"]["status"], "FAILED_BUDGET_EXHAUSTED")
        self.assertFalse((fixture.run_root / "transactions").exists())

    def test_absolute_wall_deadline_terminates_on_the_next_authenticated_state_read(self) -> None:
        fixture = self.fixture()
        created = fixture.controller.store.load()["budget"]["created_at_unix"]
        with mock.patch("controller.service.time.time", return_value=created + 601):
            terminal = fixture.controller.status()
        self.assertEqual(terminal["terminal"]["status"], "FAILED_BUDGET_EXHAUSTED")

    def test_stagnation_and_persistent_environment_block_have_distinct_failure_states(self) -> None:
        stagnant = self.fixture(no_progress_limit=1)
        stagnant.assess()
        stagnant.plan_and_approve()
        stagnant.submit_worker()
        stagnant.accept_change()
        self.assertEqual(stagnant.controller.evaluate()["terminal"]["status"], "FAILED_STAGNATION")

        blocked = self.fixture(no_progress_limit=3, initial_value="env-block")
        self.assertEqual(blocked.assess()["counters"]["environment_blocked"], 1)
        blocked.plan_and_approve()
        blocked.submit_worker()
        blocked.accept_change()
        self.assertEqual(blocked.controller.evaluate()["phase"], "PRE_EVALUATE")
        self.assertEqual(
            blocked.controller.evaluate()["terminal"]["status"],
            "FAILED_ENVIRONMENT_BLOCKED",
        )

    def test_rolled_back_candidate_does_not_count_as_persistent_environment_block(self) -> None:
        fixture = self.fixture(environment_block_limit=1)
        fixture.assess()
        fixture.plan_and_approve()
        (fixture.project / "product/work.txt").write_text("env-block\n", encoding="utf-8")
        fixture.submit_worker()
        fixture.accept_change()
        status = fixture.controller.evaluate()
        self.assertEqual(status["phase"], "PRE_EVALUATE")
        self.assertIsNone(status["terminal"])
        self.assertEqual((fixture.project / "product/work.txt").read_text(), "not-done\n")

    def test_one_blocked_required_condition_counts_even_when_another_passes(self) -> None:
        fixture = self.fixture()
        state = fixture.controller.store.load()
        mixed = GoalState(
            iteration=0,
            evaluations=(
                ConditionEvaluation("ArtifactReady", "BLOCKED_ENV", (), (), True, True, True),
                ConditionEvaluation("Other", "PASS", (), (), True, True, True),
            ),
        )
        fixture.controller._observe_environment_state(state, fixture.controller._contract(), mixed)
        self.assertEqual(state["consecutive_environment_blocked"], 1)
        self.assertEqual(state["environment_blocked_condition_ids"], ["ArtifactReady"])

    def test_state_authentication_failure_emits_a_standalone_verifiable_receipt(self) -> None:
        fixture = self.fixture()
        state_path = fixture.controller.store.state_path
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["iteration"] = 999
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(ControllerServiceError, "state authentication failed"):
            fixture.controller.status()
        verified = fixture.controller.verify_terminal()
        self.assertEqual(verified["terminal_status"], "FAILED_INTEGRITY")
        self.assertTrue(verified["emergency"])


if __name__ == "__main__":
    unittest.main()
