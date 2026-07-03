from __future__ import annotations

import json
import os
import platform
import resource as os_resource
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__
from valkey_scale_lab.config.simple_yaml import parse_config_file
from valkey_scale_lab.config.validation import normalize_config, validate_semantics

CREATED_AT = "2026-06-28T00:00:00Z"
P21_STAGE = "P21_FAILOVER_LATENCY_CURVE_200"
P32_STAGE = "P32_MANAGEMENT_MATRIX_200_REAL"
P32_SCENARIO = "strict_management_matrix_200"
EXACT_200_CONFIG_MARKER_PHASES = {P21_STAGE, P32_STAGE}


class ResourcePreflightError(RuntimeError):
    pass


def run_resource_preflight(
    config_path: str | Path,
    out_path: str | Path,
    dry_run: bool = False,
    *,
    phase_id: str | None = None,
    scenario: str | None = None,
) -> dict[str, Any]:
    config = normalize_config(parse_config_file(config_path))
    if dry_run:
        config.setdefault("runtime", {})["dry_run"] = True
    node_count = int(config["cluster"]["shards"]) * (1 + int(config["cluster"]["replicas_per_shard"]))
    phase_id = phase_id or _phase_for_node_count(node_count)
    scenario_name = scenario or _scenario_for_node_count(node_count)
    exact_200_exception = _is_exact_200_bounded_exception(config, node_count, dry_run, phase_id=phase_id, scenario=scenario_name)
    semantic_errors = _semantic_errors_for_preflight(config, allow_exact_200=exact_200_exception)
    run_id = f"{phase_id}-resource-preflight-{node_count}-20260628"
    checks: list[dict[str, Any]] = []

    checks.append(_check("config_semantics", not semantic_errors, {"errors": semantic_errors}))
    checks.append(
        _check(
            "node_count_limit",
            node_count <= 100 or dry_run or exact_200_exception,
            {
                "node_count": node_count,
                "default_cap": 100,
                "bounded_exception_phase": phase_id if exact_200_exception else "MISSING",
            },
        )
    )
    if node_count == 200:
        checks.append(
            _check(
                "exact_200_bounded_exception",
                exact_200_exception,
                {
                    "node_count": node_count,
                    "phase_id": phase_id,
                    "scenario_name": scenario_name,
                    "profile_name": config.get("profile_name", "MISSING"),
                    "dry_run": dry_run or config.get("runtime", {}).get("dry_run") is True,
                    "scale_profile": config.get("scale_profile", {}),
                },
            )
        )
    docker_details = _docker_details()
    checks.append(_check("docker_available", docker_details["available"], docker_details))
    checks.append(_check("cpu_count", (os.cpu_count() or 0) >= 2, {"cpu_count": os.cpu_count() or "MISSING"}))
    checks.append(_memory_check(node_count, int(config["cluster"].get("node_memory_limit_mb") or 0)))
    checks.append(_disk_check(Path("artifacts")))
    checks.append(_port_check(int(config["cluster"]["port_base"]), node_count, "client_ports"))
    checks.append(_port_check(int(config["cluster"]["cluster_bus_port_base"]), node_count, "cluster_bus_ports"))
    checks.append(_runtime_limit_check(node_count))
    checks.append(_cleanup_state_check(phase_id, scenario_name, node_count))

    can_run = all(item["status"] == "PASS" for item in checks)
    report = {
        "schema_version": "v1",
        "artifact_type": "resource_preflight",
        "phase_id": phase_id,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS" if can_run else "FAIL",
        "node_count": node_count,
        "nodes_requested": node_count,
        "can_run": can_run,
        "scenario_name": scenario_name,
        "config_path": str(config_path),
        "dry_run": dry_run,
        "bounded_exception": {
            "phase_id": phase_id if exact_200_exception else "MISSING",
            "scenario_name": scenario_name if exact_200_exception else "MISSING",
            "node_count": 200 if exact_200_exception else "MISSING",
            "default_max_nodes": 100,
            "config_marker_phase": config.get("scale_profile", {}).get("bounded_exception_phase", "MISSING"),
        },
        "host": _host_facts(),
        "resource_estimates": _resource_estimates(node_count, int(config["cluster"].get("node_memory_limit_mb") or 0)),
        "port_ranges": {
            "client": {
                "base": int(config["cluster"]["port_base"]),
                "last": int(config["cluster"]["port_base"]) + node_count - 1,
                "count": node_count,
            },
            "cluster_bus": {
                "base": int(config["cluster"]["cluster_bus_port_base"]),
                "last": int(config["cluster"]["cluster_bus_port_base"]) + node_count - 1,
                "count": node_count,
            },
        },
        "checks": checks,
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _is_p21_200_exception(config: dict[str, Any], node_count: int, dry_run_arg: bool) -> bool:
    return _is_exact_200_bounded_exception(
        config,
        node_count,
        dry_run_arg,
        phase_id=P21_STAGE,
        scenario=_scenario_for_node_count(node_count),
    )


def _is_exact_200_bounded_exception(
    config: dict[str, Any],
    node_count: int,
    dry_run_arg: bool,
    *,
    phase_id: str,
    scenario: str,
) -> bool:
    scale_profile = config.get("scale_profile", {})
    runtime = config.get("runtime", {})
    safety = config.get("safety", {})
    return (
        node_count == 200
        and _exact_200_phase_scenario_allowed(phase_id, scenario)
        and config.get("profile_name") == "scale_200"
        and scale_profile.get("bounded_exception_phase") in EXACT_200_CONFIG_MARKER_PHASES
        and int(scale_profile.get("bounded_exception_nodes", 0) or 0) == 200
        and int(safety.get("default_max_nodes", 0) or 0) == 100
        and safety.get("allow_1000_nodes") is False
        and dry_run_arg is False
        and runtime.get("dry_run") is False
    )


def _exact_200_phase_scenario_allowed(phase_id: str, scenario: str) -> bool:
    if phase_id == P21_STAGE:
        return scenario == "scale_200" or scenario.startswith("scale_200_sample_")
    return phase_id == P32_STAGE and scenario == P32_SCENARIO


def _semantic_errors_for_preflight(config: dict[str, Any], *, allow_exact_200: bool) -> list[dict[str, Any]]:
    errors = validate_semantics(config)
    if not allow_exact_200:
        return errors
    filtered: list[dict[str, Any]] = []
    for error in errors:
        if error.get("code") == "NODE_CAP_EXCEEDED":
            continue
        filtered.append(error)
    return filtered


def _phase_for_node_count(node_count: int) -> str:
    if node_count in {10, 30}:
        return "P12_SCALE_LADDER_10_30"
    if node_count in {50, 100}:
        return "P13_SCALE_LADDER_50_100"
    if node_count == 200:
        return "P21_FAILOVER_LATENCY_CURVE_200"
    if node_count >= 1000:
        return "P14_SCALE_1000_OPTIN_DRYRUN"
    return "P12_SCALE_LADDER_10_30"


def _scenario_for_node_count(node_count: int) -> str:
    return f"scale_{node_count}"


def _check(name: str, ok: bool, details: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "status": "PASS" if ok else "FAIL", "details": details}


def _docker_available() -> bool:
    return bool(_docker_details()["available"])


def _docker_details() -> dict[str, Any]:
    try:
        proc = subprocess.run(["docker", "info", "--format", "{{json .ServerVersion}}"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "server_version": "MISSING", "error": repr(exc)}
    version = proc.stdout.strip().strip('"')
    return {
        "available": proc.returncode == 0 and bool(version),
        "server_version": version or "MISSING",
        "returncode": proc.returncode,
        "stderr": proc.stderr[-500:],
    }


def _memory_check(node_count: int, memory_limit_mb: int) -> dict[str, Any]:
    required_mb = max(node_count * max(memory_limit_mb, 1), node_count * 32)
    # Mac Docker memory limits are owned by Docker Desktop and not always visible here, so this is a conservative floor.
    return _check(
        "memory_budget",
        required_mb <= 8192,
        {"required_memory_mb": required_mb, "node_memory_limit_mb": memory_limit_mb, "status_note": "host-visible estimate"},
    )


def _runtime_limit_check(node_count: int) -> dict[str, Any]:
    try:
        soft, hard = os_resource.getrlimit(os_resource.RLIMIT_NOFILE)
    except Exception as exc:  # noqa: BLE001
        return _check("runtime_fd_limit", False, {"reason": repr(exc), "node_count": node_count})
    required = max(1024, node_count * 4)
    ok = soft == os_resource.RLIM_INFINITY or int(soft) >= required
    return _check("runtime_fd_limit", ok, {"soft": soft, "hard": hard, "required_min": required, "node_count": node_count})


def _host_facts() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count() or "MISSING",
    }


def _resource_estimates(node_count: int, memory_limit_mb: int) -> dict[str, Any]:
    required_memory_mb = max(node_count * max(memory_limit_mb, 1), node_count * 32)
    return {
        "node_count": node_count,
        "memory_per_node_mb": max(memory_limit_mb, 32),
        "required_memory_mb": required_memory_mb,
        "required_disk_free_mb": 1024,
        "workload_overhead": "low_nonzero_p21_profile" if node_count == 200 else "standard_profile",
    }


def _disk_check(path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(path if path.exists() else Path("."))
    free_mb = usage.free // (1024 * 1024)
    return _check("disk_free", free_mb >= 1024, {"free_mb": free_mb, "required_free_mb": 1024})


def _port_check(base: int, count: int, name: str) -> dict[str, Any]:
    unavailable: list[int] = []
    for port in range(base, base + count):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                unavailable.append(port)
    return _check(name, not unavailable, {"base": base, "count": count, "unavailable": unavailable})


def _cleanup_state_check(phase_id: str, scenario: str, node_count: int) -> dict[str, Any]:
    run_id = f"{phase_id}-{scenario}-20260628"
    try:
        container_proc = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "-q",
                "--filter",
                "label=org.valkey-scale-lab.project=valkey-scale-lab",
                "--filter",
                f"label=org.valkey-scale-lab.phase={phase_id}",
                "--filter",
                f"label=org.valkey-scale-lab.run_id={run_id}",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )
        network_proc = subprocess.run(
            [
                "docker",
                "network",
                "ls",
                "-q",
                "--filter",
                "label=org.valkey-scale-lab.project=valkey-scale-lab",
                "--filter",
                f"label=org.valkey-scale-lab.phase={phase_id}",
                "--filter",
                f"label=org.valkey-scale-lab.run_id={run_id}",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        return _check("previous_cleanup_state", False, {"reason": repr(exc), "node_count": node_count})
    leftovers = [line for line in (container_proc.stdout + "\n" + network_proc.stdout).splitlines() if line.strip()]
    ok = container_proc.returncode == 0 and network_proc.returncode == 0 and not leftovers
    return _check("previous_cleanup_state", ok, {"run_id": run_id, "leftovers": leftovers, "node_count": node_count})
