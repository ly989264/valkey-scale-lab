from __future__ import annotations

import re

from scripts import meta_m1_evidence_gate_v9 as legacy_evaluator
from valkey_scale_lab import milestone1_gate as legacy_gate
from valkey_scale_lab.runtime import docker_runtime as legacy_runtime
from valkey_scale_lab.scenarios import compile_gate_plan, load_milestone1_definition


EXPECTED_ARTIFACT_MAPPING = {
    ("run_state.json", "run_metadata", None),
    ("resource_preflight.json", "resource_preflight", None),
    ("workload_windows.json", "workload_windows", None),
    ("lifecycle_timeline.json", "lifecycle_timeline", None),
    ("scenario_results.json", "scenario_results", None),
    ("management_sequence.json", "management_results", None),
    ("fault_sequence.json", "fault_results", None),
    ("fault_sequence.json", "stability_results", "recovery_health"),
    ("cleanup_report.json", "cleanup_report", None),
    ("analysis_summary.json", "analysis_summary", None),
    ("report_index.json", "report_index", None),
    ("full_flow_result.json", None, None),
    ("management_command_log.jsonl", "command_log", None),
    ("fault_command_log.jsonl", "fault_command_log", None),
    ("events.jsonl", "events", None),
    ("metrics_timeseries.jsonl", "metrics", None),
}

EXPECTED_FAULT_HANDLERS = {
    "primary_failover": "legacy.primary_failover",
    "replica_stop": "legacy.process_pause",
    "node_host_stop": "legacy.nodehost_pause",
    "az_stop": "legacy.az_pause",
    "network_delay": "legacy.proxy",
    "network_loss": "legacy.proxy",
    "network_partition": "legacy.network_disconnect",
    "network_flap": "legacy.proxy",
    "minority_majority": "legacy.network_disconnect",
    "split_brain_detection": "legacy.network_disconnect",
}


def test_definition_projects_the_frozen_legacy_registry_without_docker() -> None:
    definition = load_milestone1_definition()

    assert definition.lifecycle_ids == tuple(legacy_gate.LIFECYCLE)
    assert definition.management_ids == tuple(legacy_runtime.P36_MANAGEMENT_SCENARIOS)
    assert definition.fault_ids == tuple(legacy_runtime.P36_FAULT_SCENARIOS)
    assert definition.scenario_ids == tuple(legacy_gate.SCENARIOS)
    assert set(definition.report_ids) == legacy_evaluator.REPORT_SURFACES
    assert definition.lifecycle_steps[-1].id == "cleanup"
    assert definition.lifecycle_steps[-1].always_run is True

    raw_json_names = tuple(dict.fromkeys(item.raw_name for item in definition.raw_json_artifacts))
    raw_jsonl_names = tuple(dict.fromkeys(item.raw_name for item in definition.raw_jsonl_artifacts))
    assert raw_json_names == tuple(legacy_gate.RAW_JSON)
    assert raw_jsonl_names == tuple(legacy_gate.RAW_JSONL)
    assert {item.admitted_kind for item in definition.admitted_json_artifacts} == legacy_evaluator.JSON_ARTIFACTS
    assert {item.admitted_kind for item in definition.admitted_jsonl_artifacts} == legacy_evaluator.JSONL_ARTIFACTS
    artifact_mapping = {
        (artifact.raw_name, admission.admitted_kind, admission.source_selector)
        for artifact in definition.artifacts
        for admission in artifact.admissions
    }
    artifact_mapping.update(
        (artifact.raw_name, None, None)
        for artifact in definition.artifacts
        if not artifact.admissions
    )
    assert artifact_mapping == EXPECTED_ARTIFACT_MAPPING


def test_definition_preserves_legacy_management_operation_and_fault_mapping() -> None:
    definition = load_milestone1_definition()
    operations_by_scenario = {
        scenario.id: scenario.operations for scenario in definition.management_scenarios
    }
    expected_by_scenario = {
        scenario_id: tuple(
            operation
            for operation in legacy_runtime.P30_EXECUTION_ROWS
            if legacy_runtime._p36_management_scenario(operation) == scenario_id
        )
        for scenario_id in legacy_runtime.P36_MANAGEMENT_SCENARIOS
    }
    expected_by_scenario["bounded_stability"] = ()

    assert definition.management_execution_order == tuple(
        legacy_runtime.P30_EXECUTION_ROWS
    )
    assert len(definition.management_execution_order) == len(
        set(definition.management_execution_order)
    )
    assert operations_by_scenario == expected_by_scenario
    assert {
        operation
        for operations in operations_by_scenario.values()
        for operation in operations
    } == set(definition.management_execution_order)
    assert tuple(scenario.id for scenario in definition.fault_scenarios) == tuple(
        legacy_runtime.P36_FAULT_SCENARIOS
    )
    assert {
        scenario.id: scenario.handler_id for scenario in definition.fault_scenarios
    } == EXPECTED_FAULT_HANDLERS
    assert all(
        scenario.parameters["fault_type"] == scenario.id
        for scenario in definition.fault_scenarios
        if scenario.handler_id == "legacy.proxy"
    )
    assert all(
        scenario.command_stream == "fault_command_log"
        for scenario in definition.fault_scenarios
    )
    assert all(
        scenario.command_stream == "command_log"
        for scenario in definition.management_scenarios
    )


def test_every_exact_scale_compiles_without_downscale_and_with_stable_digest() -> None:
    definition = load_milestone1_definition()
    policy = definition.scale_policy

    assert (policy.min_nodes, policy.max_nodes) == (30, 2000)
    assert policy.exact_requested_nodes is True
    assert policy.no_silent_downscale is True
    assert policy.runnable_not_required_scales == (30, 100)
    assert policy.required_real_scales == (50, 200)
    assert policy.normal_development_cap == 100
    assert policy.bounded_exception_scale == 200
    assert policy.bounded_exception_requires_resource_preflight is True
    assert policy.above_200_requires_operator_opt_in is True
    assert policy.above_200_requires_resource_preflight is True
    assert policy.above_200_requires_cost_acknowledgement is True
    assert re.fullmatch(r"[0-9a-f]{64}", definition.digest)
    assert load_milestone1_definition().digest == definition.digest

    plans = [compile_gate_plan(definition, requested_nodes) for requested_nodes in range(30, 2001)]
    assert all(plan.requested_nodes == requested for requested, plan in zip(range(30, 2001), plans))
    assert all(plan.exact_node_count == plan.requested_nodes for plan in plans)
    assert all(plan.downscale_allowed is False for plan in plans)
    assert {plan.requested_nodes for plan in plans if plan.required_real_completion} == {50, 200}
    assert {plan.requested_nodes for plan in plans if plan.runnable_not_required} == {30, 100}
    assert all(re.fullmatch(r"[0-9a-f]{64}", plan.digest) for plan in plans)
    assert len({plan.digest for plan in plans}) == len(plans)
    assert [compile_gate_plan(definition, plan.requested_nodes).digest for plan in plans] == [
        plan.digest for plan in plans
    ]
    legacy_scenario_scale = {
        profile.scenario: profile.scale
        for profile in legacy_runtime.STRICT_FULL_FLOW_PROFILES.values()
    }
    assert all(
        plan.runtime_scenario not in legacy_scenario_scale
        or legacy_scenario_scale[plan.runtime_scenario] == plan.requested_nodes
        for plan in plans
    )


def test_legacy_p36_adapter_bindings_are_preserved_only_where_they_exist() -> None:
    definition = load_milestone1_definition()
    legacy_profiles = {
        profile.scale: profile for profile in legacy_runtime.STRICT_FULL_FLOW_PROFILES.values()
    }

    assert set(legacy_profiles) == {50, 100, 200}
    for scale, profile in legacy_profiles.items():
        plan = compile_gate_plan(definition, scale)
        assert plan.runtime_scenario == profile.scenario
        assert plan.config_template == profile.config_path

    assert 30 not in legacy_profiles
