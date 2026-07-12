from __future__ import annotations

from typing import Any

import pytest

from valkey_scale_lab.metrics import MISSING, TelemetryRun
from valkey_scale_lab.runtime import docker_runtime


def _nodes(node_count: int) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for shard_index in range(node_count // 2):
        shard_id = f"shard-{shard_index:04d}"
        for role, host_offset in (("primary", 0), ("replica", 4)):
            logical_id = f"{shard_id}-{role}"
            nodes.append(
                {
                    "logical_id": logical_id,
                    "role": role,
                    "shard_id": shard_id,
                    "nodehost_container_name": f"nodehost-{(shard_index + host_offset) % 8}",
                    "container_name": f"container-{logical_id}",
                    "pid": shard_index * 2 + (1 if role == "primary" else 2),
                    "az_id": f"az-{shard_index % 3}",
                }
            )
    return nodes


def _clean_health(node_count: int) -> dict[str, Any]:
    return {
        "cluster_state": "ok",
        "known_nodes": node_count,
        "primary_count": node_count // 2,
        "replica_count": node_count // 2,
        "handshake_count": 0,
        "fail_count": 0,
        "pfail_count": 0,
        "slots_assigned": 16384,
        "slots_ok": 16384,
        "slots_fail": 0,
        "snapshots": [],
    }


def _telemetry(node_count: int) -> TelemetryRun:
    return TelemetryRun(
        phase_id="P36_FULL_FLOW_E2E_50_100_200_REAL",
        scenario_name=f"strict_full_flow_{node_count}",
        run_id=f"rolling-{node_count}",
        coverage_id=f"{node_count}.management.rolling_restart",
        scale=node_count,
        node_count=node_count,
    )


def test_strict_rolling_restart_batches_are_bounded_by_shard_and_nodehost() -> None:
    nodes = _nodes(200)
    topology = {node["logical_id"]: {"role": node["role"]} for node in nodes}
    entries = docker_runtime._p30_rolling_restart_plan_entries(
        "rolling_restart_replica_first", "op", nodes, topology=topology
    )
    batches = docker_runtime._p30_rolling_restart_batches(entries, nodes)

    assert len(batches) < len(nodes)
    assert max(len(batch) for batch in batches) == docker_runtime.ROLLING_RESTART_MAX_PARALLELISM
    assert [entry["planned_role"] for entry in entries[:100]] == ["replica"] * 100
    assert [entry["planned_role"] for entry in entries[100:]] == ["primary"] * 100
    for batch in batches:
        assert len({entry["shard_id"] for entry in batch}) == len(batch)
        assert len({entry["nodehost_container_name"] for entry in batch}) == len(batch)
        assert len({entry["planned_role"] for entry in batch}) == 1


def _run_restart(monkeypatch: pytest.MonkeyPatch, node_count: int, operation_name: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[bool], list[str]]:
    nodes = _nodes(node_count)
    probe_modes: list[bool] = []
    safe_targets: list[str] = []

    monkeypatch.setattr(docker_runtime, "_p17_cluster_health", lambda _nodes: _clean_health(node_count))
    monkeypatch.setattr(
        docker_runtime,
        "_p19_live_topology",
        lambda current: {node["logical_id"]: {"role": node["role"]} for node in current},
    )
    monkeypatch.setattr(
        docker_runtime,
        "_p17_wait_clean_cluster",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("per-node full clean gate must not run")),
    )

    def restart_target(*, entry: dict[str, Any], target: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        return {
            "sequence": entry["sequence"],
            "process_pid_before": target["pid"],
            "process_pid_after": target["pid"] + 1000,
            "restart_started_at_ms": entry["sequence"] * 10,
            "restart_completed_at_ms": entry["sequence"] * 10 + 5,
            "restart_wall_ms": 5.0,
            "command_rows": [],
        }

    def wait_health(
        _nodes: list[dict[str, Any]],
        *,
        timeout: float,
        full_probe: bool,
        required_nodes: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        del timeout
        probe_modes.append(full_probe)
        sample_count = node_count if full_probe else max(3, len(required_nodes or []))
        return _clean_health(node_count), {
            "status": "PASS",
            "sample_scope": "all_nodes" if full_probe else "representative_by_az",
            "representative_probe_count": 0 if full_probe else sample_count,
            "full_probe_count": sample_count if full_probe else 0,
            "retry_count": 0,
            "node_command_count": sample_count * 2,
            "wall_ms": 1.0,
            "cluster_state": "ok",
            "known_nodes": node_count,
            "slots_assigned": 16384,
        }

    def make_safe(*, target: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        safe_targets.append(target["logical_id"])
        return {
            "safe_path": "cluster_failover_after_replica_sync_before_owned_process_restart",
            "safe_command_ref": "safe-command",
            "replacement_logical_id": f"{target['shard_id']}-replica",
            "promotion_latency_ms": 1.0,
            "cluster_recovery_latency_ms": 1.0,
            "read_unavailability_ms": MISSING,
            "write_unavailability_ms": MISSING,
            "missing_fields": [],
            "role_before_restart": "replica",
        }

    monkeypatch.setattr(docker_runtime, "_p30_restart_process_target", restart_target)
    monkeypatch.setattr(docker_runtime, "_p30_wait_rolling_restart_health", wait_health)
    monkeypatch.setattr(docker_runtime, "_p30_make_primary_restart_safe", make_safe)
    monkeypatch.setattr(
        docker_runtime,
        "_p30_wait_replica_sync_ready",
        lambda replica, primary, timeout: {"status": "PASS", "wait_ms": 1.0},
    )
    monkeypatch.setattr(
        docker_runtime,
        "_p30_restore_primary_placement",
        lambda **_kwargs: {"restore_command_ref": "restore-command", "placement_restored": True},
    )

    result, plan, rows, _events = docker_runtime._p30_execute_process_rolling_restart(
        telemetry=_telemetry(node_count),
        phase="P36_FULL_FLOW_E2E_50_100_200_REAL",
        run_id=f"rolling-{node_count}",
        operation_name=operation_name,
        operation_id=f"rolling-{operation_name}-{node_count}",
        nodes=nodes,
        command_log=[],
    )
    return result, plan, rows, probe_modes, safe_targets


def test_rolling_restart_uses_batch_gates_and_one_final_full_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    result, plan, rows, probe_modes, _safe_targets = _run_restart(
        monkeypatch, 200, "rolling_restart_replica_first"
    )

    assert result["operation_status"] == "PASS"
    assert result["restart_batch_count"] == len(plan["restart_batches"])
    assert result["max_concurrent_restarts"] == docker_runtime.ROLLING_RESTART_MAX_PARALLELISM
    assert len(rows) == 200
    primary_batches = sum(
        1 for batch in plan["restart_batches"] if plan["restart_order"][batch["sequences"][0] - 1]["planned_role"] == "primary"
    )
    assert probe_modes == [False] * (len(plan["restart_batches"]) + primary_batches) + [True]
    assert result["health_probe_summary"]["full_probe_count"] == 200
    assert result["health_probe_summary"]["node_command_count"] < 2_000


def test_health_probe_telemetry_counts_representative_and_full_node_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = _nodes(200)

    def snapshots(probe_nodes: list[dict[str, Any]], *, timeout: float) -> list[dict[str, Any]]:
        del timeout
        return [
            {
                "logical_id": node["logical_id"],
                "probe_status": "PASS",
                **{key: value for key, value in _clean_health(200).items() if key != "snapshots"},
            }
            for node in probe_nodes
        ]

    monkeypatch.setattr(docker_runtime, "_process_node_snapshots_parallel", snapshots)

    _health, representative = docker_runtime._p30_wait_rolling_restart_health(
        nodes, timeout=10.0, full_probe=False
    )
    _health, full = docker_runtime._p30_wait_rolling_restart_health(
        nodes, timeout=10.0, full_probe=True
    )

    assert representative["representative_probe_count"] == 3
    assert representative["full_probe_count"] == 0
    assert representative["node_command_count"] == 6
    assert full["representative_probe_count"] == 0
    assert full["full_probe_count"] == 200
    assert full["node_command_count"] == 400


def test_rolling_probe_work_scales_linearly_and_primary_handoff_runs_once_per_shard(monkeypatch: pytest.MonkeyPatch) -> None:
    result_50, _plan_50, _rows_50, _probes_50, _safe_50 = _run_restart(
        monkeypatch, 50, "rolling_restart_replica_first"
    )
    result_200, _plan_200, _rows_200, _probes_200, _safe_200 = _run_restart(
        monkeypatch, 200, "rolling_restart_replica_first"
    )
    count_50 = result_50["health_probe_summary"]["node_command_count"]
    count_200 = result_200["health_probe_summary"]["node_command_count"]

    assert count_200 <= count_50 * 4

    _result, plan, rows, _probe_modes, safe_targets = _run_restart(
        monkeypatch, 16, "rolling_restart_primary_safe"
    )
    assert len(safe_targets) == 8
    assert len(set(safe_targets)) == 8
    assert [entry["planned_role"] for entry in plan["restart_order"][:8]] == ["replica"] * 8
    assert len(rows) == 16


def test_rolling_restart_plan_uses_live_roles_instead_of_inventory_roles() -> None:
    nodes = _nodes(6)
    topology = {
        node["logical_id"]: {"role": "primary" if node["role"] == "replica" else "replica"}
        for node in nodes
    }

    entries = docker_runtime._p30_rolling_restart_plan_entries(
        "rolling_restart_primary_safe",
        "op-live-roles",
        nodes,
        topology=topology,
    )

    assert [entry["logical_node_id"] for entry in entries[:3]] == [
        node["logical_id"] for node in nodes if node["role"] == "primary"
    ]
    assert [entry["planned_role"] for entry in entries[:3]] == ["replica"] * 3


def test_primary_safe_handoff_and_restore_verify_both_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = _nodes(6)
    target = next(node for node in nodes if node["role"] == "primary")
    replacement = next(
        node for node in nodes if node["shard_id"] == target["shard_id"] and node["role"] == "replica"
    )
    topology = {node["logical_id"]: {"role": node["role"]} for node in nodes}
    role_waits: list[tuple[str, str]] = []
    commands: list[tuple[str, str]] = []

    def log_command(command_log, *, command_kind: str, target: dict[str, Any], **_kwargs: Any) -> dict[str, str]:
        commands.append((command_kind, target["logical_id"]))
        return {"command_id": f"command-{len(commands)}"}

    monkeypatch.setattr(docker_runtime, "_p17_log_node_command", log_command)
    monkeypatch.setattr(
        docker_runtime,
        "_p17_wait_node_role",
        lambda node, role, timeout: role_waits.append((node["logical_id"], role)),
    )
    monkeypatch.setattr(
        docker_runtime,
        "_p30_wait_replica_sync_ready",
        lambda replica, primary, timeout: {"status": "PASS", "wait_ms": 1.0},
    )

    safe = docker_runtime._p30_make_primary_restart_safe(
        telemetry=_telemetry(6),
        phase="P36_FULL_FLOW_E2E_50_100_200_REAL",
        run_id="rolling-6",
        operation_id="primary-safe",
        target=target,
        nodes=nodes,
        topology=topology,
        command_log=[],
    )
    restored = docker_runtime._p30_restore_primary_placement(
        telemetry=_telemetry(6),
        phase="P36_FULL_FLOW_E2E_50_100_200_REAL",
        run_id="rolling-6",
        operation_id="primary-safe",
        target=target,
        replacement=replacement,
        command_log=[],
    )

    assert safe["replacement_logical_id"] == replacement["logical_id"]
    assert restored["placement_restored"] is True
    assert role_waits == [
        (replacement["logical_id"], "master"),
        (target["logical_id"], "slave"),
        (target["logical_id"], "master"),
        (replacement["logical_id"], "slave"),
    ]


def test_replica_sync_gate_requires_link_sync_and_caught_up_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    primary = {"logical_id": "primary"}
    replica = {"logical_id": "replica"}

    def node_command(node: dict[str, Any], *args: str, timeout: float) -> str:
        del timeout
        if node is primary and args == ("CLUSTER", "MYID"):
            return "primary-id"
        if node is primary and args == ("INFO", "replication"):
            return "master_repl_offset:100\n"
        if node is replica and args == ("INFO", "replication"):
            return "master_link_status:up\nmaster_sync_in_progress:0\nslave_repl_offset:100\n"
        raise AssertionError((node, args))

    monkeypatch.setattr(docker_runtime, "_node_command", node_command)
    monkeypatch.setattr(docker_runtime, "_process_node_is_replica_of", lambda node, master_id: True)

    result = docker_runtime._p30_wait_replica_sync_ready(replica, primary, timeout=1.0)

    assert result["status"] == "PASS"
    assert result["replica_repl_offset"] == result["primary_repl_offset"] == 100


def test_replica_sync_gate_fails_closed_when_topology_is_not_replica(monkeypatch: pytest.MonkeyPatch) -> None:
    primary = {"logical_id": "primary"}
    replica = {"logical_id": "replica"}
    ticks = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(docker_runtime.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(docker_runtime, "_node_command", lambda node, *args, timeout: "primary-id")

    with pytest.raises(docker_runtime.DockerRuntimeError, match="did not catch up"):
        docker_runtime._p30_wait_replica_sync_ready(replica, primary, timeout=1.0)


def test_health_probe_scope_resets_after_diagnostic_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = _nodes(6)
    calls = 0

    def snapshots(probe_nodes: list[dict[str, Any]], *, timeout: float) -> list[dict[str, Any]]:
        nonlocal calls
        del timeout
        calls += 1
        health = _clean_health(6)
        if calls <= 2:
            health["cluster_state"] = "unknown"
        return [
            {"logical_id": node["logical_id"], "probe_status": "PASS", **health}
            for node in probe_nodes
        ]

    monkeypatch.setattr(docker_runtime, "_process_node_snapshots_parallel", snapshots)
    monkeypatch.setattr(docker_runtime.time, "sleep", lambda _seconds: None)

    _health, probe = docker_runtime._p30_wait_rolling_restart_health(
        nodes,
        timeout=1.0,
        full_probe=False,
        required_nodes=[nodes[-1]],
    )

    assert calls == 3
    assert probe["sample_scope"] == "representative_by_az_and_required_nodes"
    assert probe["attempts"][-1]["sample_scope"] == "representative_by_az_and_required_nodes"


def test_topology_placement_signature_detects_master_and_slot_drift() -> None:
    before = {
        "primary": {"node_id": "id-primary", "role": "primary", "master_id": "-", "slots": ["0-100"]},
        "replica": {"node_id": "id-replica", "role": "replica", "master_id": "id-primary", "slots": []},
    }
    wrong_master = {
        **before,
        "replica": {**before["replica"], "master_id": "id-other"},
    }
    wrong_slots = {
        **before,
        "primary": {**before["primary"], "slots": ["0-99"]},
    }

    signature = docker_runtime._p30_topology_placement_signature(before)

    assert signature != docker_runtime._p30_topology_placement_signature(wrong_master)
    assert signature != docker_runtime._p30_topology_placement_signature(wrong_slots)
