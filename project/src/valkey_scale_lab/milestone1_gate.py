from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from valkey_scale_lab.evidence import (
    ADMISSION_SCHEMA_VERSION,
    EvidenceValidationError,
    build_candidate_admission as _build_candidate_admission,
    canonical_bundle_spec,
    validate_raw_sources,
)
from valkey_scale_lab.gates import (
    FaultTargetKind,
    GateRequest,
    GateService,
    GateStatus,
    LegacyGateAdapter,
    LegacyRuntimeEntrypoints,
    OwnedFaultScope,
)
from valkey_scale_lab.resource import run_resource_preflight
from valkey_scale_lab.runtime.docker_runtime import (
    P36_SCENARIO_200,
    P36_SCENARIO_50,
    P36_STAGE,
    DockerRuntimeError,
    _node_command,
    _p17_cluster_health,
    cleanup_scenario,
    create_scenario,
    _run_id,
)
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline
from valkey_scale_lab.scenarios import compile_gate_plan, load_milestone1_definition


_BUNDLE_SPEC = canonical_bundle_spec()
LIFECYCLE = list(_BUNDLE_SPEC.lifecycle_ids)
SCENARIOS = [
    *_BUNDLE_SPEC.management_scenario_ids,
    *_BUNDLE_SPEC.fault_scenario_ids,
]
RAW_JSON = [
    name
    for name in _BUNDLE_SPEC.raw_artifact_names
    if _BUNDLE_SPEC.raw_formats[name] == "json"
]
RAW_JSONL = [
    name
    for name in _BUNDLE_SPEC.raw_artifact_names
    if _BUNDLE_SPEC.raw_formats[name] == "jsonl"
]


def run_real_gate(scale: int, evidence_dir: str | Path) -> dict[str, Any]:
    if scale not in {50, 200}:
        raise DockerRuntimeError("Milestone 1 real gate supports exactly 50 or 200 nodes")
    if os.environ.get("VSLAB_META_M1_CONTROLLER_OWNED") != "1":
        raise DockerRuntimeError("real gate requires controller ownership, preflight, and cost acknowledgement")
    product_digest = os.environ.get("VSLAB_META_M1_PRODUCT_DIGEST", os.environ.get("VSLAB_META_M1_SOURCE_DIGEST", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", product_digest):
        raise DockerRuntimeError("real gate requires the controller-provided product tree digest before execution")
    _require_docker_daemon()

    base = Path(evidence_dir).resolve()
    runtime_dir = base / "runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state_path = runtime_dir / "state.json"
    cleanup_path = runtime_dir / "cleanup_report.json"
    definition = load_milestone1_definition()
    plan = compile_gate_plan(definition, scale)
    if not plan.required_real_completion or not plan.exact or plan.downscale_allowed:
        raise DockerRuntimeError("compiled Milestone 1 plan is not an exact required real gate")
    if not plan.runtime_phase or not plan.runtime_scenario:
        raise DockerRuntimeError("compiled Milestone 1 plan has no real runtime profile")
    gate_run_id = _run_id(plan.runtime_phase, plan.runtime_scenario)
    ownership_id = f"controller-v9-{scale}-{product_digest[:12]}"
    provenance_id = f"capture-v9-{scale}-{product_digest[:12]}"
    fault_scope = OwnedFaultScope(
        run_id=gate_run_id,
        ownership_id=ownership_id,
        kind=FaultTargetKind.CONTAINER,
        resource_ids=(f"p36-exact-{scale}-sandbox",),
    )
    request = GateRequest(
        run_id=gate_run_id,
        ownership_id=ownership_id,
        provenance_id=provenance_id,
        requested_nodes=scale,
        artifact_root=base,
        fault_scope=fault_scope,
        metadata={"controller_owned": True, "product_digest": product_digest},
    )
    adapter = LegacyGateAdapter(
        LegacyRuntimeEntrypoints(
            create=create_scenario,
            cleanup=cleanup_scenario,
            preflight=_run_exact_preflight,
            live_probe=_run_live_exact_probe,
        )
    )
    run_started = _unix_ms()
    result = GateService().execute(plan, request, adapter.adapter_bundle())
    snapshot = adapter.execution_snapshot(
        run_id=gate_run_id,
        ownership_id=ownership_id,
        provenance_id=provenance_id,
    )
    if result.status is not GateStatus.PASS:
        raise DockerRuntimeError(_gate_failure_message(result))
    if snapshot.state is None or snapshot.live_probe_result is None:
        raise DockerRuntimeError("exact-scale Gate completed without owned state or a live probe")
    state = snapshot.state
    probe = snapshot.live_probe_result
    health_value = probe.get("independent_probe")
    versions_value = probe.get("valkey_versions")
    if (
        not isinstance(health_value, Mapping)
        or isinstance(versions_value, (str, bytes))
        or not isinstance(versions_value, Sequence)
    ):
        raise DockerRuntimeError("exact-scale Gate live probe result is incomplete")
    health = dict(health_value)
    versions = [str(value) for value in versions_value]
    runtime = state.get("runtime")
    runtime_run_id = runtime.get("run_id") if isinstance(runtime, Mapping) else None
    if not isinstance(runtime_run_id, str) or not runtime_run_id:
        runtime_run_id = state.get("cluster_id")
    if not isinstance(runtime_run_id, str) or not runtime_run_id:
        raise DockerRuntimeError("exact-scale Gate state has no attributable runtime run_id")
    _write_measured_lifecycle(
        runtime_dir,
        runtime_run_id,
        scale,
        snapshot.setup_segments,
    )
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


def _require_docker_daemon() -> None:
    docker_info = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if docker_info.returncode != 0 or not docker_info.stdout.strip():
        raise DockerRuntimeError(
            f"real gate requires an available Docker daemon: {docker_info.stderr.strip()}"
        )


def _run_exact_preflight(
    *,
    phase: str,
    scenario: str,
    config_path: str,
    out_path: Path,
    requested_nodes: int,
) -> dict[str, Any]:
    report = run_resource_preflight(
        config_path,
        out_path,
        phase_id=phase,
        scenario=scenario,
    )
    observed = report.get("nodes_requested", report.get("node_count"))
    if observed != requested_nodes:
        raise DockerRuntimeError(
            "resource preflight changed the exact requested node count: "
            f"requested={requested_nodes}, observed={observed}"
        )
    return report


def _run_live_exact_probe(
    *,
    state: dict[str, Any],
    requested_nodes: int,
) -> dict[str, Any]:
    nodes = list(state.get("nodes", []))
    if len(nodes) != requested_nodes:
        raise DockerRuntimeError(
            f"real gate requested {requested_nodes} nodes but runtime returned {len(nodes)}"
        )
    health = _p17_cluster_health(nodes)
    required_health = {
        "cluster_state": "ok",
        "known_nodes": requested_nodes,
        "slots_assigned": 16384,
        "slots_ok": 16384,
    }
    if any(health.get(key) != value for key, value in required_health.items()):
        raise DockerRuntimeError(f"independent exact-scale probe failed: {health}")
    versions = _observed_versions(nodes)
    if not versions or any(
        not re.fullmatch(r"9\.1(?:\.\d+)?", version) for version in versions
    ):
        raise DockerRuntimeError(
            "independent version probe did not observe only Valkey 9.1.x: "
            f"{versions}"
        )
    return {
        "status": "PASS",
        "observed_nodes": len(nodes),
        "independent_probe": health,
        "valkey_versions": versions,
    }


def _gate_failure_message(result: Any) -> str:
    parts = [f"exact-scale Gate status={result.status.value}"]
    if result.primary_failure is not None:
        parts.append(
            "primary="
            f"{result.primary_failure.code}:{result.primary_failure.reason}"
        )
    if result.cleanup_failure is not None:
        parts.append(
            "cleanup="
            f"{result.cleanup_failure.code}:{result.cleanup_failure.reason}"
        )
    return "; ".join(parts)


def validate_admission_sources(base: Path, scale: int) -> list[str]:
    return list(validate_raw_sources(Path(base), scale))


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
    try:
        return _build_candidate_admission(
            base,
            scale,
            product_digest,
            run_started_unix_ms=run_started_unix_ms,
            run_ended_unix_ms=run_ended_unix_ms,
            valkey_versions=valkey_versions,
            independent_probe=independent_probe,
        )
    except EvidenceValidationError as exc:
        raise DockerRuntimeError(str(exc)) from exc


def _write_measured_lifecycle(
    runtime: Path,
    run_id: str,
    scale: int,
    timeline: SetupTimeline | Sequence[Mapping[str, Any]],
) -> None:
    source_segments = getattr(timeline, "segments", timeline)
    segments = [
        dict(row)
        for row in source_segments
        if row.get("kind") == "span" and row.get("status") == "PASS"
    ]
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


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _unix_ms() -> int:
    return time.time_ns() // 1_000_000
