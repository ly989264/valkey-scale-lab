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
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://oidc.invalid",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "oidc-token",
            "VSLAB_M2_REAL_AUTHORIZATION": "1",
            "SSH_AUTH_SOCK": "/tmp/agent.sock",
            "CODEX_HOME": "/safe/codex-home",
            "PATH": "/usr/bin",
        }
        with patch.dict(os.environ, values, clear=True):
            environment = _agent_environment()
        self.assertEqual(environment["CODEX_HOME"], "/safe/codex-home")
        self.assertEqual(environment["PATH"], "/usr/bin")
        self.assertEqual(environment["GIT_CONFIG_KEY_0"], "credential.helper")
        self.assertEqual(environment["GIT_CONFIG_VALUE_0"], "")
        self.assertEqual(environment["GIT_CONFIG_GLOBAL"], "/dev/null")
        self.assertEqual(environment["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(environment["GIT_ASKPASS"], "/usr/bin/false")
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
