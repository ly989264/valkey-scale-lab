"""Hermetic semantic parity checks for the canonical real-runtime adapter.

These tests do not start Valkey, contact Docker, mutate networking, or emit gate
artifacts. They characterize code paths used by small-real runs, but their PASS
is never real Valkey evidence and cannot be promoted to an exact-scale gate.
"""

from __future__ import annotations

from valkey_scale_lab.execution import PROFILES
from valkey_scale_lab.gates.adapters import (
    PRODUCT_CLEANUP_SCENARIO,
    PRODUCT_EXECUTE_SCENARIO,
    ProductRuntimeEntrypoints,
)
from valkey_scale_lab.runtime import docker_runtime


def test_adapter_delegates_to_the_real_runtime_entrypoints_by_identity() -> None:
    entrypoints = ProductRuntimeEntrypoints()

    assert PRODUCT_EXECUTE_SCENARIO is docker_runtime.execute_scenario
    assert PRODUCT_CLEANUP_SCENARIO is docker_runtime.cleanup_scenario
    assert entrypoints.execute is docker_runtime.execute_scenario
    assert entrypoints.cleanup is docker_runtime.cleanup_scenario


def test_small_real_node_projection_preserves_exact_topology_and_ownership() -> None:
    config = docker_runtime.normalize_config(
        docker_runtime.parse_config_file(
            "templates/configs/single_mac_6node.yaml"
        )
    )
    nodes = docker_runtime._node_specs(
        config,
        "local_full_flow",
        "local_full_flow",
        "small-real-semantic-parity",
    )

    assert len(nodes) == 6
    assert len({node["logical_id"] for node in nodes}) == 6
    assert len({node["container_name"] for node in nodes}) == 6
    assert len({node["client_port"] for node in nodes}) == 6
    assert [node["role"] for node in nodes].count("primary") == 3
    assert [node["role"] for node in nodes].count("replica") == 3
    assert all("small-real-semantic-parity" in node["container_name"] for node in nodes)


def test_exact_profiles_reuse_the_single_runtime_implementation() -> None:
    for scale in (50, 100, 200):
        profile = PROFILES[f"exact-{scale}"]
        assert profile.requested_nodes == scale
        assert profile.config_template == f"templates/configs/scale_{scale}.yaml"


def test_semantic_parity_check_cannot_be_mistaken_for_real_gate_evidence() -> None:
    # The characterization layer has callables and topology metadata only. It
    # deliberately exposes no evidence producer or real-gate promotion flag.
    entrypoints = ProductRuntimeEntrypoints()

    assert not hasattr(entrypoints, "real_valkey")
    assert not hasattr(entrypoints, "admission_status")
    assert not hasattr(entrypoints, "evidence_path")
