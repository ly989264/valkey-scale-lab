from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from valkey_scale_lab import __version__
from valkey_scale_lab.analysis import AnalysisError, WorkloadImpactError, build_workload_impact_analysis, create_analysis_summary
from valkey_scale_lab.artifacts import build_run_metadata, create_run_context, write_run_manifest, write_run_metadata
from valkey_scale_lab.config.validation import emit_schema_report, validate_config_file
from valkey_scale_lab.fault.sandbox import FaultError, apply_fault, clear_fault
from valkey_scale_lab.planner.plan import PlannerError, create_plan_file
from valkey_scale_lab.report import FinalReportError, ReportError, build_final_goal_loop_report, render_report
from valkey_scale_lab.resource import ResourcePreflightError, run_resource_preflight
from valkey_scale_lab.runtime.docker_runtime import DockerRuntimeError, cleanup_scenario, create_scenario
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline, build_setup_telemetry_artifact, write_setup_telemetry_artifact


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
    report = validate_config_file(args.config, args.out, global_config_path=args.global_config, cli_overrides=_nodehost_cli_overrides(args))
    return 0 if report["valid"] else 1


def _config_emit_schema(args: argparse.Namespace) -> int:
    emit_schema_report(args.out)
    return 0


def _plan(args: argparse.Namespace) -> int:
    try:
        create_plan_file(args.config, args.out, dry_run=args.dry_run, global_config_path=args.global_config, cli_overrides=_nodehost_cli_overrides(args))
    except PlannerError as exc:
        print(f"ERROR: plan: {exc}", file=sys.stderr)
        return 1
    return 0


def _gate_scenario(args: argparse.Namespace) -> int:
    setup_timeline = SetupTimeline()
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
            global_config_path=args.global_config,
            cli_overrides=_nodehost_cli_overrides(args),
        )
    except DockerRuntimeError as exc:
        print(f"ERROR: gate scenario: {exc}", file=sys.stderr)
        exit_code = 1
        error = str(exc)
    finally:
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
    emit_legacy_setup_timeline = args.phase == "P13_SCALE_LADDER_50_100"
    if isinstance(runtime, dict):
        if emit_legacy_setup_timeline:
            runtime["setup_timeline_path"] = timeline_path.as_posix()
        timings = runtime.get("timings")
        if emit_legacy_setup_timeline and isinstance(timings, list):
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
        if _state_has_nodes(state_obj):
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state_obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with setup_timeline.span("setup_return", "setup_lifecycle", {"exit_code": exit_code, "error": error or ""}):
        pass
    node_count = len(state_obj.get("nodes", [])) if isinstance(state_obj.get("nodes"), list) else 0
    run_id = str(state_obj.get("cluster_id") or f"phase-{args.phase}-{args.scenario}")
    if emit_legacy_setup_timeline:
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
    telemetry = build_setup_telemetry_artifact(
        phase_id=args.phase,
        run_id=run_id,
        scenario=args.scenario,
        status="PASS" if exit_code == 0 else "FAIL",
        node_count=node_count,
        segments=setup_timeline.segments,
        runtime_timings=runtime.get("timings", []) if isinstance(runtime, dict) else [],
        nodes=state_obj.get("nodes", []) if isinstance(state_obj.get("nodes"), list) else [],
        nodehosts=state_obj.get("nodehosts", []) if isinstance(state_obj.get("nodehosts"), list) else [],
        blocked_reason={
            "status": "SKIPPED_WITH_REASON" if exit_code == 0 else "MISSING",
            "reason": error or "Setup completed; cleanup timing is added by cleanup command.",
        },
    )
    telemetry_path = artifacts_dir / "setup_telemetry.json"
    write_setup_telemetry_artifact(telemetry_path, telemetry)
    if isinstance(runtime, dict):
        runtime["setup_telemetry_path"] = telemetry_path.as_posix()
        if _state_has_nodes(state_obj):
            state_path.write_text(json.dumps(state_obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _state_has_nodes(state_obj: dict[str, object]) -> bool:
    nodes = state_obj.get("nodes")
    return isinstance(nodes, list) and bool(nodes)


def _gate_cleanup(args: argparse.Namespace) -> int:
    try:
        report = cleanup_scenario(state_path=args.state, artifacts_dir=args.artifacts_dir, out_path=args.out)
        _refresh_setup_telemetry_cleanup(args, report)
    except (DockerRuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: gate cleanup: {exc}", file=sys.stderr)
        return 1
    return 0 if report["status"] == "PASS" else 1


def _refresh_setup_telemetry_cleanup(args: argparse.Namespace, cleanup_report: dict[str, object]) -> None:
    artifacts_dir = Path(args.artifacts_dir)
    telemetry_path = artifacts_dir / "setup_telemetry.json"
    if not telemetry_path.exists():
        return
    try:
        telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
        state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    refreshed = build_setup_telemetry_artifact(
        phase_id=str(telemetry.get("phase_id", state.get("phase_id", "MISSING"))),
        run_id=str(telemetry.get("run_id", state.get("cluster_id", "MISSING"))),
        scenario=str(telemetry.get("scenario", state.get("scenario", "MISSING"))),
        status=str(telemetry.get("status", cleanup_report.get("status", "MISSING"))),
        node_count=int(telemetry.get("node_count", len(state.get("nodes", []))) or 0),
        runtime_timings=state.get("runtime", {}).get("timings", []) if isinstance(state.get("runtime"), dict) else [],
        nodes=state.get("nodes", []) if isinstance(state.get("nodes"), list) else [],
        nodehosts=state.get("nodehosts", []) if isinstance(state.get("nodehosts"), list) else [],
        cleanup_report=dict(cleanup_report),
    )
    # Preserve setup metrics collected from the original in-process timeline; cleanup runs in a second process.
    if isinstance(telemetry.get("metrics"), dict):
        refreshed["metrics"].update({k: v for k, v in telemetry["metrics"].items() if k != "cleanup_ms"})
        refreshed["metrics"]["cleanup_ms"] = refreshed["cleanup"]["cleanup_ms"]
        old_missing = [item for item in telemetry.get("missing_metrics", []) if isinstance(item, dict) and item.get("metric") != "cleanup_ms"]
        cleanup_value = refreshed["metrics"].get("cleanup_ms")
        if isinstance(cleanup_value, dict):
            old_missing.append({"metric": "cleanup_ms", **cleanup_value})
        refreshed["missing_metrics"] = old_missing
    write_setup_telemetry_artifact(telemetry_path, refreshed)


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
        if args.kind == "final-goal-loop":
            if not args.input:
                print("ERROR: report: --input is required for final-goal-loop reports", file=sys.stderr)
                return 2
            build_final_goal_loop_report(args.input, args.out_dir, phase_id=args.phase)
        else:
            if not args.analysis or not args.index_out:
                print("ERROR: report: --analysis and --index-out are required for summary reports", file=sys.stderr)
                return 2
            render_report(args.analysis, args.out_dir, args.index_out)
    except (FinalReportError, ReportError) as exc:
        print(f"ERROR: report: {exc}", file=sys.stderr)
        return 1
    return 0


def _resource_preflight(args: argparse.Namespace) -> int:
    try:
        kwargs: dict[str, object] = {
            "dry_run": args.dry_run,
            "phase_id": args.phase,
            "scenario": args.scenario,
        }
        if args.global_config is not None:
            kwargs["global_config_path"] = args.global_config
        cli_overrides = _nodehost_cli_overrides(args)
        if cli_overrides is not None:
            kwargs["cli_overrides"] = cli_overrides
        report = run_resource_preflight(
            args.config,
            args.out,
            **kwargs,
        )
    except ResourcePreflightError as exc:
        print(f"ERROR: resource preflight: {exc}", file=sys.stderr)
        return 1
    return 0 if report["can_run"] else 1


def _run_init(args: argparse.Namespace) -> int:
    context = create_run_context(args.run_id, args.runs_root)
    metadata = build_run_metadata(
        context,
        config_path=args.config,
        runtime_provider=args.runtime_provider,
        runtime_mode=args.runtime_mode,
    )
    write_run_metadata(context, metadata)
    write_run_manifest(context, metadata=metadata, status=args.status)
    print(context.run_root.as_posix())
    return 0


def _nodehost_cli_overrides(args: argparse.Namespace) -> dict[str, object] | None:
    runtime: dict[str, object] = {}
    cluster: dict[str, object] = {}
    for attr in [
        "nodehost_strategy",
        "max_nodehosts",
        "nodehosts_per_az",
        "max_logical_nodes_per_nodehost",
        "nodehost_distribution",
    ]:
        if hasattr(args, attr):
            value = getattr(args, attr)
            if value is not None:
                runtime[attr] = value
    if hasattr(args, "server_profile") and args.server_profile is not None:
        runtime["server_profile"] = args.server_profile
    valkey: dict[str, object] = {}
    for attr in ["io_threads", "io_threads_auto", "io_threads_max_per_node", "io_threads_max_total", "log_format"]:
        if hasattr(args, attr):
            value = getattr(args, attr)
            if value is not None:
                valkey[attr] = value
    if valkey:
        runtime["valkey"] = valkey
    if hasattr(args, "cluster_node_timeout_ms") and args.cluster_node_timeout_ms is not None:
        cluster["cluster_node_timeout_ms"] = args.cluster_node_timeout_ms
    if hasattr(args, "cluster_node_timeout_profile") and args.cluster_node_timeout_profile is not None:
        cluster["cluster_node_timeout_profile"] = args.cluster_node_timeout_profile
    overrides: dict[str, object] = {}
    if runtime:
        overrides["runtime"] = runtime
    if cluster:
        overrides["cluster"] = cluster
    return overrides or None


def _add_nodehost_overrides(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--global-config", help="Path to repository-level global config override.")
    parser.add_argument("--server-profile", choices=["correctness", "one_b_dev", "one_b_perf"])
    parser.add_argument("--io-threads", type=int)
    parser.add_argument("--io-threads-auto", action="store_true", default=None)
    parser.add_argument("--io-threads-max-per-node", type=int)
    parser.add_argument("--io-threads-max-total", type=int)
    parser.add_argument("--log-format", choices=["text", "json"])
    parser.add_argument("--cluster-node-timeout-ms", type=int)
    parser.add_argument("--cluster-node-timeout-profile", choices=["correctness", "failover_rto", "management_safe"])
    parser.add_argument("--nodehost-strategy", choices=["density_limited"])
    parser.add_argument("--max-nodehosts", type=int)
    parser.add_argument("--nodehosts-per-az", type=int)
    parser.add_argument("--max-logical-nodes-per-nodehost", type=int)
    parser.add_argument("--nodehost-distribution", choices=["round_robin_by_az"])


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
    _add_nodehost_overrides(validate)
    validate.set_defaults(func=_config_validate)
    emit_schema = config_sub.add_parser("emit-schema", help="Emit the config schema report.")
    emit_schema.add_argument("--out", required=True, help="Path for the schema report JSON.")
    emit_schema.set_defaults(func=_config_emit_schema)
    _add_unimplemented(config, "config")

    plan = sub.add_parser("plan", help="Create a deterministic cluster plan.")
    plan.add_argument("--config", required=True, help="Path to a run configuration file.")
    plan.add_argument("--out", required=True, help="Path for cluster_plan.json.")
    plan.add_argument("--dry-run", action="store_true", help="Plan without starting processes.")
    _add_nodehost_overrides(plan)
    plan.set_defaults(func=_plan)

    gate = sub.add_parser("gate", help="Run gate lifecycle scenarios.")
    gate_sub = gate.add_subparsers(dest="gate_command", metavar="<gate-command>")
    scenario = gate_sub.add_parser("scenario", help="Create a scenario and write state.")
    scenario.add_argument("--phase", required=True)
    scenario.add_argument("--scenario", required=True)
    scenario.add_argument("--config", required=True)
    scenario.add_argument("--artifacts-dir", required=True)
    scenario.add_argument("--state-out", required=True)
    _add_nodehost_overrides(scenario)
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
    report.add_argument("--kind", choices=["summary", "final-goal-loop"], default="summary")
    report.add_argument("--analysis", help="Path to analysis_summary.json.")
    report.add_argument("--input", help="Input artifact phase directory for final-goal-loop reports.")
    report.add_argument("--out-dir", required=True, help="Directory for rendered reports.")
    report.add_argument("--index-out", help="Path for report_index.json.")
    report.add_argument("--phase", default="P26_FINAL_REPORT_REGRESSION")
    report.set_defaults(func=_report)

    resource = sub.add_parser("resource", help="Resource checks for scale rungs.")
    resource_sub = resource.add_subparsers(dest="resource_command", metavar="<resource-command>")
    preflight = resource_sub.add_parser("preflight", help="Run resource preflight for a scale config.")
    preflight.add_argument("--config", required=True)
    preflight.add_argument("--out", required=True)
    preflight.add_argument("--dry-run", action="store_true")
    preflight.add_argument("--phase")
    preflight.add_argument("--scenario")
    _add_nodehost_overrides(preflight)
    preflight.set_defaults(func=_resource_preflight)
    _add_unimplemented(resource, "resource")

    run = sub.add_parser("run", help="Create and inspect run-oriented artifact directories.")
    run_sub = run.add_subparsers(dest="run_command", metavar="<run-command>")
    init = run_sub.add_parser("init", help="Create runs/<run_id>/artifacts|logs|reports|state with metadata.")
    init.add_argument("--run-id", help="Deterministic run id. Generated from UTC time when omitted.")
    init.add_argument("--runs-root", default="runs", help="Root directory for run outputs.")
    init.add_argument("--config", help="Optional config path to hash into run metadata.")
    init.add_argument("--runtime-provider", default="local")
    init.add_argument("--runtime-mode", default="metadata-init")
    init.add_argument("--status", default="PASS", choices=["PASS", "FAIL", "PARTIAL", "MISSING", "SKIPPED_WITH_REASON", "BLOCKED_WITH_REASON"])
    init.set_defaults(func=_run_init)
    _add_unimplemented(run, "run")

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
