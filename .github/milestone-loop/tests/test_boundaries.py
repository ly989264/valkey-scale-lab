from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from context_builder import MAX_CONTEXT_BYTES, build_context
from contracts import ContractError
from coordinator import (
    CONTROL_LABEL,
    PR_MILESTONE_RE,
    ControlState,
    LoopBlocked,
    empty_lease,
    render_control,
)
from github_api import GitHubClient
from loop import pr_metadata
from milestone_runner import (
    _canonical_digest,
    _gate_environment,
    _gate_result_summary,
    _lease_fingerprint,
    _m2_discovery_run_id,
    _validate_consumed_lease,
    authorize,
    load_m2_discovery_result,
    run_m2_discovery,
    seal_m2_discovery_result,
)
from recovery import cleanup_owned_docker, cleanup_runtime_root


ROOT = Path(__file__).resolve().parents[3]


class BoundaryTests(unittest.TestCase):
    def test_contract_change_body_closes_the_label_event_race(self) -> None:
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
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "event.json"
            path.write_text(json.dumps(event), encoding="utf-8")
            metadata = pr_metadata(object(), path)
        self.assertTrue(metadata["contract_change"])
        self.assertEqual(metadata["check"], "repository.all")

    def test_repository_has_one_workflow_and_single_runner_role_routing(self) -> None:
        workflows = sorted((ROOT / ".github" / "workflows").glob("*"))
        self.assertEqual([path.name for path in workflows], ["milestone-loop.yml"])
        text = workflows[0].read_text()
        self.assertIn("[self-hosted, macOS, valkey-codex]", text)
        self.assertIn("[self-hosted, macOS, valkey-verify]", text)
        self.assertIn("[self-hosted, macOS, valkey-real]", text)
        authorize_real = text.split("  authorize-real:", 1)[1].split("\n  milestone:", 1)[0]
        self.assertEqual(
            authorize_real.count("if: needs.coordinate.outputs.status == 'MILESTONE'"),
            1,
        )
        self.assertIn("entrypoint: ${{ steps.authorize.outputs.entrypoint }}", authorize_real)
        milestone_job = text.split("\n  milestone:", 1)[1].split("\n  m2-discovery:", 1)[0]
        self.assertIn("needs.authorize-real.outputs.entrypoint == 'milestone'", milestone_job)
        discovery_job = text.split("\n  m2-discovery:", 1)[1].split(
            "\n  record-milestone:", 1
        )[0]
        self.assertIn("needs.authorize-real.outputs.entrypoint == 'discovery'", discovery_job)
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
        self.assertIn(
            'test "${{ steps.record.outputs.discovery_status }}" = "PASS"',
            discovery_record_job,
        )
        record_job = text.split("\n  record-milestone:", 1)[1]
        self.assertIn("needs: [authorize-real, milestone]", record_job)
        self.assertIn(
            "needs.authorize-real.outputs.entrypoint == 'milestone'", record_job
        )
        self.assertNotIn("record-m2-discovery", record_job)
        self.assertNotIn("ubuntu-latest", text)
        self.assertIn("  candidate:\n    name: milestone-loop / candidate", text)
        self.assertIn('run: test "${{ steps.verify.outcome }}" = "success"', text)
        self.assertIn("group: valkey-scale-lab-milestone-loop", text)
        self.assertIn("cancel-in-progress: false", text)
        after_merge = text.split("\n  after-merge:", 1)[1].split("\n  coordinate:", 1)[0]
        self.assertIn("actions: write", after_merge)
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
        _validate_consumed_lease(snapshot, _lease_fingerprint(lease))
        changed = dict(lease)
        changed["nonce"] = "changed"
        snapshot["issues"][0]["body"] = render_control(changed, 0)
        with self.assertRaises(LoopBlocked):
            _validate_consumed_lease(snapshot, _lease_fingerprint(lease))

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

    def test_authorize_rechecks_m2_candidate_before_consuming_lease(self) -> None:
        snapshot = {
            "default_sha": "a" * 40,
            "milestone": "m2",
            "issues": [],
        }
        checkout = subprocess.CompletedProcess([], 0, "a" * 40 + "\n", "")
        with (
            patch("milestone_runner.collect_snapshot", return_value=snapshot),
            patch("milestone_runner.subprocess.run", return_value=checkout),
            patch("milestone_runner.load_trusted_documents", return_value=({}, {})),
            patch(
                "milestone_runner.m2_candidate_blockers",
                return_value=("real.local.m2-cluster-formation.selected_strategy",),
            ),
            patch("milestone_runner.consume_lease") as consume,
        ):
            with self.assertRaises(LoopBlocked):
                authorize(object(), ROOT, "m2")
        consume.assert_not_called()

    def test_authorize_preserves_non_m2_flow(self) -> None:
        snapshot = {
            "default_sha": "a" * 40,
            "milestone": "m1",
            "issues": [],
        }
        checkout = subprocess.CompletedProcess([], 0, "a" * 40 + "\n", "")
        consumed = ControlState(7, empty_lease("m1"), 0)
        client = object()
        with (
            patch("milestone_runner.collect_snapshot", return_value=snapshot),
            patch("milestone_runner.subprocess.run", return_value=checkout) as run,
            patch("milestone_runner.consume_lease", return_value=consumed) as consume,
        ):
            result = authorize(client, ROOT, "m1")
        self.assertEqual(result["default_sha"], "a" * 40)
        self.assertEqual(result["entrypoint"], "milestone")
        consume.assert_called_once_with(client, snapshot)
        run.assert_not_called()

    def test_authorize_allows_an_explicit_m2_candidate(self) -> None:
        snapshot = {
            "default_sha": "a" * 40,
            "milestone": "m2",
            "issues": [],
        }
        checkout = subprocess.CompletedProcess([], 0, "a" * 40 + "\n", "")
        consumed = ControlState(7, empty_lease("m2"), 0)
        client = object()
        with (
            patch("milestone_runner.collect_snapshot", return_value=snapshot),
            patch("milestone_runner.subprocess.run", return_value=checkout),
            patch("milestone_runner.load_trusted_documents", return_value=({}, {})),
            patch("milestone_runner.m2_candidate_blockers", return_value=()),
            patch("milestone_runner.consume_lease", return_value=consumed) as consume,
        ):
            result = authorize(client, ROOT, "m2")
        self.assertEqual(result["default_sha"], "a" * 40)
        self.assertEqual(result["entrypoint"], "milestone")
        consume.assert_called_once_with(client, snapshot)

    def test_authorize_routes_only_canonical_m2_state_to_discovery(self) -> None:
        snapshot = {
            "default_sha": "a" * 40,
            "milestone": "m2",
            "issues": [],
        }
        checkout = subprocess.CompletedProcess([], 0, "a" * 40 + "\n", "")
        consumed = ControlState(7, empty_lease("m2"), 0)
        client = object()
        with (
            patch("milestone_runner.collect_snapshot", return_value=snapshot),
            patch("milestone_runner.subprocess.run", return_value=checkout),
            patch("milestone_runner.load_trusted_documents", return_value=({}, {})),
            patch("milestone_runner.m2_candidate_blockers", return_value=("unresolved",)),
            patch("milestone_runner.m2_discovery_eligible", return_value=True),
            patch("milestone_runner.consume_lease", return_value=consumed) as consume,
        ):
            result = authorize(client, ROOT, "m2")
        self.assertEqual(result["entrypoint"], "discovery")
        consume.assert_called_once_with(client, snapshot)

    def _run_discovery_fixture(
        self,
        *,
        include_admission_report: bool = False,
        status: str = "PASS",
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
                    json.dumps({"status": status, "summary": "selection screen complete"}),
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
            validate_lease.assert_called_once_with(snapshot, "b" * 64)
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
    ) -> tuple[dict, Path, Path]:
        root = Path(temporary)
        evidence = root / "evidence"
        evidence.mkdir()
        raw_result = root / "raw.json"
        sealed = root / "sealed.json"
        sha = "a" * 40
        invocation = f"m2-discovery-gh-{run_id}-attempt-{run_attempt}"
        source = evidence / "current-source.json"
        source.write_text('{"current":true}\n', encoding="utf-8")
        source_ref = {
            "category": "preflight",
            "path": source.name,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }

        def campaign(kind: str, campaign_status: str, started: list[str], cells: list[dict]) -> dict:
            trials: list[dict] = []
            pairs: list[dict] = []
            if campaign_status == "PASS":
                for cell in cells:
                    pair_id = f"{cell['cell_id']}-pair-1"
                    baseline_id = f"{pair_id}-baseline"
                    candidate_id = f"{pair_id}-candidate"
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
                "invalid_samples": [],
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
                    "formation", "PASS", ["formation-trial"], [formation_losing_cell]
                ),
                "failover": campaign(
                    "failover", "PASS", ["failover-trial"], [failover_losing_cell]
                ),
            }
        else:
            campaigns = {
                "formation": campaign("formation", "FAIL", ["formation-trial"], []),
                "failover": campaign("failover", "FAIL", [], []),
            }
        candidate_results = {
            kind: [
                {"candidate": dict(cell["candidate"]), "status": cell["status"]}
                for cell in value["cells"]
            ]
            for kind, value in campaigns.items()
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
            "real_valkey": True,
            "execution_mode": "valkey-real",
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
        raw_result.write_text(
            json.dumps({"status": status, "summary": error or "selection complete", "tested_sha": sha}),
            encoding="utf-8",
        )
        result = seal_m2_discovery_result(
            raw_result_path=raw_result,
            evidence_root=evidence,
            output_path=sealed,
            expected_sha=sha,
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
                run_id="123",
                run_attempt="2",
            )
        self.assertEqual(result["disposition"], "CANDIDATE_SELECTION_ONLY")
        self.assertEqual(loaded["status"], "PASS")
        self.assertEqual(loaded["failure_scope"], "")

    def test_only_narrow_programming_failure_is_repairable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repairable, _sealed, _evidence = self._seal_discovery_fixture(
                temporary,
                status="FAIL",
                error="DISCOVERY_FAILED: TypeError: formation collector called an invalid API",
            )
        self.assertEqual(repairable["disposition"], "REPAIRABLE_IMPLEMENTATION")
        self.assertEqual(repairable["failure_scope"], "formation")
        self.assertEqual(repairable["failure_code"], "python-typeerror")

        with tempfile.TemporaryDirectory() as temporary:
            safety, _sealed, _evidence = self._seal_discovery_fixture(
                temporary,
                status="FAIL",
                error="DISCOVERY_FAILED: CaptureError: cluster link safety metric is nonzero",
            )
        self.assertEqual(safety["status"], "FAIL")
        self.assertEqual(safety["disposition"], "HUMAN_REQUIRED")

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
                    run_id="123",
                    run_attempt="3",
                )

    def test_missing_or_tampered_discovery_artifacts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = seal_m2_discovery_result(
                raw_result_path=root / "missing-result.json",
                evidence_root=root / "missing-evidence",
                output_path=root / "sealed.json",
                expected_sha="a" * 40,
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
                        "tested_sha": "b" * 40,
                    }
                ),
                encoding="utf-8",
            )
            result = seal_m2_discovery_result(
                raw_result_path=raw,
                evidence_root=evidence,
                output_path=root / "sealed.json",
                expected_sha="a" * 40,
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
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "12345"}):
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
        self.assertIn("milestone-evidence-12345", result)
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
