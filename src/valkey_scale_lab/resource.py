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
from valkey_scale_lab.config.validation import load_effective_config, validate_semantics
from valkey_scale_lab.nodehost_density import NodehostDensityError, build_nodehost_density_plan
from valkey_scale_lab.server_profile import compute_effective_server_profile

CREATED_AT = "2026-06-28T00:00:00Z"
P21_STAGE = "P21_FAILOVER_LATENCY_CURVE_200"
P32_STAGE = "P32_MANAGEMENT_MATRIX_200_REAL"
P32_SCENARIO = "strict_management_matrix_200"
P35_STAGE = "P35_FAULT_FAILOVER_MATRIX_200_REAL"
P35_SCENARIO = "strict_fault_matrix_200"
P36_STAGE = "P36_FULL_FLOW_E2E_50_100_200_REAL"
P36_SCENARIO = "strict_full_flow_200"
P42_STAGE = "P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG"
EXACT_200_CONFIG_MARKER_PHASES = {P21_STAGE, P32_STAGE, P35_STAGE, P36_STAGE, P42_STAGE}


class ResourcePreflightError(RuntimeError):
    pass


def run_resource_preflight(
    config_path: str | Path,
    out_path: str | Path,
    dry_run: bool = False,
    *,
    phase_id: str | None = None,
    scenario: str | None = None,
    global_config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = load_effective_config(config_path, global_config_path=global_config_path, cli_overrides=cli_overrides)
    if dry_run:
        config.setdefault("runtime", {})["dry_run"] = True
    node_count = int(config["cluster"]["shards"]) * (1 + int(config["cluster"]["replicas_per_shard"]))
    phase_id = phase_id or _phase_for_node_count(node_count)
    scenario_name = scenario or _scenario_for_node_count(node_count)
    exact_200_exception = _is_exact_200_bounded_exception(config, node_count, dry_run, phase_id=phase_id, scenario=scenario_name)
    semantic_errors = _semantic_errors_for_preflight(config, allow_exact_200=exact_200_exception)
    run_id = f"{phase_id}-resource-preflight-{node_count}-20260628"
    checks: list[dict[str, Any]] = []
    density_plan: dict[str, Any] | None = None
    density_error: str | None = None
    try:
        density_plan = build_nodehost_density_plan(
            config=config,
            nodes=_preflight_density_nodes(config),
            run_id=run_id,
            assign=True,
        )
    except NodehostDensityError as exc:
        density_error = str(exc)

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
    effective_profile = compute_effective_server_profile(
        config,
        nodehost_count=int((density_plan or {}).get("actual_nodehost_count", 0) or 0) or None,
    )
    memory_check = _memory_check(
        node_count,
        int(effective_profile["effective_node_memory_limit_mb"]),
        density_plan=density_plan,
    )
    effective_profile["memory_budget_status"] = memory_check["status"]
    effective_profile["memory_budget_reason"] = memory_check["details"].get("reason", memory_check["details"].get("status_note", "within memory budget"))
    checks.append(memory_check)
    checks.append(
        _check(
            "io_thread_budget",
            effective_profile["io_thread_budget_status"] in {"PASS", "DEGRADED_WITH_REASON"},
            {
                "requested_io_threads": effective_profile["requested_io_threads"],
                "effective_io_threads": effective_profile["effective_io_threads"],
                "total_valkey_threads": effective_profile["total_valkey_threads"],
                "io_threads_max_total": effective_profile["io_threads_max_total"],
                "reason": effective_profile["io_thread_budget_reason"],
            },
        )
    )
    checks.append(_disk_check(Path("artifacts")))
    checks.append(_total_port_count_check(config, node_count))
    checks.append(_port_check(int(config["cluster"]["port_base"]), node_count, "client_ports"))
    checks.append(_port_check(int(config["cluster"]["cluster_bus_port_base"]), node_count, "cluster_bus_ports"))
    checks.append(_runtime_limit_check(node_count, density_plan=density_plan))
    checks.extend(_nodehost_density_checks(config, density_plan, density_error))
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
        "resource_estimates": _resource_estimates(
            node_count,
            int(effective_profile["effective_node_memory_limit_mb"]),
            density_plan=density_plan,
        ),
        "server_profile": effective_profile,
        "requested_io_threads": effective_profile["requested_io_threads"],
        "effective_io_threads": effective_profile["effective_io_threads"],
        "requested_node_memory_limit_mb": effective_profile["requested_node_memory_limit_mb"],
        "effective_node_memory_limit_mb": effective_profile["effective_node_memory_limit_mb"],
        "io_thread_budget_status": effective_profile["io_thread_budget_status"],
        "memory_budget_status": effective_profile["memory_budget_status"],
        "node_memory_limit_mb": effective_profile["effective_node_memory_limit_mb"],
        "projected_node_memory_mb": node_count * int(effective_profile["effective_node_memory_limit_mb"]),
        "projected_nodehost_memory_mb": _projected_nodehost_memory(
            int(effective_profile["effective_node_memory_limit_mb"]),
            density_plan,
            node_count,
        ),
        "host_available_memory_mb": _host_available_memory_mb(),
        "nodehost_density": (density_plan or {}).get("nodehost_density", {}),
        "nodehost_density_plan": density_plan or {
            "status": "FAIL",
            "reason": density_error or "nodehost density plan unavailable",
        },
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
            "total": {
                "count": node_count * 2,
                "max_port": max(
                    int(config["cluster"]["port_base"]) + node_count - 1,
                    int(config["cluster"]["cluster_bus_port_base"]) + node_count - 1,
                ),
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
    return (phase_id, scenario) in {
        (P32_STAGE, P32_SCENARIO),
        (P35_STAGE, P35_SCENARIO),
        (P36_STAGE, P36_SCENARIO),
    } or (phase_id == P42_STAGE and scenario == "p42_server_profile_scale_200")


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


def _memory_check(node_count: int, memory_limit_mb: int, *, density_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    required_mb = node_count * max(memory_limit_mb, 1)
    host_available = _host_available_memory_mb()
    projected_nodehost = _projected_nodehost_memory(memory_limit_mb, density_plan, node_count)
    ok = isinstance(host_available, int) and required_mb <= host_available
    return _check(
        "memory_budget",
        ok,
        {
            "required_memory_mb": required_mb,
            "node_count_times_node_memory_limit_mb": required_mb,
            "node_memory_limit_mb": memory_limit_mb,
            "projected_nodehost_memory_mb": projected_nodehost,
            "host_available_memory_mb": host_available,
            "can_run": ok,
            "reason": "required memory exceeds host available memory" if not ok else "within host-visible memory budget",
            "status_note": "host-visible estimate",
        },
    )


def _runtime_limit_check(node_count: int, *, density_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        soft, hard = os_resource.getrlimit(os_resource.RLIMIT_NOFILE)
    except Exception as exc:  # noqa: BLE001
        return _check("runtime_fd_limit", False, {"reason": repr(exc), "node_count": node_count})
    nodehost_count = int((density_plan or {}).get("actual_nodehost_count", 0) or 0)
    required = max(1024, node_count * 8 + nodehost_count * 32)
    ok = soft == os_resource.RLIM_INFINITY or int(soft) >= required
    return _check("runtime_fd_limit", ok, {"soft": soft, "hard": hard, "required_min": required, "node_count": node_count, "nodehost_count": nodehost_count})


def _host_facts() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count() or "MISSING",
    }


def _resource_estimates(node_count: int, memory_limit_mb: int, *, density_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    required_memory_mb = node_count * max(memory_limit_mb, 1)
    return {
        "node_count": node_count,
        "memory_per_node_mb": memory_limit_mb,
        "required_memory_mb": required_memory_mb,
        "node_count_times_node_memory_limit_mb": required_memory_mb,
        "projected_nodehost_memory_mb": _projected_nodehost_memory(memory_limit_mb, density_plan, node_count),
        "host_available_memory_mb": _host_available_memory_mb(),
        "required_disk_free_mb": 1024,
        "workload_overhead": "low_nonzero_p21_profile" if node_count == 200 else "standard_profile",
    }


def _projected_nodehost_memory(memory_limit_mb: int, density_plan: dict[str, Any] | None, node_count: int) -> dict[str, int]:
    counts = (density_plan or {}).get("nodehost_density", {}).get("logical_nodes_per_nodehost", {})
    if not isinstance(counts, dict) or not counts:
        counts = {"single-nodehost-projection": node_count}
    return {str(key): int(value) * int(memory_limit_mb) for key, value in counts.items()}


def _host_available_memory_mb() -> int | str:
    try:
        if platform.system() == "Darwin":
            proc = subprocess.run(["sysctl", "-n", "hw.memsize"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            if proc.returncode == 0 and proc.stdout.strip().isdigit():
                return int(proc.stdout.strip()) // (1024 * 1024)
        page_size = os.sysconf("SC_PAGE_SIZE")
        try:
            pages = os.sysconf("SC_AVPHYS_PAGES")
        except (ValueError, OSError, AttributeError):
            pages = os.sysconf("SC_PHYS_PAGES")
        return int(page_size * pages) // (1024 * 1024)
    except Exception:
        return "MISSING"


def _total_port_count_check(config: dict[str, Any], node_count: int) -> dict[str, Any]:
    client_last = int(config["cluster"]["port_base"]) + max(node_count - 1, 0)
    bus_last = int(config["cluster"]["cluster_bus_port_base"]) + max(node_count - 1, 0)
    ok = node_count > 0 and client_last <= 65535 and bus_last <= 65535 and int(config["cluster"]["port_base"]) != int(config["cluster"]["cluster_bus_port_base"])
    return _check(
        "total_port_count",
        ok,
        {
            "logical_node_count": node_count,
            "total_ports": node_count * 2,
            "client_last": client_last,
            "cluster_bus_last": bus_last,
            "max_port": 65535,
        },
    )


def _nodehost_density_checks(
    config: dict[str, Any],
    density_plan: dict[str, Any] | None,
    density_error: str | None,
) -> list[dict[str, Any]]:
    if density_plan is None:
        return [_check("nodehost_density_plan", False, {"reason": density_error or "density plan missing"})]
    density = density_plan["nodehost_density"]
    max_nodehosts = int(density["max_nodehosts"])
    actual = int(density["actual_nodehost_count"])
    max_per = int(density["max_logical_nodes_per_nodehost"])
    logical_counts = {str(key): int(value) for key, value in density["logical_nodes_per_nodehost"].items()}
    return [
        _check("nodehost_density_plan", True, density),
        _check("nodehost_count_limit", actual <= max_nodehosts, {"actual_nodehost_count": actual, "max_nodehosts": max_nodehosts}),
        _check(
            "nodehost_process_density",
            all(count <= max_per for count in logical_counts.values()),
            {"max_logical_nodes_per_nodehost": max_per, "logical_nodes_per_nodehost": logical_counts},
        ),
    ]


def _preflight_density_nodes(config: dict[str, Any]) -> list[dict[str, Any]]:
    cluster = config["cluster"]
    azs = list(config["network"]["azs"])
    host_ids = [host["host_id"] for host in config.get("hosts", [{"host_id": "local"}])]
    shards = int(cluster["shards"])
    replicas = int(cluster["replicas_per_shard"])
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
                "client_port": int(cluster["port_base"]) + ordinal,
                "cluster_bus_port": int(cluster.get("cluster_bus_port_base", int(cluster["port_base"]) + 10000)) + ordinal,
            }
        )
        ordinal += 1
    for shard in range(shards):
        for replica in range(replicas):
            shard_id = f"shard-{shard:04d}"
            nodes.append(
                {
                    "logical_id": f"{shard_id}-replica-{replica:02d}",
                    "shard_id": shard_id,
                    "role": "replica",
                    "az_id": _preflight_replica_az(azs, azs[shard % len(azs)], shard, replica),
                    "host_id": host_ids[ordinal % len(host_ids)],
                    "ordinal": ordinal,
                    "client_port": int(cluster["port_base"]) + ordinal,
                    "cluster_bus_port": int(cluster.get("cluster_bus_port_base", int(cluster["port_base"]) + 10000)) + ordinal,
                }
            )
            ordinal += 1
    return nodes


def _preflight_replica_az(azs: list[str], primary_az: str, shard: int, replica: int) -> str:
    if len(azs) == 1:
        return azs[0]
    candidates = [az for az in azs if az != primary_az]
    return candidates[(shard + replica) % len(candidates)]


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
