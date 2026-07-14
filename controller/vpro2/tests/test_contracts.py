from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from vpro2.contracts import (
    FORBIDDEN_CONTROL_FIELDS,
    ContractError,
    load_contract,
    parse_contract,
)


FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = FRAMEWORK_ROOT / "templates/vpro2/milestone.template.json"
SCHEMA_PATH = FRAMEWORK_ROOT / "schemas/vpro2/milestone.schema.json"


def valid_contract() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


class MilestoneContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.temporary_root = Path(self.temporary.name).resolve()
        self.project_root = self.temporary_root / "project"
        self.project_root.mkdir()

    def parse(self, value: dict | None = None):
        return parse_contract(
            valid_contract() if value is None else value,
            project_root=self.project_root,
        )

    def test_template_is_a_valid_goal_only_contract(self) -> None:
        contract = self.parse()

        self.assertEqual(contract.schema_version, "vpro-milestone-v2")
        self.assertEqual(contract.milestone.id, "ReplaceMilestoneId")
        self.assertEqual(len(contract.success_conditions), 1)
        self.assertEqual(len(contract.evaluators), 2)
        self.assertEqual(contract.resource_budget["max_iterations"], 12)
        self.assertNotIn("objectives", valid_contract())

    def test_load_contract_reads_external_json(self) -> None:
        path = self.temporary_root / "milestone.json"
        path.write_text(json.dumps(valid_contract()), encoding="utf-8")

        contract = load_contract(path, project_root=self.project_root)

        self.assertEqual(contract.milestone.final_goal, "REPLACE: immutable final goal")

    def test_load_contract_rejects_a_user_controlled_symlink(self) -> None:
        target = self.temporary_root / "target.json"
        target.write_text(json.dumps(valid_contract()), encoding="utf-8")
        link = self.temporary_root / "milestone-link.json"
        link.symlink_to(target)

        with self.assertRaisesRegex(ContractError, "traverses symlink"):
            load_contract(link, project_root=self.project_root)

    def test_load_contract_requires_an_external_milestone_authority(self) -> None:
        embedded = self.project_root / "milestone.json"
        embedded.write_text(json.dumps(valid_contract()), encoding="utf-8")

        with self.assertRaisesRegex(ContractError, "external to the product"):
            load_contract(embedded, project_root=self.project_root)

    def test_parser_rejects_preplanned_control_fields_at_every_depth(self) -> None:
        for field in sorted(FORBIDDEN_CONTROL_FIELDS):
            with self.subTest(field=field, location="top"):
                raw = valid_contract()
                raw[field] = []
                with self.assertRaisesRegex(ContractError, "forbidden preplanned"):
                    self.parse(raw)
            with self.subTest(field=field, location="nested"):
                raw = valid_contract()
                raw["success_conditions"][0][field] = []
                with self.assertRaisesRegex(ContractError, "forbidden preplanned"):
                    self.parse(raw)

    def test_schema_is_closed_and_has_no_control_properties(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertTrue(FORBIDDEN_CONTROL_FIELDS.isdisjoint(schema["properties"]))

        def assert_closed_objects(value: object) -> None:
            if isinstance(value, dict):
                if value.get("type") == "object":
                    self.assertIs(value.get("additionalProperties"), False)
                for nested in value.values():
                    assert_closed_objects(nested)
            elif isinstance(value, list):
                for nested in value:
                    assert_closed_objects(nested)

        assert_closed_objects(schema)

    def test_unknown_fields_are_rejected(self) -> None:
        raw = valid_contract()
        raw["milestone"]["description"] = "not a declared field"

        with self.assertRaisesRegex(ContractError, "unknown fields"):
            self.parse(raw)

    def test_every_condition_requires_an_independent_evaluator(self) -> None:
        raw = valid_contract()
        raw["success_conditions"][0]["evaluator_ids"] = []
        with self.assertRaisesRegex(ContractError, "nonempty array"):
            self.parse(raw)

        raw = valid_contract()
        raw["evaluators"][0]["authority"] = "worker"
        with self.assertRaisesRegex(ContractError, "worker or controller verdicts"):
            self.parse(raw)

    def test_unknown_or_unused_authorities_are_rejected(self) -> None:
        raw = valid_contract()
        raw["success_conditions"][0]["evaluator_ids"] = ["MissingEvaluator"]
        with self.assertRaisesRegex(ContractError, "unknown evaluators"):
            self.parse(raw)

        raw = valid_contract()
        raw["evaluators"].append(
            copy.deepcopy(raw["evaluators"][0]) | {"id": "UnusedEvaluator"}
        )
        with self.assertRaisesRegex(ContractError, "unused evaluators"):
            self.parse(raw)

    def test_evidence_requires_admission_mode(self) -> None:
        raw = valid_contract()
        raw["evaluators"][1]["mode"] = "milestone"

        with self.assertRaisesRegex(ContractError, "must use admission mode"):
            self.parse(raw)

    def test_real_evidence_cannot_drop_provenance_binding_or_substitution_guard(self) -> None:
        mutations = (
            ("provenance_required", False),
            ("substitution_policy", "ALLOW_SMALLER"),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                raw = valid_contract()
                raw["evidence_requirements"][0][key] = value
                with self.assertRaises(ContractError):
                    self.parse(raw)

        raw = valid_contract()
        raw["evidence_requirements"][0]["freshness"][
            "bind_to_product_digest"
        ] = False
        with self.assertRaisesRegex(ContractError, "product/run binding"):
            self.parse(raw)

    def test_paths_cannot_escape_or_mix_worker_and_authority_writes(self) -> None:
        raw = valid_contract()
        raw["safety"]["mutable_roots"] = ["../evaluators"]
        with self.assertRaisesRegex(ContractError, "safe project-relative path"):
            self.parse(raw)

        raw = valid_contract()
        raw["safety"]["mutable_roots"] = ["product", "evaluators"]
        raw["safety"]["product_roots"] = ["product", "evaluators"]
        raw["safety"]["context_roots"] = ["product", "evaluators"]
        with self.assertRaisesRegex(ContractError, "mutable and immutable roots overlap"):
            self.parse(raw)

    def test_evaluator_adapter_and_schema_must_be_sealed_inputs(self) -> None:
        raw = valid_contract()
        raw["evaluators"][0]["argv"][1] = "product/self_report.py"
        raw["evaluators"][0]["inputs"].append("product/self_report.py")
        with self.assertRaisesRegex(ContractError, "outside sealed"):
            self.parse(raw)

        raw = valid_contract()
        raw["evaluators"][0]["inputs"].remove("schemas/evaluator_result.schema.json")
        with self.assertRaisesRegex(ContractError, "output_schema must be declared"):
            self.parse(raw)

    def test_evaluator_cannot_request_capability_or_shell(self) -> None:
        raw = valid_contract()
        raw["evaluators"][0]["capabilities"] = ["network"]
        with self.assertRaisesRegex(ContractError, "read-only and unprivileged"):
            self.parse(raw)

        raw = valid_contract()
        raw["safety"]["allowed_tools"] = ["sh", "python3"]
        raw["evaluators"][0]["argv"] = ["sh", "evaluators/milestone_evaluator.py"]
        with self.assertRaisesRegex(ContractError, "unsafe tool"):
            self.parse(raw)

    def test_budget_and_termination_semantics_are_bounded(self) -> None:
        raw = valid_contract()
        raw["resource_budget"]["max_iterations"] = 0
        with self.assertRaisesRegex(ContractError, "positive integer"):
            self.parse(raw)

        raw = valid_contract()
        raw["resource_budget"]["max_objective_attempts"] = 2
        with self.assertRaisesRegex(ContractError, "must cover max_iterations"):
            self.parse(raw)

        raw = valid_contract()
        raw["termination"]["integrity_anomaly"] = "CONTINUE"
        with self.assertRaisesRegex(ContractError, "FAIL_IMMEDIATE"):
            self.parse(raw)

    def test_capability_uses_must_fit_controller_and_operator_budgets(self) -> None:
        raw = valid_contract()
        raw["safety"]["capability_policies"] = [
            {
                "id": "Container",
                "operator_approval_required": True,
                "max_uses": 2,
                "cost_units_per_use": 1,
            }
        ]
        raw["resource_budget"]["max_capability_runs"] = 1
        raw["resource_budget"]["max_operator_runs"] = 1
        with self.assertRaisesRegex(ContractError, "max_uses exceed"):
            self.parse(raw)

    def test_ids_are_globally_unambiguous(self) -> None:
        raw = valid_contract()
        raw["evidence_requirements"][0]["id"] = "ReplaceSuccessCondition"
        raw["success_conditions"][0]["evidence_requirement_ids"] = [
            "ReplaceSuccessCondition"
        ]

        with self.assertRaisesRegex(ContractError, "globally unique"):
            self.parse(raw)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
