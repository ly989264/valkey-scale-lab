from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from valkey_scale_lab import __version__
from valkey_scale_lab.analysis import AnalysisError, create_analysis_summary
from valkey_scale_lab.config.validation import emit_schema_report, validate_config_file
from valkey_scale_lab.fault.sandbox import FaultError, apply_fault, clear_fault
from valkey_scale_lab.planner.plan import PlannerError, create_plan_file
from valkey_scale_lab.report import ReportError, render_report
from valkey_scale_lab.runtime.docker_runtime import DockerRuntimeError, cleanup_scenario, create_scenario


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


def _gate_scenario(args: argparse.Namespace) -> int:
    try:
        create_scenario(
            phase=args.phase,
            scenario=args.scenario,
            config_path=args.config,
            artifacts_dir=args.artifacts_dir,
            state_out=args.state_out,
        )
    except DockerRuntimeError as exc:
        print(f"ERROR: gate scenario: {exc}", file=sys.stderr)
        return 1
    return 0


def _gate_cleanup(args: argparse.Namespace) -> int:
    try:
        report = cleanup_scenario(state_path=args.state, artifacts_dir=args.artifacts_dir, out_path=args.out)
    except (DockerRuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: gate cleanup: {exc}", file=sys.stderr)
        return 1
    return 0 if report["status"] == "PASS" else 1


def _fault_apply(args: argparse.Namespace) -> int:
    try:
        apply_fault(
            state_path=args.state,
            target_logical_id=args.target_logical_id,
            fault_json=args.fault_json,
            out_path=args.out,
        )
    except FaultError as exc:
        print(f"ERROR: fault apply: {exc}", file=sys.stderr)
        return 1
    return 0


def _fault_clear(args: argparse.Namespace) -> int:
    try:
        clear_fault(state_path=args.state, fault_id=args.fault_id, out_path=args.out)
    except FaultError as exc:
        print(f"ERROR: fault clear: {exc}", file=sys.stderr)
        return 1
    return 0


def _analyze(args: argparse.Namespace) -> int:
    try:
        create_analysis_summary(args.input, args.out)
    except AnalysisError as exc:
        print(f"ERROR: analyze: {exc}", file=sys.stderr)
        return 1
    return 0


def _report(args: argparse.Namespace) -> int:
    try:
        render_report(args.analysis, args.out_dir, args.index_out)
    except ReportError as exc:
        print(f"ERROR: report: {exc}", file=sys.stderr)
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
    scenario.set_defaults(func=_gate_scenario)
    cleanup = gate_sub.add_parser("cleanup", help="Cleanup a scenario from state.")
    cleanup.add_argument("--state", required=True)
    cleanup.add_argument("--artifacts-dir", required=True)
    cleanup.add_argument("--out", required=True)
    cleanup.set_defaults(func=_gate_cleanup)
    _add_unimplemented(gate, "gate")

    fault = sub.add_parser("fault", help="Apply and clear sandboxed faults.")
    fault_sub = fault.add_subparsers(dest="fault_command", metavar="<fault-command>")
    apply = fault_sub.add_parser("apply", help="Apply a sandboxed fault.")
    apply.add_argument("--state", required=True)
    apply.add_argument("--target-logical-id", required=True)
    apply.add_argument("--fault-json", required=True)
    apply.add_argument("--out", required=True)
    apply.set_defaults(func=_fault_apply)
    clear = fault_sub.add_parser("clear", help="Clear a sandboxed fault.")
    clear.add_argument("--state", required=True)
    clear.add_argument("--fault-id", required=True)
    clear.add_argument("--out", required=True)
    clear.set_defaults(func=_fault_clear)
    _add_unimplemented(fault, "fault")

    analyze = sub.add_parser("analyze", help="Analyze machine-readable artifacts.")
    analyze.add_argument("--input", required=True, help="Input artifact directory to analyze.")
    analyze.add_argument("--out", required=True)
    analyze.set_defaults(func=_analyze)

    report = sub.add_parser("report", help="Render reports from artifacts.")
    report.add_argument("--analysis", required=True, help="Path to analysis_summary.json.")
    report.add_argument("--out-dir", required=True, help="Directory for rendered reports.")
    report.add_argument("--index-out", required=True, help="Path for report_index.json.")
    report.set_defaults(func=_report)

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
