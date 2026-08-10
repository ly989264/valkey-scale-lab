"""The run lifecycle, above any particular runtime.

This is the sequencing a full-flow run performs - preflight, runtime start,
cluster formation, the stability window, the management and fault matrices,
analysis, reporting - and the selection of which backend performs it. It names no
Docker primitive: every runtime operation goes through `NodeBackend`, and which
backend to use comes from `runtime/backends.py`.

It lived in `docker_runtime.py` until 2026-08-09, which is what made a second
backend impossible to write without living in the Docker module or duplicating
it. Moving it here is the last piece of the refactor whose stated goal was to
make M3 possible.

The dependency still points at `docker_runtime` for the helpers this sequencing
calls - artifact writers, cluster formation, the management and fault matrices.
Measured at the time of the move: 34 module-level helpers, of which 33 contain no
direct Docker reference. Those are backend-neutral and belong here eventually;
moving them is a separate slice with its own evidence, and doing it in the same
change would have made a behaviour-preserving move unverifiable. What matters for
M3 is already true: the sequencing and the selection are out of the Docker module,
and a second backend is a registry entry plus a `NodeBackend`.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from valkey_scale_lab.execution import validate_execution_selection
from valkey_scale_lab.runtime.backends import (
    BackendNotImplementedError,
    require_implemented,
)
from valkey_scale_lab.runtime.node_backend import NodeBackend
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline, shared_monotonic

from valkey_scale_lab.runtime import docker_runtime as _runtime


def execute_scenario(
    *,
    capability_id: str,
    scenario_id: str,
    backend_id: str,
    profile_id: str,
    requested_nodes: int,
    config_path: str | Path,
    artifacts_dir: str | Path,
    state_out: str | Path,
    setup_timeline: SetupTimeline | None = None,
    global_config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
    operator_opt_in: bool = False,
    cost_acknowledged: bool = False,
) -> dict[str, Any]:
    """Execute one canonical scenario using an explicit backend and profile."""
    try:
        backend, profile = validate_execution_selection(
            scenario_id=scenario_id,
            backend_id=backend_id,
            profile_id=profile_id,
            requested_nodes=requested_nodes,
        )
    except ValueError as exc:
        raise _runtime.DockerRuntimeError(str(exc)) from exc
    expected_capability = _runtime.SCENARIO_CAPABILITIES[scenario_id]
    if capability_id != expected_capability:
        raise _runtime.DockerRuntimeError(
            "scenario capability mismatch: "
            f"scenario={scenario_id}, expected={expected_capability}, got={capability_id}"
        )
    if backend.backend_id == "fake":
        return _runtime._execute_fake_scenario(
            capability_id=capability_id,
            scenario_id=scenario_id,
            profile_id=profile.profile_id,
            requested_nodes=requested_nodes,
            artifacts_dir=artifacts_dir,
            state_out=state_out,
        )
    # What each backend implements is data in `runtime/backends.py`, not a chain
    # here. `native_multi_ecs` is absent from that registry rather than rejected
    # in this module, which is what let a second backend be written without
    # living in it.
    try:
        require_implemented(
            backend.backend_id,
            profile_id=profile.profile_id,
            scenario_id=scenario_id,
        )
    except BackendNotImplementedError as exc:
        raise _runtime.DockerRuntimeError(str(exc)) from exc

    state = _runtime._execute_runtime(
        capability_id=capability_id,
        scenario=scenario_id,
        backend_id=backend.backend_id,
        profile_id=profile.profile_id,
        requested_nodes=requested_nodes,
        config_path=config_path,
        artifacts_dir=artifacts_dir,
        state_out=state_out,
        setup_timeline=setup_timeline,
        global_config_path=global_config_path,
        cli_overrides=cli_overrides,
        operator_opt_in=operator_opt_in,
        cost_acknowledged=cost_acknowledged,
    )
    state["scenario_id"] = scenario_id
    state["backend_id"] = backend_id
    state["profile_id"] = profile_id
    Path(state_out).write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return state



def _create_process_scenario(
    *,
    backend: NodeBackend,
    backend_id: str,
    capability_id: str,
    scenario: str,
    run_id: str,
    config: dict[str, Any],
    artifacts: Path,
    state_out: Path,
    nodes: list[dict[str, Any]],
    profile_id: str,
    setup_timeline: SetupTimeline | None = None,
    image_preflight: dict[str, Any] | None = None,
    operator_opt_in: bool = False,
    cost_acknowledged: bool = False,
) -> dict[str, Any]:
    network_name = _runtime._network_name(capability_id, scenario)
    management_profile = _runtime._management_matrix_profile(capability_id, scenario, len(nodes))
    full_flow_profile = _runtime._full_flow_profile(capability_id, scenario, len(nodes))
    for selected in (management_profile, full_flow_profile):
        if selected is not None and selected.profile_id != profile_id:
            raise _runtime.DockerRuntimeError(
                f"profile {profile_id!r} does not match configured node count {len(nodes)}"
            )
    if management_profile:
        preflight = _runtime.run_resource_preflight(
            management_profile.config_template,
            artifacts / "resource_preflight.json",
            capability_id=capability_id,
            scenario=scenario,
            profile_id=profile_id,
        )
        if preflight.get("can_run") is not True:
            _runtime._write_management_blocked_artifact(
                artifacts, preflight, management_profile, capability_id
            )
            raise _runtime.DockerRuntimeError(
                f"{capability_id} resource preflight cannot support exactly "
                f"{management_profile.requested_nodes} nodes; execution is blocked"
            )
    if full_flow_profile:
        with _runtime._timeline_span(setup_timeline, "resource_preflight", "resource_preflight", {"node_count": full_flow_profile.requested_nodes}):
            preflight = _runtime.run_resource_preflight(
                full_flow_profile.config_template,
                artifacts / "resource_preflight.json",
                capability_id=capability_id,
                scenario=scenario,
                profile_id=profile_id,
                operator_opt_in=operator_opt_in,
                cost_acknowledged=cost_acknowledged,
            )
        if preflight.get("can_run") is not True:
            _runtime._write_full_flow_blocked_artifact(
                artifacts, preflight, full_flow_profile, capability_id, scenario
            )
            raise _runtime.DockerRuntimeError(
                "LOCAL_FULL_FLOW resource preflight cannot support exactly "
                f"{full_flow_profile.requested_nodes} nodes; execution is blocked"
            )
    with _runtime._timeline_span(setup_timeline, "pre_cleanup_by_label", "docker_cleanup", {"run_id": run_id}):
        backend.reclaim_run(capability_id=capability_id, run_id=run_id)
    with _runtime._timeline_span(setup_timeline, "docker_network_create", "docker_network", {"network_name": network_name}):
        backend.create_network(network_name=network_name, capability_id=capability_id, run_id=run_id)
    with _runtime._timeline_span(setup_timeline, "nodehost_plan", "planning", {"node_count": len(nodes)}):
        nodehosts = _runtime._process_nodehosts(
            config, nodes, capability_id, scenario, run_id, backend_id=backend_id
        )
        _runtime._write_nodehost_density_plan_artifact(
            artifacts / "nodehost_density_plan.json",
            config,
            nodes,
            nodehosts,
            run_id,
            backend_id=backend_id,
        )
    snapshots: list[dict[str, Any]] = []
    timings: dict[str, dict[str, Any]] = {}
    try:
        def start_nodehost(nodehost: dict[str, Any]) -> None:
            started = backend.start_nodehost(
                nodehost,
                network_name=network_name,
                image=config["runtime"]["valkey_image"],
                capability_id=capability_id,
                scenario=scenario,
                run_id=run_id,
            )
            # The artifact contract names these container_id and container_ip.
            nodehost["container_id"] = started.handle
            nodehost["container_ip"] = started.address
            # Which scope this nodehost was started into. The fault lane
            # isolates a host from it and puts it back at the address above,
            # and both are the backend's to know rather than a stage's to
            # thread through - the same way the peer address became inventory
            # in Slice 1 instead of a second call.
            nodehost["network_name"] = network_name

        _runtime._run_timed_step(
            timings,
            "nodehost_start",
            lambda: _runtime._timeline_call(
                setup_timeline,
                "nodehost_start",
                "nodehost_start",
                lambda: _runtime._bounded_parallel(
                    nodehosts,
                    start_nodehost,
                    parallelism=_runtime.CLUSTER_ORCHESTRATION_PARALLELISM,
                    timeout=_runtime._scale_timeout(nodes, floor=120.0, per_node=2.0),
                    label="nodehost container startup",
                ),
                {"nodehost_count": len(nodehosts), "parallelism": _runtime.CLUSTER_ORCHESTRATION_PARALLELISM},
            ),
            {"nodehost_count": len(nodehosts), "parallelism": _runtime.CLUSTER_ORCHESTRATION_PARALLELISM},
        )
        nodehost_by_id = {nodehost["nodehost_id"]: nodehost for nodehost in nodehosts}

        config_prepare_details: dict[str, Any] = {}
        _runtime._run_timed_step(
            timings,
            "process_config_prepare",
            lambda: config_prepare_details.update(
                _runtime._prepare_process_nodehost_bundles(
                    backend=backend,
                    nodes=nodes,
                    nodehosts=nodehosts,
                    nodehost_by_id=nodehost_by_id,
                    artifacts=artifacts,
                    run_id=run_id,
                    setup_timeline=setup_timeline,
                )
            ),
            config_prepare_details,
        )
        _runtime._write_generated_valkey_configs_manifest(artifacts / "generated_valkey_configs_manifest.json", capability_id, scenario, run_id, nodes)

        process_start_details: dict[str, Any] = {}
        _runtime._run_timed_step(
            timings,
            "process_start",
            lambda: process_start_details.update(
                _runtime._start_process_nodes_batched(
                    backend=backend,
                    nodes=nodes,
                    nodehosts=nodehosts,
                    setup_timeline=setup_timeline,
                )
            ),
            process_start_details,
        )
        bootstrap_batching = _runtime._process_bootstrap_batching_details(
            nodes=nodes,
            nodehosts=nodehosts,
            config_prepare_details=config_prepare_details,
            process_start_details=process_start_details,
        )
        for timing_name in ["process_config_prepare", "process_start"]:
            timings.setdefault(timing_name, {}).setdefault("details", {})["process_bootstrap_batching"] = bootstrap_batching
        _runtime._run_timed_step(
            timings,
            "process_ready_wait",
            lambda: _runtime._timeline_call(
                setup_timeline,
                "process_ready_wait",
                "process_ready_wait",
                lambda: backend.wait_nodes_ready(nodes, timeout=_runtime._scale_timeout(nodes, floor=60.0, per_node=2.0)),
                {"node_count": len(nodes)},
            ),
            {"node_count": len(nodes)},
        )
        _runtime._m2_setup_event(
            setup_timeline,
            "last_process_ping",
            {"node_count": len(nodes), "observation": "all owned processes answered PING"},
        )
        state = _runtime._process_runtime_state(
            capability_id,
            scenario,
            run_id,
            network_name,
            config,
            nodehosts,
            nodes,
            snapshots,
            profile_id=profile_id,
            backend_id=backend_id,
        )
        state["runtime"]["process_bootstrap_batching"] = bootstrap_batching
        if image_preflight is not None:
            state["runtime"]["valkey_image_preflight"] = image_preflight
        _runtime._write_effective_server_profile_artifact(artifacts / "effective_server_profile.json", capability_id, scenario, run_id, state)
        _runtime._write_effective_cluster_timeout_artifact(artifacts / "effective_cluster_timeout.json", capability_id, scenario, run_id, state)
        with _runtime._timeline_span(setup_timeline, "state_write_before_cluster", "state_write", {"path": state_out.as_posix()}):
            _runtime._write_state(state_out, state)
        resource_seconds = _runtime._m2_bootstrap_resource_seconds()
        if resource_seconds is None:
            operations, snapshots = _runtime._configure_process_cluster(nodes, timings=timings, setup_timeline=setup_timeline, backend=backend)
        else:
            first_resource_sample = threading.Event()
            with ThreadPoolExecutor(max_workers=1) as executor:
                resource_future = executor.submit(
                    _runtime.write_resource_observation,
                    artifacts / "resource_observation.json",
                    capability_id=capability_id,
                    scenario_name=scenario,
                    run_id=run_id,
                    runners=_runtime._resource_runners_for_nodes(nodes, backend=backend),
                    duration_seconds=resource_seconds,
                    first_complete_sample_event=first_resource_sample,
                    monotonic=shared_monotonic,
                )
                if not first_resource_sample.wait(timeout=60.0):
                    if resource_future.done():
                        resource_future.result()
                    raise _runtime.DockerRuntimeError(
                        "bootstrap resource observation did not capture every owned process before cluster formation"
                    )
                protocol_start = _runtime._m2_bootstrap_protocol_boundary(nodes, "start")
                operations, snapshots = _runtime._configure_process_cluster(nodes, timings=timings, setup_timeline=setup_timeline, backend=backend)
                resource_report = resource_future.result()
                protocol_end = _runtime._m2_bootstrap_protocol_boundary(nodes, "end")
                resource_report["m2_bootstrap_protocol_boundaries"] = {
                    "start": protocol_start,
                    "end": protocol_end,
                }
                _runtime._write_json_artifact(artifacts / "resource_observation.json", resource_report)
            if resource_report.get("status") != "PASS":
                raise _runtime.DockerRuntimeError("bootstrap resource observation is incomplete")
        snapshots_path = artifacts / f"cluster_snapshots_{scenario}.json"
        with _runtime._timeline_span(setup_timeline, "cluster_snapshot_write", "artifact_write", {"path": snapshots_path.as_posix()}):
            snapshots_path.write_text(json.dumps(snapshots, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        state = _runtime._process_runtime_state(
            capability_id,
            scenario,
            run_id,
            network_name,
            config,
            nodehosts,
            nodes,
            snapshots,
            profile_id=profile_id,
            backend_id=backend_id,
        )
        state["runtime"]["process_bootstrap_batching"] = bootstrap_batching
        if image_preflight is not None:
            state["runtime"]["valkey_image_preflight"] = image_preflight
        state["runtime"]["cluster_snapshot_path"] = snapshots_path.as_posix()
        state["runtime"]["operations"] = operations
        timing_path = artifacts / f"runtime_timing_breakdown_{scenario}.json"
        with _runtime._timeline_span(setup_timeline, "runtime_timing_write", "artifact_write", {"path": timing_path.as_posix()}):
            _runtime._write_runtime_timing_breakdown(
                timing_path,
                capability_id,
                scenario,
                profile_id,
                run_id,
                nodes,
                timings,
                status="PASS",
            )
        state["runtime"]["timing_breakdown_path"] = timing_path.as_posix()
        state["runtime"]["timings"] = _runtime._timing_entries(timings)
        _runtime._write_effective_server_profile_artifact(artifacts / "effective_server_profile.json", capability_id, scenario, run_id, state)
        _runtime._write_effective_cluster_timeout_artifact(artifacts / "effective_cluster_timeout.json", capability_id, scenario, run_id, state)
        with _runtime._timeline_span(setup_timeline, "state_write_after_cluster", "state_write", {"path": state_out.as_posix()}):
            _runtime._write_state(state_out, state)
        if full_flow_profile:
            with _runtime._timeline_span(setup_timeline, "stabilize", "stabilize", {"node_count": len(nodes)}):
                _runtime._management_wait_clean_cluster(nodes, timeout=_runtime._scale_timeout(nodes, floor=60.0, per_node=2.0))
            if image_preflight is None:
                raise _runtime.DockerRuntimeError("LOCAL_FULL_FLOW requires a verified custom Valkey image")
            myslots_path = artifacts / "cluster_myslots_report.json"
            with _runtime._timeline_span(setup_timeline, "cluster_myslots", "artifact_validation", {"node_count": len(nodes)}):
                _runtime._write_cluster_myslots_report(
                    myslots_path,
                    capability_id=capability_id,
                    scenario=scenario,
                    run_id=run_id,
                    nodes=nodes,
                    image_preflight=image_preflight,
                )
            state["runtime"]["cluster_myslots_report_path"] = myslots_path.as_posix()
            _runtime._write_state(state_out, state)
        if management_profile:
            _runtime.write_management_matrix_artifacts(
                artifacts=artifacts,
                capability_id=capability_id,
                scenario=scenario,
                run_id=run_id,
                config=config,
                nodes=nodes,
                nodehosts=nodehosts,
                state=state,
                backend=backend,
            )
        if full_flow_profile:
            _runtime.write_full_flow_artifacts(
                artifacts=artifacts,
                capability_id=capability_id,
                scenario=scenario,
                run_id=run_id,
                config=config,
                nodes=nodes,
                nodehosts=nodehosts,
                state=state,
                backend=backend,
                setup_timeline=setup_timeline,
                operator_opt_in=operator_opt_in,
                cost_acknowledged=cost_acknowledged,
            )
        if scenario == "scale_ladder" and not management_profile and not full_flow_profile:
            with _runtime._timeline_span(setup_timeline, "scale_ladder_artifact_write", "artifact_write", {"artifacts_dir": artifacts.as_posix()}):
                _runtime.write_scale_ladder_artifacts(artifacts, capability_id, scenario, run_id, config, nodes)
        return state
    except Exception:
        backend.reclaim_run(capability_id=capability_id, run_id=run_id)
        raise


