from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from contracts import ContractError, PlannerOperation, PlannerOutput
from coordinator import (
    CONTROL_LABEL,
    DISCOVERY_REPAIR_LABEL,
    M2_DISCOVERY_REPAIR_ALLOWED_PREFIXES,
    M2_DISCOVERY_REPAIR_PROTECTED_PREFIXES,
    ControlState,
    LoopBlocked,
    apply_planner_transaction,
    coordinate,
    empty_lease,
    m2_candidate_blockers,
    m2_discovery_eligible,
    parse_control,
    pending_failure_diagnosis,
    pending_m2_discovery_diagnosis,
    prepare_planner_transaction,
    prepare_real_authorization,
    record_human_action_state,
    record_m2_discovery_result,
    render_control,
    record_real_authorization_required,
    record_milestone_result,
    set_no_progress,
    trusted_m2_discovery_repair_pr,
    validate_m2_discovery_diagnosis,
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
        self.check_reads = 0

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
        if self.control_issue is not None and number == self.control_issue["number"]:
            self.control_issue.setdefault("comments", []).append(
                {"author": "github-actions[bot]", "body": body}
            )

    def create_check_run(self, **kwargs) -> None:
        self.writes.append(("check", kwargs))

    def dispatch(self, milestone) -> None:
        self.writes.append(("dispatch", milestone))

    def api(self, endpoint, **kwargs):
        if endpoint.startswith("commits/") and endpoint.endswith(
            "/check-runs?check_name=milestone-loop%20%2F%20m2-discovery"
            "&filter=all&per_page=100"
        ):
            self.check_reads += 1
            check_runs = [
                {
                    "name": write[1].get("name"),
                    "external_id": write[1].get("external_id"),
                    "head_sha": write[1].get("head_sha"),
                    "status": "completed",
                    "conclusion": write[1].get("conclusion"),
                    "app": {"slug": "github-actions"},
                }
                for write in self.writes
                if write[0] == "check"
            ]
            return {"total_count": len(check_runs), "check_runs": check_runs}
        if self.control_issue is not None and endpoint == f"issues/{self.control_issue['number']}":
            return dict(self.control_issue)
        if (
            self.control_issue is not None
            and endpoint == f"issues/{self.control_issue['number']}/comments?per_page=51"
        ):
            return [
                {
                    "user": {"login": comment.get("author")},
                    "body": comment.get("body"),
                }
                for comment in self.control_issue.get("comments", [])
            ]
        raise AssertionError(endpoint)


def coordinate_m2(milestone: dict, catalog: dict) -> tuple[dict, FakeClient]:
    control_issue = {
        "number": 99,
        "title": "[milestone-loop] m2 control",
        "body": render_control(empty_lease("m2"), 0),
        "state": "open",
        "labels": [CONTROL_LABEL],
        "comments": [],
    }
    state = {
        "repository": "owner/repo",
        "default_branch": "main",
        "default_sha": "a" * 40,
        "milestone": "m2",
        "milestone_number": 2,
        "issues": [control_issue],
        "pull_requests": [],
    }
    control = ControlState(99, empty_lease("m2"), 0)
    client = FakeClient(control_issue)
    with (
        patch.dict(
            "os.environ",
            {
                "GITHUB_RUN_ID": "12345",
                "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_SERVER_URL": "https://github.com",
            },
            clear=True,
        ),
        patch("coordinator.load_trusted_documents", return_value=(milestone, catalog)),
        patch("coordinator.collect_snapshot", return_value=state),
        patch("coordinator.ensure_control", return_value=control),
        patch("coordinator.reconcile_review", return_value=("NONE", control)),
        patch("coordinator.run_planner", return_value=PlannerOutput((), None, "no work")),
        patch("coordinator.apply_planner_transaction"),
        patch("coordinator._run", return_value="a" * 40),
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
        cls.m2_document = json.loads(
            (ROOT / "project" / "milestones" / "m2" / "milestone.json").read_text()
        )

    @staticmethod
    def _discovery_result(
        *,
        status: str = "FAIL",
        disposition: str = "REPAIRABLE_IMPLEMENTATION",
        tested_sha: str = "a" * 40,
    ) -> dict:
        return {
            "schema_version": "m2-discovery-result-v1",
            "milestone": "m2",
            "status": status,
            "disposition": disposition,
            "failure_scope": "formation" if disposition == "REPAIRABLE_IMPLEMENTATION" else "",
            "failure_code": "python-typeerror" if disposition == "REPAIRABLE_IMPLEMENTATION" else "",
            "failure_fingerprint": "f" * 64,
            "tested_sha": tested_sha,
            "lease_sha256": "e" * 64,
            "run_id": "12345",
            "run_attempt": 1,
            "invocation_id": "m2-discovery-gh-12345-attempt-1",
            "run_outcome": "success",
            "cleanup_outcome": "success",
            "report_digest": "b" * 64,
            "evidence_digest": "c" * 64,
            "summary": "TypeError in the formation collector",
            "result_digest": "d" * 64,
        }

    @staticmethod
    def _m2_record_state(control: dict, *, default_sha: str = "a" * 40) -> dict:
        return {
            "repository": "owner/repo",
            "default_branch": "main",
            "default_sha": default_sha,
            "milestone": "m2",
            "milestone_number": 2,
            "issues": [control],
            "pull_requests": [],
        }

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

    def test_queued_dispatch_with_stale_checkout_fails_before_writes(self) -> None:
        state = snapshot([])
        state["default_sha"] = "b" * 40
        client = FakeClient()
        with (
            patch(
                "coordinator.load_trusted_documents",
                return_value=(self.milestone, self.catalog),
            ),
            patch("coordinator.collect_snapshot", return_value=state),
            patch("coordinator._run", return_value="a" * 40),
            patch("coordinator.ensure_control") as ensure_control,
            patch("coordinator.run_planner") as run_planner,
            self.assertRaisesRegex(
                LoopBlocked, "queued coordination checkout is not the live default SHA"
            ),
        ):
            coordinate(
                client=client,
                repo_root=ROOT,
                runtime_root=ROOT / ".ignored-test-runtime",
                action="start",
                milestone="m1",
            )
        ensure_control.assert_not_called()
        run_planner.assert_not_called()
        self.assertEqual(client.writes, [])

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

    def test_m2_canonical_unresolved_candidates_reach_authorization(self) -> None:
        milestone = m2_milestone()
        result, client = coordinate_m2(milestone, self.catalog)
        self.assertTrue(m2_discovery_eligible(milestone, "m2"))
        self.assertEqual(result["status"], "MILESTONE")
        self.assertEqual(result["milestone"], "m2")
        self.assertEqual(result["entrypoint"], "discovery")
        self.assertEqual(result["default_sha"], "a" * 40)
        self.assertRegex(result["readiness_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(len(client.writes), 1)
        self.assertIn("REAL_AUTHORIZATION_REQUIRED", client.writes[0][2])

    def test_m2_explicit_candidates_can_reach_milestone_gate(self) -> None:
        milestone = m2_milestone(
            selected_strategy="tree_meet_addslotsrange",
            selected_timeout_ms="10000",
        )
        result, _client = coordinate_m2(milestone, self.catalog)
        self.assertFalse(m2_discovery_eligible(milestone, "m2"))
        self.assertEqual(result["status"], "MILESTONE")
        self.assertEqual(result["milestone"], "m2")
        self.assertEqual(result["entrypoint"], "milestone")

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
        self.assertFalse(m2_discovery_eligible(milestone, "m2"))
        result, _client = coordinate_m2(milestone, self.catalog)
        self.assertEqual(result["reason"], "candidate-not-ready")

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
        self.assertFalse(m2_discovery_eligible(milestone, "m2"))

    def test_m2_extra_candidate_parameters_fail_closed(self) -> None:
        milestone = m2_milestone()
        for criterion in milestone["criteria"]:
            for check in criterion.get("check", []):
                if check["id"].startswith("real.local.m2-"):
                    check["parameters"]["unexpected"] = "not-reviewed"
        self.assertEqual(len(m2_candidate_blockers(milestone, "m2")), 4)
        self.assertFalse(m2_discovery_eligible(milestone, "m2"))

    def test_m2_discovery_requires_exact_occurrences_and_parameter_maps(self) -> None:
        duplicate = m2_milestone()
        formation = next(
            check
            for criterion in duplicate["criteria"]
            for check in criterion.get("check", [])
            if check["id"] == "real.local.m2-cluster-formation"
        )
        duplicate["criteria"][-1].setdefault("check", []).append(copy.deepcopy(formation))

        missing = m2_milestone()
        stability = next(
            check
            for criterion in missing["criteria"]
            for check in criterion.get("check", [])
            if check["id"] == "real.local.m2-stability-resource"
        )
        del stability["parameters"]["selected_timeout_ms"]

        for malformed in (duplicate, missing):
            self.assertFalse(m2_discovery_eligible(malformed, "m2"))
            result, _client = coordinate_m2(malformed, self.catalog)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["reason"], "candidate-not-ready")

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
            self.assertFalse(m2_discovery_eligible(malformed, milestone))

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
        legacy = {
            "version": 1,
            "milestone": "m1",
            "status": "exhausted",
            "nonce": "previous-invocation",
            "expires_at": "2026-07-20T00:00:00Z",
            "remaining": 0,
        }
        self.assertEqual(
            parse_control({"number": 9, "body": render_control(legacy, 0)}, "m1").lease,
            legacy,
        )
        malformed = dict(legacy)
        malformed["expires_at"] = "garbage"
        with self.assertRaises(ContractError):
            parse_control(
                {"number": 9, "body": render_control(malformed, 0)}, "m1"
            )
        malformed = dict(empty_lease("m1"))
        malformed["nonce"] = "unexpected"
        with self.assertRaises(ContractError):
            parse_control(
                {"number": 9, "body": render_control(malformed, 0)}, "m1"
            )
        with self.assertRaises(ContractError):
            parse_control({"number": 9, "body": body + "\nState: running"}, "m1")

    def test_human_action_dedup_stays_within_the_authoritative_comment_bound(self) -> None:
        control = {
            "number": 9,
            "body": render_control(empty_lease("m2"), 0),
            "labels": [CONTROL_LABEL],
            "comments": [{"author": "human", "body": "note"} for _ in range(49)],
        }
        state = self._m2_record_state(control)
        parsed = ControlState(9, empty_lease("m2"), 0)
        client = FakeClient(control)
        arguments = {
            "client": client,
            "snapshot": state,
            "control": parsed,
            "state": "HARD_BLOCKED",
            "target": "run:123:attempt:1",
            "sha": "a" * 40,
            "action": "Inspect the protected run.",
            "link": "https://github.com/owner/repo/actions/runs/123/attempts/1",
        }
        self.assertTrue(record_human_action_state(**arguments))
        self.assertFalse(record_human_action_state(**arguments))
        self.assertEqual(len(control["comments"]), 50)
        self.assertEqual(len(client.writes), 1)

        full = copy.deepcopy(control)
        full["comments"][-1] = {"author": "human", "body": "another note"}
        full_client = FakeClient(full)
        with self.assertRaises(LoopBlocked):
            record_human_action_state(
                **{**arguments, "client": full_client, "target": "run:124:attempt:1"}
            )
        self.assertEqual(full_client.writes, [])

        overflow = copy.deepcopy(full)
        overflow["comments"].append({"author": "human", "body": "overflow"})
        overflow_client = FakeClient(overflow)
        with self.assertRaises(LoopBlocked):
            record_human_action_state(
                **{**arguments, "client": overflow_client, "target": "run:125:attempt:1"}
            )
        self.assertEqual(overflow_client.writes, [])

    def test_discovery_record_refuses_a_partial_capacity_write(self) -> None:
        control = {
            "number": 9,
            "body": render_control(empty_lease("m2"), 0),
            "labels": [CONTROL_LABEL],
            "comments": [{"author": "human", "body": "note"} for _ in range(49)],
        }
        state = self._m2_record_state(control)
        client = FakeClient(control)
        with patch("coordinator.collect_snapshot", return_value=state):
            with self.assertRaises(LoopBlocked):
                record_m2_discovery_result(
                    client=client,
                    result=self._discovery_result(),
                )
        self.assertEqual(client.writes, [])

    def test_discovery_hard_block_refuses_a_partial_capacity_write(self) -> None:
        for result, default_sha in (
            (self._discovery_result(disposition="HUMAN_REQUIRED"), "a" * 40),
            (self._discovery_result(), "b" * 40),
        ):
            with self.subTest(disposition=result["disposition"], default_sha=default_sha):
                control = {
                    "number": 9,
                    "body": render_control(empty_lease("m2"), 0),
                    "labels": [CONTROL_LABEL],
                    "comments": [
                        {"author": "human", "body": "note"} for _ in range(49)
                    ],
                }
                state = self._m2_record_state(control, default_sha=default_sha)
                client = FakeClient(control)
                with patch("coordinator.collect_snapshot", return_value=state):
                    with self.assertRaises(LoopBlocked):
                        record_m2_discovery_result(client=client, result=result)
                self.assertEqual(client.writes, [])

    def test_real_authorization_action_is_deduplicated_without_editing_lease(self) -> None:
        control = {
            "number": 9,
            "title": "control",
            "body": render_control(empty_lease("m1"), 0),
            "state": "open",
            "labels": [CONTROL_LABEL],
            "comments": [],
        }
        state = snapshot([control])
        client = FakeClient(control)
        control_state = parse_control(control, "m1")
        original_body = control["body"]
        with patch.dict(
            "os.environ",
            {
                "GITHUB_RUN_ID": "12345",
                "GITHUB_RUN_ATTEMPT": "2",
                "GITHUB_SERVER_URL": "https://github.com",
            },
            clear=True,
        ):
            record_real_authorization_required(client, state, control_state)
            record_real_authorization_required(client, state, control_state)
        comments = [write for write in client.writes if write[0] == "comment"]
        self.assertEqual(len(comments), 1)
        self.assertIn("REAL_AUTHORIZATION_REQUIRED", comments[0][2])
        self.assertIn("/owner/repo/actions/runs/12345", comments[0][2])
        self.assertEqual(control["body"], original_body)

    def test_nonreplaceable_lease_hard_blocks_before_environment_review(self) -> None:
        active = {
            "version": 1,
            "milestone": "m1",
            "status": "active",
            "nonce": "legacy-active",
            "expires_at": "2026-07-21T12:00:00Z",
            "remaining": 1,
        }
        control = {
            "number": 9,
            "title": "control",
            "body": render_control(active, 0),
            "state": "open",
            "labels": [CONTROL_LABEL],
            "comments": [],
        }
        state = snapshot([control])
        client = FakeClient(control)
        with (
            patch.dict(
                "os.environ",
                {
                    "GITHUB_RUN_ID": "12345",
                    "GITHUB_RUN_ATTEMPT": "1",
                    "GITHUB_SERVER_URL": "https://github.com",
                },
                clear=True,
            ),
            patch("coordinator.collect_snapshot", return_value=state),
            patch("coordinator._run", return_value="a" * 40),
        ):
            result = prepare_real_authorization(
                client=client,
                repo_root=ROOT,
                milestone="m1",
                entrypoint="milestone",
                control=parse_control(control, "m1"),
            )
        self.assertEqual(result["status"], "BLOCKED")
        comments = [write for write in client.writes if write[0] == "comment"]
        self.assertEqual(len(comments), 1)
        self.assertIn("HARD_BLOCKED", comments[0][2])
        self.assertFalse(any(write[0] == "update" for write in client.writes))

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
        with self.assertRaises((LoopBlocked, ContractError)):
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

    def test_discovery_failure_record_is_idempotent_and_requests_diagnosis(self) -> None:
        control = {
            "number": 9,
            "body": render_control(empty_lease("m2"), 0),
            "labels": [CONTROL_LABEL],
            "comments": [],
        }
        state = self._m2_record_state(control)
        client = FakeClient(control)
        result = self._discovery_result()
        with patch("coordinator.collect_snapshot", return_value=state):
            self.assertEqual(
                record_m2_discovery_result(client=client, result=result), "DIAGNOSE"
            )
            self.assertEqual(
                record_m2_discovery_result(client=client, result=result), "NOOP"
            )
            replay = {**result, "run_id": "67890", "run_attempt": 2}
            replay["invocation_id"] = "m2-discovery-gh-67890-attempt-2"
            replay["result_digest"] = "e" * 64
            replay["evidence_digest"] = "1" * 64
            self.assertEqual(
                record_m2_discovery_result(client=client, result=replay), "NOOP"
            )

        record_comments = [
            write
            for write in client.writes
            if write[0] == "comment" and "milestone-loop-m2-discovery:" in write[2]
        ]
        self.assertEqual(len(record_comments), 1)
        self.assertEqual(len([write for write in client.writes if write[0] == "check"]), 1)
        self.assertEqual(len([write for write in client.writes if write[0] == "dispatch"]), 1)
        self.assertEqual(client.check_reads, 1)
        pending = pending_m2_discovery_diagnosis(state)
        self.assertIsNotNone(pending)
        self.assertEqual(pending["failure_fingerprint"], "f" * 64)

    def test_discovery_check_history_must_fit_the_authoritative_page(self) -> None:
        control = {
            "number": 9,
            "body": render_control(empty_lease("m2"), 0),
            "labels": [CONTROL_LABEL],
            "comments": [],
        }
        state = self._m2_record_state(control)
        client = FakeClient(control)
        result = self._discovery_result(
            status="PASS", disposition="CANDIDATE_SELECTION_ONLY"
        )
        with (
            patch("coordinator.collect_snapshot", return_value=state),
            patch.object(
                client,
                "api",
                return_value={"total_count": 101, "check_runs": [{}] * 100},
            ),
        ):
            with self.assertRaises(LoopBlocked):
                record_m2_discovery_result(client=client, result=result)
        self.assertEqual(client.writes, [])

    def test_discovery_check_creation_preserves_the_authoritative_page(self) -> None:
        control = {
            "number": 9,
            "body": render_control(empty_lease("m2"), 0),
            "labels": [CONTROL_LABEL],
            "comments": [],
        }
        state = self._m2_record_state(control)
        client = FakeClient(control)
        result = self._discovery_result(
            status="PASS", disposition="CANDIDATE_SELECTION_ONLY"
        )
        checks = [
            {
                "name": "milestone-loop / m2-discovery",
                "external_id": f"other:{index}",
                "head_sha": "a" * 40,
                "status": "completed",
                "conclusion": "success",
                "app": {"slug": "github-actions"},
            }
            for index in range(100)
        ]
        with (
            patch("coordinator.collect_snapshot", return_value=state),
            patch.object(
                client,
                "api",
                return_value={"total_count": 100, "check_runs": checks},
            ),
        ):
            with self.assertRaises(LoopBlocked):
                record_m2_discovery_result(client=client, result=result)
        self.assertEqual(client.writes, [])

    def test_discovery_reuses_only_a_trusted_consistent_partial_check(self) -> None:
        control = {
            "number": 9,
            "body": render_control(empty_lease("m2"), 0),
            "labels": [CONTROL_LABEL],
            "comments": [],
        }
        state = self._m2_record_state(control)
        client = FakeClient(control)
        result = self._discovery_result(
            status="PASS", disposition="CANDIDATE_SELECTION_ONLY"
        )
        with patch("coordinator.collect_snapshot", return_value=state):
            with (
                patch.object(
                    client,
                    "comment",
                    side_effect=RuntimeError("simulated record write failure"),
                ),
                self.assertRaises(RuntimeError),
            ):
                record_m2_discovery_result(client=client, result=result)
            self.assertEqual(
                record_m2_discovery_result(client=client, result=result), "RECORDED"
            )
        self.assertEqual(
            len([write for write in client.writes if write[0] == "check"]), 1
        )
        self.assertEqual(client.check_reads, 2)

    def test_discovery_rejects_an_untrusted_or_inconsistent_partial_check(self) -> None:
        for mutation in ("app", "conclusion"):
            with self.subTest(mutation=mutation):
                control = {
                    "number": 9,
                    "body": render_control(empty_lease("m2"), 0),
                    "labels": [CONTROL_LABEL],
                    "comments": [],
                }
                state = self._m2_record_state(control)
                client = FakeClient(control)
                result = self._discovery_result(
                    status="PASS", disposition="CANDIDATE_SELECTION_ONLY"
                )
                with patch("coordinator.collect_snapshot", return_value=state):
                    with (
                        patch.object(
                            client,
                            "comment",
                            side_effect=RuntimeError("simulated record write failure"),
                        ),
                        self.assertRaises(RuntimeError),
                    ):
                        record_m2_discovery_result(client=client, result=result)
                    check = {
                        "name": client.writes[0][1]["name"],
                        "external_id": client.writes[0][1]["external_id"],
                        "head_sha": client.writes[0][1]["head_sha"],
                        "status": "completed",
                        "conclusion": client.writes[0][1]["conclusion"],
                        "app": {"slug": "github-actions"},
                    }
                    if mutation == "app":
                        check["app"] = {"slug": "untrusted-app"}
                    else:
                        check["conclusion"] = "failure"
                    with (
                        patch.object(
                            client,
                            "api",
                            return_value={"total_count": 1, "check_runs": [check]},
                        ),
                        self.assertRaises(LoopBlocked),
                    ):
                        record_m2_discovery_result(client=client, result=result)
                self.assertEqual(len(client.writes), 1)

    def test_discovery_replay_never_repeats_an_ambiguous_dispatch(self) -> None:
        control = {
            "number": 9,
            "body": render_control(empty_lease("m2"), 0),
            "labels": [CONTROL_LABEL],
            "comments": [],
        }
        state = self._m2_record_state(control)
        client = FakeClient(control)
        result = self._discovery_result()
        original_comment = client.comment

        def fail_dispatch_receipt(number, body) -> None:
            if "milestone-loop-m2-discovery-dispatch:" in body:
                raise RuntimeError("simulated receipt write failure")
            original_comment(number, body)

        with patch("coordinator.collect_snapshot", return_value=state):
            with (
                patch.object(client, "comment", side_effect=fail_dispatch_receipt),
                self.assertRaises(RuntimeError),
            ):
                record_m2_discovery_result(client=client, result=result)
            replay = {
                **result,
                "run_id": "67890",
                "run_attempt": 2,
                "invocation_id": "m2-discovery-gh-67890-attempt-2",
                "result_digest": "e" * 64,
                "evidence_digest": "1" * 64,
            }
            self.assertEqual(
                record_m2_discovery_result(client=client, result=replay),
                "HUMAN_REQUIRED",
            )

        self.assertEqual(
            len([write for write in client.writes if write[0] == "dispatch"]), 1
        )
        hard_blocks = [
            write
            for write in client.writes
            if write[0] == "comment" and "HARD_BLOCKED" in write[2]
        ]
        self.assertEqual(len(hard_blocks), 1)
        self.assertIn("/actions/runs/12345/attempts/1", hard_blocks[0][2])
        self.assertNotIn("/actions/runs/67890", hard_blocks[0][2])

    def test_genuine_discovery_failure_never_enters_diagnosis(self) -> None:
        control = {
            "number": 9,
            "body": render_control(empty_lease("m2"), 0),
            "labels": [CONTROL_LABEL],
            "comments": [],
        }
        state = self._m2_record_state(control)
        client = FakeClient(control)
        result = self._discovery_result(disposition="HUMAN_REQUIRED")
        result["summary"] = "candidate exceeded the fixed safety bound"
        with patch("coordinator.collect_snapshot", return_value=state):
            self.assertEqual(
                record_m2_discovery_result(client=client, result=result),
                "HUMAN_REQUIRED",
            )
        self.assertIsNone(pending_m2_discovery_diagnosis(state))
        human = [
            write
            for write in client.writes
            if write[0] == "comment" and "HARD_BLOCKED" in write[2]
        ]
        self.assertEqual(len(human), 1)

    def test_discovery_pass_is_record_only_and_stale_sha_fails_closed(self) -> None:
        control = {
            "number": 9,
            "body": render_control(empty_lease("m2"), 0),
            "labels": [CONTROL_LABEL],
            "comments": [],
        }
        state = self._m2_record_state(control)
        client = FakeClient(control)
        passed = self._discovery_result(status="PASS", disposition="CANDIDATE_SELECTION_ONLY")
        with patch("coordinator.collect_snapshot", return_value=state):
            self.assertEqual(
                record_m2_discovery_result(client=client, result=passed), "RECORDED"
            )
        self.assertIsNone(pending_m2_discovery_diagnosis(state))

        stale_control = {
            "number": 10,
            "body": render_control(empty_lease("m2"), 0),
            "labels": [CONTROL_LABEL],
            "comments": [],
        }
        stale_state = self._m2_record_state(stale_control, default_sha="b" * 40)
        stale_client = FakeClient(stale_control)
        with patch("coordinator.collect_snapshot", return_value=stale_state):
            self.assertEqual(
                record_m2_discovery_result(client=stale_client, result=passed),
                "HUMAN_REQUIRED",
            )
        stale_check = next(write for write in stale_client.writes if write[0] == "check")
        self.assertEqual(stale_check[1]["conclusion"], "action_required")

    def test_discovery_diagnosis_creates_one_narrow_ready_work_item(self) -> None:
        state = self._m2_record_state(
            {
                "number": 9,
                "body": render_control(empty_lease("m2"), 0),
                "labels": [CONTROL_LABEL],
                "comments": [],
            }
        )
        operation = PlannerOperation(
            "create",
            None,
            "Repair formation collection",
            "Fix only the current implementation defect.",
            "performance.cluster-formation-experiment",
            (),
            "repository.all",
            "ready",
        )
        transaction = prepare_planner_transaction(
            snapshot=state,
            output=PlannerOutput((operation,), None, "bounded repair"),
            milestone_document=self.m2_document,
            catalog_document=self.catalog,
        )
        validated = validate_m2_discovery_diagnosis(
            transaction, record=self._discovery_result()
        )
        self.assertEqual(len(validated.writes), 1)
        self.assertIn(DISCOVERY_REPAIR_LABEL, validated.writes[0].labels)
        self.assertIn("M2-Discovery-Fingerprint: " + "f" * 64, validated.writes[0].body)

    def test_discovery_failure_enters_existing_planner_worker_path(self) -> None:
        control = {
            "number": 9,
            "title": "[milestone-loop] m2 control",
            "body": render_control(empty_lease("m2"), 0),
            "state": "open",
            "labels": [CONTROL_LABEL],
            "comments": [],
        }
        state = self._m2_record_state(control)
        client = FakeClient(control)
        operation = PlannerOperation(
            "create",
            None,
            "Repair formation collection",
            "Fix only the current implementation defect.",
            "performance.cluster-formation-experiment",
            (),
            "repository.all",
            "ready",
        )

        def apply_transaction(*, transaction, **_kwargs) -> None:
            write = transaction.writes[0]
            state["issues"].append(
                {
                    "number": 99,
                    "title": write.title,
                    "body": write.body,
                    "state": "open",
                    "labels": list(write.labels),
                    "comments": [],
                }
            )

        with patch("coordinator.collect_snapshot", return_value=state):
            self.assertEqual(
                record_m2_discovery_result(
                    client=client, result=self._discovery_result()
                ),
                "DIAGNOSE",
            )
            with (
                patch(
                    "coordinator.load_trusted_documents",
                    return_value=(self.m2_document, self.catalog),
                ),
                patch(
                    "coordinator.run_planner",
                    return_value=PlannerOutput((operation,), None, "bounded repair"),
                ),
                patch(
                    "coordinator.apply_planner_transaction",
                    side_effect=apply_transaction,
                ),
                patch("coordinator.run_worker", return_value="WAIT_PR") as worker,
                patch("coordinator._run", return_value="a" * 40),
            ):
                outcome = coordinate(
                    client=client,
                    repo_root=ROOT,
                    runtime_root=ROOT / ".ignored-test-runtime",
                    action="resume",
                    milestone="m2",
                )
        self.assertEqual(outcome["status"], "WAIT_PR")
        worker.assert_called_once()
        self.assertEqual(worker.call_args.kwargs["issue_number"], 99)

    def test_discovery_repair_protected_exception_is_exact(self) -> None:
        self.assertEqual(
            set(M2_DISCOVERY_REPAIR_PROTECTED_PREFIXES),
            {
                "project/scripts/m2_candidate_discovery.py",
                "project/scripts/m2_performance_capture.py",
                "project/src/valkey_scale_lab/runtime/docker_runtime.py",
            },
        )
        self.assertNotIn(
            ".github/workflows/milestone-loop.yml",
            M2_DISCOVERY_REPAIR_PROTECTED_PREFIXES,
        )
        self.assertNotIn(
            "project/scripts/m2_performance_gate.py",
            M2_DISCOVERY_REPAIR_ALLOWED_PREFIXES,
        )

    def test_discovery_retry_preserves_identity_and_same_work_item(self) -> None:
        repair = {
            "number": 7,
            "title": "Repair formation collection",
            "body": (
                "Fix the implementation defect.\n\n"
                "Criterion: performance.cluster-formation-experiment\n"
                "Depends on: none\n"
                "Check: repository.all\n\n"
                f"M2-Discovery-Fingerprint: {'f' * 64}\n"
                "M2-Discovery-Run: 12345 attempt 1\n"
                f"M2-Discovery-Tested-SHA: {'a' * 40}\n"
                "M2-Discovery-Failure-Code: python-typeerror\n"
                "M2-Discovery-Summary: bounded failure"
            ),
            "state": "open",
            "labels": [
                "milestone-loop:work-item",
                "milestone-loop:blocked",
                DISCOVERY_REPAIR_LABEL,
            ],
            "comments": [],
        }
        state = self._m2_record_state(
            {
                "number": 9,
                "body": render_control(empty_lease("m2"), 0),
                "labels": [CONTROL_LABEL],
                "comments": [],
            }
        )
        state["issues"].append(repair)
        operation = PlannerOperation(
            "update",
            7,
            None,
            "Retry the same bounded implementation repair.",
            "performance.cluster-formation-experiment",
            (),
            "repository.all",
            "ready",
        )
        transaction = prepare_planner_transaction(
            snapshot=state,
            output=PlannerOutput((operation,), 7, "retry"),
            milestone_document=self.m2_document,
            catalog_document=self.catalog,
        )
        validate_failure_diagnosis(transaction, issue_number=7, snapshot=state)
        self.assertIn("M2-Discovery-Fingerprint: " + "f" * 64, transaction.writes[0].body)
        self.assertIn(DISCOVERY_REPAIR_LABEL, transaction.writes[0].labels)

        state["issues"].append(issue(6, "completed"))
        dependent = PlannerOperation(
            "update",
            7,
            None,
            "Retry through an unrelated prerequisite.",
            "performance.cluster-formation-experiment",
            (6,),
            "repository.all",
            "ready",
        )
        dependent_transaction = prepare_planner_transaction(
            snapshot=state,
            output=PlannerOutput((dependent,), 7, "bad dependency"),
            milestone_document=self.m2_document,
            catalog_document=self.catalog,
        )
        with self.assertRaises(ContractError):
            validate_failure_diagnosis(
                dependent_transaction, issue_number=7, snapshot=state
            )

    def test_only_trusted_discovery_contract_failure_can_self_dispatch(self) -> None:
        result = self._discovery_result()
        record = {
            "version": 1,
            "milestone": "m2",
            "run_id": result["run_id"],
            "run_attempt": result["run_attempt"],
            "tested_sha": result["tested_sha"],
            "lease_sha256": result["lease_sha256"],
            "result_digest": result["result_digest"],
            "report_digest": result["report_digest"],
            "evidence_digest": result["evidence_digest"],
            "cleanup_outcome": result["cleanup_outcome"],
            "dedup_key": "2" * 64,
            "status": "FAIL",
            "disposition": "REPAIRABLE_IMPLEMENTATION",
            "failure_scope": "formation",
            "failure_code": "python-typeerror",
            "failure_fingerprint": "f" * 64,
            "summary": result["summary"],
        }
        control = {
            "number": 9,
            "body": render_control(empty_lease("m2"), 0),
            "labels": [CONTROL_LABEL],
            "comments": [
                {
                    "author": "github-actions[bot]",
                    "body": "<!-- milestone-loop-m2-discovery: "
                    + json.dumps(record, separators=(",", ":"))
                    + " -->",
                },
                {
                    "author": "github-actions[bot]",
                    "body": "<!-- milestone-loop-m2-discovery-diagnosis-complete: "
                    + "f" * 64
                    + " -->",
                },
            ],
        }
        repair = {
            "number": 7,
            "title": "Repair formation collection",
            "body": (
                "Fix it.\n\nCriterion: performance.cluster-formation-experiment\n"
                "Depends on: none\nCheck: repository.all\n\n"
                f"M2-Discovery-Fingerprint: {'f' * 64}\n"
                "M2-Discovery-Run: 12345 attempt 1\n"
                f"M2-Discovery-Tested-SHA: {'a' * 40}\n"
                "M2-Discovery-Failure-Code: python-typeerror\n"
                f"M2-Discovery-Summary: {result['summary']}"
            ),
            "state": "open",
            "labels": [
                "milestone-loop:work-item",
                "milestone-loop:review",
                DISCOVERY_REPAIR_LABEL,
            ],
            "comments": [],
        }
        state = self._m2_record_state(control)
        state["issues"].append(repair)
        state["pull_requests"] = [
            {
                "number": 11,
                "state": "open",
                "head_sha": "b" * 40,
                "labels": ["contract-change"],
                "body": (
                    "Milestone: m2\nWork-Item: #7\nContract-Change: true\n"
                    f"M2-Discovery-Fingerprint: {'f' * 64}"
                ),
            }
        ]
        self.assertTrue(
            trusted_m2_discovery_repair_pr(
                state, pr_number=11, head_sha="b" * 40
            )
        )
        state["pull_requests"][0]["labels"] = []
        self.assertFalse(
            trusted_m2_discovery_repair_pr(
                state, pr_number=11, head_sha="b" * 40
            )
        )
        state["pull_requests"][0]["labels"] = ["contract-change"]
        original_body = repair["body"]
        repair["body"] = original_body.replace(
            "Criterion: performance.cluster-formation-experiment",
            "Criterion: performance.automatic-failover-experiment",
        )
        with self.assertRaises(LoopBlocked):
            trusted_m2_discovery_repair_pr(
                state, pr_number=11, head_sha="b" * 40
            )
        repair["body"] = original_body.replace(
            "M2-Discovery-Run: 12345 attempt 1",
            "M2-Discovery-Run: 99999 attempt 9",
        )
        with self.assertRaises(LoopBlocked):
            trusted_m2_discovery_repair_pr(
                state, pr_number=11, head_sha="b" * 40
            )

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
