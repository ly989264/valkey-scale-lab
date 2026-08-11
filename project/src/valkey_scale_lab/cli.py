from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from valkey_scale_lab import __version__
from valkey_scale_lab import cli_compat
from valkey_scale_lab.analysis import AnalysisError, WorkloadImpactError, build_workload_impact_analysis, create_analysis_summary
from valkey_scale_lab.artifacts import build_run_metadata, create_run_context, write_run_manifest, write_run_metadata
from valkey_scale_lab.config.validation import emit_schema_report, validate_config_file
from valkey_scale_lab.compat import resolve_capability_alias, resolve_phase_alias
from valkey_scale_lab.execution import (
    BACKENDS,
    PROFILES,
    ExecutionSelectionError,
    resolve_profile,
)
from valkey_scale_lab.gates.real import product_tree_digest, run_exact_gate
from valkey_scale_lab.observability.contracts import CollectionError
from valkey_scale_lab.planner.plan import PlannerError, create_plan_file
from valkey_scale_lab.report import FinalReportError, ReportError, render_report
from valkey_scale_lab.resource import ResourcePreflightError, run_resource_preflight
from valkey_scale_lab.runtime.command_recorder import CommandRecorder, command_recorder_context
from valkey_scale_lab.runtime.docker_runtime import DockerRuntimeError, execute_scenario
from valkey_scale_lab.runtime.teardown import TeardownError, cleanup_scenario
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline, build_setup_telemetry_artifact, write_setup_telemetry_artifact
from valkey_scale_lab.scenarios import ScenarioDefinitionError, load_scenario_definition


UNIMPLEMENTED = (
    "This command is reserved by the valkey-scale-lab contract but is not "
    "implemented in repository_contract."
)


class ContractParser(argparse.ArgumentParser):
    """ArgumentParser that keeps command errors compact for gate logs."""


def _unimplemented(args: argparse.Namespace) -> int:
    command = getattr(args, "contract_command", "command")
    print(f"ERROR: {command}: {UNIMPLEMENTED}", file=sys.stderr)
    return 2


def _config_validate(args: argparse.Namespace) -> int:
    report = cli_compat.validate_config_file(args.config, args.out, global_config_path=args.global_config, cli_overrides=_nodehost_cli_overrides(args))
    return 0 if report["valid"] else 1


def _config_emit_schema(args: argparse.Namespace) -> int:
    cli_compat.emit_schema_report(args.out)
    return 0


def _plan(args: argparse.Namespace) -> int:
    try:
        kwargs: dict[str, object] = {
            "dry_run": args.dry_run,
            "global_config_path": args.global_config,
            "cli_overrides": _nodehost_cli_overrides(args),
        }
        if args.capability_id is not None:
            kwargs["capability_id"] = args.capability_id
        if args.scenario is not None:
            kwargs["scenario"] = args.scenario
        if args.operator_opt_in:
            kwargs["operator_opt_in"] = args.operator_opt_in
        if args.cost_acknowledged:
            kwargs["cost_acknowledged"] = args.cost_acknowledged
        cli_compat.create_plan_file(
            args.config,
            args.out,
            **kwargs,
        )
    except PlannerError as exc:
        print(f"ERROR: plan: {exc}", file=sys.stderr)
        return 1
    return 0


def _gate_scenario(args: argparse.Namespace) -> int:
    setup_timeline = SetupTimeline()
    state: dict[str, object] = {}
    exit_code = 0
    error: str | None = None
    legacy_alias = bool(args.legacy_alias_id)
    try:
        alias = (
            resolve_phase_alias(args.legacy_alias_id, args.scenario)
            if legacy_alias
            else None
        )
        profile = None if legacy_alias else resolve_profile(
            args.profile,
            requested_nodes=args.nodes or PROFILES[args.profile].requested_nodes,
        )
    except (ExecutionSelectionError, ValueError) as exc:
        print(f"ERROR: gate scenario: {exc}", file=sys.stderr)
        return 1
    scenario_id = alias.scenario_id if alias else args.scenario
    capability_id = alias.capability_id if alias else scenario_id
    state = {
        "capability_id": capability_id,
        "scenario_id": scenario_id,
        "backend_id": alias.backend_id if alias else args.backend,
        "profile_id": alias.profile_id if alias else profile.profile_id,
    }
    run_id = args.run_id or f"run-{capability_id}-{scenario_id}"
    if legacy_alias and not args.config:
        print("ERROR: gate scenario: compatibility aliases require --config", file=sys.stderr)
        return 2
    config_path = args.config if args.config else profile.config_template
    recorder = CommandRecorder(capability_id=capability_id, run_id=run_id, scenario=scenario_id, artifacts_dir=args.artifacts_dir)
    try:
        with command_recorder_context(recorder):
            common = {
                "config_path": config_path,
                "artifacts_dir": args.artifacts_dir,
                "state_out": args.state_out,
                "setup_timeline": setup_timeline,
                "global_config_path": args.global_config,
                "cli_overrides": _nodehost_cli_overrides(args),
            }
            if legacy_alias:
                state = cli_compat.create_scenario(
                    alias_id=args.legacy_alias_id,
                    scenario=args.scenario,
                    **common,
                )
            else:
                opt_in_kwargs = (
                    {
                        "operator_opt_in": args.operator_opt_in,
                        "cost_acknowledged": args.cost_acknowledged,
                    }
                    if profile.requested_nodes > 200
                    else {}
                )
                state = cli_compat.execute_scenario(
                    scenario_id=scenario_id,
                    backend_id=args.backend,
                    profile_id=profile.profile_id,
                    requested_nodes=profile.requested_nodes,
                    **common,
                    **opt_in_kwargs,
                )
        run_id = str(state.get("cluster_id") or run_id)
        recorder.run_id = run_id
        _attach_command_audit_refs(state, args.artifacts_dir)
    except (DockerRuntimeError, ExecutionSelectionError, ValueError) as exc:
        print(f"ERROR: gate scenario: {exc}", file=sys.stderr)
        exit_code = 1
        error = str(exc)
    finally:
        recorder.close(status="PASS" if exit_code == 0 else "FAIL")
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
    capability_id = str(state_obj.get("capability_id") or args.scenario)
    scenario_id = str(
        state_obj.get("scenario_id") or state_obj.get("scenario") or args.scenario
    )
    timeline_path = artifacts_dir / f"setup_timeline_{scenario_id}.json"
    emit_setup_timeline = True
    if isinstance(runtime, dict):
        if emit_setup_timeline:
            runtime["setup_timeline_path"] = timeline_path.as_posix()
        timings = runtime.get("timings")
        if emit_setup_timeline and isinstance(timings, list):
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
    run_id = str(state_obj.get("cluster_id") or f"run-{capability_id}-{scenario_id}")
    profile_id = str(
        runtime.get("profile_id", args.profile)
        if isinstance(runtime, dict)
        else args.profile
    )
    if emit_setup_timeline:
        setup_timeline.write_artifact(
            timeline_path,
            capability_id=capability_id,
            run_id=run_id,
            scenario=scenario_id,
            profile_id=profile_id,
            node_count=node_count,
            status="PASS" if exit_code == 0 else "FAIL",
            extra={
                "setup_command_wall_source": {
                    "status": "MISSING",
                    "reason": "outer wrapper attaches setup_command_wall_seconds during setup timing validation",
                }
            },
        )
    telemetry = build_setup_telemetry_artifact(
        capability_id=capability_id,
        run_id=run_id,
        scenario=scenario_id,
        profile_id=profile_id,
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


def _attach_command_audit_refs(state: dict[str, object], artifacts_dir: str | Path) -> None:
    runtime = state.setdefault("runtime", {})
    if not isinstance(runtime, dict):
        return
    artifacts = Path(artifacts_dir)
    runtime["command_log_ref"] = (artifacts / "command_log.jsonl").as_posix()
    runtime["command_audit_summary_ref"] = (artifacts / "command_audit_summary.json").as_posix()


def _load_json_if_present(path: str | Path) -> dict[str, object]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _gate_cleanup(args: argparse.Namespace) -> int:
    try:
        state = _load_json_if_present(args.state)
        capability_id = str(state.get("capability_id", "cluster_lifecycle")) if isinstance(state, dict) else "cluster_lifecycle"
        scenario = str(
            state.get("scenario_id")
            or state.get("scenario")
            or state.get("capability_id")
            or "cluster_lifecycle"
        ) if isinstance(state, dict) else "cluster_lifecycle"
        run_id = str(state.get("cluster_id") or state.get("runtime", {}).get("run_id") or f"run-{capability_id}-{scenario}") if isinstance(state, dict) else f"run-{capability_id}-{scenario}"
        recorder = CommandRecorder(capability_id=capability_id, run_id=run_id, scenario=scenario, artifacts_dir=args.artifacts_dir, append=True)
        with command_recorder_context(recorder):
            report = cli_compat.cleanup_scenario(state_path=args.state, artifacts_dir=args.artifacts_dir, out_path=args.out)
        summary = recorder.close(status="PASS" if report.get("status") == "PASS" else "FAIL")
        report["command_log_ref"] = summary["command_log_ref"]
        report["command_audit_summary_ref"] = str(Path(args.artifacts_dir, "command_audit_summary.json"))
        Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _refresh_setup_telemetry_cleanup(args, report)
    except (DockerRuntimeError, TeardownError, OSError, ValueError, json.JSONDecodeError) as exc:
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
        capability_id=str(telemetry.get("capability_id", state.get("capability_id", "MISSING"))),
        run_id=str(telemetry.get("run_id", state.get("cluster_id", "MISSING"))),
        scenario=str(telemetry.get("scenario", state.get("scenario", "MISSING"))),
        profile_id=str(
            telemetry.get(
                "profile_id",
                state.get("runtime", {}).get("profile_id", "MISSING"),
            )
        ),
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


def _analyze(args: argparse.Namespace) -> int:
    try:
        capability_id = (
            resolve_capability_alias(args.legacy_capability_alias)
            if args.legacy_capability_alias
            else args.capability_id
        )
        if args.kind == "workload-impact":
            if not args.out_dir:
                print("ERROR: analyze: --out-dir is required for workload-impact analysis", file=sys.stderr)
                return 2
            cli_compat.build_workload_impact_analysis(args.input, args.out_dir, capability_id=capability_id)
        else:
            if not args.out:
                print("ERROR: analyze: --out is required for summary analysis", file=sys.stderr)
                return 2
            cli_compat.create_analysis_summary(args.input, args.out)
    except (AnalysisError, WorkloadImpactError, ValueError) as exc:
        print(f"ERROR: analyze: {exc}", file=sys.stderr)
        return 1
    return 0


def _report(args: argparse.Namespace) -> int:
    try:
        capability_id = (
            resolve_capability_alias(args.legacy_capability_alias)
            if args.legacy_capability_alias
            else args.capability_id
        )
        if args.kind == "final-report":
            if not args.input:
                print("ERROR: report: --input is required for final reports", file=sys.stderr)
                return 2
            cli_compat.build_final_report(args.input, args.out_dir, capability_id=capability_id)
        else:
            if not args.analysis or not args.index_out:
                print("ERROR: report: --analysis and --index-out are required for summary reports", file=sys.stderr)
                return 2
            cli_compat.render_report(args.analysis, args.out_dir, args.index_out)
    except (FinalReportError, ReportError, ValueError) as exc:
        print(f"ERROR: report: {exc}", file=sys.stderr)
        return 1
    return 0


def _resource_preflight(args: argparse.Namespace) -> int:
    try:
        capability_id = (
            resolve_capability_alias(args.legacy_capability_alias)
            if args.legacy_capability_alias
            else args.capability_id
        )
        kwargs: dict[str, object] = {
            "dry_run": args.dry_run,
            "capability_id": capability_id,
            "scenario": args.scenario,
        }
        if args.operator_opt_in:
            kwargs["operator_opt_in"] = args.operator_opt_in
        if args.cost_acknowledged:
            kwargs["cost_acknowledged"] = args.cost_acknowledged
        if args.profile is not None:
            kwargs["profile_id"] = args.profile
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
    except (ResourcePreflightError, ValueError) as exc:
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


def _write_gate_execute_result(path: str, status: str, summary: str) -> None:
    """Emit the run's own verdict where the Gate reads it.

    `real.local.full-flow` declares `result: json`, so this file - not the exit
    code - is what the run says about itself. The exit code stays 0 whenever the
    verdict was written, because a non-zero exit makes the Gate report FAIL
    without reading the file, which is precisely the collapse this route exists
    to remove.
    """

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"status": status, "summary": summary}, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _gate_execute(args: argparse.Namespace) -> int:
    try:
        definition = load_scenario_definition(args.definition)
        run_exact_gate(
            definition=definition,
            scale=args.nodes,
            config_path=args.config,
            evidence_dir=args.artifacts_dir,
            run_id=args.run_id,
            ownership_id=args.ownership_id,
            provenance_id=args.provenance_id,
            product_digest=args.product_digest or product_tree_digest(),
            backend_id=args.backend,
            profile_id=args.profile,
            prior_admission_digest=args.prior_admission_digest,
            operator_opt_in=args.operator_opt_in,
            cost_acknowledged=args.cost_acknowledged,
        )
    except CollectionError as exc:
        # §12.1: the collector itself could not complete. §12.2 makes that the
        # run's result when no check confirmed a failure, and it is reported as
        # itself rather than as a failure of the cluster.
        print(f"ERROR: gate execute could not complete: {exc}", file=sys.stderr)
        status, summary = "ERROR", f"gate execute could not complete: {exc}"
    except (
        DockerRuntimeError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        ScenarioDefinitionError,
    ) as exc:
        print(f"ERROR: gate execute: {exc}", file=sys.stderr)
        status, summary = "FAIL", f"gate execute: {exc}"
    else:
        status, summary = "PASS", f"exact-{args.nodes} full flow admitted"
    if args.result_path is None:
        # No result file to carry the verdict, so the exit code is all there is
        # and it can only say "not PASS".
        return 0 if status == "PASS" else 1
    _write_gate_execute_result(args.result_path, status, summary)
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
            "Valkey scale lab CLI with explicit scenario, backend, and profile axes."
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
    plan.add_argument("--capability-id")
    plan.add_argument("--scenario")
    plan.add_argument("--operator-opt-in", action="store_true")
    plan.add_argument("--cost-acknowledged", action="store_true")
    _add_nodehost_overrides(plan)
    plan.set_defaults(func=_plan)

    gate = sub.add_parser("gate", help="Run gate lifecycle scenarios.")
    gate_sub = gate.add_subparsers(dest="gate_command", metavar="<gate-command>")
    scenario = gate_sub.add_parser("scenario", help="Create a scenario and write state.")
    scenario.add_argument("--scenario", default="local_full_flow")
    scenario.add_argument("--backend", choices=["fake", "docker_container", "docker_process"], default="docker_process")
    scenario.add_argument("--profile", choices=sorted(PROFILES), default="exact-50")
    scenario.add_argument("--nodes", type=int)
    scenario.add_argument("--config")
    scenario.add_argument("--run-id")
    scenario.add_argument("--phase", dest="legacy_alias_id", help=argparse.SUPPRESS)
    scenario.add_argument("--artifacts-dir", required=True)
    scenario.add_argument("--state-out", required=True)
    scenario.add_argument("--operator-opt-in", action="store_true")
    scenario.add_argument("--cost-acknowledged", action="store_true")
    _add_nodehost_overrides(scenario)
    scenario.set_defaults(func=_gate_scenario)
    cleanup = gate_sub.add_parser("cleanup", help="Cleanup a scenario from state.")
    cleanup.add_argument("--state", required=True)
    cleanup.add_argument("--artifacts-dir", required=True)
    cleanup.add_argument("--out", required=True)
    cleanup.set_defaults(func=_gate_cleanup)
    execute = gate_sub.add_parser(
        "execute",
        help="Execute an exact-scale full-flow definition and emit raw evidence.",
    )
    execute.add_argument("--definition", required=True)
    execute.add_argument("--nodes", required=True, type=int)
    execute.add_argument("--config", required=True)
    # No default: the backend comes from the configuration's runtime.provider,
    # so that a native configuration cannot silently run on Docker. Naming one
    # here still works and is refused if it contradicts the configuration.
    execute.add_argument(
        "--backend", choices=sorted(BACKENDS), default=None,
        help="override the backend the configuration's runtime.provider implies",
    )
    execute.add_argument("--profile", choices=["exact-50", "exact-100", "exact-200", "exact-2000"])
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--ownership-id", required=True)
    execute.add_argument("--provenance-id", required=True)
    execute.add_argument("--artifacts-dir", required=True)
    execute.add_argument("--result-path")
    execute.add_argument("--product-digest")
    execute.add_argument("--prior-admission-digest")
    execute.add_argument("--operator-opt-in", action="store_true")
    execute.add_argument("--cost-acknowledged", action="store_true")
    execute.set_defaults(func=_gate_execute)
    _add_unimplemented(gate, "gate")

    analyze = sub.add_parser("analyze", help="Analyze machine-readable artifacts.")
    analyze.add_argument("--kind", choices=["summary", "workload-impact"], default="summary")
    analyze.add_argument("--input", required=True, help="Input artifact directory to analyze.")
    analyze.add_argument("--out")
    analyze.add_argument("--out-dir")
    analyze.add_argument("--capability-id", default="fault_workload_impact")
    analyze.add_argument("--phase", dest="legacy_capability_alias", help=argparse.SUPPRESS)
    analyze.set_defaults(func=_analyze)

    report = sub.add_parser("report", help="Render reports from artifacts.")
    report.add_argument("--kind", choices=["summary", "final-report"], default="summary")
    report.add_argument("--analysis", help="Path to analysis_summary.json.")
    report.add_argument("--input", help="Input artifact capture directory for final reports.")
    report.add_argument("--out-dir", required=True, help="Directory for rendered reports.")
    report.add_argument("--index-out", help="Path for report_index.json.")
    report.add_argument("--capability-id", default="final_report")
    report.add_argument("--phase", dest="legacy_capability_alias", help=argparse.SUPPRESS)
    report.set_defaults(func=_report)

    resource = sub.add_parser("resource", help="Resource checks for scale rungs.")
    resource_sub = resource.add_subparsers(dest="resource_command", metavar="<resource-command>")
    preflight = resource_sub.add_parser("preflight", help="Run resource preflight for a scale config.")
    preflight.add_argument("--config", required=True)
    preflight.add_argument("--out", required=True)
    preflight.add_argument("--dry-run", action="store_true")
    preflight.add_argument("--capability-id")
    preflight.add_argument("--phase", dest="legacy_capability_alias", help=argparse.SUPPRESS)
    preflight.add_argument("--scenario")
    preflight.add_argument("--profile", choices=sorted(PROFILES))
    preflight.add_argument("--operator-opt-in", action="store_true")
    preflight.add_argument("--cost-acknowledged", action="store_true")
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
