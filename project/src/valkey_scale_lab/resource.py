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
from valkey_scale_lab import placement
from valkey_scale_lab.cluster_timeout import compute_effective_cluster_timeout
from valkey_scale_lab.config.validation import (
    is_exact_1280_native_ecs_profile,
    is_exact_2000_local_full_flow_profile,
    load_effective_config,
    validate_semantics,
)
from valkey_scale_lab.execution import (
    ExecutionSelectionError,
    exact_200_selection_allowed,
    exact_1280_selection_allowed,
    exact_2000_selection_allowed,
    resolve_profile,
)
from valkey_scale_lab.nodehost_density import NodehostDensityError, build_nodehost_density_plan
from valkey_scale_lab.runtime.backends import BackendNotImplementedError, resolve_backend
from valkey_scale_lab.runtime.host_inventory import load_host_inventory
from valkey_scale_lab.runtime.host_transport import MultiplexedSshTransport, TransportError
from valkey_scale_lab.server_profile import compute_effective_server_profile

CREATED_AT = "2026-06-28T00:00:00Z"
DEFAULT_PREFLIGHT_CAPABILITY = "scale_ladder"

#: Check statuses that do not block a run. `SKIPPED_WITH_REASON` is the
#: artifact-level vocabulary this repository already uses for evidence that is
#: absent for a stated reason, and the schema's own `status` enum carries it.
#: Only a check this module skips deliberately can hold it - `_check` still
#: produces `PASS` or `FAIL` and nothing else.
NON_BLOCKING_CHECK_STATUSES = frozenset({"PASS", "SKIPPED_WITH_REASON"})


class ResourcePreflightError(RuntimeError):
    pass


def run_resource_preflight(
    config_path: str | Path,
    out_path: str | Path,
    dry_run: bool = False,
    *,
    capability_id: str | None = None,
    scenario: str | None = None,
    profile_id: str | None = None,
    backend_id: str | None = None,
    fleet_hosts: list[dict[str, Any]] | None = None,
    operator_opt_in: bool = False,
    cost_acknowledged: bool = False,
    global_config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = load_effective_config(config_path, global_config_path=global_config_path, cli_overrides=cli_overrides)
    if dry_run:
        config.setdefault("runtime", {})["dry_run"] = True
    node_count = int(config["cluster"]["shards"]) * (1 + int(config["cluster"]["replicas_per_shard"]))
    if profile_id is not None:
        try:
            resolve_profile(profile_id, requested_nodes=node_count)
        except ExecutionSelectionError as exc:
            raise ResourcePreflightError(str(exc)) from exc
    capability_id = capability_id or DEFAULT_PREFLIGHT_CAPABILITY
    scenario_name = scenario or capability_id
    exact_200_exception = _is_exact_200_bounded_exception(
        config,
        node_count,
        dry_run,
        capability_id=capability_id,
        scenario=scenario_name,
        profile_id=profile_id,
    )
    exact_2000_exception = _is_exact_2000_local_full_flow_exception(
        config,
        node_count,
        dry_run,
        capability_id=capability_id,
        scenario=scenario_name,
        profile_id=profile_id,
        operator_opt_in=operator_opt_in,
        cost_acknowledged=cost_acknowledged,
    )
    exact_1280_exception = _is_exact_1280_native_ecs_exception(
        config,
        node_count,
        dry_run,
        capability_id=capability_id,
        scenario=scenario_name,
        profile_id=profile_id,
        operator_opt_in=operator_opt_in,
        cost_acknowledged=cost_acknowledged,
    )
    semantic_errors = _semantic_errors_for_preflight(
        config,
        allow_exact_200=exact_200_exception,
        allow_exact_2000=exact_2000_exception or exact_1280_exception,
    )
    run_id = f"{capability_id}-resource-preflight-{node_count}-20260628"
    checks: list[dict[str, Any]] = []
    density_plan: dict[str, Any] | None = None
    density_error: str | None = None
    try:
        density_plan = build_nodehost_density_plan(
            config=config,
            nodes=_preflight_density_nodes(config),
            run_id=run_id,
            assign=True,
            # The same fleet the run itself will be placed on. Without it this
            # plan says `host_id: "local"` about a run that will place its
            # nodehosts on named hosts, which is the artifact
            # `native_backend_slice_map.md` §6.2 uses to argue that placement is
            # planning. `None` for every backend that names no fleet, and then
            # nothing about this plan changes.
            #
            # The caller's fleet wins over this document's, because on a gate run
            # they are not the same document: `_prepare_runtime` preflights the
            # *profile's* canonical template - `scale_200.yaml` for exact-200 -
            # and the fleet is named by the run's own configuration. Measured:
            # without this the first real exact-200 was refused by a memory check
            # comparing against the controller, having found no fleet to compare
            # against, in a preflight that had one two frames up the stack.
            fleet_hosts=fleet_hosts if fleet_hosts is not None else _fleet_placement_records(config),
        )
    except NodehostDensityError as exc:
        density_error = str(exc)

    checks.append(_check("config_semantics", not semantic_errors, {"errors": semantic_errors}))
    checks.append(
        _check(
            "node_count_limit",
            node_count <= 100
            or dry_run
            or exact_200_exception
            or exact_2000_exception
            or exact_1280_exception,
            {
                "node_count": node_count,
                "default_cap": 100,
                "selected_capability_id": (
                    capability_id
                    if exact_200_exception or exact_2000_exception or exact_1280_exception
                    else "MISSING"
                ),
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
                    "capability_id": capability_id,
                    "scenario_name": scenario_name,
                    "profile_name": config.get("profile_name", "MISSING"),
                    "dry_run": dry_run or config.get("runtime", {}).get("dry_run") is True,
                    "scale_profile": config.get("scale_profile", {}),
                },
            )
        )
    if node_count == 1280:
        checks.append(
            _check(
                "exact_1280_native_ecs_opt_in",
                exact_1280_exception,
                {
                    "node_count": node_count,
                    "capability_id": capability_id,
                    "scenario_name": scenario_name,
                    "profile_id": profile_id or "MISSING",
                    "profile_name": config.get("profile_name", "MISSING"),
                    "operator_opt_in": operator_opt_in,
                    "cost_acknowledged": cost_acknowledged,
                    "runtime_provider": config.get("runtime", {}).get("provider", "MISSING"),
                    "runtime_dry_run": config.get("runtime", {}).get("dry_run"),
                },
            )
        )
    if node_count == 2000:
        checks.append(
            _check(
                "exact_2000_local_full_flow_opt_in",
                exact_2000_exception,
                {
                    "node_count": node_count,
                    "capability_id": capability_id,
                    "scenario_name": scenario_name,
                    "profile_id": profile_id or "MISSING",
                    "profile_name": config.get("profile_name", "MISSING"),
                    "operator_opt_in": operator_opt_in,
                    "cost_acknowledged": cost_acknowledged,
                    "runtime_dry_run": config.get("runtime", {}).get("dry_run"),
                    "workload_enabled": config.get("workload", {}).get("enabled"),
                    "scale_profile": config.get("scale_profile", {}),
                },
            )
        )
    docker_required = _requires_local_docker_daemon(backend_id)
    if docker_required:
        docker_details = _docker_details()
        checks.append(_check("docker_available", docker_details["available"], docker_details))
    else:
        checks.append(
            _skipped(
                "docker_available",
                f"backend {backend_id!r} declares requires_local_docker_daemon=false",
                {"backend_id": backend_id},
            )
        )
    checks.append(_check("cpu_count", (os.cpu_count() or 0) >= 2, {"cpu_count": os.cpu_count() or "MISSING"}))
    effective_profile = compute_effective_server_profile(
        config,
        nodehost_count=int((density_plan or {}).get("actual_nodehost_count", 0) or 0) or None,
    )
    effective_timeout = compute_effective_cluster_timeout(config)
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
    if docker_required:
        checks.append(_cleanup_state_check(capability_id, scenario_name, node_count))
    else:
        # This check asks `docker ps` and `docker network ls` what a previous run
        # of this capability left behind. A backend with no local daemon has its
        # own answer to the same question and it is not the controller's:
        # `reclaim_run` clears the run's residue on the hosts, and the lifecycle
        # calls it a few lines after this preflight returns.
        checks.append(
            _skipped(
                "previous_cleanup_state",
                f"backend {backend_id!r} declares requires_local_docker_daemon=false; "
                "pre-run reclaim happens on the hosts, in reclaim_run",
                {"backend_id": backend_id, "node_count": node_count},
            )
        )

    can_run = all(item["status"] in NON_BLOCKING_CHECK_STATUSES for item in checks)
    report = {
        "schema_version": "v1",
        "artifact_type": "resource_preflight",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS" if can_run else "FAIL",
        "node_count": node_count,
        "nodes_requested": node_count,
        "can_run": can_run,
        "scenario_name": scenario_name,
        "profile_id": profile_id or "MISSING",
        "config_path": str(config_path),
        "dry_run": dry_run,
        "bounded_exception": {
            "capability_id": capability_id if exact_200_exception else "MISSING",
            "scenario_name": scenario_name if exact_200_exception else "MISSING",
            "node_count": 200 if exact_200_exception else "MISSING",
            "default_max_nodes": 100,
            "profile_exception_nodes": config.get("scale_profile", {}).get("bounded_exception_nodes", "MISSING"),
        },
        "controlled_scale_exception": {
            "capability_id": capability_id if exact_2000_exception else "MISSING",
            "scenario_name": scenario_name if exact_2000_exception else "MISSING",
            "node_count": 2000 if exact_2000_exception else "MISSING",
            "profile_id": profile_id if exact_2000_exception else "MISSING",
            "operator_opt_in": operator_opt_in if exact_2000_exception else False,
            "cost_acknowledged": cost_acknowledged if exact_2000_exception else False,
            "runtime_dry_run": config.get("runtime", {}).get("dry_run", "MISSING"),
            "workload_enabled": config.get("workload", {}).get("enabled", "MISSING"),
        },
        "host": _host_facts(),
        "resource_estimates": _resource_estimates(
            node_count,
            int(effective_profile["effective_node_memory_limit_mb"]),
            density_plan=density_plan,
        ),
        "server_profile": effective_profile,
        "cluster_timeout": effective_timeout,
        "requested_io_threads": effective_profile["requested_io_threads"],
        "effective_io_threads": effective_profile["effective_io_threads"],
        "requested_node_memory_limit_mb": effective_profile["requested_node_memory_limit_mb"],
        "effective_node_memory_limit_mb": effective_profile["effective_node_memory_limit_mb"],
        "io_thread_budget_status": effective_profile["io_thread_budget_status"],
        "memory_budget_status": effective_profile["memory_budget_status"],
        "requested_cluster_node_timeout_ms": effective_timeout["requested_cluster_node_timeout_ms"],
        "effective_cluster_node_timeout_ms": effective_timeout["effective_cluster_node_timeout_ms"],
        "cluster_node_timeout_source": effective_timeout["cluster_node_timeout_source"],
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


def _is_exact_200_bounded_exception(
    config: dict[str, Any],
    node_count: int,
    dry_run_arg: bool,
    *,
    capability_id: str,
    scenario: str,
    profile_id: str | None,
) -> bool:
    scale_profile = config.get("scale_profile", {})
    runtime = config.get("runtime", {})
    safety = config.get("safety", {})
    return (
        node_count == 200
        and profile_id == "exact-200"
        and exact_200_selection_allowed(capability_id=capability_id, scenario_id=scenario)
        and config.get("profile_name") == "scale_200"
        and int(scale_profile.get("bounded_exception_nodes", 0) or 0) == 200
        and int(safety.get("default_max_nodes", 0) or 0) == 100
        and safety.get("allow_1000_nodes") is False
        and dry_run_arg is False
        and runtime.get("dry_run") is False
    )


def _is_exact_1280_native_ecs_exception(
    config: dict[str, Any],
    node_count: int,
    dry_run_arg: bool,
    *,
    capability_id: str,
    scenario: str,
    profile_id: str | None,
    operator_opt_in: bool,
    cost_acknowledged: bool,
) -> bool:
    """M4's exception at preflight, and the preflight is the point of it.

    Admitting the run is not the same as the run being possible: at 1280 nodes
    on eight hosts this is what compares 160 nodes per host against 7900 MiB of
    RAM, which is why `m4_density_calibration.md` §5 has the node memory limit
    dropping 64 -> 32 there. The exception waives the *cap*, never the check.
    """

    runtime = config.get("runtime", {})
    return (
        node_count == 1280
        and profile_id == "exact-1280"
        and exact_1280_selection_allowed(
            capability_id=capability_id,
            scenario_id=scenario,
        )
        and is_exact_1280_native_ecs_profile(config)
        and dry_run_arg is False
        and runtime.get("dry_run") is False
        and operator_opt_in is True
        and cost_acknowledged is True
    )


def _is_exact_2000_local_full_flow_exception(
    config: dict[str, Any],
    node_count: int,
    dry_run_arg: bool,
    *,
    capability_id: str,
    scenario: str,
    profile_id: str | None,
    operator_opt_in: bool,
    cost_acknowledged: bool,
) -> bool:
    runtime = config.get("runtime", {})
    return (
        node_count == 2000
        and profile_id == "exact-2000"
        and exact_2000_selection_allowed(
            capability_id=capability_id,
            scenario_id=scenario,
        )
        and is_exact_2000_local_full_flow_profile(config)
        and dry_run_arg is False
        and runtime.get("dry_run") is False
        and operator_opt_in is True
        and cost_acknowledged is True
    )


def _semantic_errors_for_preflight(
    config: dict[str, Any],
    *,
    allow_exact_200: bool,
    allow_exact_2000: bool,
) -> list[dict[str, Any]]:
    errors = validate_semantics(config)
    if not allow_exact_200 and not allow_exact_2000:
        return errors
    allowed_codes = {"NODE_CAP_EXCEEDED"}
    if allow_exact_2000:
        allowed_codes.update(
            {
                "REAL_EXECUTION_ABOVE_200_FORBIDDEN",
                "MISSING_200_PLUS_DRY_RUN_PROFILE",
                "WORKLOAD_ABOVE_200_FORBIDDEN",
                "MISSING_1000_ALLOW",
                "MISSING_1000_ENV_GUARD",
                "MISSING_1000_DRY_RUN",
                "MISSING_1000_SCALE_PROFILE",
            }
        )
    filtered: list[dict[str, Any]] = []
    for error in errors:
        if error.get("code") in allowed_codes:
            continue
        filtered.append(error)
    return filtered


def _check(name: str, ok: bool, details: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "status": "PASS" if ok else "FAIL", "details": details}


def _skipped(name: str, reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """A check that does not apply to this run, recorded rather than dropped.

    Omitting the row would leave two preflights differing by a missing name with
    nothing saying why, which is the shape of fabricated evidence this product
    forbids. The reason is the evidence.

    It sits beside `status` rather than inside `details` because that is where
    the §12 missing-evidence taxonomy looks: `_validate_missing_taxonomy` walks
    every object of every raw source and requires a non-empty `reason` next to
    any status in `MISSING_STATUSES`. Measured - the first native exact-50 ran
    all 860 s and was then refused by exactly that rule.
    """

    return {
        "name": name,
        "status": "SKIPPED_WITH_REASON",
        "reason": reason,
        "details": dict(details or {}),
    }


def _requires_local_docker_daemon(backend_id: str | None) -> bool:
    """Whether this run needs a Docker daemon on the machine it is driven from.

    The backend registry has declared this since `39e31b1a`, which is where the
    Gate's own daemon check moved when backend selection became data. The
    preflight kept asking unconditionally, so a native run driven from a
    controller with no daemon was blocked by two checks about a runtime it does
    not use - measured on the M3-B controller, where `docker_available` and
    `previous_cleanup_state` were the only two failures of fifteen.

    A caller that does not name a backend gets the answer it always got. That is
    deliberate: `cli preflight` and the scale ladder ask about a machine rather
    than about a run, and quietly dropping a Docker check for them would weaken a
    safety check on the strength of an omission.
    """

    if backend_id is None:
        return True
    try:
        return bool(resolve_backend(backend_id).requires_local_docker_daemon)
    except BackendNotImplementedError:
        return True


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


def _fleet_placement_records(config: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The fleet this run was given, or `None` when it was given none.

    The same expression `docker_runtime._process_nodehosts` uses, read here for
    the same reason: placement is planning, and the preflight plans.
    """

    path = config.get("runtime", {}).get("host_inventory_path")
    if not path:
        return None
    try:
        return load_host_inventory(path).placement_records()
    except Exception:  # noqa: BLE001
        # A manifest that cannot be read is `nodehost_density_plan`'s failure to
        # report, not this helper's to raise: the plan below records the reason
        # and the check fails with it.
        return None


#: What the preflight asks a fleet host for. `MemAvailable` rather than
#: `MemFree`, because it is the same quantity `_host_available_memory_mb` reads
#: locally, so the two arms of the check compare like with like.
HOST_MEMORY_ARGV: tuple[str, ...] = (
    "sh",
    "-c",
    "awk '/MemAvailable/{print $2}' /proc/meminfo",
)


def _fleet_nodehost_memory(
    density_plan: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Each placed nodehost's host, and how much memory that host reports.

    Read from the hosts, because nothing else can answer it: a manifest declares
    where a host is, not what it has free at preflight time. One transport for
    the whole check, closed before returning - a preflight that left ssh masters
    running would be leaking the resource item 1.4 exists to account for.
    """

    nodehosts = [
        item
        for item in (density_plan or {}).get("nodehosts", [])
        if item.get("host_control_endpoint")
    ]
    if not nodehosts:
        return {}, None

    readings: dict[str, dict[str, Any]] = {}
    transport = MultiplexedSshTransport()
    try:
        for nodehost in nodehosts:
            nodehost_id = str(nodehost["nodehost_id"])
            entry: dict[str, Any] = {"host_id": str(nodehost.get("host_id", "MISSING"))}
            try:
                result = transport.run(
                    nodehost["host_control_endpoint"], list(HOST_MEMORY_ARGV), timeout=30
                )
            except TransportError as error:
                entry["error"] = str(error)[:200]
            else:
                if result.returncode != 0 or not result.stdout.strip().isdigit():
                    entry["error"] = (result.stderr or result.stdout).strip()[:200] or "no answer"
                else:
                    entry["host_available_memory_mb"] = int(result.stdout.strip()) // 1024
            readings[nodehost_id] = entry
    finally:
        transport.close()
    return readings, None


def _memory_check(node_count: int, memory_limit_mb: int, *, density_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    required_mb = node_count * max(memory_limit_mb, 1)
    projected_nodehost = _projected_nodehost_memory(memory_limit_mb, density_plan, node_count)
    fleet_readings, _ = _fleet_nodehost_memory(density_plan)
    if fleet_readings:
        # The run's memory is consumed where its nodes are. Comparing the whole
        # requirement against the controller asked the wrong machine: measured on
        # the M3-B controller, exact-200 wanted 12800 MB against 12117 MB there
        # while each of eight fleet hosts held 1600 MB against 7.7 GiB. Every
        # nodehost is compared against the host it is placed on, and a host that
        # will not answer fails the check rather than being assumed to fit.
        rows = []
        for nodehost_id in sorted(fleet_readings):
            reading = fleet_readings[nodehost_id]
            projected = int(projected_nodehost.get(nodehost_id, 0))
            available = reading.get("host_available_memory_mb")
            rows.append(
                {
                    "nodehost_id": nodehost_id,
                    "host_id": reading["host_id"],
                    "projected_memory_mb": projected,
                    "host_available_memory_mb": available if available is not None else "MISSING",
                    "fits": isinstance(available, int) and projected <= available,
                    **({"error": reading["error"]} if "error" in reading else {}),
                }
            )
        ok = bool(rows) and all(row["fits"] for row in rows)
        return _check(
            "memory_budget",
            ok,
            {
                "required_memory_mb": required_mb,
                "node_count_times_node_memory_limit_mb": required_mb,
                "node_memory_limit_mb": memory_limit_mb,
                "projected_nodehost_memory_mb": projected_nodehost,
                "compared_against": "placed_host",
                "per_nodehost": rows,
                "can_run": ok,
                "reason": (
                    "every nodehost fits the host it is placed on"
                    if ok
                    else "at least one nodehost does not fit the host it is placed on"
                ),
                "status_note": "read from each placed host",
            },
        )
    host_available = _host_available_memory_mb()
    ok = isinstance(host_available, int) and required_mb <= host_available
    return _check(
        "memory_budget",
        ok,
        {
            "compared_against": "controller",
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
        "workload_overhead": "low_nonzero_failover_latency_exact_200_profile" if node_count == 200 else "standard_profile",
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
                "az_id": placement.primary_az(azs, shard),
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
                    "az_id": placement.replica_az(azs, shard, replica),
                    "host_id": host_ids[ordinal % len(host_ids)],
                    "ordinal": ordinal,
                    "client_port": int(cluster["port_base"]) + ordinal,
                    "cluster_bus_port": int(cluster.get("cluster_bus_port_base", int(cluster["port_base"]) + 10000)) + ordinal,
                }
            )
            ordinal += 1
    return nodes


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


def _cleanup_state_check(capability_id: str, scenario: str, node_count: int) -> dict[str, Any]:
    run_id = f"{capability_id}-{scenario}-20260628"
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
                f"label=org.valkey-scale-lab.capability_id={capability_id}",
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
                f"label=org.valkey-scale-lab.capability_id={capability_id}",
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
