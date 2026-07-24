from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

from context_builder import MAX_CONTEXT_BYTES, build_context
from contracts import ContractError
from coordinator import (
    CONTROL_LABEL,
    PR_MILESTONE_RE,
    LoopBlocked,
    empty_lease,
    parse_control,
    render_control,
    real_readiness_fingerprint,
)
from github_api import MAX_ISSUE_COMMENTS, GitHubClient, GitHubError
from loop import _publish_verification_comment, main as loop_main, pr_metadata
from milestone_runner import (
    LeaseConfirmationBlocked,
    _canonical_digest,
    _gate_environment,
    _gate_result_summary,
    _lease_fingerprint,
    _m2_discovery_run_id,
    _validate_consumed_lease,
    authorize_real_invocation,
    bind_real_result,
    load_milestone_result,
    load_m2_discovery_result,
    run_gate,
    run_m2_discovery,
    seal_milestone_result,
    seal_m2_discovery_result,
    validate_real_result_binding,
)
from loop import _version
from recovery import cleanup_owned_docker, cleanup_runtime_root
from verifier import verify


ROOT = Path(__file__).resolve().parents[3]


class InvocationClient:
    def __init__(self, control: dict, run: dict) -> None:
        self.control = control
        self.run = run
        self.environment = {
            "name": "valkey-real",
            "protection_rules": [
                {
                    "type": "required_reviewers",
                    "prevent_self_review": False,
                    "reviewers": [
                        {"type": "User", "reviewer": {"login": "reviewer"}}
                    ],
                }
            ],
        }
        self.updates: list[dict] = []
        self.after_update = None
        self.confirmation_error: Exception | None = None

    def api(self, endpoint: str, **_kwargs):
        if endpoint == f"issues/{self.control['number']}":
            if self.confirmation_error is not None:
                raise self.confirmation_error
            return dict(self.control)
        if endpoint == "environments/valkey-real":
            return dict(self.environment)
        if endpoint.startswith("actions/runs/"):
            return dict(self.run)
        raise AssertionError(endpoint)

    def update_issue(self, number: int, **kwargs) -> None:
        self.assert_control(number)
        self.updates.append(kwargs)
        self.control.update(kwargs)
        if self.after_update is not None:
            self.after_update()

    def assert_control(self, number: int) -> None:
        if number != self.control["number"]:
            raise AssertionError(number)


class BoundaryTests(unittest.TestCase):
    def test_environment_rejection_skips_discovery_recorder(self) -> None:
        workflow = (ROOT / ".github/workflows/milestone-loop.yml").read_text()
        discovery_job = workflow.split("\n  m2-discovery:", 1)[1].split(
            "\n  record-m2-discovery:", 1
        )[0]
        recorder_condition = workflow.split("\n  record-m2-discovery:", 1)[1].split(
            "    runs-on:", 1
        )[0]
        self.assertIn(
            "environment_started: ${{ steps.protected_checkout.outcome }}",
            discovery_job,
        )
        self.assertIn("always()", recorder_condition)
        self.assertIn(
            "needs.m2-discovery.outputs.lease_sha256 != ''", recorder_condition
        )
        self.assertIn(
            "needs.m2-discovery.outputs.environment_started != ''",
            recorder_condition,
        )
        self.assertNotIn("needs.m2-discovery.result == 'success'", recorder_condition)

    def test_started_environment_preflight_records_milestone_blocked(self) -> None:
        workflow = (ROOT / ".github/workflows/milestone-loop.yml").read_text()
        milestone_job = workflow.split("\n  milestone:", 1)[1].split(
            "\n  m2-discovery:", 1
        )[0]
        record_job = workflow.split("\n  record-milestone:", 1)[1]
        self.assertIn(
            "environment_started: ${{ steps.protected_checkout.outcome }}",
            milestone_job,
        )
        self.assertLess(
            milestone_job.index("id: protected_checkout"),
            milestone_job.index("authorize-real-invocation"),
        )
        self.assertIn(
            "needs.milestone.outputs.environment_started != ''", record_job
        )
        self.assertIn("needs.milestone.outputs.lease_sha256 != ''", record_job)
        self.assertIn("--environment-started", record_job)

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "github-output"
            with (
                patch.dict(
                    os.environ,
                    {
                        "GITHUB_OUTPUT": str(output),
                        "GITHUB_RUN_ID": "12345",
                        "GITHUB_RUN_ATTEMPT": "2",
                    },
                    clear=True,
                ),
                patch("loop.GitHubClient.from_environment", return_value=object()),
                patch("loop.record_milestone_result", return_value="BLOCKED") as record,
                patch("builtins.print"),
            ):
                exit_code = loop_main(
                    [
                        "record-milestone",
                        "--milestone",
                        "m1",
                        "--expected-sha",
                        "a" * 40,
                        "--expected-lease-sha256",
                        "",
                        "--environment-started",
                        "failure",
                        "--run-id",
                        "12345",
                        "--run-attempt",
                        "2",
                        "--result",
                        str(Path(temporary) / "missing.json"),
                    ]
                )
            outputs = dict(
                line.split("=", 1)
                for line in output.read_text(encoding="utf-8").splitlines()
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(outputs["status"], "BLOCKED")
        self.assertEqual(record.call_args.kwargs["status"], "BLOCKED")
        self.assertIn(
            "did not produce a confirmed consumed Lease",
            record.call_args.kwargs["summary"],
        )

    def test_pr_metadata_uses_live_body_labels_and_fixed_head(self) -> None:
        event = {
            "action": "opened",
            "repository": {"full_name": "owner/repo"},
            "pull_request": {
                "number": 42,
                "author_association": "OWNER",
                "body": (
                    "Milestone: m2\nWork-Item: #7\nContract-Change: true\n"
                    f"M2-Discovery-Fingerprint: {'f' * 64}"
                ),
                "labels": [],
                "merged": False,
                "head": {"sha": "b" * 40, "repo": {"full_name": "owner/repo"}},
                "base": {"sha": "a" * 40},
            },
        }
        live = copy.deepcopy(event["pull_request"])
        live["state"] = "open"
        live["body"] = "Milestone: m2\nWork-Item: #7\nContract-Change: false\n"
        live["labels"] = []
        snapshot = {
            "issues": [
                {
                    "number": 7,
                    "state": "open",
                    "labels": ["milestone-loop:work-item", "milestone-loop:review"],
                    "body": (
                        "Implement it.\n\nCriterion: local.lifecycle\n"
                        "Depends on: none\nCheck: product.unit"
                    ),
                }
            ]
        }
        client = Mock()
        client.api.return_value = live
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "event.json"
            path.write_text(json.dumps(event), encoding="utf-8")
            with patch("loop.collect_snapshot", return_value=snapshot):
                metadata = pr_metadata(client, path)
            self.assertEqual(
                (metadata["contract_change"], metadata["check"], metadata["work_item"]),
                (False, "product.unit", 7),
            )
            live["labels"] = [{"name": "contract-change"}]
            with patch("loop.collect_snapshot", return_value=snapshot):
                metadata = pr_metadata(client, path)
            self.assertEqual(
                (metadata["contract_change"], metadata["check"]),
                (True, "repository.all"),
            )
            with (
                patch("loop.collect_snapshot", return_value={"issues": []}),
                self.assertRaises(ContractError),
            ):
                pr_metadata(client, path)
            snapshot["issues"][0]["labels"].append("milestone-loop:ready")
            with (
                patch("loop.collect_snapshot", return_value=snapshot),
                self.assertRaises(ContractError),
            ):
                pr_metadata(client, path)
            snapshot["issues"][0]["labels"].pop()
            live["head"]["sha"] = "c" * 40
            with self.assertRaises(LoopBlocked):
                pr_metadata(client, path)
            live["head"]["sha"] = "b" * 40
            live["state"] = "closed"
            with self.assertRaises(LoopBlocked):
                pr_metadata(client, path)
            event["action"] = "closed"
            event["pull_request"]["merged"] = True
            live["merged"] = True
            path.write_text(json.dumps(event), encoding="utf-8")
            with patch("loop.collect_snapshot", return_value=snapshot):
                self.assertTrue(pr_metadata(client, path)["merged"])
            event["action"] = "opened"
            event["pull_request"]["merged"] = False
            live["state"] = "open"
            live["merged"] = False
            path.write_text(json.dumps(event), encoding="utf-8")
            for body in (
                "Milestone: m2\nWork-Item: #7\nNot-Contract-Change: true\n",
                "Milestone: m2\nWork-Item: #7\nContract-Change: trueish\n",
                (
                    "Milestone: m2\nWork-Item: #7\nContract-Change: false\n"
                    "Contract-Change: true\n"
                ),
            ):
                live["body"] = body
                with self.assertRaises(ContractError):
                    pr_metadata(client, path)

    def test_verification_comment_reconciles_one_ambiguous_publish(self) -> None:
        class Client:
            def __init__(self, outcomes: list[str]) -> None:
                self.comments: list[dict] = []
                self.outcomes = outcomes
                self.calls = 0
                self.hidden_reads = 0

            def api(self, endpoint: str):
                if endpoint != f"issues/42/comments?per_page={MAX_ISSUE_COMMENTS + 1}":
                    raise AssertionError(endpoint)
                if self.hidden_reads:
                    self.hidden_reads -= 1
                    return []
                return list(self.comments)

            def comment(self, number: int, body: str) -> None:
                outcome = self.outcomes[self.calls]
                self.calls += 1
                if outcome == "written-eof":
                    self.comments.append(
                        {"user": {"login": "github-actions[bot]"}, "body": body}
                    )
                    raise GitHubError("unexpected EOF")
                if outcome == "written-eof-hidden":
                    self.comments.append(
                        {"user": {"login": "github-actions[bot]"}, "body": body}
                    )
                    self.hidden_reads = 1
                    raise GitHubError("unexpected EOF")
                if outcome == "eof":
                    raise GitHubError("unexpected EOF")
                self.comments.append(
                    {"user": {"login": "github-actions[bot]"}, "body": body}
                )

        record = {"status": "PASS", "head_sha": "b" * 40}
        with patch("loop.time.sleep"):
            written = Client(["written-eof"])
            _publish_verification_comment(written, pr_number=42, record=record)
            self.assertEqual(written.calls, 1)

            delayed = Client(["written-eof-hidden"])
            _publish_verification_comment(delayed, pr_number=42, record=record)
            self.assertEqual(delayed.calls, 1)

            retried = Client(["eof", "success"])
            _publish_verification_comment(retried, pr_number=42, record=record)
            self.assertEqual(retried.calls, 2)
            _publish_verification_comment(retried, pr_number=42, record=record)
            self.assertEqual(retried.calls, 2)

            failed = Client(["eof", "eof"])
            with self.assertRaises(GitHubError):
                _publish_verification_comment(failed, pr_number=42, record=record)
            self.assertEqual(failed.calls, 2)

            invisible = Client(["success"])
            with self.assertRaises(GitHubError):
                with patch.object(invisible, "api", return_value=[]):
                    _publish_verification_comment(invisible, pr_number=42, record=record)
            self.assertEqual(invisible.calls, 1)

            read_eof = Client(["success"])
            original_api = read_eof.api
            read_attempts = iter(("eof", "empty", "empty", "eof", "visible"))

            def intermittent_read(endpoint: str):
                outcome = next(read_attempts)
                if outcome == "eof":
                    raise GitHubError("unexpected EOF")
                if outcome == "empty":
                    return []
                return original_api(endpoint)

            with patch.object(read_eof, "api", side_effect=intermittent_read):
                _publish_verification_comment(read_eof, pr_number=42, record=record)
            self.assertEqual(read_eof.calls, 1)

            capacity = Client(["success"])
            capacity.comments = [{}] * (MAX_ISSUE_COMMENTS - 1)
            _publish_verification_comment(capacity, pr_number=42, record=record)
            self.assertEqual(capacity.calls, 1)

            full = Client(["success"])
            full.comments = [{}] * MAX_ISSUE_COMMENTS
            with self.assertRaises(LoopBlocked):
                _publish_verification_comment(full, pr_number=42, record=record)
            self.assertEqual(full.calls, 0)

    def test_false_contract_metadata_rejects_protected_changes(self) -> None:
        base_sha = "a" * 40
        head_sha = "b" * 40

        def git_result(_cwd: Path, *args: str) -> str:
            if args == ("rev-parse", "HEAD"):
                return head_sha
            if args == ("diff", "--name-only", base_sha, head_sha):
                return ".github/milestone-loop/loop.py"
            if args == ("rev-parse", "HEAD^{tree}"):
                return "c" * 40
            raise AssertionError(args)

        with tempfile.TemporaryDirectory() as temporary:
            metadata = {
                "action": "synchronize",
                "base_sha": base_sha,
                "check": "product.unit",
                "contract_change": False,
                "head_sha": head_sha,
                "merged": False,
                "milestone": "m2",
                "pr": 42,
                "work_item": 7,
            }
            metadata_path = Path(temporary) / "metadata.json"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with (
                patch(
                    "verifier.verification_metadata_path",
                    return_value=metadata_path,
                ),
                patch("verifier._git", side_effect=git_result),
                self.assertRaisesRegex(
                    ContractError,
                    "ordinary Work Item PR changes protected contracts",
                ),
            ):
                verify(
                    trusted_root=ROOT,
                    candidate_root=ROOT,
                    base_sha=base_sha,
                    head_sha=head_sha,
                    check_id="product.unit",
                    pr_number=42,
                    contract_change=False,
                )

    def test_publish_binds_live_work_item_and_contract_metadata(self) -> None:
        record = {
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "work_item_check": "product.unit",
            "work_item": 7,
            "contract_change": False,
            "status": "PASS",
        }
        metadata = {
            "pr": 42,
            "work_item": 7,
            "milestone": "m2",
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "check": "product.unit",
            "contract_change": False,
        }
        with tempfile.TemporaryDirectory() as temporary:
            result_path = Path(temporary) / "result.json"
            event_path = Path(temporary) / "event.json"
            result_path.write_text(
                json.dumps({"record": record, "commands": []}),
                encoding="utf-8",
            )
            event_path.write_text("{}", encoding="utf-8")
            client = Mock()
            client.api.return_value = []
            calls: list[str] = []

            def publish(_number: int, _body: str) -> None:
                client.api.return_value = [
                    {"user": {"login": "github-actions[bot]"}, "body": _body}
                ]
                calls.append("comment")

            def check(**_kwargs) -> None:
                calls.append("check")

            client.comment.side_effect = publish
            client.create_check_run.side_effect = check
            environment = {"GITHUB_EVENT_PATH": str(event_path)}
            argv = [
                "publish-verification",
                "--pr",
                "42",
                "--head-sha",
                "b" * 40,
                "--milestone",
                "m2",
                "--contract-change",
                "false",
                "--result",
                str(result_path),
            ]
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("loop.GitHubClient.from_environment", return_value=client),
                patch("loop.pr_metadata") as live_metadata,
                patch("builtins.print"),
            ):
                live_metadata.return_value = {**metadata, "contract_change": True}
                self.assertEqual(loop_main(argv), 78)
                client.disable_auto_merge.assert_not_called()
                live_metadata.return_value = {**metadata, "work_item": 8}
                self.assertEqual(loop_main(argv), 78)
                client.disable_auto_merge.assert_not_called()
                live_metadata.return_value = metadata
                self.assertEqual(loop_main(argv), 0)
                result_path.write_text(
                    json.dumps(
                        {
                            "record": {"status": "BLOCKED"},
                            "error": "trusted verifier preflight blocked",
                        }
                    ),
                    encoding="utf-8",
                )
                self.assertEqual(loop_main(argv), 0)
        self.assertEqual(calls[:3], ["comment", "check", "check"])
        client.disable_auto_merge.assert_not_called()
        client.dispatch.assert_called_once_with("m2")
        self.assertEqual(
            client.create_check_run.call_args.kwargs["conclusion"],
            "action_required",
        )

    def test_repository_has_one_workflow_and_single_runner_role_routing(self) -> None:
        workflows = sorted((ROOT / ".github" / "workflows").glob("*"))
        self.assertEqual([path.name for path in workflows], ["milestone-loop.yml"])
        text = workflows[0].read_text()
        self.assertIn("[self-hosted, macOS, valkey-codex]", text)
        self.assertIn("[self-hosted, macOS, valkey-verify]", text)
        self.assertIn("[self-hosted, macOS, valkey-real]", text)
        self.assertNotIn("\n  authorize-real:", text)
        self.assertEqual(text.count("environment: valkey-real"), 2)
        self.assertEqual(text.count("authorize-real-invocation"), 2)
        milestone_job = text.split("\n  milestone:", 1)[1].split("\n  m2-discovery:", 1)[0]
        self.assertIn("needs: coordinate", milestone_job)
        self.assertIn("needs.coordinate.outputs.entrypoint == 'milestone'", milestone_job)
        self.assertIn("environment: valkey-real", milestone_job)
        discovery_job = text.split("\n  m2-discovery:", 1)[1].split(
            "\n  record-milestone:", 1
        )[0]
        self.assertIn("needs: coordinate", discovery_job)
        self.assertIn("needs.coordinate.outputs.entrypoint == 'discovery'", discovery_job)
        self.assertIn("environment: valkey-real", discovery_job)
        self.assertIn("run-m2-discovery", discovery_job)
        self.assertIn(
            "m2-discovery-result-${{ github.run_id }}-${{ github.run_attempt }}",
            discovery_job,
        )
        self.assertIn(
            "m2-discovery-evidence-${{ github.run_id }}-${{ github.run_attempt }}",
            discovery_job,
        )
        self.assertIn("seal-m2-discovery", discovery_job)
        self.assertIn("id: cleanup", discovery_job)
        self.assertNotIn('test "${{ steps.discovery.outputs.status }}" = "PASS"', discovery_job)
        discovery_record_job = text.split("\n  record-m2-discovery:", 1)[1].split(
            "\n  record-milestone:", 1
        )[0]
        self.assertIn("if: >-\n      always()", discovery_record_job)
        self.assertIn("record-m2-discovery", discovery_record_job)
        self.assertIn("actions: write", discovery_record_job)
        self.assertNotIn("environment: valkey-real", discovery_record_job)
        self.assertNotIn("id-token: write", discovery_record_job)
        self.assertIn("--expected-lease-sha256", discovery_record_job)
        self.assertIn(
            "needs.m2-discovery.outputs.lease_sha256", discovery_record_job
        )
        self.assertIn(
            'test "${{ steps.record.outputs.discovery_status }}" = "PASS"',
            discovery_record_job,
        )
        self.assertIn("needs: [coordinate, m2-discovery]", discovery_record_job)
        for real_job, product_command, product_condition in (
            (
                milestone_job,
                "run-milestone",
                "if: always() && steps.authorize.outcome == 'success'",
            ),
            (
                discovery_job,
                "run-m2-discovery",
                "if: success() && steps.authorize.outcome == 'success'",
            ),
        ):
            authorize_at = real_job.index("authorize-real-invocation")
            self.assertLess(real_job.index("actions/checkout@v4"), authorize_at)
            self.assertLess(authorize_at, real_job.index("recover\n"))
            self.assertLess(authorize_at, real_job.index(product_command))
            self.assertIn(product_condition, real_job)
            before_authorize = real_job[:authorize_at]
            self.assertNotIn("fingerprint --role real", before_authorize)
            self.assertIn(
                "env -u ACTIONS_ID_TOKEN_REQUEST_URL -u ACTIONS_ID_TOKEN_REQUEST_TOKEN",
                before_authorize,
            )
        record_job = text.split("\n  record-milestone:", 1)[1]
        self.assertIn("needs: [coordinate, milestone]", record_job)
        self.assertIn(
            "needs.coordinate.outputs.entrypoint == 'milestone'", record_job
        )
        self.assertNotIn("record-m2-discovery", record_job)
        self.assertNotIn("m2-discovery", record_job)
        self.assertIn(
            "milestone-result-${{ github.run_id }}-${{ github.run_attempt }}",
            milestone_job,
        )
        self.assertIn(
            "milestone-evidence-${{ github.run_id }}-${{ github.run_attempt }}",
            milestone_job,
        )
        self.assertIn("--expected-lease-sha256", record_job)
        self.assertIn("--run-attempt", record_job)
        self.assertNotIn("ubuntu-latest", text)
        self.assertIn("  candidate:\n    name: milestone-loop / candidate", text)
        self.assertIn('run: test "${{ steps.verify.outcome }}" = "success"', text)
        self.assertIn("group: valkey-scale-lab-milestone-loop", text)
        self.assertIn("cancel-in-progress: false", text)
        after_merge = text.split("\n  after-merge:", 1)[1].split("\n  coordinate:", 1)[0]
        self.assertIn("actions: write", after_merge)
        self.assertIn("github.event.pull_request.merged == true", after_merge)
        self.assertIn("loop.py after-pr", after_merge)
        dispatch_block = text.split("  workflow_dispatch:", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(dispatch_block.count("      action:"), 1)
        self.assertEqual(dispatch_block.count("      milestone:"), 1)
        self.assertIn("options: [start, resume]", dispatch_block)
        self.assertIn("options: [m1, m2, m3, m4]", dispatch_block)
        self.assertIn(
            "(inputs.milestone == 'm1' || inputs.milestone == 'm2' || "
            "inputs.milestone == 'm3' || inputs.milestone == 'm4')",
            text,
        )
        self.assertIn("[\"./gate\", \"milestone\", milestone]", (ROOT / ".github/milestone-loop/milestone_runner.py").read_text())
        self.assertEqual(PR_MILESTONE_RE.search("Milestone: m4").group(1), "m4")
        self.assertIsNone(PR_MILESTONE_RE.search("Milestone: m5"))

    def test_workflow_pins_queued_coordination_to_the_dispatch_sha(self) -> None:
        text = (ROOT / ".github/workflows/milestone-loop.yml").read_text()
        coordinate_job = text.split("\n  coordinate:", 1)[1].split(
            "\n  milestone:", 1
        )[0]
        self.assertIn("ref: ${{ github.sha }}", coordinate_job)
        self.assertNotIn(
            "ref: ${{ github.event.repository.default_branch }}", coordinate_job
        )

    def test_workflow_seals_cleanup_failure_before_recording_milestone(self) -> None:
        text = (ROOT / ".github/workflows/milestone-loop.yml").read_text()
        milestone_job = text.split("\n  milestone:", 1)[1].split(
            "\n  m2-discovery:", 1
        )[0]
        self.assertIn("id: pre_cleanup", milestone_job)
        self.assertIn("id: cleanup", milestone_job)
        self.assertIn("id: evidence", milestone_job)
        self.assertIn("continue-on-error: true", milestone_job)
        self.assertIn("seal-milestone-result", milestone_job)
        self.assertIn(
            "steps.pre_cleanup.outcome == 'success'", milestone_job
        )
        self.assertLess(
            milestone_job.index("id: pre_cleanup"),
            milestone_job.index("id: gate"),
        )
        self.assertLess(
            milestone_job.index("id: gate"),
            milestone_job.index("id: cleanup"),
        )
        self.assertLess(
            milestone_job.index("id: cleanup"),
            milestone_job.index("id: evidence"),
        )
        self.assertLess(
            milestone_job.index("id: evidence"),
            milestone_job.index("seal-milestone-result"),
        )
        self.assertLess(
            milestone_job.index("seal-milestone-result"),
            milestone_job.index("Upload bounded Milestone Gate result"),
        )
        record_job = text.split("\n  record-milestone:", 1)[1]
        self.assertIn("needs.milestone.outputs.lease_sha256 != ''", record_job)
        self.assertNotIn("needs.milestone.result == 'success'", record_job)
        self.assertIn("continue-on-error: true", record_job)
        self.assertIn("id: record\n        if: always()", record_job)
        self.assertIn(
            'test "${{ steps.record.outputs.status }}" = "HUMAN_CLOSE"',
            record_job,
        )
        self.assertNotIn("environment: valkey-real", record_job)
        self.assertNotIn("id-token: write", record_job)

    def test_single_runner_contract_and_bootstrap_order_are_documented(self) -> None:
        readme = (ROOT / ".github/milestone-loop/README.md").read_text()
        plan = (ROOT / "miletone_loop/plan.md").read_text()
        for text in (readme, plan):
            self.assertIn("valkey-local", text)
            self.assertIn("/Users/allgood/actions-runner-valkey", text)
            self.assertIn("2.335.1", text)
            self.assertIn("valkey-codex", text)
            self.assertIn("valkey-verify", text)
            self.assertIn("valkey-real", text)
        self.assertIn("routing labels, not separate runners", readme)
        self.assertIn("trusted base does not yet contain", readme)
        self.assertLess(
            readme.index("Human-review the first `contract-change` PR"),
            readme.index("enable the strict\n   required `milestone-loop / candidate` Check"),
        )
        self.assertNotIn("three separate standard macOS service accounts", readme)

    def test_control_plane_does_not_enter_product_or_read_archive(self) -> None:
        control_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in (ROOT / ".github" / "milestone-loop").rglob("*")
            if path.is_file()
            and "tests" not in path.parts
            and path.suffix in {".py", ".json"}
        )
        self.assertNotIn("loop_evidence/", control_text)
        self.assertFalse(any((ROOT / "project").rglob("*milestone_loop*")))

    def test_agent_context_never_contains_authorization_lease(self) -> None:
        lease = empty_lease("m1")
        lease["nonce"] = "LEASE-MUST-NOT-ENTER-AGENT-CONTEXT"
        state = {
            "repository": "owner/repo",
            "default_branch": "main",
            "default_sha": "a" * 40,
            "issues": [
                {
                    "number": 7,
                    "title": "M1 Control",
                    "body": render_control(lease, 0),
                    "labels": [CONTROL_LABEL],
                    "comments": [],
                }
            ],
            "pull_requests": [],
        }
        context = build_context(
            repo_root=ROOT,
            snapshot=state,
            milestone_document=json.loads(
                (ROOT / "project/milestones/m1/milestone.json").read_text()
            ),
        )
        self.assertNotIn(lease["nonce"], json.dumps(context))

    def test_repository_api_does_not_append_an_empty_path_segment(self) -> None:
        completed = subprocess.CompletedProcess(
            [], 0, b'{"default_branch":"main"}', b""
        )
        with patch("github_api.subprocess.run", return_value=completed) as run:
            self.assertEqual(GitHubClient("owner/repo").repository()["default_branch"], "main")
        self.assertEqual(run.call_args.args[0][2], "repos/owner/repo")

    def test_github_api_retries_one_tls_handshake_timeout(self) -> None:
        timed_out = subprocess.CompletedProcess(
            [], 1, b"", b'Post "https://api.github.com": net/http: TLS handshake timeout'
        )
        completed = subprocess.CompletedProcess([], 0, b'{"id":1}', b"")
        with (
            patch("github_api.subprocess.run", side_effect=[timed_out, completed]) as run,
            patch("github_api.time.sleep") as sleep,
        ):
            result = GitHubClient("owner/repo").api(
                "issues/7/comments",
                method="POST",
                input_value={"body": "result"},
            )
        self.assertEqual(result, {"id": 1})
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_github_api_does_not_retry_other_failures(self) -> None:
        failed = subprocess.CompletedProcess([], 1, b"", b"HTTP 422: Validation Failed")
        with (
            patch("github_api.subprocess.run", return_value=failed) as run,
            patch("github_api.time.sleep") as sleep,
            self.assertRaisesRegex(GitHubError, "HTTP 422"),
        ):
            GitHubClient("owner/repo").api("issues", method="POST")
        run.assert_called_once()
        sleep.assert_not_called()

    def test_synchronous_merge_is_head_bound_and_squashed(self) -> None:
        client = GitHubClient("owner/repo")
        with patch.object(
            GitHubClient,
            "api",
            return_value={"merged": True, "sha": "b" * 40},
        ) as api:
            self.assertEqual(
                client.merge_pull_request(26, expected_head_sha="a" * 40),
                "b" * 40,
            )
        api.assert_called_once_with(
            "pulls/26/merge",
            method="PUT",
            input_value={"sha": "a" * 40, "merge_method": "squash"},
        )

    def test_synchronous_merge_requires_confirmed_result(self) -> None:
        client = GitHubClient("owner/repo")
        with (
            patch.object(GitHubClient, "api", return_value={"merged": False, "sha": None}),
            self.assertRaisesRegex(GitHubError, "cannot synchronously merge PR #26"),
        ):
            client.merge_pull_request(26, expected_head_sha="a" * 40)

    def test_pre_authorization_python_probe_is_isolated_from_repository_imports(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "8.4.0\n", "")
        with patch("loop.subprocess.run", return_value=completed) as run:
            self.assertEqual(
                _version(["python3", "-I", "-c", "import pytest; print(pytest.__version__)"]),
                "8.4.0",
            )
        self.assertEqual(run.call_args.kwargs["cwd"], ROOT / ".github/milestone-loop")
        self.assertIn("-I", run.call_args.args[0])

    def test_context_overflow_blocks_without_truncation(self) -> None:
        milestone = json.loads(
            (ROOT / "project" / "milestones" / "m1" / "milestone.json").read_text()
        )
        snapshot = {
            "repository": "owner/repo",
            "default_branch": "main",
            "default_sha": "a" * 40,
            "issues": [
                {
                    "number": 1,
                    "title": "large",
                    "body": "not a Work Item",
                    "state": "open",
                    "labels": [],
                    "comments": [{"author": "human", "body": "x" * MAX_CONTEXT_BYTES}],
                }
            ],
            "pull_requests": [],
        }
        with self.assertRaises(ContractError):
            build_context(
                repo_root=ROOT,
                snapshot=snapshot,
                milestone_document=milestone,
            )

    def test_cleanup_refuses_paths_outside_runner_temp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner_temp = Path(temporary) / "runner"
            outside = Path(temporary) / "outside"
            runner_temp.mkdir()
            outside.mkdir()
            with patch.dict(os.environ, {"RUNNER_TEMP": str(runner_temp)}):
                with self.assertRaises(ContractError):
                    cleanup_runtime_root(ROOT, outside)

    def test_recovery_removes_only_discovered_owned_resources(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        with patch(
            "recovery._owned_docker_resources",
            side_effect=[(["container-1"], ["network-1"]), ([], [])],
        ), patch("recovery._run", return_value=completed) as run:
            cleanup_owned_docker()
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(["docker", "rm", "-f", "container-1"], commands)
        self.assertIn(["docker", "network", "rm", "network-1"], commands)

    def test_consumed_lease_is_rechecked_before_real_gate(self) -> None:
        lease = empty_lease("m1")
        lease.update(
            {
                "status": "exhausted",
                "nonce": "approved-once",
                "expires_at": "2999-01-01T00:00:00Z",
                "remaining": 0,
                "entrypoint": "milestone",
                "default_sha": "a" * 40,
                "run_id": "12345",
                "run_attempt": "1",
            }
        )
        snapshot = {
            "milestone": "m1",
            "issues": [
                {
                    "number": 7,
                    "labels": [CONTROL_LABEL],
                    "body": render_control(lease, 0),
                }
            ],
        }
        with patch.dict(
            os.environ,
            {"GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "1"},
            clear=True,
        ):
            _validate_consumed_lease(
                snapshot,
                _lease_fingerprint(lease),
                milestone="m1",
                entrypoint="milestone",
                expected_sha="a" * 40,
            )
        changed = dict(lease)
        changed["nonce"] = "changed"
        snapshot["issues"][0]["body"] = render_control(changed, 0)
        with patch.dict(
            os.environ,
            {"GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "1"},
            clear=True,
        ), self.assertRaises(LoopBlocked):
            _validate_consumed_lease(
                snapshot,
                _lease_fingerprint(lease),
                milestone="m1",
                entrypoint="milestone",
                expected_sha="a" * 40,
            )

    def test_consumed_lease_cannot_cross_run_attempts(self) -> None:
        lease = empty_lease("m2")
        lease.update(
            status="exhausted",
            nonce="m2-gh-12345-attempt-1-discovery-" + "a" * 12,
            expires_at="2999-01-01T00:00:00Z",
            remaining=0,
            entrypoint="discovery",
            default_sha="a" * 40,
            run_id="12345",
            run_attempt="1",
        )
        snapshot = {
            "milestone": "m2",
            "issues": [
                {
                    "number": 7,
                    "labels": [CONTROL_LABEL],
                    "body": render_control(lease, 0),
                }
            ],
        }
        with patch.dict(
            os.environ,
            {"GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "2"},
            clear=True,
        ), self.assertRaises(LoopBlocked):
            _validate_consumed_lease(
                snapshot,
                _lease_fingerprint(lease),
                milestone="m2",
                entrypoint="discovery",
                expected_sha="a" * 40,
            )

    def test_real_result_artifact_cannot_cross_run_attempts(self) -> None:
        with patch.dict(
            os.environ,
            {"GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "1"},
            clear=True,
        ):
            result = bind_real_result(
                {"status": "PASS", "summary": "ok"},
                milestone="m1",
                entrypoint="milestone",
                expected_sha="a" * 40,
                expected_lease_sha256="b" * 64,
            )
        with self.assertRaises(ContractError):
            validate_real_result_binding(
                result,
                milestone="m1",
                entrypoint="milestone",
                expected_sha="a" * 40,
                expected_lease_sha256="b" * 64,
                run_id="12345",
                run_attempt="2",
            )

    def test_cleanup_or_evidence_failure_seals_milestone_as_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_path = root / "raw.json"
            sealed_path = root / "sealed.json"
            with patch.dict(
                os.environ,
                {"GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "1"},
                clear=True,
            ):
                raw = bind_real_result(
                    {"status": "PASS", "summary": "Gate passed"},
                    milestone="m1",
                    entrypoint="milestone",
                    expected_sha="a" * 40,
                    expected_lease_sha256="b" * 64,
                )
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            result = seal_milestone_result(
                raw_result_path=raw_path,
                output_path=sealed_path,
                milestone="m1",
                expected_sha="a" * 40,
                expected_lease_sha256="b" * 64,
                run_id="12345",
                run_attempt="1",
                gate_outcome="success",
                pre_cleanup_outcome="success",
                cleanup_outcome="failure",
                evidence_outcome="success",
            )
            loaded = load_milestone_result(
                result_path=sealed_path,
                milestone="m1",
                expected_sha="a" * 40,
                expected_lease_sha256="b" * 64,
                run_id="12345",
                run_attempt="1",
            )
            evidence_failure = seal_milestone_result(
                raw_result_path=raw_path,
                output_path=root / "evidence-failure.json",
                milestone="m1",
                expected_sha="a" * 40,
                expected_lease_sha256="b" * 64,
                run_id="12345",
                run_attempt="1",
                gate_outcome="success",
                pre_cleanup_outcome="success",
                cleanup_outcome="success",
                evidence_outcome="failure",
            )
        self.assertEqual(result, loaded)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("final cleanup outcome was failure", result["summary"])
        self.assertEqual(evidence_failure["status"], "BLOCKED")
        self.assertIn("evidence upload outcome was failure", evidence_failure["summary"])

    def test_pre_cleanup_failure_seals_without_running_gate_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = seal_milestone_result(
                raw_result_path=root / "missing-raw.json",
                output_path=root / "sealed.json",
                milestone="m2",
                expected_sha="a" * 40,
                expected_lease_sha256="b" * 64,
                run_id="12345",
                run_attempt="2",
                gate_outcome="skipped",
                pre_cleanup_outcome="failure",
                cleanup_outcome="success",
                evidence_outcome="skipped",
            )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("pre-Gate cleanup outcome was failure", result["summary"])

    def test_successful_cleanup_preserves_current_gate_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_path = root / "raw.json"
            with patch.dict(
                os.environ,
                {"GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "3"},
                clear=True,
            ):
                raw = bind_real_result(
                    {"status": "FAIL", "summary": "Criterion did not pass"},
                    milestone="m2",
                    entrypoint="milestone",
                    expected_sha="a" * 40,
                    expected_lease_sha256="b" * 64,
                )
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            result = seal_milestone_result(
                raw_result_path=raw_path,
                output_path=root / "sealed.json",
                milestone="m2",
                expected_sha="a" * 40,
                expected_lease_sha256="b" * 64,
                run_id="12345",
                run_attempt="3",
                gate_outcome="success",
                pre_cleanup_outcome="success",
                cleanup_outcome="success",
                evidence_outcome="success",
            )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["summary"], "Criterion did not pass")

    def test_invalid_invocation_lease_blocks_before_cleanup_or_product(self) -> None:
        snapshot = {"milestone": "m1", "default_sha": "a" * 40, "issues": []}
        with (
            patch("milestone_runner.collect_snapshot", return_value=snapshot),
            patch(
                "milestone_runner._validate_consumed_lease",
                side_effect=LoopBlocked("old attempt"),
            ),
            patch("milestone_runner.cleanup_owned_docker") as cleanup,
            patch("milestone_runner.subprocess.run") as run,
            self.assertRaises(LoopBlocked),
        ):
            run_gate(
                client=object(),
                repo_root=ROOT,
                milestone="m1",
                expected_sha="a" * 40,
                expected_lease_sha256="b" * 64,
            )
        cleanup.assert_not_called()
        run.assert_not_called()

    def test_consumed_m2_lease_authorizes_only_the_m2_real_gate(self) -> None:
        with patch.dict(
            os.environ,
            {"VSLAB_M2_REAL_AUTHORIZATION": "untrusted-inherited-value"},
        ):
            m2_environment = _gate_environment("m2")
            m1_environment = _gate_environment("m1")

        self.assertEqual(m2_environment["VSLAB_M2_REAL_AUTHORIZATION"], "1")
        self.assertNotIn("VSLAB_M2_REAL_AUTHORIZATION", m1_environment)

    def test_m2_discovery_run_identity_is_validated_or_fresh(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            first = _m2_discovery_run_id()
            second = _m2_discovery_run_id()
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^m2-discovery-local-[0-9a-f]{32}$")
        with patch.dict(
            os.environ,
            {"GITHUB_RUN_ID": "../unsafe", "GITHUB_RUN_ATTEMPT": "1"},
            clear=True,
        ):
            with self.assertRaises(ContractError):
                _m2_discovery_run_id()

    def _authorization_fixture(self, milestone: str = "m1") -> tuple[dict, InvocationClient, dict]:
        control = {
            "number": 7,
            "title": "control",
            "body": render_control(empty_lease(milestone), 0),
            "state": "open",
            "labels": [CONTROL_LABEL],
            "comments": [],
        }
        state = {
            "repository": "owner/repo",
            "default_branch": "main",
            "default_sha": "a" * 40,
            "milestone": milestone,
            "milestone_number": int(milestone[1:]),
            "issues": [control],
            "pull_requests": [],
        }
        run = {
            "id": 12345,
            "run_attempt": 1,
            "event": "workflow_dispatch",
            "status": "in_progress",
            "head_sha": "a" * 40,
            "head_branch": "main",
            "path": ".github/workflows/milestone-loop.yml@main",
        }
        environment = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_RUN_ID": "12345",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_JOB": "milestone",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_REF": "refs/heads/main",
        }
        return state, InvocationClient(control, run), environment

    def test_approved_invocation_generates_and_consumes_one_bound_lease(self) -> None:
        state, client, environment = self._authorization_fixture()
        readiness = real_readiness_fingerprint(state)
        checkout = subprocess.CompletedProcess([], 0, "a" * 40 + "\n", "")
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("milestone_runner.collect_snapshot", return_value=state),
            patch("milestone_runner.subprocess.run", return_value=checkout),
            patch("milestone_runner.load_trusted_documents", return_value=({}, {})),
        ):
            result = authorize_real_invocation(
                client,
                ROOT,
                milestone="m1",
                entrypoint="milestone",
                expected_sha="a" * 40,
                expected_readiness_sha256=readiness,
                run_id="12345",
                run_attempt="1",
            )
        self.assertEqual(len(client.updates), 1)
        consumed = parse_control(client.control, "m1").lease
        self.assertEqual(consumed["version"], 2)
        self.assertEqual(consumed["status"], "exhausted")
        self.assertEqual(consumed["remaining"], 0)
        self.assertEqual(consumed["entrypoint"], "milestone")
        self.assertEqual(consumed["default_sha"], "a" * 40)
        self.assertEqual(consumed["run_id"], "12345")
        self.assertEqual(consumed["run_attempt"], "1")
        self.assertEqual(result["lease_sha256"], _lease_fingerprint(consumed))

    def test_unconfirmed_consumed_lease_receipt_reaches_blocked_recorders(self) -> None:
        state, client, environment = self._authorization_fixture()
        client.confirmation_error = OSError("confirmation unavailable")
        checkout = subprocess.CompletedProcess([], 0, "a" * 40 + "\n", "")
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("milestone_runner.collect_snapshot", return_value=state),
            patch("milestone_runner.subprocess.run", return_value=checkout),
            patch("milestone_runner.load_trusted_documents", return_value=({}, {})),
            self.assertRaises(LeaseConfirmationBlocked) as raised,
        ):
            authorize_real_invocation(
                client,
                ROOT,
                milestone="m1",
                entrypoint="milestone",
                expected_sha="a" * 40,
                expected_readiness_sha256=real_readiness_fingerprint(state),
                run_id="12345",
                run_attempt="1",
            )
        consumed = parse_control(client.control, "m1").lease
        receipt = raised.exception.receipt
        self.assertFalse(receipt["authorized"])
        self.assertEqual(receipt["milestone"], "m1")
        self.assertEqual(receipt["entrypoint"], "milestone")
        self.assertEqual(receipt["lease_nonce"], consumed["nonce"])
        self.assertEqual(receipt["lease_sha256"], _lease_fingerprint(consumed))
        self.assertEqual(receipt["default_sha"], "a" * 40)
        self.assertEqual(receipt["run_id"], "12345")
        self.assertEqual(receipt["run_attempt"], "1")

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "github-output"
            with (
                patch.dict(
                    os.environ, {"GITHUB_OUTPUT": str(output)}, clear=True
                ),
                patch("loop.validate_environment"),
                patch("loop.GitHubClient.from_environment", return_value=object()),
                patch(
                    "loop.authorize_real_invocation",
                    side_effect=raised.exception,
                ),
            ):
                exit_code = loop_main(
                    [
                        "authorize-real-invocation",
                        "--milestone",
                        "m1",
                        "--entrypoint",
                        "milestone",
                        "--expected-sha",
                        "a" * 40,
                        "--expected-readiness-sha256",
                        "b" * 64,
                        "--run-id",
                        "12345",
                        "--run-attempt",
                        "1",
                    ]
                )
            outputs = dict(
                line.split("=", 1)
                for line in output.read_text(encoding="utf-8").splitlines()
            )
        self.assertEqual(exit_code, 78)
        self.assertEqual(outputs["authorized"], "false")
        self.assertEqual(outputs["lease_sha256"], receipt["lease_sha256"])

        workflow = (ROOT / ".github/workflows/milestone-loop.yml").read_text()
        milestone_job = workflow.split("\n  milestone:", 1)[1].split(
            "\n  m2-discovery:", 1
        )[0]
        discovery_job = workflow.split("\n  m2-discovery:", 1)[1].split(
            "\n  record-m2-discovery:", 1
        )[0]
        receipt_condition = (
            "if: always() && steps.authorize.outputs.lease_sha256 != ''"
        )
        self.assertIn("steps.authorize.outcome == 'success'", milestone_job)
        self.assertGreaterEqual(milestone_job.count(receipt_condition), 3)
        self.assertIn(
            "if: success() && steps.authorize.outcome == 'success'",
            discovery_job,
        )
        self.assertGreaterEqual(discovery_job.count(receipt_condition), 1)

    def test_patch_response_loss_preserves_unconfirmed_receipt(self) -> None:
        state, client, environment = self._authorization_fixture()
        client.after_update = Mock(side_effect=OSError("PATCH response lost"))
        checkout = subprocess.CompletedProcess([], 0, "a" * 40 + "\n", "")
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("milestone_runner.collect_snapshot", return_value=state),
            patch("milestone_runner.subprocess.run", return_value=checkout),
            patch("milestone_runner.load_trusted_documents", return_value=({}, {})),
            self.assertRaises(LeaseConfirmationBlocked) as raised,
        ):
            authorize_real_invocation(
                client,
                ROOT,
                milestone="m1",
                entrypoint="milestone",
                expected_sha="a" * 40,
                expected_readiness_sha256=real_readiness_fingerprint(state),
                run_id="12345",
                run_attempt="1",
            )
        consumed = parse_control(client.control, "m1").lease
        self.assertEqual(len(client.updates), 1)
        self.assertEqual(consumed["status"], "exhausted")
        self.assertEqual(consumed["remaining"], 0)
        self.assertFalse(raised.exception.receipt["authorized"])
        self.assertEqual(
            raised.exception.receipt["lease_sha256"], _lease_fingerprint(consumed)
        )

    def test_same_approved_invocation_cannot_generate_a_second_lease(self) -> None:
        state, client, environment = self._authorization_fixture()
        readiness = real_readiness_fingerprint(state)
        checkout = subprocess.CompletedProcess([], 0, "a" * 40 + "\n", "")
        arguments = dict(
            milestone="m1",
            entrypoint="milestone",
            expected_sha="a" * 40,
            expected_readiness_sha256=readiness,
            run_id="12345",
            run_attempt="1",
        )
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("milestone_runner.collect_snapshot", return_value=state),
            patch("milestone_runner.subprocess.run", return_value=checkout),
            patch("milestone_runner.load_trusted_documents", return_value=({}, {})),
        ):
            authorize_real_invocation(client, ROOT, **arguments)
            with self.assertRaises(LoopBlocked):
                authorize_real_invocation(client, ROOT, **arguments)
        self.assertEqual(len(client.updates), 1)

    def test_stale_or_unapproved_run_identity_never_changes_lease(self) -> None:
        state, client, environment = self._authorization_fixture()
        environment["GITHUB_RUN_ATTEMPT"] = "2"
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("milestone_runner.collect_snapshot", return_value=state),
            self.assertRaises(LoopBlocked),
        ):
            authorize_real_invocation(
                client,
                ROOT,
                milestone="m1",
                entrypoint="milestone",
                expected_sha="a" * 40,
                expected_readiness_sha256=real_readiness_fingerprint(state),
                run_id="12345",
                run_attempt="1",
            )
        self.assertEqual(client.updates, [])

    def test_missing_required_environment_reviewer_never_changes_lease(self) -> None:
        state, client, environment = self._authorization_fixture()
        client.environment["protection_rules"] = []
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("milestone_runner.collect_snapshot", return_value=state),
            self.assertRaises(LoopBlocked),
        ):
            authorize_real_invocation(
                client,
                ROOT,
                milestone="m1",
                entrypoint="milestone",
                expected_sha="a" * 40,
                expected_readiness_sha256=real_readiness_fingerprint(state),
                run_id="12345",
                run_attempt="1",
            )
        self.assertEqual(client.updates, [])

    def test_each_invalid_live_run_field_prevents_lease_write(self) -> None:
        invalid = {
            "id": 99999,
            "run_attempt": 2,
            "event": "push",
            "status": "completed",
            "head_sha": "b" * 40,
            "head_branch": "other",
            "path": ".github/workflows/other.yml",
        }
        for field, value in invalid.items():
            with self.subTest(field=field):
                state, client, environment = self._authorization_fixture()
                client.run[field] = value
                with (
                    patch.dict(os.environ, environment, clear=True),
                    patch("milestone_runner.collect_snapshot", return_value=state),
                    self.assertRaises(LoopBlocked),
                ):
                    authorize_real_invocation(
                        client,
                        ROOT,
                        milestone="m1",
                        entrypoint="milestone",
                        expected_sha="a" * 40,
                        expected_readiness_sha256=real_readiness_fingerprint(state),
                        run_id="12345",
                        run_attempt="1",
                    )
                self.assertEqual(client.updates, [])

    def test_canonical_legacy_empty_or_exhausted_lease_migrates_once(self) -> None:
        leases = (
            {
                "version": 1,
                "milestone": "m1",
                "status": "empty",
                "nonce": "",
                "expires_at": "",
                "remaining": 0,
            },
            {
                "version": 1,
                "milestone": "m1",
                "status": "exhausted",
                "nonce": "previous-invocation",
                "expires_at": "2026-07-20T00:00:00Z",
                "remaining": 0,
            },
        )
        for legacy in leases:
            with self.subTest(status=legacy["status"]):
                state, client, environment = self._authorization_fixture()
                client.control["body"] = render_control(legacy, 0)
                checkout = subprocess.CompletedProcess([], 0, "a" * 40 + "\n", "")
                with (
                    patch.dict(os.environ, environment, clear=True),
                    patch("milestone_runner.collect_snapshot", return_value=state),
                    patch("milestone_runner.subprocess.run", return_value=checkout),
                    patch("milestone_runner.load_trusted_documents", return_value=({}, {})),
                ):
                    authorize_real_invocation(
                        client,
                        ROOT,
                        milestone="m1",
                        entrypoint="milestone",
                        expected_sha="a" * 40,
                        expected_readiness_sha256=real_readiness_fingerprint(state),
                        run_id="12345",
                        run_attempt="1",
                    )
                self.assertEqual(len(client.updates), 1)
                self.assertEqual(parse_control(client.control, "m1").lease["version"], 2)

    def test_lease_change_before_or_after_write_blocks_product_handoff(self) -> None:
        state, client, environment = self._authorization_fixture()
        changed = copy.deepcopy(state)
        changed["issues"][0]["body"] = render_control(empty_lease("m1"), 1)
        checkout = subprocess.CompletedProcess([], 0, "a" * 40 + "\n", "")
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("milestone_runner.collect_snapshot", side_effect=[state, changed]),
            patch("milestone_runner.subprocess.run", return_value=checkout),
            patch("milestone_runner.load_trusted_documents", return_value=({}, {})),
            self.assertRaises(LoopBlocked),
        ):
            authorize_real_invocation(
                client,
                ROOT,
                milestone="m1",
                entrypoint="milestone",
                expected_sha="a" * 40,
                expected_readiness_sha256=real_readiness_fingerprint(state),
                run_id="12345",
                run_attempt="1",
            )
        self.assertEqual(client.updates, [])

        state, client, environment = self._authorization_fixture()
        client.after_update = lambda: client.control.update(
            body=render_control(parse_control(client.control, "m1").lease, 1)
        )
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("milestone_runner.collect_snapshot", return_value=state),
            patch("milestone_runner.subprocess.run", return_value=checkout),
            patch("milestone_runner.load_trusted_documents", return_value=({}, {})),
            self.assertRaises(LoopBlocked),
        ):
            authorize_real_invocation(
                client,
                ROOT,
                milestone="m1",
                entrypoint="milestone",
                expected_sha="a" * 40,
                expected_readiness_sha256=real_readiness_fingerprint(state),
                run_id="12345",
                run_attempt="1",
            )
        self.assertEqual(len(client.updates), 1)

    def test_active_or_revoked_legacy_lease_is_never_consumed_or_replaced(self) -> None:
        for status, remaining in (("active", 1), ("revoked", 0)):
            with self.subTest(status=status):
                state, client, environment = self._authorization_fixture()
                legacy = {
                    "version": 1,
                    "milestone": "m1",
                    "status": status,
                    "nonce": "legacy-human-lease",
                    "expires_at": "2999-01-01T00:00:00Z",
                    "remaining": remaining,
                }
                client.control["body"] = render_control(legacy, 0)
                checkout = subprocess.CompletedProcess([], 0, "a" * 40 + "\n", "")
                with (
                    patch.dict(os.environ, environment, clear=True),
                    patch("milestone_runner.collect_snapshot", return_value=state),
                    patch("milestone_runner.subprocess.run", return_value=checkout),
                    patch("milestone_runner.load_trusted_documents", return_value=({}, {})),
                    self.assertRaises(LoopBlocked),
                ):
                    authorize_real_invocation(
                        client,
                        ROOT,
                        milestone="m1",
                        entrypoint="milestone",
                        expected_sha="a" * 40,
                        expected_readiness_sha256=real_readiness_fingerprint(state),
                        run_id="12345",
                        run_attempt="1",
                    )
                self.assertEqual(client.updates, [])

    def test_authorization_rechecks_m2_entrypoint_before_lease_write(self) -> None:
        state, client, environment = self._authorization_fixture("m2")
        environment["GITHUB_JOB"] = "m2-discovery"
        checkout = subprocess.CompletedProcess([], 0, "a" * 40 + "\n", "")
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("milestone_runner.collect_snapshot", return_value=state),
            patch("milestone_runner.subprocess.run", return_value=checkout),
            patch("milestone_runner.load_trusted_documents", return_value=({}, {})),
            patch("milestone_runner.m2_candidate_blockers", return_value=("unresolved",)),
            patch("milestone_runner.m2_discovery_eligible", return_value=False),
            self.assertRaises(LoopBlocked),
        ):
            authorize_real_invocation(
                client,
                ROOT,
                milestone="m2",
                entrypoint="discovery",
                expected_sha="a" * 40,
                expected_readiness_sha256=real_readiness_fingerprint(state),
                run_id="12345",
                run_attempt="1",
            )
        self.assertEqual(client.updates, [])

    def _run_discovery_fixture(
        self,
        *,
        include_admission_report: bool = False,
        status: str = "PASS",
        malformed_failure: bool = False,
        report_overrides: dict[str, object] | None = None,
    ) -> tuple[dict, list[tuple[list[str], dict]], int]:
        expected_sha = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary) / "repo"
            script = repo_root / "project" / "scripts" / "m2_candidate_discovery.py"
            script.parent.mkdir(parents=True)
            script.write_text("# fixed test producer\n", encoding="utf-8")
            (repo_root / "project" / "src").mkdir()
            runner_temp = Path(temporary) / "runner"
            runner_temp.mkdir()
            calls: list[tuple[list[str], dict]] = []

            def run(argv, **kwargs):
                command = list(argv)
                calls.append((command, kwargs))
                if command[:3] == ["git", "rev-parse", "HEAD"]:
                    return subprocess.CompletedProcess(command, 0, expected_sha + "\n", "")
                artifacts = Path(command[command.index("--artifacts-dir") + 1])
                result_path = Path(command[command.index("--result-path") + 1])
                run_id = command[command.index("--run-id") + 1]
                artifacts.mkdir()
                report = {
                    "schema_version": "m2-candidate-discovery-v1",
                    "artifact_type": "m2_candidate_discovery",
                    "purpose": "candidate-selection-only",
                    "admission_evidence": False,
                    "current_invocation": True,
                    "tested_sha": expected_sha,
                    "invocation_run_id": run_id,
                    "campaign_id": run_id,
                    "status": status,
                    "report_digest": "c" * 64,
                    "errors": [] if status == "PASS" else ["Docker unavailable"],
                    "campaigns": {},
                }
                report.update(report_overrides or {})
                (artifacts / "m2_candidate_discovery.json").write_text(
                    json.dumps(report), encoding="utf-8"
                )
                if include_admission_report:
                    (artifacts / "m2_performance_report.json").write_text(
                        "{}", encoding="utf-8"
                    )
                result_path.write_text(
                    json.dumps(
                        {
                            "status": status,
                            "summary": "selection screen complete",
                            "failure": (
                                {"capture_stage": "formation"}
                                if malformed_failure
                                else None
                                if status == "PASS"
                                else {
                                    "capture_stage": "preflight",
                                    "class": "environment",
                                    "evidence_path": "m2_candidate_discovery.json",
                                }
                            ),
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, "producer output\n", None)

            snapshot = {
                "default_sha": expected_sha,
                "milestone": "m2",
                "issues": [],
            }
            with (
                patch.dict(
                    os.environ,
                    {
                        "RUNNER_TEMP": str(runner_temp),
                        "GITHUB_RUN_ID": "12345",
                        "GITHUB_RUN_ATTEMPT": "2",
                        "GH_TOKEN": "must-not-leak",
                        "GITHUB_TOKEN": "must-not-leak",
                        "CODEX_API_KEY": "must-not-leak",
                    },
                ),
                patch("milestone_runner.collect_snapshot", return_value=snapshot),
                patch("milestone_runner._validate_consumed_lease") as validate_lease,
                patch("milestone_runner.subprocess.run", side_effect=run),
                patch("milestone_runner.load_trusted_documents", return_value=({}, {})),
                patch("milestone_runner.m2_discovery_eligible", return_value=True),
                patch("milestone_runner.cleanup_owned_docker") as cleanup,
            ):
                result = run_m2_discovery(
                    client=object(),
                    repo_root=repo_root,
                    expected_sha=expected_sha,
                    expected_lease_sha256="b" * 64,
                )
            validate_lease.assert_called_once_with(
                snapshot,
                "b" * 64,
                milestone="m2",
                entrypoint="discovery",
                expected_sha=expected_sha,
            )
            return result, calls, cleanup.call_count

    def test_m2_discovery_rechecks_authorization_and_uses_fixed_sanitized_command(self) -> None:
        result, calls, cleanup_count = self._run_discovery_fixture()
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["report"].endswith("/m2_candidate_discovery.json"))
        self.assertEqual(cleanup_count, 2)
        self.assertEqual(calls[0][0], ["git", "rev-parse", "HEAD"])
        producer, kwargs = calls[1]
        self.assertEqual(producer[:2], ["python3", "scripts/m2_candidate_discovery.py"])
        self.assertEqual(producer[producer.index("--tested-sha") + 1], "a" * 40)
        self.assertEqual(
            producer[producer.index("--run-id") + 1],
            "m2-discovery-gh-12345-attempt-2",
        )
        environment = kwargs["env"]
        self.assertEqual(environment["VSLAB_M2_REAL_AUTHORIZATION"], "1")
        self.assertTrue(environment["PYTHONPATH"].endswith("/project/src"))
        for key in ("GH_TOKEN", "GITHUB_TOKEN", "CODEX_API_KEY"):
            self.assertNotIn(key, environment)

    def test_m2_discovery_rejects_any_admission_report(self) -> None:
        result, _calls, cleanup_count = self._run_discovery_fixture(
            include_admission_report=True
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("forbidden admission report", result["summary"])
        self.assertEqual(cleanup_count, 2)

    def test_m2_discovery_rejects_admission_fields_and_weak_envelope(self) -> None:
        invalid_reports = (
            {"criterion_results": []},
            {"selected_candidate": {}},
            {"current_invocation": False},
            {"report_digest": "C" * 64},
            {"report_digest": "c" * 63},
        )
        for overrides in invalid_reports:
            with self.subTest(overrides=overrides):
                result, _calls, cleanup_count = self._run_discovery_fixture(
                    report_overrides=overrides
                )
                self.assertEqual(result["status"], "FAIL")
                self.assertIn("selection-only artifact", result["summary"])
                self.assertEqual(cleanup_count, 2)

    def test_m2_discovery_preserves_bounded_blocked_result_for_upload(self) -> None:
        result, _calls, cleanup_count = self._run_discovery_fixture(status="BLOCKED")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(result["artifacts"].endswith("/m2-discovery-evidence"))
        self.assertEqual(cleanup_count, 2)

        malformed, _calls, _cleanup_count = self._run_discovery_fixture(
            status="BLOCKED",
            malformed_failure=True,
        )
        self.assertEqual(malformed["status"], "FAIL")
        self.assertIn("failure metadata is invalid", malformed["summary"])

    def test_m2_discovery_blocks_if_candidate_state_is_no_longer_canonical(self) -> None:
        snapshot = {
            "default_sha": "a" * 40,
            "milestone": "m2",
            "issues": [],
        }
        checkout = subprocess.CompletedProcess([], 0, "a" * 40 + "\n", "")
        with (
            patch("milestone_runner.collect_snapshot", return_value=snapshot),
            patch("milestone_runner._validate_consumed_lease"),
            patch("milestone_runner.subprocess.run", return_value=checkout),
            patch("milestone_runner.load_trusted_documents", return_value=({}, {})),
            patch("milestone_runner.m2_discovery_eligible", return_value=False),
            patch("milestone_runner.cleanup_owned_docker") as cleanup,
        ):
            with self.assertRaises(LoopBlocked):
                run_m2_discovery(
                    client=object(),
                    repo_root=ROOT,
                    expected_sha="a" * 40,
                    expected_lease_sha256="b" * 64,
                )
        cleanup.assert_not_called()

    def _seal_discovery_fixture(
        self,
        temporary: str,
        *,
        status: str,
        error: str = "",
        cleanup_outcome: str = "success",
        tamper_report_digest: bool = False,
        malformed_campaign: bool = False,
        run_id: str = "123",
        run_attempt: str = "2",
        failure_scope: str = "formation",
        failure_class: str = "product",
        invalid_samples: list[dict[str, str]] | None = None,
    ) -> tuple[dict, Path, Path]:
        root = Path(temporary)
        evidence = root / "evidence"
        evidence.mkdir()
        raw_result = root / "raw.json"
        sealed = root / "sealed.json"
        sha = "a" * 40
        lease_sha256 = "b" * 64
        invocation = f"m2-discovery-gh-{run_id}-attempt-{run_attempt}"
        source = evidence / "current-source.json"
        source.write_text('{"current":true}\n', encoding="utf-8")
        source_ref = {
            "category": "preflight",
            "path": source.name,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }

        def campaign(
            kind: str,
            campaign_status: str,
            started: list[str],
            cells: list[dict],
            samples: list[dict[str, str]] | None = None,
        ) -> dict:
            trials: list[dict] = []
            pairs: list[dict] = []
            if campaign_status == "PASS":
                for cell in cells:
                    pair_id = f"{cell['cell_id']}-pair-1"
                    baseline_id = f"{invocation}-{pair_id}-baseline"
                    candidate_id = f"{invocation}-{pair_id}-candidate"
                    trials.extend(
                        [
                            {"trial_id": baseline_id, "pair_id": pair_id, "cell_id": cell["cell_id"]},
                            {"trial_id": candidate_id, "pair_id": pair_id, "cell_id": cell["cell_id"]},
                        ]
                    )
                    pairs.append(
                        {
                            "pair_id": pair_id,
                            "cell_id": cell["cell_id"],
                            "baseline_trial_id": baseline_id,
                            "candidate_trial_id": candidate_id,
                        }
                    )
                started = [trial["trial_id"] for trial in trials]
            return {
                "campaign_id": invocation,
                "invocation_run_id": invocation,
                "experiment_kind": kind,
                "status": campaign_status,
                "real_valkey": bool(started),
                "execution_mode": "valkey-real" if started else "not-run",
                "baseline": {"kind": "baseline", "value": "current"},
                "candidates": (
                    [dict(cell["candidate"]) for cell in cells]
                    if cells
                    else [{"kind": "candidate", "value": "test"}]
                ),
                "current_defaults": {"test": "current"},
                "protocol": {
                    "fixture_admission_allowed": False,
                    "historical_admission_allowed": False,
                    "downscale_allowed": False,
                    "takeover_allowed": False,
                },
                "started_trial_ids": started,
                "trials": trials,
                "pairs": pairs,
                "cells": cells,
                "invalid_samples": [dict(sample) for sample in (samples or [])],
                "source_refs": [dict(source_ref)] if started else [],
                "errors": [error] if error and campaign_status == "FAIL" else [],
            }

        formation_losing_cell = {
            "cell_id": "formation-discovery-test",
            "campaign_step": "discovery",
            "scale": 50,
            "failure_rate": "none",
            "required_pairs": 1,
            "candidate": {"kind": "candidate", "value": "loser"},
            "status": "FAIL",
        }
        failover_losing_cell = {
            **formation_losing_cell,
            "cell_id": "failover-discovery-test",
            "failure_rate": "one",
        }
        if status == "PASS":
            campaigns = {
                "formation": campaign(
                    "formation",
                    "PASS",
                    [f"{invocation}-formation-trial"],
                    [formation_losing_cell],
                    invalid_samples,
                ),
                "failover": campaign(
                    "failover",
                    "PASS",
                    [f"{invocation}-failover-trial"],
                    [failover_losing_cell],
                ),
            }
        elif failure_scope == "preflight":
            campaigns = {}
        elif failure_scope == "failover":
            campaigns = {
                "formation": campaign(
                    "formation",
                    "PASS",
                    [f"{invocation}-formation-trial"],
                    [formation_losing_cell],
                ),
                "failover": campaign(
                    "failover",
                    "FAIL",
                    [f"{invocation}-failover-trial"],
                    [],
                    invalid_samples,
                ),
            }
        else:
            campaigns = {
                "formation": campaign(
                    "formation",
                    "FAIL",
                    [f"{invocation}-formation-trial"],
                    [],
                    invalid_samples,
                ),
                "failover": campaign("failover", "FAIL", [], []),
            }
        candidate_results = {
            kind: [
                {"candidate": dict(cell["candidate"]), "status": cell["status"]}
                for cell in campaigns.get(kind, {}).get("cells", [])
            ]
            for kind in ("formation", "failover")
        }
        report = {
            "schema_version": "m2-candidate-discovery-v1",
            "artifact_type": "m2_candidate_discovery",
            "purpose": "candidate-selection-only",
            "admission_evidence": False,
            "campaign_id": invocation,
            "invocation_run_id": invocation,
            "current_invocation": True,
            "tested_sha": sha,
            "created_at": "2026-07-21T00:00:00Z",
            "producer": {"name": "valkey-scale-lab", "version": "test"},
            "status": status,
            "real_valkey": bool(campaigns),
            "execution_mode": "valkey-real" if campaigns else "not-run",
            "campaigns": campaigns,
            "candidate_results": candidate_results,
            "survivors": {"formation": [], "failover": []},
            "errors": [error] if error else [],
            "report_digest": "",
        }
        if malformed_campaign:
            report["campaigns"]["formation"].pop("source_refs", None)
        report["report_digest"] = _canonical_digest(report, omit="report_digest")
        if tamper_report_digest:
            report["report_digest"] = "f" * 64
        (evidence / "m2_candidate_discovery.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
        failure = (
            None
            if status == "PASS"
            else {
                "failure_phase": failure_scope,
                "class": failure_class,
                "scope": (
                    failure_scope
                    if failure_scope in {"formation", "failover"}
                    else ""
                ),
                "retryable": (
                    failure_class in {"measurement", "product"}
                    and failure_scope in {"formation", "failover"}
                ),
                "evidence_path": "m2_candidate_discovery.json",
            }
        )
        raw_result.write_text(
            json.dumps(
                {
                    "status": status,
                    "summary": error or "selection complete",
                    "failure": failure,
                    "milestone": "m2",
                    "entrypoint": "discovery",
                    "tested_sha": sha,
                    "lease_sha256": lease_sha256,
                    "run_id": run_id,
                    "run_attempt": run_attempt,
                }
            ),
            encoding="utf-8",
        )
        result = seal_m2_discovery_result(
            raw_result_path=raw_result,
            evidence_root=evidence,
            output_path=sealed,
            expected_sha=sha,
            expected_lease_sha256=lease_sha256,
            run_id=run_id,
            run_attempt=run_attempt,
            run_outcome="success",
            cleanup_outcome=cleanup_outcome,
        )
        return result, sealed, evidence

    def test_completed_candidate_losses_remain_selection_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result, sealed, evidence = self._seal_discovery_fixture(
                temporary, status="PASS"
            )
            loaded = load_m2_discovery_result(
                result_path=sealed,
                evidence_root=evidence,
                expected_sha="a" * 40,
                expected_lease_sha256="b" * 64,
                run_id="123",
                run_attempt="2",
            )
        self.assertEqual(result["disposition"], "CANDIDATE_SELECTION_ONLY")
        self.assertEqual(loaded["status"], "PASS")
        self.assertEqual(loaded["failure_scope"], "")

    def test_structured_product_and_measurement_failures_are_repairable(self) -> None:
        reason = "formation collector called an invalid API"
        with tempfile.TemporaryDirectory() as temporary:
            repairable, _sealed, _evidence = self._seal_discovery_fixture(
                temporary,
                status="FAIL",
                error=f"DISCOVERY_FAILED: TypeError: {reason}",
                invalid_samples=[
                    {
                        "trial_id": "m2-discovery-gh-123-attempt-2-formation-trial",
                        "reason": reason,
                    }
                ],
            )
        self.assertEqual(repairable["disposition"], "REPAIRABLE_IMPLEMENTATION")
        self.assertEqual(repairable["failure_class"], "product")
        self.assertEqual(repairable["failure_scope"], "formation")
        self.assertEqual(repairable["failure_code"], "product")

        failover_reason = "failover collector called an invalid API"
        with tempfile.TemporaryDirectory() as temporary:
            failover, _sealed, _evidence = self._seal_discovery_fixture(
                temporary,
                status="FAIL",
                error=f"DISCOVERY_FAILED: TypeError: {failover_reason}",
                failure_scope="failover",
                invalid_samples=[
                    {
                        "trial_id": "m2-discovery-gh-123-attempt-2-failover-trial",
                        "reason": failover_reason,
                    }
                ],
            )
        self.assertEqual(failover["disposition"], "REPAIRABLE_IMPLEMENTATION")
        self.assertEqual(failover["failure_scope"], "failover")

        with tempfile.TemporaryDirectory() as temporary:
            safety, _sealed, _evidence = self._seal_discovery_fixture(
                temporary,
                status="FAIL",
                error="DISCOVERY_FAILED: CaptureError: cluster link safety metric is nonzero",
                failure_class="measurement",
                invalid_samples=[
                    {
                        "trial_id": "m2-discovery-gh-123-attempt-2-formation-trial",
                        "reason": "cluster link safety metric is nonzero",
                    }
                ],
            )
        self.assertEqual(safety["status"], "FAIL")
        self.assertEqual(safety["disposition"], "REPAIRABLE_IMPLEMENTATION")
        self.assertEqual(safety["failure_class"], "measurement")

        with tempfile.TemporaryDirectory() as temporary:
            environment, _sealed, _evidence = self._seal_discovery_fixture(
                temporary,
                status="BLOCKED",
                error="ENVIRONMENT_AFTER_START: Docker unavailable",
                failure_class="environment",
            )
        self.assertEqual(environment["disposition"], "HUMAN_REQUIRED")
        self.assertEqual(environment["failure_class"], "environment")
        self.assertFalse(environment["retryable"])

        with tempfile.TemporaryDirectory() as temporary:
            preflight, sealed, evidence = self._seal_discovery_fixture(
                temporary,
                status="BLOCKED",
                error="ENVIRONMENT_BLOCKED: resource preflight rejected the host",
                failure_scope="preflight",
                failure_class="environment",
            )
            loaded = load_m2_discovery_result(
                result_path=sealed,
                evidence_root=evidence,
                expected_sha="a" * 40,
                expected_lease_sha256="b" * 64,
                run_id="123",
                run_attempt="2",
            )
        self.assertEqual(preflight["failure_phase"], "preflight")
        self.assertEqual(preflight["failure_class"], "environment")
        self.assertEqual(preflight["evidence_path"], "m2_candidate_discovery.json")
        self.assertEqual(loaded, preflight)

        with tempfile.TemporaryDirectory() as temporary:
            malformed, _sealed, _evidence = self._seal_discovery_fixture(
                temporary,
                status="FAIL",
                error="DISCOVERY_FAILED: unknown failure metadata",
                failure_class="unknown",
            )
        self.assertEqual(malformed["status"], "BLOCKED")
        self.assertEqual(malformed["disposition"], "HUMAN_REQUIRED")

    def test_historical_invalid_sample_does_not_replace_current_failure(self) -> None:
        error = "DISCOVERY_FAILED: TypeError: current implementation failure"
        cases = (
            (
                [
                    {
                        "trial_id": "m2-discovery-gh-123-attempt-2-formation-trial",
                        "reason": "prior candidate safety rejection",
                    }
                ],
                "FAIL",
            ),
            (
                [
                    {
                        "trial_id": "m2-discovery-gh-122-attempt-1-formation-trial",
                        "reason": "current implementation failure",
                    }
                ],
                "BLOCKED",
            ),
            (
                [
                    {
                        "trial_id": "m2-discovery-gh-123-attempt-2-formation-trial",
                        "reason": "current implementation failure",
                    },
                    {
                        "trial_id": "m2-discovery-gh-123-attempt-2-formation-trial",
                        "reason": "current implementation failure",
                    },
                ],
                "BLOCKED",
            ),
        )
        for samples, expected_status in cases:
            with self.subTest(samples=samples), tempfile.TemporaryDirectory() as temporary:
                result, _sealed, _evidence = self._seal_discovery_fixture(
                    temporary,
                    status="FAIL",
                    error=error,
                    invalid_samples=samples,
                )
            self.assertEqual(result["status"], expected_status)
            self.assertEqual(
                result["disposition"],
                (
                    "REPAIRABLE_IMPLEMENTATION"
                    if expected_status == "FAIL"
                    else "HUMAN_REQUIRED"
                ),
            )

    def test_pass_cannot_hide_invalid_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result, _sealed, _evidence = self._seal_discovery_fixture(
                temporary,
                status="PASS",
                invalid_samples=[
                    {
                        "trial_id": "m2-discovery-gh-123-attempt-2-formation-trial",
                        "reason": "hidden failure",
                    }
                ],
            )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["disposition"], "HUMAN_REQUIRED")

    def test_repairable_fingerprint_is_stable_across_real_attempt_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as first_root:
            first, _sealed, _evidence = self._seal_discovery_fixture(
                first_root,
                status="FAIL",
                error="DISCOVERY_FAILED: TypeError: port 6379 in m2-discovery-gh-123-attempt-2",
                run_id="123",
                run_attempt="2",
            )
        with tempfile.TemporaryDirectory() as second_root:
            second, _sealed, _evidence = self._seal_discovery_fixture(
                second_root,
                status="FAIL",
                error="DISCOVERY_FAILED: TypeError: port 16379 in m2-discovery-gh-456-attempt-3",
                run_id="456",
                run_attempt="3",
            )
        self.assertEqual(first["failure_fingerprint"], second["failure_fingerprint"])
        self.assertNotIn("6379", first["summary"])
        self.assertNotIn("16379", second["summary"])

    def test_discovery_digest_and_cleanup_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            digest, _sealed, _evidence = self._seal_discovery_fixture(
                temporary,
                status="PASS",
                tamper_report_digest=True,
            )
        self.assertEqual(digest["status"], "BLOCKED")
        self.assertEqual(digest["disposition"], "HUMAN_REQUIRED")

        with tempfile.TemporaryDirectory() as temporary:
            cleanup, _sealed, _evidence = self._seal_discovery_fixture(
                temporary,
                status="PASS",
                cleanup_outcome="failure",
            )
        self.assertEqual(cleanup["status"], "BLOCKED")
        self.assertEqual(cleanup["cleanup_outcome"], "failure")
        self.assertEqual(cleanup["failure_class"], "environment")
        self.assertFalse(cleanup["retryable"])

        with tempfile.TemporaryDirectory() as temporary:
            failed_cleanup, sealed, evidence = self._seal_discovery_fixture(
                temporary,
                status="FAIL",
                error="DISCOVERY_FAILED: CaptureError: sampler IPC failed",
                cleanup_outcome="failure",
                failure_class="measurement",
            )
            loaded = load_m2_discovery_result(
                result_path=sealed,
                evidence_root=evidence,
                expected_sha="a" * 40,
                expected_lease_sha256="b" * 64,
                run_id="123",
                run_attempt="2",
            )
        self.assertEqual(failed_cleanup["status"], "BLOCKED")
        self.assertEqual(failed_cleanup["disposition"], "HUMAN_REQUIRED")
        self.assertEqual(failed_cleanup["failure_phase"], "formation")
        self.assertEqual(failed_cleanup["failure_class"], "environment")
        self.assertFalse(failed_cleanup["retryable"])
        self.assertEqual(loaded, failed_cleanup)

        with tempfile.TemporaryDirectory() as temporary:
            malformed, _sealed, _evidence = self._seal_discovery_fixture(
                temporary,
                status="PASS",
                malformed_campaign=True,
            )
        self.assertEqual(malformed["status"], "BLOCKED")
        self.assertEqual(malformed["disposition"], "HUMAN_REQUIRED")

    def test_sealed_discovery_cannot_be_reused_by_another_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _result, sealed, evidence = self._seal_discovery_fixture(
                temporary, status="PASS"
            )
            with self.assertRaises(ContractError):
                load_m2_discovery_result(
                    result_path=sealed,
                    evidence_root=evidence,
                    expected_sha="a" * 40,
                    expected_lease_sha256="b" * 64,
                    run_id="123",
                    run_attempt="3",
                )
            with self.assertRaises(ContractError):
                load_m2_discovery_result(
                    result_path=sealed,
                    evidence_root=evidence,
                    expected_sha="a" * 40,
                    expected_lease_sha256="c" * 64,
                    run_id="123",
                    run_attempt="2",
                )

    def test_missing_or_tampered_discovery_artifacts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = seal_m2_discovery_result(
                raw_result_path=root / "missing-result.json",
                evidence_root=root / "missing-evidence",
                output_path=root / "sealed.json",
                expected_sha="a" * 40,
                expected_lease_sha256="b" * 64,
                run_id="123",
                run_attempt="2",
                run_outcome="success",
                cleanup_outcome="success",
            )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["disposition"], "HUMAN_REQUIRED")

        with tempfile.TemporaryDirectory() as temporary:
            _result, sealed, evidence = self._seal_discovery_fixture(
                temporary, status="PASS"
            )
            value = json.loads(sealed.read_text(encoding="utf-8"))
            value["summary"] = "tampered after sealing"
            sealed.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ContractError):
                load_m2_discovery_result(
                    result_path=sealed,
                    evidence_root=evidence,
                    expected_sha="a" * 40,
                    expected_lease_sha256="b" * 64,
                    run_id="123",
                    run_attempt="2",
                )

    def test_stale_discovery_sha_fails_closed_at_sealing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence"
            evidence.mkdir()
            raw = root / "raw.json"
            raw.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "summary": "selection complete",
                        "milestone": "m2",
                        "entrypoint": "discovery",
                        "tested_sha": "b" * 40,
                        "lease_sha256": "b" * 64,
                        "run_id": "123",
                        "run_attempt": "2",
                    }
                ),
                encoding="utf-8",
            )
            result = seal_m2_discovery_result(
                raw_result_path=raw,
                evidence_root=evidence,
                output_path=root / "sealed.json",
                expected_sha="a" * 40,
                expected_lease_sha256="b" * 64,
                run_id="123",
                run_attempt="2",
                run_outcome="success",
                cleanup_outcome="success",
            )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["disposition"], "HUMAN_REQUIRED")

    def test_m2_failure_diagnostic_reaches_context_without_raw_evidence(self) -> None:
        sentinel = "RAW-EVIDENCE-MUST-NOT-ENTER-CONTEXT"
        gate_summary = {
            "status": "FAIL",
            "tests": [
                {
                    "instance_id": "001-passing-check",
                    "criterion_id": "passing.criterion",
                    "check_id": "passing.check",
                    "test_id": "passing.test",
                    "status": "PASS",
                    "detail": sentinel,
                },
                {
                    "instance_id": "002-real.local.m2-cluster-formation",
                    "criterion_id": "performance.cluster-formation-experiment",
                    "check_id": "real.local.m2-cluster-formation",
                    "test_id": "real.local.m2-cluster-formation",
                    "status": "FAIL",
                    "exit_code": 0,
                    "detail": (
                        f"candidate did not improve at /private/tmp/{sentinel}\n"
                        "@mention <unsafe>"
                    ),
                    "parameters": {"secret": sentinel},
                    "artifacts_dir": f"/private/tmp/{sentinel}",
                    "extra": sentinel,
                },
            ],
        }
        with patch.dict(
            os.environ,
            {"GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "2"},
        ):
            result = _gate_result_summary(
                milestone="m2",
                gate_status="FAIL",
                summary=gate_summary,
                exit_code=1,
                expected_sha="a" * 40,
                invocation_id="gate-20260720T095023Z-02167ee1",
            )

        self.assertLessEqual(len(result), 3800)
        self.assertNotIn("\n", result)
        self.assertIn("not Criterion or admission evidence", result)
        self.assertIn("performance.cluster-formation-experiment", result)
        self.assertIn("candidate did not improve", result)
        self.assertIn("[absolute-path]", result)
        self.assertIn("milestone-evidence-12345-2", result)
        self.assertNotIn("passing.criterion", result)
        self.assertNotIn(sentinel, result)
        self.assertNotIn("@mention", result)
        self.assertNotIn("<unsafe>", result)

        snapshot = {
            "repository": "owner/repo",
            "default_branch": "main",
            "default_sha": "a" * 40,
            "issues": [
                {
                    "number": 7,
                    "title": "M2 Control",
                    "body": "control",
                    "state": "open",
                    "labels": [CONTROL_LABEL],
                    "comments": [
                        {
                            "author": "github-actions[bot]",
                            "body": result,
                        }
                    ],
                }
            ],
            "pull_requests": [],
        }
        context = build_context(
            repo_root=ROOT,
            snapshot=snapshot,
            milestone_document=json.loads(
                (ROOT / "project/milestones/m2/milestone.json").read_text()
            ),
        )
        encoded = json.dumps(context)
        self.assertIn("gate-20260720T095023Z-02167ee1", encoded)
        self.assertIn("real.local.m2-cluster-formation", encoded)
        self.assertNotIn(sentinel, encoded)

    def test_m2_failure_diagnostic_is_bounded_and_other_milestones_are_unchanged(self) -> None:
        tests = [
            {
                "instance_id": f"{index:03d}-real.local.m2-check",
                "criterion_id": "performance.test",
                "check_id": "real.local.m2-check",
                "test_id": "real.local.m2-check",
                "status": "FAIL",
                "detail": "x" * 10_000,
            }
            for index in range(100)
        ]
        summary = {"status": "FAIL", "tests": tests}
        result = _gate_result_summary(
            milestone="m2",
            gate_status="FAIL",
            summary=summary,
            exit_code=1,
            expected_sha="a" * 40,
            invocation_id="gate-current",
        )
        self.assertLessEqual(len(result), 3800)
        self.assertNotIn("\n", result)
        self.assertIn('"non_pass_total":100', result)
        self.assertRegex(result, r'"omitted_non_pass":[1-9][0-9]*')

        for milestone in ("m1", "m3", "m4"):
            self.assertEqual(
                _gate_result_summary(
                    milestone=milestone,
                    gate_status="FAIL",
                    summary=summary,
                    exit_code=1,
                    expected_sha="a" * 40,
                    invocation_id="gate-current",
                ),
                "Gate exit=1; summary status=FAIL",
            )

    def test_current_real_admission_chain_is_protected(self) -> None:
        from coordinator import protected_changes

        paths = (
            ".github/CODEOWNERS",
            "project/scripts/m2_candidate_discovery.py",
            "project/scripts/m2_performance_capture.py",
            "project/scripts/m2_performance_gate.py",
            "project/src/valkey_scale_lab/cli.py",
            "project/src/valkey_scale_lab/gates/real.py",
            "project/src/valkey_scale_lab/runtime/docker_runtime.py",
        )
        self.assertEqual(protected_changes(paths), paths)
        codeowners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        for path in paths[1:4]:
            self.assertIn(f"/{path} @ly989264", codeowners.splitlines())


if __name__ == "__main__":
    unittest.main()
