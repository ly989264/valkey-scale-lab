from __future__ import annotations

from pathlib import Path
from typing import Any

from valkey_scale_lab.runtime import docker_runtime


def _stat(pid: int, start_time: int) -> str:
    fields = ["0"] * 30
    fields[0] = "S"
    fields[19] = str(start_time)
    fields[21] = "1"
    return f"{pid} (valkey server) " + " ".join(fields)


def test_local_full_flow_resource_runners_use_nodehost_snapshots(monkeypatch) -> None:
    monkeypatch.setattr(
        docker_runtime,
        "_container_pid",
        lambda _container: (_ for _ in ()).throw(
            AssertionError("resource sampling must not use host procfs")
        ),
    )

    runners = docker_runtime._resource_runners_for_nodes(
        [
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
        ]
    )

    assert len(runners) == 1
    assert [process.logical_id for process in runners[0].sampler.processes] == [
        "node-a",
        "node-b",
    ]


def test_exact_200_process_round_exec_count_scales_with_nodehosts(monkeypatch) -> None:
    exec_calls: list[list[str]] = []

    def fake_run_docker(args: list[str], **_kwargs: Any) -> docker_runtime.DockerResult:
        exec_calls.append(args)
        assert args[:3] == ["exec", args[1], "sh"]
        specs = args[6:]
        rows = ["__VSLAB_PROCESS_SNAPSHOT__:v1:4096"]
        for spec in specs:
            logical_id, pid_text = spec.rsplit(":", 1)
            pid = int(pid_text)
            rows.append(
                "\t".join(
                    [
                        "OK",
                        logical_id,
                        pid_text,
                        "3",
                        _stat(pid, pid * 10),
                        _stat(pid, pid * 10),
                    ]
                )
            )
        return docker_runtime.DockerResult("\n".join(rows) + "\n", "", 0)

    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)

    nodes: list[dict[str, Any]] = []
    for index in range(200):
        nodehost = index % 8
        nodes.append(
            {
                "logical_id": f"node-{index:03d}",
                "nodehost_id": f"nodehost-{nodehost}",
                "nodehost_container_id": f"container-{nodehost}",
                "pid": 10_000 + index,
            }
        )

    runners = docker_runtime._resource_runners_for_nodes(nodes)
    for runner in runners:
        runner.sampler.process_sample()

    assert len(runners) == 8
    assert len(exec_calls) == 8
    assert sorted(len(call[6:]) for call in exec_calls) == [25] * 8


def test_local_full_flow_bounded_stability_uses_two_60_second_scalable_rounds(
    monkeypatch, tmp_path: Path
) -> None:

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

    monkeypatch.setattr(docker_runtime, "_management_matrix_run_operation_with_workload", run_operation)
    class FakeValidator:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def run(self) -> dict[str, Any]:
            return {
                "status": "OK",
                "light_validation": {
                    "nodes": [],
                    "primary_count": 25,
                },
                "topology_validation": {"status": "OK"},
            }

    class FakeSentinel:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

    class FakeLoad:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

    class FakeWindow:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def run(self) -> dict[str, Any]:
            return {
                "status": "PASS",
                "duration_seconds": 120,
                "rounds": [
                    {"round": 1, "light": {"status": "OK"}, "sentinel": {"status": "OK"}},
                    {"round": 2, "light": {"status": "OK"}, "sentinel": {"status": "OK"}},
                ],
            }

    monkeypatch.setattr(docker_runtime, "FullClusterValidator", FakeValidator)
    monkeypatch.setattr(docker_runtime, "build_sentinel_nodes", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(docker_runtime, "SentinelLane", FakeSentinel)
    monkeypatch.setattr(docker_runtime, "MemtierLoadLane", FakeLoad)
    monkeypatch.setattr(docker_runtime, "StabilityWindow", FakeWindow)

    command_log: list[dict[str, Any]] = []
    result = docker_runtime._local_full_flow_run_management_sequence(
        capability_id="LOCAL_FULL_FLOW",
        scenario="review",
        run_id="review-o3",
        scale=50,
        nodes=[
            {
                "logical_id": "node-0000",
                "host": "127.0.0.1",
                "client_port": 7000,
                "role": "primary",
                "shard_id": "shard-0000",
            }
        ],
        command_log=command_log,
        artifacts=tmp_path,
    )

    stability = [
        row for row in command_log if row.get("scenario_id") == "bounded_stability"
    ]
    assert len(stability) == 1
    assert result["summary"]["stability"]["duration_ms"] > 0
    assert result["summary"]["stability"]["health_criteria"] == {
        "all_node_light_validation": "OK",
        "sentinel_all_node_sweep": "OK",
        "load_lane": "OK",
    }
    assert result["summary"]["stability"]["sample_count"] == 2
    assert result["summary"]["stability"]["sample_interval_ms"] == 60_000
