from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__
from valkey_scale_lab.config.simple_yaml import parse_config_file
from valkey_scale_lab.config.validation import normalize_config, validate_semantics

CREATED_AT = "2026-06-28T00:00:00Z"


class ResourcePreflightError(RuntimeError):
    pass


def run_resource_preflight(config_path: str | Path, out_path: str | Path, dry_run: bool = False) -> dict[str, Any]:
    config = normalize_config(parse_config_file(config_path))
    if dry_run:
        config.setdefault("runtime", {})["dry_run"] = True
    semantic_errors = validate_semantics(config)
    node_count = int(config["cluster"]["shards"]) * (1 + int(config["cluster"]["replicas_per_shard"]))
    phase_id = _phase_for_node_count(node_count)
    run_id = f"{phase_id}-resource-preflight-{node_count}-20260628"
    checks: list[dict[str, Any]] = []

    checks.append(_check("config_semantics", not semantic_errors, {"errors": semantic_errors}))
    checks.append(_check("node_count_limit", node_count <= 100 or dry_run, {"node_count": node_count, "default_cap": 100}))
    checks.append(_check("docker_available", _docker_available(), {}))
    checks.append(_check("cpu_count", (os.cpu_count() or 0) >= 2, {"cpu_count": os.cpu_count() or "MISSING"}))
    checks.append(_memory_check(node_count, int(config["cluster"].get("node_memory_limit_mb") or 0)))
    checks.append(_disk_check(Path("artifacts")))
    checks.append(_port_check(int(config["cluster"]["port_base"]), node_count, "client_ports"))
    checks.append(_port_check(int(config["cluster"]["cluster_bus_port_base"]), node_count, "cluster_bus_ports"))
    checks.append(_cleanup_state_check(phase_id, _scenario_for_node_count(node_count), node_count))

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
        "can_run": can_run,
        "config_path": str(config_path),
        "dry_run": dry_run,
        "checks": checks,
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _phase_for_node_count(node_count: int) -> str:
    if node_count in {10, 30}:
        return "P12_SCALE_LADDER_10_30"
    if node_count in {50, 100}:
        return "P13_SCALE_LADDER_50_100"
    if node_count >= 1000:
        return "P14_SCALE_1000_OPTIN_DRYRUN"
    return "P12_SCALE_LADDER_10_30"


def _scenario_for_node_count(node_count: int) -> str:
    return f"scale_{node_count}"


def _check(name: str, ok: bool, details: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "status": "PASS" if ok else "FAIL", "details": details}


def _docker_available() -> bool:
    try:
        proc = subprocess.run(["docker", "info", "--format", "{{json .ServerVersion}}"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    except Exception:
        return False
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _memory_check(node_count: int, memory_limit_mb: int) -> dict[str, Any]:
    required_mb = max(node_count * max(memory_limit_mb, 1), node_count * 32)
    # Mac Docker memory limits are owned by Docker Desktop and not always visible here, so this is a conservative floor.
    return _check(
        "memory_budget",
        required_mb <= 8192,
        {"required_memory_mb": required_mb, "node_memory_limit_mb": memory_limit_mb, "status_note": "host-visible estimate"},
    )


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
