from __future__ import annotations

import math
import os
from copy import deepcopy
from typing import Any

SERVER_PROFILES: dict[str, dict[str, Any]] = {
    "correctness": {
        "io_threads": 1,
        "io_threads_auto": False,
        "io_threads_max_per_node": 1,
        "io_threads_max_total": 256,
        "log_format": "text",
        "node_memory_limit_mb": 64,
    },
    "one_b_dev": {
        "io_threads": 1,
        "io_threads_auto": False,
        "io_threads_max_per_node": 2,
        "io_threads_max_total": 256,
        "log_format": "text",
        "node_memory_limit_mb": 64,
    },
    "one_b_perf": {
        "io_threads": 2,
        "io_threads_auto": True,
        "io_threads_max_per_node": 8,
        "io_threads_max_total": 512,
        "log_format": "json",
        "node_memory_limit_mb": 64,
    },
}


def node_count_from_config(config: dict[str, Any]) -> int:
    cluster = config.get("cluster", {})
    return int(cluster.get("shards", 0) or 0) * (1 + int(cluster.get("replicas_per_shard", 0) or 0))


def server_profile_defaults(name: str) -> dict[str, Any]:
    if name not in SERVER_PROFILES:
        raise ValueError(f"unknown server_profile {name!r}")
    return deepcopy(SERVER_PROFILES[name])


def normalize_server_profile_config(config: dict[str, Any]) -> dict[str, Any]:
    runtime = config.setdefault("runtime", {})
    cluster = config.setdefault("cluster", {})
    profile_name = str(runtime.get("server_profile") or "one_b_dev")
    defaults = server_profile_defaults(profile_name)
    valkey = runtime.setdefault("valkey", {})
    for key in ["io_threads", "io_threads_auto", "io_threads_max_per_node", "io_threads_max_total", "log_format"]:
        valkey.setdefault(key, defaults[key])
    cluster.setdefault("node_memory_limit_mb", defaults["node_memory_limit_mb"])
    runtime["server_profile"] = profile_name
    config["_effective_server_profile"] = compute_effective_server_profile(config)
    return config


def compute_effective_server_profile(
    config: dict[str, Any],
    *,
    host_cpu_count: int | None = None,
    nodehost_count: int | None = None,
) -> dict[str, Any]:
    runtime = config.get("runtime", {})
    valkey = runtime.get("valkey", {})
    cluster = config.get("cluster", {})
    profile_name = str(runtime.get("server_profile") or "one_b_dev")
    defaults = server_profile_defaults(profile_name)
    node_count = max(1, node_count_from_config(config))
    host_cpu = int(host_cpu_count or os.cpu_count() or 1)
    estimated_nodehosts = int(nodehost_count or _estimated_nodehost_count(config, node_count) or 1)
    requested_io = _positive_int(valkey.get("io_threads"), int(defaults["io_threads"]))
    max_per_node = max(1, _positive_int(valkey.get("io_threads_max_per_node"), int(defaults["io_threads_max_per_node"])))
    max_total = max(node_count, _positive_int(valkey.get("io_threads_max_total"), int(defaults["io_threads_max_total"])))
    auto_enabled = bool(valkey.get("io_threads_auto", defaults["io_threads_auto"]))
    log_format = str(valkey.get("log_format") or defaults["log_format"])
    requested_memory = _positive_int(cluster.get("node_memory_limit_mb"), int(defaults["node_memory_limit_mb"]))

    reasons: list[str] = []
    candidate = requested_io
    auto_candidate = 1
    if auto_enabled:
        cpu_per_nodehost = max(1, host_cpu // max(estimated_nodehosts, 1))
        auto_candidate = max(1, min(max_per_node, cpu_per_nodehost))
        candidate = min(candidate, auto_candidate) if requested_io > 1 else auto_candidate
        reasons.append(f"io_threads_auto host_cpu={host_cpu} nodehosts={estimated_nodehosts} auto_candidate={auto_candidate}")

    per_node_limited = min(candidate, max_per_node)
    if requested_io > max_per_node:
        reasons.append(f"requested_io_threads {requested_io} exceeds io_threads_max_per_node {max_per_node}")
    total_allowed_per_node = max(1, max_total // node_count)
    effective_io = max(1, min(per_node_limited, total_allowed_per_node))
    if per_node_limited > total_allowed_per_node:
        reasons.append(
            f"total thread budget limits io_threads from {per_node_limited} to {effective_io} "
            f"for {node_count} nodes and io_threads_max_total {max_total}"
        )
    status = "PASS" if not reasons else "DEGRADED_WITH_REASON"
    total_threads = node_count * effective_io
    return {
        "schema_version": "v1",
        "artifact_type": "effective_server_profile",
        "server_profile": profile_name,
        "requested_io_threads": requested_io,
        "effective_io_threads": effective_io,
        "io_threads_auto": auto_enabled,
        "io_threads_auto_candidate": auto_candidate if auto_enabled else "SKIPPED_WITH_REASON",
        "io_threads_max_per_node": max_per_node,
        "io_threads_max_total": max_total,
        "total_valkey_threads": total_threads,
        "io_thread_budget_status": status if total_threads <= max_total else "FAIL",
        "io_thread_budget_reason": reasons or ["within per-node and total io-thread budget"],
        "requested_node_memory_limit_mb": requested_memory,
        "effective_node_memory_limit_mb": requested_memory,
        "memory_budget_status": "PENDING_PREFLIGHT",
        "log_format": log_format,
        "host_cpu_count": host_cpu,
        "logical_node_count": node_count,
        "nodehost_count": estimated_nodehosts,
        "runtime_memory_limit_enforced": True,
        "runtime_memory_limit_method": "valkey_maxmemory",
    }


def valkey_config_lines(profile: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    io_threads = int(profile.get("effective_io_threads", 1) or 1)
    if io_threads > 1:
        lines.append(f"io-threads {io_threads}")
    memory_mb = int(profile.get("effective_node_memory_limit_mb", 0) or 0)
    if memory_mb > 0:
        lines.append(f"maxmemory {memory_mb}mb")
    return lines


def node_effective_fields(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "effective_server_profile": profile["server_profile"],
        "effective_io_threads": int(profile.get("effective_io_threads", 1) or 1),
        "effective_node_memory_limit_mb": int(profile.get("effective_node_memory_limit_mb", 0) or 0),
        "runtime_memory_limit_enforced": bool(profile.get("runtime_memory_limit_enforced")),
        "runtime_memory_limit_method": profile.get("runtime_memory_limit_method", "MISSING"),
    }


def _estimated_nodehost_count(config: dict[str, Any], node_count: int) -> int:
    runtime = config.get("runtime", {})
    max_per = max(1, int(runtime.get("max_logical_nodes_per_nodehost", 25) or 25))
    max_nodehosts = max(1, int(runtime.get("max_nodehosts", 64) or 64))
    return min(max_nodehosts, max(1, math.ceil(node_count / max_per)))


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(1, parsed)
