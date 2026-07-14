from __future__ import annotations

import time
from typing import Any

from valkey_scale_lab.metrics import TelemetryRun
from valkey_scale_lab.runtime import docker_runtime


def test_management_event_window_exercises_workload_during_operation(monkeypatch) -> None:
    """An event window cannot measure impact if all client calls avoid the operation."""

    operation_active = False
    workload_overlapped_operation = False

    monkeypatch.setattr(
        docker_runtime,
        "_p17_topology_snapshot",
        lambda *args, **kwargs: {"snapshot_id": "review-snapshot"},
    )

    def execute_operation(**kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        nonlocal operation_active
        operation_active = True
        time.sleep(0.05)
        operation_active = False
        return {
            "operation_status": "PASS",
            "real_execution_verified": True,
        }, {}

    monkeypatch.setattr(docker_runtime, "_p30_execute_operation", execute_operation)

    def workload_command(*args: Any, **kwargs: Any) -> str:
        nonlocal workload_overlapped_operation
        workload_overlapped_operation |= operation_active
        return "OK" if args[1] == "SET" else "value"

    monkeypatch.setattr(docker_runtime, "run_node_cluster_cli", workload_command)

    telemetry = TelemetryRun(
        phase_id="P36_LOCAL_FULL_FLOW",
        scenario_name="full_flow_50",
        run_id="review-o3-round2",
        coverage_id="50.management.reshard_slot_range",
        scale=50,
        node_count=50,
    )
    docker_runtime._p30_run_operation_with_workload(
        telemetry=telemetry,
        phase="P36_LOCAL_FULL_FLOW",
        run_id="review-o3-round2",
        scenario="full_flow_50",
        operation_name="reshard_slot_range",
        operation_id="review-reshard",
        nodes=[{"logical_id": "node-0000"}],
        command_log=[],
    )

    assert workload_overlapped_operation, (
        "the event workload only ran before and after the management operation, "
        "so it cannot observe client errors or latency while the operation is active"
    )
