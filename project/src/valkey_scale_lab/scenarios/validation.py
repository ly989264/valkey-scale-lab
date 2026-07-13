from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from .registry import (
    ADMISSION_COMPATIBILITY,
    HANDLER_REGISTRY,
    TRANSFORM_REGISTRY,
    expected_admission_compatibility,
)


LIFECYCLE_IDS = (
    "resource_preflight",
    "runtime_start",
    "cluster_form",
    "stabilize",
    "baseline_workload",
    "management_matrix",
    "fault_matrix",
    "recovery",
    "artifact_validation",
    "analysis",
    "report",
    "cleanup",
)

MANAGEMENT_IDS = (
    "add_remove_node",
    "reshard_rebalance",
    "rolling_restart",
    "bounded_stability",
)

FAULT_IDS = (
    "primary_failover",
    "replica_stop",
    "node_host_stop",
    "az_stop",
    "network_delay",
    "network_loss",
    "network_partition",
    "network_flap",
    "minority_majority",
    "split_brain_detection",
)

REPORT_IDS = (
    "topology_summary",
    "phase_durations",
    "bottlenecks",
    "resources",
    "workload_impact",
    "failover",
    "recovery",
    "error_summary",
    "missing_evidence",
)

RAW_JSON_NAMES = (
    "run_state.json",
    "resource_preflight.json",
    "workload_windows.json",
    "lifecycle_timeline.json",
    "scenario_results.json",
    "management_sequence.json",
    "fault_sequence.json",
    "cleanup_report.json",
    "analysis_summary.json",
    "report_index.json",
    "full_flow_result.json",
)

RAW_JSONL_NAMES = (
    "management_command_log.jsonl",
    "fault_command_log.jsonl",
    "events.jsonl",
    "metrics_timeseries.jsonl",
)

ADMITTED_JSON_KINDS = (
    "run_metadata",
    "resource_preflight",
    "workload_windows",
    "lifecycle_timeline",
    "scenario_results",
    "management_results",
    "fault_results",
    "stability_results",
    "cleanup_report",
    "analysis_summary",
    "report_index",
)

ADMITTED_JSONL_KINDS = ("command_log", "fault_command_log", "events", "metrics")

LEGACY_PROJECTION_STEPS = (
    "config_validate",
    "resource_preflight",
    "plan_cluster",
    "create_cluster",
    "meet_nodes",
    "assign_slots",
    "add_replica",
    "baseline_workload",
    "telemetry_collect",
    "analysis_build",
    "report_render",
    "cleanup_verify",
)

MANAGEMENT_OPERATIONS = {
    "add_remove_node": (
        "create_cluster",
        "meet_nodes",
        "add_replica",
        "remove_replica",
        "remove_failed_node",
        "remove_primary_drained_or_safe_replaced",
    ),
    "reshard_rebalance": (
        "reshard_slot_range",
        "reshard_with_keys",
        "rebalance_after_imbalance",
    ),
    "rolling_restart": (
        "rolling_restart_replica_first",
        "rolling_restart_primary_safe",
    ),
    "bounded_stability": (),
}

MANAGEMENT_EXECUTION_ORDER = (
    "create_cluster",
    "meet_nodes",
    "add_replica",
    "reshard_slot_range",
    "reshard_with_keys",
    "rebalance_after_imbalance",
    "rolling_restart_replica_first",
    "rolling_restart_primary_safe",
    "remove_replica",
    "remove_failed_node",
    "remove_primary_drained_or_safe_replaced",
)

EXPECTED_SCENARIO_HANDLERS = {
    "add_remove_node": "legacy.management_operation",
    "reshard_rebalance": "legacy.management_operation",
    "rolling_restart": "legacy.management_operation",
    "bounded_stability": "legacy.bounded_stability",
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

EXPECTED_SCENARIO_PARAMETERS = {
    "add_remove_node": {},
    "reshard_rebalance": {},
    "rolling_restart": {},
    "bounded_stability": {
        "health_sample_count": 3,
        "health_interval_seconds": 1.0,
    },
    "primary_failover": {},
    "replica_stop": {},
    "node_host_stop": {},
    "az_stop": {},
    "network_delay": {
        "fault_type": "network_delay",
        "delay_ms": 25,
        "expect_success": True,
    },
    "network_loss": {
        "fault_type": "network_loss",
        "loss_percent": 100.0,
        "expect_success": False,
    },
    "network_partition": {"observation": "network_partition"},
    "network_flap": {
        "fault_type": "network_flap",
        "flap_down_ms": 250,
        "flap_iterations": 1,
        "expect_success": False,
    },
    "minority_majority": {
        "observation": "minority_majority",
        "wait_cluster_timeout_plus_ms": 1000,
        "require_majority_ok": True,
        "require_isolated_not_ok": True,
    },
    "split_brain_detection": {
        "observation": "split_brain_detection",
        "wait_cluster_timeout_plus_ms": 1000,
        "forbid_both_ok": True,
    },
}

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_TOP_LEVEL_KEYS = {
    "$schema",
    "schema_version",
    "definition_id",
    "version",
    "lifecycle",
    "scenarios",
    "management_execution_order",
    "artifacts",
    "report_surfaces",
    "scale_policy",
    "legacy_profiles",
    "legacy_projection_steps",
}


def validate_scenario_definition(document: Any) -> tuple[str, ...]:
    errors: list[str] = []
    if not isinstance(document, Mapping):
        return ("$: definition must be a JSON object",)

    _check_keys(document, _TOP_LEVEL_KEYS, _TOP_LEVEL_KEYS, "$", errors)
    if document.get("$schema") != "../../../../schemas/scenario/gate_scenario.schema.json":
        errors.append("$.$schema: unexpected schema path")
    if document.get("schema_version") != "gate-scenario-v1":
        errors.append("$.schema_version: expected 'gate-scenario-v1'")
    if document.get("definition_id") != "milestone1_full_flow":
        errors.append("$.definition_id: expected 'milestone1_full_flow'")
    if isinstance(document.get("version"), bool) or document.get("version") != 1:
        errors.append("$.version: expected integer 1")

    _validate_lifecycle(document.get("lifecycle"), errors)
    _validate_scenarios(document.get("scenarios"), errors)
    _expect_ordered_strings(
        document.get("management_execution_order"),
        MANAGEMENT_EXECUTION_ORDER,
        "$.management_execution_order",
        errors,
    )
    _validate_artifacts(document.get("artifacts"), errors)
    _expect_ordered_strings(document.get("report_surfaces"), REPORT_IDS, "$.report_surfaces", errors)
    _validate_scale_policy(document.get("scale_policy"), errors)
    _validate_legacy_profiles(document.get("legacy_profiles"), errors)
    _expect_ordered_strings(
        document.get("legacy_projection_steps"),
        LEGACY_PROJECTION_STEPS,
        "$.legacy_projection_steps",
        errors,
    )
    return tuple(errors)


def _validate_lifecycle(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("$.lifecycle: expected array")
        return
    ids = [item.get("id") for item in value if isinstance(item, Mapping)]
    _expect_exact_order(ids, LIFECYCLE_IDS, "$.lifecycle ids", errors)
    if _has_duplicates(ids):
        errors.append("$.lifecycle: step ids must be unique")

    graph: dict[str, tuple[str, ...]] = {}
    known = set(ids)
    for index, item in enumerate(value):
        path = f"$.lifecycle[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{path}: expected object")
            continue
        _check_keys(item, {"id", "handler_id", "depends_on", "always_run", "terminal"}, {"id", "handler_id", "depends_on", "always_run", "terminal"}, path, errors)
        step_id = item.get("id")
        handler_id = item.get("handler_id")
        expected_handler = f"legacy.{step_id}"
        if handler_id != expected_handler or HANDLER_REGISTRY.get(str(handler_id)) != "lifecycle":
            errors.append(f"{path}.handler_id: expected closed handler {expected_handler!r}")
        depends_on = item.get("depends_on")
        if not isinstance(depends_on, list) or any(not isinstance(dep, str) for dep in depends_on):
            errors.append(f"{path}.depends_on: expected string array")
            continue
        graph[str(step_id)] = tuple(depends_on)
        for dependency in depends_on:
            if dependency not in known:
                errors.append(f"{path}.depends_on: unknown dependency {dependency!r}")
        expected_dependencies = [] if index == 0 else [LIFECYCLE_IDS[index - 1]] if index < len(LIFECYCLE_IDS) else []
        if depends_on != expected_dependencies:
            errors.append(f"{path}.depends_on: lifecycle must be the canonical linear DAG")
        expected_always = step_id == "cleanup"
        if item.get("always_run") is not expected_always:
            errors.append(f"{path}.always_run: expected {expected_always!r}")
        if item.get("terminal") is not expected_always:
            errors.append(f"{path}.terminal: expected {expected_always!r}")

    _check_acyclic(graph, errors)
    if value:
        final = value[-1]
        if not isinstance(final, Mapping) or final.get("id") != "cleanup" or final.get("always_run") is not True or final.get("terminal") is not True:
            errors.append("$.lifecycle: cleanup must be the only terminal always_run step")


def _validate_scenarios(value: Any, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        errors.append("$.scenarios: expected object")
        return
    _check_keys(value, {"management", "fault"}, {"management", "fault"}, "$.scenarios", errors)
    all_ids: list[Any] = []
    for category, expected_ids, stream in (
        ("management", MANAGEMENT_IDS, "command_log"),
        ("fault", FAULT_IDS, "fault_command_log"),
    ):
        rows = value.get(category)
        path = f"$.scenarios.{category}"
        if not isinstance(rows, list):
            errors.append(f"{path}: expected array")
            continue
        ids = [row.get("id") for row in rows if isinstance(row, Mapping)]
        all_ids.extend(ids)
        _expect_exact_order(ids, expected_ids, f"{path} ids", errors)
        for index, row in enumerate(rows):
            item_path = f"{path}[{index}]"
            if not isinstance(row, Mapping):
                errors.append(f"{item_path}: expected object")
                continue
            _check_keys(row, {"id", "handler_id", "command_stream", "operations", "parameters"}, {"id", "handler_id", "command_stream", "operations", "parameters"}, item_path, errors)
            scenario_id = row.get("id")
            handler_id = row.get("handler_id")
            expected_handler = EXPECTED_SCENARIO_HANDLERS.get(str(scenario_id))
            if handler_id != expected_handler or HANDLER_REGISTRY.get(str(handler_id)) != category:
                errors.append(f"{item_path}.handler_id: unexpected or unregistered handler {handler_id!r}")
            if row.get("command_stream") != stream:
                errors.append(f"{item_path}.command_stream: expected {stream!r}")
            operations = row.get("operations")
            if not isinstance(operations, list) or any(not isinstance(item, str) for item in operations):
                errors.append(f"{item_path}.operations: expected string array")
            elif tuple(operations) != MANAGEMENT_OPERATIONS.get(str(scenario_id), ()):
                errors.append(f"{item_path}.operations: missing, unknown, or reordered operations")
            if not isinstance(row.get("parameters"), Mapping):
                errors.append(f"{item_path}.parameters: expected object")
            elif row.get("parameters") != EXPECTED_SCENARIO_PARAMETERS.get(str(scenario_id)):
                errors.append(f"{item_path}.parameters: unexpected closed handler parameters")
    if _has_duplicates(all_ids):
        errors.append("$.scenarios: scenario ids must be globally unique")
    classified_operations = [
        operation
        for scenario_id in MANAGEMENT_IDS
        for operation in MANAGEMENT_OPERATIONS[scenario_id]
    ]
    if len(classified_operations) != len(set(classified_operations)) or set(classified_operations) != set(MANAGEMENT_EXECUTION_ORDER):
        errors.append("$.scenarios.management: every management operation must classify exactly once")


def _validate_artifacts(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("$.artifacts: expected array")
        return
    raw_names: list[Any] = []
    admitted: list[Any] = []
    for index, row in enumerate(value):
        path = f"$.artifacts[{index}]"
        if not isinstance(row, Mapping):
            errors.append(f"{path}: expected object")
            continue
        _check_keys(row, {"raw_name", "format", "required_raw", "admissions"}, {"raw_name", "format", "required_raw", "admissions"}, path, errors)
        raw_name = row.get("raw_name")
        raw_names.append(raw_name)
        if not isinstance(raw_name, str) or not _is_safe_relative_path(raw_name):
            errors.append(f"{path}.raw_name: unsafe artifact path")
        artifact_format = row.get("format")
        if artifact_format not in {"json", "jsonl"}:
            errors.append(f"{path}.format: expected 'json' or 'jsonl'")
        expected_format = (
            "json"
            if raw_name in RAW_JSON_NAMES
            else "jsonl"
            if raw_name in RAW_JSONL_NAMES
            else None
        )
        if expected_format is not None and artifact_format != expected_format:
            errors.append(
                f"{path}.format: {raw_name!r} requires {expected_format!r}"
            )
        if row.get("required_raw") is not True:
            errors.append(f"{path}.required_raw: canonical raw artifacts are required")
        admissions = row.get("admissions")
        if not isinstance(admissions, list):
            errors.append(f"{path}.admissions: expected array")
            continue
        for admission_index, admission in enumerate(admissions):
            admission_path = f"{path}.admissions[{admission_index}]"
            if not isinstance(admission, Mapping):
                errors.append(f"{admission_path}: expected object")
                continue
            _check_keys(admission, {"kind", "transform_id", "source_selector"}, {"kind"}, admission_path, errors)
            kind = admission.get("kind")
            admitted.append(kind)
            if not isinstance(kind, str) or not _IDENTIFIER.fullmatch(kind):
                errors.append(f"{admission_path}.kind: unsafe artifact kind")
            transform_id = admission.get("transform_id")
            if transform_id is not None and (
                not isinstance(transform_id, str)
                or transform_id not in TRANSFORM_REGISTRY
            ):
                errors.append(f"{admission_path}.transform_id: unknown closed transform {transform_id!r}")
            selector = admission.get("source_selector")
            if selector is not None and (not isinstance(selector, str) or not _IDENTIFIER.fullmatch(selector)):
                errors.append(f"{admission_path}.source_selector: unsafe selector")
            if (
                isinstance(raw_name, str)
                and isinstance(artifact_format, str)
                and isinstance(kind, str)
            ):
                expected_admission = expected_admission_compatibility(kind)
                if expected_admission is not None:
                    if (
                        raw_name != expected_admission.source_raw_name
                        or artifact_format != expected_admission.source_format
                        or transform_id != expected_admission.transform_id
                        or selector != expected_admission.source_selector
                    ):
                        errors.append(
                            f"{admission_path}: incompatible admission; admitted kind "
                            f"{kind!r} requires source "
                            f"{expected_admission.source_raw_name!r} "
                            f"({expected_admission.source_format}), transform "
                            f"{expected_admission.transform_id!r}, and source_selector "
                            f"{expected_admission.source_selector!r}"
                        )
                else:
                    errors.append(
                        f"{admission_path}: admitted kind {kind!r} has no closed "
                        "source compatibility rule"
                    )
    _expect_exact_order(raw_names, RAW_JSON_NAMES + RAW_JSONL_NAMES, "$.artifacts raw names", errors)
    if _has_duplicates(raw_names):
        errors.append("$.artifacts: raw artifact paths must be unique")
    _expect_exact_order(admitted, ADMITTED_JSON_KINDS + ADMITTED_JSONL_KINDS, "$.artifacts admitted kinds", errors)
    if _has_duplicates(admitted):
        errors.append("$.artifacts: admitted kinds must be unique")
    if set(item for item in admitted if isinstance(item, str)) != set(ADMISSION_COMPATIBILITY):
        errors.append("$.artifacts: admitted kinds must exactly match the closed source registry")


def _validate_scale_policy(value: Any, errors: list[str]) -> None:
    expected = {
        "min_nodes": 30,
        "max_nodes": 2000,
        "required_real_scales": [50, 200],
        "runnable_not_required_scales": [30, 100],
        "normal_development_cap": 100,
        "bounded_exception_scale": 200,
        "exact_requested_nodes": True,
        "no_silent_downscale": True,
        "bounded_exception_requires_resource_preflight": True,
        "above_200_requires_operator_opt_in": True,
        "above_200_requires_resource_preflight": True,
        "above_200_requires_cost_acknowledgement": True,
    }
    if not isinstance(value, Mapping):
        errors.append("$.scale_policy: expected object")
        return
    _check_keys(value, set(expected), set(expected), "$.scale_policy", errors)
    for key, expected_value in expected.items():
        actual = value.get(key)
        if isinstance(expected_value, bool):
            matches = actual is expected_value
        elif isinstance(expected_value, int):
            matches = (
                isinstance(actual, int)
                and not isinstance(actual, bool)
                and actual == expected_value
            )
        elif isinstance(expected_value, list):
            matches = (
                isinstance(actual, list)
                and all(isinstance(item, int) and not isinstance(item, bool) for item in actual)
                and actual == expected_value
            )
        else:
            matches = actual == expected_value
        if not matches:
            errors.append(f"$.scale_policy.{key}: expected {expected_value!r}")


def _validate_legacy_profiles(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("$.legacy_profiles: expected array")
        return
    expected_scales = (50, 100, 200)
    scales = [row.get("requested_nodes") for row in value if isinstance(row, Mapping)]
    _expect_exact_order(scales, expected_scales, "$.legacy_profiles requested_nodes", errors)
    for index, row in enumerate(value):
        path = f"$.legacy_profiles[{index}]"
        if not isinstance(row, Mapping):
            errors.append(f"{path}: expected object")
            continue
        _check_keys(row, {"requested_nodes", "runtime_phase", "runtime_scenario", "config_template"}, {"requested_nodes", "runtime_phase", "runtime_scenario", "config_template"}, path, errors)
        scale = row.get("requested_nodes")
        if row.get("runtime_phase") != "P36_FULL_FLOW_E2E_50_100_200_REAL":
            errors.append(f"{path}.runtime_phase: unexpected legacy phase")
        if row.get("runtime_scenario") != f"strict_full_flow_{scale}":
            errors.append(f"{path}.runtime_scenario: unexpected legacy scenario")
        template = row.get("config_template")
        if template != f"templates/configs/scale_{scale}.yaml" or not isinstance(template, str) or not _is_safe_relative_path(template):
            errors.append(f"{path}.config_template: unsafe or unexpected template path")


def _check_acyclic(graph: Mapping[str, Sequence[str]], errors: list[str]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            errors.append(f"$.lifecycle: dependency cycle includes {node!r}")
            return
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph.get(node, ()):
            if dependency in graph:
                visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def _is_safe_relative_path(value: str) -> bool:
    if not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def _check_keys(value: Mapping[str, Any], allowed: set[str], required: set[str], path: str, errors: list[str]) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        errors.append(f"{path}: missing required keys {missing}")
    if unknown:
        errors.append(f"{path}: unknown keys {unknown}")


def _expect_ordered_strings(value: Any, expected: Sequence[str], path: str, errors: list[str]) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        errors.append(f"{path}: expected string array")
        return
    _expect_exact_order(value, expected, path, errors)


def _expect_exact_order(actual: Sequence[Any], expected: Sequence[Any], path: str, errors: list[str]) -> None:
    if tuple(actual) != tuple(expected):
        errors.append(f"{path}: expected exact order {list(expected)!r}, got {list(actual)!r}")


def _has_duplicates(values: Sequence[Any]) -> bool:
    seen: set[str] = set()
    for value in values:
        marker = repr(value)
        if marker in seen:
            return True
        seen.add(marker)
    return False
