from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from valkey_scale_lab.observability.cluster import (
    FullClusterValidator,
    LightClusterProbe,
    NodeEndpoint,
    normalize_cluster_shards,
    observation_complexity,
    parse_myslots,
)
from valkey_scale_lab.observability.contracts import (
    CheckResult,
    CheckStatus,
    CollectionError,
    SemanticFailure,
    final_verdict,
    run_check,
)
from valkey_scale_lab.observability.failover import (
    ActuatorRecorder,
    AffectedShardObserver,
)
from valkey_scale_lab.observability.load import MemtierLoadLane, per_connection_rate
from valkey_scale_lab.observability.sentinel import (
    Canary,
    ClusterRouter,
    SentinelLane,
    SentinelNode,
    key_slot,
    slot_tags,
)
from valkey_scale_lab.valkey.resp import Endpoint, RespCommandError, read_response


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


def test_load_lane_uses_only_the_fixed_v1_parameters(tmp_path: Path) -> None:
    lane = MemtierLoadLane(
        host="127.0.0.1",
        port=7000,
        primary_count=40,
        run_scope="run-a:arm-b",
        artifacts_dir=tmp_path,
    )
    command = lane.command(lane.paths("formal"), duration_seconds=120)

    assert per_connection_rate(40) == 250
    assert "-c" in command and command[command.index("-c") + 1] == "1"
    assert "-t" in command and command[command.index("-t") + 1] == "1"
    assert "--pipeline=1" in command
    assert "--ratio=1:9" in command
    assert "--key-minimum=0" in command
    assert "--key-maximum=99999" in command
    assert "--data-size=32" in command
    assert "--rate-limiting=250" in command
    assert "--key-prefix=vsl:load:run-a:arm-b:" in command
    assert not any("preload" in value or "warmup" in value for value in command)


def test_sentinel_keyspace_and_one_canary_per_shard() -> None:
    tags = slot_tags([0, 8192])
    canaries = [
        Canary("a" * 40, slot, f"vsl:sentinel:r:a:{{{tags[slot]}}}:s", "v")
        for slot in (0, 8192)
    ]

    assert [key_slot(canary.key) for canary in canaries] == [0, 8192]
    assert all(not canary.key.startswith("vsl:load:") for canary in canaries)


def test_sentinel_router_tries_next_seed_after_connection_failure() -> None:
    seeds = [Endpoint("first", 7000), Endpoint("second", 7001)]
    calls: list[Endpoint] = []

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        calls.append(endpoint)
        response: Any = (
            ConnectionRefusedError("primary seed is down")
            if endpoint == seeds[0]
            else b"value"
        )
        return FakeConnection({("GET", "key"): response})

    router = ClusterRouter(seeds, connection_factory=factory)

    assert router.get("key") == b"value"
    assert calls == seeds


def test_fault_probe_reaches_promoted_replica_through_its_published_endpoint() -> None:
    clock = FakeClock()
    affected = Canary("affected", 0, "affected-key", "affected-value")
    control = Canary("control", 1, "control-key", "control-value")
    nodes = [
        SentinelNode(
            NodeEndpoint("affected-primary", "127.0.0.1", 7000, "primary", "affected"),
            "1" * 40,
            "affected",
            "primary",
            affected,
        ),
        SentinelNode(
            NodeEndpoint("control-primary", "127.0.0.1", 7001, "primary", "control"),
            "2" * 40,
            "control",
            "primary",
            control,
        ),
        SentinelNode(
            NodeEndpoint("promoted-replica", "127.0.0.1", 7002, "replica", "affected"),
            "3" * 40,
            "affected",
            "replica",
            affected,
        ),
        SentinelNode(
            NodeEndpoint("control-replica", "127.0.0.1", 7003, "replica", "control"),
            "4" * 40,
            "control",
            "replica",
            control,
        ),
    ]
    redirected = Endpoint("172.18.0.3", 7002)
    calls: list[tuple[Endpoint, str]] = []

    def factory(endpoint: Endpoint, _timeout: float) -> FakeConnection:
        def response(key: str) -> Any:
            calls.append((endpoint, key))
            if endpoint.port == 7000 or endpoint == redirected:
                raise ConnectionRefusedError("endpoint is unreachable")
            if endpoint.port == 7002 and key == affected.key:
                return affected.value
            if endpoint.port == 7001 and key == control.key:
                return control.value
            raise RespCommandError(
                f"MOVED {key_slot(key)} {redirected.host}:{redirected.port}"
            )

        return FakeConnection(
            {
                ("GET", affected.key): lambda: response(affected.key),
                ("GET", control.key): lambda: response(control.key),
            }
        )

    result = SentinelLane(
        nodes,
        connection_factory=factory,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    ).fault_probe(
        affected=affected,
        control=control,
        recovery_deadline_seconds=2.0,
        fault_monotonic=clock.monotonic(),
    )

    assert result["stable_rounds"] == 10
    assert (Endpoint("127.0.0.1", 7002), affected.key) in calls
    assert (redirected, control.key) in calls


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


def test_actuator_failure_is_a_collection_error() -> None:
    recorder = ActuatorRecorder(target="p0", action="kill")
    recorder.start()
    recorder.sent()
    with pytest.raises(CollectionError, match="could not execute"):
        recorder.complete(result="permission denied")
