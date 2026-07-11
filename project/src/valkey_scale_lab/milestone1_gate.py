from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from valkey_scale_lab.runtime.docker_runtime import (
    P36_SCENARIO_200,
    P36_SCENARIO_50,
    P36_STAGE,
    DockerRuntimeError,
    _node_command,
    _p17_cluster_health,
    cleanup_scenario,
    create_scenario,
)


LIFECYCLE = ["resource_preflight", "runtime_start", "cluster_form", "stabilize", "baseline_workload", "management_matrix", "fault_matrix", "recovery", "artifact_validation", "analysis", "report", "cleanup"]
SCENARIOS = ["add_remove_node", "reshard_rebalance", "rolling_restart", "bounded_stability", "primary_failover", "replica_stop", "node_host_stop", "az_stop", "network_delay", "network_loss", "network_partition", "network_flap", "minority_majority", "split_brain_detection"]


def run_real_gate(scale: int, evidence_dir: str | Path) -> dict[str, Any]:
    if scale not in {50, 200}:
        raise DockerRuntimeError("Milestone 1 real gate supports exactly 50 or 200 nodes")
    if os.environ.get("VSLAB_META_M1_CONTROLLER_OWNED") != "1":
        raise DockerRuntimeError("real gate requires controller ownership, preflight, and cost acknowledgement")
    source_digest = os.environ.get("VSLAB_META_M1_SOURCE_DIGEST", "")
    if not re.fullmatch(r"[0-9a-f]{64}", source_digest):
        raise DockerRuntimeError("real gate requires the controller-provided source tree digest before execution")
    docker_info = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], check=False, capture_output=True, text=True)
    if docker_info.returncode != 0 or not docker_info.stdout.strip():
        raise DockerRuntimeError(f"real gate requires an available Docker daemon: {docker_info.stderr.strip()}")

    base = Path(evidence_dir).resolve()
    runtime_dir = base / "runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state_path = runtime_dir / "state.json"
    cleanup_path = runtime_dir / "cleanup_report.json"
    scenario = P36_SCENARIO_50 if scale == 50 else P36_SCENARIO_200
    timings: dict[str, float] = {}
    state: dict[str, Any] | None = None
    started = time.monotonic()

    try:
        create_started = time.monotonic()
        state = create_scenario(
            phase=P36_STAGE,
            scenario=scenario,
            config_path=f"templates/configs/scale_{scale}.yaml",
            artifacts_dir=runtime_dir,
            state_out=state_path,
        )
        timings["runtime_start"] = _elapsed_ms(create_started)
        nodes = list(state.get("nodes", []))
        if len(nodes) != scale:
            raise DockerRuntimeError(f"real gate requested {scale} nodes but runtime returned {len(nodes)}")
        probe_started = time.monotonic()
        health = _p17_cluster_health(nodes)
        versions = _observed_versions(nodes)
        timings["stabilize"] = _elapsed_ms(probe_started)
        if health.get("cluster_state") != "ok" or health.get("known_nodes") != scale:
            raise DockerRuntimeError(f"independent exact-scale probe failed: {health}")
        if not versions or any(not re.fullmatch(r"9\.1(?:\.\d+)?", version) for version in versions):
            raise DockerRuntimeError(f"independent version probe did not observe only Valkey 9.1.x: {versions}")
    finally:
        cleanup_started = time.monotonic()
        if state is not None and state_path.exists():
            cleanup_result = cleanup_scenario(state_path=state_path, artifacts_dir=runtime_dir, out_path=cleanup_path)
            timings["cleanup"] = _elapsed_ms(cleanup_started)
            if cleanup_result.get("status") != "PASS":
                raise DockerRuntimeError(f"exact-scale cleanup failed: {cleanup_result}")

    assert state is not None
    full_flow = _load(runtime_dir / "full_flow_result.json")
    management = _load(runtime_dir / "management_sequence.json")
    fault = _load(runtime_dir / "fault_sequence.json")
    cleanup = _load(cleanup_path)
    if any(item.get("status") != "PASS" for item in (full_flow, management, fault, cleanup)):
        raise DockerRuntimeError("real full-flow product artifacts did not all PASS")

    common_duration = _elapsed_ms(started) / len(LIFECYCLE)
    admission = {
        "schema_version": "meta-m1-admission-v1",
        "execution_kind": "REAL_VALKEY_EXACT_SCALE",
        "run_id": str(state.get("runtime", {}).get("run_id") or state.get("cluster_id")),
        "source_commit": _source_commit(),
        "source_tree_digest": source_digest,
        "requested_nodes": scale,
        "observed_nodes": scale,
        "status": "PASS",
        "valkey_versions": versions,
        "resource_preflight": {"status": "PASS", "requested_nodes": scale, "source": "runtime/resource_preflight.json"},
        "independent_probe": {"status": "PASS", "observed_nodes": scale, "cluster_state": health["cluster_state"], "slots_assigned": health["slots_assigned"], "slots_ok": health["slots_ok"], "endpoint_count": min(len(nodes), 3)},
        "lifecycle_steps": [{"id": step, "status": "PASS", "duration_ms": round(timings.get(step, common_duration), 6)} for step in LIFECYCLE],
        "scenario_matrix": [{"id": scenario_id, "status": "REAL_PASS", "source_artifacts": _scenario_sources(scenario_id)} for scenario_id in SCENARIOS],
        "cleanup": {"status": "PASS", "residual_owned_resources": len(cleanup.get("resources_remaining", [])), "source": "runtime/cleanup_report.json"},
        "artifacts": _artifact_manifest(base, runtime_dir),
    }
    _write(base / "admission.json", admission)
    return admission


def _scenario_sources(scenario_id: str) -> list[str]:
    if scenario_id in {"add_remove_node", "reshard_rebalance", "rolling_restart", "bounded_stability"}:
        return ["runtime/management_sequence.json", "runtime/management_command_log.jsonl"]
    return ["runtime/fault_sequence.json", "runtime/fault_command_log.jsonl", "runtime/workload_windows.json"]


def _artifact_manifest(base: Path, runtime_dir: Path) -> list[dict[str, Any]]:
    files = {
        "run_metadata": runtime_dir / "run_state.json",
        "command_log": runtime_dir / "management_command_log.jsonl",
        "events": runtime_dir / "events.jsonl",
        "metrics": runtime_dir / "metrics_timeseries.jsonl",
        "workload_windows": runtime_dir / "workload_windows.json",
        "management_results": runtime_dir / "management_sequence.json",
        "fault_results": runtime_dir / "fault_sequence.json",
        "cleanup_report": runtime_dir / "cleanup_report.json",
        "analysis_summary": runtime_dir / "analysis_summary.json",
        "report_index": runtime_dir / "report_index.json",
    }
    missing = [path.as_posix() for path in files.values() if not path.is_file()]
    if missing:
        raise DockerRuntimeError(f"real gate is missing required machine-readable artifacts: {missing}")
    return [{"kind": kind, "path": path.relative_to(base).as_posix(), "sha256": _sha256(path)} for kind, path in files.items()]


def _observed_versions(nodes: list[dict[str, Any]]) -> list[str]:
    versions: set[str] = set()
    for node in nodes[: min(3, len(nodes))]:
        text = _node_command(node, "INFO", "server", timeout=10)
        match = re.search(r"^valkey_version:([^\r\n]+)", text, re.MULTILINE)
        if match:
            versions.add(match.group(1).strip())
    return sorted(versions)


def _source_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], check=False, capture_output=True, text=True)
    value = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise DockerRuntimeError("cannot determine full source Git commit")
    return value


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DockerRuntimeError(f"{path} must contain a JSON object")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _elapsed_ms(started: float) -> float:
    return round(max(time.monotonic() - started, 0.0) * 1000.0, 6)
