from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from controller.contracts import ContractError, load_milestone, parse_milestone


def milestone() -> dict:
    return {
        "schema_version": "controller-milestone-v1",
        "milestone": {"id": "Synthetic", "title": "Synthetic", "goal": "Finish it."},
        "success_conditions": [
            {
                "id": "ready",
                "statement": "The artifact is ready.",
                "evidence_requirement_ids": ["real"],
            }
        ],
        "evidence_requirements": [
            {
                "id": "real",
                "statement": "Current real evidence is accepted.",
                "kind": "REAL",
                "source_id": "real.source",
                "freshness_seconds": 60,
                "provenance_required": True,
                "substitution_policy": "FORBIDDEN",
                "parameters": {"nodes": 50},
            }
        ],
        "termination": {
            "max_iterations": 4,
            "max_stagnant_iterations": 2,
            "max_environment_retries": 2,
            "max_no_plan_rounds": 2,
            "max_wall_seconds": 60,
        },
    }


class ContractTests(unittest.TestCase):
    def test_minimal_milestone_contains_only_goal_acceptance_and_termination(self) -> None:
        parsed = parse_milestone(milestone())
        self.assertEqual(parsed.id, "Synthetic")
        self.assertEqual(parsed.success_conditions[0].evidence_requirement_ids, ("real",))

    def test_runtime_control_fields_are_rejected_anywhere(self) -> None:
        for field in ("objectives", "depends_on", "implementation_order", "allowed_write_paths"):
            value = milestone()
            value["milestone"][field] = []
            with self.subTest(field=field), self.assertRaises(ContractError):
                parse_milestone(value)

    def test_unknown_or_duplicate_evidence_references_fail(self) -> None:
        unknown = milestone()
        unknown["success_conditions"][0]["evidence_requirement_ids"] = ["missing"]
        with self.assertRaisesRegex(ContractError, "unknown evidence"):
            parse_milestone(unknown)

        duplicate = milestone()
        duplicate["evidence_requirements"].append(duplicate["evidence_requirements"][0])
        with self.assertRaisesRegex(ContractError, "duplicate evidence"):
            parse_milestone(duplicate)

        overlapping = milestone()
        overlapping["evidence_requirements"][0]["id"] = "ready"
        overlapping["success_conditions"][0]["evidence_requirement_ids"] = ["ready"]
        with self.assertRaisesRegex(ContractError, "must not overlap"):
            parse_milestone(overlapping)

    def test_file_loader_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "milestone.json"
            text = json.dumps(milestone()).replace(
                '"schema_version": "controller-milestone-v1"',
                '"schema_version": "controller-milestone-v1", "schema_version": "other"',
                1,
            )
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "duplicate JSON key"):
                load_milestone(path)


if __name__ == "__main__":
    unittest.main()
