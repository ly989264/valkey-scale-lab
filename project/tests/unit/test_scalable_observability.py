from __future__ import annotations

import copy
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from valkey_scale_lab.observability.cluster import (
    FullClusterValidator,
    LightClusterProbe,
    NodeEndpoint,
    cluster_shards_node_ids,
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
    Canary,
    ClusterRouter,
    SentinelLane,
    SentinelNode,
    key_slot,
    slot_tags,
)
from valkey_scale_lab.observability.stability import StabilityWindow
from valkey_scale_lab.valkey.resp import Endpoint, read_response


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


def _shards_with_loading_replica(node_ids: list[str]) -> list[Any]:
    """CLUSTER SHARDS where one replica has not finished its initial sync."""
    shards = copy.deepcopy(_shards(node_ids))
    replica = shards[0][3][1]
    assert replica[-2] == b"health"
    replica[-1] = b"loading"
    return shards


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


def test_actuator_failure_is_a_collection_error() -> None:
    recorder = ActuatorRecorder(target="p0", action="kill")
    recorder.start()
    recorder.sent()
    with pytest.raises(CollectionError, match="could not execute"):
        recorder.complete(result="permission denied")


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
