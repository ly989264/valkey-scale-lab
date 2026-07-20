#!/usr/bin/env python3
"""Current-invocation real-Valkey capture producer for the M2 admission gate.

The module is deliberately an orchestration layer over the existing product
CLI and runtime probes.  It never accepts an input capture and never selects a
smaller profile.  The caller is responsible for real-run authorization.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
REPORT_NAME = "m2_performance_report.json"
TRIALS_DIR = "trials"
BASELINE_STRATEGY = "valkey_cli_cluster_create_primaries"
BASELINE_TIMEOUT_MS = 30000
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
FORBIDDEN_EVIDENCE_PATH_PARTS = {
    "fixture",
    "fixtures",
    "historical",
    "loop_evidence",
    "retained",
}
CONTROL_KEYS = {
    "valkey_binary",
    "product",
    "configuration_except_treatment",
    "topology",
    "placement",
    "host",
    "workload",
    "resource_preflight",
}
CRITERIA = {
    "formation": {
        "performance.measurement-contract",
        "performance.cluster-formation-experiment",
        "performance.cluster-formation-budget",
    },
    "failover": {
        "performance.measurement-contract",
        "performance.automatic-failover-experiment",
        "performance.automatic-failover-budget",
    },
    "stability": {
        "performance.measurement-contract",
        "performance.stability-and-resource-safety",
    },
}
SETUP_EVENTS = (
    "last_process_ping",
    "first_membership_command",
    "all_primaries_known",
    "all_slots_assigned",
    "all_replicas_attached",
    "all_replicas_synchronized",
    "every_node_clean",
    "data_path_probe",
)


class CaptureError(RuntimeError):
    pass


class EnvironmentBlocked(CaptureError):
    pass


@dataclass
class CaptureContext:
    args: Any
    artifacts_dir: Path
    report_path: Path
    source_refs: list[dict[str, str]] = field(default_factory=list)
    started_trial_ids: list[str] = field(default_factory=list)
    trials: list[dict[str, Any]] = field(default_factory=list)
    pairs: list[dict[str, Any]] = field(default_factory=list)
    cells: list[dict[str, Any]] = field(default_factory=list)
    invalid_samples: list[dict[str, str]] = field(default_factory=list)
    preflights: dict[tuple[int, str], tuple[Path, dict[str, Any]]] = field(default_factory=dict)
    selected_candidate: dict[str, Any] | None = None
    product_digest: str = ""
    environment_facts: dict[str, Any] = field(default_factory=dict)
    environment_digest: str = ""
    started: bool = False


@dataclass(frozen=True)
class ArmSpec:
    trial_id: str
    pair_id: str
    cell_id: str
    arm: str
    order: int
    scale: int
    scenario: str
    treatment: dict[str, Any]
    resource_seconds: float
    workload_seconds: float


@dataclass
class FaultClientProbe:
    shard_id: str
    key: str
    value: str
    client: Any
    affected: bool
    samples: list[dict[str, Any]] = field(default_factory=list)


def capture_current_invocation(args: Any) -> tuple[str, str]:
    """Capture one authorized M2 campaign and write its closed report bundle."""
    artifacts_dir = Path(args.artifacts_dir).resolve()
    if {part.lower() for part in artifacts_dir.parts}.intersection(FORBIDDEN_EVIDENCE_PATH_PARTS):
        return "FAIL", "M2 artifacts directory names forbidden fixture, historical, retained, or loop evidence"
    report_path = artifacts_dir / REPORT_NAME
    trials_dir = artifacts_dir / TRIALS_DIR
    if report_path.exists() or trials_dir.exists():
        return "FAIL", "refusing pre-existing M2 report or trial directory"
    if not RUN_ID_RE.fullmatch(str(args.run_id)):
        return "FAIL", "M2 run id is not a safe current-invocation identifier"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    trials_dir.mkdir()
    ctx = CaptureContext(args=args, artifacts_dir=artifacts_dir, report_path=report_path)
    try:
        ctx.product_digest = _product_digest()
        ctx.environment_facts = _environment_facts()
        ctx.environment_digest = _digest(ctx.environment_facts)
        if args.mode == "formation":
            _capture_formation(ctx)
        elif args.mode == "failover":
            _capture_failover(ctx)
        elif args.mode == "stability":
            _capture_stability(ctx)
        else:
            raise CaptureError(f"unsupported M2 capture mode {args.mode!r}")
    except EnvironmentBlocked as exc:
        if ctx.started:
            _write_failed_report(ctx, f"ENVIRONMENT_AFTER_START: {exc}")
            return "FAIL", str(exc)
        _write_blocked_report(ctx, f"ENVIRONMENT_BLOCKED: {exc}")
        return "BLOCKED", str(exc)
    except Exception as exc:  # noqa: BLE001 - partial real evidence must close as FAIL
        _write_failed_report(ctx, f"CAPTURE_FAILED: {type(exc).__name__}: {exc}")
        return "FAIL", str(exc)
    report = _build_report(ctx, status="PASS", errors=[])
    _write_report(ctx.report_path, report)
    return "PASS", f"captured {len(ctx.trials)} current real-Valkey trials"


def _capture_formation(ctx: CaptureContext) -> None:
    selected = _selected_strategy(ctx.args.selected_strategy)
    baseline = {"kind": "cluster_create_strategy", "value": BASELINE_STRATEGY}
    if selected == BASELINE_STRATEGY:
        ctx.selected_candidate = baseline
        cell_id = "formation-discovery-current-default"
        ctx.cells.append(_cell(cell_id, "discovery", 50, "none", 1, baseline, "FAIL"))
        ctx.pairs.append(
            _capture_pair(
                ctx,
                cell_id=cell_id,
                sequence=1,
                scale=50,
                scenario="cluster_timeout",
                baseline=baseline,
                candidate=baseline,
                resource_seconds=120.0,
                workload_seconds=1.0,
            )
        )
        raise CaptureError("current formation default is the forced baseline; discovery improvement is 0 percent")
    candidates = _formation_candidates()
    requested_parallelism = _selected_strategy_parallelism(ctx.args.selected_strategy)
    eligible = [
        row
        for row in candidates
        if row["value"] == selected
        and (requested_parallelism is None or row.get("bounded_parallelism") == requested_parallelism)
    ]
    if not eligible:
        raise CaptureError("selected formation strategy is not one of the fixed discovery candidates")
    survivors: list[tuple[dict[str, Any], float]] = []
    for index, candidate in enumerate(candidates, start=1):
        cell_id = f"formation-discovery-{index}"
        ctx.cells.append(_cell(cell_id, "discovery", 50, "none", 1, candidate, "FAIL"))
        pair = _capture_pair(
            ctx,
            cell_id=cell_id,
            sequence=1,
            scale=50,
            scenario="cluster_timeout",
            baseline=baseline,
            candidate=candidate,
            resource_seconds=120.0,
            workload_seconds=1.0,
        )
        ctx.pairs.append(pair)
        baseline_trial, candidate_trial = _pair_trials(ctx, pair)
        passed = float(candidate_trial["derived_intervals"]["formation_seconds"]) < float(baseline_trial["derived_intervals"]["formation_seconds"])
        ctx.cells[-1]["status"] = "PASS" if passed else "FAIL"
        if passed:
            survivors.append((candidate, float(candidate_trial["derived_intervals"]["formation_seconds"])))
    selected_survivors = [row for row in survivors if row[0] in eligible]
    if not selected_survivors:
        raise CaptureError("selected formation candidate did not beat the exact-50 discovery baseline")
    selected_treatment = min(selected_survivors, key=lambda row: row[1])[0]
    ctx.selected_candidate = dict(selected_treatment)
    for candidate, _duration in survivors:
        candidate_id = _treatment_id(candidate)
        for scale in (50, 100, 200):
            promotion_id = f"formation-promotion-{candidate_id}-exact-{scale}"
            ctx.cells.append(_cell(promotion_id, "promotion", scale, "none", 7, candidate, "FAIL"))
            for sequence in range(1, 8):
                ctx.pairs.append(
                    _capture_pair(
                        ctx,
                        cell_id=promotion_id,
                        sequence=sequence,
                        scale=scale,
                        scenario="cluster_timeout",
                        baseline=baseline,
                        candidate=candidate,
                        resource_seconds=120.0,
                        workload_seconds=1.0,
                    )
                )
            ctx.cells[-1]["status"] = "PASS"


def _capture_failover(ctx: CaptureContext) -> None:
    selected = _selected_timeout(ctx.args.selected_timeout_ms)
    baseline = _timeout_treatment(BASELINE_TIMEOUT_MS)
    if selected == BASELINE_TIMEOUT_MS:
        ctx.selected_candidate = baseline
        cell_id = "failover-discovery-current-default"
        ctx.cells.append(_cell(cell_id, "discovery", 50, "one", 1, baseline, "FAIL"))
        ctx.pairs.append(
            _capture_pair(
                ctx,
                cell_id=cell_id,
                sequence=1,
                scale=50,
                scenario="failover_timeline",
                baseline=baseline,
                candidate=baseline,
                resource_seconds=120.0,
                workload_seconds=120.0,
                fault_rate="one",
            )
        )
        raise CaptureError("current failover default is the 30000 ms baseline; discovery improvement is 0 percent")
    candidates = [_timeout_treatment(value) for value in (5000, 10000, 15000)]
    requested_candidate = next((row for row in candidates if row["value"] == selected), None)
    if requested_candidate is None:
        raise CaptureError("selected failover timeout is not one of 5000, 10000, or 15000 ms")
    survivors: list[dict[str, Any]] = []
    for value in candidates:
        cell_id = f"failover-discovery-{value['value']}"
        ctx.cells.append(_cell(cell_id, "discovery", 50, "one", 1, value, "FAIL"))
        pair = _capture_pair(
                ctx,
                cell_id=cell_id,
                sequence=1,
                scale=50,
                scenario="failover_timeline",
                baseline=baseline,
                candidate=value,
                resource_seconds=120.0,
                workload_seconds=120.0,
                fault_rate="one",
            )
        ctx.pairs.append(pair)
        passed = _failover_discovery_passed(ctx, pair)
        ctx.cells[-1]["status"] = "PASS" if passed else "FAIL"
        if passed:
            survivors.append(value)
    if requested_candidate not in survivors:
        raise CaptureError("selected failover timeout did not pass exact-50 discovery")
    ctx.selected_candidate = dict(requested_candidate)
    for candidate in survivors:
        for scale in (50, 200):
            for rate in ("one", "10_percent", "33_percent"):
                cell_id = f"failover-matrix-{candidate['value']}-exact-{scale}-{rate}"
                ctx.cells.append(_cell(cell_id, "matrix", scale, rate, 10, candidate, "FAIL"))
                for sequence in range(1, 11):
                    ctx.pairs.append(
                        _capture_pair(
                            ctx,
                            cell_id=cell_id,
                            sequence=sequence,
                            scale=scale,
                            scenario="failover_timeline",
                            baseline=baseline,
                            candidate=candidate,
                            resource_seconds=120.0,
                            workload_seconds=120.0,
                            fault_rate=rate,
                        )
                    )
                ctx.cells[-1]["status"] = "PASS"


def _capture_stability(ctx: CaptureContext) -> None:
    strategy = _selected_strategy(ctx.args.selected_strategy)
    timeout = _selected_timeout(ctx.args.selected_timeout_ms)
    baseline = {
        "kind": "selected_settings",
        "value": "m1-defaults",
        "cluster_create_strategy": BASELINE_STRATEGY,
        "cluster_node_timeout_ms": BASELINE_TIMEOUT_MS,
    }
    candidate = {
        "kind": "selected_settings",
        "value": "selected",
        "cluster_create_strategy": strategy,
        "cluster_node_timeout_ms": timeout,
    }
    parallelism = _selected_strategy_parallelism(ctx.args.selected_strategy)
    if parallelism is not None:
        candidate["bounded_parallelism"] = parallelism
    ctx.selected_candidate = candidate
    cell_id = "stability-exact-200-steady"
    ctx.cells.append(_cell(cell_id, "stability", 200, "none", 1, candidate, "FAIL"))
    pair = _capture_pair(
        ctx,
        cell_id=cell_id,
        sequence=1,
        scale=200,
        scenario="cluster_timeout",
        baseline=baseline,
        candidate=candidate,
        resource_seconds=120.0,
        workload_seconds=120.0,
    )
    ctx.pairs.append(pair)
    if strategy == BASELINE_STRATEGY and timeout == BASELINE_TIMEOUT_MS:
        raise CaptureError("selected stability settings equal M1 defaults; paired improvement is 0 percent")
    ctx.cells[0]["status"] = "PASS"
    fault_id = "stability-exact-200-fault-33-percent"
    ctx.cells.append(_cell(fault_id, "stability", 200, "33_percent", 1, candidate, "FAIL"))
    ctx.pairs.append(
        _capture_pair(
            ctx,
            cell_id=fault_id,
            sequence=1,
            scale=200,
            scenario="failover_timeline",
            baseline=baseline,
            candidate=candidate,
            resource_seconds=120.0,
            workload_seconds=120.0,
            fault_rate="33_percent",
        )
    )
    ctx.cells[-1]["status"] = "PASS"
    soak_id = "stability-exact-200-soak"
    ctx.cells.append(_cell(soak_id, "soak", 200, "none", 1, candidate, "FAIL"))
    ctx.pairs.append(
        _capture_pair(
            ctx,
            cell_id=soak_id,
            sequence=1,
            scale=200,
            scenario="cluster_timeout",
            baseline=baseline,
            candidate=candidate,
            resource_seconds=1800.0,
            workload_seconds=1800.0,
        )
    )
    ctx.cells[-1]["status"] = "PASS"


def _capture_pair(
    ctx: CaptureContext,
    *,
    cell_id: str,
    sequence: int,
    scale: int,
    scenario: str,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    resource_seconds: float,
    workload_seconds: float,
    fault_rate: str | None = None,
) -> dict[str, Any]:
    order_name = "AB" if sequence % 2 else "BA"
    arm_order = ("baseline", "candidate") if order_name == "AB" else ("candidate", "baseline")
    pair_id = f"{cell_id}-pair-{sequence:02d}"
    created: dict[str, dict[str, Any]] = {}
    for order, arm in enumerate(arm_order, start=1):
        treatment = baseline if arm == "baseline" else candidate
        trial_id = f"{ctx.args.run_id}-{pair_id}-{arm}"
        try:
            trial = _capture_arm(
                ctx,
                ArmSpec(
                    trial_id=trial_id,
                    pair_id=pair_id,
                    cell_id=cell_id,
                    arm=arm,
                    order=order,
                    scale=scale,
                    scenario=scenario,
                    treatment=treatment,
                    resource_seconds=resource_seconds,
                    workload_seconds=workload_seconds,
                ),
                fault_rate=fault_rate,
            )
        except Exception as exc:
            ctx.invalid_samples.append({"trial_id": trial_id, "reason": str(exc)})
            raise
        ctx.trials.append(trial)
        created[arm] = trial
    if created["baseline"]["control_digests"] != created["candidate"]["control_digests"]:
        raise CaptureError(f"pair {pair_id} did not hold all control digests constant")
    return {
        "pair_id": pair_id,
        "cell_id": cell_id,
        "sequence": sequence,
        "order": order_name,
        "baseline_trial_id": created["baseline"]["trial_id"],
        "candidate_trial_id": created["candidate"]["trial_id"],
        "equal_observation_seconds": resource_seconds,
        "control_digests": created["baseline"]["control_digests"],
    }


def _capture_arm(ctx: CaptureContext, spec: ArmSpec, *, fault_rate: str | None = None) -> dict[str, Any]:
    trial_dir = ctx.artifacts_dir / TRIALS_DIR / spec.trial_id
    if trial_dir.exists():
        raise CaptureError(f"trial directory already exists: {trial_dir}")
    preflight_path, preflight = _ensure_preflight(ctx, spec.scale, spec.scenario)
    trial_dir.mkdir()
    ctx.started = True
    ctx.started_trial_ids.append(spec.trial_id)
    state_path = trial_dir / "state.json"
    cleanup_path = trial_dir / "cleanup_report.json"
    command_ledger = trial_dir / "attempt_ledger.json"
    wrapper_commands = trial_dir / "capture_wrapper_commands.json"
    setup_env = _treatment_environment(spec)
    setup_cmd = _setup_command(spec, trial_dir, state_path)
    trial_started_at_monotonic = round(time.monotonic(), 6)
    _write_json(
        command_ledger,
        {
            "artifact_type": "m2_trial_attempt",
            "status": "STARTED",
            "trial_id": spec.trial_id,
            "run_id": spec.trial_id,
            "ownership_id": spec.trial_id,
            "trial_started_at_monotonic": trial_started_at_monotonic,
            "setup": "PENDING",
            "cleanup": "PENDING",
        },
    )
    setup_result = _run_command(setup_cmd, env=setup_env, timeout=1800)
    _write_json(wrapper_commands, {"setup": setup_result, "cleanup": "PENDING"})
    state: dict[str, Any] = {}
    trial_error: Exception | None = None
    measurement: dict[str, Any] = {}
    try:
        if setup_result["returncode"] != 0 or not state_path.is_file():
            raise CaptureError(f"setup failed for {spec.trial_id}: {setup_result['stderr'][-1000:]}")
        state = _load_object(state_path)
        _validate_state(state, spec)
        topology = _capture_topology(
            trial_dir,
            state,
            spec.scale,
            environment_facts=ctx.environment_facts,
        )
        _attach_setup_wrapper_timing(
            trial_dir / f"setup_timeline_{spec.scenario}.json",
            setup_result,
            state=state,
            topology=topology,
        )
        if fault_rate is not None:
            target_nodes = _select_fault_target_nodes(state, spec.scale, fault_rate)
            first_resource_sample = threading.Event()
            fault_window_start = threading.Event()
            with ThreadPoolExecutor(max_workers=1) as executor:
                resource_future = executor.submit(
                    _capture_resource_window,
                    trial_dir,
                    state,
                    spec.resource_seconds,
                    expected_gone_processes=[
                        {
                            "nodehost_id": str(node["nodehost_id"]),
                            "container_id": str(node["container_id"]),
                            "pid": int(node["pid"]),
                        }
                        for node in target_nodes
                    ],
                    first_sample_event=first_resource_sample,
                    window_start_event=fault_window_start,
                )
                _wait_for_resource_start(resource_future, first_resource_sample)
                measurement = _capture_fault_window(
                    trial_dir,
                    state,
                    spec,
                    fault_rate,
                    selected=target_nodes,
                    initial_topology=topology,
                    resource_window_start_event=fault_window_start,
                )
                workload = measurement["workload"]
                resource = resource_future.result()
        else:
            if _uses_setup_resource_window(spec):
                resource = _load_resource_window(trial_dir / "resource_window.json")
                if _needs_stability_observation(spec):
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        workload_future = executor.submit(
                            _capture_data_path,
                            trial_dir,
                            state,
                            duration_seconds=spec.workload_seconds,
                        )
                        stability_future = executor.submit(
                            _capture_stability_observation,
                            state,
                            duration_seconds=spec.workload_seconds,
                            initial_topology=topology,
                        )
                        workload = workload_future.result()
                        stability = stability_future.result()
                    workload["stability_observation"] = stability
                    _write_json(trial_dir / "workload_observation.json", workload)
                else:
                    workload = _capture_data_path(
                        trial_dir,
                        state,
                        duration_seconds=spec.workload_seconds,
                    )
            else:
                worker_count = 3 if _needs_stability_observation(spec) else 2
                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    workload_future = executor.submit(
                        _capture_data_path,
                        trial_dir,
                        state,
                        duration_seconds=spec.workload_seconds,
                    )
                    resource_future = executor.submit(
                        _capture_resource_window,
                        trial_dir,
                        state,
                        spec.resource_seconds,
                    )
                    stability_future = (
                        executor.submit(
                            _capture_stability_observation,
                            state,
                            duration_seconds=spec.workload_seconds,
                            initial_topology=topology,
                        )
                        if _needs_stability_observation(spec)
                        else None
                    )
                    workload = workload_future.result()
                    resource = resource_future.result()
                    if stability_future is not None:
                        workload["stability_observation"] = stability_future.result()
                        _write_json(trial_dir / "workload_observation.json", workload)
        measurement.update({"topology": topology, "workload": workload, "resource": resource})
    except Exception as exc:  # cleanup below remains mandatory
        trial_error = exc
    cleanup_state_path = _cleanup_state_for_attempt(
        trial_dir,
        state_path,
        capability_id=spec.scenario,
        run_id=spec.trial_id,
    )
    cleanup_result = _run_command(
        _cleanup_command(trial_dir, cleanup_state_path, cleanup_path),
        env=setup_env,
        timeout=600,
    )
    wrapper = _load_object(wrapper_commands)
    wrapper["cleanup"] = cleanup_result
    _write_json(wrapper_commands, wrapper)
    cleanup = _load_object(cleanup_path) if cleanup_path.is_file() else {}
    cleanup_error = _cleanup_error(
        cleanup_result,
        cleanup,
        state,
        expected_run_id=spec.trial_id,
    )
    _write_json(
        command_ledger,
        {
            "artifact_type": "m2_trial_attempt",
            "status": "PASS" if trial_error is None and not cleanup_error else "FAIL",
            "trial_id": spec.trial_id,
            "run_id": spec.trial_id,
            "ownership_id": spec.trial_id,
            "trial_started_at_monotonic": trial_started_at_monotonic,
            "trial_ended_at_monotonic": round(time.monotonic(), 6),
            "setup": _command_boundary(setup_result),
            "cleanup": _command_boundary(cleanup_result),
        },
    )
    if trial_error is not None:
        _collect_partial_refs(ctx, trial_dir, spec)
        raise CaptureError(str(trial_error))
    if cleanup_error:
        _collect_partial_refs(ctx, trial_dir, spec)
        raise CaptureError(cleanup_error)
    return _build_trial(ctx, spec, state, preflight_path, preflight, trial_dir, cleanup, measurement)


def _capture_topology(
    trial_dir: Path,
    state: dict[str, Any],
    scale: int,
    *,
    environment_facts: Mapping[str, Any],
) -> dict[str, Any]:
    from valkey_scale_lab.observer.failover_timeline import ObserverEndpoint, _probe_endpoint

    endpoints = [ObserverEndpoint.from_node(node) for node in state["nodes"]]
    with ThreadPoolExecutor(max_workers=min(len(endpoints), 32)) as executor:
        probes = list(executor.map(lambda endpoint: _probe_endpoint(endpoint, 2.0), endpoints))
    versions = _observed_versions(state)
    binary_sha256s = _observed_binary_sha256s(state)
    healthy = bool(probes) and len(probes) == scale
    for probe in probes:
        nodes = probe.get("cluster_nodes") if isinstance(probe, dict) else None
        healthy = healthy and probe.get("status") == "PASS"
        healthy = healthy and probe.get("cluster_state") == "ok"
        healthy = healthy and probe.get("cluster_slots_assigned") == 16384
        healthy = healthy and probe.get("cluster_slots_ok") == 16384
        healthy = healthy and probe.get("cluster_known_nodes") == scale
        healthy = healthy and isinstance(nodes, dict) and len(nodes) == scale
        if isinstance(nodes, dict):
            healthy = healthy and not any(
                set(row.get("flags", ())).intersection({"fail", "fail?", "handshake", "noaddr"})
                for row in nodes.values()
            )
    result = {
        "status": "PASS" if healthy else "FAIL",
        "versions": versions,
        "valkey_binary_sha256s": binary_sha256s,
        "topology_control": _topology_control(state),
        "placement_control": _placement_control(state),
        "environment_control": dict(environment_facts),
        "probes": probes,
    }
    _write_json(trial_dir / "topology_observation.json", result)
    if not healthy:
        raise CaptureError("every-node topology observation was not exact, clean, and fully slotted")
    return result


def _capture_data_path(trial_dir: Path, state: dict[str, Any], *, duration_seconds: float) -> dict[str, Any]:
    from valkey_scale_lab.observer.failover_timeline import ObserverEndpoint, PersistentClusterClient
    from valkey_scale_lab.metrics import nearest_rank

    endpoints = [ObserverEndpoint.from_node(node) for node in state["nodes"]]
    key = f"m2-current-{state['runtime']['run_id']}"
    value = "x" * 512
    latencies: list[float] = []
    errors: list[str] = []
    started = round(time.monotonic(), 6)
    with PersistentClusterClient(endpoints, timeout_seconds=1.0) as client:
        while not latencies or time.monotonic() - started < duration_seconds:
            set_started = time.monotonic()
            try:
                set_result = client.execute("SET", key, value)
                set_completed = time.monotonic()
                if str(set_result.value).upper() != "OK":
                    raise CaptureError("persistent cluster-aware SET returned an unexpected value")
                latencies.append(round((set_completed - set_started) * 1000.0, 6))
                get_result = client.execute("GET", key)
                if str(get_result.value) != value:
                    raise CaptureError("persistent cluster-aware GET returned an unexpected value")
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))
                break
    ended = round(time.monotonic(), 6)
    elapsed = max(ended - started, 0.000001)
    histogram = Counter(latencies)
    report = {
        "status": "PASS" if latencies and not errors else "FAIL",
        "requested_duration_seconds": float(duration_seconds),
        "duration_seconds": round(elapsed, 6),
        "started_at_monotonic": started,
        "ended_at_monotonic": ended,
        "value_size_bytes": 512,
        "operation_count": len(latencies),
        "latency_operation": "SET",
        "error_count": len(errors),
        "latency_histogram": [
            {"latency_ms": latency, "count": count}
            for latency, count in sorted(histogram.items())
        ],
        "set_throughput_ops_per_second": round(len(latencies) / elapsed, 6),
        "p99_latency_ms": round(nearest_rank(latencies, 0.99), 6) if latencies else "MISSING",
        "errors": errors,
        "persistent_cluster_client": True,
        "per_operation_process_spawn": False,
        "affected_shard_max_interval_ms": 100.0,
        "stable_shards": [],
    }
    _write_json(trial_dir / "workload_observation.json", report)
    if report["status"] != "PASS":
        raise CaptureError("persistent cluster-aware data-path observation failed")
    return report


def _capture_stability_observation(
    state: dict[str, Any],
    *,
    duration_seconds: float,
    initial_topology: Mapping[str, Any],
) -> dict[str, Any]:
    from valkey_scale_lab.observer.failover_timeline import ObserverEndpoint, _probe_endpoint

    endpoints = [ObserverEndpoint.from_node(node) for node in state["nodes"]]
    observers = _representative_observers(endpoints)
    initial_probes = initial_topology.get("probes")
    if not isinstance(initial_probes, list):
        raise CaptureError("stability observation lacks its pre-window topology")
    baseline_nodes = _merged_cluster_nodes(initial_probes)
    baseline_roles = {
        node_id: str(row.get("role"))
        for node_id, row in baseline_nodes.items()
        if isinstance(row, dict)
    }
    expected_nodes = len(state["nodes"])
    interval_seconds = 5.0
    sample_count = int(math.ceil(float(duration_seconds) / interval_seconds)) + 1
    started = time.monotonic()
    samples: list[dict[str, Any]] = []
    errors: list[str] = []
    for index in range(sample_count):
        scheduled = started + min(index * interval_seconds, float(duration_seconds))
        delay = scheduled - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        sample_started = time.monotonic()
        with ThreadPoolExecutor(max_workers=len(observers)) as executor:
            probes = list(executor.map(lambda endpoint: _probe_endpoint(endpoint, 1.0), observers))
        sample_ended = time.monotonic()
        facts = _stability_probe_facts(
            probes,
            expected_nodes=expected_nodes,
            baseline_roles=baseline_roles,
        )
        if facts["status"] != "PASS":
            errors.append(f"stability sample {index} did not prove a clean unchanged topology")
        samples.append(
            {
                "sample_index": index,
                "scheduled_offset_seconds": round(min(index * interval_seconds, float(duration_seconds)), 6),
                "started_at_monotonic": round(sample_started, 6),
                "ended_at_monotonic": round(sample_ended, 6),
                "facts": facts,
                "probes": probes,
            }
        )
    observed_duration = max(float(samples[-1]["ended_at_monotonic"]) - started, 0.0) if samples else 0.0
    start_times = [float(sample["started_at_monotonic"]) for sample in samples]
    max_interval_ms = max(
        ((right - left) * 1000.0 for left, right in zip(start_times, start_times[1:])),
        default=0.0,
    )
    complete = (
        len(samples) == sample_count
        and observed_duration >= float(duration_seconds)
        and max_interval_ms <= (interval_seconds * 1000.0) + 500.0
        and not errors
    )
    return {
        "artifact_type": "m2_stability_observation",
        "status": "PASS" if complete else "FAIL",
        "duration_seconds": float(duration_seconds),
        "observed_duration_seconds": round(observed_duration, 6),
        "interval_seconds": interval_seconds,
        "expected_sample_count": sample_count,
        "observed_sample_count": len(samples),
        "observer_count": len(observers),
        "max_sample_interval_ms": round(max_interval_ms, 6),
        "baseline_roles": baseline_roles,
        "samples": samples,
        "errors": errors,
    }


def _stability_probe_facts(
    probes: list[dict[str, Any]],
    *,
    expected_nodes: int,
    baseline_roles: Mapping[str, str],
) -> dict[str, Any]:
    unexpected_pfail: set[str] = set()
    unexpected_fail: set[str] = set()
    unexpected_promotions: set[str] = set()
    split_brain = False
    slot_loss = False
    clean = bool(probes)
    for probe in probes:
        nodes = probe.get("cluster_nodes") if isinstance(probe, dict) else None
        clean = clean and (
            isinstance(nodes, dict)
            and probe.get("status") == "PASS"
            and probe.get("cluster_state") == "ok"
            and probe.get("cluster_slots_assigned") == 16384
            and probe.get("cluster_slots_ok") == 16384
            and probe.get("cluster_known_nodes") == expected_nodes
            and len(nodes) == expected_nodes
        )
        if not isinstance(nodes, dict):
            slot_loss = True
            continue
        owned_slots: set[int] = set()
        for node_id, row in nodes.items():
            if not isinstance(row, dict):
                clean = False
                continue
            flags = set(str(flag) for flag in row.get("flags", []))
            if flags & {"pfail", "fail?"}:
                unexpected_pfail.add(str(node_id))
            if "fail" in flags:
                unexpected_fail.add(str(node_id))
            if flags & {"handshake", "noaddr"} or row.get("link_state") != "connected":
                clean = False
            role = str(row.get("role"))
            if baseline_roles.get(str(node_id)) != role:
                unexpected_promotions.add(str(node_id))
            if role == "primary":
                try:
                    slots = _slots_for_node(row)
                except CaptureError:
                    slot_loss = True
                    continue
                if owned_slots.intersection(slots):
                    split_brain = True
                owned_slots.update(slots)
        if len(owned_slots) != 16384:
            slot_loss = True
    status = (
        clean
        and not unexpected_pfail
        and not unexpected_fail
        and not unexpected_promotions
        and not split_brain
        and not slot_loss
    )
    return {
        "status": "PASS" if status else "FAIL",
        "unexpected_pfail_node_ids": sorted(unexpected_pfail),
        "unexpected_fail_node_ids": sorted(unexpected_fail),
        "unexpected_promotion_node_ids": sorted(unexpected_promotions),
        "split_brain": split_brain,
        "slot_loss": slot_loss,
        "clean_topology": clean,
    }


def _capture_resource_window(
    trial_dir: Path,
    state: dict[str, Any],
    duration_seconds: float,
    *,
    expected_gone_processes: list[dict[str, Any]] | None = None,
    first_sample_event: threading.Event | None = None,
    window_start_event: threading.Event | None = None,
) -> dict[str, Any]:
    from valkey_scale_lab.metrics.m2_resource import collect_m2_resource_window
    from valkey_scale_lab.runtime.docker_runtime import run_docker

    interval = min(5.0, max(duration_seconds, 0.001))
    report = collect_m2_resource_window(
        state,
        window_name="m2-equal-observation",
        duration_seconds=duration_seconds,
        interval_seconds=interval,
        command=run_docker,
        expected_gone_processes=expected_gone_processes,
        first_complete_sample_event=first_sample_event,
        window_start_event=window_start_event,
    )
    _write_json(trial_dir / "resource_window.json", report)
    return _validate_resource_report(report)


def _load_resource_window(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise CaptureError("M2 setup resource window is missing or unsafe")
    return _validate_resource_report(_load_object(path))


def _validate_resource_report(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("status") != "PASS" or report.get("coverage", {}).get("complete") is not True:
        raise CaptureError("M2 resource window is missing or incomplete")
    metrics = report.get("metrics")
    if not isinstance(metrics, dict):
        raise CaptureError("M2 resource metrics are missing")
    for field in ("peak_rss_bytes", "cpu_time_seconds", "fd_count", "connection_count", "cluster_bus_bytes"):
        if isinstance(metrics.get(field), bool) or not isinstance(metrics.get(field), (int, float)):
            raise CaptureError(f"M2 resource metric {field} is unavailable")
    for field in ("cluster_link_errors", "buffer_overflows"):
        if metrics.get(field) != 0:
            raise CaptureError(f"M2 resource safety metric {field} is unavailable or nonzero")
    return report


def _wait_for_resource_start(future: Any, first_sample_event: threading.Event) -> None:
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        if first_sample_event.wait(timeout=0.05):
            return
        if future.done():
            future.result()
            raise CaptureError("M2 fault resource window ended before its first complete sample")
    raise CaptureError("M2 fault resource window did not capture every owned process before SIGKILL")


def _owned_pid_is_alive(
    node: Mapping[str, Any],
    target: Any,
    *,
    command: Callable[..., Any],
) -> bool:
    result = command(
        [
            "exec",
            str(node["container_id"]),
            "sh",
            "-c",
            (
                f"if [ ! -r /proc/{target.pid}/stat ]; then printf VSLAB_GONE; exit 0; fi; "
                f"s=$(awk '{{print $3}}' /proc/{target.pid}/stat) || exit 70; "
                "case \"$s\" in Z|X) printf VSLAB_GONE;; *) printf VSLAB_ALIVE;; esac"
            ),
        ],
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise CaptureError(
            f"PID observation failed for {target.logical_id}: "
            f"exit={result.returncode} stderr={str(result.stderr)[-300:]}"
        )
    observation = str(result.stdout).strip()
    if observation == "VSLAB_ALIVE":
        return True
    if observation == "VSLAB_GONE":
        return False
    raise CaptureError(f"PID observation for {target.logical_id} returned no owned-process sentinel")


def _capture_fault_window(
    trial_dir: Path,
    state: dict[str, Any],
    spec: ArmSpec,
    fault_rate: str,
    *,
    selected: list[dict[str, Any]],
    initial_topology: dict[str, Any],
    resource_window_start_event: threading.Event,
) -> dict[str, Any]:
    """Measure an owned primary-loss window without coordinated failover."""
    from valkey_scale_lab.observer.failover_timeline import (
        ObserverEndpoint,
        OwnedProcessTarget,
        PersistentClusterClient,
        StableShardAccumulator,
        _probe_endpoint,
        apply_owned_sigkill,
    )
    from valkey_scale_lab.metrics import nearest_rank
    from valkey_scale_lab.runtime.docker_runtime import run_docker

    primaries = sorted((node for node in state["nodes"] if node.get("role") == "primary"), key=lambda row: row["logical_id"])
    count = _failed_primary_count(spec.scale, fault_rate)
    if len(selected) != count:
        raise CaptureError("fault target selection does not match the required half-up failure count")
    ownership_id = str(state["runtime"]["run_id"])
    targets = [
        OwnedProcessTarget(str(node["logical_id"]), str(node["nodehost_id"]), int(node["pid"]), ownership_id)
        for node in selected
    ]
    node_by_logical = {str(node["logical_id"]): node for node in state["nodes"]}
    endpoints = [ObserverEndpoint.from_node(node) for node in state["nodes"]]
    initial_probes = initial_topology.get("probes")
    if not isinstance(initial_probes, list) or len(initial_probes) != spec.scale:
        raise CaptureError("fault trial lacks its complete pre-fault topology observation")
    node_ids = _node_ids_by_logical(initial_probes)
    initial_nodes = _merged_cluster_nodes(initial_probes)
    if len(initial_nodes) != spec.scale:
        raise CaptureError("pre-fault topology does not identify every Valkey node")
    initial_roles = {node_id: str(row.get("role")) for node_id, row in initial_nodes.items()}
    initial_shards = {
        node_ids[str(node["logical_id"])]: str(node["shard_id"])
        for node in state["nodes"]
    }
    target_node_ids = {node_ids[str(node["logical_id"])] for node in selected}
    replacement_nodes = [_replacement_for_target(state, node) for node in selected]
    replacement_node_ids = {node_ids[str(node["logical_id"])] for node in replacement_nodes}

    affected: list[FaultClientProbe] = []
    for node in selected:
        target_node_id = node_ids[str(node["logical_id"])]
        slots = _slots_for_node(initial_nodes[target_node_id])
        key = _key_for_slots(spec.trial_id, str(node["shard_id"]), slots)
        affected.append(
            FaultClientProbe(
                shard_id=str(node["shard_id"]),
                key=key,
                value="x" * 512,
                client=PersistentClusterClient(endpoints, timeout_seconds=0.04),
                affected=True,
            )
        )
    unaffected_primary = next((node for node in primaries if node not in selected), None)
    if unaffected_primary is None:
        raise CaptureError("fault trial has no unaffected shard for the continuous client control")
    unaffected_slots = _slots_for_node(initial_nodes[node_ids[str(unaffected_primary["logical_id"])]])
    controls = [
        FaultClientProbe(
            shard_id=str(unaffected_primary["shard_id"]),
            key=_key_for_slots(spec.trial_id, str(unaffected_primary["shard_id"]), unaffected_slots),
            value="x" * 512,
            client=PersistentClusterClient(endpoints, timeout_seconds=0.04),
            affected=False,
        )
    ]
    client_probes = [*affected, *controls]
    with ThreadPoolExecutor(max_workers=len(client_probes)) as executor:
        warmups = list(executor.map(_warm_fault_client, client_probes))
    if not all(row.get("status") == "PASS" for row in warmups):
        for probe in client_probes:
            probe.client.close()
        raise CaptureError("persistent affected-slot clients were not established before SIGKILL")

    def alive(target: Any) -> bool:
        node = node_by_logical[target.logical_id]
        return _owned_pid_is_alive(node, target, command=run_docker)

    send, command_batches = _owned_sigkill_sender(state, selected, command=run_docker)

    sample_lock = threading.Lock()
    stop_clients = threading.Event()
    client_started = [threading.Event() for _probe in client_probes]
    client_executor = ThreadPoolExecutor(max_workers=len(client_probes))
    client_futures = [
        client_executor.submit(
            _fault_client_loop,
            probe,
            stop_clients,
            started,
            sample_lock,
        )
        for probe, started in zip(client_probes, client_started)
    ]
    fault: dict[str, Any] = {}
    observer_rounds: list[dict[str, Any]] = []
    accumulator = StableShardAccumulator(window_ms=1000.0, min_pairs=10, max_pair_interval_ms=100.0)
    markers: dict[str, float] = {}
    first_success: dict[str, float] = {}
    processed = {probe.shard_id: 0 for probe in affected}
    full_convergence: dict[str, Any] = {}
    observed_safety = {
        "unexpected_pfail": 0,
        "unexpected_fail": 0,
        "unexpected_promotions": 0,
        "split_brain": False,
    }
    try:
        if not all(event.wait(timeout=5.0) for event in client_started):
            raise CaptureError("persistent fault clients did not start before SIGKILL")
        fault = apply_owned_sigkill(
            targets,
            expected_ownership_id=ownership_id,
            signal_sender=send,
            process_alive=alive,
            wait_timeout_seconds=10.0,
            barrier_callback=resource_window_start_event.set,
        )
        fault["mode"] = "owned-process-sigkill"
        fault["command_batches"] = command_batches
        fault["commands"] = [
            " ".join(["docker", *[str(value) for value in batch["argv"]]])
            for batch in command_batches
        ]
        fault["primary_count"] = len(primaries)
        fault["failed_primary_count"] = count
        fault["barrier_monotonic"] = float(fault["fault_apply_monotonic_ms"]) / 1000.0
        fault["injection_skew_ms"] = fault.get("signal_barrier_span_ms", "MISSING")
        for row, node in zip(fault.get("targets", []), selected):
            row["shard_id"] = str(node["shard_id"])
            row["physical_fault_id"] = f"{spec.trial_id}:{node['container_name']}:{node['pid']}"
            row["process_gone"] = row.get("status") == "PASS"
            row["valkey_node_id"] = node_ids[str(node["logical_id"])]
        _write_json(trial_dir / "fault_observation.json", fault)
        if fault.get("status") != "PASS" or not isinstance(fault.get("injection_skew_ms"), (int, float)) or fault["injection_skew_ms"] > 500:
            raise CaptureError("owned simultaneous SIGKILL did not complete within its evidence contract")
        markers["sigkill_barrier"] = round(float(fault["barrier_monotonic"]), 6)
        gone_values = [
            float(row["process_gone_at_monotonic_ms"]) / 1000.0
            for row in fault["targets"]
            if isinstance(row.get("process_gone_at_monotonic_ms"), (int, float))
        ]
        if len(gone_values) != count:
            raise CaptureError("one or more target PID-gone timestamps are missing")
        markers["all_processes_gone"] = round(max(gone_values), 6)

        survivor_endpoints = [endpoint for endpoint in endpoints if endpoint.logical_id not in {target.logical_id for target in targets}]
        representative_endpoints = _representative_observers(survivor_endpoints)
        deadline = markers["sigkill_barrier"] + float(spec.workload_seconds)
        next_probe = time.monotonic()
        while time.monotonic() <= deadline:
            now = time.monotonic()
            if now < next_probe:
                time.sleep(next_probe - now)
            probe_started = time.monotonic()
            with ThreadPoolExecutor(max_workers=len(representative_endpoints)) as executor:
                probes = list(executor.map(lambda endpoint: _probe_endpoint(endpoint, 0.08), representative_endpoints))
            observed_at = time.monotonic()
            facts = _fault_topology_facts(
                probes,
                initial_roles=initial_roles,
                node_shards=initial_shards,
                target_node_ids=target_node_ids,
                replacement_node_ids=replacement_node_ids,
                expected_nodes=spec.scale,
            )
            observer_rounds.append(
                {
                    "at_monotonic": round(observed_at, 6),
                    "probe_started_at_monotonic": round(probe_started, 6),
                    "probe_duration_ms": round(max(observed_at - probe_started, 0.0) * 1000.0, 6),
                    "facts": facts,
                    "views": _compact_fault_views(probes, target_node_ids, replacement_node_ids),
                }
            )
            for field in ("unexpected_pfail", "unexpected_fail", "unexpected_promotions"):
                observed_safety[field] = max(int(observed_safety[field]), int(facts.get(field, 0)))
            observed_safety["split_brain"] = bool(observed_safety["split_brain"] or facts.get("split_brain") is True)
            _advance_fault_markers(markers, observed_at, facts)
            _consume_fault_samples(
                affected,
                sample_lock,
                processed,
                accumulator,
                markers,
                first_success,
            )
            stable = accumulator.summary([probe.shard_id for probe in affected])
            if stable.get("status") == "PASS" and "all_slots_covered_cluster_ok" in markers:
                stable_at = float(stable["stable_endpoint_monotonic_ms"]) / 1000.0
                markers.setdefault("stable_client_recovery", round(stable_at, 6))
            if "stable_client_recovery" in markers and "every_node_converged" not in markers:
                convergence_probe_started = time.monotonic()
                with ThreadPoolExecutor(max_workers=min(len(survivor_endpoints), 32)) as executor:
                    full_probes = list(executor.map(lambda endpoint: _probe_endpoint(endpoint, 0.5), survivor_endpoints))
                convergence_probe_observed = time.monotonic()
                full_convergence = _fault_topology_facts(
                    full_probes,
                    initial_roles=initial_roles,
                    node_shards=initial_shards,
                    target_node_ids=target_node_ids,
                    replacement_node_ids=replacement_node_ids,
                    expected_nodes=spec.scale,
                )
                if full_convergence.get("converged") is True:
                    markers["every_node_converged"] = round(convergence_probe_observed, 6)
                    fault["every_node_convergence_probe"] = {
                        "at_monotonic": round(convergence_probe_observed, 6),
                        "probe_started_at_monotonic": round(convergence_probe_started, 6),
                        "probe_duration_ms": round(
                            max(convergence_probe_observed - convergence_probe_started, 0.0) * 1000.0,
                            6,
                        ),
                    }
                    fault["every_node_convergence_views"] = _compact_fault_views(
                        full_probes,
                        target_node_ids,
                        replacement_node_ids,
                    )
            # Keep observing topology for the full fixed window after recovery;
            # otherwise a late PFAIL, FAIL, promotion, or slot loss would be
            # invisible. The client probes continue at their <=100 ms cadence.
            next_probe = probe_started + (
                1.0 if all(name in markers for name in _fault_marker_names()) else 0.1
            )
    finally:
        stop_clients.set()
        for future in client_futures:
            try:
                future.result(timeout=2.0)
            except Exception:
                pass
        client_executor.shutdown(wait=True)
        for probe in client_probes:
            probe.client.close()

    _consume_fault_samples(affected, sample_lock, processed, accumulator, markers, first_success)
    stable = accumulator.summary([probe.shard_id for probe in affected])
    stable_shards = _stable_shard_rows(accumulator, stable)
    cadence = _fault_cadence(client_probes, markers.get("sigkill_barrier"), float(spec.workload_seconds))
    barrier = markers.get("sigkill_barrier", float("inf"))
    all_samples = [
        row
        for probe in client_probes
        for row in probe.samples
        if isinstance(row.get("started_at_monotonic"), (int, float))
        and float(row["started_at_monotonic"]) >= barrier
    ]
    latencies = [float(row["latency_ms"]) for row in all_samples if row.get("status") == "PASS"]
    error_rows = [row for row in all_samples if row.get("status") != "PASS"]
    workload = {
        "status": "PASS",
        "requested_duration_seconds": float(spec.workload_seconds),
        "duration_seconds": float(spec.workload_seconds),
        "observed_duration_seconds": round(max(time.monotonic() - markers.get("sigkill_barrier", time.monotonic()), 0.0), 6),
        "value_size_bytes": 512,
        "set_throughput_ops_per_second": round(sum(1 for row in all_samples if row.get("set_succeeded") is True) / max(float(spec.workload_seconds), 0.000001), 6),
        "p99_latency_ms": round(nearest_rank(latencies, 0.99), 6) if latencies else "MISSING",
        "errors": [str(row.get("error") or "client operation failed") for row in error_rows],
        "error_count": len(error_rows),
        "timeout_count": sum(1 for row in error_rows if row.get("timed_out") is True),
        "persistent_cluster_client": True,
        "per_operation_process_spawn": False,
        "affected_shard_max_interval_ms": cadence.get("affected_shard_max_interval_ms", "MISSING"),
        "stable_shards": stable_shards,
        "accumulator": stable,
        "pre_fault_warmups": warmups,
        "first_success": first_success,
        "per_shard": cadence.get("per_shard", []),
        "client_series": _fault_client_series(client_probes, markers, stable_shards),
        "unaffected_control_shards": [probe.shard_id for probe in controls],
    }
    missing = _missing_fault_facts(
        markers,
        first_success,
        stable,
        stable_shards,
        cadence,
        full_convergence,
        observed_safety,
    )
    if not latencies:
        missing.append("no successful persistent client operation was measured")
    if missing:
        workload["status"] = "FAIL"
        workload["errors"] = [*workload["errors"], *missing]
    fault.update(
        {
            "monotonic_markers": markers,
            "observer_rounds": observer_rounds,
            "topology_facts": full_convergence,
            "observed_safety": observed_safety,
            "initial_roles": initial_roles,
            "node_shards": initial_shards,
            "target_node_ids": sorted(target_node_ids),
            "replacement_node_ids": sorted(replacement_node_ids),
            "status": "PASS" if not missing else "FAIL",
            "errors": [*fault.get("errors", []), *missing],
        }
    )
    _write_json(trial_dir / "fault_observation.json", fault)
    _write_json(trial_dir / "workload_observation.json", workload)
    if missing:
        raise CaptureError("fault measurement is incomplete: " + "; ".join(missing))
    intervals = _fault_intervals(markers, first_success)
    correctness = {
        "exact_membership": full_convergence["exact_membership"],
        "observed_nodes": full_convergence["observed_nodes"],
        "slots_covered": full_convergence["slots_covered"],
        "replicas_synchronized": full_convergence["replacement_promotions_complete"],
        "clean_topology": full_convergence["clean_topology"],
        "data_path": stable.get("status") == "PASS",
        "split_brain": observed_safety["split_brain"],
        "unexpected_pfail": observed_safety["unexpected_pfail"],
        "unexpected_fail": observed_safety["unexpected_fail"],
        "unexpected_promotions": observed_safety["unexpected_promotions"],
        "slot_loss": full_convergence["slot_loss"],
    }
    return {
        "fault": fault,
        "workload": workload,
        "monotonic_markers": markers,
        "derived_intervals": intervals,
        "correctness": correctness,
    }


def _select_fault_target_nodes(
    state: dict[str, Any],
    scale: int,
    fault_rate: str,
) -> list[dict[str, Any]]:
    nodes = state.get("nodes")
    if not isinstance(nodes, list):
        raise CaptureError("fault target selection requires runtime nodes")
    primaries = sorted(
        (node for node in nodes if isinstance(node, dict) and node.get("role") == "primary"),
        key=lambda row: str(row.get("logical_id")),
    )
    if len(primaries) != scale // 2:
        raise CaptureError("fault target selection requires the exact primary count")
    eligible: list[dict[str, Any]] = []
    for primary in primaries:
        replicas = [
            node
            for node in nodes
            if isinstance(node, dict)
            and node.get("role") == "replica"
            and node.get("shard_id") == primary.get("shard_id")
            and node.get("nodehost_id") != primary.get("nodehost_id")
            and node.get("az_id") != primary.get("az_id")
        ]
        if len(replicas) == 1:
            eligible.append(primary)
    required = _failed_primary_count(scale, fault_rate)
    if len(eligible) < required:
        raise CaptureError(
            "not enough deterministic primary targets have one replica on a different nodehost and failure domain"
        )
    return eligible[:required]


def _owned_sigkill_sender(
    state: Mapping[str, Any],
    selected: list[dict[str, Any]],
    *,
    command: Callable[..., Any],
) -> tuple[Callable[[Any, int], None], list[dict[str, Any]]]:
    """Pre-authorize containers, then issue one post-barrier kill per container."""
    runtime = state.get("runtime")
    capability_id = state.get("capability_id")
    if not isinstance(runtime, Mapping) or not isinstance(runtime.get("run_id"), str):
        raise CaptureError("SIGKILL batching requires runtime ownership")
    ownership_id = str(runtime["run_id"])
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    logical_to_group: dict[str, tuple[str, str]] = {}
    logical_to_pid: dict[str, int] = {}
    container_names: dict[str, str] = {}
    for node in selected:
        logical_id = node.get("logical_id")
        container_name = node.get("container_name")
        container_id = node.get("container_id")
        pid = node.get("pid")
        if (
            not isinstance(logical_id, str)
            or not logical_id
            or not isinstance(container_name, str)
            or not container_name
            or not isinstance(container_id, str)
            or not container_id
            or not isinstance(pid, int)
            or isinstance(pid, bool)
            or pid <= 0
        ):
            raise CaptureError("SIGKILL target lacks a complete container/process identity")
        if logical_id in logical_to_group:
            raise CaptureError("SIGKILL target logical ids are duplicated")
        if container_name in container_names and container_names[container_name] != container_id:
            raise CaptureError("SIGKILL target container name maps to multiple container ids")
        container_names[container_name] = container_id
        key = (container_name, container_id)
        groups.setdefault(key, []).append(node)
        logical_to_group[logical_id] = key
        logical_to_pid[logical_id] = pid

    expected_labels = {
        "org.valkey-scale-lab.project": "valkey-scale-lab",
        "org.valkey-scale-lab.capability_id": capability_id,
        "org.valkey-scale-lab.run_id": ownership_id,
    }
    batch_states: dict[tuple[str, str], dict[str, Any]] = {}
    for key, nodes in groups.items():
        container_name, container_id = key
        inspected = command(["inspect", container_id], timeout=10, check=True)
        payload = json.loads(inspected.stdout)
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise CaptureError(f"SIGKILL container {container_name} inspection was incomplete")
        labels = payload[0].get("Config", {}).get("Labels", {})
        if payload[0].get("Id") != container_id or any(
            labels.get(label) != value for label, value in expected_labels.items()
        ):
            raise CaptureError(f"SIGKILL container {container_name} failed identity/ownership verification")
        ordered = sorted(nodes, key=lambda row: str(row["logical_id"]))
        argv = ["exec", container_id, "kill", "-KILL", *[str(node["pid"]) for node in ordered]]
        batch_states[key] = {
            "event": threading.Event(),
            "leader": str(ordered[0]["logical_id"]),
            "pids": [int(node["pid"]) for node in ordered],
            "error": None,
            "evidence": {
                "container_name": container_name,
                "container_id": container_id,
                "logical_ids": [str(node["logical_id"]) for node in ordered],
                "pids": [int(node["pid"]) for node in ordered],
                "ownership_id": ownership_id,
                "argv": argv,
                "started_at_monotonic": "MISSING",
                "ended_at_monotonic": "MISSING",
                "returncode": "MISSING",
                "status": "PENDING",
            },
        }

    def send(target: Any, _signal: int) -> None:
        logical_id = str(target.logical_id)
        key = logical_to_group.get(logical_id)
        if key is None or int(target.pid) != logical_to_pid.get(logical_id):
            raise CaptureError(f"SIGKILL callback target {logical_id} was not pre-authorized")
        container_name, container_id = key
        batch = batch_states[key]
        event = batch["event"]
        if logical_id == batch["leader"]:
            evidence = batch["evidence"]
            evidence["started_at_monotonic"] = round(time.monotonic(), 6)
            try:
                result = command(
                    list(evidence["argv"]),
                    timeout=10,
                    check=True,
                )
                evidence["returncode"] = int(result.returncode)
                if result.returncode != 0:
                    raise CaptureError(
                        f"SIGKILL command returned {result.returncode} for container {container_name}"
                    )
                evidence["status"] = "PASS"
            except Exception as exc:  # noqa: BLE001 - all callbacks must see one batch failure
                batch["error"] = exc
                evidence["status"] = "FAIL"
                returncode = getattr(exc, "returncode", None)
                if isinstance(returncode, int) and not isinstance(returncode, bool):
                    evidence["returncode"] = returncode
                evidence["error"] = repr(exc)
            finally:
                evidence["ended_at_monotonic"] = round(time.monotonic(), 6)
                event.set()
        elif not event.wait(timeout=10.0):
            raise CaptureError(f"SIGKILL batch leader timed out for container {container_name}")
        if batch["error"] is not None:
            raise CaptureError(f"SIGKILL batch failed for container {container_name}: {batch['error']!r}")

    command_batches = [
        batch_states[key]["evidence"]
        for key in sorted(batch_states)
    ]
    return send, command_batches


def _replacement_for_target(state: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    replicas = sorted(
        (
            node
            for node in state.get("nodes", [])
            if isinstance(node, dict)
            and node.get("role") == "replica"
            and node.get("shard_id") == target.get("shard_id")
            and node.get("nodehost_id") != target.get("nodehost_id")
            and node.get("az_id") != target.get("az_id")
        ),
        key=lambda row: str(row.get("logical_id")),
    )
    if len(replicas) != 1:
        raise CaptureError(f"target shard {target.get('shard_id')} lacks one deterministic cross-domain replica")
    return replicas[0]


def _node_ids_by_logical(probes: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for probe in probes:
        if not isinstance(probe, dict) or probe.get("status") != "PASS":
            raise CaptureError("pre-fault identity probe did not PASS")
        rows = probe.get("cluster_nodes")
        if not isinstance(rows, dict):
            raise CaptureError("pre-fault identity probe has no parsed CLUSTER NODES")
        myself = [node_id for node_id, row in rows.items() if "myself" in set(row.get("flags", []))]
        if len(myself) != 1:
            raise CaptureError("pre-fault identity probe does not identify exactly one local Valkey node")
        logical_id = str(probe.get("logical_id", ""))
        if not logical_id or logical_id in result:
            raise CaptureError("pre-fault identity probe has duplicate or missing logical id")
        result[logical_id] = str(myself[0])
    if len(set(result.values())) != len(result):
        raise CaptureError("pre-fault identity probes map multiple logical nodes to one Valkey node id")
    return result


def _merged_cluster_nodes(probes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for probe in probes:
        rows = probe.get("cluster_nodes") if isinstance(probe, dict) else None
        if not isinstance(rows, dict):
            continue
        for node_id, row in rows.items():
            if isinstance(row, dict):
                merged.setdefault(str(node_id), row)
    return merged


def _slots_for_node(node: dict[str, Any]) -> set[int]:
    slots: set[int] = set()
    for token in node.get("slots", []):
        text = str(token)
        if text.startswith("["):
            continue
        if text.isdigit():
            slots.add(int(text))
            continue
        if "-" in text:
            left, right = text.split("-", 1)
            if left.isdigit() and right.isdigit() and int(left) <= int(right):
                slots.update(range(int(left), int(right) + 1))
    if not slots or min(slots) < 0 or max(slots) > 16383:
        raise CaptureError("target primary has no valid pre-fault slot ownership")
    return slots


def _key_for_slots(trial_id: str, shard_id: str, slots: set[int]) -> str:
    for sequence in range(200_000):
        tag = f"m2-{trial_id}-{shard_id}-{sequence}"
        if binascii.crc_hqx(tag.encode("utf-8"), 0) % 16384 in slots:
            return f"{{{tag}}}:value"
    raise CaptureError(f"could not derive an affected-slot key for {shard_id}")


def _warm_fault_client(probe: FaultClientProbe) -> dict[str, Any]:
    try:
        expected_slot = binascii.crc_hqx(probe.key[1 : probe.key.index("}")].encode("utf-8"), 0) % 16384
        observed_slot = probe.client.execute("CLUSTER", "KEYSLOT", probe.key)
        set_result = probe.client.execute("SET", probe.key, probe.value)
        get_result = probe.client.execute("GET", probe.key)
        if int(observed_slot.value) != expected_slot:
            raise CaptureError("Valkey CLUSTER KEYSLOT disagrees with the selected affected-slot key")
        if str(set_result.value).upper() != "OK" or str(get_result.value) != probe.value:
            raise CaptureError("pre-fault persistent SET/GET did not return the expected value")
        return {
            "status": "PASS",
            "shard_id": probe.shard_id,
            "key": probe.key,
            "slot": expected_slot,
            "affected": probe.affected,
        }
    except Exception as exc:  # noqa: BLE001 - a failed warmup invalidates the physical trial
        return {
            "status": "FAIL",
            "shard_id": probe.shard_id,
            "key": probe.key,
            "affected": probe.affected,
            "error": repr(exc),
        }


def _fault_client_loop(
    probe: FaultClientProbe,
    stop: threading.Event,
    started: threading.Event,
    sample_lock: threading.Lock,
    *,
    monotonic_clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    cadence_seconds = 0.09
    next_start = monotonic_clock()
    started.set()
    while not stop.is_set():
        delay = next_start - monotonic_clock()
        if delay > 0:
            sleep(delay)
        if stop.is_set():
            break
        operation_started = monotonic_clock()
        set_succeeded = False
        get_succeeded = False
        value_matches = False
        timed_out = False
        error = ""
        set_completed: float | str = "MISSING"
        get_completed: float | str = "MISSING"
        moved_count = 0
        ask_count = 0
        operation_errors: list[str] = []
        try:
            set_result = probe.client.execute("SET", probe.key, probe.value)
            set_completed = monotonic_clock()
            moved_count += int(set_result.moved_count)
            ask_count += int(set_result.ask_count)
            set_succeeded = str(set_result.value).upper() == "OK"
            if not set_succeeded:
                raise CaptureError("SET returned a non-OK response")
        except Exception as exc:  # noqa: BLE001 - the paired GET must still be attempted
            timed_out = timed_out or isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()
            operation_errors.append(f"SET {type(exc).__name__}: {exc}")
        try:
            get_result = probe.client.execute("GET", probe.key)
            get_completed = monotonic_clock()
            moved_count += int(get_result.moved_count)
            ask_count += int(get_result.ask_count)
            get_succeeded = True
            value_matches = str(get_result.value) == probe.value
            if not value_matches:
                raise CaptureError("GET did not return the preceding SET value")
        except Exception as exc:  # noqa: BLE001 - failures are expected observations during failover
            timed_out = timed_out or isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()
            operation_errors.append(f"GET {type(exc).__name__}: {exc}")
        error = "; ".join(operation_errors)
        operation_completed = monotonic_clock()
        row = {
            "shard_id": probe.shard_id,
            "affected": probe.affected,
            "started_at_monotonic": round(operation_started, 6),
            "completed_at_monotonic": round(operation_completed, 6),
            "set_completed_at_monotonic": round(set_completed, 6) if isinstance(set_completed, float) else set_completed,
            "get_completed_at_monotonic": round(get_completed, 6) if isinstance(get_completed, float) else get_completed,
            "latency_ms": round(max(operation_completed - operation_started, 0.0) * 1000.0, 6),
            "set_succeeded": set_succeeded,
            "get_succeeded": get_succeeded,
            "value_matches": value_matches,
            "timed_out": timed_out,
            "error": error,
            "moved_count": moved_count,
            "ask_count": ask_count,
            "status": "PASS" if set_succeeded and get_succeeded and value_matches and not error else "FAIL",
        }
        with sample_lock:
            probe.samples.append(row)
        next_start += cadence_seconds
        if next_start < operation_started:
            next_start = operation_started


def _representative_observers(endpoints: list[Any]) -> list[Any]:
    if not endpoints:
        raise CaptureError("fault observation has no surviving endpoint")
    selected: list[Any] = []
    seen_domains: set[str] = set()
    for endpoint in sorted(endpoints, key=lambda item: item.logical_id):
        domain = str(endpoint.az_id or endpoint.logical_id)
        if domain not in seen_domains:
            selected.append(endpoint)
            seen_domains.add(domain)
    for endpoint in sorted(endpoints, key=lambda item: item.logical_id):
        if endpoint not in selected and len(selected) < 3:
            selected.append(endpoint)
    return selected[:3]


def _fault_topology_facts(
    probes: list[dict[str, Any]],
    *,
    initial_roles: dict[str, str],
    node_shards: dict[str, str],
    target_node_ids: set[str],
    replacement_node_ids: set[str],
    expected_nodes: int,
) -> dict[str, Any]:
    expected_node_ids = set(initial_roles)
    mappings_complete = (
        isinstance(expected_nodes, int)
        and not isinstance(expected_nodes, bool)
        and expected_nodes > 0
        and len(expected_node_ids) == expected_nodes
        and set(node_shards) == expected_node_ids
        and all(role in {"primary", "replica"} for role in initial_roles.values())
        and all(isinstance(shard_id, str) and shard_id for shard_id in node_shards.values())
    )
    views = [probe.get("cluster_nodes") for probe in probes if isinstance(probe, dict)]
    complete_views = (
        mappings_complete
        and bool(probes)
        and len(views) == len(probes)
        and all(isinstance(view, dict) for view in views)
        and all(probe.get("status") == "PASS" for probe in probes)
    )
    normalized_views = [view for view in views if isinstance(view, dict)]

    def flags(view: dict[str, Any], node_id: str) -> set[str]:
        row = view.get(node_id, {})
        return set(row.get("flags", [])) if isinstance(row, dict) else set()

    def observed_role(row: Any) -> str:
        node = row if isinstance(row, dict) else {}
        node_flags = set(node.get("flags", [])) if isinstance(node.get("flags"), list) else set()
        primary = "master" in node_flags
        replica = bool(node_flags.intersection({"slave", "replica"}))
        if primary and not replica:
            return "primary"
        if replica and not primary:
            return "replica"
        return "unknown"

    target_pfail = sorted(
        node_id
        for node_id in target_node_ids
        if any(flags(view, node_id).intersection({"pfail", "fail?"}) for view in normalized_views)
    )
    target_fail = sorted(
        node_id for node_id in target_node_ids if any("fail" in flags(view, node_id) for view in normalized_views)
    )
    promoted = sorted(
        node_id
        for node_id in replacement_node_ids
        if any(observed_role(view.get(node_id)) == "primary" for view in normalized_views)
    )
    replacement_complete = complete_views and bool(replacement_node_ids) and all(
        all(observed_role(view.get(node_id)) == "primary" for view in normalized_views)
        for node_id in replacement_node_ids
    )
    exact_membership = complete_views and all(set(view) == expected_node_ids for view in normalized_views)
    summary_slots_ok = exact_membership and all(
        probe.get("cluster_state") == "ok"
        and probe.get("cluster_slots_assigned") == 16384
        and probe.get("cluster_slots_ok") == 16384
        and probe.get("cluster_known_nodes") == expected_nodes
        for probe in probes
    )
    unexpected_pfail_ids: set[str] = set()
    unexpected_fail_ids: set[str] = set()
    unexpected_promotions: set[str] = set()
    clean_topology = complete_views
    split_brain = False
    raw_slots_ok = exact_membership
    for view in normalized_views:
        live_primaries: dict[str, int] = {}
        owned_slots: set[int] = set()
        for node_id, row in view.items():
            if not isinstance(row, dict):
                clean_topology = False
                continue
            raw_flags = row.get("flags")
            raw_slots = row.get("slots")
            row_flags = set(raw_flags) if isinstance(raw_flags, list) else set()
            role = row.get("role")
            inferred_role = observed_role(row)
            row_structure_valid = (
                row.get("node_id") == node_id
                and isinstance(raw_flags, list)
                and all(isinstance(flag, str) for flag in raw_flags)
                and isinstance(raw_slots, list)
                and all(isinstance(slot, str) for slot in raw_slots)
                and role == inferred_role
                and inferred_role in {"primary", "replica"}
                and row.get("link_state") in {"connected", "disconnected"}
            )
            clean_topology = clean_topology and row_structure_valid
            if row_flags.intersection({"handshake", "noaddr"}):
                clean_topology = False
            if node_id not in target_node_ids and row.get("link_state") != "connected":
                clean_topology = False
            if node_id not in target_node_ids and row_flags.intersection({"pfail", "fail?"}):
                unexpected_pfail_ids.add(str(node_id))
            if node_id not in target_node_ids and "fail" in row_flags:
                unexpected_fail_ids.add(str(node_id))
            if initial_roles.get(str(node_id)) == "replica" and inferred_role == "primary" and node_id not in replacement_node_ids:
                unexpected_promotions.add(str(node_id))
            try:
                node_slots = _fault_slot_tokens(raw_slots)
            except CaptureError:
                raw_slots_ok = False
                clean_topology = False
                node_slots = set()
            if inferred_role == "replica" and raw_slots:
                clean_topology = False
            if inferred_role == "primary" and not row_flags.intersection({"pfail", "fail?", "fail", "handshake", "noaddr"}):
                shard_id = node_shards.get(str(node_id))
                if shard_id:
                    live_primaries[shard_id] = live_primaries.get(shard_id, 0) + 1
                if owned_slots.intersection(node_slots):
                    split_brain = True
                owned_slots.update(node_slots)
        if any(value > 1 for value in live_primaries.values()):
            split_brain = True
        if len(owned_slots) != 16384:
            raw_slots_ok = False
    slots_ok = summary_slots_ok and raw_slots_ok and not split_brain
    all_expected_fail = complete_views and all(
        all("fail" in flags(view, node_id) for view in normalized_views)
        for node_id in target_node_ids
    )
    converged = (
        exact_membership
        and slots_ok
        and replacement_complete
        and all_expected_fail
        and clean_topology
        and not split_brain
        and not unexpected_pfail_ids
        and not unexpected_fail_ids
        and not unexpected_promotions
    )
    return {
        "probe_count": len(probes),
        "passing_probe_count": sum(
            1
            for probe in probes
            if isinstance(probe, dict)
            and probe.get("status") == "PASS"
            and isinstance(probe.get("cluster_nodes"), dict)
        ),
        "target_pfail_node_ids": target_pfail,
        "target_fail_node_ids": target_fail,
        "promoted_replacement_node_ids": promoted,
        "replacement_promotions_complete": replacement_complete,
        "all_expected_targets_fail": all_expected_fail,
        "exact_membership": exact_membership,
        "observed_nodes": expected_nodes if exact_membership else max((len(view) for view in normalized_views), default=0),
        "slots_covered": 16384 if slots_ok else 0,
        "cluster_ok_all_slots": slots_ok and replacement_complete,
        "clean_topology": clean_topology,
        "unexpected_pfail": len(unexpected_pfail_ids),
        "unexpected_fail": len(unexpected_fail_ids),
        "unexpected_promotions": len(unexpected_promotions),
        "split_brain": split_brain,
        "slot_loss": not slots_ok,
        "converged": converged,
    }


def _fault_slot_tokens(raw_slots: Any) -> set[int]:
    if not isinstance(raw_slots, list):
        raise CaptureError("fault topology slots are not a list")
    slots: set[int] = set()
    for raw_token in raw_slots:
        if not isinstance(raw_token, str):
            raise CaptureError("fault topology slot token is not a string")
        if raw_token.startswith("["):
            raise CaptureError("fault topology contains a migrating or importing slot")
        if raw_token.isdigit():
            value = int(raw_token)
            if not 0 <= value <= 16383:
                raise CaptureError("fault topology slot is outside the cluster range")
            slots.add(value)
            continue
        if "-" in raw_token:
            left, right = raw_token.split("-", 1)
            if left.isdigit() and right.isdigit() and 0 <= int(left) <= int(right) <= 16383:
                slots.update(range(int(left), int(right) + 1))
                continue
        raise CaptureError("fault topology contains an invalid slot token")
    return slots


def _compact_fault_views(
    probes: list[dict[str, Any]],
    target_node_ids: set[str],
    replacement_node_ids: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for probe in probes:
        nodes = probe.get("cluster_nodes") if isinstance(probe, dict) else None
        rows.append(
            {
                "logical_id": probe.get("logical_id", "MISSING") if isinstance(probe, dict) else "MISSING",
                "status": probe.get("status", "FAIL") if isinstance(probe, dict) else "FAIL",
                "cluster_state": probe.get("cluster_state", "MISSING") if isinstance(probe, dict) else "MISSING",
                "cluster_slots_assigned": probe.get("cluster_slots_assigned", "MISSING") if isinstance(probe, dict) else "MISSING",
                "cluster_slots_ok": probe.get("cluster_slots_ok", "MISSING") if isinstance(probe, dict) else "MISSING",
                "cluster_known_nodes": probe.get("cluster_known_nodes", "MISSING") if isinstance(probe, dict) else "MISSING",
                "cluster_nodes": nodes if isinstance(nodes, dict) else {},
                "target_flags": {
                    node_id: (nodes.get(node_id, {}).get("flags", []) if isinstance(nodes, dict) else [])
                    for node_id in sorted(target_node_ids)
                },
                "replacement_roles": {
                    node_id: (nodes.get(node_id, {}).get("role", "MISSING") if isinstance(nodes, dict) else "MISSING")
                    for node_id in sorted(replacement_node_ids)
                },
            }
        )
    return rows


def _advance_fault_markers(markers: dict[str, float], observed_at: float, facts: dict[str, Any]) -> None:
    timestamp = round(float(observed_at), 6)
    if facts.get("target_pfail_node_ids"):
        markers.setdefault("first_pfail", timestamp)
    if "first_pfail" in markers and facts.get("target_fail_node_ids"):
        markers.setdefault("quorum_fail", timestamp)
    if "quorum_fail" in markers and facts.get("promoted_replacement_node_ids"):
        markers.setdefault("first_promotion", timestamp)
    if "first_promotion" in markers and facts.get("cluster_ok_all_slots") is True:
        markers.setdefault("all_slots_covered_cluster_ok", timestamp)


def _consume_fault_samples(
    affected: list[FaultClientProbe],
    sample_lock: threading.Lock,
    processed: dict[str, int],
    accumulator: Any,
    markers: dict[str, float],
    first_success: dict[str, float],
) -> None:
    barrier = markers.get("sigkill_barrier")
    if barrier is None:
        return
    cluster_ok = markers.get("all_slots_covered_cluster_ok")
    for probe in affected:
        with sample_lock:
            rows = list(probe.samples[processed[probe.shard_id] :])
            processed[probe.shard_id] += len(rows)
        for row in rows:
            started = row.get("started_at_monotonic")
            completed = row.get("completed_at_monotonic")
            if (
                not isinstance(started, (int, float))
                or float(started) < barrier
                or not isinstance(completed, (int, float))
                or float(completed) < float(started)
            ):
                continue
            row["after_barrier"] = True
            if (
                row.get("set_succeeded") is True
                and isinstance(row.get("set_completed_at_monotonic"), (int, float))
                and float(row["set_completed_at_monotonic"]) >= barrier
            ):
                observed = float(row["set_completed_at_monotonic"])
                first_success["first_affected_write"] = min(
                    observed,
                    first_success.get("first_affected_write", observed),
                )
            if (
                row.get("get_succeeded") is True
                and row.get("value_matches") is True
                and isinstance(row.get("get_completed_at_monotonic"), (int, float))
                and float(row["get_completed_at_monotonic"]) >= barrier
            ):
                observed = float(row["get_completed_at_monotonic"])
                first_success["first_affected_read"] = min(
                    observed,
                    first_success.get("first_affected_read", observed),
                )
            if (
                cluster_ok is not None
                and isinstance(row.get("started_at_monotonic"), (int, float))
                and float(row["started_at_monotonic"]) >= cluster_ok
            ):
                accumulator.record(
                    shard_id=probe.shard_id,
                    monotonic_ms_value=float(completed) * 1000.0,
                    set_succeeded=row.get("set_succeeded") is True,
                    get_succeeded=row.get("get_succeeded") is True,
                    value_matches=row.get("value_matches") is True,
                    error=str(row.get("error", "")),
                    timed_out=row.get("timed_out") is True,
                )


def _stable_shard_rows(accumulator: Any, summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for shard in summary.get("shards", []):
        if shard.get("status") != "PASS" or not isinstance(shard.get("stable_at_monotonic_ms"), (int, float)):
            continue
        shard_id = str(shard["shard_id"])
        endpoint_ms = float(shard["stable_at_monotonic_ms"])
        streak: list[dict[str, Any]] = []
        for sample in reversed(accumulator.samples.get(shard_id, [])):
            if float(sample["monotonic_ms"]) > endpoint_ms:
                continue
            if sample.get("status") != "PASS":
                break
            if streak and float(streak[-1]["monotonic_ms"]) - float(sample["monotonic_ms"]) > 100.0 + 1e-9:
                break
            streak.append(sample)
            if float(sample["monotonic_ms"]) < endpoint_ms - 1000.0:
                break
        in_window = [sample for sample in streak if float(sample["monotonic_ms"]) >= endpoint_ms - 1000.0]
        rows.append(
            {
                "shard_id": shard_id,
                "window_start_monotonic": round((endpoint_ms / 1000.0) - 1.0, 6),
                "window_seconds": 1,
                "consecutive_pairs": len(in_window),
                "errors": sum(1 for sample in in_window if sample.get("error")),
                "timeouts": sum(1 for sample in in_window if sample.get("timed_out") is True),
                "endpoint_monotonic": round(endpoint_ms / 1000.0, 6),
                "earliest_qualifying": True,
            }
        )
    return rows


def _fault_cadence(
    probes: list[FaultClientProbe],
    barrier: float | None,
    duration_seconds: float,
) -> dict[str, Any]:
    if barrier is None:
        return {"status": "FAIL", "affected_shard_max_interval_ms": "MISSING", "per_shard": []}
    end = barrier + duration_seconds
    per_shard: list[dict[str, Any]] = []
    affected_maxima: list[float] = []
    for probe in probes:
        starts = sorted(
            float(row["started_at_monotonic"])
            for row in probe.samples
            if isinstance(row.get("started_at_monotonic"), (int, float))
            and barrier <= float(row["started_at_monotonic"]) <= end
        )
        intervals = [max(starts[0] - barrier, 0.0)] if starts else []
        intervals.extend(right - left for left, right in zip(starts, starts[1:]))
        if starts:
            intervals.append(max(end - starts[-1], 0.0))
        max_ms = round(max(intervals) * 1000.0, 6) if intervals else "MISSING"
        passed = isinstance(max_ms, float) and max_ms <= 100.0 + 1e-6
        per_shard.append(
            {
                "shard_id": probe.shard_id,
                "affected": probe.affected,
                "attempt_count": len(starts),
                "max_attempt_interval_ms": max_ms,
                "status": "PASS" if passed else "FAIL",
            }
        )
        if probe.affected and isinstance(max_ms, float):
            affected_maxima.append(max_ms)
    expected_affected = sum(1 for probe in probes if probe.affected)
    complete = len(affected_maxima) == expected_affected and all(
        row["status"] == "PASS" for row in per_shard if row["affected"] is True
    )
    return {
        "status": "PASS" if complete else "FAIL",
        "affected_shard_max_interval_ms": max(affected_maxima) if complete else "MISSING",
        "per_shard": per_shard,
    }


def _fault_client_series(
    probes: list[FaultClientProbe],
    markers: dict[str, float],
    stable_shards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    barrier = markers.get("sigkill_barrier", float("inf"))
    stable_by_shard = {str(row["shard_id"]): float(row["endpoint_monotonic"]) for row in stable_shards}
    series: list[dict[str, Any]] = []
    for probe in probes:
        cadence_rows = [
            row
            for row in probe.samples
            if isinstance(row.get("started_at_monotonic"), (int, float))
            and float(row["started_at_monotonic"]) >= barrier
        ]
        recovery_rows = [
            row
            for row in probe.samples
            if isinstance(row.get("started_at_monotonic"), (int, float))
            and float(row["started_at_monotonic"]) >= barrier
            and isinstance(row.get("completed_at_monotonic"), (int, float))
            and float(row["completed_at_monotonic"]) >= float(row["started_at_monotonic"])
        ]
        endpoint = stable_by_shard.get(probe.shard_id)
        through_stable = [
            {
                "started_at_monotonic": row["started_at_monotonic"],
                "completed_at_monotonic": row["completed_at_monotonic"],
                "set_completed_at_monotonic": row["set_completed_at_monotonic"],
                "get_completed_at_monotonic": row["get_completed_at_monotonic"],
                "set_succeeded": row["set_succeeded"],
                "get_succeeded": row["get_succeeded"],
                "value_matches": row["value_matches"],
                "timed_out": row["timed_out"],
                "error": row["error"],
            }
            for row in recovery_rows
            if endpoint is None or float(row["completed_at_monotonic"]) <= endpoint
        ]
        series.append(
            {
                "shard_id": probe.shard_id,
                "affected": probe.affected,
                "key": probe.key,
                "attempt_started_monotonic": [row["started_at_monotonic"] for row in cadence_rows],
                "successful_pair_latencies_ms": [row["latency_ms"] for row in cadence_rows if row.get("status") == "PASS"],
                "attempt_count": len(cadence_rows),
                "set_success_count": sum(1 for row in cadence_rows if row.get("set_succeeded") is True),
                "get_success_count": sum(1 for row in cadence_rows if row.get("get_succeeded") is True),
                "error_count": sum(1 for row in cadence_rows if row.get("status") != "PASS"),
                "timeout_count": sum(1 for row in cadence_rows if row.get("timed_out") is True),
                "moved_count": sum(int(row.get("moved_count", 0)) for row in cadence_rows),
                "ask_count": sum(int(row.get("ask_count", 0)) for row in cadence_rows),
                "samples_through_stable_endpoint": through_stable if probe.affected else [],
            }
        )
    return series


def _fault_marker_names() -> tuple[str, ...]:
    return (
        "sigkill_barrier",
        "all_processes_gone",
        "first_pfail",
        "quorum_fail",
        "first_promotion",
        "all_slots_covered_cluster_ok",
        "stable_client_recovery",
        "every_node_converged",
    )


def _missing_fault_facts(
    markers: dict[str, float],
    first_success: dict[str, float],
    stable: dict[str, Any],
    stable_shards: list[dict[str, Any]],
    cadence: dict[str, Any],
    convergence: dict[str, Any],
    observed_safety: dict[str, Any],
) -> list[str]:
    missing = [f"missing monotonic marker {name}" for name in _fault_marker_names() if name not in markers]
    ordered = [markers[name] for name in _fault_marker_names() if name in markers]
    if len(ordered) == len(_fault_marker_names()) and any(left > right for left, right in zip(ordered, ordered[1:])):
        missing.append("fault monotonic markers are out of order")
    for name in ("first_affected_write", "first_affected_read"):
        if name not in first_success:
            missing.append(f"missing {name} timestamp")
    if stable.get("status") != "PASS":
        missing.append("not every affected shard reached its earliest stable one-second SET/GET window")
    required_shards = set(stable.get("required_shards", []))
    observed_stable = {str(row.get("shard_id")) for row in stable_shards}
    if observed_stable != required_shards or any(
        row.get("window_seconds") != 1
        or not isinstance(row.get("consecutive_pairs"), int)
        or row["consecutive_pairs"] < 10
        or row.get("errors") != 0
        or row.get("timeouts") != 0
        or row.get("earliest_qualifying") is not True
        for row in stable_shards
    ):
        missing.append("stable affected-shard evidence is incomplete or contains an error/timeout")
    if cadence.get("status") != "PASS":
        missing.append("affected-shard SET/GET attempt cadence exceeded 100 ms or was incomplete")
    if convergence.get("converged") is not True:
        missing.append("every surviving node did not prove converged topology")
    for field in ("unexpected_pfail", "unexpected_fail", "unexpected_promotions"):
        if observed_safety.get(field) != 0:
            missing.append(f"fault window has nonzero {field}")
    if observed_safety.get("split_brain") is not False:
        missing.append("fault window observed split brain")
    if convergence.get("slot_loss") is not False:
        missing.append("post-fault topology observed slot loss")
    return missing


def _fault_intervals(markers: dict[str, float], first_success: dict[str, float]) -> dict[str, float]:
    def delta(start: str, end: str) -> float:
        return round(float(markers[end]) - float(markers[start]), 6)

    return {
        "kill_to_stable_seconds": delta("sigkill_barrier", "stable_client_recovery"),
        "pfail_to_cluster_ok_seconds": delta("first_pfail", "all_slots_covered_cluster_ok"),
        "process_gone_to_pfail_seconds": delta("all_processes_gone", "first_pfail"),
        "cluster_ok_to_stable_seconds": delta("all_slots_covered_cluster_ok", "stable_client_recovery"),
        "sigkill_to_pfail_seconds": delta("sigkill_barrier", "first_pfail"),
        "pfail_to_quorum_fail_seconds": delta("first_pfail", "quorum_fail"),
        "quorum_fail_to_promotion_seconds": delta("quorum_fail", "first_promotion"),
        "promotion_to_cluster_ok_seconds": delta("first_promotion", "all_slots_covered_cluster_ok"),
        "recovery_to_convergence_seconds": delta("stable_client_recovery", "every_node_converged"),
        "sigkill_to_first_write_seconds": round(first_success["first_affected_write"] - markers["sigkill_barrier"], 6),
        "sigkill_to_first_read_seconds": round(first_success["first_affected_read"] - markers["sigkill_barrier"], 6),
    }


def _derive_formation_correctness(
    *,
    timeline: Mapping[str, Any],
    topology: Mapping[str, Any],
    workload: Mapping[str, Any],
    state: Mapping[str, Any],
    scale: int,
) -> dict[str, Any]:
    probes = topology.get("probes")
    events = timeline.get("events")
    state_nodes = state.get("nodes")
    if not isinstance(probes, list) or not isinstance(events, list) or not isinstance(state_nodes, list):
        raise CaptureError("formation correctness lacks raw topology, timeline, or state evidence")
    parsed_probes = [probe for probe in probes if isinstance(probe, dict)]
    views = [probe.get("cluster_nodes") for probe in parsed_probes]
    parsed_views = [view for view in views if isinstance(view, dict)]
    canonical_ids = set(parsed_views[0]) if parsed_views else set()
    exact_membership = (
        len(parsed_probes) == scale
        and len(parsed_views) == scale
        and len(canonical_ids) == scale
        and all(set(view) == canonical_ids for view in parsed_views)
        and all(probe.get("cluster_known_nodes") == scale for probe in parsed_probes)
    )
    slots = [probe.get("cluster_slots_ok") for probe in parsed_probes]
    slots_covered = min((int(value) for value in slots if isinstance(value, int) and not isinstance(value, bool)), default=0)
    bad_flags: dict[str, set[str]] = {}
    for view in parsed_views:
        for node_id, row in view.items():
            if not isinstance(row, dict):
                continue
            bad_flags.setdefault(str(node_id), set()).update(
                set(str(flag) for flag in row.get("flags", []))
                & {"pfail", "fail?", "fail", "handshake", "noaddr"}
            )
    link_clean = all(
        isinstance(row, dict) and row.get("link_state") == "connected"
        for view in parsed_views
        for row in view.values()
    )
    clean_topology = topology.get("status") == "PASS" and not any(bad_flags.values()) and link_clean

    first_view = parsed_views[0] if parsed_views else {}
    primary_slots: list[set[int]] = []
    for row in first_view.values():
        if isinstance(row, dict) and row.get("role") == "primary":
            primary_slots.append(_slots_for_node(row))
    seen_slots: set[int] = set()
    split_brain = False
    for owned_slots in primary_slots:
        if seen_slots.intersection(owned_slots):
            split_brain = True
        seen_slots.update(owned_slots)

    replica_count = sum(1 for node in state_nodes if isinstance(node, dict) and node.get("role") == "replica")
    synchronized_events = [
        event
        for event in events
        if isinstance(event, dict) and event.get("name") == "all_replicas_synchronized"
    ]
    replicas_synchronized = len(synchronized_events) == 1 and (
        synchronized_events[0].get("details", {}).get("replica_count") == replica_count
        and synchronized_events[0].get("details", {}).get("observed_count") == replica_count
    )
    data_path_events = [
        event for event in events if isinstance(event, dict) and event.get("name") == "data_path_probe"
    ]
    data_path = len(data_path_events) == 1 and workload.get("status") == "PASS"

    logical_to_node_id = _node_ids_by_logical(parsed_probes) if exact_membership else {}
    unexpected_promotions = 0
    for node in state_nodes:
        if not isinstance(node, dict) or node.get("role") != "replica":
            continue
        node_id = logical_to_node_id.get(str(node.get("logical_id")))
        row = first_view.get(node_id, {}) if node_id else {}
        if isinstance(row, dict) and row.get("role") == "primary":
            unexpected_promotions += 1

    result = {
        "exact_membership": exact_membership,
        "observed_nodes": len(canonical_ids),
        "slots_covered": slots_covered,
        "replicas_synchronized": replicas_synchronized,
        "clean_topology": clean_topology,
        "data_path": data_path,
        "split_brain": split_brain,
        "unexpected_pfail": sum(1 for flags in bad_flags.values() if flags & {"pfail", "fail?"}),
        "unexpected_fail": sum(1 for flags in bad_flags.values() if "fail" in flags),
        "unexpected_promotions": unexpected_promotions,
        "slot_loss": slots_covered != 16384,
    }
    stability = workload.get("stability_observation")
    if isinstance(stability, dict):
        stability_samples = [
            sample
            for sample in stability.get("samples", [])
            if isinstance(sample, dict) and isinstance(sample.get("facts"), dict)
        ]
        pfail_ids = {
            str(node_id)
            for sample in stability_samples
            for node_id in sample["facts"].get("unexpected_pfail_node_ids", [])
        }
        fail_ids = {
            str(node_id)
            for sample in stability_samples
            for node_id in sample["facts"].get("unexpected_fail_node_ids", [])
        }
        promotion_ids = {
            str(node_id)
            for sample in stability_samples
            for node_id in sample["facts"].get("unexpected_promotion_node_ids", [])
        }
        result.update(
            {
                "clean_topology": result["clean_topology"]
                and stability.get("status") == "PASS"
                and bool(stability_samples)
                and all(sample["facts"].get("clean_topology") is True for sample in stability_samples),
                "split_brain": result["split_brain"]
                or any(sample["facts"].get("split_brain") is True for sample in stability_samples),
                "unexpected_pfail": len(pfail_ids),
                "unexpected_fail": len(fail_ids),
                "unexpected_promotions": len(promotion_ids),
                "slot_loss": result["slot_loss"]
                or any(sample["facts"].get("slot_loss") is True for sample in stability_samples),
            }
        )
    if not (
        result["exact_membership"]
        and result["observed_nodes"] == scale
        and result["slots_covered"] == 16384
        and result["replicas_synchronized"]
        and result["clean_topology"]
        and result["data_path"]
        and result["split_brain"] is False
        and result["unexpected_pfail"] == 0
        and result["unexpected_fail"] == 0
        and result["unexpected_promotions"] == 0
        and result["slot_loss"] is False
    ):
        raise CaptureError("formation correctness is not proven by raw current-trial observations")
    return result


def _build_trial(
    ctx: CaptureContext,
    spec: ArmSpec,
    state: dict[str, Any],
    preflight_path: Path,
    preflight: dict[str, Any],
    trial_dir: Path,
    cleanup: dict[str, Any],
    measurement: dict[str, Any],
) -> dict[str, Any]:
    timeline_path = trial_dir / f"setup_timeline_{spec.scenario}.json"
    timeline = _load_object(timeline_path)
    events = timeline.get("events")
    if not isinstance(events, list):
        raise CaptureError("setup timeline has no observed M2 events")
    markers = {str(row.get("name")): float(row["at_monotonic"]) for row in events if isinstance(row, dict) and isinstance(row.get("at_monotonic"), (int, float))}
    if any(name not in markers for name in SETUP_EVENTS):
        raise CaptureError("setup timeline is missing required formation events")
    unexplained_seconds = timeline.get("setup_timeline_unexplained_seconds")
    if (
        isinstance(unexplained_seconds, bool)
        or not isinstance(unexplained_seconds, (int, float))
        or float(unexplained_seconds) != 0.0
    ):
        raise CaptureError("setup timeline contains missing or unexplained wall time")
    resource_report = measurement["resource"]
    resource_metrics = dict(resource_report["metrics"])
    resource_metrics.update(
        {
            "duration_seconds": float(resource_report["duration_seconds"]),
            "cluster_link_errors": int(resource_metrics["cluster_link_errors"]),
            "buffer_overflows": int(resource_metrics["buffer_overflows"]),
        }
    )
    workload_raw = measurement["workload"]
    workload = {
        "duration_seconds": float(workload_raw["duration_seconds"]),
        "set_throughput_ops_per_second": float(workload_raw["set_throughput_ops_per_second"]),
        "p99_latency_ms": float(workload_raw["p99_latency_ms"]),
        "errors": int(workload_raw.get("error_count", len(workload_raw.get("errors", [])))),
        "persistent_cluster_client": workload_raw.get("persistent_cluster_client") is True,
        "per_operation_process_spawn": workload_raw.get("per_operation_process_spawn") is True,
        "affected_shard_max_interval_ms": float(workload_raw.get("affected_shard_max_interval_ms", 100.0)),
        "stable_shards": list(workload_raw.get("stable_shards", [])),
    }
    topology_digest = _digest(_topology_control(state))
    placement_digest = _digest(_placement_control(state))
    versions = measurement["topology"]["versions"]
    binary_sha256s = measurement["topology"]["valkey_binary_sha256s"]
    valkey_digest = _digest(
        {"versions": sorted(versions), "valkey_binary_sha256s": sorted(binary_sha256s)}
    )
    config_digest = _file_digest(ROOT / "templates" / "configs" / f"scale_{spec.scale}.yaml")
    fault_document = measurement.get("fault") if isinstance(measurement.get("fault"), dict) else {}
    raw_fault_targets = fault_document.get("targets") if isinstance(fault_document, dict) else []
    fault_targets = [
        {
            "logical_id": str(target.get("logical_id")),
            "shard_id": str(target.get("shard_id")),
        }
        for target in (raw_fault_targets if isinstance(raw_fault_targets, list) else [])
        if isinstance(target, dict)
    ]
    workload_digest = _digest(
        {
            "value_size_bytes": 512,
            "persistent": True,
            "duration": workload_raw.get("requested_duration_seconds"),
            "fault_targets": sorted(fault_targets, key=lambda row: (row["logical_id"], row["shard_id"])),
        }
    )
    controls = {
        "valkey_binary": valkey_digest,
        "product": ctx.product_digest,
        "configuration_except_treatment": config_digest,
        "topology": topology_digest,
        "placement": placement_digest,
        "host": ctx.environment_digest,
        "workload": workload_digest,
        "resource_preflight": _file_digest(preflight_path),
    }
    if set(controls) != CONTROL_KEYS:
        raise CaptureError("internal control digest set is incomplete")
    provenance_path = trial_dir / "evidence_provenance.json"
    categorized = _trial_source_paths(trial_dir, spec, measurement)
    capture_digest = _digest({category: _file_digest(path) for category, path in categorized if path.is_file()})
    command_path = trial_dir / "command_log.jsonl"
    provenance = {
        "status": "PASS",
        "current_invocation": True,
        "invocation_run_id": str(ctx.args.run_id),
        "product_owned": True,
        "fixture": False,
        "historical": False,
        "valkey_versions": versions,
        "valkey_binary_digest": valkey_digest,
        "resource_preflight_digest": _file_digest(preflight_path),
        "definition_digest": _digest({"mode": ctx.args.mode, "protocol": _protocol()}),
        "product_digest": ctx.product_digest,
        "configuration_digest": config_digest,
        "environment_digest": ctx.environment_digest,
        "topology_digest": topology_digest,
        "placement_digest": placement_digest,
        "workload_digest": workload_digest,
        "command_digest": _file_digest(command_path),
        "capture_digest": capture_digest,
        "evidence_ref": _rel(ctx, provenance_path),
    }
    _write_json(provenance_path, provenance)
    categorized.append(("provenance", provenance_path))
    refs = [_source_ref(ctx, category, path) for category, path in categorized]
    ctx.source_refs.extend(refs)
    correctness = measurement.get("correctness")
    if not isinstance(correctness, dict) or not correctness:
        correctness = _derive_formation_correctness(
            timeline=timeline,
            topology=measurement["topology"],
            workload=workload_raw,
            state=state,
            scale=spec.scale,
        )
    markers.update(measurement.get("monotonic_markers", {}))
    derived_intervals = {
        "formation_seconds": round(markers["data_path_probe"] - markers["last_process_ping"], 6),
        **measurement.get("derived_intervals", {}),
    }
    return {
        "trial_id": spec.trial_id,
        "pair_id": spec.pair_id,
        "cell_id": spec.cell_id,
        "arm": spec.arm,
        "order": spec.order,
        "scale": spec.scale,
        "run_id": str(state["runtime"]["run_id"]),
        "ownership_id": str(state["runtime"]["run_id"]),
        "evidence_root": _rel(ctx, trial_dir),
        "real_valkey": True,
        "fresh_cluster": True,
        "treatment": spec.treatment,
        "timing_source": "monotonic-observed",
        "unexplained_seconds": float(unexplained_seconds),
        "monotonic_markers": markers,
        "derived_intervals": derived_intervals,
        "correctness": correctness,
        "resource_window": resource_metrics,
        "workload": workload,
        "fault": measurement.get("fault"),
        "cleanup": {
            "status": cleanup["status"],
            "resources_remaining": cleanup.get("resources_remaining", []),
            "cleanup_errors": cleanup.get("cleanup_errors", []),
            "evidence_ref": _rel(ctx, trial_dir / "cleanup_report.json"),
        },
        "provenance": provenance,
        "source_sha256s": refs,
        "control_digests": controls,
    }


def _ensure_preflight(ctx: CaptureContext, scale: int, scenario: str) -> tuple[Path, dict[str, Any]]:
    key = (scale, scenario)
    if key in ctx.preflights:
        return ctx.preflights[key]
    path = ctx.artifacts_dir / f"resource_preflight_{scenario}_{scale}.json"
    config = ROOT / "templates" / "configs" / f"scale_{scale}.yaml"
    command = [
        sys.executable,
        "-m",
        "valkey_scale_lab.cli",
        "resource",
        "preflight",
        "--config",
        str(config),
        "--out",
        str(path),
        "--capability-id",
        scenario,
        "--scenario",
        scenario,
        "--profile",
        f"exact-{scale}",
    ]
    result = _run_command(command, env=_base_environment(), timeout=120)
    report = _load_object(path) if path.is_file() else {}
    if result["returncode"] != 0 or report.get("can_run") is not True:
        raise EnvironmentBlocked(result["stderr"][-1000:] or "resource preflight did not authorize exact run")
    ctx.preflights[key] = (path, report)
    ctx.source_refs.append(_source_ref(ctx, "preflight", path))
    return path, report


def _setup_command(spec: ArmSpec, trial_dir: Path, state_path: Path) -> list[str]:
    config = ROOT / "templates" / "configs" / f"scale_{spec.scale}.yaml"
    command = [
        sys.executable,
        "-m",
        "valkey_scale_lab.cli",
        "gate",
        "scenario",
        "--scenario",
        spec.scenario,
        "--backend",
        "docker_process",
        "--profile",
        f"exact-{spec.scale}",
        "--nodes",
        str(spec.scale),
        "--config",
        str(config),
        "--run-id",
        spec.trial_id,
        "--artifacts-dir",
        str(trial_dir),
        "--state-out",
        str(state_path),
    ]
    timeout = spec.treatment.get("value") if spec.treatment.get("kind") == "cluster_node_timeout_ms" else spec.treatment.get("cluster_node_timeout_ms")
    if isinstance(timeout, int):
        command.extend(["--cluster-node-timeout-ms", str(timeout)])
    return command


def _cleanup_command(trial_dir: Path, state_path: Path, cleanup_path: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "valkey_scale_lab.cli",
        "gate",
        "cleanup",
        "--state",
        str(state_path),
        "--artifacts-dir",
        str(trial_dir),
        "--out",
        str(cleanup_path),
    ]


def _cleanup_state_for_attempt(
    trial_dir: Path,
    state_path: Path,
    *,
    capability_id: str,
    run_id: str,
) -> Path:
    if state_path.is_file() and not state_path.is_symlink():
        try:
            state = _load_object(state_path)
        except (CaptureError, OSError, UnicodeError, json.JSONDecodeError):
            state = {}
        runtime = state.get("runtime")
        if (
            state.get("capability_id") == capability_id
            and isinstance(runtime, dict)
            and runtime.get("run_id") == run_id
            and runtime.get("type") == "docker_process"
            and isinstance(state.get("nodehosts"), list)
            and bool(state["nodehosts"])
            and isinstance(state.get("nodes"), list)
            and bool(state["nodes"])
        ):
            return state_path
    recovery_path = trial_dir / "cleanup_recovery_state.json"
    _write_json(
        recovery_path,
        {
            "capability_id": capability_id,
            "scenario": capability_id,
            "runtime": {
                "type": "m2_label_recovery",
                "run_id": run_id,
                "recovery_scope": "exact product-owned Docker labels",
            },
        },
    )
    return recovery_path


def _treatment_environment(spec: ArmSpec) -> dict[str, str]:
    env = _base_environment()
    env["VSLAB_M2_MEASUREMENT"] = "1"
    env["VSLAB_M2_RUN_ID"] = spec.trial_id
    env.pop("VSLAB_M2_BOOTSTRAP_RESOURCE_SECONDS", None)
    env.pop("VSLAB_CLUSTER_CREATE_STRATEGY", None)
    env.pop("VSLAB_CLUSTER_CREATE_PARALLELISM", None)
    env.pop("VSLAB_REPLICA_REPLICATE_PARALLELISM", None)
    if spec.treatment.get("kind") == "cluster_create_strategy":
        env["VSLAB_CLUSTER_CREATE_STRATEGY"] = str(spec.treatment["value"])
    elif spec.treatment.get("kind") == "cluster_node_timeout_ms":
        env["VSLAB_CLUSTER_CREATE_STRATEGY"] = str(spec.treatment["cluster_create_strategy"])
    elif spec.treatment.get("kind") == "selected_settings":
        env["VSLAB_CLUSTER_CREATE_STRATEGY"] = str(spec.treatment["cluster_create_strategy"])
    bounded_parallelism = spec.treatment.get("bounded_parallelism")
    if isinstance(bounded_parallelism, int) and not isinstance(bounded_parallelism, bool):
        env["VSLAB_CLUSTER_CREATE_PARALLELISM"] = str(bounded_parallelism)
    if _uses_setup_resource_window(spec):
        env["VSLAB_M2_BOOTSTRAP_RESOURCE_SECONDS"] = str(spec.resource_seconds)
    return env


def _uses_setup_resource_window(spec: ArmSpec) -> bool:
    return spec.scenario == "cluster_timeout" and "soak" not in spec.cell_id


def _needs_stability_observation(spec: ArmSpec) -> bool:
    return spec.cell_id.startswith("stability-")


def _base_environment() -> dict[str, str]:
    env = dict(os.environ)
    src = str(ROOT / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not existing else f"{src}{os.pathsep}{existing}"
    return env


def _run_command(command: list[str], *, env: Mapping[str, str], timeout: int) -> dict[str, Any]:
    started_wall = time.time()
    started_mono = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            env=dict(env),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = str(exc.stdout or "")
        stderr = f"timeout after {timeout}s: {exc.stderr or ''}"
    return {
        "argv": command,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "started_at_unix_ms": int(started_wall * 1000),
        "ended_at_unix_ms": int(time.time() * 1000),
        "started_at_monotonic": round(started_mono, 6),
        "ended_at_monotonic": round(time.monotonic(), 6),
    }


def _command_boundary(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "returncode": result.get("returncode", "MISSING"),
        "started_at_monotonic": result.get("started_at_monotonic", "MISSING"),
        "ended_at_monotonic": result.get("ended_at_monotonic", "MISSING"),
    }


def _exhaustive_setup_wrapper_segments(
    segments: list[Any],
    *,
    outer_start: float,
    outer_end: float,
) -> list[dict[str, Any]]:
    if outer_end < outer_start:
        raise CaptureError("setup wrapper ends before it starts")

    expanded: list[dict[str, Any]] = []
    previous_end = outer_start
    previous_name = "setup_wrapper_start"
    internal_gap_index = 0
    for index, raw in enumerate(segments):
        if not isinstance(raw, dict):
            raise CaptureError(f"setup timeline segment {index} is not an object")
        start = raw.get("start_monotonic")
        end = raw.get("end_monotonic")
        if (
            isinstance(start, bool)
            or not isinstance(start, (int, float))
            or isinstance(end, bool)
            or not isinstance(end, (int, float))
            or not math.isfinite(float(start))
            or not math.isfinite(float(end))
        ):
            raise CaptureError(f"setup timeline segment {index} has invalid monotonic bounds")
        segment_start = float(start)
        segment_end = float(end)
        segment_name = str(raw.get("name", f"segment_{index + 1:03d}"))
        if segment_end < segment_start:
            raise CaptureError(f"setup timeline segment {segment_name!r} ends before it starts")
        if segment_start < outer_start or segment_end > outer_end:
            raise CaptureError("setup timeline falls outside its observed wrapper bounds")
        if segment_start < previous_end:
            raise CaptureError(f"setup timeline segment {segment_name!r} overlaps its predecessor")
        if segment_start > previous_end:
            if index == 0:
                gap_name = "setup_wrapper_before_cli_timeline"
                reason = "observed process-wrapper startup before CLI timeline origin"
            else:
                internal_gap_index += 1
                gap_name = f"setup_wrapper_between_cli_segments_{internal_gap_index:03d}"
                reason = "observed elapsed time between adjacent CLI timeline segments"
            expanded.append(
                {
                    "name": gap_name,
                    "kind": "gap",
                    "category": "gap",
                    "start_monotonic": previous_end,
                    "end_monotonic": segment_start,
                    "status": "PASS",
                    "details": {
                        "reason": reason,
                        "previous_segment": previous_name,
                        "next_segment": segment_name,
                    },
                }
            )
        expanded.append(dict(raw))
        previous_end = segment_end
        previous_name = segment_name

    if previous_end < outer_end:
        expanded.append(
            {
                "name": "setup_wrapper_after_cli_timeline",
                "kind": "gap",
                "category": "gap",
                "start_monotonic": previous_end,
                "end_monotonic": outer_end,
                "status": "PASS",
                "details": {
                    "reason": "observed CLI process exit after final setup span",
                    "previous_segment": previous_name,
                    "next_segment": "setup_wrapper_end",
                },
            }
        )
    for index, segment in enumerate(expanded, start=1):
        segment["id"] = f"segment_{index:03d}"
    return expanded


def _attach_setup_wrapper_timing(
    timeline_path: Path,
    setup_result: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    topology: Mapping[str, Any],
) -> None:
    from valkey_scale_lab.runtime.setup_timeline import (
        build_setup_timeline_artifact,
        validate_setup_timeline_artifact,
    )

    timeline = _load_object(timeline_path)
    segments = timeline.get("segments")
    events = timeline.get("events")
    start = setup_result.get("started_at_monotonic")
    end = setup_result.get("ended_at_monotonic")
    if (
        not isinstance(segments, list)
        or not segments
        or not isinstance(events, list)
        or isinstance(start, bool)
        or not isinstance(start, (int, float))
        or isinstance(end, bool)
        or not isinstance(end, (int, float))
        or not all(math.isfinite(float(value)) for value in (start, end))
    ):
        raise CaptureError("setup wrapper monotonic evidence is missing")
    outer_start = float(start)
    outer_end = float(end)
    expanded = _exhaustive_setup_wrapper_segments(
        segments,
        outer_start=outer_start,
        outer_end=outer_end,
    )

    nodes = state.get("nodes")
    if not isinstance(nodes, list):
        raise CaptureError("setup wrapper cannot derive exact role counts")
    roles = {
        "primary": sum(1 for node in nodes if isinstance(node, dict) and node.get("role") == "primary"),
        "replica": sum(1 for node in nodes if isinstance(node, dict) and node.get("role") == "replica"),
    }
    rebuilt = build_setup_timeline_artifact(
        capability_id=str(timeline.get("capability_id", "")),
        run_id=str(timeline.get("run_id", "")),
        scenario=str(timeline.get("scenario", "")),
        profile_id=str(timeline.get("profile_id", "")),
        node_count=int(timeline.get("node_count", 0)),
        status=str(timeline.get("status", "FAIL")),
        segments=expanded,
        events=[dict(event) for event in events],
        setup_command_wall_seconds=round(outer_end - outer_start, 6),
        real_valkey_evidence_summary={
            "status": "PASS" if topology.get("status") == "PASS" else "FAIL",
            "real_valkey": True,
            "nodes_observed": len(nodes),
            "data_path_result": "PASS"
            if any(isinstance(event, dict) and event.get("name") == "data_path_probe" for event in events)
            else "FAIL",
            "role_counts": roles,
            "valkey_versions": list(topology.get("versions", [])),
        },
        source_artifacts=list(timeline.get("source_artifacts", [])),
        extra={
            "setup_command_wall_source": {
                "status": "PASS",
                "clock": "monotonic",
                "started_at_monotonic": round(outer_start, 6),
                "ended_at_monotonic": round(outer_end, 6),
            }
        },
    )
    errors = validate_setup_timeline_artifact(rebuilt)
    if (
        rebuilt.get("setup_timeline_unexplained_seconds") != 0.0
        or rebuilt.get("setup_timeline_total_seconds") != rebuilt.get("setup_command_wall_seconds")
        or errors
    ):
        raise CaptureError("setup wrapper does not account for all monotonic wall time: " + "; ".join(errors))
    _write_json(timeline_path, rebuilt)


def _validate_state(state: dict[str, Any], spec: ArmSpec) -> None:
    runtime = state.get("runtime")
    nodes = state.get("nodes")
    if not isinstance(runtime, dict) or runtime.get("type") != "docker_process":
        raise CaptureError("setup state is not a real docker_process runtime")
    if runtime.get("run_id") != spec.trial_id:
        raise CaptureError("runtime ownership id does not equal the current trial id")
    if state.get("requested_nodes") != spec.scale or state.get("observed_nodes") != spec.scale:
        raise CaptureError("setup state is downscaled or has inexact membership")
    if not isinstance(nodes, list) or len(nodes) != spec.scale:
        raise CaptureError("setup state lacks the exact node set")
    if len({(node.get("container_name"), node.get("pid")) for node in nodes if isinstance(node, dict)}) != spec.scale:
        raise CaptureError("setup state has duplicate physical process ownership")
    expected_strategy = spec.treatment.get("value") if spec.treatment.get("kind") == "cluster_create_strategy" else spec.treatment.get("cluster_create_strategy")
    if expected_strategy is not None and runtime.get("cluster_create_strategy") != expected_strategy:
        raise CaptureError("runtime cluster-create treatment does not match the requested arm")
    expected_parallelism = spec.treatment.get("bounded_parallelism")
    if isinstance(expected_parallelism, int) and runtime.get("cluster_create_parallelism") != expected_parallelism:
        raise CaptureError("runtime cluster-create parallelism does not match the requested arm")
    expected_timeout = spec.treatment.get("value") if spec.treatment.get("kind") == "cluster_node_timeout_ms" else spec.treatment.get("cluster_node_timeout_ms")
    if isinstance(expected_timeout, int) and runtime.get("effective_cluster_node_timeout_ms") != expected_timeout:
        raise CaptureError("runtime cluster timeout treatment does not match the requested arm")


def _cleanup_error(
    result: dict[str, Any],
    cleanup: dict[str, Any],
    state: dict[str, Any],
    *,
    expected_run_id: str,
) -> str:
    if result.get("returncode") != 0:
        return "owned cleanup command failed"
    if cleanup.get("status") != "PASS":
        return "owned cleanup report did not PASS"
    if cleanup.get("resources_remaining") != [] or cleanup.get("cleanup_errors") != []:
        return "owned cleanup left residual resources or errors"
    if cleanup.get("run_id") != expected_run_id:
        return "cleanup ownership id does not match the current trial"
    runtime = state.get("runtime") if isinstance(state, dict) else None
    if isinstance(runtime, dict) and cleanup.get("run_id") != runtime.get("run_id"):
        return "cleanup ownership id does not match setup state"
    return ""


def _trial_source_paths(trial_dir: Path, spec: ArmSpec, measurement: dict[str, Any]) -> list[tuple[str, Path]]:
    rows = [
        ("attempt", trial_dir / "attempt_ledger.json"),
        ("state", trial_dir / "state.json"),
        ("cleanup", trial_dir / "cleanup_report.json"),
        ("timeline", trial_dir / f"setup_timeline_{spec.scenario}.json"),
        ("command_log", trial_dir / "command_log.jsonl"),
        ("resource", trial_dir / "resource_window.json"),
        ("workload", trial_dir / "workload_observation.json"),
        ("topology", trial_dir / "topology_observation.json"),
    ]
    if measurement.get("fault") is not None or (trial_dir / "fault_observation.json").is_file():
        rows.append(("fault", trial_dir / "fault_observation.json"))
    missing = [path.name for _category, path in rows if not path.is_file()]
    if missing:
        raise CaptureError(f"trial source set is incomplete: {', '.join(missing)}")
    return rows


def _collect_partial_refs(ctx: CaptureContext, trial_dir: Path, spec: ArmSpec) -> None:
    candidates = [
        ("attempt", trial_dir / "attempt_ledger.json"),
        ("state", trial_dir / "state.json"),
        ("cleanup", trial_dir / "cleanup_report.json"),
        ("timeline", trial_dir / f"setup_timeline_{spec.scenario}.json"),
        ("command_log", trial_dir / "command_log.jsonl"),
        ("resource", trial_dir / "resource_window.json"),
        ("workload", trial_dir / "workload_observation.json"),
        ("topology", trial_dir / "topology_observation.json"),
        ("fault", trial_dir / "fault_observation.json"),
    ]
    for category, path in candidates:
        if path.is_file() and not path.is_symlink():
            ctx.source_refs.append(_source_ref(ctx, category, path))


def _source_ref(ctx: CaptureContext, category: str, path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        raise CaptureError(f"current-invocation source is absent or unsafe: {path}")
    return {"category": category, "path": _rel(ctx, path), "sha256": _file_digest(path)}


def _rel(ctx: CaptureContext, path: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(ctx.artifacts_dir):
        raise CaptureError(f"source escapes current artifact directory: {path}")
    return resolved.relative_to(ctx.artifacts_dir).as_posix()


def _selected_strategy(value: Any) -> str:
    if value == "current-default":
        return _current_strategy_default()
    if not isinstance(value, str) or not value:
        raise CaptureError("selected formation strategy is missing")
    return value


def _selected_strategy_parallelism(value: Any) -> int | None:
    from valkey_scale_lab.runtime import docker_runtime

    selected = getattr(docker_runtime, "CLUSTER_CREATE_PARALLELISM_DEFAULT", None)
    if not isinstance(selected, int) or isinstance(selected, bool):
        return None
    strategy = _current_strategy_default() if value == "current-default" else str(value)
    return selected if strategy == "tree_meet_addslotsrange" else None


def _selected_timeout(value: Any) -> int:
    if value == "current-default":
        return _current_timeout_default()
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise CaptureError("selected timeout must be current-default or a positive integer") from exc
    if parsed <= 0:
        raise CaptureError("selected timeout must be positive")
    return parsed


def _current_timeout_default() -> int:
    from valkey_scale_lab.cluster_timeout import DEFAULT_CLUSTER_NODE_TIMEOUT_MS

    return int(DEFAULT_CLUSTER_NODE_TIMEOUT_MS)


def _current_strategy_default() -> str:
    from valkey_scale_lab.runtime.docker_runtime import CLUSTER_CREATE_STRATEGY_DEFAULT

    return str(CLUSTER_CREATE_STRATEGY_DEFAULT)


def _failed_primary_count(scale: int, rate: str) -> int:
    primaries = scale // 2
    if rate == "one":
        return 1
    multiplier = 0.10 if rate == "10_percent" else 0.33 if rate == "33_percent" else None
    if multiplier is None:
        raise CaptureError(f"unsupported fault rate {rate!r}")
    return int((primaries * multiplier) + 0.5)


def _treatment_id(treatment: Mapping[str, Any]) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", str(treatment.get("value", "candidate"))).strip("-")
    parallelism = treatment.get("bounded_parallelism")
    return f"{value}-p{parallelism}" if isinstance(parallelism, int) else value


def _failover_discovery_passed(ctx: CaptureContext, pair: Mapping[str, Any]) -> bool:
    baseline, candidate = _pair_trials(ctx, dict(pair))
    baseline_intervals = baseline.get("derived_intervals", {})
    candidate_intervals = candidate.get("derived_intervals", {})
    required = (
        "kill_to_stable_seconds",
        "pfail_to_cluster_ok_seconds",
        "process_gone_to_pfail_seconds",
        "cluster_ok_to_stable_seconds",
    )
    if not all(
        isinstance(baseline_intervals.get(name), (int, float))
        and isinstance(candidate_intervals.get(name), (int, float))
        for name in required
    ):
        return False
    return (
        float(candidate_intervals["kill_to_stable_seconds"])
        < float(baseline_intervals["kill_to_stable_seconds"])
        and float(candidate_intervals["kill_to_stable_seconds"]) <= 35.0
        and float(candidate_intervals["pfail_to_cluster_ok_seconds"]) <= 10.0
        and float(candidate_intervals["process_gone_to_pfail_seconds"]) <= 25.0
        and float(candidate_intervals["cluster_ok_to_stable_seconds"]) <= 2.0
    )


def _observed_versions(state: dict[str, Any]) -> list[str]:
    from valkey_scale_lab.observer.failover_timeline import ObserverEndpoint, _RespConnection, parse_info

    versions: set[str] = set()
    for node in state["nodes"]:
        endpoint = ObserverEndpoint.from_node(node)
        raw = _RespConnection(endpoint, 2.0).execute("INFO", "server")
        info = parse_info(str(raw))
        version = info.get("valkey_version") or info.get("redis_version")
        if not isinstance(version, str) or not version.startswith("9.1."):
            raise CaptureError("observed Valkey version is missing or not 9.1.x")
        versions.add(version)
    return sorted(versions)


def _observed_binary_sha256s(state: dict[str, Any]) -> list[str]:
    from valkey_scale_lab.runtime.docker_runtime import run_docker

    digests: set[str] = set()
    containers = sorted({str(node["container_name"]) for node in state["nodes"]})
    command = 'binary=$(command -v valkey-server) || exit 1; sha256sum "$binary"'
    for container in containers:
        result = run_docker(
            ["exec", container, "sh", "-c", command],
            timeout=30,
            check=True,
        )
        digest = result.stdout.strip().split(maxsplit=1)[0]
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise CaptureError(f"Valkey binary digest is unavailable in {container}")
        digests.add(digest)
    if not digests:
        raise CaptureError("Valkey binary digest set is empty")
    return sorted(digests)


def _topology_control(state: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (
            {
                "logical_id": node["logical_id"],
                "shard_id": node["shard_id"],
                "role": node["role"],
                "az_id": node["az_id"],
            }
            for node in state["nodes"]
        ),
        key=lambda row: row["logical_id"],
    )


def _placement_control(state: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (
            {
                "logical_id": node["logical_id"],
                "nodehost_id": node["nodehost_id"],
                "host_id": node["host_id"],
                "az_id": node["az_id"],
            }
            for node in state["nodes"]
        ),
        key=lambda row: row["logical_id"],
    )


def _pair_trials(ctx: CaptureContext, pair: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    by_id = {trial["trial_id"]: trial for trial in ctx.trials}
    return by_id[pair["baseline_trial_id"]], by_id[pair["candidate_trial_id"]]


def _cell(cell_id: str, campaign_step: str, scale: int, failure_rate: str, required: int, candidate: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "cell_id": cell_id,
        "campaign_step": campaign_step,
        "scale": scale,
        "failure_rate": failure_rate,
        "required_pairs": required,
        "candidate": candidate,
        "status": status,
    }


def _protocol() -> dict[str, Any]:
    return {
        "percentile_method": "nearest-rank",
        "paired": True,
        "arm_order": "alternating-AB-BA",
        "fresh_cluster_per_arm": True,
        "cleanup_between_arms": True,
        "fixture_admission_allowed": False,
        "historical_admission_allowed": False,
        "downscale_allowed": False,
        "takeover_allowed": False,
        "formation_pairs_per_scale": 7,
        "failover_pairs_per_cell": 10,
        "stable_window_seconds": 1,
        "stable_window_min_pairs": 10,
        "affected_shard_max_interval_ms": 100,
        "soak_seconds": 1800,
    }


def _report_treatments(ctx: CaptureContext) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if ctx.args.mode == "formation":
        baseline = {"kind": "cluster_create_strategy", "value": BASELINE_STRATEGY}
        selected = dict(ctx.selected_candidate or {"kind": "cluster_create_strategy", "value": _selected_strategy(ctx.args.selected_strategy)})
        parallelism = _selected_strategy_parallelism(ctx.args.selected_strategy)
        if parallelism is not None:
            selected.setdefault("bounded_parallelism", parallelism)
        return baseline, _formation_candidates(), selected
    if ctx.args.mode == "failover":
        baseline = _timeout_treatment(BASELINE_TIMEOUT_MS)
        selected = dict(ctx.selected_candidate or _timeout_treatment(_selected_timeout(ctx.args.selected_timeout_ms)))
        candidates = [_timeout_treatment(value) for value in (5000, 10000, 15000)]
        return baseline, candidates, selected
    baseline = {
        "kind": "selected_settings",
        "value": "m1-defaults",
        "cluster_create_strategy": BASELINE_STRATEGY,
        "cluster_node_timeout_ms": BASELINE_TIMEOUT_MS,
    }
    selected = dict(
        ctx.selected_candidate
        or {
            "kind": "selected_settings",
            "value": "selected",
            "cluster_create_strategy": _selected_strategy(ctx.args.selected_strategy),
            "cluster_node_timeout_ms": _selected_timeout(ctx.args.selected_timeout_ms),
        }
    )
    parallelism = _selected_strategy_parallelism(ctx.args.selected_strategy)
    if parallelism is not None:
        selected.setdefault("bounded_parallelism", parallelism)
    return baseline, [selected], selected


def _formation_candidates() -> list[dict[str, Any]]:
    return [
        {"kind": "cluster_create_strategy", "value": "manual_tree_meet_parallel_slots"},
        *[
            {
                "kind": "cluster_create_strategy",
                "value": "tree_meet_addslotsrange",
                "bounded_parallelism": parallelism,
            }
            for parallelism in (4, 8, 16)
        ],
    ]


def _timeout_treatment(value: int) -> dict[str, Any]:
    return {
        "kind": "cluster_node_timeout_ms",
        "value": value,
        "cluster_create_strategy": _current_strategy_default(),
    }


def _build_report(ctx: CaptureContext, *, status: str, errors: list[str], real_valkey: bool = True) -> dict[str, Any]:
    baseline, candidates, selected = _report_treatments(ctx)
    criterion_status = status if status in {"PASS", "FAIL", "BLOCKED"} else "FAIL"
    report: dict[str, Any] = {
        "schema_version": "m2-performance-report-v1",
        "artifact_type": "m2_performance_report",
        "campaign_id": str(ctx.args.run_id),
        "invocation_run_id": str(ctx.args.run_id),
        "experiment_kind": str(ctx.args.mode),
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "producer": {"name": "valkey-scale-lab", "version": _product_version()},
        "status": status,
        "real_valkey": real_valkey,
        "execution_mode": "valkey-real" if real_valkey else "not-run",
        "baseline": baseline,
        "candidates": candidates,
        "selected_candidate": selected,
        "current_defaults": {
            "cluster_create_strategy": _current_strategy_default(),
            "cluster_node_timeout_ms": _current_timeout_default(),
        },
        "protocol": _protocol(),
        "started_trial_ids": list(ctx.started_trial_ids),
        "trials": ctx.trials,
        "pairs": ctx.pairs,
        "cells": ctx.cells,
        "criterion_results": [
            {"criterion_id": criterion_id, "status": criterion_status, "errors": list(errors)}
            for criterion_id in sorted(CRITERIA[str(ctx.args.mode)])
        ],
        "invalid_samples": ctx.invalid_samples,
        "source_refs": _unique_refs(ctx.source_refs),
        "errors": errors,
        "report_digest": "",
    }
    report["report_digest"] = _report_digest(report)
    return report


def _write_failed_report(ctx: CaptureContext, error: str) -> None:
    _write_report(ctx.report_path, _build_report(ctx, status="FAIL", errors=[error], real_valkey=ctx.started))


def _write_blocked_report(ctx: CaptureContext, error: str) -> None:
    ctx.started_trial_ids.clear()
    ctx.trials.clear()
    ctx.pairs.clear()
    ctx.cells.clear()
    ctx.invalid_samples.clear()
    _write_report(ctx.report_path, _build_report(ctx, status="BLOCKED", errors=[error], real_valkey=False))


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CaptureError(f"expected JSON object at {path}")
    return value


def _product_digest() -> str:
    from valkey_scale_lab.gates.real import product_tree_digest

    return str(product_tree_digest(ROOT))


def _product_version() -> str:
    from valkey_scale_lab import __version__

    return str(__version__)


def _environment_facts() -> dict[str, Any]:
    docker = _run_command(["docker", "version", "--format", "{{json .}}"], env=_base_environment(), timeout=30)
    if docker["returncode"] != 0 or not docker["stdout"].strip():
        raise EnvironmentBlocked("Docker server identity is unavailable")
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "docker": docker["stdout"].strip(),
    }


def _report_digest(report: dict[str, Any]) -> str:
    payload = dict(report)
    payload.pop("report_digest", None)
    return _digest(payload)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _unique_refs(refs: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for ref in refs:
        key = (ref["category"], ref["path"], ref["sha256"])
        if key not in seen:
            result.append(ref)
            seen.add(key)
    return result


__all__ = ["capture_current_invocation"]
