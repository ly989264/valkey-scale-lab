from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


class ExecutionSelectionError(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionBackend:
    backend_id: str
    provider: str
    real_runtime: bool


@dataclass(frozen=True)
class ExecutionProfile:
    profile_id: str
    requested_nodes: int
    environment: str
    config_template: str


BACKENDS: Mapping[str, ExecutionBackend] = MappingProxyType(
    {
        "fake": ExecutionBackend("fake", "in_memory", False),
        "docker_container": ExecutionBackend("docker_container", "docker", True),
        "docker_process": ExecutionBackend("docker_process", "docker", True),
        "native_multi_ecs": ExecutionBackend("native_multi_ecs", "ecs", True),
    }
)

PROFILES: Mapping[str, ExecutionProfile] = MappingProxyType(
    {
        "fake": ExecutionProfile(
            "fake", 6, "hermetic", "templates/configs/single_mac_6node.yaml"
        ),
        "small-real": ExecutionProfile(
            "small-real",
            6,
            "local-real",
            "templates/configs/single_mac_6node.yaml",
        ),
        "exact-10": ExecutionProfile(
            "exact-10", 10, "local-real", "templates/configs/scale_10.yaml"
        ),
        "exact-30": ExecutionProfile(
            "exact-30", 30, "local-real", "templates/configs/scale_30.yaml"
        ),
        "exact-50": ExecutionProfile(
            "exact-50", 50, "local-real", "templates/configs/scale_50.yaml"
        ),
        "exact-100": ExecutionProfile(
            "exact-100", 100, "local-real", "templates/configs/scale_100.yaml"
        ),
        "exact-200": ExecutionProfile(
            "exact-200", 200, "local-real", "templates/configs/scale_200.yaml"
        ),
    }
)

SCENARIO_CAPABILITIES: Mapping[str, str] = MappingProxyType(
    {
        "cluster_lifecycle": "cluster_lifecycle",
        "management_matrix": "management_matrix",
        "workload": "workload",
        "observability": "observability",
        "fault_sandbox": "fault_matrix",
        "failover": "fault_matrix",
        "failover_latency_curve": "failover_latency_curve",
        "fault_matrix": "fault_matrix",
        "failover_timeline": "failover_timeline",
        "clean_gate_diagnostics": "clean_gate_diagnostics",
        "cluster_timeout": "cluster_timeout",
        "server_profile": "server_profile",
        "nodehost_density": "nodehost_density",
        "analysis_reporting": "analysis_reporting",
        "orchestration": "orchestration",
        "stability": "stability",
        "telemetry": "telemetry",
        "scale_ladder": "scale_ladder",
        "fault_workload_impact": "fault_workload_impact",
        "final_report": "final_report",
        "local_full_flow": "local_full_flow",
    }
)

# Exact-200 remains a bounded product admission. The selected scenario owns
# eligibility; the profile contributes only the requested scale and environment.
EXACT_200_SCENARIOS = frozenset(
    {
        "clean_gate_diagnostics",
        "cluster_timeout",
        "failover_latency_curve",
        "failover_timeline",
        "fault_matrix",
        "local_full_flow",
        "management_matrix",
        "nodehost_density",
        "server_profile",
    }
)


def resolve_backend(backend_id: str) -> ExecutionBackend:
    try:
        return BACKENDS[backend_id]
    except KeyError as exc:
        raise ExecutionSelectionError(f"unknown backend_id {backend_id!r}") from exc


def resolve_profile(profile_id: str, *, requested_nodes: int) -> ExecutionProfile:
    try:
        profile = PROFILES[profile_id]
    except KeyError as exc:
        raise ExecutionSelectionError(f"unknown profile_id {profile_id!r}") from exc
    if profile.requested_nodes != requested_nodes:
        raise ExecutionSelectionError(
            "profile cannot change the exact requested node count: "
            f"profile={profile.requested_nodes}, requested={requested_nodes}"
        )
    return profile


def profile_for_exact_nodes(requested_nodes: int) -> ExecutionProfile | None:
    return PROFILES.get(f"exact-{requested_nodes}")


def exact_200_selection_allowed(*, capability_id: str, scenario_id: str) -> bool:
    return (
        scenario_id == capability_id
        and scenario_id in EXACT_200_SCENARIOS
        and SCENARIO_CAPABILITIES.get(scenario_id) == capability_id
    )


def validate_execution_selection(
    *,
    scenario_id: str,
    backend_id: str,
    profile_id: str,
    requested_nodes: int,
) -> tuple[ExecutionBackend, ExecutionProfile]:
    if scenario_id not in SCENARIO_CAPABILITIES:
        raise ExecutionSelectionError(f"unknown scenario_id {scenario_id!r}")
    backend = resolve_backend(backend_id)
    profile = resolve_profile(profile_id, requested_nodes=requested_nodes)
    if backend.backend_id == "fake" and profile.profile_id != "fake":
        raise ExecutionSelectionError("fake backend requires the fake profile")
    if backend.backend_id != "fake" and profile.profile_id == "fake":
        raise ExecutionSelectionError("fake profile cannot select a real backend")
    return backend, profile


__all__ = [
    "BACKENDS",
    "EXACT_200_SCENARIOS",
    "PROFILES",
    "SCENARIO_CAPABILITIES",
    "ExecutionBackend",
    "ExecutionProfile",
    "ExecutionSelectionError",
    "exact_200_selection_allowed",
    "profile_for_exact_nodes",
    "resolve_backend",
    "resolve_profile",
    "validate_execution_selection",
]
