from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence

from contracts import ContractError


def _run(argv: Sequence[str], *, cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(argv),
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(f"cleanup command cannot run ({' '.join(argv)}): {exc}") from exc


def _owned_docker_resources() -> tuple[list[str], list[str]]:
    containers = _run(
        [
            "docker",
            "ps",
            "-a",
            "-q",
            "--filter",
            "label=org.valkey-scale-lab.project=valkey-scale-lab",
        ],
        cwd=Path.cwd(),
        timeout=30,
    )
    networks = _run(
        [
            "docker",
            "network",
            "ls",
            "-q",
            "--filter",
            "label=org.valkey-scale-lab.project=valkey-scale-lab",
        ],
        cwd=Path.cwd(),
        timeout=30,
    )
    if containers.returncode != 0 or networks.returncode != 0:
        raise ContractError("Docker daemon is unavailable for recovery cleanup")

    def select(ids: list[str], kind: str) -> list[str]:
        selected: list[str] = []
        for resource_id in ids:
            inspect = _run(
                ["docker", "inspect", resource_id, "--format", "{{json .Config.Labels}}"]
                if kind == "container"
                else ["docker", "network", "inspect", resource_id, "--format", "{{json .Labels}}"],
                cwd=Path.cwd(),
                timeout=30,
            )
            if inspect.returncode != 0:
                raise ContractError(f"cannot inspect owned Docker {kind} {resource_id}")
            try:
                labels: Any = json.loads(inspect.stdout)
            except json.JSONDecodeError as exc:
                raise ContractError(f"Docker {kind} labels are invalid") from exc
            project = labels.get("org.valkey-scale-lab.project") if isinstance(labels, dict) else None
            if project == "valkey-scale-lab":
                selected.append(resource_id)
        return selected

    container_ids = [line for line in containers.stdout.splitlines() if line]
    network_ids = [line for line in networks.stdout.splitlines() if line]
    return select(container_ids, "container"), select(network_ids, "network")


def cleanup_owned_docker() -> None:
    containers, networks = _owned_docker_resources()
    if containers:
        result = _run(["docker", "rm", "-f", *containers], cwd=Path.cwd(), timeout=180)
        if result.returncode != 0:
            raise ContractError(f"cannot remove owned containers: {result.stderr[-1000:]}")
    if networks:
        result = _run(["docker", "network", "rm", *networks], cwd=Path.cwd(), timeout=180)
        if result.returncode != 0:
            raise ContractError(f"cannot remove owned networks: {result.stderr[-1000:]}")
    remaining_containers, remaining_networks = _owned_docker_resources()
    if remaining_containers or remaining_networks:
        raise ContractError("owned Docker resources remain after cleanup")


def cleanup_runtime_root(repo_root: Path, runtime_root: Path) -> None:
    runtime_root = runtime_root.resolve()
    temp_root = Path(os.environ.get("RUNNER_TEMP", "/tmp")).resolve()
    try:
        runtime_root.relative_to(temp_root)
    except ValueError as exc:
        raise ContractError("runtime cleanup root must stay under RUNNER_TEMP") from exc
    if runtime_root == temp_root:
        raise ContractError("runtime cleanup root cannot equal RUNNER_TEMP")
    worktree = runtime_root / "worker-worktree"
    if worktree.exists():
        _run(["git", "worktree", "remove", "--force", str(worktree)], cwd=repo_root)
    if runtime_root.exists():
        shutil.rmtree(runtime_root)
    _run(["git", "worktree", "prune"], cwd=repo_root)


def recover(repo_root: Path, runtime_root: Path, *, require_docker: bool) -> None:
    cleanup_runtime_root(repo_root, runtime_root)
    if require_docker:
        cleanup_owned_docker()
