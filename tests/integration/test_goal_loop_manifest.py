from __future__ import annotations

import json
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


def test_strict_stage_assertion_cli_passes_for_p27() -> None:
    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = str(Path(".pycache").resolve())
    proc = subprocess.run(
        ["python3", "scripts/assert_strict_stage_contract.py", "--phase", "P27_STRICT_MATRIX_REBASE_HARNESS"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "PASS strict stage contract" in proc.stdout


def test_coverage_registry_bootstrap_cli_passes() -> None:
    proc = subprocess.run(
        ["python3", "scripts/assert_coverage_registry.py", "--bootstrap-only"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "PASS coverage bootstrap assertion" in proc.stdout


def test_p25_manifest_generates_analysis_before_assertions() -> None:
    manifest = json.loads(Path("codex/phase_manifest.json").read_text(encoding="utf-8"))
    phase = next(item for item in manifest["phases"] if item["id"] == "P25_FAULT_WORKLOAD_IMPACT_ANALYSIS")
    names = [gate["name"] for gate in phase["gates"]]

    assert names.index("real_valkey_e2e") < names.index("p25_workload_impact_analysis")
    assert names.index("p25_workload_impact_analysis") < names.index("quant_artifact_assertion")
    assert names.index("p25_workload_impact_analysis") < names.index("workload_impact_assertion")
    command = phase["gates"][names.index("p25_workload_impact_analysis")]["command"]
    assert "--kind workload-impact" in command
    assert "artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS" in command
