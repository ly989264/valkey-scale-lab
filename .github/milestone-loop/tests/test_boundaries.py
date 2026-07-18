from __future__ import annotations

import json
import os
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from context_builder import MAX_CONTEXT_BYTES, build_context
from contracts import ContractError
from coordinator import CONTROL_LABEL, LoopBlocked, empty_lease, render_control
from milestone_runner import _lease_fingerprint, _validate_consumed_lease
from recovery import cleanup_owned_docker, cleanup_runtime_root


ROOT = Path(__file__).resolve().parents[3]


class BoundaryTests(unittest.TestCase):
    def test_repository_has_one_workflow_and_single_runner_role_routing(self) -> None:
        workflows = sorted((ROOT / ".github" / "workflows").glob("*"))
        self.assertEqual([path.name for path in workflows], ["milestone-loop.yml"])
        text = workflows[0].read_text()
        self.assertIn("[self-hosted, macOS, valkey-codex]", text)
        self.assertIn("[self-hosted, macOS, valkey-verify]", text)
        self.assertIn("[self-hosted, macOS, valkey-real]", text)
        self.assertNotIn("ubuntu-latest", text)
        self.assertIn("group: valkey-scale-lab-milestone-loop", text)
        self.assertIn("cancel-in-progress: false", text)
        dispatch_block = text.split("  workflow_dispatch:", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(dispatch_block.count("      action:"), 1)
        self.assertEqual(dispatch_block.count("      milestone:"), 1)
        self.assertIn("options: [start, resume]", dispatch_block)
        self.assertIn("options: [m1, m2, m3]", dispatch_block)
        self.assertIn("[\"./gate\", \"milestone\", milestone]", (ROOT / ".github/milestone-loop/milestone_runner.py").read_text())

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

    def test_current_real_admission_chain_is_protected(self) -> None:
        from coordinator import protected_changes

        paths = (
            ".github/CODEOWNERS",
            "project/src/valkey_scale_lab/cli.py",
            "project/src/valkey_scale_lab/gates/real.py",
            "project/src/valkey_scale_lab/runtime/docker_runtime.py",
        )
        self.assertEqual(protected_changes(paths), paths)


if __name__ == "__main__":
    unittest.main()
