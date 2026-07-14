from __future__ import annotations

import unittest

from controller.contracts import parse_milestone
from controller.evaluation import EvaluationError, build_goal_state


class EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.milestone = parse_milestone(
            {
                "schema_version": "controller-milestone-v1",
                "milestone": {"id": "Evidence", "title": "Evidence", "goal": "Prove it."},
                "success_conditions": [
                    {
                        "id": "ready",
                        "statement": "Ready",
                        "evidence_requirement_ids": ["real"],
                    }
                ],
                "evidence_requirements": [
                    {
                        "id": "real",
                        "statement": "Real proof",
                        "kind": "REAL",
                        "source_id": "real.source",
                        "freshness_seconds": 60,
                        "provenance_required": True,
                        "substitution_policy": "FORBIDDEN",
                        "parameters": {"nodes": 50},
                    }
                ],
                "termination": {
                    "max_iterations": 2,
                    "max_stagnant_iterations": 1,
                    "max_environment_retries": 1,
                    "max_no_plan_rounds": 1,
                    "max_wall_seconds": 30,
                },
            }
        )

    def result(self, evidence_status: str):
        return {
            "condition_results": [{"id": "ready", "status": "PASS", "summary": "function passes"}],
            "evidence_results": [
                {
                    "id": "real",
                    "status": evidence_status,
                    "summary": "evidence observation",
                    "artifact": "run/real.json",
                    "provenance": {"nodes": 200, "capture": "real"},
                }
            ],
        }

    def test_only_passed_required_evidence_completes_the_milestone(self) -> None:
        complete = build_goal_state(self.milestone, self.result("PASS"), iteration=1)
        self.assertTrue(complete.complete)
        for status in ("MISSING", "STALE", "UNTRUSTED", "SUBSTITUTED", "ERROR"):
            with self.subTest(status=status):
                state = build_goal_state(self.milestone, self.result(status), iteration=1)
                self.assertFalse(state.complete)
                self.assertEqual({gap.id for gap in state.gaps}, {"ready", "real"})

        self_report = self.result("PASS")
        self_report["evidence_results"][0].pop("artifact")
        self_report["evidence_results"][0]["provenance"] = {}
        state = build_goal_state(self.milestone, self_report, iteration=1)
        self.assertFalse(state.complete)
        self.assertEqual(state.evidence_results[0].status.value, "UNTRUSTED")

    def test_evaluator_must_cover_the_complete_immutable_acceptance_set(self) -> None:
        missing = self.result("PASS")
        missing["evidence_results"] = []
        with self.assertRaisesRegex(EvaluationError, "result set mismatch"):
            build_goal_state(self.milestone, missing, iteration=1)
        unknown = self.result("PASS")
        unknown["condition_results"].append(
            {"id": "worker_claim", "status": "PASS", "summary": "claimed"}
        )
        with self.assertRaisesRegex(EvaluationError, "unknown"):
            build_goal_state(self.milestone, unknown, iteration=1)


if __name__ == "__main__":
    unittest.main()
