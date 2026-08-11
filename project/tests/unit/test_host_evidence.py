"""Cross-host evidence: the estimator, both backends, and what the validator refuses.

Roadmap item 1.3. `project/docs/cross_host_evidence_slice_map.md` carries the
derivation.

Three things a hermetic test can prove here, and one it cannot:

  it can  that the estimator keeps the least-delayed exchange, reports the offset
          with the bound that contains the truth, and that a *shifted* clock
          falls outside that bound;
  it can  the argv each backend builds and the class it raises when a transfer
          fails, which is the acceptance's own "ERROR, not silence";
  it cannot  that a real host's clock is where the reading says it is. That was
          measured on two simulated hosts instead - slice map §2.4 - and the
          detection half is here, because shifting a simulated host's clock would
          shift the kernel the controller shares with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from valkey_scale_lab.observability.contracts import CollectionError
from valkey_scale_lab.runtime import docker_runtime, native_backend as native_backend_module
from valkey_scale_lab.runtime.docker_runtime import DockerHostEvidence
from valkey_scale_lab.runtime.host_clock import (
    CLOCK_EXCHANGE_COUNT,
    HOST_CLOCK_ARGV,
    parse_host_clock,
    reduce_clock_exchanges,
)
from valkey_scale_lab.runtime.host_transport import CommandResult, TransportError
from valkey_scale_lab.runtime.native_backend import NativeMultiEcsBackend

CONTROL = {
    "address": "10.0.0.11",
    "port": 22,
    "user": "ops",
    "private_key_path": "/keys/id_ed25519",
    "known_hosts_path": "/keys/known_hosts",
}


def _exchange(before: float, host: float, after: float, monotonic: float = 100.0) -> dict[str, float]:
    return {
        "controller_before_unix_ms": before,
        "host_unix_ms": host,
        "host_monotonic_seconds": monotonic,
        "controller_after_unix_ms": after,
    }


# --- the estimator ----------------------------------------------------------


def test_the_least_delayed_exchange_is_the_one_kept() -> None:
    reading = reduce_clock_exchanges(
        [
            _exchange(1_000.0, 1_030.0, 1_100.0),  # 100 ms round trip, badly biased
            _exchange(2_000.0, 2_005.0, 2_010.0, monotonic=7.5),  # 10 ms
            _exchange(3_000.0, 3_020.0, 3_060.0),  # 60 ms
        ]
    )

    assert reading["round_trip_ms"] == 10.0
    assert reading["offset_ms"] == 0.0
    assert reading["uncertainty_ms"] == 5.0
    assert reading["host_monotonic_seconds"] == 7.5
    assert reading["exchanges"] == 3


def test_an_offset_is_always_reported_with_the_bound_that_contains_the_truth() -> None:
    # A host whose clock is identical to the controller's, read over a channel
    # whose outbound leg is longer than its return - the +2.3 ms this project
    # measures on simulated hosts. The estimate is biased and the bound covers it.
    reading = reduce_clock_exchanges([_exchange(1_000.0, 1_007.0, 1_010.0)])

    assert reading["offset_ms"] == 2.0
    assert abs(reading["offset_ms"]) <= reading["uncertainty_ms"]


def test_a_shifted_host_clock_falls_outside_its_own_bound() -> None:
    # The same 10 ms exchange against a host running one minute fast. This is the
    # detection half of the estimator, and it is here rather than on a simulated
    # fleet because those hosts share the controller's kernel clock.
    reading = reduce_clock_exchanges([_exchange(1_000.0, 61_005.0, 1_010.0)])

    assert reading["offset_ms"] == 60_000.0
    assert reading["uncertainty_ms"] == 5.0
    assert abs(reading["offset_ms"]) > reading["uncertainty_ms"]


def test_a_reading_with_no_exchange_is_a_collection_error() -> None:
    with pytest.raises(CollectionError):
        reduce_clock_exchanges([])


@pytest.mark.parametrize("stdout", ["", "1786413978.9", "not a clock at all", "abc def"])
def test_an_unreadable_clock_reply_is_a_collection_error(stdout: str) -> None:
    with pytest.raises(CollectionError):
        parse_host_clock(stdout)


def test_a_well_formed_clock_reply_is_wall_then_monotonic() -> None:
    assert parse_host_clock(" 1786413978.9035127 684.4572976 \n") == (
        1786413978.9035127,
        684.4572976,
    )


# --- the Docker backend's half ----------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_the_docker_backend_reads_a_clock_through_the_nodehost_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run_docker(args, **_kwargs):  # noqa: ANN001
        calls.append(list(args))
        return _FakeCompleted(stdout="1786413978.9 684.45\n")

    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    rows = DockerHostEvidence(container="vslab-nodehost-a").clock_exchanges(2)

    assert len(rows) == 2
    assert calls == [["exec", "vslab-nodehost-a", *HOST_CLOCK_ARGV]] * 2
    assert rows[0]["host_unix_ms"] == pytest.approx(1786413978.9 * 1000.0)
    assert rows[0]["host_monotonic_seconds"] == 684.45


def test_a_docker_clock_that_will_not_answer_is_a_collection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        lambda *_args, **_kwargs: _FakeCompleted(returncode=1, stderr="no such container"),
    )
    with pytest.raises(CollectionError, match="clock"):
        DockerHostEvidence(container="gone").clock_exchanges(1)


def test_the_docker_backend_copies_a_node_journal_out_of_its_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_subprocess_run(args, **_kwargs):  # noqa: ANN001
        calls.append(list(args))
        Path(args[-1]).write_text("node started\n", encoding="utf-8")
        return _FakeCompleted()

    monkeypatch.setattr(docker_runtime.subprocess, "run", fake_subprocess_run)
    local = tmp_path / "journals" / "local" / "shard-0000-primary.log"
    DockerHostEvidence(container="vslab-nodehost-a").collect_node_journal(
        {"logical_id": "shard-0000-primary", "log_file": "/tmp/vsl/run/shard/valkey.log"},
        local,
    )

    assert calls == [
        [
            "docker",
            "cp",
            "vslab-nodehost-a:/tmp/vsl/run/shard/valkey.log",
            local.as_posix(),
        ]
    ]
    assert local.read_text(encoding="utf-8") == "node started\n"


def test_a_docker_journal_copy_that_fails_is_a_collection_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        docker_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: _FakeCompleted(returncode=1, stderr="no such file"),
    )
    with pytest.raises(CollectionError, match="journal"):
        DockerHostEvidence(container="c").collect_node_journal(
            {"logical_id": "n", "log_file": "/tmp/valkey.log"}, tmp_path / "n.log"
        )


def test_a_node_with_no_recorded_log_file_is_a_collection_error(tmp_path: Path) -> None:
    with pytest.raises(CollectionError, match="no recorded log file"):
        DockerHostEvidence(container="c").collect_node_journal(
            {"logical_id": "n"}, tmp_path / "n.log"
        )


# --- the native backend's half ----------------------------------------------


class _FakeTransport:
    """Records what would have been run, and can be made to fail like a network."""

    def __init__(self, *, stdout: str = "1786413978.9 684.45\n") -> None:
        self.commands: list[tuple[str, list[str]]] = []
        self.gets: list[tuple[str, str]] = []
        self.stdout = stdout
        self.fail_run = False
        self.fail_get = False

    def run(self, control_endpoint, argv, *, timeout):  # noqa: ANN001
        argv = [str(item) for item in argv]
        self.commands.append((str(control_endpoint["address"]), argv))
        if self.fail_run:
            raise TransportError("connection reset")
        return CommandResult(
            argv=argv,
            returncode=0,
            stdout=self.stdout,
            stderr="",
            started_at_unix_ms=1_000,
            ended_at_unix_ms=1_010,
        )

    def put(self, control_endpoint, local_path, remote_path, *, timeout):  # noqa: ANN001
        raise AssertionError("host evidence never puts a file")

    def get(self, control_endpoint, remote_path, local_path, *, timeout):  # noqa: ANN001
        self.gets.append((remote_path, str(local_path)))
        if self.fail_get:
            raise TransportError("scp: connection closed")
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        Path(local_path).write_text("node started\n", encoding="utf-8")

    def close(self) -> None:
        return None


def _native(transport: _FakeTransport) -> NativeMultiEcsBackend:
    return NativeMultiEcsBackend(transport=transport)


def test_the_native_backend_asks_the_host_the_same_question_as_the_docker_one() -> None:
    transport = _FakeTransport()
    source = _native(transport).host_evidence(
        {"nodehost_id": "nodehost-az-a-00", "host_control_endpoint": CONTROL}
    )

    rows = source.clock_exchanges(CLOCK_EXCHANGE_COUNT)

    assert len(rows) == CLOCK_EXCHANGE_COUNT
    assert [argv for _address, argv in transport.commands] == [
        list(HOST_CLOCK_ARGV)
    ] * CLOCK_EXCHANGE_COUNT
    assert rows[0]["host_monotonic_seconds"] == 684.45


def test_a_native_clock_read_that_cannot_reach_the_host_is_a_collection_error() -> None:
    transport = _FakeTransport()
    transport.fail_run = True
    source = _native(transport).host_evidence(
        {"nodehost_id": "n", "host_control_endpoint": CONTROL}
    )

    with pytest.raises(CollectionError, match="host clock"):
        source.clock_exchanges(1)


def test_the_native_backend_fetches_the_journal_the_node_record_names(tmp_path: Path) -> None:
    transport = _FakeTransport()
    source = _native(transport).host_evidence(
        {"nodehost_id": "n", "host_control_endpoint": CONTROL}
    )
    local = tmp_path / "journals" / "sim-host-00" / "shard-0000-primary.log"

    source.collect_node_journal(
        {"logical_id": "shard-0000-primary", "log_file": "/tmp/vsl/run/shard/valkey.log"},
        local,
    )

    assert transport.gets == [("/tmp/vsl/run/shard/valkey.log", local.as_posix())]
    assert local.read_text(encoding="utf-8") == "node started\n"


def test_a_native_journal_transfer_failure_is_error_and_not_a_cluster_verdict(
    tmp_path: Path,
) -> None:
    # The acceptance clause's own case. `TransportError` alone reports `FAIL` -
    # the claim that the cluster was observed and found wanting - because
    # `is_collection_failure` answers False for anything it cannot place. §12.1
    # puts 必要证据无法写入 on the collector's side.
    transport = _FakeTransport()
    transport.fail_get = True
    source = _native(transport).host_evidence(
        {"nodehost_id": "n", "host_control_endpoint": CONTROL}
    )

    with pytest.raises(CollectionError, match="journal"):
        source.collect_node_journal(
            {"logical_id": "n", "log_file": "/tmp/valkey.log"}, tmp_path / "n.log"
        )


def test_a_native_load_lane_transfer_failure_is_error_too(tmp_path: Path) -> None:
    # The same defect at the sibling site: item 0.5 extracted this upload and the
    # native implementation let a `TransportError` out where the Docker one has
    # always raised `CollectionError`.
    transport = _FakeTransport()
    transport.fail_get = True
    lane = native_backend_module.NativeLoadLaneHost(
        backend=_native(transport), control_endpoint=CONTROL, install_path="/opt/bin"
    )

    with pytest.raises(CollectionError, match="load lane evidence"):
        lane.collect_evidence("/tmp/vslab-load-lane/formal", tmp_path / "load_lane")
