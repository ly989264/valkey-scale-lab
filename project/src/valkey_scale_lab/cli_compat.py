from __future__ import annotations

from pathlib import Path
from typing import Any

from valkey_scale_lab.compat import resolve_phase_alias
from valkey_scale_lab.execution import SCENARIO_CAPABILITIES, resolve_profile
from valkey_scale_lab.analysis import summary as analysis_summary
from valkey_scale_lab.analysis import workload_impact
from valkey_scale_lab.config import validation as config_validation
from valkey_scale_lab.planner import plan as planner
from valkey_scale_lab.report import final as final_report
from valkey_scale_lab.report import render as summary_report
from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.runtime import teardown
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline


def validate_config_file(
    config_path: str | Path,
    out_path: str | Path,
    *,
    global_config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return config_validation.validate_config_file(
        config_path,
        out_path,
        global_config_path=global_config_path,
        cli_overrides=cli_overrides,
    )


def emit_schema_report(out_path: str | Path) -> dict[str, Any]:
    return config_validation.emit_schema_report(out_path)


def create_plan_file(
    config_path: str | Path,
    out_path: str | Path,
    dry_run: bool = False,
    *,
    capability_id: str | None = None,
    scenario: str | None = None,
    operator_opt_in: bool = False,
    cost_acknowledged: bool = False,
    global_config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "dry_run": dry_run,
        "global_config_path": global_config_path,
        "cli_overrides": cli_overrides,
    }
    if capability_id is not None:
        kwargs["capability_id"] = capability_id
    if scenario is not None:
        kwargs["scenario"] = scenario
    if operator_opt_in:
        kwargs["operator_opt_in"] = operator_opt_in
    if cost_acknowledged:
        kwargs["cost_acknowledged"] = cost_acknowledged
    return planner.create_plan_file(config_path, out_path, **kwargs)


def create_scenario(
    *,
    alias_id: str,
    scenario: str,
    config_path: str | Path,
    artifacts_dir: str | Path,
    state_out: str | Path,
    setup_timeline: SetupTimeline | None = None,
    global_config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
    operator_opt_in: bool = False,
    cost_acknowledged: bool = False,
) -> dict[str, Any]:
    alias = resolve_phase_alias(alias_id, scenario)
    profile = resolve_profile(
        alias.profile_id,
        requested_nodes=_configured_node_count(config_path),
    )
    return execute_scenario(
        capability_id=alias.capability_id,
        scenario_id=alias.scenario_id,
        backend_id=alias.backend_id,
        profile_id=profile.profile_id,
        requested_nodes=profile.requested_nodes,
        config_path=config_path,
        artifacts_dir=artifacts_dir,
        state_out=state_out,
        setup_timeline=setup_timeline,
        global_config_path=global_config_path,
        cli_overrides=cli_overrides,
        operator_opt_in=operator_opt_in,
        cost_acknowledged=cost_acknowledged,
    )


def execute_scenario(
    *,
    capability_id: str | None = None,
    scenario_id: str,
    backend_id: str,
    profile_id: str,
    requested_nodes: int,
    config_path: str | Path,
    artifacts_dir: str | Path,
    state_out: str | Path,
    setup_timeline: SetupTimeline | None = None,
    global_config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
    operator_opt_in: bool = False,
    cost_acknowledged: bool = False,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "capability_id": capability_id or SCENARIO_CAPABILITIES[scenario_id],
        "scenario_id": scenario_id,
        "backend_id": backend_id,
        "profile_id": profile_id,
        "requested_nodes": requested_nodes,
        "config_path": config_path,
        "artifacts_dir": artifacts_dir,
        "state_out": state_out,
        "setup_timeline": setup_timeline,
        "global_config_path": global_config_path,
        "cli_overrides": cli_overrides,
    }
    if requested_nodes > 200:
        kwargs["operator_opt_in"] = operator_opt_in
        kwargs["cost_acknowledged"] = cost_acknowledged
    return docker_runtime.execute_scenario(**kwargs)


def _configured_node_count(config_path: str | Path) -> int:
    config = docker_runtime.normalize_config(
        docker_runtime.parse_config_file(config_path)
    )
    cluster = config["cluster"]
    return int(cluster["shards"]) * (1 + int(cluster["replicas_per_shard"]))


def cleanup_scenario(
    *,
    state_path: str | Path,
    artifacts_dir: str | Path,
    out_path: str | Path,
) -> dict[str, Any]:
    return teardown.cleanup_scenario(
        state_path=state_path,
        artifacts_dir=artifacts_dir,
        out_path=out_path,
    )


def create_analysis_summary(
    input_dir: str | Path,
    out_path: str | Path,
) -> dict[str, Any]:
    return analysis_summary.create_analysis_summary(input_dir, out_path)


def build_workload_impact_analysis(
    source_root: str | Path,
    out_dir: str | Path,
    *,
    capability_id: str = workload_impact.CAPABILITY_ID,
    run_id: str = workload_impact.RUN_ID,
) -> dict[str, Any]:
    return workload_impact.build_workload_impact_analysis(
        source_root,
        out_dir,
        capability_id=capability_id,
        run_id=run_id,
    )


def render_report(
    analysis_path: str | Path,
    out_dir: str | Path,
    index_out: str | Path,
    *,
    lang: str = summary_report.DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    return summary_report.render_report(analysis_path, out_dir, index_out, lang=lang)


def build_final_report(
    input_dir: str | Path,
    out_dir: str | Path,
    capability_id: str = final_report.CAPABILITY_ID,
) -> dict[str, Any]:
    return final_report.build_final_report(
        input_dir,
        out_dir,
        capability_id=capability_id,
    )


def build_final_goal_loop_report(
    input_dir: str | Path,
    out_dir: str | Path,
    capability_id: str = final_report.CAPABILITY_ID,
) -> dict[str, Any]:
    """Compatibility alias for the former controller-named report entry point."""
    return build_final_report(input_dir, out_dir, capability_id=capability_id)


__all__ = [
    "build_final_report",
    "build_final_goal_loop_report",
    "build_workload_impact_analysis",
    "cleanup_scenario",
    "create_analysis_summary",
    "create_plan_file",
    "create_scenario",
    "execute_scenario",
    "emit_schema_report",
    "render_report",
    "validate_config_file",
]
