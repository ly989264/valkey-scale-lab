from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
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
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline


ADMISSION_SCHEMA_VERSION = "meta-m1-admission-v2"
LIFECYCLE = ["resource_preflight", "runtime_start", "cluster_form", "stabilize", "baseline_workload", "management_matrix", "fault_matrix", "recovery", "artifact_validation", "analysis", "report", "cleanup"]
SCENARIOS = ["add_remove_node", "reshard_rebalance", "rolling_restart", "bounded_stability", "primary_failover", "replica_stop", "node_host_stop", "az_stop", "network_delay", "network_loss", "network_partition", "network_flap", "minority_majority", "split_brain_detection"]
RAW_JSON = ["run_state.json", "resource_preflight.json", "workload_windows.json", "lifecycle_timeline.json", "scenario_results.json", "management_sequence.json", "fault_sequence.json", "cleanup_report.json", "analysis_summary.json", "report_index.json", "full_flow_result.json"]
RAW_JSONL = ["management_command_log.jsonl", "fault_command_log.jsonl", "events.jsonl", "metrics_timeseries.jsonl"]


def run_real_gate(scale: int, evidence_dir: str | Path) -> dict[str, Any]:
    if scale not in {50, 200}:
        raise DockerRuntimeError("Milestone 1 real gate supports exactly 50 or 200 nodes")
    if os.environ.get("VSLAB_META_M1_CONTROLLER_OWNED") != "1":
        raise DockerRuntimeError("real gate requires controller ownership, preflight, and cost acknowledgement")
    product_digest = os.environ.get("VSLAB_META_M1_PRODUCT_DIGEST", os.environ.get("VSLAB_META_M1_SOURCE_DIGEST", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", product_digest):
        raise DockerRuntimeError("real gate requires the controller-provided product tree digest before execution")
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
    state: dict[str, Any] | None = None
    run_started = _unix_ms()
    setup_timeline = SetupTimeline()

    try:
        state = create_scenario(
            phase=P36_STAGE,
            scenario=scenario,
            config_path=f"templates/configs/scale_{scale}.yaml",
            artifacts_dir=runtime_dir,
            state_out=state_path,
            setup_timeline=setup_timeline,
        )
        nodes = list(state.get("nodes", []))
        if len(nodes) != scale:
            raise DockerRuntimeError(f"real gate requested {scale} nodes but runtime returned {len(nodes)}")
        health = _p17_cluster_health(nodes)
        versions = _observed_versions(nodes)
        if health.get("cluster_state") != "ok" or health.get("known_nodes") != scale:
            raise DockerRuntimeError(f"independent exact-scale probe failed: {health}")
        if not versions or any(not re.fullmatch(r"9\.1(?:\.\d+)?", version) for version in versions):
            raise DockerRuntimeError(f"independent version probe did not observe only Valkey 9.1.x: {versions}")
    finally:
        if state is not None and state_path.exists():
            with setup_timeline.span("cleanup", "cleanup", {"node_count": scale}):
                cleanup_result = cleanup_scenario(state_path=state_path, artifacts_dir=runtime_dir, out_path=cleanup_path)
            if cleanup_result.get("status") != "PASS":
                raise DockerRuntimeError(f"exact-scale cleanup failed: {cleanup_result}")

    assert state is not None
    _write_measured_lifecycle(runtime_dir, str(state.get("runtime", {}).get("run_id") or state.get("cluster_id")), scale, setup_timeline)
    run_ended = _unix_ms()
    source_errors = validate_admission_sources(base, scale)
    if source_errors:
        raise DockerRuntimeError("real gate source evidence is invalid: " + "; ".join(source_errors))
    return build_admission_from_sources(
        base,
        scale,
        product_digest,
        run_started_unix_ms=run_started,
        run_ended_unix_ms=run_ended,
        valkey_versions=versions,
        independent_probe=health,
    )


def validate_admission_sources(base: Path, scale: int) -> list[str]:
    runtime = Path(base).resolve() / "runtime"
    errors: list[str] = []
    objects: dict[str, dict[str, Any]] = {}
    for name in RAW_JSON:
        path = runtime / name
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"runtime/{name} is missing or invalid: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"runtime/{name} must contain a JSON object")
            continue
        objects[name] = value
    streams: dict[str, list[dict[str, Any]]] = {}
    for name in RAW_JSONL:
        path = runtime / name
        try:
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"runtime/{name} is missing or invalid: {exc}")
            continue
        if not rows or any(not isinstance(row, dict) for row in rows):
            errors.append(f"runtime/{name} must contain non-empty JSON object rows")
        else:
            streams[name] = rows
    run_state = objects.get("run_state.json", {})
    run_id = run_state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        errors.append("runtime/run_state.json requires run_id")
    if run_state.get("status") != "PASS" or run_state.get("node_count") != scale or len(run_state.get("nodes", [])) != scale:
        errors.append(f"runtime/run_state.json must PASS with exactly {scale} nodes")
    for name in ("management_sequence.json", "fault_sequence.json", "cleanup_report.json", "analysis_summary.json", "report_index.json", "full_flow_result.json"):
        value = objects.get(name, {})
        if value.get("status") != "PASS" or value.get("run_id") != run_id:
            errors.append(f"runtime/{name} must PASS for the admitted run")
    preflight = objects.get("resource_preflight.json", {})
    if preflight.get("status") != "PASS" or preflight.get("can_run") is not True or preflight.get("nodes_requested", preflight.get("node_count")) != scale:
        errors.append(f"runtime/resource_preflight.json must admit exactly {scale} nodes")
    cleanup = objects.get("cleanup_report.json", {})
    if cleanup.get("resources_remaining") not in ([], None) or cleanup.get("cleanup_errors") not in ([], None):
        errors.append("runtime/cleanup_report.json reports residual resources or cleanup errors")
    analysis = objects.get("analysis_summary.json", {})
    required_surfaces = {"topology_summary", "phase_durations", "bottlenecks", "resources", "workload_impact", "failover", "recovery", "error_summary", "missing_evidence"}
    missing = sorted(required_surfaces - analysis.keys())
    if missing:
        errors.append(f"runtime/analysis_summary.json is missing report surfaces: {missing}")
    for name, rows in streams.items():
        if any(row.get("run_id") != run_id for row in rows):
            errors.append(f"runtime/{name} contains rows from another run")
    _validate_source_lifecycle(objects.get("lifecycle_timeline.json"), streams.get("events.jsonl", []), str(run_id), errors)
    _validate_source_scenarios(objects.get("scenario_results.json"), streams, str(run_id), errors)
    return errors


def _validate_source_lifecycle(value: dict[str, Any] | None, events: list[dict[str, Any]], run_id: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        return
    rows = value.get("steps") if isinstance(value.get("steps"), list) else []
    by_id = {str(row.get("id")): row for row in rows if isinstance(row, dict)}
    missing = sorted(set(LIFECYCLE) - by_id.keys())
    if missing:
        errors.append(f"runtime/lifecycle_timeline.json missing measured steps: {missing}")
    event_by_id = {str(row.get("event_id")): row for row in events if row.get("event_id")}
    for step_id in LIFECYCLE:
        row = by_id.get(step_id)
        if row is None:
            continue
        start = row.get("started_monotonic_ms")
        end = row.get("ended_monotonic_ms")
        if row.get("status") != "PASS" or row.get("run_id") != run_id:
            errors.append(f"lifecycle step {step_id} must PASS for the admitted run")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            errors.append(f"lifecycle step {step_id} requires positive measured monotonic bounds")
        if not isinstance(row.get("event_ids"), list) or not row["event_ids"]:
            errors.append(f"lifecycle step {step_id} requires measured event references")
        elif any(str(ref) not in event_by_id or event_by_id[str(ref)].get("step_id") != step_id for ref in row["event_ids"]):
            errors.append(f"lifecycle step {step_id} requires matching measured events")
    preflight = by_id.get("resource_preflight", {})
    runtime_start = by_id.get("runtime_start", {})
    if isinstance(preflight.get("ended_monotonic_ms"), (int, float)) and isinstance(runtime_start.get("started_monotonic_ms"), (int, float)):
        if preflight["ended_monotonic_ms"] > runtime_start["started_monotonic_ms"]:
            errors.append("resource_preflight must finish before runtime_start begins")


def _validate_source_scenarios(
    value: dict[str, Any] | None,
    streams: dict[str, list[dict[str, Any]]],
    run_id: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        return
    rows = value.get("scenarios") if isinstance(value.get("scenarios"), list) else []
    by_id = {str(row.get("id")): row for row in rows if isinstance(row, dict)}
    missing = sorted(set(SCENARIOS) - by_id.keys())
    if missing:
        errors.append(f"runtime/scenario_results.json missing observed scenarios: {missing}")
    events = streams.get("events.jsonl", [])
    commands_by_stream = {
        "management": streams.get("management_command_log.jsonl", []),
        "fault": streams.get("fault_command_log.jsonl", []),
    }
    event_by_id = {str(row.get("event_id")): row for row in events if row.get("event_id")}
    if len(event_by_id) != len(events):
        errors.append("runtime/events.jsonl requires globally unique event_id values")
    command_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for stream_name, commands in commands_by_stream.items():
        for row in commands:
            command_id = str(row.get("command_id", ""))
            if not command_id or command_id in command_by_id:
                errors.append("runtime command logs require globally unique command_id values")
                continue
            command_by_id[command_id] = (stream_name, row)
    operation_owner: dict[str, str] = {}
    management_scenarios = set(SCENARIOS[:4])
    for scenario_id in SCENARIOS:
        row = by_id.get(scenario_id)
        if row is None:
            continue
        if row.get("status") != "REAL_PASS" or row.get("run_id") != run_id:
            errors.append(f"scenario {scenario_id} must be an observed REAL_PASS for the admitted run")
        event_ids = row.get("event_ids") if isinstance(row.get("event_ids"), list) else []
        command_ids = row.get("command_ids") if isinstance(row.get("command_ids"), list) else []
        if not event_ids or any(str(ref) not in event_by_id for ref in event_ids):
            errors.append(f"scenario {scenario_id} requires existing observed event_ids")
        if not command_ids or any(str(ref) not in command_by_id for ref in command_ids):
            errors.append(f"scenario {scenario_id} requires existing observed command_ids")
        expected_stream = "management" if scenario_id in management_scenarios else "fault"
        for ref in command_ids:
            stream_row = command_by_id.get(str(ref))
            if stream_row is None:
                continue
            stream_name, command = stream_row
            if stream_name != expected_stream or command.get("scenario_id") != scenario_id:
                errors.append(f"scenario {scenario_id} command provenance does not match its source stream")
            _claim_operation(command.get("operation_id"), scenario_id, operation_owner, errors)
        for ref in event_ids:
            event = event_by_id.get(str(ref))
            if event is None:
                continue
            if event.get("scenario_id") != scenario_id:
                errors.append(f"scenario {scenario_id} event provenance does not match")
            _claim_operation(event.get("operation_id"), scenario_id, operation_owner, errors)


def _claim_operation(raw: Any, scenario_id: str, owners: dict[str, str], errors: list[str]) -> None:
    if not isinstance(raw, str) or not raw:
        errors.append(f"scenario {scenario_id} requires observed operation_id provenance")
        return
    existing = owners.setdefault(raw, scenario_id)
    if existing != scenario_id:
        errors.append(f"operation {raw} cannot be relabelled from {existing} to scenario {scenario_id}")


def build_admission_from_sources(
    base: Path,
    scale: int,
    product_digest: str,
    *,
    run_started_unix_ms: int | None = None,
    run_ended_unix_ms: int | None = None,
    valkey_versions: list[str] | None = None,
    independent_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = Path(base).resolve()
    runtime = base / "runtime"
    errors = validate_admission_sources(base, scale)
    if errors:
        raise DockerRuntimeError("cannot build admission from invalid sources: " + "; ".join(errors))
    if not valkey_versions or any(not re.fullmatch(r"9\.1(?:\.\d+)?", version) for version in valkey_versions):
        raise DockerRuntimeError("admission requires independently observed Valkey 9.1.x versions")
    if not isinstance(independent_probe, dict):
        raise DockerRuntimeError("admission requires an independent exact-scale cluster probe")
    required_probe = {"cluster_state": "ok", "known_nodes": scale, "slots_assigned": 16384, "slots_ok": 16384}
    if any(independent_probe.get(key) != value for key, value in required_probe.items()):
        raise DockerRuntimeError(f"independent exact-scale cluster probe is not admissible: {independent_probe}")
    raw = {name: _load(runtime / name) for name in RAW_JSON}
    run_id = str(raw["run_state.json"]["run_id"])
    raw_events = _load_jsonl(runtime / "events.jsonl")
    raw_metrics = _load_jsonl(runtime / "metrics_timeseries.jsonl")
    raw_management_commands = _load_jsonl(runtime / "management_command_log.jsonl")
    raw_fault_commands = _load_jsonl(runtime / "fault_command_log.jsonl")
    raw_commands = [*raw_management_commands, *raw_fault_commands]
    observed_times = [int(row["timestamp_unix_ms"]) for row in [*raw_events, *raw_metrics] if isinstance(row.get("timestamp_unix_ms"), int)]
    observed_times.extend(int(row["ended_at_unix_ms"]) for row in raw_commands if isinstance(row.get("ended_at_unix_ms"), int))
    started_ms = run_started_unix_ms if isinstance(run_started_unix_ms, int) else min(observed_times)
    ended_ms = run_ended_unix_ms if isinstance(run_ended_unix_ms, int) else max(observed_times)
    out = runtime / "admission_v2"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    normalized_management_commands = [_normalize_command(row) for row in raw_management_commands]
    normalized_fault_commands = [_normalize_command(row) for row in raw_fault_commands]

    common = {"schema_version": "v1", "status": "PASS", "run_id": run_id, "created_at_unix_ms": ended_ms, "node_count": scale}
    json_artifacts = {
        "run_metadata": {**common, "nodes": raw["run_state.json"]["nodes"]},
        "resource_preflight": {**raw["resource_preflight.json"], **common},
        "workload_windows": {**raw["workload_windows.json"], **common},
        "lifecycle_timeline": {**raw["lifecycle_timeline.json"], **common},
        "scenario_results": {**raw["scenario_results.json"], **common},
        "management_results": {**raw["management_sequence.json"], **common},
        "fault_results": {**raw["fault_sequence.json"], **common},
        "stability_results": {**common, "recovery_health": raw["fault_sequence.json"].get("recovery_health")},
        "cleanup_report": {**raw["cleanup_report.json"], **common},
        "analysis_summary": {**raw["analysis_summary.json"], **common},
        "report_index": {**raw["report_index.json"], **common, "views": [{"format": "json", "path": "admission_v2/analysis_summary.json", "status": "PASS"}]},
    }
    for kind, value in json_artifacts.items():
        _write(out / f"{kind}.json", value)
    _write_jsonl(out / "command_log.jsonl", normalized_management_commands)
    _write_jsonl(out / "fault_command_log.jsonl", normalized_fault_commands)
    _write_jsonl(out / "events.jsonl", raw_events)
    _write_jsonl(out / "metrics.jsonl", raw_metrics)

    artifacts: list[dict[str, Any]] = []
    paths = {kind: out / f"{kind}.json" for kind in json_artifacts}
    paths.update({"command_log": out / "command_log.jsonl", "fault_command_log": out / "fault_command_log.jsonl", "events": out / "events.jsonl", "metrics": out / "metrics.jsonl"})
    for kind, path in paths.items():
        artifacts.append({"kind": kind, "path": path.relative_to(base).as_posix(), "sha256": _sha256(path)})
    probe = independent_probe
    admission = {
        "schema_version": ADMISSION_SCHEMA_VERSION,
        "execution_kind": "REAL_VALKEY_EXACT_SCALE",
        "run_id": run_id,
        "run_nonce": uuid.uuid4().hex,
        "run_started_unix_ms": started_ms,
        "run_ended_unix_ms": ended_ms,
        "source_commit": _source_commit(),
        "product_digest": product_digest,
        "requested_nodes": scale,
        "observed_nodes": scale,
        "status": "PASS",
        "valkey_versions": valkey_versions,
        "independent_probe": {"status": "PASS", "observed_nodes": scale, "cluster_state": probe.get("cluster_state"), "slots_assigned": probe.get("slots_assigned"), "slots_ok": probe.get("slots_ok"), "endpoint_count": 3},
        "cleanup": {"status": "PASS", "residual_owned_resources": 0, "source": "runtime/cleanup_report.json"},
        "artifacts": artifacts,
    }
    _write(base / "admission.json", admission)
    return admission


def _normalize_command(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    if not isinstance(item.get("timestamp_unix_ms"), int):
        item["timestamp_unix_ms"] = int(item["ended_at_unix_ms"])
    return item


def _write_measured_lifecycle(runtime: Path, run_id: str, scale: int, timeline: SetupTimeline) -> None:
    segments = [row for row in timeline.segments if row.get("kind") == "span" and row.get("status") == "PASS"]
    resource_index = next((index for index, row in enumerate(segments) if row.get("name") == "resource_preflight"), -1)
    cluster_index = next((index for index, row in enumerate(segments) if row.get("category") == "cluster_formation"), -1)
    if resource_index < 0 or cluster_index <= resource_index:
        raise DockerRuntimeError("measured lifecycle is missing ordered preflight/runtime/cluster spans")
    groups: dict[str, list[dict[str, Any]]] = {
        "resource_preflight": [segments[resource_index]],
        "runtime_start": segments[resource_index + 1 : cluster_index],
        "cluster_form": [row for row in segments if row.get("category") == "cluster_formation"],
    }
    for step in LIFECYCLE[3:]:
        groups[step] = [row for row in segments if row.get("name") == step]
    missing = [step for step in LIFECYCLE if not groups.get(step)]
    if missing:
        raise DockerRuntimeError(f"measured lifecycle spans are missing: {missing}")
    now_ms = _unix_ms()
    lifecycle_events: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for step in LIFECYCLE:
        rows = groups[step]
        started_ms = min(float(row["start_monotonic"]) for row in rows) * 1000.0
        ended_ms = max(float(row["end_monotonic"]) for row in rows) * 1000.0
        if ended_ms <= started_ms:
            raise DockerRuntimeError(f"measured lifecycle step {step} has no positive duration")
        event_id = f"lifecycle-{step}-measured"
        lifecycle_events.append(
            {
                "schema_version": "v1",
                "run_id": run_id,
                "event_id": event_id,
                "event_type": "lifecycle_step_measured",
                "operation_id": f"lifecycle:{step}",
                "scenario_id": "lifecycle",
                "step_id": step,
                "timestamp_unix_ms": now_ms,
                "monotonic_ms": ended_ms,
                "status": "PASS",
            }
        )
        steps.append(
            {
                "id": step,
                "run_id": run_id,
                "status": "PASS",
                "started_monotonic_ms": round(started_ms, 6),
                "ended_monotonic_ms": round(ended_ms, 6),
                "duration_ms": round(ended_ms - started_ms, 6),
                "event_ids": [event_id],
                "source_segments": [str(row["name"]) for row in rows],
            }
        )
    existing_events = _load_jsonl(runtime / "events.jsonl")
    _write_jsonl(runtime / "events.jsonl", [*existing_events, *lifecycle_events])
    _write(
        runtime / "lifecycle_timeline.json",
        {
            "schema_version": "v1",
            "artifact_type": "lifecycle_timeline",
            "run_id": run_id,
            "status": "PASS",
            "scale": scale,
            "node_count": scale,
            "created_at_unix_ms": now_ms,
            "steps": steps,
        },
    )


def _observed_versions(nodes: list[dict[str, Any]]) -> list[str]:
    versions: set[str] = set()
    for node in nodes[: min(3, len(nodes))]:
        match = re.search(r"^valkey_version:([^\r\n]+)", _node_command(node, "INFO", "server", timeout=10), re.MULTILINE)
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


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _elapsed_ms(started: float) -> float:
    return round(max(time.monotonic() - started, 0.0) * 1000.0, 6)


def _unix_ms() -> int:
    return time.time_ns() // 1_000_000
