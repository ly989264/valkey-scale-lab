"""Cross-host evidence: the estimator, both backends, and what the validator refuses.

Roadmap item 1.3. `project/docs/cross_host_evidence_slice_map.md` carries the
derivation.

Three things a hermetic test can prove here, and one it cannot:

  it can  that the estimator keeps the least-delayed exchange, reports the offset
          with the bound that contains the truth, and that a *shifted* clock
          falls outside that bound;
  it can  the argv each backend builds and the class it raises when a transfer
          fails, which is the acceptance's own "ERROR, not silence";
  it can  every refusal the admission validator makes;
  it cannot  that a real host's clock is where the reading says it is. That was
          measured on two simulated hosts instead - slice map §2.4 - and the
          detection half is here, because shifting a simulated host's clock would
          shift the kernel the controller shares with it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from valkey_scale_lab.evidence.validation import validate_raw_sources_by_kind
from valkey_scale_lab.observability.contracts import CollectionError
from valkey_scale_lab.runtime import docker_runtime, native_backend as native_backend_module
from valkey_scale_lab.runtime.docker_runtime import DockerHostEvidence
from valkey_scale_lab.runtime.host_clock import (
    CLOCK_EXCHANGE_COUNT,
    HOST_CLOCK_ARGV,
    parse_host_clock,
    reduce_clock_exchanges,
)
from valkey_scale_lab.runtime.host_evidence import (
    build_host_evidence_document,
    collect_node_journals,
    read_host_clocks,
)
from valkey_scale_lab.runtime.host_transport import CommandResult, TransportError
from valkey_scale_lab.runtime.native_backend import NativeMultiEcsBackend
from valkey_scale_lab.scenarios import load_local_full_flow_definition

DEFINITION = load_local_full_flow_definition()

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


# --- what the lifecycle assembles -------------------------------------------


class _StubBackend:
    """Two nodehosts on two hosts, answering with distinct clocks."""

    def __init__(self) -> None:
        self.journals: list[tuple[str, str]] = []

    def host_evidence(self, nodehost):  # noqa: ANN001
        return _StubSource(self, str(nodehost["nodehost_id"]))


class _StubSource:
    def __init__(self, backend: _StubBackend, nodehost_id: str) -> None:
        self._backend = backend
        self._nodehost_id = nodehost_id

    def clock_exchanges(self, count: int):
        base = 1_000.0 if self._nodehost_id.endswith("00") else 2_000.0
        return [_exchange(base, base + 5.0, base + 10.0) for _ in range(count)]

    def collect_node_journal(self, node, local_path: Path) -> None:  # noqa: ANN001
        self._backend.journals.append((self._nodehost_id, str(node["logical_id"])))
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(f"{node['logical_id']}\n", encoding="utf-8")


NODEHOSTS = [
    {"nodehost_id": "nodehost-az-a-00", "host_id": "sim-host-00", "fleet_id": "sim-a"},
    {"nodehost_id": "nodehost-az-b-00", "host_id": "sim-host-01", "fleet_id": "sim-a"},
]
NODES = [
    {"logical_id": "shard-0000-primary", "nodehost_id": "nodehost-az-a-00"},
    {"logical_id": "shard-0000-replica-00", "nodehost_id": "nodehost-az-b-00"},
]


def test_journals_land_under_the_host_they_came_from(tmp_path: Path) -> None:
    backend = _StubBackend()
    rows = collect_node_journals(backend, NODEHOSTS, NODES, tmp_path)

    assert (tmp_path / "sim-host-00" / "shard-0000-primary.log").is_file()
    assert (tmp_path / "sim-host-01" / "shard-0000-replica-00.log").is_file()
    primary = rows["nodehost-az-a-00"][0]
    assert primary["path"] == "runtime/node_journals/sim-host-00/shard-0000-primary.log"
    assert primary["sha256"] == hashlib.sha256(b"shard-0000-primary\n").hexdigest()
    assert primary["bytes"] == len(b"shard-0000-primary\n")


def test_the_document_attributes_every_surface_to_exactly_one_host(tmp_path: Path) -> None:
    backend = _StubBackend()
    clocks = read_host_clocks(backend, NODEHOSTS)
    journals = collect_node_journals(backend, NODEHOSTS, NODES, tmp_path)

    document = build_host_evidence_document(
        capability_id="local_full_flow",
        scenario="local_full_flow",
        run_id="run-1",
        nodehosts=NODEHOSTS,
        start_clocks=clocks,
        end_clocks=clocks,
        journals=journals,
        load_lane_nodehost_id="nodehost-az-a-00",
        timing={"clock_start_seconds": 0.2},
    )

    assert document["artifact_type"] == "host_evidence"
    assert document["fleet_ids"] == ["sim-a"]
    assert document["host_count"] == 2
    assert [row["host_id"] for row in document["hosts"]] == ["sim-host-00", "sim-host-01"]
    # Exactly one host claims the Load Lane's uploaded directory.
    assert [row["load_lane_dirs"] for row in document["hosts"]] == [["runtime/load_lane"], []]
    # And each claims its own sampler, which is what `static.sampler_id` records.
    assert [row["resource_sampler_ids"] for row in document["hosts"]] == [
        ["nodehost-az-a-00"],
        ["nodehost-az-b-00"],
    ]
    for row in document["hosts"]:
        for boundary in ("start", "end"):
            assert row["clock"][boundary]["uncertainty_ms"] == 5.0


def test_a_docker_run_says_local_rather_than_inventing_a_fleet(tmp_path: Path) -> None:
    # Every Docker nodehost carries `host_id: "local"`, which is true and is
    # exactly why a Docker run is not cross-host evidence.
    nodehosts = [{"nodehost_id": "nodehost-az-a-00", "host_id": "local"}]
    backend = _StubBackend()
    document = build_host_evidence_document(
        capability_id="local_full_flow",
        scenario="local_full_flow",
        run_id="run-1",
        nodehosts=nodehosts,
        start_clocks=read_host_clocks(backend, nodehosts),
        end_clocks=read_host_clocks(backend, nodehosts),
        journals={},
        load_lane_nodehost_id=None,
        timing={},
    )

    assert document["fleet_ids"] == ["local"]
    assert document["host_count"] == 1
    assert "fleet_id" not in document["hosts"][0]


# --- what the validator refuses ---------------------------------------------


def _sources(tmp_path: Path, mutate=None) -> Path:  # noqa: ANN001
    """A minimal admissible bundle, so a test can break exactly one thing."""

    support = __import__(
        "tests.provenance.test_exact_gate_measured_sources", fromlist=["_bundle"]
    )
    base = support._bundle(tmp_path)
    if mutate is not None:
        path = base / "runtime" / "host_evidence.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        mutate(document)
        path.write_text(json.dumps(document) + "\n", encoding="utf-8")
    return base


def _complaints(base: Path) -> str:
    return "; ".join(validate_raw_sources_by_kind(base, 50, DEFINITION).all)


def test_the_unmodified_bundle_is_admissible(tmp_path: Path) -> None:
    assert not validate_raw_sources_by_kind(_sources(tmp_path), 50, DEFINITION)


def test_evidence_attributed_to_no_host_is_refused(tmp_path: Path) -> None:
    base = _sources(tmp_path, lambda doc: doc["hosts"][0].pop("host_id"))
    assert "does not attribute nodehost" in _complaints(base)


def test_an_offset_without_its_bound_is_refused(tmp_path: Path) -> None:
    base = _sources(tmp_path, lambda doc: doc["hosts"][0]["clock"]["start"].pop("uncertainty_ms"))
    assert "requires a measured uncertainty_ms" in _complaints(base)


def test_a_run_clocked_at_only_one_end_is_refused(tmp_path: Path) -> None:
    base = _sources(tmp_path, lambda doc: doc["hosts"][1]["clock"].pop("end"))
    assert "no end-of-run clock reading" in _complaints(base)


def test_a_nodehost_with_no_host_evidence_row_is_refused(tmp_path: Path) -> None:
    base = _sources(tmp_path, lambda doc: doc["hosts"].pop())
    assert "does not account for every nodehost" in _complaints(base)


def test_a_node_with_no_journal_is_refused(tmp_path: Path) -> None:
    base = _sources(tmp_path, lambda doc: doc["hosts"][0]["journals"].pop())
    assert "one journal per observed node" in _complaints(base)


def test_a_node_journalled_by_two_hosts_is_refused(tmp_path: Path) -> None:
    def mutate(doc: dict) -> None:
        doc["hosts"][1]["journals"].append(dict(doc["hosts"][0]["journals"][0]))

    base = _sources(tmp_path, mutate)
    assert "to both" in _complaints(base)


def test_a_journal_whose_file_is_absent_is_refused(tmp_path: Path) -> None:
    base = _sources(tmp_path)
    (base / "runtime" / "node_journals" / "host-a" / "node-0.log").unlink()
    assert "is missing or escapes" in _complaints(base)


def test_a_journal_that_escapes_the_run_is_refused(tmp_path: Path) -> None:
    base = _sources(
        tmp_path, lambda doc: doc["hosts"][0]["journals"][0].update(path="../../etc/passwd")
    )
    assert "is missing or escapes" in _complaints(base)


def test_a_journal_without_a_digest_is_refused(tmp_path: Path) -> None:
    base = _sources(tmp_path, lambda doc: doc["hosts"][0]["journals"][0].update(sha256="short"))
    assert "SHA-256 digest" in _complaints(base)


def test_host_evidence_that_names_another_run_is_refused(tmp_path: Path) -> None:
    base = _sources(tmp_path, lambda doc: doc.update(run_id="someone-elses-run"))
    assert "runtime/host_evidence.json must PASS for the admitted run" in _complaints(base)


def test_host_evidence_with_no_hosts_at_all_is_refused(tmp_path: Path) -> None:
    base = _sources(tmp_path, lambda doc: doc.update(hosts=[]))
    assert "requires at least one attributed host" in _complaints(base)
