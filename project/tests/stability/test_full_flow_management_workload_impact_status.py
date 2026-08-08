from __future__ import annotations

import time
from typing import Any

from valkey_scale_lab.metrics import TelemetryRun
from valkey_scale_lab.runtime import docker_runtime


def test_expected_event_window_errors_are_measured_without_failing_recovered_operation(monkeypatch) -> None:
    operation_active = False

    monkeypatch.setattr(docker_runtime, "_management_topology_snapshot", lambda *args, **kwargs: {})

    def execute_operation(**kwargs: Any):
        nonlocal operation_active
        operation_active = True
        time.sleep(0.03)
        operation_active = False
        return {"operation_status": "PASS", "real_execution_verified": True}, {}

    class Backend:
        def run_cluster_admin(self, node, argv, **_kwargs: Any) -> str:
            if operation_active:
                raise ConnectionError("measured client interruption")
            return "OK" if "SET" in argv else "value"

    monkeypatch.setattr(docker_runtime, "_management_matrix_execute_operation", execute_operation)
    telemetry = TelemetryRun(
        capability_id=docker_runtime.LOCAL_FULL_FLOW_CAPABILITY,
        scenario_name=docker_runtime.LOCAL_FULL_FLOW_SCENARIO,
        run_id="workload-impact-status",
        coverage_id="50.management.rolling_restart",
        scale=50,
        node_count=50,
    )

    result, _events, _metrics, windows, _topology, _extras = docker_runtime._management_matrix_run_operation_with_workload(
        telemetry=telemetry,
        capability_id=docker_runtime.LOCAL_FULL_FLOW_CAPABILITY,
        run_id="workload-impact-status",
        scenario=docker_runtime.LOCAL_FULL_FLOW_SCENARIO,
        operation_name="rolling_restart_replica_first",
        operation_id="rolling-restart-impact",
        nodes=[{"logical_id": "node-0000", "client_port": 7000}],
        command_log=[],
        backend=Backend(),
    )

    event = next(window for window in windows if window["window_name"] == "event")
    assert event["metrics"]["error_ops"] > 0
    assert event["status"] == "PASS"
    assert result["operation_status"] == "PASS"
    assert result["workload_impact"]["errors_observed_during_operation"] is True
