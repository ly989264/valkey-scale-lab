from __future__ import annotations

from typing import Any

import pytest

from valkey_scale_lab.metrics import MISSING, TelemetryRun
from valkey_scale_lab.observability.contracts import CollectionError
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


class NoRuntimeBackend:
    """A backend that fails if the stage reaches a runtime at all.

    These tests stub the restart itself, so the only thing left to assert about
    the seam is that nothing under it is touched behind the stub's back.
    """

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"rolling restart must not reach the runtime: {name}")


def _telemetry(node_count: int) -> TelemetryRun:
    return TelemetryRun(
        capability_id="local_full_flow",
        scenario_name="local_full_flow",
        run_id=f"rolling-{node_count}",
        coverage_id=f"{node_count}.management.rolling_restart",
        scale=node_count,
        node_count=node_count,
    )


def test_strict_rolling_restart_batches_are_bounded_by_shard_and_nodehost() -> None:
    nodes = _nodes(200)
    topology = {node["logical_id"]: {"role": node["role"]} for node in nodes}
    entries = docker_runtime._management_matrix_rolling_restart_plan_entries(
        "rolling_restart_replica_first", "op", nodes, topology=topology
    )
    batches = docker_runtime._management_matrix_rolling_restart_batches(entries, nodes)

    assert len(batches) < len(nodes)
    assert max(len(batch) for batch in batches) == docker_runtime.ROLLING_RESTART_MAX_PARALLELISM
    assert [entry["planned_role"] for entry in entries[:100]] == ["replica"] * 100
    assert [entry["planned_role"] for entry in entries[100:]] == ["primary"] * 100
    for batch in batches:
        assert len({entry["shard_id"] for entry in batch}) == len(batch)
        assert len({entry["nodehost_container_name"] for entry in batch}) == len(batch)
        assert len({entry["planned_role"] for entry in batch}) == 1


def _run_restart(
    monkeypatch: pytest.MonkeyPatch,
    node_count: int,
    operation_name: str,
    topology_scopes: list[list[str]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[bool], list[str]]:
    nodes = _nodes(node_count)
    probe_modes: list[bool] = []
    safe_targets: list[str] = []

    def live_topology(
        current: list[dict[str, Any]]
    , **_kwargs) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
        if topology_scopes is not None:
            topology_scopes.append([str(node["logical_id"]) for node in current])
        # Every node answered, so there are no gaps to report.
        return {node["logical_id"]: {"role": node["role"]} for node in current}, {}

    monkeypatch.setattr(docker_runtime, "_management_cluster_health", lambda _nodes, **_kwargs: _clean_health(node_count))
    monkeypatch.setattr(docker_runtime, "_management_live_topology", live_topology)
    monkeypatch.setattr(
        docker_runtime,
        "_management_wait_clean_cluster",
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

    monkeypatch.setattr(docker_runtime, "_management_matrix_restart_process_target", restart_target)
    monkeypatch.setattr(docker_runtime, "_management_matrix_wait_rolling_restart_health", wait_health)
    monkeypatch.setattr(docker_runtime, "_management_matrix_make_primary_restart_safe", make_safe)
    monkeypatch.setattr(
        docker_runtime,
        "_management_matrix_wait_replica_sync_ready",
        lambda replica, primary, timeout: {"status": "PASS", "wait_ms": 1.0},
    )
    monkeypatch.setattr(
        docker_runtime,
        "_management_matrix_restore_primary_placement",
        lambda **_kwargs: {"restore_command_ref": "restore-command", "placement_restored": True},
    )

    result, plan, rows, _events = docker_runtime._management_matrix_execute_process_rolling_restart(
        telemetry=_telemetry(node_count),
        capability_id="local_full_flow",
        run_id=f"rolling-{node_count}",
        operation_name=operation_name,
        operation_id=f"rolling-{operation_name}-{node_count}",
        nodes=nodes,
        command_log=[],
        backend=NoRuntimeBackend(),
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

    _health, representative = docker_runtime._management_matrix_wait_rolling_restart_health(
        nodes, timeout=10.0, full_probe=False
    )
    _health, full = docker_runtime._management_matrix_wait_rolling_restart_health(
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


def test_rolling_restart_batch_topology_is_scoped_to_the_batch_shards(monkeypatch: pytest.MonkeyPatch) -> None:
    """A batch observes its own shards, not the fleet, twice per batch.

    Everything a batch reads from the live topology is shard-scoped, so probing
    all 200 nodes each time bought no evidence and cost 400 host connections a
    batch. The plan and the final verification still see every node.
    """
    scopes: list[list[str]] = []
    _run_restart(monkeypatch, 200, "rolling_restart_replica_first", topology_scopes=scopes)

    assert len(scopes[0]) == 200, "the plan must still read every node's live role"
    assert len(scopes[-1]) == 200, "the final verification must still read every node"

    per_batch = scopes[1:-1]
    assert per_batch, "a 200 node restart runs batches"
    for scope in per_batch:
        shards = {logical_id.rsplit("-", 1)[0] for logical_id in scope}
        # A batch holds at most one node per shard, and a shard has two nodes.
        assert len(shards) <= docker_runtime.ROLLING_RESTART_MAX_PARALLELISM
        assert len(scope) == 2 * len(shards), "the scope is every member of those shards"
        assert len(scope) <= 2 * docker_runtime.ROLLING_RESTART_MAX_PARALLELISM


def test_rolling_restart_plan_uses_live_roles_instead_of_inventory_roles() -> None:
    nodes = _nodes(6)
    topology = {
        node["logical_id"]: {"role": "primary" if node["role"] == "replica" else "replica"}
        for node in nodes
    }

    entries = docker_runtime._management_matrix_rolling_restart_plan_entries(
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

    monkeypatch.setattr(docker_runtime, "_management_log_node_command", log_command)
    monkeypatch.setattr(
        docker_runtime,
        "_management_wait_node_role",
        lambda node, role, timeout: role_waits.append((node["logical_id"], role)),
    )
    monkeypatch.setattr(
        docker_runtime,
        "_management_matrix_wait_replica_sync_ready",
        lambda replica, primary, timeout: {"status": "PASS", "wait_ms": 1.0},
    )

    safe = docker_runtime._management_matrix_make_primary_restart_safe(
        telemetry=_telemetry(6),
        capability_id="local_full_flow",
        run_id="rolling-6",
        operation_id="primary-safe",
        target=target,
        nodes=nodes,
        topology=topology,
        command_log=[],
    )
    restored = docker_runtime._management_matrix_restore_primary_placement(
        telemetry=_telemetry(6),
        capability_id="local_full_flow",
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

    result = docker_runtime._management_matrix_wait_replica_sync_ready(replica, primary, timeout=1.0)

    assert result["status"] == "PASS"
    assert result["replica_repl_offset"] == result["primary_repl_offset"] == 100


def test_replica_sync_gate_fails_closed_when_topology_is_not_replica(monkeypatch: pytest.MonkeyPatch) -> None:
    primary = {"logical_id": "primary"}
    replica = {"logical_id": "replica"}
    ticks = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(docker_runtime.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(docker_runtime, "_node_command", lambda node, *args, timeout: "primary-id")

    with pytest.raises(docker_runtime.DockerRuntimeError, match="did not catch up"):
        docker_runtime._management_matrix_wait_replica_sync_ready(replica, primary, timeout=1.0)


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

    _health, probe = docker_runtime._management_matrix_wait_rolling_restart_health(
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

    signature = docker_runtime._management_matrix_topology_placement_signature(before)

    assert signature != docker_runtime._management_matrix_topology_placement_signature(wrong_master)
    assert signature != docker_runtime._management_matrix_topology_placement_signature(wrong_slots)


@pytest.mark.parametrize(
    ("failure_kind", "expected"),
    [("tool", CollectionError), ("semantic", docker_runtime.DockerRuntimeError)],
)
def test_an_unread_node_is_not_reported_as_a_changed_role(
    monkeypatch: pytest.MonkeyPatch, failure_kind: str, expected: type[Exception]
) -> None:
    """The named defect: `live role changed ... actual=MISSING`.

    `_management_live_topology` dropped any node whose light probe was not OK, and
    the strict check reported that absence as a role change - a collector failure
    blamed on Valkey, which acceptance item 12 forbids. The node's own probe row
    already says why it failed and which 12.1 kind it was, so both are reported
    as themselves, and 12.2's precedence decides the class.
    """

    nodes = _nodes(6)
    missing = str(nodes[0]["logical_id"])

    def live_topology(current, **_kwargs):
        return (
            {
                node["logical_id"]: {"role": node["role"]}
                for node in current
                if str(node["logical_id"]) != missing
            },
            {missing: {"reason": "probe did not answer", "kind": failure_kind}},
        )

    monkeypatch.setattr(docker_runtime, "_management_live_topology", live_topology)

    with pytest.raises(expected) as excinfo:
        docker_runtime._management_matrix_rolling_restart_plan_entries(
            "rolling_restart_replica_first", "op", nodes
        )

    message = str(excinfo.value)
    assert missing in message
    assert "probe did not answer" in message
    # The old message claimed a role change and hid the reason. Never again.
    assert "role changed" not in message
    assert "actual=MISSING" not in message
    assert excinfo.type is expected
    if failure_kind == "tool":
        assert "could not be observed" in message


def test_one_disagreeing_node_outranks_any_number_of_unread_ones() -> None:
    """12.2: a confirmed failure beats a tool error, so the class is FAIL."""

    gaps = {
        "node-a": {"reason": "connection refused", "kind": "semantic"},
        "node-b": {"reason": "[Errno 49] Can't assign requested address", "kind": "tool"},
        "node-c": {"reason": "[Errno 49] Can't assign requested address", "kind": "tool"},
    }

    error = docker_runtime._management_topology_gap_error(gaps, sorted(gaps), "check")

    assert type(error) is docker_runtime.DockerRuntimeError
    assert "could not be observed" not in str(error)

    # Only tool errors, and only then, is it an ERROR.
    tool_only = {key: gaps[key] for key in ("node-b", "node-c")}
    tool_error = docker_runtime._management_topology_gap_error(
        tool_only, sorted(tool_only), "check"
    )
    assert type(tool_error) is CollectionError

    # A stage only cares about the nodes it asked about.
    assert docker_runtime._management_topology_gap_error(gaps, ["node-z"], "check") is None


@pytest.mark.parametrize(
    ("failure_kind", "expected"),
    [("tool", CollectionError), ("semantic", docker_runtime.DockerRuntimeError)],
)
def test_a_batch_whose_node_went_unread_mid_restart_says_so(
    monkeypatch: pytest.MonkeyPatch, failure_kind: str, expected: type[Exception]
) -> None:
    """The same gap, at the per-batch reading rather than at planning.

    Planning reads the whole fleet once; the batch loop re-reads each batch's
    scope before restarting it, and that second reading is a separate site with
    its own check. Seeding the defect back proved the planning test alone does
    not reach it, which is why this test exists at all.
    """

    nodes = _nodes(6)
    node_count = len(nodes)
    scopes: list[list[str]] = []
    # `rolling_restart_replica_first` restarts replicas first and batches are
    # shard-disjoint, so this node is a target of the first batch.
    unread = "shard-0000-replica"

    def live_topology(current, **_kwargs):
        scope = [str(node["logical_id"]) for node in current]
        scopes.append(scope)
        # The first reading is planning and must succeed. From the second on, the
        # node this batch is about to restart goes unread - a peer going unread
        # is a different question and deliberately does not stop the batch.
        if len(scopes) == 1 or unread not in scope:
            return {node["logical_id"]: {"role": node["role"]} for node in current}, {}
        return (
            {
                node["logical_id"]: {"role": node["role"]}
                for node in current
                if str(node["logical_id"]) != unread
            },
            {unread: {"reason": "probe did not answer", "kind": failure_kind}},
        )

    monkeypatch.setattr(
        docker_runtime, "_management_cluster_health", lambda _n, **_kwargs: _clean_health(node_count)
    )
    monkeypatch.setattr(docker_runtime, "_management_live_topology", live_topology)
    monkeypatch.setattr(
        docker_runtime,
        "_management_matrix_wait_rolling_restart_health",
        lambda *_a, **_k: (_clean_health(node_count), {"status": "PASS"}),
    )
    monkeypatch.setattr(
        docker_runtime,
        "_management_matrix_restart_process_target",
        lambda **_k: (_ for _ in ()).throw(
            AssertionError("a batch must not restart anything while a node is unread")
        ),
    )

    with pytest.raises(expected) as excinfo:
        docker_runtime._management_matrix_execute_process_rolling_restart(
            telemetry=_telemetry(node_count),
            capability_id="local_full_flow",
            run_id=f"rolling-{node_count}",
            operation_name="rolling_restart_replica_first",
            operation_id=f"rolling-batch-gap-{node_count}",
            nodes=nodes,
            command_log=[],
            backend=NoRuntimeBackend(),
        )

    message = str(excinfo.value)
    assert "probe did not answer" in message
    assert "role changed" not in message
    assert "actual=MISSING" not in message
    assert excinfo.type is expected
    assert len(scopes) > 1, "the batch loop must have re-read the topology"


class _Clock:
    """A monotonic clock that only advances when the gate sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _install_clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(docker_runtime.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(docker_runtime.time, "sleep", clock.sleep)
    return clock


def _snapshot_rows(probe_nodes: list[dict[str, Any]], clean: bool) -> list[dict[str, Any]]:
    """One reading per probed node.

    `known_nodes` stays the cluster's own count however few nodes are probed,
    because it is what each node reports about the whole cluster rather than a
    property of the sample. Tying it to the sample size instead is what the
    first version of this helper did, and it made the scoped probe unable to be
    clean at all - so the gate could only ever end on the diagnostic, which is
    the very thing under test.
    """

    health = {key: value for key, value in _clean_health(200).items() if key != "snapshots"}
    if not clean:
        health["cluster_state"] = "unknown"
    return [
        {"logical_id": node["logical_id"], "probe_status": "PASS", **health}
        for node in probe_nodes
    ]


def test_the_health_gate_diagnostic_is_rate_limited_not_run_every_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A waiting gate used to run a whole-fleet `CLUSTER NODES` round a second.

    Measured on a real exact-200 acceptance run,
    `gate-20260815T174023Z-9bca9ac6`: one gate escalated **85 times over
    116.8 s** and moved **19,150 `CLUSTER NODES` and 484.3 MB**, against 1,442
    and 36.6 MB in the run taken beside it. §16 item 1 forbids the normal path
    from periodically running whole-fleet `CLUSTER NODES`; a reply is 25.2 KB at
    200 nodes and grows with node count, so the same event at 1280 nodes moves
    about 17 GB through one controller.
    """

    nodes = _nodes(200)
    clock = _install_clock(monkeypatch)
    probed: list[tuple[float, int]] = []

    def snapshots(probe_nodes: list[dict[str, Any]], *, timeout: float) -> list[dict[str, Any]]:
        del timeout
        probed.append((clock.now, len(probe_nodes)))
        return _snapshot_rows(probe_nodes, clean=False)

    monkeypatch.setattr(docker_runtime, "_process_node_snapshots_parallel", snapshots)

    with pytest.raises(docker_runtime.DockerRuntimeError):
        docker_runtime._management_matrix_wait_rolling_restart_health(
            nodes, timeout=120.0, full_probe=False
        )

    whole_fleet = [when for when, size in probed if size == len(nodes)]
    # One taken at once, then one per WHOLE_FLEET_RECHECK_SECONDS, then one on
    # the way out. Left unlimited a 120s wait costs 120 of them.
    assert len(whole_fleet) <= 11, "a 120s gate must not cost 120 whole-fleet rounds"
    assert len(whole_fleet) >= 8
    assert whole_fleet[0] == 0.0, "the first reading is still taken at once"
    # And the failure still reports what the whole fleet looked like, freshly.
    assert probed[-1][1] == len(nodes)


def test_the_health_gate_still_ends_on_its_scoped_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rate limit is on the diagnostic, never on the decision.

    The scoped probe is a subset of the diagnostic's nodes and every health
    field is a min or a max over what was probed, so a scoped reading that is
    not clean cannot become clean by probing more nodes at the same instant. All
    the escalation ever added was a second reading a moment later, which the
    next attempt takes anyway - so removing it from every attempt must not delay
    the gate by even one poll.
    """

    nodes = _nodes(200)
    clock = _install_clock(monkeypatch)
    settles_at = 5.0

    def snapshots(probe_nodes: list[dict[str, Any]], *, timeout: float) -> list[dict[str, Any]]:
        del timeout
        return _snapshot_rows(probe_nodes, clean=clock.now >= settles_at)

    monkeypatch.setattr(docker_runtime, "_process_node_snapshots_parallel", snapshots)

    _health, probe = docker_runtime._management_matrix_wait_rolling_restart_health(
        nodes, timeout=120.0, full_probe=False
    )

    assert probe["status"] == "PASS"
    assert clock.now == settles_at, "the gate ends when the scoped probe clears"
    assert probe["sample_scope"] == "representative_by_az_and_required_nodes"
    # Exactly one diagnostic - the immediate one. Unlimited it would be five,
    # one per second of the wait.
    assert probe["full_probe_count"] == len(nodes)


def test_a_cluster_that_settles_at_the_deadline_still_passes_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rate limit must not be able to fail a gate that would have passed.

    The in-loop diagnostic no longer runs every second, so a cluster settling
    inside the last WHOLE_FLEET_RECHECK_SECONDS would time out where before a
    diagnostic a second later ended the gate. The reading taken on the way out
    is therefore decisive as well as diagnostic. Here the scoped probe never
    clears at all and only the whole fleet does, which is the shape that has no
    other way through.
    """

    nodes = _nodes(200)
    clock = _install_clock(monkeypatch)
    settles_at = 25.0

    def snapshots(probe_nodes: list[dict[str, Any]], *, timeout: float) -> list[dict[str, Any]]:
        del timeout
        whole_fleet = len(probe_nodes) == len(nodes)
        return _snapshot_rows(probe_nodes, clean=whole_fleet and clock.now >= settles_at)

    monkeypatch.setattr(docker_runtime, "_process_node_snapshots_parallel", snapshots)

    _health, probe = docker_runtime._management_matrix_wait_rolling_restart_health(
        nodes, timeout=30.0, full_probe=False
    )

    assert probe["status"] == "PASS"
    assert probe["sample_scope"] == "all_nodes_diagnostic"
    assert probe["attempts"][-1]["sample_scope"] == "all_nodes_diagnostic"
