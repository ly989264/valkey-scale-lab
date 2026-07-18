from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agent import _agent_environment
from verifier import _candidate_environment


class AgentBoundaryTests(unittest.TestCase):
    def test_agent_never_inherits_github_or_real_environment_credentials(self) -> None:
        values = {
            "GH_TOKEN": "write-token",
            "GITHUB_TOKEN": "write-token",
            "AWS_SECRET_ACCESS_KEY": "real-secret",
            "VALKEY_REAL_CREDENTIAL": "real-secret",
            "MILESTONE_LEASE_NONCE": "lease",
            "SSH_AUTH_SOCK": "/tmp/agent.sock",
            "CODEX_HOME": "/safe/codex-home",
            "PATH": "/usr/bin",
        }
        with patch.dict(os.environ, values, clear=True):
            environment = _agent_environment()
        self.assertEqual(environment["CODEX_HOME"], "/safe/codex-home")
        self.assertEqual(environment["PATH"], "/usr/bin")
        for name in values:
            if name not in {"CODEX_HOME", "PATH"}:
                self.assertNotIn(name, environment)

    def test_candidate_gate_never_inherits_ssh_or_service_credentials(self) -> None:
        values = {
            "GH_TOKEN": "write-token",
            "GITHUB_TOKEN": "write-token",
            "OPENAI_API_KEY": "agent-secret",
            "SSH_AUTH_SOCK": "/tmp/agent.sock",
            "PATH": "/usr/bin",
        }
        with patch.dict(os.environ, values, clear=True):
            environment = _candidate_environment()
        self.assertEqual(environment["PATH"], "/usr/bin")
        for name in values:
            if name != "PATH":
                self.assertNotIn(name, environment)


if __name__ == "__main__":
    unittest.main()
