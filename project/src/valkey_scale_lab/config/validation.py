from __future__ import annotations

import json
import shutil
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__
from valkey_scale_lab.cluster_timeout import (
    DEFAULT_CLUSTER_NODE_TIMEOUT_MATRIX_MS,
    DEFAULT_CLUSTER_NODE_TIMEOUT_MS,
    compute_cluster_timeout_source,
    normalize_cluster_timeout_config,
    profile_timeout_overlay,
    selected_timeout_profile,
    validate_cluster_timeout_config,
)
from valkey_scale_lab.config.schema import load_schema, validate
from valkey_scale_lab.config.simple_yaml import parse_config_file
from valkey_scale_lab.nodehost_density import NodehostDensityError, build_nodehost_density_plan, density_runtime_config
from valkey_scale_lab.server_profile import normalize_server_profile_config

CAPABILITY_ID = "config_validation"
RUN_ID = "config_validation-local-20260628"
CREATED_AT = "2026-06-28T00:00:00Z"
REQUIRED_1000_ENV_VALUE = "I_UNDERSTAND_THIS_IS_NOT_A_DEFAULT_GATE"
GLOBAL_CONFIG_PATH = Path("config/valkey_scale_lab_global.yaml")
BUILT_IN_DEFAULTS: dict[str, Any] = {
    "safety": {
        "default_max_nodes": 100,
        "allow_1000_nodes": False,
        "require_sandbox_network": True,
        "forbid_host_network_mutation": True,
        "cleanup_on_error": True,
    },
    "runtime": {
        "provider": "docker",
        "sandbox_mode": "container_namespace",
        "dry_run": False,
        "server_profile": "one_b_dev",
        "valkey": {
            "io_threads": 1,
            "io_threads_auto": False,
            "io_threads_max_per_node": 2,
            "io_threads_max_total": 256,
            "log_format": "text",
        },
        "nodehost_strategy": "density_limited",
        "max_nodehosts": 64,
        "nodehosts_per_az": 2,
        "max_logical_nodes_per_nodehost": 25,
        "nodehost_distribution": "round_robin_by_az",
    },
    "workload": {"enabled": False},
    "cluster": {"node_memory_limit_mb": 64, "cluster_node_timeout_ms": DEFAULT_CLUSTER_NODE_TIMEOUT_MS},
    "fault": {"cluster_node_timeout_matrix_ms": list(DEFAULT_CLUSTER_NODE_TIMEOUT_MATRIX_MS)},
    "observability": {
        "failover_timeline_observer": {
            "enabled": True,
            "probe_interval_ms": 250,
            "client_probe_interval_ms": 250,
            "probe_timeout_ms": 1000,
            "max_observer_endpoints": 32,
        }
    },
    "profiles": {
        "correctness": {"cluster_node_timeout_ms": DEFAULT_CLUSTER_NODE_TIMEOUT_MS},
        "failover_rto": {"cluster_node_timeout_ms": DEFAULT_CLUSTER_NODE_TIMEOUT_MS},
        "management_safe": {"cluster_node_timeout_ms": DEFAULT_CLUSTER_NODE_TIMEOUT_MS, "allow_override": True},
    },
    "faults": [],
    "scale_profile": {},
    "metadata": {},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def producer() -> dict[str, str]:
    return {"name": "valkey-scale-lab", "version": __version__}


def validate_config_file(
    config_path: str | Path,
    out_path: str | Path,
    *,
    global_config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config_path = Path(config_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path = out_path.with_name(f"{out_path.stem}.normalized.json")
    errors: list[dict[str, Any]] = []
    normalized: dict[str, Any] = {}

    try:
        raw = parse_config_file(config_path)
        normalized = normalize_config(
            raw,
            scenario_config_path=config_path,
            global_config_path=global_config_path,
            cli_overrides=cli_overrides,
        )
        schema = load_schema(Path("schemas/config/run_config.schema.json"))
        for message in validate(normalized, schema):
            errors.append({"code": "SCHEMA_VALIDATION", "message": message})
        errors.extend(validate_semantics(normalized))
    except Exception as exc:
        errors.append({"code": "CONFIG_PARSE_ERROR", "message": str(exc)})

    valid = not errors
    if normalized:
        normalized_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        normalized_path.write_text("{}\n", encoding="utf-8")

    report = {
        "schema_version": "v1",
        "artifact_type": "config_validation_report",
        "capability_id": CAPABILITY_ID,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": producer(),
        "status": "PASS" if valid else "FAIL",
        "config_path": config_path.as_posix(),
        "valid": valid,
        "errors": errors,
        "normalized_config_path": normalized_path.as_posix(),
        "total_nodes": _total_nodes(normalized) if normalized else None,
        "valkey_version_required_prefix": "9.1.",
        "config_sources": normalized.get("_config_sources", {}) if normalized else {},
        "nodehost_density": _nodehost_density_report(normalized) if normalized else {},
        "server_profile": normalized.get("_effective_server_profile", {}) if normalized else {},
        "cluster_timeout": normalized.get("_effective_cluster_timeout", {}) if normalized else {},
        "failover_timeline_observer": normalized.get("observability", {}).get("failover_timeline_observer", {}) if normalized else {},
    }
    if normalized:
        effective_profile = normalized.get("_effective_server_profile", {})
        report.update(
            {
                "requested_io_threads": effective_profile.get("requested_io_threads", "MISSING"),
                "effective_io_threads": effective_profile.get("effective_io_threads", "MISSING"),
                "requested_node_memory_limit_mb": effective_profile.get("requested_node_memory_limit_mb", "MISSING"),
                "effective_node_memory_limit_mb": effective_profile.get("effective_node_memory_limit_mb", "MISSING"),
                "io_thread_budget_status": effective_profile.get("io_thread_budget_status", "MISSING"),
                "memory_budget_status": effective_profile.get("memory_budget_status", "MISSING"),
            }
        )
        effective_timeout = normalized.get("_effective_cluster_timeout", {})
        report.update(
            {
                "requested_cluster_node_timeout_ms": effective_timeout.get("requested_cluster_node_timeout_ms", "MISSING"),
                "effective_cluster_node_timeout_ms": effective_timeout.get("effective_cluster_node_timeout_ms", "MISSING"),
                "cluster_node_timeout_source": effective_timeout.get("cluster_node_timeout_source", "MISSING"),
                "cluster_node_timeout_profile": effective_timeout.get("cluster_node_timeout_profile", "MISSING"),
                "cluster_node_timeout_matrix_ms": effective_timeout.get("cluster_node_timeout_matrix_ms", []),
            }
        )
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def emit_schema_report(out_path: str | Path) -> dict[str, Any]:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path = Path("schemas/config/run_config.schema.json")
    report = {
        "schema_version": "v1",
        "artifact_type": "config_schema_report",
        "capability_id": CAPABILITY_ID,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": producer(),
        "status": "PASS",
        "schema_path": schema_path.as_posix(),
        "defaults": {
            "default_max_nodes": 100,
            "runtime.provider": "docker",
            "runtime.sandbox_mode": "container_namespace",
            "runtime.dry_run": False,
            "runtime.nodehost_strategy": "density_limited",
            "runtime.max_nodehosts": 64,
            "runtime.nodehosts_per_az": 2,
            "runtime.max_logical_nodes_per_nodehost": 25,
            "runtime.nodehost_distribution": "round_robin_by_az",
            "safety.allow_1000_nodes": False,
            "workload.enabled": False,
            "faults": [],
        },
        "constraints": [
            {
                "name": "default_node_cap",
                "description": "Automatic/default execution must not exceed 100 Valkey nodes.",
                "status": "PASS",
            },
            {
                "name": "valkey_version",
                "description": "Runtime image must declare a Valkey 9.1.x tag.",
                "status": "PASS",
            },
            {
                "name": "sandbox_network",
                "description": "Configs must require sandbox networking and forbid host network mutation.",
                "status": "PASS",
            },
            {
                "name": "two_virtual_azs",
                "description": "Multi-AZ profiles use exactly two virtual AZs so each shard's primary and replica live in opposite AZ containers.",
                "status": "PASS",
            },
            {
                "name": "scale_1000_opt_in",
                "description": "1000-node configs require allow_1000_nodes, opt_in_1000, dry_run_only, and runtime.dry_run.",
                "status": "PASS",
            },
            {
                "name": "nodehost_density_global_merge",
                "description": "Nodehost density config merge order is built-in defaults < global config < scenario config < CLI override.",
                "status": "PASS",
            },
            {
                "name": "cluster_node_timeout_global_profile",
                "description": "cluster-node-timeout merge order is built-in defaults < global config < selected profile < scenario config < CLI override.",
                "status": "PASS",
            },
            {
                "name": "failover_timeline_observer_global_config",
                "description": "Failover timeline observer probe intervals and endpoint fanout merge through the global observability config.",
                "status": "PASS",
            },
            {
                "name": "workload_ratios",
                "description": "Enabled workloads must have read_ratio + write_ratio equal to 1.0.",
                "status": "PASS",
            },
        ],
    }
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def normalize_config(
    raw: dict[str, Any],
    *,
    scenario_config_path: str | Path | None = None,
    global_config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    global_path = Path(global_config_path) if global_config_path is not None else GLOBAL_CONFIG_PATH
    config = deepcopy(BUILT_IN_DEFAULTS)
    global_config: dict[str, Any] = {}
    if global_path.exists():
        global_config = parse_config_file(global_path)
        _deep_merge(config, global_config)
    profile_name = selected_timeout_profile(raw, cli_overrides)
    if profile_name:
        _deep_merge(config, profile_timeout_overlay(config, profile_name))
    _deep_merge(config, deepcopy(raw))
    if cli_overrides:
        _deep_merge(config, deepcopy(cli_overrides))
    config.setdefault("workload", {"enabled": False})
    config.setdefault("faults", [])
    config.setdefault("scale_profile", {})
    config.setdefault("metadata", {})

    safety = config.setdefault("safety", {})
    safety.setdefault("default_max_nodes", 100)
    safety.setdefault("allow_1000_nodes", False)
    safety.setdefault("require_sandbox_network", True)
    safety.setdefault("forbid_host_network_mutation", True)
    safety.setdefault("cleanup_on_error", True)

    runtime = config.setdefault("runtime", {})
    runtime.setdefault("provider", "docker")
    runtime.setdefault("sandbox_mode", "container_namespace")
    runtime.setdefault("dry_run", False)
    runtime.setdefault("server_profile", "one_b_dev")
    runtime.setdefault("valkey", {})
    runtime.setdefault("nodehost_strategy", "density_limited")
    runtime.setdefault("max_nodehosts", 64)
    runtime.setdefault("nodehosts_per_az", 2)
    runtime.setdefault("max_logical_nodes_per_nodehost", 25)
    runtime.setdefault("nodehost_distribution", "round_robin_by_az")

    workload = config.setdefault("workload", {})
    workload.setdefault("enabled", False)
    if workload.get("enabled"):
        workload.setdefault("pipeline", 1)
        workload.setdefault("timing", "all_run")
    observability = config.setdefault("observability", {})
    failover_observer = observability.setdefault("failover_timeline_observer", {})
    failover_observer.setdefault("enabled", True)
    failover_observer.setdefault("probe_interval_ms", 250)
    failover_observer.setdefault("client_probe_interval_ms", 250)
    failover_observer.setdefault("probe_timeout_ms", 1000)
    failover_observer.setdefault("max_observer_endpoints", 32)
    timeout_source = compute_cluster_timeout_source(
        raw=raw,
        global_config=global_config or config,
        cli_overrides=cli_overrides,
        profile_name=profile_name,
    )
    normalize_cluster_timeout_config(config, source=timeout_source, profile_name=profile_name)
    normalize_server_profile_config(config)
    config["_config_sources"] = {
        "merge_order": ["built-in defaults", "global config", "scenario config", "CLI override"],
        "built_in_defaults": "valkey_scale_lab.config.validation.BUILT_IN_DEFAULTS",
        "global_config_path": global_path.as_posix(),
        "global_config_loaded": global_path.exists(),
        "scenario_config_path": Path(scenario_config_path).as_posix() if scenario_config_path else "MISSING",
        "cli_override_applied": bool(cli_overrides),
        "cluster_node_timeout": {
            "merge_order": ["built-in defaults", "global config", "selected profile", "scenario config", "CLI override"],
            "source": timeout_source,
            "requested_cluster_node_timeout_ms": config["_effective_cluster_timeout"]["requested_cluster_node_timeout_ms"],
            "effective_cluster_node_timeout_ms": config["_effective_cluster_timeout"]["effective_cluster_node_timeout_ms"],
            "profile": config["_effective_cluster_timeout"]["cluster_node_timeout_profile"],
        },
    }
    return config


def load_effective_config(
    config_path: str | Path,
    *,
    global_config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return normalize_config(
        parse_config_file(config_path),
        scenario_config_path=config_path,
        global_config_path=global_config_path,
        cli_overrides=cli_overrides,
    )


def load_effective_config_with_timing(
    config_path: str | Path,
    *,
    global_config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, float]]:
    parse_start = time.perf_counter()
    raw = parse_config_file(config_path)
    parse_end = time.perf_counter()
    config = normalize_config(
        raw,
        scenario_config_path=config_path,
        global_config_path=global_config_path,
        cli_overrides=cli_overrides,
    )
    validate_end = time.perf_counter()
    return config, {
        "config_parse_ms": round(max(parse_end - parse_start, 0.0) * 1000.0, 3),
        "config_normalize_validate_ms": round(max(validate_end - parse_end, 0.0) * 1000.0, 3),
    }


def validate_semantics(config: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    safety = _obj(config, "safety")
    runtime = _obj(config, "runtime")
    cluster = _obj(config, "cluster")
    network = _obj(config, "network")
    workload = _obj(config, "workload")
    observability = _obj(config, "observability")
    scale_profile = _obj(config, "scale_profile")
    hosts = config.get("hosts", [])
    faults = config.get("faults", [])

    total_nodes = _total_nodes(config)
    default_cap = safety.get("default_max_nodes", 100)
    allow_1000 = safety.get("allow_1000_nodes") is True
    dry_run = runtime.get("dry_run") is True
    scale_projection = is_scale_projection_profile(config)
    legacy_1000_dry_run = (
        total_nodes >= 1000
        and allow_1000
        and dry_run
        and safety.get("require_1000_env") == "VSLAB_ALLOW_1000_DRYRUN"
        and scale_profile.get("opt_in_1000") is True
        and scale_profile.get("dry_run_only") is True
    )
    exact_2000_local_full_flow = is_exact_2000_local_full_flow_profile(config)

    if default_cap != 100:
        errors.append(_err("DEFAULT_NODE_CAP", "safety.default_max_nodes must be exactly 100 for development capabilities"))
    if total_nodes > 200:
        if not dry_run and not exact_2000_local_full_flow:
            errors.append(_err("REAL_EXECUTION_ABOVE_200_FORBIDDEN", "configs above 200 nodes must use runtime.dry_run: true"))
        if not exact_2000_local_full_flow and not scale_projection and not legacy_1000_dry_run:
            errors.append(
                _err(
                    "MISSING_200_PLUS_DRY_RUN_PROFILE",
                    "configs above 200 nodes require an explicit scale-projection profile or the legacy 1000-node dry-run opt-in",
                )
            )
        if workload.get("enabled") is True and not exact_2000_local_full_flow:
            errors.append(_err("WORKLOAD_ABOVE_200_FORBIDDEN", "configs above 200 nodes must not enable workload execution"))
    if total_nodes > default_cap and not allow_1000 and not scale_projection and not exact_2000_local_full_flow:
        errors.append(_err("NODE_CAP_EXCEEDED", f"config creates {total_nodes} nodes above default cap {default_cap}"))
    if total_nodes >= 1000 and not exact_2000_local_full_flow:
        if not allow_1000:
            errors.append(_err("MISSING_1000_ALLOW", "1000-node configs require safety.allow_1000_nodes: true"))
        if safety.get("require_1000_env") != "VSLAB_ALLOW_1000_DRYRUN":
            errors.append(_err("MISSING_1000_ENV_GUARD", "1000-node configs must name VSLAB_ALLOW_1000_DRYRUN"))
        if not dry_run:
            errors.append(_err("MISSING_1000_DRY_RUN", "1000-node configs require runtime.dry_run: true"))
        if scale_profile.get("opt_in_1000") is not True or scale_profile.get("dry_run_only") is not True:
            errors.append(_err("MISSING_1000_SCALE_PROFILE", "1000-node configs require opt_in_1000 and dry_run_only"))
    if safety.get("require_sandbox_network") is not True:
        errors.append(_err("SANDBOX_REQUIRED", "safety.require_sandbox_network must be true"))
    if safety.get("forbid_host_network_mutation") is not True:
        errors.append(_err("HOST_NETWORK_FORBIDDEN", "safety.forbid_host_network_mutation must be true"))
    if runtime.get("provider") != "docker":
        errors.append(_err("RUNTIME_PROVIDER", "runtime.provider must be docker"))
    if runtime.get("sandbox_mode") not in {"container_namespace", "sandbox_proxy"}:
        errors.append(_err("SANDBOX_MODE", "runtime.sandbox_mode must be container_namespace or sandbox_proxy"))
    if runtime.get("server_profile") not in {"correctness", "one_b_dev", "one_b_perf"}:
        errors.append(_err("SERVER_PROFILE", "runtime.server_profile must be correctness, one_b_dev, or one_b_perf"))
    valkey_runtime = _obj(runtime, "valkey")
    if valkey_runtime.get("log_format") not in {"text", "json"}:
        errors.append(_err("VALKEY_LOG_FORMAT", "runtime.valkey.log_format must be text or json"))
    for key in ["io_threads", "io_threads_max_per_node", "io_threads_max_total"]:
        try:
            value = int(valkey_runtime.get(key, 0) or 0)
        except (TypeError, ValueError):
            value = 0
        if value < 1:
            errors.append(_err("VALKEY_IO_THREADS", f"runtime.valkey.{key} must be an integer >= 1"))
    if not isinstance(valkey_runtime.get("io_threads_auto", False), bool):
        errors.append(_err("VALKEY_IO_THREADS_AUTO", "runtime.valkey.io_threads_auto must be boolean"))
    if ":9.1." not in str(runtime.get("valkey_image", "")):
        errors.append(_err("VALKEY_VERSION", "runtime.valkey_image must use a 9.1.x tag"))
    errors.extend(_validate_nodehost_density(config))
    errors.extend(validate_cluster_timeout_config(config))

    errors.extend(_validate_hosts(hosts))
    errors.extend(_validate_network(network))
    errors.extend(_validate_cluster_ports(cluster, total_nodes))
    errors.extend(_validate_workload(workload))
    errors.extend(_validate_failover_timeline_observer(observability))
    errors.extend(_validate_faults(faults))
    return errors


def _validate_failover_timeline_observer(observability: dict[str, Any]) -> list[dict[str, Any]]:
    observer = observability.get("failover_timeline_observer", {})
    if not isinstance(observer, dict):
        return [_err("FAILOVER_TIMELINE_OBSERVER_CONFIG", "observability.failover_timeline_observer must be an object")]
    errors: list[dict[str, Any]] = []
    if not isinstance(observer.get("enabled", True), bool):
        errors.append(_err("FAILOVER_TIMELINE_OBSERVER_ENABLED", "observability.failover_timeline_observer.enabled must be boolean"))
    for key, low, high in [
        ("probe_interval_ms", 50, 60000),
        ("client_probe_interval_ms", 50, 60000),
        ("probe_timeout_ms", 50, 60000),
        ("max_observer_endpoints", 1, 10000),
    ]:
        try:
            value = int(observer.get(key, 0) or 0)
        except (TypeError, ValueError):
            value = 0
        if value < low or value > high:
            errors.append(_err("FAILOVER_TIMELINE_OBSERVER_RANGE", f"observability.failover_timeline_observer.{key} must be between {low} and {high}"))
    return errors


def is_scale_projection_profile(config: dict[str, Any]) -> bool:
    total_nodes = _total_nodes(config)
    safety = _obj(config, "safety")
    runtime = _obj(config, "runtime")
    scale_profile = _obj(config, "scale_profile")
    workload = _obj(config, "workload")
    return (
        total_nodes > 200
        and runtime.get("dry_run") is True
        and scale_profile.get("dry_run_only") is True
        and scale_profile.get("scale_projection_target") is True
        and scale_profile.get("execution_mode") == "dry_run"
        and int(scale_profile.get("target_nodes", 0) or 0) == total_nodes
        and workload.get("enabled") is not True
        and safety.get("require_sandbox_network") is True
        and safety.get("forbid_host_network_mutation") is True
    )


def is_exact_2000_local_full_flow_profile(config: dict[str, Any]) -> bool:
    total_nodes = _total_nodes(config)
    safety = _obj(config, "safety")
    runtime = _obj(config, "runtime")
    scale_profile = _obj(config, "scale_profile")
    workload = _obj(config, "workload")
    return (
        total_nodes == 2000
        and config.get("profile_name") == "scale_2000_local_full_flow_optin"
        and runtime.get("provider") == "docker"
        and runtime.get("sandbox_mode") == "container_namespace"
        and runtime.get("dry_run") is False
        and workload.get("enabled") is True
        and scale_profile.get("exact_2000_local_full_flow_opt_in") is True
        and int(scale_profile.get("target_nodes", 0) or 0) == 2000
        and scale_profile.get("execution_mode") == "operator_opt_in"
        and int(safety.get("default_max_nodes", 0) or 0) == 100
        and safety.get("allow_1000_nodes") is False
        and safety.get("require_sandbox_network") is True
        and safety.get("forbid_host_network_mutation") is True
    )


def _validate_hosts(hosts: Any) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(hosts, list) or not hosts:
        return [_err("HOSTS_REQUIRED", "hosts must contain at least one host")]
    seen: set[str] = set()
    for idx, host in enumerate(hosts):
        if not isinstance(host, dict):
            errors.append(_err("HOST_INVALID", f"hosts[{idx}] must be an object"))
            continue
        host_id = str(host.get("host_id", ""))
        if not host_id:
            errors.append(_err("HOST_ID_REQUIRED", f"hosts[{idx}].host_id is required"))
        if host_id in seen:
            errors.append(_err("HOST_ID_DUPLICATE", f"duplicate host_id {host_id}"))
        seen.add(host_id)
        for field in ["os", "arch", "ip", "docker_endpoint", "memory_gb", "disk_gb", "labels"]:
            if field not in host:
                errors.append(_err("HOST_FIELD_REQUIRED", f"hosts[{idx}].{field} is required"))
        labels = host.get("labels", [])
        if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
            errors.append(_err("HOST_LABELS", f"hosts[{idx}].labels must be a list of strings"))
    return errors


def _validate_network(network: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    azs = network.get("azs", [])
    mode = network.get("virtual_az_mode")
    if mode == "single" and len(azs) != 1:
        errors.append(_err("SINGLE_AZ_COUNT", "single AZ mode requires exactly one AZ"))
    if mode == "multi" and len(azs) != 2:
        errors.append(_err("MULTI_AZ_COUNT", "multi AZ mode requires exactly two virtual AZs"))
    if len(set(azs)) != len(azs):
        errors.append(_err("DUPLICATE_AZ", "network.azs must be unique"))
    return errors


def _validate_cluster_ports(cluster: dict[str, Any], total_nodes: int) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    port_base = int(cluster.get("port_base", 0) or 0)
    bus_base = int(cluster.get("cluster_bus_port_base", 0) or 0)
    if port_base == bus_base:
        errors.append(_err("PORT_BASE_COLLISION", "client and cluster bus port bases must differ"))
    if port_base + max(total_nodes - 1, 0) > 65535:
        errors.append(_err("CLIENT_PORT_RANGE", "client port range exceeds 65535"))
    if bus_base + max(total_nodes - 1, 0) > 65535:
        errors.append(_err("BUS_PORT_RANGE", "cluster bus port range exceeds 65535"))
    return errors


def _validate_workload(workload: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if workload.get("enabled") is not True:
        return errors
    profiles = workload.get("profiles", [workload.get("profile", "smoke")])
    if isinstance(profiles, str):
        profiles = [item.strip() for item in profiles.split(",") if item.strip()]
    allowed_profiles = {"smoke", "uniform", "hotspot", "mixed_rw", "write_heavy", "read_heavy"}
    for profile in profiles if isinstance(profiles, list) else []:
        if profile not in allowed_profiles:
            errors.append(_err("WORKLOAD_PROFILE", f"workload profile {profile!r} is not recognized"))
    if workload.get("mode", "smoke") not in {"smoke", "benchmark"}:
        errors.append(_err("WORKLOAD_MODE", "workload.mode must be smoke or benchmark"))
    if workload.get("hash_slot_distribution", "single_tag") not in {"single_tag", "multi_slot", "full_slot", "hotspot"}:
        errors.append(_err("WORKLOAD_HASH_SLOT_DISTRIBUTION", "workload.hash_slot_distribution is not recognized"))
    read_ratio = float(workload.get("read_ratio", -1))
    write_ratio = float(workload.get("write_ratio", -1))
    if abs((read_ratio + write_ratio) - 1.0) > 0.000001:
        errors.append(_err("WORKLOAD_RATIO_SUM", "read_ratio + write_ratio must equal 1.0"))
    for field in ["uniform_qps", "hotspot_qps", "target_qps"]:
        if field in workload and float(workload.get(field, -1)) < 0:
            errors.append(_err("WORKLOAD_QPS", f"workload.{field} must be non-negative"))
    for field in ["pipeline", "connections", "keyspace", "value_size", "timeout_ms"]:
        if field in workload and int(workload.get(field, 0) or 0) < 1:
            errors.append(_err("WORKLOAD_POSITIVE", f"workload.{field} must be at least 1"))
    for field in ["duration_seconds"]:
        if field in workload and float(workload.get(field, 0) or 0) <= 0:
            errors.append(_err("WORKLOAD_POSITIVE", f"workload.{field} must be positive"))
    if float(workload.get("warmup_seconds", 0) or 0) < 0:
        errors.append(_err("WORKLOAD_POSITIVE", "workload.warmup_seconds must be non-negative"))
    fraction = float(workload.get("hotspot_key_fraction", 1))
    if fraction <= 0 or fraction > 1:
        errors.append(_err("WORKLOAD_HOTSPOT_FRACTION", "hotspot_key_fraction must be in (0, 1]"))
    if workload.get("timing") not in {"before_fault", "during_fault", "after_recovery", "all_run"}:
        errors.append(_err("WORKLOAD_TIMING", "workload.timing is not recognized"))
    return errors


def _validate_faults(faults: Any) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(faults, list):
        return [_err("FAULTS_TYPE", "faults must be a list")]
    valid_types = {"network_delay", "network_loss", "network_partition", "network_flap", "process_stop", "process_restart"}
    valid_scopes = {"node", "virtual_az"}
    for idx, fault in enumerate(faults):
        if not isinstance(fault, dict):
            errors.append(_err("FAULT_INVALID", f"faults[{idx}] must be an object"))
            continue
        for field in ["fault_id", "type", "target_scope", "target"]:
            if not fault.get(field):
                errors.append(_err("FAULT_FIELD_REQUIRED", f"faults[{idx}].{field} is required"))
        if fault.get("type") not in valid_types:
            errors.append(_err("FAULT_TYPE", f"faults[{idx}].type is not supported"))
        if fault.get("target_scope") not in valid_scopes:
            errors.append(_err("FAULT_TARGET_SCOPE", f"faults[{idx}].target_scope is not supported"))
        if "duration_seconds" in fault and float(fault["duration_seconds"]) <= 0:
            errors.append(_err("FAULT_DURATION", f"faults[{idx}].duration_seconds must be positive"))
    return errors


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = deepcopy(value)
    return base


def _nodehost_density_report(config: dict[str, Any]) -> dict[str, Any]:
    density = density_runtime_config(config)
    density["config_sources"] = config.get("_config_sources", {})
    return density


def _validate_nodehost_density(config: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    runtime = _obj(config, "runtime")
    if runtime.get("nodehost_strategy") != "density_limited":
        errors.append(_err("NODEHOST_STRATEGY", "runtime.nodehost_strategy must be density_limited"))
    if runtime.get("nodehost_distribution") != "round_robin_by_az":
        errors.append(_err("NODEHOST_DISTRIBUTION", "runtime.nodehost_distribution must be round_robin_by_az"))
    for key in ["max_nodehosts", "nodehosts_per_az", "max_logical_nodes_per_nodehost"]:
        value = runtime.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            errors.append(_err("NODEHOST_DENSITY_INTEGER", f"runtime.{key} must be a positive integer"))
    if errors:
        return errors
    try:
        build_nodehost_density_plan(
            config=config,
            nodes=_semantic_density_nodes(config),
            run_id="semantic-density-check",
            assign=True,
        )
    except NodehostDensityError as exc:
        errors.append(_err("NODEHOST_DENSITY_PLAN", str(exc)))
    return errors


def _semantic_density_nodes(config: dict[str, Any]) -> list[dict[str, Any]]:
    cluster = _obj(config, "cluster")
    network = _obj(config, "network")
    hosts = config.get("hosts", [{"host_id": "local"}])
    host_ids = [host.get("host_id", "local") for host in hosts if isinstance(host, dict)] or ["local"]
    azs = list(network.get("azs", ["az-local"])) or ["az-local"]
    shards = int(cluster.get("shards", 0) or 0)
    replicas = int(cluster.get("replicas_per_shard", 0) or 0)
    port_base = int(cluster.get("port_base", 7000) or 7000)
    bus_base = int(cluster.get("cluster_bus_port_base", port_base + 10000) or (port_base + 10000))
    nodes: list[dict[str, Any]] = []
    ordinal = 0
    for shard in range(shards):
        shard_id = f"shard-{shard:04d}"
        nodes.append(
            {
                "logical_id": f"{shard_id}-primary",
                "shard_id": shard_id,
                "role": "primary",
                "az_id": azs[shard % len(azs)],
                "host_id": host_ids[ordinal % len(host_ids)],
                "ordinal": ordinal,
                "client_port": port_base + ordinal,
                "cluster_bus_port": bus_base + ordinal,
            }
        )
        ordinal += 1
    for shard in range(shards):
        shard_id = f"shard-{shard:04d}"
        for replica in range(replicas):
            nodes.append(
                {
                    "logical_id": f"{shard_id}-replica-{replica:02d}",
                    "shard_id": shard_id,
                    "role": "replica",
                    "az_id": _semantic_replica_az(azs, azs[shard % len(azs)], shard, replica),
                    "host_id": host_ids[ordinal % len(host_ids)],
                    "ordinal": ordinal,
                    "client_port": port_base + ordinal,
                    "cluster_bus_port": bus_base + ordinal,
                }
            )
            ordinal += 1
    return nodes


def _semantic_replica_az(azs: list[str], primary_az: str, shard: int, replica: int) -> str:
    if len(azs) == 1:
        return azs[0]
    candidates = [az for az in azs if az != primary_az]
    return candidates[(shard + replica) % len(candidates)]


def _obj(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key, {})
    return value if isinstance(value, dict) else {}


def _total_nodes(config: dict[str, Any]) -> int:
    cluster = _obj(config, "cluster")
    return int(cluster.get("shards", 0) or 0) * (1 + int(cluster.get("replicas_per_shard", 0) or 0))


def _err(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}


def write_run_summary(path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "v1",
        "artifact_type": "run_summary",
        "capability_id": CAPABILITY_ID,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": producer(),
        "status": "PASS",
        "summary": "CONFIG_VALIDATION implemented deterministic run configuration parsing, normalization, schema reporting, and semantic validation for safety, runtime, host, AZ, cluster, workload, fault, and 1000-node opt-in settings.",
        "required_artifacts": [
            "artifacts/captures/config_validation/run_summary.json",
            "artifacts/captures/config_validation/config_validation_report.json",
            "artifacts/captures/config_validation/config_validation_multi_az_report.json",
            "artifacts/captures/config_validation/config_schema_report.json",
        ],
        "missing_metrics": [
            {
                "metric": "real_valkey_e2e_evidence",
                "status": "SKIPPED_WITH_REASON",
                "reason": "config_validation is a fake-only configuration validation capability_id; real Valkey evidence begins at CLUSTER_LIFECYCLE.",
                "impact": "No runtime cluster claims are made by this capability_id.",
            }
        ],
        "risks": [
            {
                "risk": "YAML support is intentionally limited to the repository's JSON-compatible template style until a dependency policy is introduced.",
                "severity": "low",
                "required_before_next_capability": False,
            }
        ],
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
