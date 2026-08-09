from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from valkey_scale_lab.observability.contracts import CollectionError
from valkey_scale_lab.runtime import docker_runtime


_ONE_NODE = {
    "logical_id": "node-0000",
    "host": "127.0.0.1",
    "client_port": 7000,
    "role": "primary",
    "shard_id": "shard-0000",
    # The load lane runs memtier inside the node's own nodehost container,
    # where the cluster's advertised addresses resolve.
    "container_name": "vslab-review-o3-nodehost-az-a-00",
}


def _install_management_fakes(monkeypatch) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Everything the management sequence needs that is not the stability lane.

    Returns the two lists the caller may want to inspect: the options each
    `FullClusterValidator` was run with, and the options each `StabilityWindow`
    was constructed with.
    """

    monkeypatch.setattr(
        docker_runtime,
        "MANAGEMENT_MATRIX_EXECUTION_ROWS",
        ["add_node", "reshard_slot_range", "rolling_restart_replica_first"],
    )
    monkeypatch.setattr(
        docker_runtime,
        "_management_topology_snapshot",
        lambda *args, **kwargs: {"snapshot_id": kwargs.get("label", "snapshot")},
    )

    def run_operation(**kwargs: Any):
        command_log = kwargs["command_log"]
        operation_id = kwargs["operation_id"]
        command_log.append(
            {
                "command_id": f"{operation_id}-cmd",
                "operation_id": operation_id,
                "status": "PASS",
            }
        )
        return {"operation_status": "PASS"}, [], [], [], [], {}

    monkeypatch.setattr(
        docker_runtime, "_management_matrix_run_operation_with_workload", run_operation
    )
    validation_options: list[dict[str, Any]] = []
    stability_windows: list[dict[str, Any]] = []

    class FakeValidator:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def run(self, **options: Any) -> dict[str, Any]:
            validation_options.append(options)
            return {
                "status": "OK",
                "light_validation": {"nodes": [], "primary_count": 25},
                "topology_validation": {"status": "OK"},
            }

    class FakeSentinel:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

    class FakeLoad:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

    monkeypatch.setattr(docker_runtime, "FullClusterValidator", FakeValidator)
    monkeypatch.setattr(docker_runtime, "build_sentinel_nodes", lambda *_a, **_k: [])
    monkeypatch.setattr(docker_runtime, "SentinelLane", FakeSentinel)
    monkeypatch.setattr(docker_runtime, "MemtierLoadLane", FakeLoad)
    return validation_options, stability_windows


def test_local_full_flow_resource_runners_are_nodehost_local_agents() -> None:
    runners = docker_runtime._resource_runners_for_nodes(
        backend=docker_runtime.DockerNodeBackend(),
        nodes=[
            {
                "logical_id": "node-a",
                "nodehost_id": "nodehost-a",
                "nodehost_container_id": "container-a",
                "pid": 101,
            },
            {
                "logical_id": "node-b",
                "nodehost_id": "nodehost-a",
                "nodehost_container_id": "container-a",
                "pid": 102,
            },
        ],
    )

    # One long-lived sampler per nodehost, running on the nodehost itself, so
    # it reads that nodehost's own procfs rather than another machine's.
    assert len(runners) == 1
    assert isinstance(runners[0], docker_runtime.NodehostResourceAgent)
    assert runners[0].container == "container-a"
    assert runners[0].sampler.sampler_id == "nodehost-a"
    assert [process.logical_id for process in runners[0].sampler.processes] == [
        "node-a",
        "node-b",
    ]


def test_local_full_flow_bounded_stability_uses_two_60_second_scalable_rounds(
    monkeypatch, tmp_path: Path
) -> None:
    validation_options, stability_windows = _install_management_fakes(monkeypatch)

    class FakeWindow:
        def __init__(self, *_args: Any, **kwargs: Any) -> None:
            stability_windows.append(dict(kwargs.get("validation_options") or {}))

        def run(self) -> dict[str, Any]:
            return {
                "status": "PASS",
                "duration_seconds": 120,
                "rounds": [
                    {"round": 1, "light": {"status": "OK"}, "sentinel": {"status": "OK"}},
                    {"round": 2, "light": {"status": "OK"}, "sentinel": {"status": "OK"}},
                ],
            }

    monkeypatch.setattr(docker_runtime, "StabilityWindow", FakeWindow)

    command_log: list[dict[str, Any]] = []
    result = docker_runtime._local_full_flow_run_management_sequence(
        capability_id="LOCAL_FULL_FLOW",
        scenario="review",
        run_id="review-o3",
        scale=50,
        nodes=[_ONE_NODE],
        command_log=command_log,
        artifacts=tmp_path,
        backend=docker_runtime.DockerNodeBackend(),
    )

    stability = [
        row for row in command_log if row.get("scenario_id") == "bounded_stability"
    ]
    # Management operations have already moved roles by this point, so the
    # bounded-stability validation must not assert the original role plan.
    # Every other invariant stays on: nothing else is relaxed.
    assert validation_options == [{"require_plan_roles": False}]
    # The window's own boundary and per-round probes observe under the same
    # contract as the validation that precedes them.
    assert stability_windows == [{"require_plan_roles": False}]
    assert len(stability) == 1
    assert result["summary"]["stability"]["duration_ms"] > 0
    assert result["summary"]["stability"]["health_criteria"] == {
        "all_node_light_validation": "OK",
        "sentinel_all_node_sweep": "OK",
        "load_lane": "OK",
    }
    assert result["summary"]["stability"]["sample_count"] == 2
    assert result["summary"]["stability"]["sample_interval_ms"] == 60_000


@pytest.mark.parametrize(
    ("window_status", "expected"),
    [("ERROR", CollectionError), ("FAIL", docker_runtime.DockerRuntimeError)],
)
def test_bounded_stability_raises_a_tool_error_apart_from_a_cluster_failure(
    monkeypatch, tmp_path: Path, window_status: str, expected: type[Exception]
) -> None:
    """The lane's own §12.2 verdict decides which failure the run reports.

    `final_verdict` separates a check that could not complete from a check that
    observed something wrong, and this is the only place in a real run where that
    distinction exists. Raising both as the same class is what made the verdict
    unreachable: the run said the cluster failed when the collector had broken.
    """

    _install_management_fakes(monkeypatch)
    tool_errors = ["resource_analysis:nodehost-az-a-99"]

    class FakeWindow:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def run(self) -> dict[str, Any]:
            return {
                "status": window_status,
                "duration_seconds": 120,
                "rounds": [],
                "tool_errors": tool_errors if window_status == "ERROR" else [],
            }

    monkeypatch.setattr(docker_runtime, "StabilityWindow", FakeWindow)

    with pytest.raises(expected) as excinfo:
        docker_runtime._local_full_flow_run_management_sequence(
            capability_id="LOCAL_FULL_FLOW",
            scenario="review",
            run_id="review-verdict",
            scale=50,
            nodes=[_ONE_NODE],
            command_log=[],
            artifacts=tmp_path,
            backend=docker_runtime.DockerNodeBackend(),
        )

    if window_status == "ERROR":
        # The tool errors §12.2 lists separately are what the message has to
        # carry, because the observation artifact does not outlive the raise.
        assert "could not complete" in str(excinfo.value)
        assert tool_errors[0] in str(excinfo.value)
    else:
        assert "failed" in str(excinfo.value)
    # A tool error is never also a cluster failure, and a cluster failure is
    # never reported as a tool error. `CollectionError` is a `RuntimeError`, so
    # asserting the class alone would not prove the second half.
    assert isinstance(excinfo.value, expected)
    assert (excinfo.type is CollectionError) == (window_status == "ERROR")
