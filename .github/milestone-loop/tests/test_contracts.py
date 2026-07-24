from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from contracts import (
    ContractError,
    PLANNER_STATUSES,
    PlannerOutput,
    WorkItemContract,
    fixed_milestone_path,
    github_conclusion,
    milestone_criteria,
    parse_planner_output,
    parse_work_item,
    parse_worker_output,
    pr_contract_change,
    render_work_item,
    require_candidate_check,
    validate_acyclic,
    validate_transition,
    verified_tree,
)


ROOT = Path(__file__).resolve().parents[3]


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = json.loads((ROOT / "project" / "catalog.json").read_text())

    def test_dispatch_milestone_uses_only_fixed_paths(self) -> None:
        self.assertEqual(
            fixed_milestone_path(ROOT, "m1"),
            ROOT / "project" / "milestones" / "m1" / "milestone.json",
        )
        self.assertEqual(
            fixed_milestone_path(ROOT, "m4"),
            ROOT / "project" / "milestones" / "m4" / "milestone.json",
        )
        for invalid in ("M1", "m5", "../m1", "m1/check"):
            with self.assertRaises(ContractError):
                fixed_milestone_path(ROOT, invalid)

    def test_three_line_contract_is_exact_and_bounded(self) -> None:
        body = render_work_item(
            "Implement the observable behavior.",
            WorkItemContract("local.lifecycle", (12, 19), "product.integration"),
        )
        self.assertEqual(
            parse_work_item(body),
            WorkItemContract("local.lifecycle", (12, 19), "product.integration"),
        )
        rejected = (
            body + "\nCheck: product.unit",
            body.replace("Check: product.integration", "Check: ./gate suite product.integration"),
            body.replace("Depends on: #12, #19", "Depends on: 12"),
            body.replace("Criterion:", "criterion:"),
        )
        for value in rejected:
            with self.assertRaises(ContractError):
                parse_work_item(value)

    def test_catalog_check_is_fixed_and_parameterized_checks_are_rejected(self) -> None:
        self.assertEqual(
            require_candidate_check(self.catalog, "product.unit"),
            ("./gate", "suite", "product.unit"),
        )
        with self.assertRaises(ContractError):
            require_candidate_check(self.catalog, "real.local.full-flow")
        for value in ("./gate", "product.unit --flag", "project/catalog.json", "unknown.check"):
            with self.assertRaises(ContractError):
                require_candidate_check(self.catalog, value)

    def test_agent_protocol_rejects_unknown_fields_and_bounds(self) -> None:
        valid = {
            "operations": [],
            "ready_issue": None,
            "summary": "nothing needed",
        }
        self.assertEqual(parse_planner_output(json.dumps(valid)).operations, ())
        with self.assertRaises(ContractError):
            parse_planner_output(json.dumps({**valid, "command": "gh issue close 1"}))
        with self.assertRaises(ContractError):
            parse_planner_output(json.dumps({**valid, "operations": [{}] * 13}))
        with self.assertRaises(ContractError):
            parse_planner_output(" " * 33000)
        self.assertTrue(
            parse_worker_output(
                json.dumps({"ready": True, "summary": "ready", "failure_kind": None})
            ).ready
        )
        with self.assertRaises(ContractError):
            parse_worker_output(
                json.dumps({"ready": False, "summary": "not ready", "failure_kind": None})
            )

    def test_planner_dependency_uniqueness_is_enforced_after_schema_output(self) -> None:
        schema = json.loads(
            (ROOT / ".github/milestone-loop/schemas/planner-output.schema.json").read_text()
        )
        depends_on = schema["properties"]["operations"]["items"]["properties"]["depends_on"]
        self.assertNotIn("uniqueItems", depends_on)
        duplicate = {
            "operations": [
                {
                    "kind": "create",
                    "issue": None,
                    "title": "Bounded work",
                    "description": "Implement the criterion.",
                    "criterion": "criterion.one",
                    "depends_on": [3, 3],
                    "check": "product.unit",
                    "status": "ready",
                }
            ],
            "ready_issue": None,
            "summary": "duplicate dependency",
        }
        with self.assertRaisesRegex(ContractError, "contains duplicates"):
            parse_planner_output(json.dumps(duplicate))

    def test_planner_cannot_output_coordinator_owned_progress_status(self) -> None:
        schema = json.loads(
            (ROOT / ".github/milestone-loop/schemas/planner-output.schema.json").read_text()
        )
        status = schema["properties"]["operations"]["items"]["properties"]["status"]
        self.assertEqual(tuple(status["enum"]), PLANNER_STATUSES)
        operation = {
            "kind": "update",
            "issue": 8,
            "title": None,
            "description": None,
            "criterion": "criterion.one",
            "depends_on": [],
            "check": "product.unit",
            "status": "completed",
        }
        output = {"operations": [operation], "ready_issue": None, "summary": "done"}
        with self.assertRaisesRegex(ContractError, "operation.status is invalid"):
            parse_planner_output(json.dumps(output))

    def test_status_transitions_and_dependency_cycles_fail_closed(self) -> None:
        validate_transition("ready", "in-progress")
        validate_transition("review", "completed")
        with self.assertRaises(ContractError):
            validate_transition("completed", "ready")
        validate_acyclic({1: (), 2: (1,), 3: (2,)})
        with self.assertRaises(ContractError):
            validate_acyclic({1: (2,), 2: (1,)})
        with self.assertRaises(ContractError):
            validate_acyclic({1: (99,)})

    def test_verified_tree_binds_all_three_shas(self) -> None:
        a, b, c, d = (character * 40 for character in "abcd")
        first = verified_tree(a, b, c)
        self.assertNotEqual(first, verified_tree(a, b, d))
        self.assertNotEqual(first, verified_tree(a, c, c))
        self.assertNotEqual(first, verified_tree(d, b, c))

    def test_contract_change_metadata_is_body_authoritative(self) -> None:
        self.assertTrue(pr_contract_change("Contract-Change: true\n", []))
        self.assertFalse(
            pr_contract_change(
                "Contract-Change: false\n",
                ["milestone-loop:contract-change"],
            )
        )
        for body in (
            "",
            "Contract-Change:true\n",
            "Contract-Change: maybe\n",
            "Contract-Change: false\nContract-Change: true\n",
        ):
            with self.subTest(body=body), self.assertRaises(ContractError):
                pr_contract_change(body, [])

    def test_gate_conclusions_have_only_three_fixed_mappings(self) -> None:
        self.assertEqual(github_conclusion("PASS"), "success")
        self.assertEqual(github_conclusion("FAIL"), "failure")
        self.assertEqual(github_conclusion("BLOCKED"), "action_required")
        with self.assertRaises(ContractError):
            github_conclusion("ERROR")

    def test_no_work_item_branch_checks_every_criterion_binding(self) -> None:
        ready = {
            "id": "m1",
            "goal": "goal",
            "criteria": [{"id": "criterion.one", "statement": "done", "check": [{"id": "product.unit"}]}],
        }
        self.assertEqual(milestone_criteria(ready, "m1"), {"criterion.one": ("product.unit",)})
        defined = {
            "id": "m1",
            "goal": "goal",
            "criteria": [{"id": "criterion.one", "statement": "not executable"}],
        }
        self.assertEqual(milestone_criteria(defined, "m1"), {"criterion.one": ()})


if __name__ == "__main__":
    unittest.main()
