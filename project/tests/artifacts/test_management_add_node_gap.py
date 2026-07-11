from __future__ import annotations

from valkey_scale_lab.metrics import TelemetryRun
from valkey_scale_lab.runtime import docker_runtime


def test_strict_add_replica_executes_a_live_management_mutation(monkeypatch) -> None:
    nodes = [{"logical_id": "primary"}, {"logical_id": "replica"}]
    health = {
        "cluster_state": "ok",
        "known_nodes": 2,
        "slots_assigned": 16384,
        "slots_ok": 16384,
        "slots_fail": 0,
        "primary_count": 1,
        "replica_count": 1,
    }
    monkeypatch.setattr(docker_runtime, "_p17_cluster_health", lambda _nodes: dict(health))
    monkeypatch.setattr(docker_runtime, "_p17_topology_snapshot", lambda *args, **kwargs: {"snapshot_id": "snapshot"})
    monkeypatch.setattr(docker_runtime, "_p30_slot_balance", lambda _nodes: {"status": "PASS"})
    monkeypatch.setattr(docker_runtime, "_p17_wait_clean_cluster", lambda _nodes, timeout: None)

    command_log: list[dict] = []
    delegated_operations: list[str] = []

    def fake_remove_and_restore(telemetry, phase, run_id, operation_name, operation_id, nodes, commands):
        delegated_operations.append(operation_name)
        commands.append({"operation_id": operation_id, "command_id": "live-add", "status": "PASS"})
        return {"operation_status": "PASS", "missing_fields": []}

    monkeypatch.setattr(docker_runtime, "_p30_remove_and_restore_row", fake_remove_and_restore)
    telemetry = TelemetryRun(
        phase_id="P30_MANAGEMENT_MATRIX_50_REAL",
        scenario_name="strict_management_matrix_50",
        run_id="gap-review",
        coverage_id="50.management.add_replica",
        scale=2,
        node_count=2,
    )
    result, _ = docker_runtime._p30_execute_operation(
        telemetry=telemetry,
        phase="P30_MANAGEMENT_MATRIX_50_REAL",
        run_id="gap-review",
        scenario="strict_management_matrix_50",
        operation_name="add_replica",
        operation_id="p30-add_replica-2",
        nodes=nodes,
        command_log=command_log,
    )

    assert command_log, "add_replica was accepted from pre-existing setup state without executing a management command"
    assert result["command_count"] > 0
    assert delegated_operations == ["remove_replica"]
    assert result["management_mutation"] == "replica_removed_then_added_back"
