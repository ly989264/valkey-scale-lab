"""Hermetic semantic parity checks for the legacy real-runtime adapter.

These tests do not start Valkey, contact Docker, mutate networking, or emit gate
artifacts. They characterize code paths used by small-real runs, but their PASS
is never real Valkey evidence and cannot be promoted to an exact-scale gate.
"""

from __future__ import annotations

from valkey_scale_lab.gates.adapters import (
    LEGACY_CLEANUP_SCENARIO,
    LEGACY_CREATE_SCENARIO,
    LegacyRuntimeEntrypoints,
)
from valkey_scale_lab.runtime import docker_runtime


def test_adapter_delegates_to_the_real_runtime_entrypoints_by_identity() -> None:
    entrypoints = LegacyRuntimeEntrypoints()

    assert LEGACY_CREATE_SCENARIO is docker_runtime.create_scenario
    assert LEGACY_CLEANUP_SCENARIO is docker_runtime.cleanup_scenario
    assert entrypoints.create is docker_runtime.create_scenario
    assert entrypoints.cleanup is docker_runtime.cleanup_scenario


def test_small_real_node_projection_preserves_exact_topology_and_ownership() -> None:
    config = docker_runtime.normalize_config(
        docker_runtime.parse_config_file(
            "templates/configs/single_mac_6node.yaml"
        )
    )
    nodes = docker_runtime._node_specs(
        config,
        "P03_LOCAL_DOCKER_VALKEY",
        "cluster_smoke",
        "small-real-semantic-parity",
    )

    assert len(nodes) == 6
    assert len({node["logical_id"] for node in nodes}) == 6
    assert len({node["container_name"] for node in nodes}) == 6
    assert len({node["client_port"] for node in nodes}) == 6
    assert [node["role"] for node in nodes].count("primary") == 3
    assert [node["role"] for node in nodes].count("replica") == 3
    assert all("small-real-semantic-parity" in node["container_name"] for node in nodes)


def test_p36_adapter_profiles_are_the_existing_exact_runtime_profiles() -> None:
    for scale in (50, 100, 200):
        phase = docker_runtime.P36_STAGE
        scenario = f"strict_full_flow_{scale}"
        profile = docker_runtime._strict_full_flow_profile(phase, scenario)

        assert profile is not None
        assert profile.scale == scale
        assert profile.config_path == f"templates/configs/scale_{scale}.yaml"
        assert docker_runtime._strict_full_flow_node_count(phase, scenario) == scale
        assert docker_runtime._scenario_node_count_allowed(
            phase,
            scenario,
            scale,
        ) is True

    assert docker_runtime._strict_full_flow_profile(
        docker_runtime.P36_STAGE,
        "strict_full_flow_30",
    ) is None


def test_semantic_parity_check_cannot_be_mistaken_for_real_gate_evidence() -> None:
    # The characterization layer has callables and topology metadata only. It
    # deliberately exposes no evidence producer or real-gate promotion flag.
    entrypoints = LegacyRuntimeEntrypoints()

    assert not hasattr(entrypoints, "real_valkey")
    assert not hasattr(entrypoints, "admission_status")
    assert not hasattr(entrypoints, "evidence_path")
