from __future__ import annotations

from typing import Any

from valkey_scale_lab.runtime import docker_runtime


def test_p36_bounded_stability_is_a_repeated_measured_health_soak(monkeypatch) -> None:
    """A single instantaneous CLUSTER INFO probe is not a bounded soak check."""

    monkeypatch.setattr(
        docker_runtime,
        "P30_EXECUTION_ROWS",
        ["add_node", "reshard_slot_range", "rolling_restart_replica_first"],
    )
    monkeypatch.setattr(
        docker_runtime,
        "_p17_topology_snapshot",
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

    monkeypatch.setattr(docker_runtime, "_p30_run_operation_with_workload", run_operation)
    health_samples: list[str] = []

    def cluster_info(*args: Any, **kwargs: Any) -> str:
        if args[1:] == ("PING",):
            return "PONG"
        health_samples.append("sample")
        return (
            "cluster_state:ok\n"
            "cluster_slots_assigned:16384\n"
            "cluster_slots_ok:16384\n"
            "cluster_slots_fail:0\n"
            "cluster_known_nodes:50\n"
        )

    monkeypatch.setattr(docker_runtime, "_node_command", cluster_info)

    command_log: list[dict[str, Any]] = []
    result = docker_runtime._p36_run_management_sequence(
        phase="P36",
        scenario="review",
        run_id="review-o3",
        scale=50,
        nodes=[{"logical_id": "node-0000"}],
        command_log=command_log,
    )

    stability = [
        row for row in command_log if row.get("scenario_id") == "bounded_stability"
    ]
    assert len(health_samples) >= 2, "bounded stability must sample health repeatedly, not once"
    assert len(stability) == len(health_samples)
    assert result["summary"]["stability"]["duration_ms"] > 0
    assert result["summary"]["stability"]["health_criteria"] == {
        "cluster_state": "ok",
        "cluster_slots_assigned": 16384,
        "cluster_slots_ok": 16384,
        "cluster_slots_fail": 0,
        "cluster_known_nodes": 50,
    }
