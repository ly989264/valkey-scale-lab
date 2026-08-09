from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from valkey_scale_lab.evidence import (
    ADMISSION_SCHEMA_VERSION,
    EvidenceValidationError,
    build_candidate_admission as _build_candidate_admission,
    canonical_bundle_spec,
    validate_raw_sources,
)
from valkey_scale_lab.execution import ExecutionProfile
from valkey_scale_lab.gates import (
    FaultTargetKind,
    GateRequest,
    GateService,
    GateStatus,
    ProductGateAdapter,
    ProductRuntimeEntrypoints,
    OwnedFaultScope,
    StepStatus,
)
from valkey_scale_lab.observability.contracts import (
    CheckResult,
    CheckStatus,
    CollectionError,
    final_verdict,
)
from valkey_scale_lab.resource import run_resource_preflight
from valkey_scale_lab.runtime.docker_runtime import (
    DockerRuntimeError,
    _node_command,
    _management_cluster_health,
    cleanup_scenario,
    execute_scenario,
)
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline
from valkey_scale_lab.scenarios import ScenarioDefinition, compile_gate_plan


PRODUCT_DIGEST_EXCLUDED_ROOTS = {".pytest_cache", "artifacts", "audit", "runs"}
PRODUCT_DIGEST_EXCLUDED_DIR_NAMES = {"__pycache__"}
PRODUCT_DIGEST_EXCLUDED_FILE_SUFFIXES = {".pyc", ".pyo"}


def product_tree_digest(project_root: str | Path | None = None) -> str:
    """Digest the complete product snapshot using the controller-neutral tree contract."""
    root = (
        Path(__file__).resolve().parents[3]
        if project_root is None
        else Path(project_root).resolve()
    )
    if not root.is_dir() or root.is_symlink():
        raise DockerRuntimeError(f"product root must be a real directory: {root}")
    manifest: dict[str, dict[str, Any]] = {}
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            name
            for name in directories
            if not _product_digest_excluded(current_path / name, root, is_dir=True)
        ]
        for name in sorted((*directories, *files)):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if _product_digest_excluded(path, root, is_dir=path.is_dir()):
                continue
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                raise DockerRuntimeError(
                    f"symlinks are not permitted in a product snapshot: {relative}"
                )
            if stat.S_ISDIR(info.st_mode):
                manifest[relative] = {"kind": "directory", "mode": mode}
            elif stat.S_ISREG(info.st_mode):
                manifest[relative] = {
                    "kind": "file",
                    "mode": mode,
                    "size": info.st_size,
                    "sha256": _file_sha256(path),
                }
            else:
                raise DockerRuntimeError(
                    f"special files are not permitted in a product snapshot: {relative}"
                )
    value = {
        "product": {
            "kind": "directory",
            "manifest": dict(sorted(manifest.items())),
        }
    }
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _product_digest_excluded(path: Path, root: Path, *, is_dir: bool) -> bool:
    relative = path.relative_to(root)
    if relative.parts and relative.parts[0] in PRODUCT_DIGEST_EXCLUDED_ROOTS:
        return True
    if is_dir and path.name in PRODUCT_DIGEST_EXCLUDED_DIR_NAMES:
        return True
    return not is_dir and path.suffix in PRODUCT_DIGEST_EXCLUDED_FILE_SUFFIXES


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_exact_gate(
    *,
    definition: ScenarioDefinition,
    scale: int,
    config_path: str | Path,
    evidence_dir: str | Path,
    run_id: str,
    ownership_id: str,
    provenance_id: str,
    product_digest: str,
    backend_id: str = "docker_process",
    profile_id: str | None = None,
    prior_admission_digest: str | None = None,
    operator_opt_in: bool = False,
    cost_acknowledged: bool = False,
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", product_digest):
        raise DockerRuntimeError("exact gate requires a 64-character product digest")
    _require_docker_daemon()

    base = Path(evidence_dir).resolve()
    runtime_dir = base / "runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state_path = runtime_dir / "state.json"
    cleanup_path = runtime_dir / "cleanup_report.json"
    plan = compile_gate_plan(definition, scale)
    if not plan.exact or plan.downscale_allowed:
        raise DockerRuntimeError("compiled plan does not preserve the exact requested scale")
    if plan.profile is None:
        profile = ExecutionProfile(
            profile_id=f"exact-{scale}",
            requested_nodes=scale,
            environment="local-real",
            config_template=str(config_path),
        )
    else:
        profile = ExecutionProfile(
            profile_id=plan.profile.profile_id,
            requested_nodes=scale,
            environment=plan.profile.environment,
            config_template=str(config_path),
        )
    plan = replace(plan, profile=profile)
    if profile_id is not None and profile_id != profile.profile_id:
        raise DockerRuntimeError(
            f"profile {profile_id!r} does not match exact requested scale {scale}"
        )
    if backend_id != "docker_process":
        raise DockerRuntimeError("exact real admission requires backend docker_process")
    fault_scope = OwnedFaultScope(
        run_id=run_id,
        ownership_id=ownership_id,
        kind=FaultTargetKind.CONTAINER,
        resource_ids=(f"exact-{scale}-sandbox",),
    )
    request = GateRequest(
        run_id=run_id,
        ownership_id=ownership_id,
        provenance_id=provenance_id,
        requested_nodes=scale,
        artifact_root=base,
        fault_scope=fault_scope,
        backend_id=backend_id,
        profile_id=profile.profile_id,
        operator_opt_in=operator_opt_in,
        cost_acknowledged=cost_acknowledged,
        metadata={"product_digest": product_digest},
    )
    adapter = ProductGateAdapter(
        ProductRuntimeEntrypoints(
            execute=execute_scenario,
            cleanup=cleanup_scenario,
            preflight=_run_exact_preflight,
            live_probe=_run_live_exact_probe,
        )
    )
    run_started = _unix_ms()
    result = GateService().execute(plan, request, adapter.adapter_bundle())
    snapshot = adapter.execution_snapshot(
        run_id=run_id,
        ownership_id=ownership_id,
        provenance_id=provenance_id,
    )
    # Written before the raise, because a failing run's only machine-readable
    # verdict used to be the Gate's own summary and an exit code.
    _write_run_verdict(runtime_dir, run_id, scale, result)
    if result.status is not GateStatus.PASS:
        raise _gate_failure(result)
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
        canonical_bundle_spec(definition).lifecycle_ids,
    )
    run_ended = _unix_ms()
    source_errors = validate_admission_sources(base, scale, definition)
    if source_errors:
        raise DockerRuntimeError("real gate source evidence is invalid: " + "; ".join(source_errors))
    return build_admission_from_sources(
        base,
        scale,
        product_digest,
        definition=definition,
        run_started_unix_ms=run_started,
        run_ended_unix_ms=run_ended,
        valkey_versions=versions,
        independent_probe=health,
        promoted_from_admission_digest=prior_admission_digest,
        invocation_run_id=run_id,
    )


def _require_docker_daemon() -> None:
    """§12.1's 任务未发起: no daemon means the run never started, not that it failed.

    This was a `DockerRuntimeError`, so an unreachable daemon came out as `FAIL` -
    a claim that the cluster was observed and found wanting, when nothing was
    observed at all. It is also the one tool error that can be staged for real,
    which is why the acceptance evidence for the whole ERROR verdict rests on it.
    """

    try:
        docker_info = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:  # no docker binary at all
        raise CollectionError(
            f"real gate could not run the Docker client: {exc}"
        ) from exc
    if docker_info.returncode != 0 or not docker_info.stdout.strip():
        raise CollectionError(
            f"real gate requires an available Docker daemon: {docker_info.stderr.strip()}"
        )


def _run_exact_preflight(
    *,
    capability_id: str,
    scenario_id: str,
    backend_id: str,
    profile_id: str,
    config_path: str,
    out_path: Path,
    requested_nodes: int,
    operator_opt_in: bool = False,
    cost_acknowledged: bool = False,
) -> dict[str, Any]:
    report = run_resource_preflight(
        config_path,
        out_path,
        capability_id=capability_id,
        scenario=scenario_id,
        profile_id=profile_id,
        operator_opt_in=operator_opt_in,
        cost_acknowledged=cost_acknowledged,
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
    health = _management_cluster_health(nodes)
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


def _write_run_verdict(
    runtime: Path, run_id: str, scale: int, result: Any
) -> dict[str, Any]:
    """§12.2's aggregation over the lifecycle stages, written whether or not it passed.

    Measured across both exact-200 baselines: a failing run writes 23 of the usual
    61 artifacts, every surviving one says `PASS`, and the only thing that reports
    the failure is the Gate's own `summary.json` on the strength of an exit code.
    So the run had no way to say what happened in its own evidence. This is that,
    in §12.2's vocabulary, over the stages the scenario definition declares.

    Aggregation is `final_verdict` rather than a second implementation of the
    precedence rule, so `FAIL` beating `ERROR` is decided in one place.

    A stage that never ran contributes no verdict. §12.2 aggregates observations
    and a skipped stage is not one, so those are recorded beside the checks rather
    than counted as `OK` - which would be a claim - or as `ERROR`, which would put
    fail-fast's own bookkeeping into `tool_errors`.
    """

    tool_error_stage = (
        result.primary_failure.step_id
        if result.primary_failure is not None
        and str(result.primary_failure.code).endswith("_TOOL_ERROR")
        else None
    )
    checks: list[CheckResult] = []
    not_run: list[dict[str, str]] = []
    for step in result.steps:
        if step.status is StepStatus.PASS:
            checks.append(CheckResult(name=step.step_id, status=CheckStatus.OK))
            continue
        if step.status in {
            StepStatus.SKIPPED_WITH_REASON,
            StepStatus.UNSUPPORTED_WITH_REASON,
        }:
            not_run.append(
                {
                    "stage": step.step_id,
                    "status": step.status.value,
                    "reason": step.reason or "",
                }
            )
            continue
        checks.append(
            CheckResult(
                name=step.step_id,
                status=(
                    CheckStatus.ERROR
                    if step.step_id == tool_error_stage
                    else CheckStatus.FAIL
                ),
                reason=step.reason or "",
            )
        )
    verdict = final_verdict(checks)
    if result.status is GateStatus.BLOCKED:
        # The Gate declined to start the run. That is not one of §12.2's three
        # states and must not be dressed as one: a refused run was not observed
        # and did not fail. `BLOCKED` is the Gate's own word and it is kept.
        verdict["status"] = GateStatus.BLOCKED.value
    document = {
        "schema_version": "v1",
        "artifact_type": "run_verdict",
        "run_id": run_id,
        "scale": scale,
        "node_count": scale,
        "gate_status": result.status.value,
        "stages_not_run": not_run,
        **verdict,
    }
    _write(runtime / "run_verdict.json", document)
    return document


def _gate_failure(result: Any) -> Exception:
    """Raise the failure in the class that says which §12.1 kind it was.

    `GateStatus` is the Gate's own lifecycle result and stays `PASS/FAIL/BLOCKED`
    - a collector that broke mid-run is not a fourth lifecycle outcome. What the
    run has to keep is the kind of failure, and the orchestrator already recorded
    it in the failure code, so re-raising a tool error as a `CollectionError`
    carries it out without a second status enum.

    A cleanup failure fails the run whatever kind it was, and that is deliberate
    rather than an oversight of the split. Ownership is the one thing this product
    is fail-closed about: not being able to prove that every started resource was
    removed is at least as bad as knowing one was left, so it is never softened
    to "the tool could not tell". §12.2's precedence points the same way when a
    step failed too.
    """

    message = _gate_failure_message(result)
    if result.cleanup_failure is not None:
        return DockerRuntimeError(message)
    primary = result.primary_failure
    if primary is not None and primary.code.endswith("_TOOL_ERROR"):
        return CollectionError(message)
    return DockerRuntimeError(message)


def validate_admission_sources(
    base: Path,
    scale: int,
    definition: ScenarioDefinition,
) -> list[str]:
    return list(validate_raw_sources(Path(base), scale, definition))


def build_admission_from_sources(
    base: Path,
    scale: int,
    product_digest: str,
    *,
    definition: ScenarioDefinition,
    run_started_unix_ms: int | None = None,
    run_ended_unix_ms: int | None = None,
    valkey_versions: list[str] | None = None,
    independent_probe: dict[str, Any] | None = None,
    promoted_from_admission_digest: str | None = None,
    invocation_run_id: str | None = None,
) -> dict[str, Any]:
    base = Path(base).resolve()
    errors = validate_admission_sources(base, scale, definition)
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
            definition=definition,
            run_started_unix_ms=run_started_unix_ms,
            run_ended_unix_ms=run_ended_unix_ms,
            valkey_versions=valkey_versions,
            independent_probe=independent_probe,
            promoted_from_admission_digest=promoted_from_admission_digest,
            invocation_run_id=invocation_run_id,
        )
    except EvidenceValidationError as exc:
        raise DockerRuntimeError(str(exc)) from exc


def _write_measured_lifecycle(
    runtime: Path,
    run_id: str,
    scale: int,
    timeline: SetupTimeline | Sequence[Mapping[str, Any]],
    lifecycle_ids: Sequence[str],
) -> None:
    lifecycle = tuple(lifecycle_ids)
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
    for step in lifecycle[3:]:
        groups[step] = [row for row in segments if row.get("name") == step]
    missing = [step for step in lifecycle if not groups.get(step)]
    if missing:
        raise DockerRuntimeError(f"measured lifecycle spans are missing: {missing}")
    now_ms = _unix_ms()
    lifecycle_events: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for step in lifecycle:
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
