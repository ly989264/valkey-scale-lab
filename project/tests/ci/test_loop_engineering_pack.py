from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCHEMAS = [
    "command_log_entry",
    "subagent_response",
    "stage_state",
    "previous_harness_result",
    "current_harness_plan",
    "validation_result",
    "stage_result",
    "global_loop_state",
]


def test_loop_engineering_pack_files_exist() -> None:
    assert Path("scripts/loop_engineering_validate.py").is_file()
    assert Path("tests/loop_engineering/test_loop_state_contract.py").is_file()
    for name in SCHEMAS:
        assert Path(f"schemas/loop_engineering/{name}.schema.json").is_file()


def test_loop_engineering_validator_accepts_current_root() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/loop_engineering_validate.py", "--root", "artifacts/loop_engineering"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_github_coverage_workflow_runs_loop_engineering_pack() -> None:
    text = Path(".github/workflows/github-coverage-gates.yml").read_text(encoding="utf-8")
    required_commands = [
        "python3 scripts/loop_engineering_validate.py --root artifacts/loop_engineering",
        "python3 -m pytest -q tests/loop_engineering tests/ci/test_loop_engineering_pack.py",
    ]
    for command in required_commands:
        assert command in text


def test_loop_engineering_workflow_stays_off_p14_and_real_gates() -> None:
    text = Path(".github/workflows/github-coverage-gates.yml").read_text(encoding="utf-8")
    forbidden_tokens = [
        "P14_SCALE_1000_OPTIN_DRYRUN",
        "VSLAB_ALLOW_1000_DRYRUN",
        "scripts/valkey_e2e_gate.py",
        "scripts/fault_safety_gate.py",
        "scripts/fault_failover_gate.py",
    ]
    for token in forbidden_tokens:
        assert token not in text
