from __future__ import annotations

import json
from pathlib import Path

import pytest

from valkey_scale_lab.goal import parse_goal_definition
from valkey_scale_lab.meta_loop_v8.cli import _parser
from valkey_scale_lab.meta_loop_v8.controller import load_v8_kernel_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_v8_kernel_manifest_covers_reused_core_and_all_v8_controller_modules() -> None:
    raw = json.loads((PROJECT_ROOT / "codex/meta_m1_v8/kernel_manifest.json").read_text(encoding="utf-8"))
    files = set(raw["files"])
    goal_modules = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "src/valkey_scale_lab/goal").glob("*.py")
    }
    v8_modules = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "src/valkey_scale_lab/meta_loop_v8").glob("*.py")
    }
    assert goal_modules <= files
    assert v8_modules <= files
    assert "scripts/meta_m1_real_gate_v8.py" in files
    assert "tests/meta_loop_v8/test_retry_budget.py" in files
    manifest = load_v8_kernel_manifest(PROJECT_ROOT, "codex/meta_m1_v8/kernel_manifest.json")
    assert set(manifest.paths) == files


def test_v8_kernel_manifest_seals_v7_reproduction_and_v8_successor() -> None:
    raw = json.loads((PROJECT_ROOT / "codex/meta_m1_v8/kernel_manifest.json").read_text(encoding="utf-8"))
    files = set(raw["files"])
    assert "tests/meta_loop_v7/test_o1_retry_budget_gap.py" in files
    assert "tests/meta_loop_v8/test_retry_budget.py" in files


def test_v8_control_requires_successor_and_excludes_only_frozen_v7_gap_test() -> None:
    raw = json.loads((PROJECT_ROOT / "codex/meta_m1_v8/control_block.json").read_text(encoding="utf-8"))
    goal = parse_goal_definition(raw, expected_version="v8")
    assert [objective.id for objective in goal.objectives] == [
        "O1_GOAL_SCHEDULER_AND_CONTRACTS",
        "O2_CANONICAL_SCENARIO_DEFINITION",
        "O3_GATE_ORCHESTRATION_AND_RUNTIME_ADAPTERS",
        "O4_EVIDENCE_AND_ADMISSION",
        "O5_ANALYSIS_AND_REPORT",
        "O6_COMPATIBILITY_SAFETY_AND_EXACT_50",
        "O7_EXACT_200_AND_FINAL_CLOSURE",
    ]
    closure = next(check for check in goal.closure_checks if check.id == "full-non-real-regression-floor")
    ignores = {arg for arg in closure.command if arg.startswith("--ignore=")}
    assert ignores == {
        "--ignore=tests/real_valkey",
        "--ignore=tests/meta_loop_v7/test_o1_retry_budget_gap.py",
    }
    o1 = goal.objective("O1_GOAL_SCHEDULER_AND_CONTRACTS")
    core = next(check for check in o1.checks if check.id == "v8-goal-controller-contract")
    assert "tests/meta_loop_v7" in core.command
    assert "tests/meta_loop_v8" in core.command
    assert {arg for arg in core.command if arg.startswith("--ignore=")} == {
        "--ignore=tests/meta_loop_v7/test_o1_retry_budget_gap.py"
    }
    successor = next(check for check in o1.checks if check.id == "o1-changing-failure-identity-budget-v8")
    assert "tests/meta_loop_v8/test_retry_budget.py" in successor.command


def test_v8_cli_has_migration_but_no_bootstrap(capsys) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(["bootstrap"])
    assert "invalid choice" in capsys.readouterr().err
    args = _parser().parse_args(["migrate-v7", "--state", "source.json"])
    assert args.command == "migrate-v7"
