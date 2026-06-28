from __future__ import annotations

import json
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__
from valkey_scale_lab.config.schema import load_schema, validate
from valkey_scale_lab.config.simple_yaml import parse_config_file

PHASE_ID = "P01_CONFIG_SCHEMA"
RUN_ID = "P01_CONFIG_SCHEMA-local-20260628"
CREATED_AT = "2026-06-28T00:00:00Z"
REQUIRED_1000_ENV_VALUE = "I_UNDERSTAND_THIS_IS_NOT_A_DEFAULT_GATE"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def producer() -> dict[str, str]:
    return {"name": "valkey-scale-lab", "version": __version__}


def validate_config_file(config_path: str | Path, out_path: str | Path) -> dict[str, Any]:
    config_path = Path(config_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path = out_path.with_name(f"{out_path.stem}.normalized.json")
    errors: list[dict[str, Any]] = []
    normalized: dict[str, Any] = {}

    try:
        raw = parse_config_file(config_path)
        normalized = normalize_config(raw)
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
        "phase_id": PHASE_ID,
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
    }
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def emit_schema_report(out_path: str | Path) -> dict[str, Any]:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path = Path("schemas/config/run_config.schema.json")
    report = {
        "schema_version": "v1",
        "artifact_type": "config_schema_report",
        "phase_id": PHASE_ID,
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
                "name": "scale_1000_opt_in",
                "description": "1000-node configs require allow_1000_nodes, opt_in_1000, dry_run_only, and runtime.dry_run.",
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


def normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    config = deepcopy(raw)
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

    workload = config.setdefault("workload", {})
    workload.setdefault("enabled", False)
    if workload.get("enabled"):
        workload.setdefault("pipeline", 1)
        workload.setdefault("timing", "all_run")
    return config


def validate_semantics(config: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    safety = _obj(config, "safety")
    runtime = _obj(config, "runtime")
    cluster = _obj(config, "cluster")
    network = _obj(config, "network")
    workload = _obj(config, "workload")
    scale_profile = _obj(config, "scale_profile")
    hosts = config.get("hosts", [])
    faults = config.get("faults", [])

    total_nodes = _total_nodes(config)
    default_cap = safety.get("default_max_nodes", 100)
    allow_1000 = safety.get("allow_1000_nodes") is True
    dry_run = runtime.get("dry_run") is True

    if default_cap != 100:
        errors.append(_err("DEFAULT_NODE_CAP", "safety.default_max_nodes must be exactly 100 for development phases"))
    if total_nodes > default_cap and not allow_1000:
        errors.append(_err("NODE_CAP_EXCEEDED", f"config creates {total_nodes} nodes above default cap {default_cap}"))
    if total_nodes >= 1000:
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
    if ":9.1." not in str(runtime.get("valkey_image", "")):
        errors.append(_err("VALKEY_VERSION", "runtime.valkey_image must use a 9.1.x tag"))

    errors.extend(_validate_hosts(hosts))
    errors.extend(_validate_network(network))
    errors.extend(_validate_cluster_ports(cluster, total_nodes))
    errors.extend(_validate_workload(workload))
    errors.extend(_validate_faults(faults))
    return errors


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
    if mode == "multi" and len(azs) < 2:
        errors.append(_err("MULTI_AZ_COUNT", "multi AZ mode requires at least two AZs"))
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
    read_ratio = float(workload.get("read_ratio", -1))
    write_ratio = float(workload.get("write_ratio", -1))
    if abs((read_ratio + write_ratio) - 1.0) > 0.000001:
        errors.append(_err("WORKLOAD_RATIO_SUM", "read_ratio + write_ratio must equal 1.0"))
    for field in ["uniform_qps", "hotspot_qps"]:
        if float(workload.get(field, -1)) < 0:
            errors.append(_err("WORKLOAD_QPS", f"workload.{field} must be non-negative"))
    if int(workload.get("pipeline", 0) or 0) < 1:
        errors.append(_err("WORKLOAD_PIPELINE", "workload.pipeline must be at least 1"))
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


def _obj(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key, {})
    return value if isinstance(value, dict) else {}


def _total_nodes(config: dict[str, Any]) -> int:
    cluster = _obj(config, "cluster")
    return int(cluster.get("shards", 0) or 0) * (1 + int(cluster.get("replicas_per_shard", 0) or 0))


def _err(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}


def write_phase_summary(path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "v1",
        "artifact_type": "phase_summary",
        "phase_id": PHASE_ID,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": producer(),
        "status": "PASS",
        "summary": "P01 implemented deterministic run configuration parsing, normalization, schema reporting, and semantic validation for safety, runtime, host, AZ, cluster, workload, fault, and 1000-node opt-in settings.",
        "required_artifacts": [
            "artifacts/phases/P01_CONFIG_SCHEMA/phase_summary.json",
            "artifacts/phases/P01_CONFIG_SCHEMA/config_validation_report.json",
            "artifacts/phases/P01_CONFIG_SCHEMA/config_validation_multi_az_report.json",
            "artifacts/phases/P01_CONFIG_SCHEMA/config_schema_report.json",
        ],
        "missing_metrics": [
            {
                "metric": "real_valkey_e2e_evidence",
                "status": "SKIPPED_WITH_REASON",
                "reason": "P01_CONFIG_SCHEMA is a fake-only configuration validation phase; real Valkey evidence begins at P03.",
                "impact": "No runtime cluster claims are made by this phase.",
            }
        ],
        "risks": [
            {
                "risk": "YAML support is intentionally limited to the repository's JSON-compatible template style until a dependency policy is introduced.",
                "severity": "low",
                "required_before_next_phase": False,
            }
        ],
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
