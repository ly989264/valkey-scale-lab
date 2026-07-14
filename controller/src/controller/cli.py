from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import ContractError, load_milestone


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="controller")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("milestone-validate")
    validate.add_argument("--milestone", type=Path, required=True)
    subparsers.add_parser("milestone-template")
    status = subparsers.add_parser("status")
    status.add_argument("--state", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "milestone-validate":
            milestone = load_milestone(args.milestone)
            value = {
                "status": "PASS",
                "milestone_id": milestone.id,
                "success_condition_ids": [item.id for item in milestone.success_conditions],
                "evidence_requirement_ids": [item.id for item in milestone.evidence_requirements],
            }
        elif args.command == "milestone-template":
            path = Path(__file__).resolve().parents[2] / "templates/milestone.template.json"
            value = json.loads(path.read_text(encoding="utf-8"))
        else:
            value = json.loads(args.state.read_text(encoding="utf-8"))
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0
