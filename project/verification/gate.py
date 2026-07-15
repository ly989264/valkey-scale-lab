from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from verification.catalog import GateError, load_catalog
from verification.milestone import load_project_milestone
from verification.planning import (
    build_plan,
    build_milestone_plan,
    load_suite_parameters,
    parameters_for_suite,
    parse_cli_parameters,
    select_suite,
    select_test,
)
from verification.runner import TestResult, execute_test


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="./gate",
        description="Run registered project checks through catalog.json.",
    )
    commands = parser.add_subparsers(dest="command", metavar="<command>", required=True)
    commands.add_parser("help", help="Show Gate commands and parameter rules.")
    test = commands.add_parser("test", help="Run one registered Test.")
    test.add_argument("test_id", metavar="<test-id>")
    test.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    suite = commands.add_parser("suite", help="Run every Test in a registered Suite.")
    suite.add_argument("suite_id", metavar="<suite-id>")
    suite.add_argument("--params-file", type=Path, metavar="PATH")
    milestone = commands.add_parser(
        "milestone", help="Run every Check attached to a product Milestone."
    )
    milestone.add_argument("milestone_id", metavar="<milestone-id>")
    return parser


def _help(parser: argparse.ArgumentParser) -> None:
    parser.print_help()
    print(
        "\nCommands:\n"
        "  ./gate help\n"
        "  ./gate test <test-id> [--param NAME=VALUE ...]\n"
        "  ./gate suite <suite-id> [--params-file PATH]\n"
        "  ./gate milestone <milestone-id>\n\n"
        "Examples:\n"
        "  ./gate test <test-id>\n"
        "  ./gate test <test-id> --param name=value\n"
        "  ./gate suite <suite-id>\n"
        "  ./gate suite <suite-id> --params-file suite-params.json\n"
        "  ./gate milestone m1\n\n"
        "Parameter sources are exclusive: test uses --param; suite uses --params-file."
    )


def _color(status: str, enabled: bool) -> str:
    if not enabled:
        return status
    code = {
        "PASS": "32",
        "FAIL": "31",
        "BLOCKED": "33",
        "DEFINED": "36",
        "READY": "36",
        "ERROR": "35",
        "TIMEOUT": "33",
        "RUN": "36",
    }.get(status)
    return status if code is None else f"\033[{code}m{status}\033[0m"


def _overall_status(plan, results: Sequence[TestResult]) -> str:
    if plan.selection_kind != "milestone":
        return "PASS" if all(result.status == "PASS" for result in results) else "FAIL"
    if any(result.status == "FAIL" for result in results):
        return "FAIL"
    if any(result.status in {"BLOCKED", "ERROR", "TIMEOUT"} for result in results):
        return "BLOCKED"
    if plan.definition_status == "DEFINED":
        return "DEFINED"
    return "PASS"


def _write_summary(plan, results: Sequence[TestResult], status: str) -> None:
    payload = {
        "schema_version": "gate-summary-v1",
        "invocation_id": plan.invocation_id,
        "selection": {"kind": plan.selection_kind, "id": plan.selection_id},
        "status": status,
        "tests": [
            {
                "instance_id": planned.instance_id,
                "criterion_id": planned.criterion_id,
                "check_id": planned.check_id,
                "test_id": result.test_id,
                "parameters": dict(planned.parameters),
                "status": result.status,
                "duration_seconds": round(result.duration_seconds, 3),
                "detail": result.detail,
                "exit_code": result.exit_code,
                "counts": result.counts,
                "artifacts_dir": str(result.artifacts_dir),
            }
            for planned, result in zip(plan.tests, results)
        ],
    }
    if plan.definition_status is not None:
        payload["definition_status"] = plan.definition_status
    plan.artifacts_dir.mkdir(parents=True, exist_ok=True)
    (plan.artifacts_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _print_summary(
    plan, results: Sequence[TestResult], colors: bool, status: str
) -> None:
    print("\nSummary")
    headers = ("TEST ID", "STATUS", "SECONDS", "DETAIL")
    rows = [
        (
            result.test_id,
            result.status,
            f"{result.duration_seconds:.2f}",
            result.detail,
        )
        for result in results
    ]
    widths = [
        min(
            72,
            max([len(headers[index]), *(len(row[index]) for row in rows)]),
        )
        for index in range(len(headers))
    ]
    plain_header = "  ".join(
        headers[index].ljust(widths[index]) for index in range(len(headers))
    )
    print(plain_header)
    print("  ".join("-" * width for width in widths))
    for row in rows:
        values = list(row)
        row_status = values[1]
        values[1] = _color(row_status, colors)
        print(
            "  ".join(
                values[index].ljust(
                    widths[index]
                    + (len(values[1]) - len(row_status) if index == 1 else 0)
                )
                for index in range(len(headers))
            )
        )
    passed = sum(result.status == "PASS" for result in results)
    print(f"\n{passed}/{len(results)} passed")
    print(f"Status: {_color(status, colors)}")
    print(f"Artifacts: {plan.artifacts_dir}")


def _execute(plan) -> int:
    colors = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    print("Verification Gate")
    print(f"Run: {plan.invocation_id}")
    print(f"Selected: {plan.selection_kind} {plan.selection_id} ({len(plan.tests)} tests)\n")
    if plan.definition_status is not None:
        print(f"Definition: {_color(plan.definition_status, colors)}\n")
    results: list[TestResult] = []
    for index, planned in enumerate(plan.tests, start=1):
        print(
            f"[{index}/{len(plan.tests)}] {_color('RUN', colors)}  "
            f"{planned.test.test_id}",
            flush=True,
        )
        result = execute_test(planned)
        results.append(result)
        print(
            f"[{index}/{len(plan.tests)}] {_color(result.status, colors)} "
            f"{planned.test.test_id} ({result.duration_seconds:.2f}s)",
            flush=True,
        )
        if result.excerpt:
            print(result.excerpt)
    status = _overall_status(plan, results)
    _write_summary(plan, results, status)
    _print_summary(plan, results, colors, status)
    return 0 if status == "PASS" else 1


def main(
    argv: Sequence[str] | None = None,
    *,
    project_root: Path | None = None,
    catalog_path: Path | None = None,
    milestones_root: Path | None = None,
) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "help":
        _help(parser)
        return 0
    root = (project_root or Path(__file__).resolve().parents[1]).resolve()
    path = catalog_path or root / "catalog.json"
    try:
        catalog = load_catalog(path)
        if args.command == "test":
            tests = select_test(catalog, args.test_id)
            parameters = {args.test_id: parse_cli_parameters(args.param)}
            plan = build_plan(
                tests,
                parameters,
                root,
                selection_kind="test",
                selection_id=args.test_id,
                cli_source=True,
            )
        elif args.command == "suite":
            tests = select_suite(catalog, args.suite_id)
            raw_parameters = load_suite_parameters(args.params_file)
            parameters = parameters_for_suite(tests, raw_parameters)
            plan = build_plan(
                tests,
                parameters,
                root,
                selection_kind="suite",
                selection_id=args.suite_id,
                cli_source=False,
            )
        else:
            milestone = load_project_milestone(
                root,
                args.milestone_id,
                milestones_root=milestones_root,
            )
            plan = build_milestone_plan(catalog, milestone, root)
    except GateError as exc:
        print(f"ERROR: gate: {exc}", file=sys.stderr)
        return 2
    return _execute(plan)
