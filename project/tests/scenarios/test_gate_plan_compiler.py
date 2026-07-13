from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from valkey_scale_lab.scenarios import (
    GatePlanError,
    compile_gate_plan,
    load_milestone1_definition,
)


@pytest.mark.parametrize("requested_nodes", [30, 31, 50, 100, 101, 199, 200, 201, 2000])
def test_compiler_preserves_every_requested_node_count(requested_nodes: int) -> None:
    definition = load_milestone1_definition()
    first = compile_gate_plan(definition, requested_nodes)
    second = compile_gate_plan(definition, requested_nodes)

    assert first.exact is True
    assert first.requested_nodes == requested_nodes
    assert first.exact_node_count == requested_nodes
    assert first.downscale_allowed is False
    assert first.digest == second.digest
    assert first.lifecycle_steps is definition.lifecycle_steps
    assert first.management_execution_order == definition.management_execution_order


def test_compiler_encodes_frozen_scale_policy_without_inventing_permissions() -> None:
    definition = load_milestone1_definition()
    scale_30 = compile_gate_plan(definition, 30)
    scale_50 = compile_gate_plan(definition, 50)
    scale_100 = compile_gate_plan(definition, 100)
    scale_150 = compile_gate_plan(definition, 150)
    scale_200 = compile_gate_plan(definition, 200)
    scale_201 = compile_gate_plan(definition, 201)

    assert scale_30.runnable_not_gated and not scale_30.required_completion_gate
    assert scale_50.required_completion_gate and scale_50.normal_development_eligible
    assert scale_100.runnable_not_gated and not scale_100.required_completion_gate
    assert not scale_150.normal_development_eligible
    assert scale_150.execution_mode == "deferred_adapter"
    assert not scale_150.requires_operator_opt_in
    assert scale_200.required_completion_gate and scale_200.bounded_200_exception
    assert scale_200.requires_resource_preflight
    assert not scale_200.requires_cost_acknowledgement
    assert scale_201.requires_operator_opt_in
    assert scale_201.requires_resource_preflight
    assert scale_201.requires_cost_acknowledgement
    assert not scale_201.automatic_execution_allowed


def test_compiler_only_resolves_declared_existing_legacy_profiles() -> None:
    definition = load_milestone1_definition()
    assert compile_gate_plan(definition, 30).legacy_profile is None
    assert compile_gate_plan(definition, 50).config_template == "templates/configs/scale_50.yaml"
    assert compile_gate_plan(definition, 100).runtime_scenario == "strict_full_flow_100"
    assert compile_gate_plan(definition, 200).runtime_scenario == "strict_full_flow_200"
    assert compile_gate_plan(definition, 201).legacy_profile is None


@pytest.mark.parametrize("value", [29, 2001, True, 50.0, "50"])
def test_compiler_rejects_out_of_contract_or_non_integer_requests(value) -> None:
    with pytest.raises(GatePlanError):
        compile_gate_plan(load_milestone1_definition(), value)  # type: ignore[arg-type]


def test_gate_plan_is_frozen() -> None:
    plan = compile_gate_plan(load_milestone1_definition(), 50)
    with pytest.raises(FrozenInstanceError):
        plan.requested_nodes = 49  # type: ignore[misc]
