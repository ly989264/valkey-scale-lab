from __future__ import annotations

import ast
import copy
import errno
import json
import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from valkey_scale_lab.observability import cluster as cluster_module
from valkey_scale_lab.observability.cluster import (
    CONVERGENCE_NO_PROGRESS_SECONDS,
    EndpointConnections,
    FullClusterValidator,
    LightClusterProbe,
    NodeEndpoint,
    TopologyObserver,
    cluster_shards_node_ids,
    normalize_cluster_shards,
    observation_complexity,
    parse_myslots,
)
from valkey_scale_lab.observability.contracts import (
    CheckResult,
    CheckStatus,
    CollectionError,
    ConvergenceFailure,
    SemanticFailure,
    final_verdict,
    is_collection_failure,
    is_transient_transport_error,
    run_check,
)
from valkey_scale_lab.observability.failover import (
    ActuatorRecorder,
    AffectedShardObserver,
    redundancy_recovery,
    sample_affected_observers,
)
from valkey_scale_lab.observability import load as load_module
from valkey_scale_lab.observability.load import MemtierLoadLane, per_connection_rate
from valkey_scale_lab.observability import resources as resources_module
from valkey_scale_lab.observability.resources import (
    ExpectedGoneProcess,
    LocalResourceSampler,
    ProcessSpec,
    ResourceSamplerRunner,
    analyze_resource_samples,
)
from valkey_scale_lab.observability import resource_observation as observation_module
from valkey_scale_lab.observability.resource_observation import run_resource_observation
from valkey_scale_lab.observability.sentinel import (
    MAX_SEEDS_PER_LOOKUP,
    Canary,
    ClusterRouter,
    SentinelLane,
    SentinelNode,
    _round_cadence,
    key_slot,
    slot_tags,
)
from valkey_scale_lab.observability.stability import StabilityWindow
from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.runtime.docker_runtime import ValkeyErrorReply
from valkey_scale_lab.valkey.resp import (
    Endpoint,
    RespCommandError,
    RespProtocolError,
    read_response,
)


def _bitmap(start: int, end: int) -> bytes:
    value = bytearray(2048)
    for slot in range(start, end + 1):
        value[slot >> 3] |= 1 << (slot & 7)
    return bytes(value)


def _myslots(
    node_id: str,
    shard_id: str,
    role: str,
    owner_id: str,
    bitmap: bytes,
) -> list[Any]:
    return [
        b"node-id",
        node_id.encode(),
        b"shard-id",
        shard_id.encode(),
        b"role",
        role.encode(),
        b"slot-owner-id",
        owner_id.encode(),
        b"slot-count",
        sum(bin(byte).count("1") for byte in bitmap),
        b"bitmap-encoding",
        b"lsb0",
        b"slot-bitmap",
        bitmap,
    ]


def _shards(node_ids: list[str]) -> list[Any]:
    return [
        [
            b"slots",
            [0, 8191],
            b"nodes",
            [
                [
                    b"id",
                    node_ids[0].encode(),
                    b"endpoint",
                    b"127.0.0.1",
                    b"port",
                    7000,
                    b"role",
                    b"master",
                    b"health",
                    b"online",
                ],
                [
                    b"id",
                    node_ids[2].encode(),
                    b"endpoint",
                    b"127.0.0.1",
                    b"port",
                    7002,
                    b"role",
                    b"replica",
                    b"health",
                    b"online",
                ],
            ],
        ],
        [
            b"slots",
            [8192, 16383],
            b"nodes",
            [
                [
                    b"id",
                    node_ids[1].encode(),
                    b"endpoint",
                    b"127.0.0.1",
                    b"port",
                    7001,
                    b"role",
                    b"master",
                    b"health",
                    b"online",
                ],
                [
                    b"id",
                    node_ids[3].encode(),
                    b"endpoint",
                    b"127.0.0.1",
                    b"port",
                    7003,
                    b"role",
                    b"replica",
                    b"health",
                    b"online",
                ],
            ],
        ],
    ]


class FakeConnection:
    def __init__(self, responses: dict[tuple[Any, ...], Any]) -> None:
        self.responses = responses
        self.closed = False

    def connect(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def execute(self, *command: Any) -> Any:
        value = self.responses[tuple(command)]
        if isinstance(value, Exception):
            raise value
        return value() if callable(value) else value

    def execute_many(self, commands: Any) -> list[Any]:
        return [self.execute(*command) for command in commands]

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()


def _cluster_fixture() -> tuple[list[NodeEndpoint], dict[int, dict[tuple[Any, ...], Any]]]:
    nodes = [
        NodeEndpoint("p0", "127.0.0.1", 7000, "primary", "s0", "az-a", "h0"),
        NodeEndpoint("p1", "127.0.0.1", 7001, "primary", "s1", "az-b", "h1"),
        NodeEndpoint("r0", "127.0.0.1", 7002, "replica", "s0", "az-b", "h2"),
        NodeEndpoint("r1", "127.0.0.1", 7003, "replica", "s1", "az-a", "h3"),
    ]
    ids = [f"{index + 1:040x}" for index in range(4)]
    shard_ids = ["a" * 40, "b" * 40]
    bitmaps = [_bitmap(0, 8191), _bitmap(8192, 16383)]
    info = (
        b"cluster_state:ok\r\ncluster_slots_assigned:16384\r\n"
        b"cluster_slots_ok:16384\r\ncluster_slots_fail:0\r\n"
        b"cluster_known_nodes:4\r\ncluster_current_epoch:1\r\n"
    )
    responses: dict[int, dict[tuple[Any, ...], Any]] = {}
    for index, node in enumerate(nodes):
        shard = 0 if index in {0, 2} else 1
        owner = ids[shard]
        role = node.expected_role
        role_response = (
            [b"master", 0, []]
            if role == "primary"
            else [b"slave", b"127.0.0.1", 7000 + shard, b"connected", 0]
        )
        responses[node.port] = {
            ("PING",): "PONG",
            ("CLUSTER", "INFO"): info,
            ("ROLE",): role_response,
            ("CLUSTER", "MYID"): ids[index].encode(),
            ("CLUSTER", "MYSHARDID"): shard_ids[shard].encode(),
            ("CLUSTER", "MYSLOTS"): _myslots(
                ids[index], shard_ids[shard], role, owner, bitmaps[shard]
            ),
            ("CLUSTER", "SHARDS"): _shards(ids),
        }
    return nodes, responses


def test_light_probe_keeps_one_connection_per_endpoint_across_rounds() -> None:
    """Rounds reuse connections instead of paying a handshake per node per round.

    A whole-fleet probe opening and closing a socket per node per round is what
    exhausted the host's ephemeral ports at 200 nodes; the cost is per round, so
    it is the second round that has to be free.
    """
    nodes, responses = _cluster_fixture()
    opened: list[int] = []

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        opened.append(endpoint.port)
        return FakeConnection(responses[endpoint.port])

    connections = EndpointConnections()
    for _round in range(5):
        rows = LightClusterProbe(
            nodes, concurrency=32, connection_factory=factory, connections=connections
        ).collect()
        assert [row["status"] for row in rows] == ["OK"] * 4

    assert len(opened) == 4, "one connection per endpoint, not one per round"
    connections.close_all()


def test_light_probe_reports_a_dead_node_from_a_fresh_connection() -> None:
    """A stale kept connection is not evidence; the node's own refusal is.

    Reuse must not turn "the socket we had is gone" into the reported error, or
    a node that really died would be described by our bookkeeping instead of by
    itself.
    """
    nodes, responses = _cluster_fixture()
    dead_port = nodes[0].port
    node_is_dead = False
    attempts: list[int] = []
    kept: dict[int, FakeConnection] = {}

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        attempts.append(endpoint.port)
        if endpoint.port == dead_port and node_is_dead:
            failing = FakeConnection({})

            def refuse(*_command: Any) -> Any:
                raise ConnectionRefusedError("[Errno 61] Connection refused")

            failing.execute = refuse  # type: ignore[method-assign]
            return failing
        connection = FakeConnection(responses[endpoint.port])
        kept[endpoint.port] = connection
        return connection

    connections = EndpointConnections()
    probe = lambda: LightClusterProbe(  # noqa: E731 - the probe is rebuilt per round
        nodes, concurrency=32, connection_factory=factory, connections=connections
    ).collect()

    assert [row["status"] for row in probe()] == ["OK"] * 4

    # The node dies, so the connection we kept for it is now stale.
    node_is_dead = True

    def closed_by_peer(*_command: Any) -> Any:
        raise EOFError("Valkey connection closed")

    kept[dead_port].execute = closed_by_peer  # type: ignore[method-assign]

    rows = {row["logical_id"]: row for row in probe()}

    assert rows["p0"]["status"] == "FAIL"
    assert "ConnectionRefusedError" in rows["p0"]["error"], rows["p0"]["error"]
    assert "EOFError" not in rows["p0"]["error"]
    assert attempts.count(dead_port) == 2, "one retry on a fresh connection, not more"
    assert [rows[name]["status"] for name in ("p1", "r0", "r1")] == ["OK"] * 3
    connections.close_all()


def test_light_probe_does_not_pool_a_caller_supplied_factory_by_default() -> None:
    nodes, responses = _cluster_fixture()
    opened: list[int] = []

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        opened.append(endpoint.port)
        return FakeConnection(responses[endpoint.port])

    for _round in range(3):
        LightClusterProbe(nodes, concurrency=32, connection_factory=factory).collect()

    assert len(opened) == 12, "a caller owning its connections opts into reuse"


def test_full_cluster_validation_is_linear_plus_fixed_observers() -> None:
    nodes, responses = _cluster_fixture()
    calls: list[tuple[int, tuple[Any, ...]]] = []

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        connection = FakeConnection(responses[endpoint.port])
        original = connection.execute

        def execute(*command: Any) -> Any:
            calls.append((endpoint.port, tuple(command)))
            return original(*command)

        connection.execute = execute  # type: ignore[method-assign]
        return connection

    result = FullClusterValidator(
        nodes, concurrency=32, observer_count=3, connection_factory=factory
    ).run()

    assert result["status"] == "OK"
    assert result["light_validation"]["nodes_observed"] == 4
    assert result["topology_validation"]["observer_count"] == 3
    assert sum(command == ("CLUSTER", "MYSLOTS") for _, command in calls) == 4
    assert sum(command == ("CLUSTER", "SHARDS") for _, command in calls) == 3
    assert all(command != ("CLUSTER", "NODES") for _, command in calls)


def _option_value(command: list[str], name: str) -> str:
    """The value of a `--name=value` option in a built command line."""
    prefix = f"{name}="
    matches = [item[len(prefix):] for item in command if item.startswith(prefix)]
    assert len(matches) == 1, f"{name} appears {len(matches)} times in {command}"
    return matches[0]


def _shards_with_loading_replica(node_ids: list[str]) -> list[Any]:
    """CLUSTER SHARDS where one replica has not finished its initial sync."""
    shards = copy.deepcopy(_shards(node_ids))
    replica = shards[0][3][1]
    assert replica[-2] == b"health"
    replica[-1] = b"loading"
    return shards



class _FakeLoadLaneHost:
    """A runtime host for the Load Lane, with no runtime behind it.

    §15 keeps the Load Lane unchanged across backends, so its own tests must be
    able to run without one. The Docker implementation of this protocol is
    asserted where it lives, in the Docker runtime's contract tests.
    """

    seed_host = "10.0.0.7"

    def __init__(self) -> None:
        self.collected: list[tuple[str, str]] = []
        self.fail_collect: str | None = None

    def command(self, argv: Any, *, remote_dir: str) -> list[str]:
        return ["on-host", remote_dir, *[str(arg) for arg in argv]]

    def collect_evidence(self, remote_dir: str, local_dir: Path) -> None:
        if self.fail_collect is not None:
            raise CollectionError(
                f"could not copy memtier output out of host: {self.fail_collect}"
            )
        self.collected.append((remote_dir, local_dir.as_posix()))


def test_load_lane_runs_on_the_runtime_host_it_was_given(tmp_path: Path) -> None:
    lane = MemtierLoadLane(
        host="127.0.0.1",
        port=7401,
        primary_count=25,
        run_scope="run:stability",
        artifacts_dir=tmp_path,
        remote_host=_FakeLoadLaneHost(),
    )
    paths = lane.paths("formal")
    command = lane.command(paths, duration_seconds=120)

    # The cluster advertises the runtime's own addresses, so memtier has to run
    # where those resolve rather than here - and where that is, is the adapter's.
    # Run-scoped: the lane's remote directory is the one residue a native run
    # leaves, and a directory named only "formal" says nothing about whose it
    # is. `run_scope` already names the run and the lane; the colon becomes a
    # dash so the path stays easy for every tool that reads one.
    assert command[:2] == ["on-host", "/tmp/vslab-load-lane/run-stability/formal"]
    assert "memtier_benchmark" in command
    assert "--cluster-mode" in command

    # Output goes to a path on that host and is collected back to the local paths.
    assert paths.remote_dir == "/tmp/vslab-load-lane/run-stability/formal"
    assert f"--json-out-file={paths.remote_dir}/{paths.json.name}" in command
    assert f"--hdr-file-prefix={paths.remote_dir}/{paths.hdr_prefix.name}" in command
    assert not any(str(tmp_path) in part for part in command)

    # stdout and stderr still stream straight back over the launcher's channel.
    assert paths.stdout.parent == tmp_path
    assert paths.stderr.parent == tmp_path


def test_load_lane_runs_here_when_it_was_given_no_runtime_host(tmp_path: Path) -> None:
    lane = MemtierLoadLane(
        host="127.0.0.1",
        port=7401,
        primary_count=25,
        run_scope="run:stability",
        artifacts_dir=tmp_path,
    )
    paths = lane.paths("formal")
    command = lane.command(paths, duration_seconds=120)

    assert command[0] == "memtier_benchmark"
    assert paths.remote_dir is None
    assert f"--json-out-file={paths.json.as_posix()}" in command


def test_load_lane_collects_host_output_back_to_the_local_paths(tmp_path: Path) -> None:
    host = _FakeLoadLaneHost()
    lane = MemtierLoadLane(
        host="127.0.0.1",
        port=7401,
        primary_count=25,
        run_scope="run:stability",
        artifacts_dir=tmp_path,
        remote_host=host,
    )
    lane._collect_outputs(lane.paths("formal"))

    assert host.collected == [("/tmp/vslab-load-lane/run-stability/formal", tmp_path.as_posix())]


def test_load_lane_reports_a_failed_output_collection(tmp_path: Path) -> None:
    host = _FakeLoadLaneHost()
    host.fail_collect = "no such container"
    lane = MemtierLoadLane(
        host="127.0.0.1",
        port=7401,
        primary_count=25,
        run_scope="run:stability",
        artifacts_dir=tmp_path,
        remote_host=host,
    )

    with pytest.raises(CollectionError, match="could not copy memtier output"):
        lane._collect_outputs(lane.paths("formal"))


def test_load_lane_holds_no_runtime_of_its_own() -> None:
    """§15 keeps the Load Lane unchanged across backends.

    It named `docker` three times until roadmap item 0.5 - the exec wrapper, the
    `which` preflight and the output copy. This is the boundary, pinned.
    """
    source = Path(load_module.__file__).read_text(encoding="utf-8")
    assert "docker" not in source


def test_permanent_role_mismatch_fails_without_waiting_for_convergence() -> None:
    nodes, responses = _cluster_fixture()
    # The node planned as a primary is observed as a replica, as it would be
    # after an intentional promotion. That never resolves by looking again.
    nodes[0] = NodeEndpoint("p0", "127.0.0.1", 7000, "replica", "s0", "az-a", "h0")
    attempts = [0]

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        if endpoint.port == 7000:
            attempts[0] += 1
        return FakeConnection(responses[endpoint.port])

    with pytest.raises(SemanticFailure) as excinfo:
        FullClusterValidator(
            nodes,
            concurrency=32,
            observer_count=3,
            convergence_timeout=30.0,
            convergence_poll_seconds=1.0,
            connection_factory=factory,
        ).run()

    message = str(excinfo.value)
    assert "role is primary, expected replica" in message
    # Reported as-is, not wrapped in a convergence timeout, and observed once.
    assert "did not converge" not in message
    assert not isinstance(excinfo.value, ConvergenceFailure)
    assert attempts[0] == 1


def test_plan_role_mismatch_is_accepted_when_plan_roles_are_not_required() -> None:
    nodes, responses = _cluster_fixture()
    nodes[0] = NodeEndpoint("p0", "127.0.0.1", 7000, "replica", "s0", "az-a", "h0")

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        return FakeConnection(responses[endpoint.port])

    result = FullClusterValidator(
        nodes, concurrency=32, observer_count=3, connection_factory=factory
    ).run(require_plan_roles=False)

    # Dropping the inventory role plan must not drop the structural contract.
    assert result["status"] == "OK"
    coverage = result["light_validation"]["coverage"]
    assert coverage["all_slots_covered_exactly_once"] is True
    assert coverage["primary_bitmaps_pairwise_disjoint"] is True
    assert coverage["inventory_roles_and_shards_match"] is False
    assert result["light_validation"]["primary_count"] == 2
    assert result["light_validation"]["shard_count"] == 2



def _shards_with_no_primary(node_ids: list[str]) -> list[Any]:
    """A shard between losing its primary and promoting its replica."""
    shards = copy.deepcopy(_shards(node_ids))
    shards[0][3] = [m for m in shards[0][3] if m[1] != node_ids[0].encode()]
    return shards


def _shards_with_two_primaries(node_ids: list[str]) -> list[Any]:
    """Split brain: both members of a shard claim to be its primary."""
    shards = copy.deepcopy(_shards(node_ids))
    replica = shards[0][3][1]
    assert replica[-4] == b"role"
    replica[-3] = b"master"
    return shards


def test_a_shard_awaiting_promotion_is_a_convergence_state() -> None:
    node_ids = [f"{index + 1:040x}" for index in range(4)]

    # The failover tests create this deliberately, and it resolves when the
    # promotion lands, so it must be observable again rather than fatal.
    with pytest.raises(ConvergenceFailure, match="has no serving primary"):
        normalize_cluster_shards(_shards_with_no_primary(node_ids))


def test_two_primaries_in_one_shard_is_permanent() -> None:
    node_ids = [f"{index + 1:040x}" for index in range(4)]

    with pytest.raises(SemanticFailure) as excinfo:
        normalize_cluster_shards(_shards_with_two_primaries(node_ids))

    # Split brain never resolves by looking again, so it must not be retried,
    # and the failure names both primaries and their health.
    message = str(excinfo.value)
    assert "2 healthy primaries" in message
    assert message.count("(online)") == 2
    assert not isinstance(excinfo.value, ConvergenceFailure)



def test_a_failed_primary_beside_its_promoted_replica_is_accepted() -> None:
    node_ids = [f"{index + 1:040x}" for index in range(4)]
    shards = copy.deepcopy(_shards(node_ids))
    # The killed primary is still known and still flagged a primary, while its
    # replica has already been promoted. Both were observed together at t+44.3s
    # in a real exact-10 failover.
    old_primary, promoted = shards[0][3]
    assert old_primary[-2] == b"health"
    old_primary[-1] = b"failed"
    assert promoted[-4] == b"role"
    promoted[-3] = b"master"

    result = normalize_cluster_shards(
        shards, allowed_unhealthy_node_ids={node_ids[0]}
    )

    # The shard settles into this state and stays there until the dead node is
    # removed, so it is the correct post-failover shape, not a wait.
    shard = next(s for s in result["shards"] if (0, 8191) in {tuple(r) for r in s["slots"]})
    # The serving node owns the shard, never the corpse.
    assert shard["primary_id"] == node_ids[2]
    assert node_ids[0] in {member["node_id"] for member in shard["nodes"]}



def test_a_shard_whose_only_primary_failed_is_not_serving() -> None:
    node_ids = [f"{index + 1:040x}" for index in range(4)]
    shards = copy.deepcopy(_shards(node_ids))
    primary = shards[0][3][0]
    primary[-1] = b"failed"

    # Nothing is serving the shard, so this waits rather than being admitted.
    with pytest.raises(ConvergenceFailure) as excinfo:
        normalize_cluster_shards(shards, allowed_unhealthy_node_ids={node_ids[0]})

    assert "no serving primary" in str(excinfo.value)
    assert "(failed)" in str(excinfo.value)


def test_two_healthy_primaries_stay_fatal_even_mid_failover() -> None:
    node_ids = [f"{index + 1:040x}" for index in range(4)]
    shards = copy.deepcopy(_shards(node_ids))
    promoted = shards[0][3][1]
    promoted[-3] = b"master"

    # Allowing the old primary to be unhealthy must not turn split brain into
    # something the validator waits out.
    with pytest.raises(SemanticFailure) as excinfo:
        normalize_cluster_shards(
            shards, allowed_unhealthy_node_ids={node_ids[0]}
        )

    assert "healthy primaries" in str(excinfo.value)
    assert not isinstance(excinfo.value, ConvergenceFailure)


def test_validation_waits_out_a_promotion_then_succeeds() -> None:
    nodes, responses = _cluster_fixture()
    node_ids = [f"{index + 1:040x}" for index in range(4)]
    observed = [0]
    promoting = _shards_with_no_primary(node_ids)
    promoted = _shards(node_ids)

    def shards_response() -> list[Any]:
        observed[0] += 1
        return promoting if observed[0] <= 1 else promoted

    for node in nodes:
        responses[node.port][("CLUSTER", "SHARDS")] = shards_response

    result = FullClusterValidator(
        nodes,
        concurrency=32,
        observer_count=3,
        convergence_timeout=5.0,
        convergence_poll_seconds=0.01,
        connection_factory=lambda endpoint, _t: FakeConnection(responses[endpoint.port]),
    ).run()

    assert result["status"] == "OK"
    assert observed[0] > 3



def test_sentinel_recovery_timeout_reports_what_it_observed() -> None:
    from valkey_scale_lab.observability.sentinel import _recovery_diagnosis

    assert _recovery_diagnosis([], 10) == "no rounds were observed"

    rows = [
        {
            "status": "FAIL",
            "stable_streak": 0,
            "affected_value_ok": False,
            "control_value_ok": True,
            "errors": {"affected": "CLUSTERDOWN The cluster is down"},
        },
        {
            "status": "OK",
            "stable_streak": 1,
            "affected_value_ok": True,
            "control_value_ok": True,
            "errors": {},
        },
    ]
    diagnosis = _recovery_diagnosis(rows, 10)

    # A timeout has to say why it timed out, not just that it did.
    assert "rounds=2" in diagnosis
    assert "best_streak=1/10" in diagnosis
    assert "CLUSTERDOWN" in diagnosis



def test_router_follows_a_promotion_to_an_advertised_address(tmp_path: Path) -> None:
    from valkey_scale_lab.observability.sentinel import ClusterRouter
    from valkey_scale_lab.valkey.resp import RespCommandError

    seed = Endpoint("127.0.0.1", 7200)
    advertised = Endpoint("172.18.0.3", 7205)
    reachable = Endpoint("127.0.0.1", 7205)
    dialled: list[Endpoint] = []

    class Conn:
        def __init__(self, endpoint: Endpoint) -> None:
            self.endpoint = endpoint

        def execute(self, *command: Any) -> Any:
            if self.endpoint == seed:
                # After the promotion the cluster names the new primary by the
                # address it announces, which the observer cannot route.
                raise RespCommandError(f"MOVED 0 {advertised.host}:{advertised.port}")
            return b"canary-value"

        def close(self) -> None:
            return None

    def factory(endpoint: Endpoint, _timeout: float) -> Conn:
        dialled.append(endpoint)
        return Conn(endpoint)

    router = ClusterRouter(
        [seed],
        connection_factory=factory,  # type: ignore[arg-type]
        endpoint_resolver=lambda e: reachable if e == advertised else e,
    )

    assert router.get("probe") == b"canary-value"
    # It dialled the reachable address, never the advertised one.
    assert advertised not in dialled
    assert reachable in dialled


def test_router_without_a_resolver_dials_what_the_cluster_advertised() -> None:
    from valkey_scale_lab.observability.sentinel import ClusterRouter

    seed = Endpoint("127.0.0.1", 7200)
    dialled: list[Endpoint] = []

    class Conn:
        def execute(self, *command: Any) -> Any:
            return b"v"

        def close(self) -> None:
            return None

    def factory(endpoint: Endpoint, _timeout: float) -> Conn:
        dialled.append(endpoint)
        return Conn()

    router = ClusterRouter([seed], connection_factory=factory)  # type: ignore[arg-type]
    router.get("probe")

    assert dialled == [seed]


def test_runtime_resolves_announced_nodehost_addresses() -> None:
    from valkey_scale_lab.runtime.docker_runtime import _advertised_endpoint_resolver

    resolve = _advertised_endpoint_resolver(
        [
            {
                "logical_id": "shard-0000-replica-00",
                "host": "127.0.0.1",
                "client_port": 7205,
                "nodehost_container_ip": "172.18.0.3",
            }
        ]
    )

    assert resolve(Endpoint("172.18.0.3", 7205)) == Endpoint("127.0.0.1", 7205)
    # Anything the inventory does not describe is left exactly as it came.
    assert resolve(Endpoint("172.18.0.9", 7300)) == Endpoint("172.18.0.9", 7300)
    assert resolve(Endpoint("127.0.0.1", 7205)) == Endpoint("127.0.0.1", 7205)



def test_a_single_observation_reports_what_it_saw_unwrapped() -> None:
    nodes, responses = _cluster_fixture()
    node_ids = [f"{index + 1:040x}" for index in range(4)]
    factory, observed = _loading_then_healthy_factory(
        nodes, responses, node_ids, loading_observations=10**6
    )

    # A caller that owns the deadline asks for one observation. Nesting a wait
    # inside its retry loop would double the worst case for that window.
    with pytest.raises(ConvergenceFailure) as excinfo:
        FullClusterValidator(
            nodes,
            concurrency=32,
            observer_count=3,
            convergence_timeout=0.0,
            connection_factory=factory,
        ).run()

    message = str(excinfo.value)
    assert "did not converge within" not in message
    assert "CLUSTER SHARDS contains unhealthy nodes" in message
    # Exactly one round of observers, never a second attempt.
    assert observed[0] == 1


def test_the_nested_failover_validation_does_not_wait() -> None:
    import inspect

    from valkey_scale_lab.runtime import docker_runtime

    source = inspect.getsource(docker_runtime._run_scalable_primary_kill_failover)
    validation = source.split("def full_validation_while_target_down")[1]
    assert "convergence_timeout=0.0" in validation.split(".run(")[0]



def test_the_fault_sequence_leaves_the_load_lane_to_steady_state() -> None:
    import inspect

    from valkey_scale_lab.runtime import docker_runtime

    source = inspect.getsource(docker_runtime._run_scalable_primary_kill_failover)

    # memtier stops issuing operations for good once an endpoint disappears, so
    # running it across the fault would record the client's outage, not the
    # cluster's. The Sentinel canaries carry the fault window instead.
    assert "MemtierLoadLane(" not in source
    assert "load.start(" not in source
    assert "NOT_APPLICABLE" in source

    # The Sentinel still probes affected and control shards through the fault.
    assert "sentinel.fault_probe" in source
    assert "affected=affected_canary" in source
    assert "control=control_canary" in source


def test_the_steady_state_window_still_drives_load() -> None:
    import inspect

    from valkey_scale_lab.runtime import docker_runtime

    source = inspect.getsource(
        docker_runtime._local_full_flow_run_management_sequence
    )

    # Scoping the lane to steady state must not remove it from steady state.
    assert "MemtierLoadLane(" in source



def test_formation_waits_still_assert_the_role_plan() -> None:
    import inspect

    from valkey_scale_lab.runtime import docker_runtime

    source = inspect.getsource(docker_runtime._wait_process_snapshot_clean)
    # The option is opt-in per call site; nothing is relaxed by default.
    assert "validation_options: Mapping[str, Any] | None = None" in source


def test_cluster_shards_membership_ignores_unrelated_node_health() -> None:
    node_ids = [f"{index + 1:040x}" for index in range(4)]
    raw = _shards_with_loading_replica(node_ids)

    # Membership answers only who is known, so a converging replica elsewhere
    # cannot decide whether some other node is still in the cluster.
    assert cluster_shards_node_ids(raw) == set(node_ids)

    # The health contract itself is untouched for callers that ask for it.
    with pytest.raises(SemanticFailure, match="contains unhealthy nodes"):
        normalize_cluster_shards(raw)


def test_cluster_shards_membership_reports_a_removed_node_absent() -> None:
    node_ids = [f"{index + 1:040x}" for index in range(4)]
    removed = node_ids[2]
    raw = copy.deepcopy(_shards(node_ids))
    raw[0][3] = [member for member in raw[0][3] if member[1] != removed.encode()]

    known = cluster_shards_node_ids(raw)

    assert removed not in known
    assert known == {node_ids[0], node_ids[1], node_ids[3]}


def _loading_then_healthy_factory(
    nodes: list[NodeEndpoint],
    responses: dict[int, dict[tuple[Any, ...], Any]],
    node_ids: list[str],
    *,
    loading_observations: int,
) -> tuple[Any, list[int]]:
    """Report `loading` for the first N CLUSTER SHARDS observations, then `online`."""
    observed = [0]
    loading = _shards_with_loading_replica(node_ids)
    healthy = _shards(node_ids)

    def shards_response() -> list[Any]:
        observed[0] += 1
        return loading if observed[0] <= loading_observations else healthy

    for node in nodes:
        responses[node.port][("CLUSTER", "SHARDS")] = shards_response

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        return FakeConnection(responses[endpoint.port])

    return factory, observed


def test_convergence_retries_reread_the_observers_not_the_whole_fleet() -> None:
    """A wait costs three `CLUSTER SHARDS` per attempt, not one round per node.

    Measured on a real exact-200 formation: 77 attempts over 156.7s, and every
    attempt spent a whole-fleet 200-node light round - 1200 RESP commands and
    400 KB of `CLUSTER MYSLOTS` bitmap - to reach a check that failed on three
    observers. The light validation passed 77 of 77 times; layer 2 raised 77 of
    77. §4.4 budgets the whole-fleet round at one per 60s and this issued one
    every 2.0s.

    The first attempt still reads both layers in the original order, so a
    permanent failure the light layer alone can see is still reported at once
    rather than waited out.
    """

    nodes, responses = _cluster_fixture()
    node_ids = [f"{index + 1:040x}" for index in range(4)]
    factory, _observed = _loading_then_healthy_factory(
        nodes, responses, node_ids, loading_observations=20
    )
    myslots = [0]
    inner = factory

    def counting_factory(endpoint: Endpoint, timeout: float) -> FakeConnection:
        connection = inner(endpoint, timeout)
        original = connection.execute

        def execute(*command: Any) -> Any:
            if command == ("CLUSTER", "MYSLOTS"):
                myslots[0] += 1
            return original(*command)

        connection.execute = execute  # type: ignore[method-assign]
        return connection

    result = FullClusterValidator(
        nodes,
        concurrency=32,
        observer_count=3,
        convergence_timeout=30.0,
        convergence_poll_seconds=0.001,
        connection_factory=counting_factory,
    ).run()

    assert result["status"] == "OK"
    # Twenty-one attempts, four nodes: the old order costs 84 whole-fleet
    # `CLUSTER MYSLOTS`. Only the first attempt and the one that succeeds may
    # pay for a round, so the bound is two rounds however long the wait runs.
    assert myslots[0] == 2 * len(nodes)


def test_full_cluster_validation_waits_for_transient_loading_to_converge() -> None:
    nodes, responses = _cluster_fixture()
    node_ids = [f"{index + 1:040x}" for index in range(4)]
    factory, observed = _loading_then_healthy_factory(
        nodes, responses, node_ids, loading_observations=1
    )

    result = FullClusterValidator(
        nodes,
        concurrency=32,
        observer_count=3,
        convergence_timeout=5.0,
        convergence_poll_seconds=0.01,
        connection_factory=factory,
    ).run()

    assert result["status"] == "OK"
    # The first observation failed the health contract, so validation retried.
    assert observed[0] > 3


def test_full_cluster_validation_fails_when_loading_never_converges() -> None:
    nodes, responses = _cluster_fixture()
    node_ids = [f"{index + 1:040x}" for index in range(4)]
    factory, observed = _loading_then_healthy_factory(
        nodes, responses, node_ids, loading_observations=10**6
    )

    with pytest.raises(SemanticFailure) as excinfo:
        FullClusterValidator(
            nodes,
            concurrency=32,
            observer_count=3,
            convergence_timeout=0.05,
            convergence_poll_seconds=0.01,
            connection_factory=factory,
        ).run()

    message = str(excinfo.value)
    assert "did not converge" in message
    # `loading` is never admitted as a terminal healthy state.
    assert "CLUSTER SHARDS contains unhealthy nodes" in message
    assert node_ids[2] in message
    assert observed[0] >= 2


def test_observation_plan_remains_linear_for_any_supported_scale() -> None:
    for node_count in (30, 137, 2000):
        plan = observation_complexity(node_count, observer_count=3)
        assert plan["light_command_count"] == node_count * 6
        assert plan["light_bitmap_bytes"] == node_count * 2048
        assert plan["cluster_shards_view_count"] == 3
        assert plan["cluster_nodes_command_count"] == 0


def test_light_validation_rejects_overlapping_primary_bitmaps() -> None:
    nodes, responses = _cluster_fixture()
    ids = [f"{index + 1:040x}" for index in range(4)]
    responses[7001][("CLUSTER", "MYSLOTS")] = _myslots(
        ids[1], "b" * 40, "primary", ids[1], _bitmap(0, 16383)
    )
    responses[7003][("CLUSTER", "MYSLOTS")] = _myslots(
        ids[3], "b" * 40, "replica", ids[1], _bitmap(0, 16383)
    )
    probe = LightClusterProbe(
        nodes,
        concurrency=32,
        connection_factory=lambda endpoint, _timeout: FakeConnection(
            responses[endpoint.port]
        ),
    )

    with pytest.raises(SemanticFailure, match="overlap"):
        probe.run()


def test_myslots_requires_exact_contract_and_bitmap_population() -> None:
    bitmap = _bitmap(0, 9)
    parsed = parse_myslots(
        _myslots("1" * 40, "a" * 40, "primary", "1" * 40, bitmap)
    )
    assert parsed.slot_count == 10
    invalid = _myslots("1" * 40, "a" * 40, "primary", "1" * 40, bitmap)
    invalid[9] = 11
    with pytest.raises(SemanticFailure, match="slot-count"):
        parse_myslots(invalid)


def test_resp_reader_supports_resp2_arrays_and_resp3_maps() -> None:
    resp2 = read_response(BytesIO(b"*2\r\n$3\r\nkey\r\n:7\r\n"))
    resp3 = read_response(BytesIO(b"%1\r\n$3\r\nkey\r\n:7\r\n"))

    assert resp2 == [b"key", 7]
    assert resp3 == {b"key": 7}


def test_cluster_shards_normalization_rejects_duplicate_slot() -> None:
    node_ids = [f"{index + 1:040x}" for index in range(4)]
    value = _shards(node_ids)
    value[1][1] = [8191, 16383]
    with pytest.raises(SemanticFailure, match="duplicated"):
        normalize_cluster_shards(value)


def test_check_contract_retries_collection_once_and_preserves_fail() -> None:
    attempts = 0

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise CollectionError("collector unavailable")

    error = run_check("collector", operation)
    failure = run_check(
        "cluster", lambda: (_ for _ in ()).throw(SemanticFailure("wrong role"))
    )
    verdict = final_verdict([error, failure])

    assert error.status is CheckStatus.ERROR
    assert error.attempts == 2
    assert failure.status is CheckStatus.FAIL
    assert failure.attempts == 1
    assert verdict["status"] == "FAIL"
    assert verdict["tool_errors"] == ["collector"]


def test_check_contract_reports_error_only_tool_failures() -> None:
    error = CheckResult(
        name="collector",
        status=CheckStatus.ERROR,
        reason="collector unavailable",
    )

    verdict = final_verdict([error])

    assert verdict["status"] == "ERROR"
    assert verdict["tool_errors"] == ["collector"]


def test_check_contract_retries_technical_exception_once() -> None:
    attempts = 0

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("parser crashed")

    result = run_check("collector", operation)

    assert result.status is CheckStatus.ERROR
    assert result.attempts == 2
    assert result.reason == "RuntimeError: parser crashed"


def test_load_lane_uses_only_the_fixed_v1_parameters(tmp_path: Path) -> None:
    lane = MemtierLoadLane(
        host="127.0.0.1",
        port=7000,
        primary_count=40,
        run_scope="run-a:arm-b",
        artifacts_dir=tmp_path,
    )
    paths = lane.paths("formal")
    assert paths.remote_dir is None
    command = lane.command(paths, duration_seconds=120)

    assert per_connection_rate(40) == 250
    assert "-c" in command and command[command.index("-c") + 1] == "1"
    assert "-t" in command and command[command.index("-t") + 1] == "1"
    assert "--pipeline=1" in command
    assert "--ratio=1:9" in command
    # memtier_benchmark refuses to start on a key-minimum of zero, so assert the
    # constraint rather than pinning whatever string the command happens to use.
    key_minimum = int(_option_value(command, "--key-minimum"))
    key_maximum = int(_option_value(command, "--key-maximum"))
    assert key_minimum > 0
    assert key_maximum > key_minimum
    assert key_maximum == 99999
    assert "--data-size=32" in command
    assert "--rate-limiting=250" in command
    assert "--key-prefix=vsl:load:run-a:arm-b:" in command
    assert not any("preload" in value or "warmup" in value for value in command)


class FakeMemtierProcess:
    def __init__(
        self,
        command: list[str],
        *,
        stdout: Any,
        stderr: Any,
        poll_code: int | None = None,
        stderr_text: str = "",
    ) -> None:
        self.command = command
        self.returncode: int | None = poll_code
        self._stdout = stdout
        self._stderr = stderr
        self._stderr_text = stderr_text

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        json_path = next(
            Path(value.split("=", 1)[1])
            for value in self.command
            if value.startswith("--json-out-file=")
        )
        hdr_prefix = next(
            Path(value.split("=", 1)[1])
            for value in self.command
            if value.startswith("--hdr-file-prefix=")
        )
        json_path.write_text('{"Totals": {"Ops/sec": 10000}}\n', encoding="utf-8")
        hdr_prefix.with_suffix(".hdr").write_text("hdr\n", encoding="utf-8")
        self._stderr.write(self._stderr_text)
        self._stderr.flush()
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


def _patch_memtier_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(load_module.shutil, "which", lambda _name: "/bin/memtier")
    monkeypatch.setattr(load_module.time, "sleep", lambda _seconds: None)


def test_memtier_preflight_checks_process_json_hdr_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_memtier_binary(monkeypatch)

    def popen(command: list[str], *, stdout: Any, stderr: Any, text: bool) -> FakeMemtierProcess:
        return FakeMemtierProcess(command, stdout=stdout, stderr=stderr)

    lane = MemtierLoadLane(
        host="127.0.0.1",
        port=7000,
        primary_count=10,
        run_scope="run",
        artifacts_dir=tmp_path,
        popen=popen,  # type: ignore[arg-type]
    )

    result = lane.preflight(duration_seconds=5.0)

    assert result["preflight_checks"] == {
        "cluster_connection": True,
        "process_stayed_running": True,
        "json_output": True,
        "hdr_output": True,
        "fd_or_connection_init_errors": False,
    }


def test_memtier_preflight_rejects_early_process_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_memtier_binary(monkeypatch)

    def popen(command: list[str], *, stdout: Any, stderr: Any, text: bool) -> FakeMemtierProcess:
        return FakeMemtierProcess(command, stdout=stdout, stderr=stderr, poll_code=2)

    lane = MemtierLoadLane(
        host="127.0.0.1",
        port=7000,
        primary_count=10,
        run_scope="run",
        artifacts_dir=tmp_path,
        popen=popen,  # type: ignore[arg-type]
    )

    with pytest.raises(CollectionError, match="exited before"):
        lane.preflight(duration_seconds=5.0)


def test_memtier_preflight_rejects_fd_or_connection_init_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_memtier_binary(monkeypatch)

    def popen(command: list[str], *, stdout: Any, stderr: Any, text: bool) -> FakeMemtierProcess:
        return FakeMemtierProcess(
            command,
            stdout=stdout,
            stderr=stderr,
            stderr_text="Too many open files while initializing cluster connections",
        )

    lane = MemtierLoadLane(
        host="127.0.0.1",
        port=7000,
        primary_count=10,
        run_scope="run",
        artifacts_dir=tmp_path,
        popen=popen,  # type: ignore[arg-type]
    )

    with pytest.raises(CollectionError, match="FD or connection initialization"):
        lane.preflight(duration_seconds=5.0)


def test_sentinel_keyspace_and_one_canary_per_shard() -> None:
    tags = slot_tags([0, 8192])
    canaries = [
        Canary("a" * 40, slot, f"vsl:sentinel:r:a:{{{tags[slot]}}}:s", "v")
        for slot in (0, 8192)
    ]

    assert [key_slot(canary.key) for canary in canaries] == [0, 8192]
    assert all(not canary.key.startswith("vsl:load:") for canary in canaries)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += max(seconds, 0.0)


def test_sentinel_prepares_once_and_fault_probe_requires_ten_rounds() -> None:
    clock = FakeClock()
    canary_a = Canary("a" * 40, 0, "vsl:sentinel:r:{tag-a}:a", "value-a")
    canary_b = Canary("b" * 40, 1, "vsl:sentinel:r:{tag-b}:b", "value-b")
    nodes = [
        SentinelNode(
            NodeEndpoint("p", "h", 1, "primary", "s0"),
            "1" * 40,
            "a" * 40,
            "primary",
            canary_a,
        ),
        SentinelNode(
            NodeEndpoint("r", "h", 2, "replica", "s0"),
            "2" * 40,
            "a" * 40,
            "replica",
            canary_a,
        ),
    ]
    values: dict[str, str] = {}

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        role = (
            [b"master", 0, []]
            if endpoint.port == 1
            else [b"slave", b"h", 1, b"connected", 0]
        )
        node_id = "1" * 40 if endpoint.port == 1 else "2" * 40
        return FakeConnection(
            {
                ("CLUSTER", "MYID"): node_id.encode(),
                ("ROLE",): role,
                ("READONLY",): "OK",
                ("SET", canary_a.key, canary_a.value): lambda: values.setdefault(
                    canary_a.key, canary_a.value
                )
                and "OK",
                ("GET", canary_a.key): lambda: values.get(canary_a.key),
            }
        )

    lane = SentinelLane(
        nodes,
        connection_factory=factory,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert lane.prepare()["replicas_confirmed"] == 1

    class Router:
        def get(self, key: str) -> str:
            return canary_a.value if key == canary_a.key else canary_b.value

        def close(self) -> None:
            return None

    result = lane.fault_probe(
        affected=canary_a,
        control=canary_b,
        recovery_deadline_seconds=2.0,
        fault_monotonic=clock.monotonic(),
        router=Router(),  # type: ignore[arg-type]
    )
    assert result["stable_rounds"] == 10
    assert len(result["samples"]) == 10
    assert result["rto_ms"] == 0


def test_fault_window_access_failures_are_transient_but_wrong_values_are_not() -> None:
    """§12.1: 故障转换期暂时访问失败…不逐样本判 `FAIL`.

    A passing exact-50 run recorded 443 and 455 per-sample `FAIL`s in the two
    frozen baselines - during a planned kill, with the lane's own verdict correctly
    `OK`. The sibling observer watching this same window already records
    `TRANSIENT` for the same class of error, so the vocabulary existed; only this
    probe disagreed.

    The exemption is for *access* failures. A value mismatch is a successful read
    of the wrong data, which no part of a planned kill excuses, so it stays `FAIL`
    - relabelling it too would erase the one finding this probe exists to catch.
    """

    clock = FakeClock()
    affected = Canary("a" * 40, 0, "vsl:sentinel:r:{tag-a}:a", "value-a")
    control = Canary("b" * 40, 1, "vsl:sentinel:r:{tag-b}:b", "value-b")
    lane = SentinelLane(
        [
            SentinelNode(
                NodeEndpoint("p", "h", 1, "primary", "s0"),
                "1" * 40,
                "a" * 40,
                "primary",
                affected,
            )
        ],
        connection_factory=lambda *_a, **_k: None,  # type: ignore[arg-type]
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    script: list[Any] = [
        SemanticFailure("could not reach a live seed"),  # the killed primary
        "wrong-value",                                   # read, and wrong
        SemanticFailure("still not reachable"),
    ]

    class Router:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, key: str) -> Any:
            if key == control.key:
                return control.value
            if self.calls < len(script):
                step = script[self.calls]
                self.calls += 1
                if isinstance(step, Exception):
                    raise step
                return step
            self.calls += 1
            return affected.value

        def close(self) -> None:
            return None

    result = lane.fault_probe(
        affected=affected,
        control=control,
        recovery_deadline_seconds=5.0,
        fault_monotonic=clock.monotonic(),
        router=Router(),  # type: ignore[arg-type]
    )

    labels = [sample["status"] for sample in result["samples"]]
    assert labels[0] == "TRANSIENT", "an unreachable canary during the kill"
    assert labels[1] == "FAIL", "a wrong value is not excused by the window"
    assert labels[2] == "TRANSIENT"
    assert labels[3:] == ["OK"] * 10
    # The lane's verdict was never wrong, and must not move: it is the streak and
    # the recovery time, both computed from `ok` rather than from this label.
    assert result["status"] == "OK"
    assert result["stable_rounds"] == 10
    # The wrong-value sample reset the streak, exactly as a non-OK sample should.
    assert result["samples"][1]["affected_value_ok"] is False
    assert result["samples"][1]["errors"] == {}


def test_sentinel_cluster_router_tries_live_seed_after_dead_first_seed() -> None:
    key = "vsl:sentinel:r:{tag-a}:a"
    calls: list[int] = []

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        calls.append(endpoint.port)
        if endpoint.port == 7000:
            return FakeConnection({("GET", key): ConnectionError("dead seed")})
        return FakeConnection({("GET", key): "value-a"})

    router = ClusterRouter(
        [Endpoint("127.0.0.1", 7000), Endpoint("127.0.0.1", 7001)],
        connection_factory=factory,  # type: ignore[arg-type]
    )

    assert router.get(key) == "value-a"
    assert calls == [7000, 7001]


def test_sentinel_sweep_reconnect_failure_does_not_block_other_nodes() -> None:
    clock = FakeClock()
    canary_a = Canary("a" * 40, 0, "vsl:sentinel:r:{tag-a}:a", "value-a")
    canary_b = Canary("b" * 40, 1, "vsl:sentinel:r:{tag-b}:b", "value-b")
    nodes = [
        SentinelNode(
            NodeEndpoint("p0", "h", 1, "primary", "s0"),
            "1" * 40,
            "a" * 40,
            "primary",
            canary_a,
        ),
        SentinelNode(
            NodeEndpoint("p1", "h", 2, "primary", "s1"),
            "2" * 40,
            "b" * 40,
            "primary",
            canary_b,
        ),
    ]
    calls: list[tuple[str, tuple[Any, ...]]] = []

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        logical = "p0" if endpoint.port == 1 else "p1"
        node_id = "1" * 40 if endpoint.port == 1 else "2" * 40
        canary = canary_a if endpoint.port == 1 else canary_b
        response: dict[tuple[Any, ...], Any] = {
            ("CLUSTER", "MYID"): node_id.encode(),
            ("ROLE",): [b"master", 0, []],
            ("GET", canary.key): RuntimeError("disconnect"),
        }
        if endpoint.port == 2:
            response[("GET", canary.key)] = canary.value
        connection = FakeConnection(response)
        original = connection.execute

        def execute(*command: Any) -> Any:
            calls.append((logical, tuple(command)))
            return original(*command)

        connection.execute = execute  # type: ignore[method-assign]
        return connection

    lane = SentinelLane(
        nodes,
        connection_factory=factory,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    with pytest.raises(SemanticFailure, match="p0"):
        lane.rolling_sweep(duration_seconds=0.02)

    assert ("p1", ("GET", canary_b.key)) in calls


def test_sentinel_expected_down_pauses_then_restore_reconnects() -> None:
    canary = Canary("a" * 40, 0, "vsl:sentinel:r:{tag-a}:a", "value-a")
    node = SentinelNode(
        NodeEndpoint("r0", "h", 1, "replica", "s0"),
        "1" * 40,
        "a" * 40,
        "replica",
        canary,
    )
    readonly_calls = 0

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        nonlocal readonly_calls
        connection = FakeConnection(
            {
                ("CLUSTER", "MYID"): b"1" * 40,
                ("ROLE",): [b"slave", b"h", 2, b"connected", 0],
                ("READONLY",): "OK",
                ("GET", canary.key): canary.value,
            }
        )
        original = connection.execute

        def execute(*command: Any) -> Any:
            nonlocal readonly_calls
            if command == ("READONLY",):
                readonly_calls += 1
            return original(*command)

        connection.execute = execute  # type: ignore[method-assign]
        return connection

    lane = SentinelLane([node], connection_factory=factory)
    lane.mark_expected_down("r0")
    with pytest.raises(SemanticFailure, match="paused"):
        lane.reconnect_and_confirm("r0")
    lane.mark_restore_started("r0")

    result = lane.reconnect_and_confirm("r0")

    assert result["status"] == "OK"
    assert result["last_connected_role"] == "replica"
    assert readonly_calls == 1
    assert any(event["event"] == "connected" for event in result["connection_events"])


def test_affected_shard_converges_after_two_500ms_rounds() -> None:
    clock = FakeClock()
    nodes = [
        NodeEndpoint("p", "h", 1, "primary", "s0"),
        NodeEndpoint("r", "h", 2, "replica", "s0"),
    ]

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        role = (
            [b"master", 0, []]
            if endpoint.port == 1
            else [b"slave", b"h", 1, b"connected", 0]
        )
        return FakeConnection(
            {
                ("ROLE",): role,
                ("CLUSTER", "INFO"): b"cluster_state:ok\r\n",
            }
        )

    observer = AffectedShardObserver(
        nodes,
        connection_factory=factory,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    result = observer.wait_for_convergence(
        deadline_seconds=2,
        full_validation=lambda: {"status": "OK"},
    )
    assert len(result["rounds"]) == 2
    assert result["round_interval_ms"] == 500


def _four_replica_survivors() -> list[NodeEndpoint]:
    """The affected shard of a 4-replica cluster once its primary is killed.

    Four survivors, dialled on published loopback ports, announcing a nodehost
    address to each other - the shape a Docker run actually has, and the shape
    no fixture had before four replicas made the two addresses distinguishable.
    """
    return [
        NodeEndpoint(
            "shard-0000-replica-00",
            "127.0.0.1",
            7401,
            "replica",
            "s0",
            announced_host="172.18.0.5",
        ),
        *[
            NodeEndpoint(
                f"shard-0000-replica-0{index}",
                "127.0.0.1",
                7401 + index,
                "replica",
                "s0",
                announced_host="172.18.0.5",
            )
            for index in (1, 2, 3)
        ],
    ]


def test_affected_shard_converges_when_replicas_name_the_announced_primary() -> None:
    """The promoted node is named by the address it announced, not the dialled one.

    A replica's ROLE reports its primary's cluster-announced address. Under
    Docker that is the nodehost's network address while the observer dials a
    published port on 127.0.0.1, so comparing the two literally can never hold.
    At one replica the affected shard has a single survivor, which promotes, so
    the replica branch is unreachable and the mismatch is invisible.
    """
    clock = FakeClock()
    nodes = _four_replica_survivors()

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        role = (
            [b"master", 0, []]
            if endpoint.port == 7401
            else [b"slave", b"172.18.0.5", 7401, b"connected", 0]
        )
        return FakeConnection(
            {
                ("ROLE",): role,
                ("CLUSTER", "INFO"): b"cluster_state:ok\r\n",
            }
        )

    observer = AffectedShardObserver(
        nodes,
        connection_factory=factory,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    result = observer.wait_for_convergence(
        deadline_seconds=2,
        full_validation=lambda: {"status": "OK"},
    )

    assert result["status"] == "OK"
    relationships = result["converged_relationship"]["relationships"]
    assert result["converged_relationship"]["primary"] == "shard-0000-replica-00"
    assert relationships == {
        "shard-0000-replica-00": "primary",
        "shard-0000-replica-01": "replica-of:shard-0000-replica-00",
        "shard-0000-replica-02": "replica-of:shard-0000-replica-00",
        "shard-0000-replica-03": "replica-of:shard-0000-replica-00",
    }


def _refuses_stray_replica(stray_host: bytes, stray_port: int) -> None:
    """One survivor names a primary that is not the promoted node.

    Guards the announced-address fix against degenerating into "any replica
    counts". The host and the port are exercised by separate callers because a
    case that strays in both cannot tell which half of the comparison is doing
    the work - the first version of this test strayed only in the port, and
    dropping the host comparison altogether left it green.
    """
    clock = FakeClock()
    nodes = _four_replica_survivors()

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        if endpoint.port == 7401:
            role: Any = [b"master", 0, []]
        elif endpoint.port == 7404:
            role = [b"slave", stray_host, stray_port, b"connected", 0]
        else:
            role = [b"slave", b"172.18.0.5", 7401, b"connected", 0]
        return FakeConnection(
            {
                ("ROLE",): role,
                ("CLUSTER", "INFO"): b"cluster_state:ok\r\n",
            }
        )

    observer = AffectedShardObserver(
        nodes,
        connection_factory=factory,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    with pytest.raises(SemanticFailure, match="two identical healthy 500ms rounds"):
        observer.wait_for_convergence(
            deadline_seconds=2,
            full_validation=lambda: {"status": "OK"},
        )


def test_affected_shard_refuses_a_replica_following_another_address() -> None:
    # A sibling attached to a primary on a different nodehost.
    _refuses_stray_replica(b"172.18.0.9", 7401)


def test_affected_shard_refuses_a_replica_following_another_port() -> None:
    # A sibling still replicating from the node that was killed.
    _refuses_stray_replica(b"172.18.0.5", 7400)


def test_node_endpoint_announced_host_is_the_peer_address() -> None:
    """`container_ip` is the peer address on both backends, so this needs no branch.

    It falls back to the dial host for an inventory that carries no separate
    announced address, which is what keeps every fixture built by hand honest.
    """
    announced = NodeEndpoint.from_inventory(
        {
            "logical_id": "shard-0000-primary",
            "host": "127.0.0.1",
            "client_port": 7400,
            "role": "primary",
            "shard_id": "shard-0000",
            "container_ip": "172.18.0.5",
        }
    )
    assert announced.host == "127.0.0.1"
    assert announced.announced_host == "172.18.0.5"

    without = NodeEndpoint.from_inventory(
        {
            "logical_id": "shard-0000-primary",
            "host": "10.0.0.4",
            "client_port": 7400,
            "role": "primary",
            "shard_id": "shard-0000",
        }
    )
    assert without.announced_host == "10.0.0.4"


def test_affected_shard_sampling_starts_other_observers_while_one_blocks() -> None:
    release = threading.Event()
    slow_started = threading.Event()
    fast_started = threading.Event()

    class Observer:
        def __init__(self, name: str, started: threading.Event, *, block: bool = False) -> None:
            self.name = name
            self.started = started
            self.block = block

        def sample_round(self) -> dict[str, Any]:
            self.started.set()
            if self.block:
                assert release.wait(timeout=1.0)
            return {"monotonic": 1.0, "rows": [], "candidate": None}

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            sample_affected_observers,
            {
                "slow": Observer("slow", slow_started, block=True),  # type: ignore[arg-type]
                "fast": Observer("fast", fast_started),  # type: ignore[arg-type]
            },
        )
        assert slow_started.wait(timeout=0.5)
        assert fast_started.wait(timeout=0.5)
        assert not future.done()
        release.set()

    assert [row["shard_id"] for row in future.result(timeout=1.0)] == ["fast", "slow"]


def test_exact_200_thirty_three_percent_affected_observers_all_start_same_round() -> None:
    release = threading.Event()
    started: list[str] = []
    condition = threading.Condition()

    class Observer:
        def __init__(self, name: str) -> None:
            self.name = name

        def sample_round(self) -> dict[str, Any]:
            with condition:
                started.append(self.name)
                condition.notify_all()
            assert release.wait(timeout=1.0)
            return {"monotonic": 1.0, "rows": [], "candidate": None}

    observers = {
        f"shard-{index:02d}": Observer(f"shard-{index:02d}")  # type: ignore[arg-type]
        for index in range(33)
    }

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(sample_affected_observers, observers)
        with condition:
            assert condition.wait_for(lambda: len(started) == 33, timeout=1.0)
        assert len(set(started)) == 33
        assert not future.done()
        release.set()
        rows = future.result(timeout=1.0)

    assert len(rows) == 33


def test_exact_200_thirty_three_percent_affected_command_budget_is_role_info_only() -> None:
    calls: list[tuple[int, tuple[str, ...]]] = []
    lock = threading.Lock()

    class RecordingConnection:
        def __init__(self, endpoint: Endpoint, _timeout: float) -> None:
            self.endpoint = endpoint

        def execute_many(self, commands: list[tuple[str, ...]]) -> list[Any]:
            with lock:
                calls.extend((self.endpoint.port, tuple(command)) for command in commands)
            assert commands == [("ROLE",), ("CLUSTER", "INFO")]
            return [
                [b"master", 0, []],
                b"cluster_state:ok\r\ncluster_slots_pfail:0\r\ncluster_slots_fail:0\r\n",
            ]

        def close(self) -> None:
            return None

    observers = {
        f"shard-{index:02d}": AffectedShardObserver(
            [
                NodeEndpoint(
                    f"replica-{index:02d}",
                    "127.0.0.1",
                    7300 + index,
                    "replica",
                    f"shard-{index:02d}",
                )
            ],
            connection_factory=lambda endpoint, timeout: RecordingConnection(endpoint, timeout),  # type: ignore[arg-type]
        )
        for index in range(33)
    }

    rows = sample_affected_observers(observers)

    assert len(rows) == 33
    assert len(calls) == 66
    assert sum(1 for _port, command in calls if command == ("ROLE",)) == 33
    assert sum(1 for _port, command in calls if command == ("CLUSTER", "INFO")) == 33
    assert all(command != ("CLUSTER", "COUNT-FAILURE-REPORTS") for _port, command in calls)


def _topology_observer(
    nodes: list[NodeEndpoint],
    responses: dict[int, dict[tuple[Any, ...], Any]],
    *,
    failures: dict[int, Exception],
    dialled: list[str],
) -> TopologyObserver:
    """A `TopologyObserver` whose named ports fail on connect."""

    port_to_id = {node.port: node.logical_id for node in nodes}

    def factory(endpoint: Endpoint, _timeout: float) -> Any:
        dialled.append(port_to_id[endpoint.port])
        if endpoint.port in failures:
            raise failures[endpoint.port]
        return FakeConnection(responses[endpoint.port])

    return TopologyObserver(nodes, observer_count=3, connection_factory=factory)


def test_a_transiently_unreadable_observer_is_replaced_from_its_own_az() -> None:
    """Substitution, not quorum, and not a cross-AZ fallback.

    The fixture's observers are p0 (az-a), p1 (az-b) and r0 (az-b). Failing p0
    must be answered by az-a's other node, r1 - never by an az-b node, which
    would answer a question about the wrong part of the cluster.
    """

    nodes, responses = _cluster_fixture()
    dialled: list[str] = []
    observer = _topology_observer(
        nodes,
        responses,
        failures={7000: TimeoutError("timed out")},
        dialled=dialled,
    )

    result = observer.run()

    assert result["status"] == "OK"
    assert result["observer_count"] == 3
    assert [view["logical_id"] for view in result["observers"]] == ["r1", "p1", "r0"]
    # The substitute is in the failed observer's own AZ.
    assert {view["az_id"] for view in result["observers"]} == {"az-a", "az-b"}
    assert dialled[:2] == ["p0", "r1"]

    # And the run says so, rather than looking like a clean three-observer read.
    substitutions = result["observer_substitutions"]
    assert len(substitutions) == 1
    assert substitutions[0]["planned_logical_id"] == "p0"
    assert substitutions[0]["substituted_logical_id"] == "r1"
    assert substitutions[0]["az_id"] == "az-a"
    assert substitutions[0]["attempts"][0]["logical_id"] == "p0"
    assert "TimeoutError" in substitutions[0]["attempts"][0]["error"]
    assert result["observers"][0]["planned_logical_id"] == "p0"


def test_an_unreadable_az_fails_closed_rather_than_letting_the_others_concur() -> None:
    """The whole point of substitution over quorum.

    Under an AZ partition the observer that is lost is *correlated* with the
    event the redundancy exists to catch, so tolerating a minority would record
    "cannot see az-a" as "az-a concurs". Exhausting az-a must raise.
    """

    nodes, responses = _cluster_fixture()
    dialled: list[str] = []
    observer = _topology_observer(
        nodes,
        responses,
        # Both az-a nodes: p0 (7000) and r1 (7003).
        failures={
            7000: TimeoutError("timed out"),
            7003: ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused"),
        },
        dialled=dialled,
    )

    with pytest.raises(SemanticFailure) as caught:
        observer.run()

    message = str(caught.value)
    assert "no readable CLUSTER SHARDS observer" in message
    assert "az-a" in message
    # It asked every node az-a had, and it never asked an az-b node in az-a's place.
    assert dialled == ["p0", "r1"]


def test_an_unreadable_az_is_not_covered_by_a_spare_node_in_another_az() -> None:
    """The fail-open hole, stated where the fixture can actually express it.

    The four-node fixture cannot: exhausting az-a there leaves no *unchosen*
    node anywhere, so a cross-AZ fallback would raise for the right reason by
    accident. Measured - a mutation widening `_substitutes_for` to any unchosen
    node passed that test. This one gives az-b two spare nodes, so a cross-AZ
    fallback would find one, answer, and report a healthy three-observer read of
    a cluster half of which could not be reached.
    """

    nodes, responses = _cluster_fixture()
    ids = [f"{index + 1:040x}" for index in range(4)]
    spares = [
        NodeEndpoint("r2", "127.0.0.1", 7004, "replica", "s0", "az-b", "h4"),
        NodeEndpoint("r3", "127.0.0.1", 7005, "replica", "s1", "az-b", "h5"),
    ]
    for spare in spares:
        responses[spare.port] = {("CLUSTER", "SHARDS"): _shards(ids)}
    all_nodes = nodes + spares

    dialled: list[str] = []
    port_to_id = {node.port: node.logical_id for node in all_nodes}
    failed_ports = {7000, 7003}  # p0 and r1, the whole of az-a

    def factory(endpoint: Endpoint, _timeout: float) -> Any:
        dialled.append(port_to_id[endpoint.port])
        if endpoint.port in failed_ports:
            raise TimeoutError("timed out")
        return FakeConnection(responses[endpoint.port])

    observer = TopologyObserver(all_nodes, observer_count=3, connection_factory=factory)

    with pytest.raises(SemanticFailure) as caught:
        observer.run(expected_node_count=4)

    assert "az-a" in str(caught.value)
    # The spares exist and are readable; they were never asked, because they are
    # in the wrong AZ to answer a question about az-a.
    assert "r2" not in dialled
    assert "r3" not in dialled


def test_a_substitute_leaves_the_failed_placement_before_the_failed_az() -> None:
    """The placement is the fault domain, so it is the least likely to answer.

    `isolate_nodehost` isolates a whole `placement_id` and the preflight refuses
    a shard whose members share one, so a node that cannot be reached most often
    means its whole nodehost is gone. Preferring its own placement would dial
    every node on a dead nodehost before trying a live one. Same-placement nodes
    stay as a fallback, because a single node can also fail alone.
    """

    nodes, responses = _cluster_fixture()
    ids = [f"{index + 1:040x}" for index in range(4)]
    # az-a gains a sibling on p0's own placement, and one on a third placement.
    extra = [
        NodeEndpoint("p0b", "127.0.0.1", 7004, "replica", "s0", "az-a", "h0"),
        NodeEndpoint("p0c", "127.0.0.1", 7005, "replica", "s1", "az-a", "h9"),
    ]
    for node in extra:
        responses[node.port] = {("CLUSTER", "SHARDS"): _shards(ids)}
    all_nodes = nodes + extra

    dialled: list[str] = []
    port_to_id = {node.port: node.logical_id for node in all_nodes}

    def factory(endpoint: Endpoint, _timeout: float) -> Any:
        dialled.append(port_to_id[endpoint.port])
        if endpoint.port == 7000:
            raise TimeoutError("timed out")
        return FakeConnection(responses[endpoint.port])

    observer = TopologyObserver(all_nodes, observer_count=3, connection_factory=factory)
    result = observer.run(expected_node_count=4)

    substitution = result["observer_substitutions"][0]
    assert substitution["planned_logical_id"] == "p0"
    # r1 (az-a, h3) and p0c (az-a, h9) are both off p0's placement; p0b shares it
    # and must not be tried before them.
    assert substitution["substituted_logical_id"] in {"r1", "p0c"}
    assert "p0b" not in dialled


def test_the_substitution_walk_is_bounded_rather_than_the_whole_az() -> None:
    """An uncapped walk is minutes of serial dialling, not a fallback.

    Every node in an AZ is a candidate in principle - 640 of them at 1280 nodes -
    and at a 5s connect timeout that is ~53 minutes for one slot, inside gates
    whose whole budget used to be a single 5s dial. It also destroys
    contemporaneity: the three views are compared for equality and "observers
    disagree" is a *permanent* failure, so a long walk over a converging cluster
    turns a transient into a false permanent disagreement.
    """

    ids = [f"{index + 1:040x}" for index in range(4)]
    nodes, responses = _cluster_fixture()
    # az-a gains twenty more nodes on twenty distinct placements.
    spares = [
        NodeEndpoint(f"a{n}", "127.0.0.1", 7100 + n, "replica", "s0", "az-a", f"ha{n}")
        for n in range(20)
    ]
    for spare in spares:
        responses[spare.port] = {("CLUSTER", "SHARDS"): _shards(ids)}
    all_nodes = nodes + spares

    dialled: list[str] = []
    port_to_id = {node.port: node.logical_id for node in all_nodes}

    def factory(endpoint: Endpoint, _timeout: float) -> Any:
        dialled.append(port_to_id[endpoint.port])
        # Every az-a node is dark; az-b answers.
        if endpoint.port == 7000 or endpoint.port == 7003 or endpoint.port >= 7100:
            raise TimeoutError("timed out")
        return FakeConnection(responses[endpoint.port])

    observer = TopologyObserver(all_nodes, observer_count=3, connection_factory=factory)

    with pytest.raises(SemanticFailure):
        observer.run(expected_node_count=4)

    # The planned observer plus at most MAX_OBSERVER_SUBSTITUTIONS replacements,
    # not the twenty-two az-a nodes that exist.
    assert len(dialled) == 1 + cluster_module.MAX_OBSERVER_SUBSTITUTIONS


def test_a_substitute_prefers_a_placement_no_other_view_came_from() -> None:
    """Substitution must not quietly collapse the spread it is replacing.

    `choose_topology_observers` spreads across `az_id` and `placement_id`, so a
    substitute landing on a placement another view already came from would leave
    two of three views inside one fault domain - the redundancy still reporting
    three observers while covering two.

    The failing observer here is the *third* slot, deliberately. An earlier draft
    failed the first one, where nothing has answered yet and the preference is
    vacuous - measured, three separate mutations to the ordering all passed it.
    """

    ids = [f"{index + 1:040x}" for index in range(4)]
    nodes, responses = _cluster_fixture()
    # Observers are p0 (az-a, h0), p1 (az-b, h1), r0 (az-b, h2). r0 fails last,
    # by which point h0 and h1 have answered. The three az-b candidates are
    # listed worst-first, so a missing rule shows up as the wrong pick rather
    # than as luck: h2 is r0's own dead placement, h1 is already covered by p1,
    # and h8 is the only one that keeps three distinct fault domains.
    spares = [
        NodeEndpoint("sib", "127.0.0.1", 7104, "replica", "s0", "az-b", "h2"),
        NodeEndpoint("dup", "127.0.0.1", 7105, "replica", "s1", "az-b", "h1"),
        NodeEndpoint("fresh", "127.0.0.1", 7106, "replica", "s0", "az-b", "h8"),
    ]
    for spare in spares:
        responses[spare.port] = {("CLUSTER", "SHARDS"): _shards(ids)}
    all_nodes = nodes + spares

    dialled: list[str] = []
    port_to_id = {node.port: node.logical_id for node in all_nodes}

    def factory(endpoint: Endpoint, _timeout: float) -> Any:
        dialled.append(port_to_id[endpoint.port])
        if endpoint.port == 7002:  # r0
            raise TimeoutError("timed out")
        return FakeConnection(responses[endpoint.port])

    observer = TopologyObserver(all_nodes, observer_count=3, connection_factory=factory)
    result = observer.run(expected_node_count=4)

    substitution = result["observer_substitutions"][0]
    assert substitution["planned_logical_id"] == "r0"
    assert substitution["substituted_logical_id"] == "fresh"
    assert substitution["placement_id"] == "h8"

    placements = [view["placement_id"] for view in result["observers"]]
    assert sorted(placements) == ["h0", "h1", "h8"]
    assert len(set(placements)) == 3
    # r0's own placement is the fault domain that just failed; it is tried last,
    # and here never, because a better candidate answered.
    assert "sib" not in dialled
    assert "dup" not in dialled


def test_observers_that_disagree_are_a_disagreement_and_not_another_substitution() -> None:
    """Substitution triggers on transport only, so it cannot paper over a split.

    A substitute that answers with a *different* topology has been reached; that
    is a real observation of two vantage points disagreeing, and asking a fourth
    node until one agrees is exactly the fail-open behaviour this design refuses.
    """

    ids = [f"{index + 1:040x}" for index in range(4)]
    nodes, responses = _cluster_fixture()
    # r0's view disagrees: one shard reports a different node id.
    divergent = _shards([ids[0], ids[1], ids[2], f"{99:040x}"])
    responses[nodes[2].port][("CLUSTER", "SHARDS")] = divergent

    dialled: list[str] = []
    port_to_id = {node.port: node.logical_id for node in nodes}

    def factory(endpoint: Endpoint, _timeout: float) -> Any:
        dialled.append(port_to_id[endpoint.port])
        return FakeConnection(responses[endpoint.port])

    observer = TopologyObserver(nodes, observer_count=3, connection_factory=factory)

    with pytest.raises(SemanticFailure) as caught:
        observer.run()

    assert "disagree" in str(caught.value)
    # Three dials, one per planned observer: nothing was substituted.
    assert dialled == ["p0", "p1", "r0"]


def test_one_node_cannot_answer_for_two_observer_slots() -> None:
    """Otherwise three views could be three reads of the same node."""

    ids = [f"{index + 1:040x}" for index in range(4)]
    nodes, responses = _cluster_fixture()
    spare = NodeEndpoint("spare", "127.0.0.1", 7106, "replica", "s0", "az-b", "h6")
    responses[spare.port] = {("CLUSTER", "SHARDS"): _shards(ids)}
    all_nodes = nodes + [spare]

    dialled: list[str] = []
    port_to_id = {node.port: node.logical_id for node in all_nodes}

    def factory(endpoint: Endpoint, _timeout: float) -> Any:
        dialled.append(port_to_id[endpoint.port])
        # Both az-b planned observers fail, so both slots want an az-b substitute.
        if endpoint.port in {7001, 7002}:
            raise TimeoutError("timed out")
        return FakeConnection(responses[endpoint.port])

    observer = TopologyObserver(all_nodes, observer_count=3, connection_factory=factory)

    # az-b offers exactly one readable spare, so the first slot takes it and the
    # second has nothing left - which must fail closed rather than reuse it.
    with pytest.raises(SemanticFailure):
        observer.run(expected_node_count=4)

    assert dialled.count("spare") == 1


def test_a_non_transient_observer_failure_is_not_substituted() -> None:
    """Substitution is for transport failures only.

    Anything else - a parse fault, a bug, an error reply - is a real answer or a
    real defect, and asking a different node would hide it behind a healthy view.
    """

    nodes, responses = _cluster_fixture()
    dialled: list[str] = []
    observer = _topology_observer(
        nodes,
        responses,
        failures={7000: RespCommandError("ERR unknown command 'CLUSTER|SHARDS'")},
        dialled=dialled,
    )

    with pytest.raises(SemanticFailure) as caught:
        observer.run()

    assert "p0 CLUSTER SHARDS failed" in str(caught.value)
    assert dialled == ["p0"]


def test_a_clean_read_records_no_substitution() -> None:
    nodes, responses = _cluster_fixture()
    dialled: list[str] = []
    observer = _topology_observer(nodes, responses, failures={}, dialled=dialled)

    result = observer.run()

    assert result["observer_substitutions"] == []
    assert [view["logical_id"] for view in result["observers"]] == ["p0", "p1", "r0"]
    assert all(
        view["planned_logical_id"] == view["logical_id"] for view in result["observers"]
    )
    assert dialled == ["p0", "p1", "r0"]


def test_which_observation_failures_are_the_collectors_own() -> None:
    """§12.1's boundary, in the direction that matters.

    Valkey refusing a connection, timing out, or answering wrongly is a
    successful observation of an unhealthy cluster and stays a FAIL. Only a local
    failure is the collector's - and the one that actually happened here is
    ephemeral-port exhaustion at 200 nodes.
    """

    refused = ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")
    exhausted = OSError(errno.EADDRNOTAVAIL, "Can't assign requested address")

    assert is_collection_failure(exhausted) is True
    assert is_collection_failure(OSError(errno.EMFILE, "Too many open files")) is True
    assert is_collection_failure(CollectionError("cannot write evidence")) is True

    # Every one of these is the cluster's problem, not the tool's.
    assert is_collection_failure(refused) is False
    assert is_collection_failure(TimeoutError("timed out")) is False
    assert is_collection_failure(EOFError("Valkey connection closed")) is False
    assert is_collection_failure(SemanticFailure("ROLE disagrees")) is False
    # Unplaceable failures stay FAIL: calling a real failure a tool error is the
    # direction that loses a finding.
    assert is_collection_failure(RuntimeError("something else")) is False


def test_which_failures_are_worth_asking_again() -> None:
    """The retry-eligibility axis, which is deliberately not §12.1's axis.

    The two predicates disagree on a timeout on purpose: a timed-out node was
    observed to not answer (semantic, per §12.1) *and* asking again is
    reasonable. This pins both halves together so a later change cannot quietly
    collapse one axis into the other.
    """

    transient = [
        TimeoutError("timed out"),
        socket.timeout("timed out"),
        ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused"),
        ConnectionResetError(errno.ECONNRESET, "Connection reset by peer"),
        BrokenPipeError(errno.EPIPE, "Broken pipe"),
        EOFError("Valkey connection closed"),
        RespProtocolError("truncated RESP line"),
        RespProtocolError("truncated RESP bulk string"),
    ]
    for exc in transient:
        assert is_transient_transport_error(exc) is True, type(exc).__name__

    # An error *reply* means the node was reached and answered. Asking again
    # neither changes the answer nor is safe for the mutations that produce it.
    assert is_transient_transport_error(RespCommandError("ERR unknown node")) is False
    assert is_transient_transport_error(ValkeyErrorReply("ERR node must be empty")) is False
    assert is_transient_transport_error(SemanticFailure("ROLE disagrees")) is False

    # Local resource exhaustion is the collector's own and is *not* retried:
    # re-entering a 1024-way fan-out that has run out of file descriptors makes
    # it worse. This is the one input the two predicates classify in opposite
    # directions to a timeout, and it is the direction that matters.
    exhausted = OSError(errno.EADDRNOTAVAIL, "Can't assign requested address")
    assert is_collection_failure(exhausted) is True
    assert is_transient_transport_error(exhausted) is False
    assert is_transient_transport_error(OSError(errno.EMFILE, "Too many open files")) is False

    # Unrecognised failures are not retried, mirroring `is_collection_failure`'s
    # refusal to place what it cannot place.
    assert is_transient_transport_error(RuntimeError("something else")) is False
    assert is_transient_transport_error(CollectionError("cannot write evidence")) is False

    # §12.1 stays exactly where it was. A timeout is still semantic.
    assert is_collection_failure(TimeoutError("timed out")) is False


def test_no_thread_pool_budget_timeout_can_reach_the_retry_predicate() -> None:
    """The confusion that killed a real 1280-node run at 448s, pinned closed.

    On Python 3.11+ `concurrent.futures.TimeoutError` *is* the builtin
    `TimeoutError`, so `is_transient_transport_error` answers True for a thread
    pool's budget being blown - which must never be retried, because the budget
    is already spent. What makes that safe is a property of the call sites rather
    than of the type: only two producers exist, `_bounded_parallel` converts what
    its `as_completed` raises into a `DockerRuntimeError`, and the one
    `Future.result(timeout=...)` sits in a management teardown that nothing
    retries.

    Both halves are asserted, because the first alone would be a statement about
    the Python version rather than about this product. The sweep is over the
    whole package and deliberately lists both producers by line, so that adding a
    third - the way this could actually regress - fails here rather than in a
    paid run.

    Do **not** assert that a `FutureTimeoutError` is non-transient. That passes
    on 3.9 and fails on 3.12, which is the version-divergent trap this whole test
    exists to keep closed.

    **This test is vacuous on Python 3.9**, where the two classes differ and the
    first assertion holds for an uninteresting reason. The workstation is 3.9 and
    the controller 3.12, so mutation-check it on the controller.
    """

    if sys.version_info >= (3, 11):
        assert FutureTimeoutError is TimeoutError
        assert is_transient_transport_error(FutureTimeoutError("budget")) is True

    # Sweep the whole package, not one module: the claim is that no *third*
    # producer of a futures timeout appears anywhere, and a single-module scan
    # would have missed the second one - `Future.result(timeout=...)`, which
    # raises through a different API than `as_completed`.
    package = Path(docker_runtime.__file__).parent.parent
    producers: list[str] = []
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not any(keyword.arg == "timeout" for keyword in node.keywords):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "as_completed":
                producers.append(f"{path.name} as_completed")
            elif isinstance(func, ast.Attribute) and func.attr == "result":
                producers.append(f"{path.name} .result")

    # Identified by file and call kind rather than by line, so that editing the
    # module above them does not fail this - only a genuinely new producer does.
    assert sorted(producers) == [
        "docker_runtime.py .result",
        "docker_runtime.py as_completed",
    ], producers

    # And it converts what that raises, so the predicate never sees it.
    def never_finishes(_item: int) -> None:
        time.sleep(3.0)

    with pytest.raises(docker_runtime.DockerRuntimeError) as caught:
        docker_runtime._bounded_parallel(
            [1, 2], never_finishes, parallelism=2, timeout=0.5, label="pool"
        )
    assert is_transient_transport_error(caught.value) is False


def test_a_failed_light_probe_row_states_which_kind_it_was() -> None:
    nodes, _responses = _cluster_fixture()

    def refuse(_endpoint: Endpoint, _timeout: float) -> Any:
        raise ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")

    def exhaust(_endpoint: Endpoint, _timeout: float) -> Any:
        raise OSError(errno.EADDRNOTAVAIL, "Can't assign requested address")

    refused_row = LightClusterProbe(
        nodes[:1], connection_factory=refuse
    ).observe_node(nodes[0])
    exhausted_row = LightClusterProbe(
        nodes[:1], connection_factory=exhaust
    ).observe_node(nodes[0])

    assert refused_row["status"] == "FAIL"
    assert refused_row["failure_kind"] == "semantic"
    assert exhausted_row["failure_kind"] == "tool"
    # The rendered message is kept as well: the kind is what consumers act on,
    # the message is what a person reads.
    assert "Can't assign requested address" in exhausted_row["error"]


def test_actuator_failure_is_a_collection_error() -> None:
    recorder = ActuatorRecorder(target="p0", action="kill")
    recorder.start()
    recorder.sent()
    with pytest.raises(CollectionError, match="could not execute"):
        recorder.complete(result="permission denied")
    # The record is complete before the raise, so a caller can still report it.
    assert recorder.record["result"] == "permission denied"
    assert recorder.record["action_completed"] is not None


@pytest.mark.parametrize(
    ("kill_result", "expected_status"), [("OK", "PASS"), ("permission denied", "ERROR")]
)
def test_the_actuator_row_is_written_on_the_path_where_the_kill_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kill_result: str,
    expected_status: str,
) -> None:
    """§9.1 wants the action's result recorded, and it matters most when it is
    not OK.

    The row that carries the record used to be appended after
    `ActuatorRecorder.complete`, which raises for a non-OK result - so §9.1's
    `result` was persisted only when there was nothing to report, and the row's
    status was a literal `"PASS"` for the same reason.
    """

    from valkey_scale_lab.runtime import docker_runtime

    class FakeCanary:
        key = "canary"
        value = "v"
        slot = 0

    class FakeSentinelNode:
        def __init__(self, shard_id: str) -> None:
            self.shard_id = shard_id
            self.canary = FakeCanary()

    closed: list[str] = []
    expected_down: list[str] = []

    class FakeSentinel:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def prepare(self) -> dict[str, Any]:
            return {"status": "OK"}

        def mark_expected_down(self, logical_id: str) -> None:
            expected_down.append(logical_id)

        def close(self) -> None:
            closed.append("closed")

    class FakeBackend:
        def kill_node(self, node: dict[str, Any]) -> list[dict[str, Any]]:
            return [
                {
                    "argv": ["kill", "-9", str(node.get("pid", 1))],
                    "result": kill_result,
                }
            ]

    monkeypatch.setattr(
        docker_runtime,
        "build_sentinel_nodes",
        lambda *_a, **_k: [FakeSentinelNode("shard-0000"), FakeSentinelNode("shard-0001")],
    )
    monkeypatch.setattr(docker_runtime, "SentinelLane", FakeSentinel)
    monkeypatch.setattr(
        docker_runtime, "_advertised_endpoint_resolver", lambda _nodes: (lambda e: e)
    )
    # The kill is the last thing this test needs to reach; everything after it
    # observes recovery, which is not what §9.1's record is about.
    monkeypatch.setattr(
        docker_runtime,
        "AffectedShardObserver",
        lambda *_a, **_k: (_ for _ in ()).throw(
            docker_runtime.DockerRuntimeError("stop after the actuator")
        ),
    )

    nodes = [
        {"logical_id": "shard-0000-primary", "shard_id": "shard-0000", "pid": 11},
        {"logical_id": "shard-0000-replica-00", "shard_id": "shard-0000", "pid": 12},
        {"logical_id": "shard-0001-primary", "shard_id": "shard-0001", "pid": 13},
    ]
    inventory = [
        NodeEndpoint(
            logical_id=node["logical_id"],
            host="127.0.0.1",
            port=7000 + index,
            expected_role="primary",
            expected_shard=node["shard_id"],
        )
        for index, node in enumerate(nodes)
    ]
    initial_validation = {
        "light_validation": {
            "nodes": [
                {
                    "logical_id": node["logical_id"],
                    "myslots": {
                        "node-id": f"id-{node['logical_id']}",
                        "shard-id": node["shard_id"],
                    },
                }
                for node in nodes
            ]
        }
    }
    command_log: list[dict[str, Any]] = []

    with pytest.raises(Exception):
        docker_runtime._run_scalable_primary_kill_failover(
            capability_id="LOCAL_FULL_FLOW",
            scenario="review",
            run_id="review-actuator",
            operation_id="op-failover",
            nodes=nodes,
            inventory=inventory,
            initial_validation=initial_validation,
            target=nodes[0],
            command_log=command_log,
            artifacts=tmp_path,
            backend=FakeBackend(),
        )

    rows = [row for row in command_log if row["command_kind"] == "actuator_kill_primary"]
    assert len(rows) == 1, "the actuator row must exist on both paths"
    row = rows[0]
    assert row["status"] == expected_status
    record = json.loads(row["stdout_tail"])
    # §9.1's six fields, all present, on both paths.
    assert set(record) == {
        "target",
        "action",
        "action_start",
        "signal_or_request_sent",
        "action_completed",
        "result",
    }
    assert record["target"] == "shard-0000-primary"
    assert record["action"] == "kill-primary"
    assert record["result"] == kill_result
    assert all(
        record[field] is not None
        for field in ("action_start", "signal_or_request_sent", "action_completed")
    )
    assert isinstance(row["duration_ms"], float)
    if kill_result == "OK":
        assert row["error_type"] == ""
    else:
        assert row["error_type"] == "CollectionError"
        assert kill_result in row["stderr_tail"]
    assert expected_down == ["shard-0000-primary"]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_resource_sampler_reads_only_fixed_proc_fields_and_analyzes_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    _write(
        proc / "stat",
        "cpu 10 1 5 100 2 1 1 0 0 0\nprocs_running 2\nprocs_blocked 1\n",
    )
    _write(
        proc / "meminfo",
        "MemTotal: 1000 kB\nMemAvailable: 800 kB\n"
        "SwapTotal: 100 kB\nSwapFree: 90 kB\n",
    )
    _write(
        proc / "net" / "dev",
        "Inter-| Receive | Transmit\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n"
        "eth0: 100 10 1 2 0 0 0 0 200 20 3 4 0 0 0 0\n",
    )
    _write(proc / "123" / "stat", "123 (valkey server) S " + " ".join(["0"] * 30) + "\n")
    (proc / "123" / "fd").mkdir(parents=True)
    (proc / "123" / "fd" / "0").touch()
    monkeypatch.setattr(
        os,
        "readlink",
        lambda *_args: (_ for _ in ()).throw(AssertionError("FD sampling must not readlink")),
    )
    _write(cgroup / "cpu.max", "100000 100000\n")
    _write(cgroup / "cpu.stat", "usage_usec 10\nnr_throttled 1\nthrottled_usec 2\n")
    _write(cgroup / "memory.current", "100\n")
    _write(cgroup / "memory.max", "1000\n")
    _write(cgroup / "memory.events", "oom 0\noom_kill 0\n")
    sampler = LocalResourceSampler(
        sampler_id="host-a",
        processes=[ProcessSpec("node-a", 123)],
        proc_root=proc,
        cgroup_root=cgroup,
    )

    static = sampler.static()
    samples = [sampler.host_sample(), sampler.process_sample()]
    analysis = analyze_resource_samples(static, samples)

    assert static["network_interfaces"] == ["eth0"]
    assert samples[0]["network"]["eth0"]["rx_drops"] == 2
    assert samples[1]["processes"][0]["fd_count"] == 1
    assert analysis["status"] == "OK"
    assert analysis["processes"]["node-a"]["fd_count_max"] == 1
    serialized = json.dumps(samples)
    assert "CLUSTER" not in serialized
    assert "valkey-cli" not in serialized


def test_resource_runner_host_sampling_continues_while_process_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(resources_module, "HOST_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(resources_module, "PROCESS_INTERVAL_SECONDS", 0.05)
    release_process = threading.Event()
    process_started = threading.Event()
    host_condition = threading.Condition()
    host_count = 0

    class BlockingSampler:
        sampler_id = "host-a"

        def static(self) -> dict[str, Any]:
            return {"sampler_id": self.sampler_id}

        def host_sample(self) -> dict[str, Any]:
            nonlocal host_count
            with host_condition:
                host_count += 1
                host_condition.notify_all()
                count = host_count
            return {"kind": "host", "monotonic": count}

        def process_sample(self) -> dict[str, Any]:
            process_started.set()
            assert release_process.wait(timeout=1.0)
            return {"kind": "process", "monotonic": 1.0, "processes": []}

    runner = ResourceSamplerRunner(
        BlockingSampler(),  # type: ignore[arg-type]
        host_interval=0.01,
        process_interval=0.05,
    )
    runner.start()
    assert process_started.wait(timeout=0.5)
    with host_condition:
        assert host_condition.wait_for(lambda: host_count >= 3, timeout=0.5)
    release_process.set()
    document = runner.stop()

    assert sum(1 for sample in document["samples"] if sample["kind"] == "host") >= 3
    assert any(sample["kind"] == "process" for sample in document["samples"])


def test_resource_runner_process_rounds_do_not_overlap_or_catch_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(resources_module, "HOST_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(resources_module, "PROCESS_INTERVAL_SECONDS", 0.05)
    release_first = threading.Event()
    first_started = threading.Event()
    first_finished = threading.Event()
    condition = threading.Condition()
    process_calls = 0
    active_process_calls = 0
    overlap_detected = False

    class SlowProcessSampler:
        sampler_id = "host-a"

        def static(self) -> dict[str, Any]:
            return {"sampler_id": self.sampler_id}

        def host_sample(self) -> dict[str, Any]:
            return {"kind": "host", "monotonic": 1.0}

        def process_sample(self) -> dict[str, Any]:
            nonlocal active_process_calls, overlap_detected, process_calls
            with condition:
                process_calls += 1
                active_process_calls += 1
                if active_process_calls > 1:
                    overlap_detected = True
                condition.notify_all()
                call_number = process_calls
            if call_number == 1:
                first_started.set()
                assert release_first.wait(timeout=1.0)
            with condition:
                active_process_calls -= 1
                condition.notify_all()
            if call_number == 1:
                first_finished.set()
            return {"kind": "process", "monotonic": call_number, "processes": []}

    runner = ResourceSamplerRunner(
        SlowProcessSampler(),  # type: ignore[arg-type]
        host_interval=0.01,
        process_interval=0.05,
    )
    runner.start()
    assert first_started.wait(timeout=0.5)
    with condition:
        assert not condition.wait_for(lambda: process_calls > 1, timeout=0.08)
        assert process_calls == 1
        assert active_process_calls == 1
    release_first.set()
    assert first_finished.wait(timeout=0.5)
    with condition:
        assert not condition.wait_for(lambda: process_calls > 1, timeout=0.02)
    document = runner.stop()

    assert not overlap_detected
    assert sum(1 for sample in document["samples"] if sample["kind"] == "process") == 1
    assert runner._host_thread is not None and not runner._host_thread.is_alive()
    assert runner._process_thread is not None and not runner._process_thread.is_alive()


def test_process_sampling_is_sequential_complete_and_preserves_expected_gone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes = [ProcessSpec(f"node-{index:02d}", 10_000 + index) for index in range(25)]
    expected_gone = processes[-1]
    fd_order: list[int] = []
    sampler = LocalResourceSampler(
        sampler_id="host-a",
        processes=processes,
        proc_root=tmp_path,
        cgroup_root=tmp_path,
        expected_gone_processes=[
            ExpectedGoneProcess(expected_gone.logical_id, expected_gone.pid)
        ],
        expected_gone_active=lambda: True,
    )

    def process_stat(process: ProcessSpec) -> dict[str, Any]:
        return {
            "state": "S",
            "user_cpu_ticks": 1,
            "system_cpu_ticks": 2,
            "start_time_ticks": process.pid * 10,
            "rss_bytes": 4096,
        }

    def fd_count(pid: int) -> int:
        fd_order.append(pid)
        if pid == expected_gone.pid:
            raise CollectionError("planned process is gone")
        return 3

    monkeypatch.setattr(sampler, "_process_stat", process_stat)
    monkeypatch.setattr(sampler, "_fd_count", fd_count)

    sample = sampler.process_sample()

    assert isinstance(sampler.processes, tuple)
    assert [
        (row["logical_id"], row["pid"]) for row in sample["processes"]
    ] == [(process.logical_id, process.pid) for process in processes]
    assert len(sample["processes"]) == 25
    assert len({(row["logical_id"], row["pid"]) for row in sample["processes"]}) == 25
    assert fd_order == [process.pid for process in processes]
    assert sample["processes"][-1]["status"] == "EXPECTED_GONE"

    failing = LocalResourceSampler(
        sampler_id="host-b",
        processes=[ProcessSpec("node-bad", 20_000)],
        proc_root=tmp_path,
        cgroup_root=tmp_path,
    )
    monkeypatch.setattr(failing, "_process_stat", process_stat)
    monkeypatch.setattr(
        failing,
        "_fd_count",
        lambda _pid: (_ for _ in ()).throw(CollectionError("unexpected failure")),
    )
    with pytest.raises(CollectionError, match="unexpected failure"):
        failing.process_sample()


def test_resource_sampler_rejects_pid_identity_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = ProcessSpec("node-a", 123)
    sampler = LocalResourceSampler(
        sampler_id="host-a",
        processes=[process],
        proc_root=tmp_path,
        cgroup_root=tmp_path,
    )
    start_time = 10

    def process_stat(_process: ProcessSpec) -> dict[str, Any]:
        return {
            "state": "S",
            "user_cpu_ticks": 1,
            "system_cpu_ticks": 2,
            "start_time_ticks": start_time,
            "rss_bytes": 4096,
        }

    monkeypatch.setattr(sampler, "_process_stat", process_stat)
    monkeypatch.setattr(sampler, "_fd_count", lambda _pid: 3)
    sampler.process_sample()
    assert sampler._process_start_times[(process.logical_id, process.pid)] == 10
    start_time = 20

    with pytest.raises(CollectionError, match="process identity changed"):
        sampler.process_sample()

    mid_round = LocalResourceSampler(
        sampler_id="host-b",
        processes=[process],
        proc_root=tmp_path,
        cgroup_root=tmp_path,
    )
    stat_calls = 0

    def changing_process_stat(_process: ProcessSpec) -> dict[str, Any]:
        nonlocal stat_calls
        stat_calls += 1
        return {
            "state": "S",
            "user_cpu_ticks": 1,
            "system_cpu_ticks": 2,
            "start_time_ticks": 30 if stat_calls == 1 else 40,
            "rss_bytes": 4096,
        }

    monkeypatch.setattr(mid_round, "_process_stat", changing_process_stat)
    monkeypatch.setattr(mid_round, "_fd_count", lambda _pid: 3)

    with pytest.raises(CollectionError, match="process identity changed while sampling"):
        mid_round.process_sample()


def test_resource_analyzer_consumes_design_categories() -> None:
    static = {
        "sampler_id": "host-a",
        "network_interfaces": ["eth0"],
        "cpu_count": 4,
    }
    collector = {
        "sample_duration_seconds": 0.01,
        "cpu_time_seconds": 0.1,
        "rss_bytes": 1000,
        "overrun_seconds": 0.0,
    }
    samples = [
        {
            "kind": "host",
            "wall_time": 1.0,
            "monotonic": 1.0,
            "cpu": {"user": 10, "system": 10, "idle": 80, "iowait": 0, "steal": 0},
            "scheduler": {"running": 1, "blocked": 0},
            "memory": {"mem_available_bytes": 2000, "swap_used_bytes": 0},
            "cgroup": {
                "cpu_usage_usec": 100,
                "cpu_throttled_usec": 10,
                "memory_current_bytes": 1000,
                "memory_max_bytes": 5000,
                "oom_count": 0,
                "oom_kill_count": 0,
            },
            "network": {"eth0": {"rx_bytes": 100, "rx_packets": 10, "rx_errors": 0, "rx_drops": 0, "tx_bytes": 200, "tx_packets": 20, "tx_errors": 0, "tx_drops": 0}},
            "collector": collector,
        },
        {
            "kind": "host",
            "wall_time": 6.0,
            "monotonic": 6.0,
            "cpu": {"user": 60, "system": 20, "idle": 120, "iowait": 0, "steal": 0},
            "scheduler": {"running": 3, "blocked": 1},
            "memory": {"mem_available_bytes": 1500, "swap_used_bytes": 4},
            "cgroup": {
                "cpu_usage_usec": 300,
                "cpu_throttled_usec": 30,
                "memory_current_bytes": 2500,
                "memory_max_bytes": 5000,
                "oom_count": 1,
                "oom_kill_count": 1,
            },
            "network": {"eth0": {"rx_bytes": 600, "rx_packets": 40, "rx_errors": 1, "rx_drops": 2, "tx_bytes": 1200, "tx_packets": 70, "tx_errors": 3, "tx_drops": 4}},
            "collector": collector,
        },
        {
            "kind": "process",
            "wall_time": 1.0,
            "monotonic": 1.0,
            "processes": [{"logical_id": "node-a", "pid": 123, "status": "OK", "state": "S", "start_time_ticks": 10, "user_cpu_ticks": 1, "system_cpu_ticks": 2, "rss_bytes": 100, "fd_count": 3}],
            "collector": collector,
        },
        {
            "kind": "process",
            "wall_time": 61.0,
            "monotonic": 61.0,
            "processes": [{"logical_id": "node-a", "pid": 123, "status": "OK", "state": "S", "start_time_ticks": 10, "user_cpu_ticks": 4, "system_cpu_ticks": 6, "rss_bytes": 140, "fd_count": 5}],
            "collector": collector,
        },
    ]

    analysis = analyze_resource_samples(
        static,
        samples,
        timeline_events=[
            {"event_type": "actuator_kill", "event_id": "fault-1", "monotonic": 6.0},
            {"event_type": "sentinel_get", "event_id": "sweep-1", "monotonic": 61.0},
        ],
    )

    assert analysis["cpu"]["utilization_p95"] == 60.0
    assert analysis["cpu"]["throttled_usec_delta"] == 20
    assert analysis["cpu"]["throttling_ratio"] == 0.1
    assert analysis["memory"]["mem_available_min"] == 1500
    assert analysis["memory"]["cgroup_headroom_min"] == 2500
    assert analysis["memory"]["oom_delta"] == 1
    assert analysis["memory"]["oom_kill_delta"] == 1
    assert analysis["memory"]["oom_events"][0]["overlapping_events"][0]["event_type"] == "actuator_kill"
    assert analysis["network"]["eth0"]["rx_bytes_throughput_p95"] == 100.0
    assert analysis["network"]["eth0"]["rx_pps_p95"] == 6.0
    assert analysis["network"]["eth0"]["tx_errors"]["delta"] == 3
    assert analysis["timeline_correlation"]["network_error_or_drop_overlap_count"] == 4
    assert analysis["processes"]["node-a"]["cpu_ticks_delta"] == 7
    assert analysis["process_totals"]["rss_bytes_max_sum"] == 140
    assert analysis["process_totals"]["max_fd_process"] == "node-a"


class FakeLightProbe:
    def collect(self) -> list[dict[str, Any]]:
        return [{"logical_id": "node-a"}]

    def collect_rolling(self, *, duration_seconds: float) -> list[dict[str, Any]]:
        return [{"logical_id": "node-a", "round_seconds": duration_seconds}]

    def validate(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "status": "OK",
            "nodes": [
                {
                    "logical_id": row["logical_id"],
                    "cluster_info": {
                        "cluster_current_epoch": "1",
                        "cluster_my_epoch": "1",
                    },
                }
                for row in rows
            ],
        }


class FakeSentinelLane:
    def prepare(self) -> dict[str, Any]:
        return {"status": "OK"}

    def rolling_sweep(self, *, duration_seconds: float) -> dict[str, Any]:
        return {"status": "OK", "duration_seconds": duration_seconds}

    def close(self) -> None:
        return None


class FakeLoadLane:
    def preflight(self) -> dict[str, Any]:
        return {"status": "OK"}

    def start(self, *, duration_seconds: float) -> object:
        return object()

    def finish(self, process: object) -> dict[str, Any]:
        return {"status": "OK", "warnings": []}


def _resource_document() -> dict[str, Any]:
    collector = {
        "sample_duration_seconds": 0.001,
        "cpu_time_seconds": 0.01,
        "rss_bytes": 1000,
        "overrun_seconds": 0.0,
    }
    return {
        "static": {"sampler_id": "host-a", "network_interfaces": []},
        "samples": [
            {
                "kind": "host",
                "sampler_id": "host-a",
                "wall_time": 1.0,
                "monotonic": 1.0,
                "cpu": {"user": 1, "system": 1, "idle": 10, "iowait": 0, "steal": 0},
                "scheduler": {"running": 1, "blocked": 0},
                "memory": {"mem_available_bytes": 1000, "swap_used_bytes": 0},
                "cgroup": {
                    "memory_current_bytes": 100,
                    "memory_max_bytes": 1000,
                    "cpu_throttled_usec": 0,
                    "oom_kill_count": 0,
                },
                "network": {},
                "collector": collector,
            },
            {
                "kind": "process",
                "sampler_id": "host-a",
                "wall_time": 1.0,
                "monotonic": 1.0,
                "processes": [
                    {
                        "logical_id": "node-a",
                        "pid": 123,
                        "state": "S",
                        "start_time_ticks": 10,
                        "user_cpu_ticks": 1,
                        "system_cpu_ticks": 2,
                        "rss_bytes": 100,
                        "fd_count": 3,
                    }
                ],
                "collector": collector,
            },
        ],
        "errors": [],
    }


class FakeResourceRunner:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document
        self.sampler = type(
            "Sampler",
            (),
            {
                "sampler_id": "host-a",
                "processes": [ProcessSpec("node-a", 123)],
            },
        )()

    def start(self) -> None:
        return None

    def stop(self) -> dict[str, Any]:
        return self.document


class ImmediateResourceRunner:
    def __init__(
        self,
        document: dict[str, Any],
        *,
        logical_id: str = "node-a",
        pid: int = 123,
    ) -> None:
        self.document = document
        self.samples: list[dict[str, Any]] = []
        self.sampler = type(
            "Sampler",
            (),
            {
                "sampler_id": "host-a",
                "processes": [ProcessSpec(logical_id, pid)],
            },
        )()

    def start(self) -> None:
        self.samples = list(self.document.get("samples", []))

    def stop(self) -> dict[str, Any]:
        return self.document


def test_stability_window_requires_resource_sampler() -> None:
    result = StabilityWindow(
        light_probe=FakeLightProbe(),  # type: ignore[arg-type]
        sentinel=FakeSentinelLane(),  # type: ignore[arg-type]
        load=FakeLoadLane(),  # type: ignore[arg-type]
    ).run()

    assert result["status"] == "ERROR"
    assert result["formal_window_started"] is False
    assert result["checks"][0]["name"] == "resource_sampler_configured"


def test_stability_window_consumes_resource_analysis() -> None:
    result = StabilityWindow(
        light_probe=FakeLightProbe(),  # type: ignore[arg-type]
        sentinel=FakeSentinelLane(),  # type: ignore[arg-type]
        load=FakeLoadLane(),  # type: ignore[arg-type]
        resource_runners=[FakeResourceRunner(_resource_document())],  # type: ignore[list-item]
    ).run()

    resource_checks = [
        check
        for check in result["checks"]
        if check["name"] == "resource_analysis:host-a"
    ]
    assert result["status"] == "PASS"
    assert resource_checks
    assert resource_checks[0]["evidence"]["processes"]["node-a"]["fd_count_max"] == 3


def test_resource_observation_positive_path_consumes_sampler_and_analyzer() -> None:
    document = _resource_document()
    document["samples"].append(
        {
            **document["samples"][-1],
            "monotonic": 2.0,
            "processes": [
                {
                    "logical_id": "node-a",
                    "pid": 123,
                    "status": "EXPECTED_GONE",
                    "reason": "planned actuator kill",
                }
            ],
        }
    )
    runner = ImmediateResourceRunner(document)

    result = run_resource_observation(
        runners=[runner],  # type: ignore[list-item]
        duration_seconds=0.002,
        expected_gone_processes=[ExpectedGoneProcess("node-a", 123)],
        sleep_interval_seconds=0.001,
    )

    assert result["status"] == "PASS"
    assert result["planned_kill_prefault_sample_complete"] is True
    assert result["resource_analyses"][0]["analysis"]["expected_gone_processes"]


def test_resource_observation_without_runner_is_error() -> None:
    result = run_resource_observation(runners=[], duration_seconds=0.001)

    assert result["status"] == "ERROR"
    assert result["checks"][0]["name"] == "resource_sampler_configured"


def test_resource_observation_analyzer_failure_is_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_analyzer(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("analysis broke")

    monkeypatch.setattr(observation_module, "analyze_resource_samples", fail_analyzer)
    result = run_resource_observation(
        runners=[ImmediateResourceRunner(_resource_document())],  # type: ignore[list-item]
        duration_seconds=0.002,
        sleep_interval_seconds=0.001,
    )

    assert result["status"] == "ERROR"
    assert result["checks"][-1]["name"] == "resource_analysis:host-a"


def test_resource_observation_missing_live_process_sample_is_error() -> None:
    document = _resource_document()
    document["samples"][-1]["processes"] = []

    result = run_resource_observation(
        runners=[ImmediateResourceRunner(document)],  # type: ignore[list-item]
        duration_seconds=0.002,
        sleep_interval_seconds=0.001,
    )

    assert result["status"] == "ERROR"
    assert "live process samples are missing" in result["checks"][-1]["reason"]


def test_resource_observation_requires_planned_kill_prefault_sample() -> None:
    document = _resource_document()
    document["samples"][-1]["processes"] = [
        {
            "logical_id": "node-a",
            "pid": 123,
            "status": "EXPECTED_GONE",
            "reason": "already gone",
        }
    ]

    result = run_resource_observation(
        runners=[ImmediateResourceRunner(document)],  # type: ignore[list-item]
        duration_seconds=0.002,
        expected_gone_processes=[ExpectedGoneProcess("node-a", 123)],
        sleep_interval_seconds=0.001,
    )

    assert result["status"] == "ERROR"
    assert result["checks"][0]["name"] == "resource_expected_gone_prefault_sample"


class _ScriptedValidator(FullClusterValidator):
    """A validator whose observations are a script, so the waiting rule is what
    is under test rather than a cluster."""

    def __init__(self, script, **kwargs):
        super().__init__(
            [NodeEndpoint("p0", "127.0.0.1", 7000, "primary", "s0")],
            connection_factory=lambda *_a, **_k: None,
            **kwargs,
        )
        self._script = list(script)
        self.observations = 0

    def _run_once(self, **_options):
        self.observations += 1
        pending = self._script[min(self.observations - 1, len(self._script) - 1)]
        if pending is None:
            return {"status": "OK"}
        raise ConvergenceFailure(
            "CLUSTER SHARDS contains unhealthy nodes: " + ", ".join(pending),
            pending=pending,
        )


def test_a_moving_queue_converges_however_long_the_queue_is(monkeypatch) -> None:
    """The measured shape at 200 nodes: one node unhealthy at a time, clearing
    and handing off, with the set never shrinking below one until it empties.

    A rule keyed on the set's *size* would reject this - the size is 1 from the
    first observation to the last - so progress has to be a departure by identity.
    """

    monkeypatch.setattr(time, "sleep", lambda _s: None)
    clock = iter([n * 2.0 for n in range(2000)])
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    # 60 handoffs at 2s each is 120s of a queue that never has fewer than one
    # pending node, then healthy.
    script = [[f"node-{i // 4:04d}"] for i in range(240)] + [None]

    validator = _ScriptedValidator(script, no_progress_seconds=60.0)
    assert validator.run()["status"] == "OK"
    assert validator.observations == 241


def test_one_laggard_that_finally_clears_is_not_a_stall(monkeypatch) -> None:
    """Run D, measured: a healthy cluster held one node unhealthy, unchanged, for
    83.1s and then converged. Any window at or below that rejects a good cluster,
    which is why the bound is 240s and not the 180s it replaces."""

    monkeypatch.setattr(time, "sleep", lambda _s: None)
    clock = iter([n * 2.13 for n in range(2000)])
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    rounds = int(83.1 / 2.13) + 1
    validator = _ScriptedValidator(
        [["c000b736347c"]] * rounds + [None],
        no_progress_seconds=CONVERGENCE_NO_PROGRESS_SECONDS,
    )

    assert validator.run()["status"] == "OK"


def test_a_stuck_node_stops_the_wait_without_reaching_the_ceiling(monkeypatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    clock = iter([n * 2.0 for n in range(4000)])
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    validator = _ScriptedValidator(
        [["stuck-node"]], no_progress_seconds=60.0, convergence_timeout=1800.0
    )

    with pytest.raises(ConvergenceFailure) as excinfo:
        validator.run()

    message = str(excinfo.value)
    assert "stopped converging" in message
    assert "nothing left the pending set" in message
    assert "stuck-node" in message
    assert excinfo.value.pending == frozenset({"stuck-node"})
    # It reports on the no-progress window, nowhere near the 1800s ceiling.
    assert validator.observations < 40


def test_a_growing_pending_set_is_not_progress(monkeypatch) -> None:
    """A set that only gains members has not made progress, however much it
    changes. Keying on "the set changed" instead of "something left" would wait
    for ever on a cluster that is getting worse."""

    monkeypatch.setattr(time, "sleep", lambda _s: None)
    clock = iter([n * 2.0 for n in range(4000)])
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    script = [[f"node-{j:04d}" for j in range(i + 1)] for i in range(200)]
    validator = _ScriptedValidator(script, no_progress_seconds=60.0)

    with pytest.raises(ConvergenceFailure, match="stopped converging"):
        validator.run()


def test_a_single_observation_caller_still_gets_the_raw_failure(monkeypatch) -> None:
    """`convergence_timeout=0.0` is the failover lane's contract: observe once and
    report what was seen, unwrapped."""

    monkeypatch.setattr(time, "sleep", lambda _s: None)
    validator = _ScriptedValidator([["p0"]], convergence_timeout=0.0)

    with pytest.raises(ConvergenceFailure) as excinfo:
        validator.run()

    assert "CLUSTER SHARDS contains unhealthy nodes" in str(excinfo.value)
    assert "stopped converging" not in str(excinfo.value)
    assert validator.observations == 1


class _CountingConn:
    """Counts what one Sentinel lookup costs, so a budget can be asserted."""

    def __init__(self, endpoint, ledger, dead, owner) -> None:
        self.endpoint = endpoint
        self.ledger = ledger
        self.owner = owner
        ledger["connects"] += 1
        if endpoint in dead():
            raise ConnectionRefusedError(f"refused {endpoint}")

    def execute(self, *args):
        self.ledger["commands"] += 1
        if self.endpoint == self.owner():
            return b"canary"
        target = self.owner()
        raise RespCommandError(f"MOVED 0 {target.host}:{target.port}")

    def close(self) -> None:
        return None


def _router_lookup_cost(primary_count: int, *, promoted: bool):
    """One steady-state lookup against a cluster whose slot owner is dead."""

    seeds = [Endpoint(f"10.0.0.{i + 1}", 7000 + i) for i in range(primary_count)]
    state = {"dead": {seeds[0]}, "owner": seeds[0]}
    ledger = {"connects": 0, "commands": 0}
    router = ClusterRouter(
        seeds,
        connection_factory=lambda endpoint, timeout: _CountingConn(
            endpoint, ledger, lambda: state["dead"], lambda: state["owner"]
        ),
    )
    key = "{vslab-sentinel-0}:canary"
    router._slot_routes[key_slot(key)] = seeds[0]
    for _ in range(3):  # warm the persistent connections the design allows
        try:
            router.get(key)
        except Exception:
            pass
    if promoted:
        state["owner"] = Endpoint("10.9.9.9", 7999)
    ledger["connects"] = 0
    ledger["commands"] = 0
    value = None
    try:
        value = router.get(key)
    except Exception:
        pass
    return ledger, value


def test_sentinel_lookup_cost_does_not_grow_with_cluster_size() -> None:
    """§14 budgets the fault probe at O(1) and §7.6 at ~20 GET/s 'independent of
    cluster node count'. Before this bound one outage lookup cost one connect and
    one GET per primary - measured 100/99 at 100 primaries and 1000/999 at 1000 -
    which is what broke §16 item 8's 100ms period at exact-200 and would have made
    the probe a load generator against the failover it measures at exact-2000."""

    costs = {n: _router_lookup_cost(n, promoted=False)[0] for n in (15, 100, 1000)}

    assert costs[15] == costs[100] == costs[1000]
    assert costs[1000]["commands"] <= MAX_SEEDS_PER_LOOKUP
    # Only the dead owner is dialled, and only once, however many seeds name it.
    assert costs[1000]["connects"] <= 2


def test_sentinel_lookup_still_finds_the_promoted_owner() -> None:
    """The bound must not buy its cost back by observing recovery late: the
    promoted node is not a seed, so it is only reachable through a seed's MOVED."""

    for primary_count in (15, 100, 1000):
        ledger, value = _router_lookup_cost(primary_count, promoted=True)
        assert value == b"canary", primary_count
        assert ledger["commands"] <= MAX_SEEDS_PER_LOOKUP + 1


def test_sentinel_lookup_rotates_so_no_seed_is_starved() -> None:
    """A fixed window would keep asking the same few primaries; over successive
    rounds every primary must get a turn, or a stale trio could hide a promotion."""

    seeds = [Endpoint(f"10.0.0.{i + 1}", 7000 + i) for i in range(12)]
    asked: list[Endpoint] = []

    class _Recorder:
        def __init__(self, endpoint, *_a) -> None:
            self.endpoint = endpoint

        def execute(self, *args):
            asked.append(self.endpoint)
            raise RespCommandError(f"MOVED 0 {seeds[0].host}:{seeds[0].port}")

        def close(self) -> None:
            return None

    router = ClusterRouter(seeds, connection_factory=lambda e, t: _Recorder(e))
    for _ in range(12):
        try:
            router.get("{vslab-sentinel-0}:canary")
        except Exception:
            pass

    assert len(set(asked)) > MAX_SEEDS_PER_LOOKUP


def test_probe_cadence_is_measured_rather_than_declared() -> None:
    """§16 item 8 asks the fault probe to reach a 100ms period. At exact-200 it
    achieved 194ms and said 100ms, so an RTO read off it claimed a precision it
    did not have."""

    lost_cadence = _round_cadence([{"monotonic": i * 0.194} for i in range(20)], 0.1)

    assert lost_cadence["requested_interval_ms"] == 100.0
    assert lost_cadence["median_interval_ms"] == pytest.approx(194.0, abs=0.5)
    assert lost_cadence["overrun_round_count"] == 19

    # A healthy probe sleeps off its period and inherits scheduling jitter, so
    # every interval is a little over 100ms. Measured on a real exact-50: 438 of
    # 438 intervals between 100.1ms and 114.9ms. Counting those as overruns
    # would make the field fire on every run and mean nothing.
    healthy = _round_cadence([{"monotonic": i * 0.1074} for i in range(20)], 0.1)

    assert healthy["median_interval_ms"] == pytest.approx(107.4, abs=0.5)
    assert healthy["overrun_round_count"] == 0


def _failover_round(offset_s, fault_at, *, role, pfail, fail, slots_ok, status="OK"):
    return {
        "monotonic": fault_at + offset_s,
        "rows": [
            {
                "logical_id": "shard-0001-replica-00",
                "status": status,
                "role": {"role": role},
                "cluster_state": "ok",
                "cluster_info": {
                    "cluster_nodes_pfail": pfail,
                    "cluster_nodes_fail": fail,
                    "cluster_slots_ok": slots_ok,
                    "cluster_state": "ok",
                },
            }
        ],
        "candidate": None,
    }


def _failover_inputs(*, pfail_at=45.5, promote_at=47.5, fault_at=1000.0):
    rounds = []
    offset = 0.1
    while offset < promote_at + 1.0:
        promoted = offset >= promote_at
        rounds.append(
            _failover_round(
                offset,
                fault_at,
                role="primary" if promoted else "replica",
                pfail=0 if promoted or offset < pfail_at else 1,
                fail=1 if promoted else 0,
                slots_ok=16384 if promoted else 15730,
            )
        )
        offset += 0.5
    samples = []
    offset = 0.1
    while offset < promote_at + 1.2:
        samples.append(
            {
                "monotonic": fault_at + offset,
                "status": "OK" if offset >= promote_at else "TRANSIENT",
            }
        )
        offset += 0.1
    actuator = {
        "signal_or_request_sent": {"monotonic": fault_at},
        "action_completed": {"monotonic": fault_at + 0.14},
    }
    convergence = {"rounds": rounds, "round_interval_ms": 500}
    sentinel = {
        "rto_ms": promote_at * 1000.0,
        "samples": samples,
        "round_cadence": {"median_interval_ms": 100.0, "requested_interval_ms": 100.0},
    }
    return actuator, convergence, sentinel


def _derived(**kwargs):
    from valkey_scale_lab.runtime.docker_runtime import _derive_failover_timeline

    actuator, convergence, sentinel = _failover_inputs(**kwargs)
    timeline = _derive_failover_timeline(
        actuator_record=actuator,
        convergence_result=convergence,
        sentinel_result=sentinel,
        observer_interval_ms=500.0,
    )
    return timeline, {row["field"]: row for row in timeline["intervals"]}


def test_failover_timeline_separates_detection_from_control_plane() -> None:
    """The whole point of the timeline: an aggregate RTO folds a detection term
    that is flat in node count together with a control-plane term that is not.
    Measured over 74 retained runs, detection stayed at 44.1s/44.0s/42.8s median
    for 30/50/200 nodes while pfail->promotion grew 2.53s -> 3.80s -> 8.05s."""

    _timeline, intervals = _derived(pfail_at=45.5, promote_at=47.5)

    detection = intervals["process_gone_to_pfail_ms"]
    control_plane = intervals["pfail_to_promotion_ms"]
    assert detection["value_ms"] == pytest.approx(45_460.0, abs=520.0)
    assert control_plane["value_ms"] == pytest.approx(2_000.0, abs=520.0)
    # Both endpoints are sampled, so the interval carries both sampling delays.
    assert control_plane["precision_ms"] == 1000.0
    assert detection["precision_ms"] == 500.0


def test_failover_timeline_keeps_the_legacy_rto_meaning() -> None:
    """M3 froze its baselines on rto_ms, so the end-to-end number must keep its
    meaning exactly or M3 and M4 stop being comparable."""

    _timeline, intervals = _derived(promote_at=47.5)

    assert intervals["failure_to_client_recovered_ms"]["value_ms"] == 47_500.0


def test_failover_timeline_states_absence_instead_of_inventing_a_number() -> None:
    """A run where no round ever reported a pfail node must say so. Filling the
    gap with a neighbouring timestamp would make the control-plane metric look
    measured on exactly the runs where it was not."""

    from valkey_scale_lab.runtime.docker_runtime import _derive_failover_timeline

    actuator, convergence, sentinel = _failover_inputs()
    for entry in convergence["rounds"]:
        entry["rows"][0]["cluster_info"]["cluster_nodes_pfail"] = 0
    timeline = _derive_failover_timeline(
        actuator_record=actuator,
        convergence_result=convergence,
        sentinel_result=sentinel,
        observer_interval_ms=500.0,
    )
    intervals = {row["field"]: row for row in timeline["intervals"]}

    assert intervals["pfail_to_promotion_ms"]["status"] == "MISSING"
    assert intervals["pfail_to_promotion_ms"]["reason"]
    assert "value_ms" not in intervals["pfail_to_promotion_ms"]
    assert timeline["observation_points_ms"]["first_pfail_at_ms"] == "MISSING"


def test_failover_timeline_declares_what_its_vantage_cannot_measure() -> None:
    """first_fail and first_cluster_ok are not coarse, they are unobservable from
    the affected shard's survivor. Declaring them keeps a later reader from
    deriving them from a neighbouring field that happens to move."""

    timeline, _intervals = _derived()
    declared = {row["field"]: row for row in timeline["unmeasurable_points"]}

    assert set(declared) == {"first_fail_at_ms", "first_cluster_ok_at_ms"}
    for row in declared.values():
        assert row["status"] == "MISSING"
        assert len(row["reason"]) > 40


def test_failover_timeline_does_not_skip_the_round_that_set_its_own_threshold() -> None:
    """Regression: `_failover_point` used to compare an unrounded offset against
    an already-rounded threshold, so a round whose offset rounds *up* was judged
    to precede itself. Promotion and full slot coverage land in the same round -
    exactly 0.000 in all 74 retained runs - and the defect reported 511ms of
    topology recovery that never happened.

    The monotonic below is chosen so (monotonic - fault) * 1000 rounds up.
    """

    from valkey_scale_lab.runtime.docker_runtime import _derive_failover_timeline

    fault_at = 1000.0
    raw_offset_s = 47.14336499  # * 1000 -> 47143.36499, rounds to 47143.365
    assert round(raw_offset_s * 1000.0, 3) > raw_offset_s * 1000.0

    rounds = [
        _failover_round(0.1, fault_at, role="replica", pfail=1, fail=0, slots_ok=15730),
        _failover_round(
            raw_offset_s, fault_at, role="primary", pfail=0, fail=1, slots_ok=16384
        ),
    ]
    timeline = _derive_failover_timeline(
        actuator_record={
            "signal_or_request_sent": {"monotonic": fault_at},
            "action_completed": {"monotonic": fault_at + 0.14},
        },
        convergence_result={"rounds": rounds, "round_interval_ms": 500},
        sentinel_result={
            "rto_ms": 47000.0,
            "samples": [{"monotonic": fault_at + 0.1, "status": "TRANSIENT"}],
            "round_cadence": {"median_interval_ms": 100.0},
        },
        observer_interval_ms=500.0,
    )
    intervals = {row["field"]: row for row in timeline["intervals"]}

    assert intervals["promotion_to_slots_covered_ms"]["value_ms"] == 0.0


def _four_survivor_nodes() -> list[NodeEndpoint]:
    """One promoted primary and three siblings still replicating to it.

    The shape a four-replica shard is left in after its primary is killed, and
    the shape no test has ever built: every observer fixture in this file has
    one or two survivors, because one replica per shard is all any run has had.
    """

    return [
        NodeEndpoint("r0", "h", 1, "replica", "s0"),
        NodeEndpoint("r1", "h", 2, "replica", "s0"),
        NodeEndpoint("r2", "h", 3, "replica", "s0"),
        NodeEndpoint("r3", "h", 4, "replica", "s0"),
    ]


def test_affected_shard_converges_with_four_survivors() -> None:
    """Plural-capable by construction, asserted rather than assumed.

    The observer takes every surviving shard member and detects promotion as
    "exactly one survivor reports primary, and every other names it". Nothing in
    it counts replicas, so the only thing worth proving is that the relationship
    check holds when three replicas have to agree instead of one.
    """

    clock = FakeClock()
    nodes = _four_survivor_nodes()

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        role = (
            [b"master", 0, []]
            if endpoint.port == 2
            else [b"slave", b"h", 2, b"connected", 0]
        )
        return FakeConnection({("ROLE",): role, ("CLUSTER", "INFO"): b"cluster_state:ok\r\n"})

    observer = AffectedShardObserver(
        nodes, connection_factory=factory, sleep=clock.sleep, monotonic=clock.monotonic
    )
    result = observer.wait_for_convergence(
        deadline_seconds=2, full_validation=lambda: {"status": "OK"}
    )

    assert result["status"] == "OK"
    assert result["converged_relationship"]["primary"] == "r1"
    assert result["converged_relationship"]["relationships"] == {
        "r0": "replica-of:r1",
        "r1": "primary",
        "r2": "replica-of:r1",
        "r3": "replica-of:r1",
    }
    assert len(result["rounds"]) == 2


def test_one_transient_survivor_resets_the_convergence_streak() -> None:
    """A round is a whole-shard observation: one unreachable sibling voids it.

    With four survivors there are four chances per round for that, where with
    one there was one. The round still records the sibling as TRANSIENT rather
    than failing, and the two-identical-rounds rule simply starts again.
    """

    clock = FakeClock()
    nodes = _four_survivor_nodes()
    rounds = {"count": 0}

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        role = (
            [b"master", 0, []]
            if endpoint.port == 2
            else [b"slave", b"h", 2, b"connected", 0]
        )
        responses: dict[tuple[Any, ...], Any] = {
            ("ROLE",): role,
            ("CLUSTER", "INFO"): b"cluster_state:ok\r\n",
        }
        if endpoint.port == 4 and rounds["count"] < 2:
            responses[("ROLE",)] = ConnectionRefusedError("r3 is still coming back")
        return FakeConnection(responses)

    observer = AffectedShardObserver(
        nodes, connection_factory=factory, sleep=clock.sleep, monotonic=clock.monotonic
    )
    original = observer.sample_round

    def counted() -> dict[str, Any]:
        result = original()
        rounds["count"] += 1
        return result

    observer.sample_round = counted  # type: ignore[method-assign]
    result = observer.wait_for_convergence(
        deadline_seconds=5, full_validation=lambda: {"status": "OK"}
    )

    assert result["status"] == "OK"
    # Two voided rounds, then the two identical healthy ones the rule wants.
    assert len(result["rounds"]) == 4
    assert result["rounds"][0]["candidate"] is None
    assert [row["status"] for row in result["rounds"][0]["rows"]].count("TRANSIENT") == 1
    assert result["rounds"][-1]["candidate"]["primary"] == "r1"


def test_two_primaries_among_four_survivors_is_not_a_converged_round() -> None:
    """Two candidates can report primary at once while an election settles."""

    clock = FakeClock()
    nodes = _four_survivor_nodes()

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        role = (
            [b"master", 0, []]
            if endpoint.port in (2, 3)
            else [b"slave", b"h", 2, b"connected", 0]
        )
        return FakeConnection({("ROLE",): role, ("CLUSTER", "INFO"): b"cluster_state:ok\r\n"})

    observer = AffectedShardObserver(
        nodes, connection_factory=factory, sleep=clock.sleep, monotonic=clock.monotonic
    )
    with pytest.raises(SemanticFailure, match="two identical healthy 500ms rounds"):
        observer.wait_for_convergence(
            deadline_seconds=2, full_validation=lambda: {"status": "OK"}
        )


def _light_report(shard_replicas: dict[str, int], *, connected: dict[str, int] | None = None) -> dict[str, Any]:
    connected = connected or {}
    rows: list[dict[str, Any]] = []
    for shard_id, replicas in shard_replicas.items():
        rows.append(
            {
                "logical_id": f"{shard_id}-primary",
                "myslots": {"shard-id": shard_id, "role": "primary"},
                "role": {"replication_state": "connected"},
            }
        )
        healthy = connected.get(shard_id, replicas)
        for index in range(replicas):
            rows.append(
                {
                    "logical_id": f"{shard_id}-replica-{index:02d}",
                    "myslots": {"shard-id": shard_id, "role": "replica"},
                    "role": {
                        "replication_state": "connected" if index < healthy else "sync"
                    },
                }
            )
    return {"nodes": rows}


def test_redundancy_recovery_is_exact_at_one_and_at_four_replicas() -> None:
    """The first tests this function has had; it was already r-generic.

    `redundancy_recovery` counts the shard's own replicas against an expectation
    the caller derives from that shard's membership, so nothing in it assumes
    one. What had never been checked is that it refuses the two ways a
    four-replica shard can be short: a missing replica, and a replica present but
    not yet connected.
    """

    for replicas in (1, 4):
        report = _light_report({"s0": replicas, "s1": replicas})
        result = redundancy_recovery(report, expected_replicas_per_shard=replicas)
        assert result == {
            "status": "OK",
            "shard_count": 2,
            "expected_replicas_per_shard": replicas,
            "replicas_connected": True,
        }

    short = _light_report({"s0": 3, "s1": 4})
    with pytest.raises(SemanticFailure, match="redundancy recovery is incomplete"):
        redundancy_recovery(short, expected_replicas_per_shard=4)

    resyncing = _light_report({"s0": 4, "s1": 4}, connected={"s0": 2})
    with pytest.raises(SemanticFailure) as excinfo:
        redundancy_recovery(resyncing, expected_replicas_per_shard=4)
    assert "'replicas': 4" in str(excinfo.value)
    assert "'connected': 2" in str(excinfo.value)


def test_redundancy_recovery_refuses_a_shard_shape_that_is_not_uniform() -> None:
    """One expectation is compared against every shard, so a mixed fleet fails."""

    mixed = _light_report({"s0": 4, "s1": 1})
    with pytest.raises(SemanticFailure, match="s1"):
        redundancy_recovery(mixed, expected_replicas_per_shard=4)


class _Clock:
    """A monotonic clock that only advances when something sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _gate_nodes(count: int = 12) -> list[dict[str, Any]]:
    return [
        {
            "logical_id": f"shard-{index // 2:04d}-"
            + ("primary" if index % 2 == 0 else "replica"),
            "role": "primary" if index % 2 == 0 else "replica",
            "shard_id": f"shard-{index // 2:04d}",
            "az_id": "az-a" if index % 2 == 0 else "az-b",
            "host": "127.0.0.1",
            "client_port": 7000 + index,
        }
        for index in range(count)
    ]


def _clean_snapshots(nodes: list[dict[str, Any]], expected_nodes: int) -> list[dict[str, Any]]:
    return [
        {
            "logical_id": node["logical_id"],
            "probe_status": "PASS",
            "cluster_state": "ok",
            "known_nodes": expected_nodes,
            "role": node["role"],
            "slots_assigned": 16384,
            "slots_ok": 16384,
            "slots_fail": 0,
        }
        for node in nodes
    ]


def test_a_bounded_wait_does_not_spend_a_whole_fleet_round_every_second(monkeypatch) -> None:
    """The adversarial case: everything a subset can see is clean and the fleet
    is not, so the cheap prefilter cannot help and only the backoff can.

    Role counts are a property of the probed set, so no subset can evaluate
    them; this is the one shape where the observers say clean round after round
    while the whole-fleet round keeps disagreeing. Left at one round per second
    a 120s wait costs 120 whole-fleet rounds - at 1280 nodes that is 7680 RESP
    commands a second from one controller, against §4.4's one round per 60s.
    """

    from valkey_scale_lab.runtime import docker_runtime

    nodes = _gate_nodes()
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "sleep", clock.sleep)
    probed: list[int] = []

    def health(probe_nodes, *, rows=None):
        probed.append(len(probe_nodes))
        return {
            "cluster_state": "ok",
            "known_nodes": len(nodes),
            # Never the expected counts, so the wait can never end.
            "primary_count": 0,
            "replica_count": 0,
            "slots_assigned": 16384,
            "slots_ok": 16384,
            "slots_fail": 0,
            "snapshots": _clean_snapshots(probe_nodes, len(nodes)),
        }

    monkeypatch.setattr(docker_runtime, "_management_cluster_health", health)
    monkeypatch.setattr(
        docker_runtime, "_process_node_snapshot", lambda node: {"logical_id": node["logical_id"]}
    )

    with pytest.raises(docker_runtime.DockerRuntimeError):
        docker_runtime._management_wait_clean_cluster(nodes, timeout=120.0)

    whole_fleet = [size for size in probed if size == len(nodes)]
    assert len(whole_fleet) <= 12, "a 120s wait must not cost 120 whole-fleet rounds"
    # And it does keep re-reading the fleet, because the prefilter is an
    # optimisation and not a verdict: 15s is the longest gap it may leave.
    assert len(whole_fleet) >= 8


def test_a_bounded_wait_still_ends_only_on_a_whole_fleet_round(monkeypatch) -> None:
    """The prefilter decides when to look, never what was seen.

    Its observers report clean from the first observation while the fleet is
    not, so a wait that trusted them would return immediately on three nodes.
    """

    from valkey_scale_lab.runtime import docker_runtime

    nodes = _gate_nodes()
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "sleep", clock.sleep)
    fleet_clean_at = 5.0
    probed: list[tuple[float, int]] = []

    def health(probe_nodes, *, rows=None):
        probed.append((clock.now, len(probe_nodes)))
        whole_fleet = len(probe_nodes) == len(nodes)
        settled = clock.now >= fleet_clean_at
        return {
            "cluster_state": "ok",
            "known_nodes": len(nodes),
            "primary_count": len([n for n in probe_nodes if n["role"] == "primary"])
            if not whole_fleet or settled
            else 0,
            "replica_count": len([n for n in probe_nodes if n["role"] == "replica"])
            if not whole_fleet or settled
            else 0,
            "slots_assigned": 16384,
            "slots_ok": 16384,
            "slots_fail": 0,
            "snapshots": _clean_snapshots(probe_nodes, len(nodes)),
        }

    monkeypatch.setattr(docker_runtime, "_management_cluster_health", health)
    monkeypatch.setattr(
        docker_runtime, "_process_node_snapshot", lambda node: {"logical_id": node["logical_id"]}
    )

    docker_runtime._management_wait_clean_cluster(nodes, timeout=120.0)

    assert probed[-1][1] == len(nodes), "the wait ended on a whole-fleet round"
    assert probed[-1][0] >= fleet_clean_at, "and not before the fleet was clean"
    # It also did not sit out the whole recheck interval once the fleet settled.
    assert probed[-1][0] < fleet_clean_at + docker_runtime.WHOLE_FLEET_RECHECK_SECONDS


def test_the_partition_probes_clean_wait_uses_the_same_rule(monkeypatch) -> None:
    """The other clock-driven whole-fleet gate, measured on the same run: three
    16.7s waits inside the network-partition probe cost 51 whole-fleet rounds
    between them."""

    from valkey_scale_lab.runtime import docker_runtime

    nodes = _gate_nodes()
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "sleep", clock.sleep)
    rounds: list[float] = []

    class _NeverCleanProbe:
        def __init__(self, inventory, **_kwargs) -> None:
            self._count = len(inventory)

        def run(self, **_options):
            rounds.append(clock.now)
            return {"status": "OK", "nodes_observed": self._count - 1}

    def health(probe_nodes, *, rows=None):
        return {
            "cluster_state": "ok",
            "known_nodes": len(nodes),
            "primary_count": 0,
            "replica_count": 0,
            "slots_assigned": 16384,
            "slots_ok": 16384,
            "slots_fail": 0,
            "snapshots": _clean_snapshots(probe_nodes, len(nodes)),
        }

    monkeypatch.setattr(docker_runtime, "LightClusterProbe", _NeverCleanProbe)
    monkeypatch.setattr(docker_runtime, "_management_cluster_health", health)
    monkeypatch.setattr(
        docker_runtime, "_process_node_snapshots_parallel", lambda nodes, **_k: []
    )

    with pytest.raises(docker_runtime.DockerRuntimeError):
        docker_runtime._wait_process_light_clean(
            nodes,
            expected_nodes=len(nodes),
            expected_primaries=len(nodes) // 2,
            expected_replicas=len(nodes) // 2,
            timeout=120.0,
        )

    assert len(rounds) <= 12, "a 120s wait must not cost 120 whole-fleet rounds"
    assert len(rounds) >= 8


def test_a_topology_snapshot_observes_the_fleet_once(monkeypatch) -> None:
    """The health summary and the live topology are two derivations of one
    layer-1 round, and used to be two rounds taken milliseconds apart.

    Measured on a real exact-200 run: 68 snapshots issued 136 whole-fleet
    200-node rounds, 32% of every whole-fleet round the run made.
    """

    from valkey_scale_lab.runtime import docker_runtime

    nodes = _gate_nodes()
    collected: list[int] = []
    real_rows = docker_runtime._light_probe_rows

    def rows(probe_nodes):
        collected.append(len(probe_nodes))
        return [
            {
                "logical_id": node["logical_id"],
                "status": "FAIL",
                "error": "probe not wired in this test",
                "failure_kind": "semantic",
            }
            for node in probe_nodes
        ]

    monkeypatch.setattr(docker_runtime, "_light_probe_rows", rows)
    assert real_rows is not rows

    class _Telemetry:
        def now_unix_ms(self) -> int:
            return 0

    snapshot = docker_runtime._management_topology_snapshot(
        _Telemetry(), "cap", "run", "op", "label", nodes, nodes
    )

    assert collected == [len(nodes)], "one round, two derivations"
    assert len(snapshot["nodes"]) == len(nodes)
