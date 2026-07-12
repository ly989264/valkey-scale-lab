from __future__ import annotations

from valkey_scale_lab.runtime import docker_runtime


def test_p36_fault_probe_records_retry_timeout_and_error_telemetry() -> None:
    command_log: list[dict] = []

    docker_runtime._p36_execute_fault_probe(
        run_id="review-o2-command-diagnostics",
        scale=50,
        scenario_id="network_delay",
        action=lambda: {"actions": ["bounded project-owned network delay probe"]},
        command_log=command_log,
        events=[],
        metrics=[],
        windows=[],
    )

    assert len(command_log) == 1
    command = command_log[0]
    assert command["duration_ms"] >= 0
    assert command["retry_index"] == 0
    assert command["attempt_count"] == 1
    assert command["timeout_ms"] > 0
    assert command["error_type"] == ""
