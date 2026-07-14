from __future__ import annotations

import json
from pathlib import Path

import pytest

from valkey_scale_lab.goal import parse_goal_definition
from valkey_scale_lab.meta_loop_v9.cli import _parser
from valkey_scale_lab.meta_loop_v9.controller import load_v9_kernel_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
V7_GAP = "--ignore=tests/meta_loop_v7/test_o1_retry_budget_gap.py"
V8_GAP = "--deselect=tests/meta_loop_v8/test_contract.py::test_v8_kernel_manifest_seals_v7_reproduction_and_v8_successor"


def test_v9_kernel_manifest_seals_v7_v8_gap_chain_and_v9_successor() -> None:
    raw = json.loads((PROJECT_ROOT / "codex/meta_m1_v9/kernel_manifest.json").read_text(encoding="utf-8"))
    files = set(raw["files"])
    required = {
        "codex/meta_m1_v8/kernel_manifest.json",
        "tests/meta_loop_v7/test_o1_retry_budget_gap.py",
        "tests/meta_loop_v8/test_retry_budget.py",
        "tests/meta_loop_v8/test_contract.py",
        "tests/meta_loop_v9/test_v9_contract.py",
    }
    assert required <= files


def test_v9_kernel_manifest_covers_all_transitive_controller_modules() -> None:
    raw = json.loads((PROJECT_ROOT / "codex/meta_m1_v9/kernel_manifest.json").read_text(encoding="utf-8"))
    files = set(raw["files"])
    for package in ("goal", "meta_loop_v8", "meta_loop_v9"):
        modules = {
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in (PROJECT_ROOT / f"src/valkey_scale_lab/{package}").glob("*.py")
        }
        assert modules <= files
    assert "scripts/meta_m1_real_gate_v9.py" in files
    assert set(load_v9_kernel_manifest(PROJECT_ROOT, "codex/meta_m1_v9/kernel_manifest.json").paths) == files


def test_v9_control_excludes_exactly_both_frozen_kernel_gap_proofs() -> None:
    raw = json.loads((PROJECT_ROOT / "codex/meta_m1_v9/control_block.json").read_text(encoding="utf-8"))
    goal = parse_goal_definition(raw, expected_version="v9")
    closure = next(check for check in goal.closure_checks if check.id == "full-non-real-regression-floor")
    assert {arg for arg in closure.command if arg.startswith(("--ignore=", "--deselect="))} == {
        "--ignore=tests/real_valkey",
        V7_GAP,
        V8_GAP,
    }
    o1 = goal.objective("O1_GOAL_SCHEDULER_AND_CONTRACTS")
    core = next(check for check in o1.checks if check.id == "v9-goal-controller-contract")
    assert all(path in core.command for path in ("tests/meta_loop_v7", "tests/meta_loop_v8", "tests/meta_loop_v9"))
    assert {arg for arg in core.command if arg.startswith(("--ignore=", "--deselect="))} == {V7_GAP, V8_GAP}
    successor = next(check for check in o1.checks if check.id == "o1-seal-v7-v8-kernel-gap-evidence-v9")
    assert "tests/meta_loop_v9/test_v9_contract.py::test_v9_kernel_manifest_seals_v7_v8_gap_chain_and_v9_successor" in successor.command


def test_v9_cli_has_migration_but_no_bootstrap(capsys) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(["bootstrap"])
    assert "invalid choice" in capsys.readouterr().err
    assert _parser().parse_args(["migrate-v8", "--state", "source.json"]).command == "migrate-v8"
