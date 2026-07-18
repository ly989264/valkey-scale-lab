from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from contracts import ContractError, PlannerOperation, PlannerOutput
from coordinator import (
    CONTROL_LABEL,
    LoopBlocked,
    apply_planner_transaction,
    consume_lease,
    empty_lease,
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
