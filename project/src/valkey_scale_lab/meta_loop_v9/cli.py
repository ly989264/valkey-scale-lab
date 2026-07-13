from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from valkey_scale_lab.goal import ContractError, GoalServiceError, ProgramRunnerError, StateStoreError, load_json

from .controller import MetaLoopV9Controller


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = PROJECT_ROOT.parent


def controller() -> MetaLoopV9Controller:
    return MetaLoopV9Controller(
        project_root=PROJECT_ROOT,
        workspace_root=WORKSPACE_ROOT,
        control_path=PROJECT_ROOT / "codex/meta_m1_v9/control_block.json",
        state_root=WORKSPACE_ROOT / "loop_evidence/meta_runs/milestone1-v9",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Milestone pipeline-refactor v9 Goal controller")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    migrate = commands.add_parser("migrate-v8")
    migrate.add_argument("--state", type=Path, required=True)
    commands.add_parser("status")
    commands.add_parser("next")
    commands.add_parser("evaluate")
    commands.add_parser("accept-evaluator-repair")
    review = commands.add_parser("review")
    review.add_argument("--report", type=Path, required=True)
    return parser


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    service = controller()
    try:
        if args.command == "doctor":
            result = service.doctor()
        elif args.command == "migrate-v8":
            result = service.migrate_v8(args.state)
        elif args.command == "status":
            result = service.status()
        elif args.command == "next":
            result = service.next_work_item()
        elif args.command == "evaluate":
            result = service.evaluate_active()
        elif args.command == "accept-evaluator-repair":
            result = service.accept_evaluator_repair()
        elif args.command == "review":
            result = service.submit_review(load_json(args.report))
        else:  # pragma: no cover
            raise GoalServiceError(f"unknown command: {args.command}")
    except (ContractError, GoalServiceError, ProgramRunnerError, StateStoreError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _emit(result)
    return 0
