from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from contracts import ContractError, PlannerOperation, PlannerOutput
from coordinator import (
    CONTROL_LABEL,
    ControlState,
    LoopBlocked,
    apply_planner_transaction,
    consume_lease,
    coordinate,
    empty_lease,
    m2_candidate_blockers,
    parse_control,
    pending_failure_diagnosis,
    prepare_planner_transaction,
    render_control,
    record_milestone_result,
    set_no_progress,
    validate_failure_diagnosis,
    verification_record,
)


ROOT = Path(__file__).resolve().parents[3]


def issue(number: int, status: str, *, depends: str = "none") -> dict:
    return {
        "number": number,
        "title": f"Issue {number}",
        "body": (
            "Implement it.\n\n"
            "Criterion: local.lifecycle\n"
            f"Depends on: {depends}\n"
            "Check: product.unit"
        ),
        "state": "open",
        "labels": ["milestone-loop:work-item", f"milestone-loop:{status}"],
        "comments": [],
    }


def snapshot(issues: list[dict]) -> dict:
    return {
        "repository": "owner/repo",
        "default_branch": "main",
        "default_sha": "a" * 40,
        "milestone": "m1",
        "milestone_number": 1,
        "issues": issues,
        "pull_requests": [],
    }


def m2_milestone(
    selected_strategy: object = "current-default",
    selected_timeout_ms: object = "current-default",
) -> dict:
    milestone = json.loads(
        (ROOT / "project" / "milestones" / "m2" / "milestone.json").read_text()
    )
    for criterion in milestone["criteria"]:
        for check in criterion.get("check", []):
            if check["id"] == "real.local.m2-cluster-formation":
                check["parameters"]["selected_strategy"] = selected_strategy
            elif check["id"] == "real.local.m2-automatic-failover":
                check["parameters"]["selected_timeout_ms"] = selected_timeout_ms
            elif check["id"] == "real.local.m2-stability-resource":
                check["parameters"].update(
                    selected_strategy=selected_strategy,
                    selected_timeout_ms=selected_timeout_ms,
                )
    return milestone


class FakeClient:
    def __init__(self, control_issue: dict | None = None) -> None:
        self.control_issue = control_issue
        self.writes: list[tuple] = []

    def ensure_label(self, *args) -> None:
        return None

    def update_issue(self, number, **kwargs) -> None:
        self.writes.append(("update", number, kwargs))
        if self.control_issue is not None and number == self.control_issue["number"]:
            self.control_issue.update(kwargs)

    def create_issue(self, **kwargs) -> int:
        self.writes.append(("create", kwargs))
        return 99

    def comment(self, number, body) -> None:
        self.writes.append(("comment", number, body))

    def create_check_run(self, **kwargs) -> None:
        self.writes.append(("check", kwargs))

    def api(self, endpoint, **kwargs):
        if endpoint == f"issues/{self.control_issue['number']}":
            return dict(self.control_issue)
        raise AssertionError(endpoint)


def coordinate_m2(milestone: dict, catalog: dict) -> tuple[dict, FakeClient]:
    state = {
        "repository": "owner/repo",
        "default_branch": "main",
        "default_sha": "a" * 40,
        "milestone": "m2",
        "milestone_number": 2,
        "issues": [],
        "pull_requests": [],
    }
    control = ControlState(99, empty_lease("m2"), 0)
    client = FakeClient()
    with (
        patch("coordinator.load_trusted_documents", return_value=(milestone, catalog)),
        patch("coordinator.collect_snapshot", return_value=state),
        patch("coordinator.ensure_control", return_value=control),
        patch("coordinator.reconcile_review", return_value=("NONE", control)),
        patch("coordinator.run_planner", return_value=PlannerOutput((), None, "no work")),
        patch("coordinator.apply_planner_transaction"),
    ):
        result = coordinate(
            client=client,
            repo_root=ROOT,
            runtime_root=ROOT / ".ignored-test-runtime",
            action="resume",
            milestone="m2",
        )
    return result, client


class CoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = json.loads((ROOT / "project" / "catalog.json").read_text())
        cls.milestone = json.loads(
            (ROOT / "project" / "milestones" / "m1" / "milestone.json").read_text()
        )

    def test_planner_transaction_leaves_only_one_selected_ready(self) -> None:
        state = snapshot([issue(1, "blocked"), issue(2, "blocked")])
        operation = PlannerOperation(
            "update", 1, None, None, "local.lifecycle", (), "product.unit", "ready"
        )
        transaction = prepare_planner_transaction(
            snapshot=state,
            output=PlannerOutput((operation,), 1, "select one"),
            milestone_document=self.milestone,
            catalog_document=self.catalog,
        )
        self.assertEqual(transaction.ready_issue, 1)
        second = PlannerOperation(
            "update", 2, None, None, "local.lifecycle", (), "product.unit", "ready"
        )
        with self.assertRaises(ContractError):
            prepare_planner_transaction(
                snapshot=state,
                output=PlannerOutput((operation, second), 1, "too many"),
                milestone_document=self.milestone,
                catalog_document=self.catalog,
            )

    def test_ready_dependencies_must_be_completed(self) -> None:
        state = snapshot([issue(1, "blocked"), issue(2, "blocked", depends="#1")])
        operation = PlannerOperation(
            "update", 2, None, None, "local.lifecycle", (1,), "product.unit", "ready"
        )
        with self.assertRaises(ContractError):
            prepare_planner_transaction(
                snapshot=state,
                output=PlannerOutput((operation,), 2, "bad dependency"),
                milestone_document=self.milestone,
                catalog_document=self.catalog,
            )

    def test_new_ready_item_is_resolved_after_creation(self) -> None:
        state = snapshot([])
        operation = PlannerOperation(
            "create",
            None,
            "First work",
            "Implement the first bounded product change.",
            "local.lifecycle",
            (),
            "product.unit",
            "ready",
        )
        transaction = prepare_planner_transaction(
            snapshot=state,
            output=PlannerOutput((operation,), None, "create one ready item"),
            milestone_document=self.milestone,
            catalog_document=self.catalog,
        )
        self.assertIsNone(transaction.ready_issue)
        self.assertEqual(transaction.writes[0].operation.status, "ready")

    def test_planner_cannot_mark_accepted_progress(self) -> None:
        state = snapshot([issue(1, "review")])
        operation = PlannerOperation(
            "update", 1, None, None, "local.lifecycle", (), "product.unit", "completed"
        )
        with self.assertRaises(ContractError):
            prepare_planner_transaction(
                snapshot=state,
                output=PlannerOutput((operation,), None, "fake completion"),
                milestone_document=self.milestone,
                catalog_document=self.catalog,
            )

    def test_m2_current_baselines_block_before_real_authorization(self) -> None:
        milestone = m2_milestone()
        result, client = coordinate_m2(milestone, self.catalog)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "candidate-not-ready")
        self.assertEqual(
            set(result["parameters"]),
            {
                "real.local.m2-cluster-formation.selected_strategy",
                "real.local.m2-automatic-failover.selected_timeout_ms",
                "real.local.m2-stability-resource.selected_strategy",
                "real.local.m2-stability-resource.selected_timeout_ms",
            },
        )
        self.assertEqual([write[0] for write in client.writes], ["comment"])

    def test_m2_explicit_candidates_can_reach_milestone_gate(self) -> None:
        milestone = m2_milestone(
            selected_strategy="tree_meet_addslotsrange",
            selected_timeout_ms="10000",
        )
        result, _client = coordinate_m2(milestone, self.catalog)
        self.assertEqual(result, {"status": "MILESTONE", "milestone": "m2"})

    def test_m2_explicit_baseline_values_are_not_candidates(self) -> None:
        milestone = m2_milestone()
        for criterion in milestone["criteria"]:
            for check in criterion.get("check", []):
                if check["id"] in {
                    "real.local.m2-cluster-formation",
                    "real.local.m2-stability-resource",
                }:
                    check["parameters"]["selected_strategy"] = (
                        "valkey_cli_cluster_create_primaries"
                    )
                if check["id"] in {
                    "real.local.m2-automatic-failover",
                    "real.local.m2-stability-resource",
                }:
                    check["parameters"]["selected_timeout_ms"] = (
                        "030000"
                        if check["id"] == "real.local.m2-automatic-failover"
                        else 30000
                    )
        self.assertEqual(len(m2_candidate_blockers(milestone, "m2")), 4)

    def test_m2_invalid_or_ambiguous_candidates_fail_closed(self) -> None:
        milestone = m2_milestone()
        formation_check = None
        for criterion in milestone["criteria"]:
            for check in criterion.get("check", []):
                if check["id"] == "real.local.m2-cluster-formation":
                    formation_check = check
                    check["parameters"]["selected_strategy"] = "tree_meet_addslotsrange"
                elif check["id"] == "real.local.m2-automatic-failover":
                    check["parameters"]["selected_timeout_ms"] = 5000
                elif check["id"] == "real.local.m2-stability-resource":
                    check["parameters"].update(
                        selected_strategy="bogus",
                        selected_timeout_ms=True,
                    )
        milestone["criteria"][-1].setdefault("check", []).append(
            copy.deepcopy(formation_check)
        )
        self.assertEqual(len(m2_candidate_blockers(milestone, "m2")), 4)

    def test_m2_extra_candidate_parameters_fail_closed(self) -> None:
        milestone = m2_milestone(
            selected_strategy="tree_meet_addslotsrange",
            selected_timeout_ms="10000",
        )
        for criterion in milestone["criteria"]:
            for check in criterion.get("check", []):
                if check["id"].startswith("real.local.m2-"):
                    check["parameters"]["unexpected"] = "not-reviewed"
        self.assertEqual(len(m2_candidate_blockers(milestone, "m2")), 4)

    def test_m2_stability_must_use_the_selected_experiment_candidates(self) -> None:
        milestone = m2_milestone(
            selected_strategy="tree_meet_addslotsrange",
            selected_timeout_ms="10000",
        )
        for criterion in milestone["criteria"]:
            for check in criterion.get("check", []):
                if check["id"] == "real.local.m2-stability-resource":
                    check["parameters"].update(
                        selected_strategy="manual_tree_meet_parallel_slots",
                        selected_timeout_ms="15000",
                    )
        self.assertEqual(
            set(m2_candidate_blockers(milestone, "m2")),
            {
                "real.local.m2-stability-resource.selected_strategy",
                "real.local.m2-stability-resource.selected_timeout_ms",
            },
        )

    def test_m2_candidate_check_does_not_apply_to_other_milestones(self) -> None:
        malformed = {"criteria": [{"check": [{"id": "anything"}]}]}
        for milestone in ("m1", "m3", "m4"):
            self.assertEqual(m2_candidate_blockers(malformed, milestone), ())

    def test_live_state_change_prevents_all_planner_writes(self) -> None:
        state = snapshot([issue(1, "blocked")])
        operation = PlannerOperation(
            "update", 1, None, None, "local.lifecycle", (), "product.unit", "ready"
        )
        transaction = prepare_planner_transaction(
            snapshot=state,
            output=PlannerOutput((operation,), 1, "select"),
            milestone_document=self.milestone,
            catalog_document=self.catalog,
        )
        changed = {**state, "default_sha": "b" * 40}
        client = FakeClient()
        with patch("coordinator.collect_snapshot", return_value=changed):
            with self.assertRaises(LoopBlocked):
                apply_planner_transaction(
                    client=client,
                    original_snapshot=state,
                    transaction=transaction,
                )
        self.assertEqual(client.writes, [])

    def test_control_issue_contains_only_lease_and_no_progress(self) -> None:
        body = render_control(empty_lease("m1"), 3)
        parsed = parse_control({"number": 9, "body": body}, "m1")
        self.assertEqual(parsed.no_progress_count, 3)
        with self.assertRaises(ContractError):
            parse_control({"number": 9, "body": body + "\nState: running"}, "m1")

    def test_lease_is_consumed_once_and_exhausts(self) -> None:
        lease = empty_lease("m1")
        lease.update(
            {
                "status": "active",
                "nonce": "human-approved-1",
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1))
                .isoformat()
                .replace("+00:00", "Z"),
                "remaining": 1,
            }
        )
        control = {
            "number": 9,
            "body": render_control(lease, 0),
            "labels": [CONTROL_LABEL],
        }
        state = snapshot([control])
        client = FakeClient(control)
        consumed = consume_lease(client, state)
        self.assertEqual(consumed.lease["status"], "exhausted")
        self.assertEqual(consumed.lease["remaining"], 0)
        with self.assertRaises(LoopBlocked):
            consume_lease(client, state)

    def test_control_update_rejects_a_concurrent_lease_edit(self) -> None:
        original = empty_lease("m1")
        control = {
            "number": 9,
            "body": render_control(original, 0),
            "labels": [CONTROL_LABEL],
        }
        state = parse_control(control, "m1")
        edited = dict(original)
        edited["nonce"] = "human-edit"
        control["body"] = render_control(edited, 0)
        with self.assertRaises(LoopBlocked):
            set_no_progress(FakeClient(control), state, 1)

    def test_only_actions_bot_verification_records_are_trusted(self) -> None:
        marker = '<!-- milestone-loop-verification: {"status":"PASS"} -->'
        forged = {"comments": [{"author": "human", "body": marker}]}
        self.assertIsNone(verification_record(forged))
        trusted = {"comments": [{"author": "github-actions[bot]", "body": marker}]}
        self.assertEqual(verification_record(trusted), {"status": "PASS"})

    def test_milestone_result_never_moves_to_a_newer_default_sha(self) -> None:
        control = {
            "number": 9,
            "body": render_control(empty_lease("m1"), 0),
            "labels": [CONTROL_LABEL],
        }
        live = snapshot([control])
        live["default_sha"] = "b" * 40
        client = FakeClient(control)
        with patch("coordinator.collect_snapshot", return_value=live):
            action = record_milestone_result(
                client=client,
                milestone="m1",
                expected_sha="a" * 40,
                status="PASS",
                summary="passed on the authorized commit",
            )
        self.assertEqual(action, "STALE")
        check = next(write for write in client.writes if write[0] == "check")
        self.assertEqual(check[1]["head_sha"], "a" * 40)

    def test_failure_diagnosis_is_single_and_cannot_rewrite_other_work(self) -> None:
        signature = "b" * 64
        first = issue(1, "blocked")
        first["comments"] = [
            {
                "author": "github-actions[bot]",
                "body": f"<!-- milestone-loop-diagnosis-request: {signature} -->",
            }
        ]
        state = snapshot([first, issue(2, "blocked")])
        self.assertEqual(pending_failure_diagnosis(state), (1, signature))
        operation = PlannerOperation(
            "update", 2, None, None, "local.lifecycle", (), "product.unit", "blocked"
        )
        transaction = prepare_planner_transaction(
            snapshot=state,
            output=PlannerOutput((operation,), None, "wrong target"),
            milestone_document=self.milestone,
            catalog_document=self.catalog,
        )
        with self.assertRaises(ContractError):
            validate_failure_diagnosis(transaction, issue_number=1, snapshot=state)


if __name__ == "__main__":
    unittest.main()
