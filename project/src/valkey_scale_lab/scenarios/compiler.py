from __future__ import annotations

import hashlib
import json

from .contracts import GatePlan, ScenarioDefinition


class GatePlanError(ValueError):
    pass


def compile_gate_plan(
    definition: ScenarioDefinition,
    requested_nodes: int,
) -> GatePlan:
    if isinstance(requested_nodes, bool) or not isinstance(requested_nodes, int):
        raise GatePlanError("requested_nodes must be an integer")
    policy = definition.scale_policy
    if requested_nodes < policy.min_nodes or requested_nodes > policy.max_nodes:
        raise GatePlanError(
            f"requested_nodes must be in the exact supported range "
            f"{policy.min_nodes}..{policy.max_nodes}, got {requested_nodes}"
        )
    if not policy.exact_requested_nodes or not policy.no_silent_downscale:
        raise GatePlanError("definition does not preserve exact requested node counts")

    normal_development_eligible = requested_nodes <= policy.normal_development_cap
    bounded_200_exception = requested_nodes == policy.bounded_exception_scale
    above_200 = requested_nodes > policy.bounded_exception_scale
    legacy_profile = next(
        (
            binding
            for binding in definition.legacy_profiles
            if binding.requested_nodes == requested_nodes
        ),
        None,
    )

    if normal_development_eligible:
        execution_mode = "normal_development"
    elif bounded_200_exception:
        execution_mode = "bounded_200_exception"
    elif above_200:
        execution_mode = "operator_opt_in"
    else:
        execution_mode = "deferred_adapter"

    requires_operator_opt_in = (
        above_200 and policy.above_200_requires_operator_opt_in
    )
    requires_resource_preflight = (
        bounded_200_exception
        and policy.bounded_exception_requires_resource_preflight
    ) or (above_200 and policy.above_200_requires_resource_preflight)
    requires_cost_acknowledgement = (
        above_200 and policy.above_200_requires_cost_acknowledgement
    )
    automatic_execution_allowed = normal_development_eligible

    digest_payload = {
        "definition_digest": definition.digest,
        "requested_nodes": requested_nodes,
        "exact": True,
        "execution_mode": execution_mode,
        "normal_development_eligible": normal_development_eligible,
        "automatic_execution_allowed": automatic_execution_allowed,
        "bounded_200_exception": bounded_200_exception,
        "requires_operator_opt_in": requires_operator_opt_in,
        "requires_resource_preflight": requires_resource_preflight,
        "requires_cost_acknowledgement": requires_cost_acknowledgement,
        "downscale_allowed": False,
        "legacy_profile": (
            None
            if legacy_profile is None
            else {
                "requested_nodes": legacy_profile.requested_nodes,
                "runtime_phase": legacy_profile.runtime_phase,
                "runtime_scenario": legacy_profile.runtime_scenario,
                "config_template": legacy_profile.config_template,
            }
        ),
        "lifecycle_ids": list(definition.lifecycle_ids),
        "scenario_ids": list(definition.scenario_ids),
        "management_execution_order": list(
            definition.management_execution_order
        ),
        "artifact_ids": list(definition.artifact_ids),
        "report_ids": list(definition.report_ids),
    }
    plan_digest = hashlib.sha256(
        json.dumps(
            digest_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return GatePlan(
        definition_id=definition.definition_id,
        definition_version=definition.version,
        definition_digest=definition.digest,
        requested_nodes=requested_nodes,
        exact=True,
        legacy_profile=legacy_profile,
        execution_mode=execution_mode,
        normal_development_eligible=normal_development_eligible,
        automatic_execution_allowed=automatic_execution_allowed,
        bounded_200_exception=bounded_200_exception,
        requires_operator_opt_in=requires_operator_opt_in,
        requires_resource_preflight=requires_resource_preflight,
        requires_cost_acknowledgement=requires_cost_acknowledgement,
        downscale_allowed=False,
        lifecycle_steps=definition.lifecycle_steps,
        management_scenarios=definition.management_scenarios,
        fault_scenarios=definition.fault_scenarios,
        management_execution_order=definition.management_execution_order,
        artifacts=definition.artifacts,
        report_surfaces=definition.report_surfaces,
        legacy_projection_steps=definition.legacy_projection_steps,
        digest=plan_digest,
    )
