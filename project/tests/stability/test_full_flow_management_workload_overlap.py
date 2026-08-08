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
        "_management_topology_snapshot",
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

    monkeypatch.setattr(docker_runtime, "_management_matrix_execute_operation", execute_operation)

    class Backend:
        """The workload reaches the cluster only through the seam now, so the
        probe that proves the overlap sits on the backend's own method."""

        def run_cluster_admin(self, node, argv, **_kwargs: Any) -> str:
            nonlocal workload_overlapped_operation
            workload_overlapped_operation |= operation_active
            return "OK" if "SET" in argv else "value"

    telemetry = TelemetryRun(
        capability_id="LOCAL_FULL_FLOW_LOCAL_FULL_FLOW",
        scenario_name="full_flow_50",
        run_id="review-o3-round2",
        coverage_id="50.management.reshard_slot_range",
        scale=50,
        node_count=50,
    )
    docker_runtime._management_matrix_run_operation_with_workload(
        telemetry=telemetry,
        capability_id="LOCAL_FULL_FLOW_LOCAL_FULL_FLOW",
        run_id="review-o3-round2",
        scenario="full_flow_50",
        operation_name="reshard_slot_range",
        operation_id="review-reshard",
        nodes=[{"logical_id": "node-0000", "client_port": 7000}],
        command_log=[],
        backend=Backend(),
    )

    assert workload_overlapped_operation, (
        "the event workload only ran before and after the management operation, "
        "so it cannot observe client errors or latency while the operation is active"
    )
