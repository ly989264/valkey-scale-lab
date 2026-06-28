from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from valkey_scale_lab import __version__
from valkey_scale_lab.config.validation import emit_schema_report, validate_config_file
from valkey_scale_lab.planner.plan import PlannerError, create_plan_file


UNIMPLEMENTED = (
    "This command is reserved by the valkey-scale-lab contract but is not "
    "implemented in P00_REPO_CONTRACT."
)


class ContractParser(argparse.ArgumentParser):
    """ArgumentParser that keeps command errors compact for gate logs."""


def _unimplemented(args: argparse.Namespace) -> int:
    command = getattr(args, "contract_command", "command")
    print(f"ERROR: {command}: {UNIMPLEMENTED}", file=sys.stderr)
    return 2


def _config_validate(args: argparse.Namespace) -> int:
    report = validate_config_file(args.config, args.out)
    return 0 if report["valid"] else 1


def _config_emit_schema(args: argparse.Namespace) -> int:
    emit_schema_report(args.out)
    return 0


def _plan(args: argparse.Namespace) -> int:
    try:
        create_plan_file(args.config, args.out, dry_run=args.dry_run)
    except PlannerError as exc:
        print(f"ERROR: plan: {exc}", file=sys.stderr)
        return 1
    return 0


def _add_unimplemented(parser: argparse.ArgumentParser, command: str) -> None:
    parser.set_defaults(func=_unimplemented, contract_command=command)


def build_parser() -> argparse.ArgumentParser:
    parser = ContractParser(
        prog="python3 -m valkey_scale_lab.cli",
        description=(
            "Valkey scale lab CLI. P00 exposes the command contract; later "
            "phases implement runtime behavior."
        ),
    )
    parser.add_argument("--version", action="version", version=f"valkey-scale-lab {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    config = sub.add_parser("config", help="Validate and emit run configuration artifacts.")
    config_sub = config.add_subparsers(dest="config_command", metavar="<config-command>")
    validate = config_sub.add_parser("validate", help="Validate a run config.")
    validate.add_argument("--config", required=True, help="Path to a run configuration file.")
    validate.add_argument("--out", required=True, help="Path for the validation report JSON.")
    validate.set_defaults(func=_config_validate)
    emit_schema = config_sub.add_parser("emit-schema", help="Emit the config schema report.")
    emit_schema.add_argument("--out", required=True, help="Path for the schema report JSON.")
    emit_schema.set_defaults(func=_config_emit_schema)
    _add_unimplemented(config, "config")

    plan = sub.add_parser("plan", help="Create a deterministic cluster plan.")
    plan.add_argument("--config", required=True, help="Path to a run configuration file.")
    plan.add_argument("--out", required=True, help="Path for cluster_plan.json.")
    plan.add_argument("--dry-run", action="store_true", help="Plan without starting processes.")
    plan.set_defaults(func=_plan)

    gate = sub.add_parser("gate", help="Run gate lifecycle scenarios.")
    gate_sub = gate.add_subparsers(dest="gate_command", metavar="<gate-command>")
    scenario = gate_sub.add_parser("scenario", help="Create a scenario and write state.")
    scenario.add_argument("--phase", required=True)
    scenario.add_argument("--scenario", required=True)
    scenario.add_argument("--config", required=True)
    scenario.add_argument("--artifacts-dir", required=True)
    scenario.add_argument("--state-out", required=True)
    _add_unimplemented(scenario, "gate scenario")
    cleanup = gate_sub.add_parser("cleanup", help="Cleanup a scenario from state.")
    cleanup.add_argument("--state", required=True)
    cleanup.add_argument("--artifacts-dir", required=True)
    cleanup.add_argument("--out", required=True)
    _add_unimplemented(cleanup, "gate cleanup")
    _add_unimplemented(gate, "gate")

    fault = sub.add_parser("fault", help="Apply and clear sandboxed faults.")
    fault_sub = fault.add_subparsers(dest="fault_command", metavar="<fault-command>")
    apply = fault_sub.add_parser("apply", help="Apply a sandboxed fault.")
    apply.add_argument("--state", required=True)
    apply.add_argument("--target-logical-id", required=True)
    apply.add_argument("--fault-json", required=True)
    apply.add_argument("--out", required=True)
    _add_unimplemented(apply, "fault apply")
    clear = fault_sub.add_parser("clear", help="Clear a sandboxed fault.")
    clear.add_argument("--state", required=True)
    clear.add_argument("--fault-id", required=True)
    clear.add_argument("--out", required=True)
    _add_unimplemented(clear, "fault clear")
    _add_unimplemented(fault, "fault")

    analyze = sub.add_parser("analyze", help="Analyze machine-readable artifacts.")
    analyze.add_argument("--artifacts-dir", required=True)
    analyze.add_argument("--out", required=True)
    _add_unimplemented(analyze, "analyze")

    report = sub.add_parser("report", help="Render reports from artifacts.")
    report.add_argument("--artifacts-dir", required=True)
    report.add_argument("--out", required=True)
    _add_unimplemented(report, "report")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
