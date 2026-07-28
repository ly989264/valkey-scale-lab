from __future__ import annotations

import pytest

from valkey_scale_lab.execution import (
    EXACT_200_SCENARIOS,
    EXACT_2000_SCENARIOS,
    ExecutionSelectionError,
    PROFILES,
    exact_200_selection_allowed,
    exact_2000_selection_allowed,
    resolve_profile,
    validate_execution_selection,
)
from valkey_scale_lab.config.simple_yaml import parse_config_file


def test_profiles_only_select_scale_and_environment() -> None:
    assert PROFILES["fake"].requested_nodes == 6
    assert PROFILES["small-real"].requested_nodes == 6
    assert PROFILES["exact-10"].requested_nodes == 10
    assert PROFILES["exact-30"].requested_nodes == 30
    assert PROFILES["exact-50"].requested_nodes == 50
    assert PROFILES["exact-200"].requested_nodes == 200
    assert PROFILES["exact-2000"].requested_nodes == 2000
    assert set(PROFILES["exact-200"].__dataclass_fields__) == {
        "profile_id",
        "requested_nodes",
        "environment",
        "config_template",
    }
    profile_config = parse_config_file(PROFILES["exact-200"].config_template)
    assert not any(
        "capability" in key or "scenario" in key
        for key in profile_config.get("scale_profile", {})
    )


def test_exact_200_eligibility_is_owned_by_the_canonical_scenario_selection() -> None:
    assert {
        "management_matrix",
        "fault_matrix",
        "local_full_flow",
        "failover_latency_curve",
    } <= EXACT_200_SCENARIOS
    assert exact_200_selection_allowed(
        capability_id="local_full_flow",
        scenario_id="local_full_flow",
    )
    assert not exact_200_selection_allowed(
        capability_id="local_full_flow",
        scenario_id="fault_matrix",
    )


def test_exact_2000_eligibility_is_only_local_full_flow() -> None:
    assert EXACT_2000_SCENARIOS == frozenset({"local_full_flow"})
    assert exact_2000_selection_allowed(
        capability_id="local_full_flow",
        scenario_id="local_full_flow",
    )
    assert not exact_2000_selection_allowed(
        capability_id="management_matrix",
        scenario_id="management_matrix",
    )


def test_backend_selection_does_not_change_scenario_or_profile_semantics() -> None:
    container_backend, container_profile = validate_execution_selection(
        scenario_id="local_full_flow",
        backend_id="docker_container",
        profile_id="small-real",
        requested_nodes=6,
    )
    process_backend, process_profile = validate_execution_selection(
        scenario_id="local_full_flow",
        backend_id="docker_process",
        profile_id="small-real",
        requested_nodes=6,
    )

    assert container_backend.backend_id != process_backend.backend_id
    assert container_profile == process_profile


def test_profile_mismatch_is_rejected_instead_of_downscaled() -> None:
    with pytest.raises(ExecutionSelectionError, match="cannot change the exact"):
        resolve_profile("exact-50", requested_nodes=200)


def test_fake_backend_cannot_be_promoted_to_a_real_profile() -> None:
    with pytest.raises(ExecutionSelectionError, match="requires the fake profile"):
        validate_execution_selection(
            scenario_id="local_full_flow",
            backend_id="fake",
            profile_id="exact-50",
            requested_nodes=50,
        )
