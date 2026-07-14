from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class LegacyExecutionAlias:
    """Translate an old Pxx entry point into the canonical execution axes."""

    scenario_id: str
    backend_id: str
    profile_id: str
    capability_id: str


_ALIASES: Mapping[tuple[str, str], LegacyExecutionAlias] = MappingProxyType(
    {
        ("P03_LOCAL_DOCKER_VALKEY", "cluster_smoke"): LegacyExecutionAlias(
            "cluster_lifecycle", "docker_container", "small-real", "cluster_lifecycle"
        ),
        ("P04_CLUSTER_MANAGEMENT_OPS", "management_ops"): LegacyExecutionAlias(
            "management_matrix", "docker_process", "small-real", "management_matrix"
        ),
        ("P05_WORKLOAD_ENGINE", "workload_smoke"): LegacyExecutionAlias(
            "workload", "docker_container", "small-real", "workload"
        ),
        ("P06_OBSERVABILITY_METRICS", "observability_smoke"): LegacyExecutionAlias(
            "observability", "docker_container", "small-real", "observability"
        ),
        ("P07_FAULT_INJECTION_SANDBOX", "fault_sandbox_setup"): LegacyExecutionAlias(
            "fault_sandbox", "docker_container", "small-real", "fault_matrix"
        ),
        ("P08_FAILOVER_SPLIT_BRAIN", "failover_setup"): LegacyExecutionAlias(
            "failover", "docker_container", "small-real", "fault_matrix"
        ),
        ("P09_ANALYSIS_REPORTING", "reporting_source_smoke"): LegacyExecutionAlias(
            "analysis_reporting", "docker_container", "small-real", "analysis_reporting"
        ),
        ("P10_MULTI_HOST_ORCHESTRATION", "orchestrated_localhost"): LegacyExecutionAlias(
            "orchestration", "docker_container", "small-real", "orchestration"
        ),
        ("P11_STABILITY_SOAK", "stability_soak_smoke"): LegacyExecutionAlias(
            "stability", "docker_container", "small-real", "stability"
        ),
        ("P22_FAULT_REPLICA_HOST_AZ_STOP", "fault_matrix"): LegacyExecutionAlias(
            "fault_matrix", "docker_container", "small-real", "fault_matrix"
        ),
        ("P23_FAULT_NETWORK_DELAY_LOSS_FLAP", "fault_matrix"): LegacyExecutionAlias(
            "fault_matrix", "docker_container", "small-real", "fault_matrix"
        ),
        ("P24_PARTITION_SPLIT_BRAIN_MATRIX", "fault_matrix"): LegacyExecutionAlias(
            "fault_matrix", "docker_container", "small-real", "fault_matrix"
        ),
        ("P30_MANAGEMENT_MATRIX_REAL", "strict_management_matrix"): LegacyExecutionAlias(
            "management_matrix", "docker_process", "exact-50", "management_matrix"
        ),
        ("P31_MANAGEMENT_MATRIX_100_REAL", "strict_management_matrix_100"): LegacyExecutionAlias(
            "management_matrix", "docker_process", "exact-100", "management_matrix"
        ),
        ("P32_MANAGEMENT_MATRIX_200_REAL", "strict_management_matrix_200"): LegacyExecutionAlias(
            "management_matrix", "docker_process", "exact-200", "management_matrix"
        ),
        ("P33_FAULT_FAILOVER_MATRIX_50_REAL", "strict_fault_matrix_50"): LegacyExecutionAlias(
            "fault_matrix", "docker_process", "exact-50", "fault_matrix"
        ),
        ("P34_FAULT_FAILOVER_MATRIX_100_REAL", "strict_fault_matrix_100"): LegacyExecutionAlias(
            "fault_matrix", "docker_process", "exact-100", "fault_matrix"
        ),
        ("P35_FAULT_FAILOVER_MATRIX_200_REAL", "strict_fault_matrix_200"): LegacyExecutionAlias(
            "fault_matrix", "docker_process", "exact-200", "fault_matrix"
        ),
        ("P36_FULL_FLOW_E2E_50_100_200_REAL", "strict_full_flow_50"): LegacyExecutionAlias(
            "local_full_flow", "docker_process", "exact-50", "local_full_flow"
        ),
        ("P36_FULL_FLOW_E2E_50_100_200_REAL", "strict_full_flow_100"): LegacyExecutionAlias(
            "local_full_flow", "docker_process", "exact-100", "local_full_flow"
        ),
        ("P36_FULL_FLOW_E2E_50_100_200_REAL", "strict_full_flow_200"): LegacyExecutionAlias(
            "local_full_flow", "docker_process", "exact-200", "local_full_flow"
        ),
    }
)

_CAPABILITY_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "P00_REPO_CONTRACT": "repository_contract",
        "P01_CONFIG_SCHEMA": "config_schema",
        "P02_PLANNER": "scale_planning",
        "P12_SCALE_LADDER_10_30": "scale_ladder",
        "P13_SCALE_LADDER_50_100": "scale_ladder",
        "P14_SCALE_1000_OPTIN_DRYRUN": "scale_planning",
        "P16_QUANT_TELEMETRY_UNIFICATION": "telemetry",
        "P17_MANAGEMENT_REMOVE_NODE": "management_matrix",
        "P18_MANAGEMENT_RESHARD_REBALANCE": "management_matrix",
        "P19_MANAGEMENT_ROLLING_RESTART": "management_matrix",
        "P20_FAILOVER_LATENCY_CURVE_30_50_100": "failover_latency_curve",
        "P21_FAILOVER_LATENCY_CURVE_200": "failover_latency_curve",
        "P25_FAULT_WORKLOAD_IMPACT_ANALYSIS": "fault_workload_impact",
        "P26_FINAL_REPORT_REGRESSION": "final_report",
        "P27_STRICT_MATRIX_REBASE_HARNESS": "harness",
        "P29_QUANT_TELEMETRY_COLLECTOR_HARDENING": "telemetry",
        "P41_NODEHOST_DENSITY_GLOBAL_CONFIG": "nodehost_density",
        "P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG": "server_profile",
        "P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE": "cluster_timeout",
        "P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY": "failover_timeline",
        "P45_CLEAN_GATE_LAYERED_DIAGNOSTICS": "clean_gate_diagnostics",
        "P46_REPOSITORY_LAYOUT_MIGRATION": "repository_layout",
    }
)


def resolve_phase_alias(phase: str, scenario: str) -> LegacyExecutionAlias:
    """Resolve a migration-only Pxx name without owning product behavior."""

    try:
        return _ALIASES[(phase, scenario)]
    except KeyError as exc:
        raise ValueError(f"unknown compatibility alias {phase}/{scenario}") from exc


def resolve_capability_alias(alias_id: str) -> str:
    """Translate a non-execution Pxx flag into a canonical capability ID."""

    try:
        return _CAPABILITY_ALIASES[alias_id]
    except KeyError as exc:
        raise ValueError(f"unknown capability compatibility alias {alias_id}") from exc
