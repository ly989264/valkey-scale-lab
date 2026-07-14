from __future__ import annotations

from pathlib import Path
from typing import Any

from valkey_scale_lab.analysis import summary as analysis_summary
from valkey_scale_lab.analysis import workload_impact
from valkey_scale_lab.config import validation as config_validation
from valkey_scale_lab.fault import sandbox as fault_sandbox
from valkey_scale_lab.planner import plan as planner
from valkey_scale_lab.report import final as final_report
from valkey_scale_lab.report import render as summary_report
from valkey_scale_lab.runtime import docker_runtime
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
    global_config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return planner.create_plan_file(
        config_path,
        out_path,
        dry_run=dry_run,
        global_config_path=global_config_path,
        cli_overrides=cli_overrides,
    )


def create_scenario(
    *,
    phase: str,
    scenario: str,
    config_path: str | Path,
    artifacts_dir: str | Path,
    state_out: str | Path,
    setup_timeline: SetupTimeline | None = None,
    global_config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return docker_runtime.create_scenario(
        phase=phase,
        scenario=scenario,
        config_path=config_path,
        artifacts_dir=artifacts_dir,
        state_out=state_out,
        setup_timeline=setup_timeline,
        global_config_path=global_config_path,
        cli_overrides=cli_overrides,
    )


def cleanup_scenario(
    *,
    state_path: str | Path,
    artifacts_dir: str | Path,
    out_path: str | Path,
) -> dict[str, Any]:
    return docker_runtime.cleanup_scenario(
        state_path=state_path,
        artifacts_dir=artifacts_dir,
        out_path=out_path,
    )


def apply_fault(
    *,
    state_path: str | Path,
    target_logical_id: str,
    fault_json: str | Path,
    out_path: str | Path,
) -> dict[str, Any]:
    return fault_sandbox.apply_fault(
        state_path=state_path,
        target_logical_id=target_logical_id,
        fault_json=fault_json,
        out_path=out_path,
    )


def clear_fault(
    *,
    state_path: str | Path,
    fault_id: str,
    out_path: str | Path,
) -> dict[str, Any]:
    return fault_sandbox.clear_fault(
        state_path=state_path,
        fault_id=fault_id,
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
    phase_id: str = workload_impact.PHASE_ID,
    run_id: str = workload_impact.RUN_ID,
) -> dict[str, Any]:
    return workload_impact.build_workload_impact_analysis(
        source_root,
        out_dir,
        phase_id=phase_id,
        run_id=run_id,
    )


def render_report(
    analysis_path: str | Path,
    out_dir: str | Path,
    index_out: str | Path,
) -> dict[str, Any]:
    return summary_report.render_report(analysis_path, out_dir, index_out)


def build_final_goal_loop_report(
    input_dir: str | Path,
    out_dir: str | Path,
    phase_id: str = final_report.PHASE_ID,
) -> dict[str, Any]:
    return final_report.build_final_goal_loop_report(
        input_dir,
        out_dir,
        phase_id=phase_id,
    )


__all__ = [
    "apply_fault",
    "build_final_goal_loop_report",
    "build_workload_impact_analysis",
    "cleanup_scenario",
    "clear_fault",
    "create_analysis_summary",
    "create_plan_file",
    "create_scenario",
    "emit_schema_report",
    "render_report",
    "validate_config_file",
]
