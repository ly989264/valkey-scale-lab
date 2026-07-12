from __future__ import annotations

import time
from typing import Any

from valkey_scale_lab.metrics import TelemetryRun
from valkey_scale_lab.runtime import docker_runtime


def test_expected_event_window_errors_are_measured_without_failing_recovered_operation(monkeypatch) -> None:
    operation_active = False

    monkeypatch.setattr(docker_runtime, "_p17_topology_snapshot", lambda *args, **kwargs: {})

    def execute_operation(**kwargs: Any):
        nonlocal operation_active
        operation_active = True
        time.sleep(0.03)
        operation_active = False
        return {"operation_status": "PASS", "real_execution_verified": True}, {}

    def workload(*args: Any, **kwargs: Any) -> str:
        if operation_active:
            raise ConnectionError("measured client interruption")
        return "OK" if args[1] == "SET" else "value"

    monkeypatch.setattr(docker_runtime, "_p30_execute_operation", execute_operation)
    monkeypatch.setattr(docker_runtime, "run_node_cluster_cli", workload)
    telemetry = TelemetryRun(
        phase_id=docker_runtime.P36_STAGE,
        scenario_name=docker_runtime.P36_SCENARIO_50,
        run_id="workload-impact-status",
        coverage_id="50.management.rolling_restart",
        scale=50,
        node_count=50,
    )

    result, _events, _metrics, windows, _topology, _extras = docker_runtime._p30_run_operation_with_workload(
        telemetry=telemetry,
        phase=docker_runtime.P36_STAGE,
        run_id="workload-impact-status",
        scenario=docker_runtime.P36_SCENARIO_50,
        operation_name="rolling_restart_replica_first",
        operation_id="rolling-restart-impact",
        nodes=[{"logical_id": "node-0000"}],
        command_log=[],
    )

    event = next(window for window in windows if window["window_name"] == "event")
    assert event["metrics"]["error_ops"] > 0
    assert event["status"] == "PASS"
    assert result["operation_status"] == "PASS"
    assert result["workload_impact"]["errors_observed_during_operation"] is True
