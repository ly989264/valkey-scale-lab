from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from verification.catalog import GateError, load_catalog
from verification.planning import (
    build_plan,
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
        description="Run registered project tests through verification/catalog.json.",
    )
    commands = parser.add_subparsers(dest="command", metavar="<command>", required=True)
    commands.add_parser("help", help="Show Gate commands and parameter rules.")
    test = commands.add_parser("test", help="Run one registered Test.")
    test.add_argument("test_id", metavar="<test-id>")
    test.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    suite = commands.add_parser("suite", help="Run every Test in a registered Suite.")
    suite.add_argument("suite_id", metavar="<suite-id>")
    suite.add_argument("--params-file", type=Path, metavar="PATH")
    return parser


def _help(parser: argparse.ArgumentParser) -> None:
    parser.print_help()
    print(
        "\nCommands:\n"
        "  ./gate help\n"
        "  ./gate test <test-id> [--param NAME=VALUE ...]\n"
        "  ./gate suite <suite-id> [--params-file PATH]\n\n"
        "Examples:\n"
        "  ./gate test <test-id>\n"
        "  ./gate test <test-id> --param name=value\n"
        "  ./gate suite <suite-id>\n"
        "  ./gate suite <suite-id> --params-file suite-params.json\n\n"
        "Parameter sources are exclusive: test uses --param; suite uses --params-file."
    )


def _color(status: str, enabled: bool) -> str:
    if not enabled:
        return status
    code = {
        "PASS": "32",
        "FAIL": "31",
        "ERROR": "35",
        "TIMEOUT": "33",
        "RUN": "36",
    }.get(status)
    return status if code is None else f"\033[{code}m{status}\033[0m"


def _write_summary(plan, results: Sequence[TestResult]) -> None:
    payload = {
        "schema_version": "gate-summary-v1",
        "invocation_id": plan.invocation_id,
        "selection": {"kind": plan.selection_kind, "id": plan.selection_id},
        "status": "PASS" if all(result.status == "PASS" for result in results) else "FAIL",
        "tests": [
            {
                "test_id": result.test_id,
                "status": result.status,
                "duration_seconds": round(result.duration_seconds, 3),
                "detail": result.detail,
                "exit_code": result.exit_code,
                "counts": result.counts,
                "artifacts_dir": str(result.artifacts_dir),
            }
            for result in results
        ],
    }
    plan.artifacts_dir.mkdir(parents=True, exist_ok=True)
    (plan.artifacts_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _print_summary(plan, results: Sequence[TestResult], colors: bool) -> None:
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
        min(72, max(len(headers[index]), *(len(row[index]) for row in rows)))
        for index in range(len(headers))
    ]
    plain_header = "  ".join(
        headers[index].ljust(widths[index]) for index in range(len(headers))
    )
    print(plain_header)
    print("  ".join("-" * width for width in widths))
    for row in rows:
        values = list(row)
        status = values[1]
        values[1] = _color(status, colors)
        print(
            "  ".join(
                values[index].ljust(widths[index] + (len(values[1]) - len(status) if index == 1 else 0))
                for index in range(len(headers))
            )
        )
    passed = sum(result.status == "PASS" for result in results)
    print(f"\n{passed}/{len(results)} passed")
    print(f"Artifacts: {plan.artifacts_dir}")


def _execute(plan) -> int:
    colors = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    print("Verification Gate")
    print(f"Run: {plan.invocation_id}")
    print(f"Selected: {plan.selection_kind} {plan.selection_id} ({len(plan.tests)} tests)\n")
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
    _write_summary(plan, results)
    _print_summary(plan, results, colors)
    return 0 if all(result.status == "PASS" for result in results) else 1


def main(
    argv: Sequence[str] | None = None,
    *,
    project_root: Path | None = None,
    catalog_path: Path | None = None,
) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "help":
        _help(parser)
        return 0
    root = (project_root or Path(__file__).resolve().parents[1]).resolve()
    path = catalog_path or root / "verification" / "catalog.json"
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
        else:
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
    except GateError as exc:
        print(f"ERROR: gate: {exc}", file=sys.stderr)
        return 2
    return _execute(plan)
