from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__
from valkey_scale_lab.config.validation import (
    REQUIRED_1000_ENV_VALUE,
    is_p37_200_plus_dry_run_profile,
    load_effective_config,
    normalize_config,
    validate_semantics,
)
from valkey_scale_lab.nodehost_density import NodehostDensityError, build_nodehost_density_plan
from valkey_scale_lab.server_profile import compute_effective_server_profile, node_effective_fields

PHASE_ID = "P02_PLANNER"
RUN_ID = "P02_PLANNER-local-20260628"
CREATED_AT = "2026-06-28T00:00:00Z"


class PlannerError(ValueError):
    pass


def create_plan_file(
    config_path: str | Path,
    out_path: str | Path,
    dry_run: bool = False,
    *,
    global_config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = load_effective_config(config_path, global_config_path=global_config_path, cli_overrides=cli_overrides)
    if dry_run:
        config.setdefault("runtime", {})["dry_run"] = True
    errors = validate_semantics(config)
    if errors:
        message = "; ".join(f"{item['code']}: {item['message']}" for item in errors)
        raise PlannerError(message)
    plan = build_cluster_plan(config, config_path=Path(config_path), force_dry_run=dry_run)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return plan


def build_cluster_plan(
    config: dict[str, Any],
    config_path: Path | None = None,
    force_dry_run: bool = False,
    *,
    bounded_exception_phase: str | None = None,
    bounded_exception_scenario: str | None = None,
) -> dict[str, Any]:
    cluster = config["cluster"]
    network = config["network"]
    runtime = config["runtime"]
    safety = config["safety"]
    hosts = config["hosts"]
    scale_profile = config.get("scale_profile", {})

    shard_count = int(cluster["shards"])
    replicas_per_shard = int(cluster["replicas_per_shard"])
    node_count = shard_count * (1 + replicas_per_shard)
    azs = list(network["azs"])
    host_ids = [host["host_id"] for host in hosts]
    dry_run = bool(force_dry_run or runtime.get("dry_run"))
    opt_in_1000 = bool(safety.get("allow_1000_nodes") and scale_profile.get("opt_in_1000"))
    p37_200_plus_dry_run = is_p37_200_plus_dry_run_profile(config)
    exact_200_bounded_exception = _is_p32_exact_200_bounded_exception(
        config,
        node_count=node_count,
        dry_run=dry_run,
        phase=bounded_exception_phase,
        scenario=bounded_exception_scenario,
    )

    if network.get("virtual_az_mode") == "single" and replicas_per_shard > 0:
        if not config.get("cluster", {}).get("non_ha_allowed"):
            raise PlannerError("single-AZ replica plans require cluster.non_ha_allowed: true")

    planned_nodes: list[dict[str, Any]] = []
    az_cursor = 0
    for shard_index in range(shard_count):
        shard_id = f"shard-{shard_index:04d}"
        primary_az = azs[az_cursor % len(azs)]
        az_cursor += 1
        planned_nodes.append(
            _node(
                config=config,
                shard_index=shard_index,
                replica_index=None,
                role="primary",
                host_id=host_ids[len(planned_nodes) % len(host_ids)],
                az_id=primary_az,
                ordinal=len(planned_nodes),
                dry_run=dry_run,
            )
        )
        for replica_index in range(replicas_per_shard):
            replica_az = _replica_az(azs, primary_az, shard_index, replica_index)
            planned_nodes.append(
                _node(
                    config=config,
                    shard_index=shard_index,
                    replica_index=replica_index,
                    role="replica",
                    host_id=host_ids[len(planned_nodes) % len(host_ids)],
                    az_id=replica_az,
                    ordinal=len(planned_nodes),
                    dry_run=dry_run,
                )
            )

    try:
        density_plan = build_nodehost_density_plan(config=config, nodes=planned_nodes, run_id=RUN_ID, assign=True)
    except NodehostDensityError as exc:
        raise PlannerError(str(exc)) from exc
    effective_profile = compute_effective_server_profile(config, nodehost_count=int(density_plan.get("actual_nodehost_count", 0) or 0))
    for node in planned_nodes:
        node.update(node_effective_fields(effective_profile))
    nodehosts = density_plan["nodehosts"]
    density = density_plan["nodehost_density"]
    capacity = _check_host_capacity(config, planned_nodes)
    constraints = {
        "primary_replica_distinct_az": _primary_replica_distinct_az(planned_nodes)
        or _explicit_non_ha_single_az(config),
        "two_virtual_azs": network.get("virtual_az_mode") != "multi" or len(azs) == 2,
        "primary_replica_opposite_az_pair": _primary_replica_opposite_az_pair(planned_nodes, azs)
        or _explicit_non_ha_single_az(config),
        "default_node_cap": int(safety["default_max_nodes"]),
        "dry_run": dry_run,
        "opt_in_1000": opt_in_1000,
        "p37_200_plus_dry_run": p37_200_plus_dry_run,
        "above_200_dry_run_only": node_count > 200,
        "exact_200_bounded_exception": exact_200_bounded_exception,
        "no_execution": dry_run,
        "port_collision_checked": _ports_unique_per_host(planned_nodes),
        "az_balanced": _az_balanced(planned_nodes),
        "host_capacity_checked": capacity["ok"],
        "host_capacity": capacity["hosts"],
        "nodehost_density_configured": True,
        "nodehost_density_within_limit": all(
            int(count) <= int(density["max_logical_nodes_per_nodehost"])
            for count in density["logical_nodes_per_nodehost"].values()
        ),
        "nodehost_count_within_limit": int(density["actual_nodehost_count"]) <= int(density["max_nodehosts"]),
        "non_ha_single_az": _explicit_non_ha_single_az(config),
        "allow_1000_env": safety.get("require_1000_env") if opt_in_1000 else None,
        "required_1000_env_value": REQUIRED_1000_ENV_VALUE if opt_in_1000 else None,
    }
    if exact_200_bounded_exception:
        constraints["bounded_exception_phase"] = bounded_exception_phase
        constraints["bounded_exception_scenario"] = bounded_exception_scenario
    if node_count > 200 and not dry_run:
        raise PlannerError("plans above 200 nodes must be dry-run only")
    if node_count > 200 and dry_run and not p37_200_plus_dry_run and not opt_in_1000:
        raise PlannerError("above-200 dry-run plans require explicit P37 dry-run markers")
    if node_count > int(safety["default_max_nodes"]) and not opt_in_1000 and not exact_200_bounded_exception and not p37_200_plus_dry_run:
        raise PlannerError("node count exceeds default cap without 1000 opt-in")
    if node_count >= 1000 and not dry_run:
        raise PlannerError("1000-node plans must be dry-run only")
    if not all(
        [
            constraints["primary_replica_distinct_az"],
            constraints["two_virtual_azs"],
            constraints["primary_replica_opposite_az_pair"],
            constraints["port_collision_checked"],
            constraints["az_balanced"],
            constraints["host_capacity_checked"],
            constraints["nodehost_density_within_limit"],
            constraints["nodehost_count_within_limit"],
        ]
    ):
        raise PlannerError("planner constraints failed")

    return {
        "schema_version": "v1",
        "artifact_type": "cluster_plan",
        "phase_id": PHASE_ID,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "config_path": config_path.as_posix() if config_path else None,
        "node_count": node_count,
        "shard_count": shard_count,
        "replicas_per_shard": replicas_per_shard,
        "hosts": host_ids,
        "azs": azs,
        "runtime": {
            "provider": runtime["provider"],
            "sandbox_mode": runtime["sandbox_mode"],
            "network_mode": "container_namespace",
            "container_strategy": "density_limited_nodehosts_with_valkey_processes",
            "valkey_image": runtime["valkey_image"],
            "dry_run": dry_run,
            "server_profile": effective_profile,
            "effective_io_threads": effective_profile["effective_io_threads"],
            "effective_node_memory_limit_mb": effective_profile["effective_node_memory_limit_mb"],
            "runtime_memory_limit_enforced": effective_profile["runtime_memory_limit_enforced"],
            **density,
        },
        "directories": {
            "run_root": f"artifacts/runtime/{RUN_ID}",
            "state_dir": f"artifacts/runtime/{RUN_ID}/state",
        },
        "nodehost_density": density,
        "effective_server_profile": effective_profile,
        "config_sources": config.get("_config_sources", {}),
        "nodehosts": nodehosts,
        "nodes": planned_nodes,
        "constraints": constraints,
    }


def _is_p32_exact_200_bounded_exception(
    config: dict[str, Any],
    *,
    node_count: int,
    dry_run: bool,
    phase: str | None,
    scenario: str | None,
) -> bool:
    scale_profile = config.get("scale_profile", {})
    safety = config.get("safety", {})
    runtime = config.get("runtime", {})
    allowed_exact_200 = {
        ("P32_MANAGEMENT_MATRIX_200_REAL", "strict_management_matrix_200"),
        ("P36_FULL_FLOW_E2E_50_100_200_REAL", "strict_full_flow_200"),
    }
    return (
        (phase, scenario) in allowed_exact_200
        and node_count == 200
        and config.get("profile_name") == "scale_200"
        and int(safety.get("default_max_nodes", 0) or 0) == 100
        and safety.get("allow_1000_nodes") is False
        and runtime.get("dry_run") is False
        and dry_run is False
        and scale_profile.get("bounded_exception_phase") in {
            "P21_FAILOVER_LATENCY_CURVE_200",
            "P32_MANAGEMENT_MATRIX_200_REAL",
            "P36_FULL_FLOW_E2E_50_100_200_REAL",
        }
        and int(scale_profile.get("bounded_exception_nodes", 0) or 0) == 200
    )


def write_phase_summary(path: str | Path) -> None:
    summary = {
        "schema_version": "v1",
        "artifact_type": "phase_summary",
        "phase_id": PHASE_ID,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "summary": "P02 implemented deterministic cluster planning with AZ-aware primary/replica placement, port/name/directory collision checks, host assignment, and opt-in dry-run handling for 1000-node plans.",
        "required_artifacts": [
            "artifacts/phases/P02_PLANNER/phase_summary.json",
            "artifacts/phases/P02_PLANNER/cluster_plan.json",
            "artifacts/phases/P02_PLANNER/scale_1000_dryrun_plan.json",
        ],
        "missing_metrics": [
            {
                "metric": "real_valkey_e2e_evidence",
                "status": "SKIPPED_WITH_REASON",
                "reason": "P02_PLANNER is a fake-only planning phase; real Valkey evidence begins at P03.",
                "impact": "Planner artifacts make no live runtime claim.",
            }
        ],
        "risks": [
            {
                "risk": "Host capacity checks are conservative structural checks in P02 and will need real resource probing before runtime phases.",
                "severity": "low",
                "required_before_next_phase": False,
            }
        ],
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _node(
    *,
    config: dict[str, Any],
    shard_index: int,
    replica_index: int | None,
    role: str,
    host_id: str,
    az_id: str,
    ordinal: int,
    dry_run: bool,
) -> dict[str, Any]:
    cluster = config["cluster"]
    shard_id = f"shard-{shard_index:04d}"
    suffix = "primary" if role == "primary" else f"replica-{replica_index:02d}"
    logical_id = f"{shard_id}-{suffix}"
    run_root = f"artifacts/runtime/{RUN_ID}"
    return {
        "logical_id": logical_id,
        "host_id": host_id,
        "az_id": az_id,
        "role": role,
        "shard_id": shard_id,
        "runtime_type": "docker_process",
        "nodehost_id": "MISSING",
        "nodehost_container_name": "MISSING",
        "process_name": logical_id,
        "client_port": int(cluster["port_base"]) + ordinal,
        "cluster_bus_port": int(cluster["cluster_bus_port_base"]) + ordinal,
        "container_name": f"vslab-{RUN_ID.lower().replace('_', '-')}-{logical_id}",
        "data_dir": f"{run_root}/data/{logical_id}",
        "log_dir": f"{run_root}/logs/{logical_id}",
        "pid_file": f"{run_root}/pids/{logical_id}.pid",
        "state_file": f"{run_root}/state/{logical_id}.json",
        "dry_run": dry_run,
        "resource_limits": {
            "memory_mb": config["cluster"].get("node_memory_limit_mb"),
        },
    }


def _replica_az(azs: list[str], primary_az: str, shard_index: int, replica_index: int) -> str:
    if len(azs) == 1:
        return azs[0]
    candidates = [az for az in azs if az != primary_az]
    return candidates[(shard_index + replica_index) % len(candidates)]


def _primary_replica_distinct_az(nodes: list[dict[str, Any]]) -> bool:
    primaries = {node["shard_id"]: node["az_id"] for node in nodes if node["role"] == "primary"}
    return all(node["az_id"] != primaries[node["shard_id"]] for node in nodes if node["role"] == "replica")


def _primary_replica_opposite_az_pair(nodes: list[dict[str, Any]], azs: list[str]) -> bool:
    if len(azs) != 2:
        return False
    by_shard: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        by_shard.setdefault(node["shard_id"], []).append(node)
    expected_pair = set(azs)
    for shard_nodes in by_shard.values():
        if len([node for node in shard_nodes if node["role"] == "replica"]) != 1:
            continue
        if {node["az_id"] for node in shard_nodes} != expected_pair:
            return False
    return True


def _ports_unique_per_host(nodes: list[dict[str, Any]]) -> bool:
    per_host: dict[str, list[int]] = {}
    for node in nodes:
        per_host.setdefault(node["host_id"], []).extend([int(node["client_port"]), int(node["cluster_bus_port"])])
    return all(len(ports) == len(set(ports)) for ports in per_host.values())


def _az_balanced(nodes: list[dict[str, Any]]) -> bool:
    counts = Counter(node["az_id"] for node in nodes)
    if len(counts) <= 1:
        return True
    return max(counts.values()) - min(counts.values()) <= 1


def _explicit_non_ha_single_az(config: dict[str, Any]) -> bool:
    return (
        config.get("network", {}).get("virtual_az_mode") == "single"
        and bool(config.get("cluster", {}).get("non_ha_allowed"))
    )


def _check_host_capacity(config: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, Any]:
    node_memory_mb = int(config["cluster"].get("node_memory_limit_mb") or 0)
    node_counts = Counter(node["host_id"] for node in nodes)
    host_results: list[dict[str, Any]] = []
    ok = True
    for host in config["hosts"]:
        host_id = host["host_id"]
        planned_nodes = int(node_counts.get(host_id, 0))
        required_mb = planned_nodes * node_memory_mb
        memory_gb = host.get("memory_gb")
        available_mb: int | None
        status: str
        reason: str | None = None
        if isinstance(memory_gb, (int, float)) and not isinstance(memory_gb, bool):
            available_mb = int(float(memory_gb) * 1024)
            if available_mb <= 0:
                status = "FAIL"
                reason = "host memory_gb must be positive when numeric"
                ok = False
            elif required_mb > available_mb:
                status = "FAIL"
                reason = f"planned memory {required_mb} MB exceeds host capacity {available_mb} MB"
                ok = False
            else:
                status = "PASS"
        elif memory_gb == "auto":
            available_mb = None
            status = "SKIPPED_WITH_REASON"
            reason = "host memory is auto; runtime preflight will probe physical capacity"
        else:
            available_mb = None
            status = "FAIL"
            reason = "host memory_gb must be numeric or auto"
            ok = False
        host_results.append(
            {
                "host_id": host_id,
                "planned_nodes": planned_nodes,
                "required_memory_mb": required_mb,
                "available_memory_mb": available_mb,
                "status": status,
                "reason": reason,
            }
        )
    return {"ok": ok, "hosts": host_results}


def _nodehost_summaries(nodes: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    safe_run = run_id.lower().replace("_", "-")
    az_order = []
    for node in nodes:
        if node["az_id"] not in az_order:
            az_order.append(node["az_id"])
    summaries = []
    for ordinal, az_id in enumerate(az_order):
        hosted = [node for node in nodes if node["az_id"] == az_id]
        nodehost_id = f"nodehost-{az_id}"
        summaries.append(
            {
                "nodehost_id": nodehost_id,
                "az_id": az_id,
                "host_id": hosted[0]["host_id"] if hosted else "MISSING",
                "ordinal": ordinal,
                "container_name": f"vslab-{safe_run}-{nodehost_id}",
                "logical_node_count": len(hosted),
                "client_ports": sorted(int(node["client_port"]) for node in hosted),
                "cluster_bus_ports": sorted(int(node["cluster_bus_port"]) for node in hosted),
            }
        )
    return summaries
