from __future__ import annotations

from pathlib import Path

from valkey_scale_lab.goal import load_json, load_kernel_manifest, parse_goal_definition
from valkey_scale_lab.meta_loop_v7.cli import _parser


def test_repository_v7_control_and_explicit_kernel_manifest_are_valid() -> None:
    project = Path(__file__).resolve().parents[2]
    control_path = project / "codex/meta_m1_v7/control_block.json"
    goal = parse_goal_definition(load_json(control_path), expected_version="v7")
    manifest = load_kernel_manifest(project, goal.kernel_manifest_path)
    assert len(goal.objectives) == 7
    assert "src/valkey_scale_lab/goal/controller.py" in manifest.paths
    assert "src/valkey_scale_lab/goal/service.py" in manifest.paths
    high_level = [(objective.id, check.id, check.level) for objective in goal.objectives for check in objective.checks if check.level >= 3]
    assert high_level
    assert {objective_id for objective_id, _, _ in high_level} == {
        "O6_COMPATIBILITY_SAFETY_AND_EXACT_50",
        "O7_EXACT_200_AND_FINAL_CLOSURE",
    }


def test_v7_cli_requires_anchored_migration_and_has_no_bootstrap() -> None:
    parser = _parser()
    subparsers = next(action for action in parser._actions if action.dest == "command")
    assert "migrate-v6" in subparsers.choices
    assert "bootstrap" not in subparsers.choices
