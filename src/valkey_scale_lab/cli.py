from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from valkey_scale_lab import __version__
from valkey_scale_lab.analysis import AnalysisError, WorkloadImpactError, build_workload_impact_analysis, create_analysis_summary
from valkey_scale_lab.config.validation import emit_schema_report, validate_config_file
from valkey_scale_lab.fault.sandbox import FaultError, apply_fault, clear_fault
from valkey_scale_lab.planner.plan import PlannerError, create_plan_file
from valkey_scale_lab.report import ReportError, render_report
from valkey_scale_lab.resource import ResourcePreflightError, run_resource_preflight
from valkey_scale_lab.runtime.docker_runtime import DockerRuntimeError, cleanup_scenario, create_scenario
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline


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
    setup_timeline = SetupTimeline() if args.phase == "P13_SCALE_LADDER_50_100" else None
    state: dict[str, object] = {}
    exit_code = 0
    error: str | None = None
    try:
        state = create_scenario(
            phase=args.phase,
            scenario=args.scenario,
            config_path=args.config,
            artifacts_dir=args.artifacts_dir,
            state_out=args.state_out,
            setup_timeline=setup_timeline,
        )
    except DockerRuntimeError as exc:
        print(f"ERROR: gate scenario: {exc}", file=sys.stderr)
        exit_code = 1
        error = str(exc)
    finally:
        if setup_timeline is not None:
            _finalize_setup_timeline(args, setup_timeline, state, exit_code=exit_code, error=error)
    return exit_code


def _finalize_setup_timeline(
    args: argparse.Namespace,
    setup_timeline: SetupTimeline,
    state: dict[str, object],
    *,
    exit_code: int,
    error: str | None,
) -> None:
    artifacts_dir = Path(args.artifacts_dir)
    timeline_path = artifacts_dir / f"setup_timeline_{args.scenario}.json"
    state_path = Path(args.state_out)
    state_obj = dict(state)
    if state_path.exists():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state_obj = loaded
        except (OSError, json.JSONDecodeError):
            pass
    runtime = state_obj.setdefault("runtime", {})
    if isinstance(runtime, dict):
        runtime["setup_timeline_path"] = timeline_path.as_posix()
        timings = runtime.get("timings")
        if isinstance(timings, list):
            for entry in timings:
                if isinstance(entry, dict) and entry.get("name") == "nodehost_start":
                    details = entry.setdefault("details", {})
                    if isinstance(details, dict):
                        details["setup_timeline_path"] = timeline_path.as_posix()
                    break
    with setup_timeline.span(
        "state_write_setup_timeline_reference",
        "state_write",
        {"path": state_path.as_posix(), "setup_timeline_path": timeline_path.as_posix()},
    ):
        if state_obj:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state_obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with setup_timeline.span("setup_return", "setup_lifecycle", {"exit_code": exit_code, "error": error or ""}):
        pass
    node_count = len(state_obj.get("nodes", [])) if isinstance(state_obj.get("nodes"), list) else 0
    run_id = str(state_obj.get("cluster_id") or f"phase-{args.phase}-{args.scenario}")
    setup_timeline.write_artifact(
        timeline_path,
        phase_id=args.phase,
        run_id=run_id,
        scenario=args.scenario,
        node_count=node_count,
        status="PASS" if exit_code == 0 else "FAIL",
        extra={
            "setup_command_wall_source": {
                "status": "MISSING",
                "reason": "outer wrapper attaches setup_command_wall_seconds during P13O validation",
            }
        },
    )


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
        if args.kind == "workload-impact":
            if not args.out_dir:
                print("ERROR: analyze: --out-dir is required for workload-impact analysis", file=sys.stderr)
                return 2
            build_workload_impact_analysis(args.input, args.out_dir, phase_id=args.phase)
        else:
            if not args.out:
                print("ERROR: analyze: --out is required for summary analysis", file=sys.stderr)
                return 2
            create_analysis_summary(args.input, args.out)
    except (AnalysisError, WorkloadImpactError) as exc:
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


def _resource_preflight(args: argparse.Namespace) -> int:
    try:
        report = run_resource_preflight(args.config, args.out, dry_run=args.dry_run)
    except ResourcePreflightError as exc:
        print(f"ERROR: resource preflight: {exc}", file=sys.stderr)
        return 1
    return 0 if report["can_run"] else 1


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
    analyze.add_argument("--kind", choices=["summary", "workload-impact"], default="summary")
    analyze.add_argument("--input", required=True, help="Input artifact directory to analyze.")
    analyze.add_argument("--out")
    analyze.add_argument("--out-dir")
    analyze.add_argument("--phase", default="P25_FAULT_WORKLOAD_IMPACT_ANALYSIS")
    analyze.set_defaults(func=_analyze)

    report = sub.add_parser("report", help="Render reports from artifacts.")
    report.add_argument("--analysis", required=True, help="Path to analysis_summary.json.")
    report.add_argument("--out-dir", required=True, help="Directory for rendered reports.")
    report.add_argument("--index-out", required=True, help="Path for report_index.json.")
    report.set_defaults(func=_report)

    resource = sub.add_parser("resource", help="Resource checks for scale rungs.")
    resource_sub = resource.add_subparsers(dest="resource_command", metavar="<resource-command>")
    preflight = resource_sub.add_parser("preflight", help="Run resource preflight for a scale config.")
    preflight.add_argument("--config", required=True)
    preflight.add_argument("--out", required=True)
    preflight.add_argument("--dry-run", action="store_true")
    preflight.set_defaults(func=_resource_preflight)
    _add_unimplemented(resource, "resource")

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
