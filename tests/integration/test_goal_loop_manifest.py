from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_goal_loop_stage_assertion_cli_passes_for_p15() -> None:
    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = str(Path(".pycache").resolve())
    proc = subprocess.run(
        ["python3", "scripts/assert_goal_loop_stage.py", "--phase", "P15_GOAL_REBASE_HARNESS_EXTENSION"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "PASS goal-loop stage assertion" in proc.stdout
