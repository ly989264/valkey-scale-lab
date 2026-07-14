from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from vpro2.contracts import parse_contract
from vpro2.evaluation import build_goal_state
from vpro2.integrity import canonical_digest
from vpro2.runner import EvaluatorError, EvaluatorRunner
from vpro2.schema_validation import SchemaValidationError, validate_json_schema
from vpro2.service import VPro2Controller


class EvidenceClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(
            EvaluatorRunner,
            "_sandboxed_command",
            lambda self, command, *, cwd, **kwargs: (command, cwd),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "worker"
        self.project = self.workspace / "project"
        self.run_root = self.root / "operator/run"
        for relative in ("product", "evaluator", "authority", "runtime-evidence"):
            (self.project / relative).mkdir(parents=True, exist_ok=True)
        (self.project / "product/value.txt").write_text("ready\n", encoding="utf-8")
        (self.project / "authority/result.schema.json").write_text("{}\n", encoding="utf-8")
        (self.project / "evaluator/milestone.py").write_text(self._milestone_source(), encoding="utf-8")
        (self.project / "evaluator/admit.py").write_text(self._admission_source("PASS"), encoding="utf-8")
        self.contract = parse_contract(self._contract(), project_root=self.project)
        self.seals = EvaluatorRunner.seal_tools(
            self.contract.safety.allowed_tools,
            workspace_root=self.workspace,
            run_root=self.run_root,
        )
        artifact = self.run_root / "evidence/raw/real.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text('{"observed_nodes": 200}\n', encoding="utf-8")

    def _contract(self) -> dict:
        evaluator_common = {
            "authority": "independent_evaluator",
            "trust_mode": "sealed_local",
            "cwd": ".",
            "timeout_seconds": 5,
            "output_schema": "authority/result.schema.json",
            "cost": "cheap",
            "cost_units": 1,
            "capabilities": [],
        }
        return {
            "schema_version": "vpro-milestone-v2",
            "milestone": {
                "id": "RealEvidence",
                "version": "2.0.0",
                "title": "Real evidence",
                "final_goal": "Admit an exact independently observed run.",
            },
            "success_conditions": [
                {
                    "id": "ExactRun",
                    "statement": "The exact requested run passes.",
                    "evaluator_ids": ["milestone-evaluator"],
                    "evidence_requirement_ids": ["RealCapture"],
                    "required": True,
                }
            ],
            "evaluators": [
                {
                    **evaluator_common,
                    "id": "milestone-evaluator",
                    "mode": "milestone",
                    "argv": ["python3", "evaluator/milestone.py"],
                    "inputs": ["evaluator/milestone.py", "authority/result.schema.json", "product/value.txt"],
                },
                {
                    **evaluator_common,
                    "id": "admission-evaluator",
                    "mode": "admission",
                    "argv": ["python3", "evaluator/admit.py"],
                    "inputs": ["evaluator/admit.py", "authority/result.schema.json", "product/value.txt"],
                },
            ],
            "evidence_requirements": [
                {
                    "id": "RealCapture",
                    "statement": "A current real run with provenance is admitted.",
                    "capture_class": "REAL",
                    "provenance_required": True,
                    "freshness": {
                        "max_age_seconds": 300,
                        "bind_to_product_digest": True,
                        "bind_to_run_id": True,
                    },
                    "substitution_policy": "FORBIDDEN",
                    "admission_evaluator_ids": ["admission-evaluator"],
                }
            ],
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
                "forbidden_effects": ["downscale", "fixture_substitution"],
            },
            "resource_budget": {
                "max_iterations": 2,
                "max_objective_attempts": 2,
                "max_planning_rounds_per_iteration": 2,
                "max_wall_seconds": 300,
                "max_worker_seconds": 30,
                "max_evaluator_seconds": 30,
                "max_cost_units": 10,
                "max_context_bytes": 1000,
                "max_write_bytes": 1000,
                "max_evidence_bytes": 10000,
                "max_transaction_bytes": 10000,
                "max_capability_runs": 0,
                "max_operator_runs": 0,
                "max_diagnostic_iterations": 0,
            },
            "termination": {
                "max_consecutive_no_material_progress": 2,
                "max_consecutive_environment_blocked": 2,
                "max_no_legal_plan_rounds": 2,
                "integrity_anomaly": "FAIL_IMMEDIATE",
                "budget_exhaustion": "FAIL",
                "operator_abort": "FAIL",
            },
        }

    @staticmethod
    def _milestone_source() -> str:
        return (
            "import json, os\n"
            "from pathlib import Path\n"
            "r={'schema_version':'vpro2-evaluator-result-v1','evaluator_id':os.environ['VPRO2_EVALUATOR_ID'],"
            "'run_id':os.environ['VPRO2_RUN_ID'],'product_digest':os.environ['VPRO2_PRODUCT_DIGEST'],"
            "'input_digest':os.environ['VPRO2_INPUT_DIGEST'],'condition_results':[{'condition_id':'ExactRun',"
            "'status':'PASS','summary':'exact run checked'}],'evidence_results':[],'facts':[]}\n"
            "Path(os.environ['VPRO2_RESULT_PATH']).write_text(json.dumps(r))\n"
        )

    @staticmethod
    def _admission_source(status: str, *, substituted: bool = False) -> str:
        artifact = "raw/real.json" if status == "PASS" else ""
        return (
            "import json, os, time\n"
            "from pathlib import Path\n"
            f"e={{'requirement_id':'RealCapture','status':'{status}','artifact':'{artifact}',"
            "'capture_class':'REAL','provenance':{'source':'independent-runner'},"
            "'captured_at_unix':int(time.time()),'run_id':os.environ['VPRO2_RUN_ID'],"
            f"'product_digest':os.environ['VPRO2_PRODUCT_DIGEST'],'substituted':{substituted!r}}}\n"
            "r={'schema_version':'vpro2-evaluator-result-v1','evaluator_id':os.environ['VPRO2_EVALUATOR_ID'],"
            "'run_id':os.environ['VPRO2_RUN_ID'],'product_digest':os.environ['VPRO2_PRODUCT_DIGEST'],"
            "'input_digest':os.environ['VPRO2_INPUT_DIGEST'],'condition_results':[],"
            "'evidence_results':[e],'facts':[]}\n"
            "Path(os.environ['VPRO2_RESULT_PATH']).write_text(json.dumps(r))\n"
            f"raise SystemExit({0 if status == 'PASS' else 1})\n"
        )

    def _runner(self) -> EvaluatorRunner:
        return EvaluatorRunner(
            project_root=self.project,
            workspace_root=self.workspace,
            run_root=self.run_root,
            contract=self.contract,
            tool_seals=self.seals,
        )

    def test_current_real_evidence_and_evaluator_receipts_close_the_goal(self) -> None:
        runner = self._runner()
        runs = tuple(
            runner.run(
                evaluator,
                run_id="run-1",
                product_digest="a" * 64,
                evaluation_id="real-pass",
            )
            for evaluator in self.contract.evaluators
        )
        goal = build_goal_state(
            self.contract,
            runs,
            iteration=0,
            evidence_root=self.run_root / "evidence",
        )
        self.assertTrue(goal.evaluation("ExactRun").is_proven_pass)
        admitted = next(run for run in runs if run.evaluator_id == "admission-evaluator")
        archived = Path(admitted.evidence_artifacts[0]["path"])
        raw = self.run_root / "evidence/raw/real.json"
        self.assertTrue(archived.is_relative_to((self.run_root / "evaluations").resolve()))
        self.assertNotEqual(archived, raw)
        original = archived.read_bytes()
        raw.write_text('{"observed_nodes": 1}\n', encoding="utf-8")
        self.assertEqual(archived.read_bytes(), original)

    def test_terminal_freshness_applies_to_the_final_goal_state_not_old_history(self) -> None:
        runner = self._runner()
        evaluations = []
        for evaluation_id in ("old", "final"):
            evaluations.append(
                tuple(
                    runner.run(
                        evaluator,
                        run_id="run-1",
                        product_digest="a" * 64,
                        evaluation_id=evaluation_id,
                    )
                    for evaluator in self.contract.evaluators
                )
            )
        terminal_time = int(time.time())
        histories = []
        for evaluation_id, runs in (("old", evaluations[0]), ("final", evaluations[1])):
            history = {
                "evaluation_id": evaluation_id,
                "phase": "FINAL_EVALUATE",
                "iteration": 0,
                "product_digest": "a" * 64,
                "goal_state_digest": "same-goal",
                "runs": [VPro2Controller._run_to_dict(run) for run in runs],
            }
            histories.append(history)
        old_artifact = next(
            item
            for run in histories[0]["runs"]
            for item in run["evidence_artifacts"]
        )
        old_artifact["captured_at_unix"] = terminal_time - 301
        for history in histories:
            history["history_digest"] = canonical_digest(history)
        state = {
            "run_id": "run-1",
            "terminal": {
                "last_goal_state_digest": "same-goal",
                "product_digest": "a" * 64,
                "created_at_unix": terminal_time,
            },
            "evaluation_history": histories,
        }
        controller = object.__new__(VPro2Controller)
        controller.run_root = self.run_root.resolve()
        self.assertEqual(
            controller._audit_evaluation_artifacts(
                state, self.contract, require_current=True
            ),
            [],
        )

    def test_missing_evidence_never_becomes_success(self) -> None:
        (self.project / "evaluator/admit.py").write_text(self._admission_source("MISSING"), encoding="utf-8")
        runner = self._runner()
        runs = tuple(
            runner.run(
                evaluator,
                run_id="run-1",
                product_digest="b" * 64,
                evaluation_id="real-missing",
            )
            for evaluator in self.contract.evaluators
        )
        goal = build_goal_state(self.contract, runs, iteration=0, evidence_root=self.run_root / "evidence")
        self.assertEqual(goal.evaluation("ExactRun").status, "MISSING")
        self.assertFalse(goal.evaluation("ExactRun").is_proven_pass)

    def test_substituted_or_downscaled_evidence_is_rejected_fail_closed(self) -> None:
        (self.project / "evaluator/admit.py").write_text(
            self._admission_source("PASS", substituted=True), encoding="utf-8"
        )
        runner = self._runner()
        runner.run(
            self.contract.evaluator("milestone-evaluator"),
            run_id="run-1",
            product_digest="c" * 64,
            evaluation_id="substituted",
        )
        with self.assertRaisesRegex(EvaluatorError, "substituted evidence is forbidden"):
            runner.run(
                self.contract.evaluator("admission-evaluator"),
                run_id="run-1",
                product_digest="c" * 64,
                evaluation_id="substituted",
            )

    def test_sealed_declared_output_schema_is_enforced_in_addition_to_kernel_protocol(self) -> None:
        (self.project / "authority/result.schema.json").write_text(
            json.dumps(
                {
                    "type": "object",
                    "properties": {"evaluator_id": {"const": "different-evaluator"}},
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(EvaluatorError, "sealed output schema"):
            self._runner().run(
                self.contract.evaluator("milestone-evaluator"),
                run_id="run-1",
                product_digest="d" * 64,
                evaluation_id="schema-reject",
            )


class EvaluatorSandboxTests(unittest.TestCase):
    def test_macos_profile_denies_network_writes_and_undeclared_child_exec(self) -> None:
        runner = object.__new__(EvaluatorRunner)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("scratch", "evidence", "result"):
                (root / name).mkdir()
            command, cwd = runner._sandboxed_command(
                ["/usr/bin/python3", "check.py"],
                cwd=root,
                result_path=root / "result/out.json",
                scratch_root=root / "scratch",
                evidence_root=root / "evidence",
                allowed_executable=Path("/usr/bin/python3"),
                read_paths=(),
                read_evidence=False,
            )
        self.assertEqual(command[0], "/usr/bin/sandbox-exec")
        profile = command[2]
        self.assertIn("(deny network*)", profile)
        self.assertIn("(deny default)", profile)
        self.assertIn('(allow process-exec (literal "/usr/bin/python3"))', profile)
        self.assertNotIn("/bin/sh", profile)
        self.assertNotIn("(allow file-read*)", profile)
        self.assertEqual(cwd, root)

    def test_linux_profile_does_not_mount_the_host_root_or_unrequested_evidence(self) -> None:
        runner = object.__new__(EvaluatorRunner)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("scratch", "evidence", "result", "cwd"):
                (root / name).mkdir()
            declared = root / "cwd/input.txt"
            declared.write_text("input\n", encoding="utf-8")
            with mock.patch("vpro2.runner.platform.system", return_value="Linux"), mock.patch(
                "vpro2.runner.shutil.which", return_value="/usr/bin/bwrap"
            ), mock.patch.object(EvaluatorRunner, "_verify_system_sandbox"):
                command, cwd = runner._sandboxed_command(
                    ["/usr/bin/python3", "check.py"],
                    cwd=root / "cwd",
                    result_path=root / "result/out.json",
                    scratch_root=root / "scratch",
                    evidence_root=root / "evidence",
                    allowed_executable=Path("/usr/bin/python3"),
                    read_paths=(declared,),
                    read_evidence=False,
                )
        joined = " ".join(command)
        self.assertNotIn("--ro-bind / /", joined)
        self.assertNotIn(str(root / "evidence"), joined)
        self.assertIn(str(declared), joined)
        self.assertEqual(cwd, Path("/"))


class DeclaredSchemaSafetyTests(unittest.TestCase):
    def test_malformed_numeric_constraint_is_a_controlled_schema_error(self) -> None:
        with self.assertRaisesRegex(SchemaValidationError, "minimum must be numeric"):
            validate_json_schema("text", {"type": "string", "minimum": "not-a-number"})

    def test_recursive_declared_schema_is_rejected_without_recursing(self) -> None:
        schema = {"$ref": "#/$defs/loop", "$defs": {"loop": {"$ref": "#/$defs/loop"}}}
        with self.assertRaisesRegex(SchemaValidationError, "recursive"):
            validate_json_schema({}, schema)


if __name__ == "__main__":
    unittest.main()
