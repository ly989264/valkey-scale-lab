from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .contracts import ContractError, load_json
from .controller import MetaLoopController, MetaLoopError
from .runner import ProgramRunnerError
from .store import StateStoreError


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = PROJECT_ROOT.parent


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Milestone 1 v6 Goal-mode controller")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("bootstrap")
    migrate_v5 = commands.add_parser("migrate-v5")
    migrate_v5.add_argument("--state", type=Path, required=True)
    migrate = commands.add_parser("migrate-v2")
    migrate.add_argument("--receipt", type=Path, required=True)
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
    controller = MetaLoopController(
        project_root=PROJECT_ROOT,
        control_path=PROJECT_ROOT / "codex" / "meta_m1_v6" / "control_block.json",
        state_root=WORKSPACE_ROOT / "loop_evidence" / "meta_runs" / "milestone1-v6",
        workspace_root=WORKSPACE_ROOT,
    )
    try:
        if args.command == "doctor":
            result = controller.doctor()
        elif args.command == "bootstrap":
            result = controller.bootstrap()
        elif args.command == "migrate-v5":
            result = controller.migrate_v5(args.state)
        elif args.command == "migrate-v2":
            result = controller.migrate_v2(args.receipt)
        elif args.command == "status":
            result = controller.status()
        elif args.command == "next":
            result = controller.next_work_item()
        elif args.command == "evaluate":
            result = controller.evaluate_active()
        elif args.command == "accept-evaluator-repair":
            result = controller.accept_evaluator_repair()
        elif args.command == "review":
            result = controller.submit_review(load_json(args.report))
        else:  # pragma: no cover
            raise MetaLoopError(f"unknown command: {args.command}")
    except (ContractError, MetaLoopError, ProgramRunnerError, StateStoreError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
