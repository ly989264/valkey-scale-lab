"""The native backend, proven against a fake transport.

What a fake can prove is the argv the backend builds for every operation, the
record shapes it returns, its refusals, and the placement join - the parts a real
fleet would prove slowly and a fake proves exhaustively. What it cannot prove is
that the argv does what it says on a host; that is the development ladder's, and
these tests do not claim it.

The transport double records every call, so a test asserts on what would have
been run rather than on a mock's call count.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from valkey_scale_lab.runtime import native_backend as native_backend_module
from valkey_scale_lab.nodehost_density import NodehostDensityError, build_nodehost_density_plan
from valkey_scale_lab.runtime.backends import resolve_backend
from valkey_scale_lab.runtime.host_inventory import (
    HostInventoryError,
    load_host_inventory,
)
from valkey_scale_lab.runtime.host_transport import (
    CONTROL_PATH_MAX_BYTES,
    CommandResult,
    MultiplexedSshTransport,
    TransportError,
)
from valkey_scale_lab.runtime.docker_runtime import DockerNodeBackend
from valkey_scale_lab.runtime.native_backend import (
    NATIVE_INSTALL_ROOT,
    NativeMultiEcsBackend,
    NativeRuntimeError,
    build_native_backend_for_run,
)

@pytest.fixture()
def fast_clock(monkeypatch: pytest.MonkeyPatch):
    """Advance the backend's bounded waits without waiting.

    Both waits here are wall-clock bounded loops - 30 s for readiness, 10 s then
    30 s for a process to disappear - and a test that lets them run really does
    take that long. The loop bodies are what these tests are about.
    """
    ticks = {"now": 0.0}

    def monotonic() -> float:
        ticks["now"] += 1.0
        return ticks["now"]

    monkeypatch.setattr(native_backend_module.time, "monotonic", monotonic)
    monkeypatch.setattr(native_backend_module.time, "sleep", lambda _seconds: None)
    return ticks


CONTROL = {
    "address": "10.0.0.11",
    "port": 22,
    "user": "ops",
    "private_key_path": "/keys/id_ed25519",
    "known_hosts_path": "/keys/known_hosts",
}


class FakeTransport:
    """Records every command and transfer, and answers whatever a test scripts."""

    def __init__(self, responses: dict[str, tuple[int, str, str]] | None = None) -> None:
        self.commands: list[tuple[str, list[str]]] = []
        self.puts: list[tuple[str, str, str]] = []
        self.gets: list[tuple[str, str, str]] = []
        self.closed = False
        self._responses = responses or {}
        self.default = (0, "", "")

    def respond(self, needle: str, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self._responses[needle] = (returncode, stdout, stderr)

    def run(self, control_endpoint, argv, *, timeout):  # noqa: ANN001
        argv = [str(item) for item in argv]
        self.commands.append((str(control_endpoint["address"]), argv))
        joined = " ".join(argv)
        returncode, stdout, stderr = self.default
        for needle, response in self._responses.items():
            if needle in joined:
                returncode, stdout, stderr = response
                break
        return CommandResult(
            argv=argv,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            started_at_unix_ms=1_000,
            ended_at_unix_ms=1_050,
        )

    def put(self, control_endpoint, local_path, remote_path, *, timeout):  # noqa: ANN001
        self.puts.append((str(control_endpoint["address"]), str(local_path), remote_path))

    def get(self, control_endpoint, remote_path, local_path, *, timeout):  # noqa: ANN001
        self.gets.append((str(control_endpoint["address"]), remote_path, str(local_path)))

    def close(self) -> None:
        self.closed = True

    def last(self) -> list[str]:
        return self.commands[-1][1]

    def ran(self, needle: str) -> bool:
        return any(needle in " ".join(argv) for _address, argv in self.commands)


def _manifest(tmp_path: Path, *, hosts: int = 2, first_port: int = 7400, per_host: int = 60) -> Path:
    records = []
    for index in range(hosts):
        records.append(
            {
                "host_id": f"host-{index:02d}",
                "availability_zone": f"az-{'ab'[index % 2]}",
                "data_address": f"10.0.0.{index + 1}",
                "control_endpoint": {**CONTROL, "address": f"192.168.0.{index + 1}"},
                "client_endpoint": {
                    "address": f"192.168.0.{index + 1}",
                    "port_range": {"first": first_port, "last": first_port + per_host - 1},
                },
                "os": {"kind": "linux"},
                "capacity": {"cpus": 4, "memory_bytes": 8 << 30},
            }
        )
    path = tmp_path / "inventory.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "artifact_type": "host_inventory",
                "fleet_id": "fleet-a",
                "host_count": len(records),
                "hosts": records,
            }
        ),
        encoding="utf-8",
    )
    return path


def _bundle(tmp_path: Path, *, version: str = "9.1.0") -> Path:
    """A minimal bundle whose digests are real, because the verifier recomputes them."""
    import hashlib

    root = tmp_path / "bundle"
    (root / "bin").mkdir(parents=True)
    binaries = {}
    for name in ("valkey-server", "valkey-cli", "memtier_benchmark"):
        member = root / "bin" / name
        member.write_bytes(name.encode())
        binaries[name] = {
            "path": f"bin/{name}",
            "sha256": hashlib.sha256(name.encode()).hexdigest(),
        }
    archive = root / "pinned.tar.gz"
    archive.write_bytes(b"archive-bytes")
    (root / "bundle_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "artifact_type": "native_build_bundle",
                "bundle_name": "pinned",
                "architecture": "arm64",
                "valkey_version": version,
                "source_sha256": "a" * 64,
                "patch_sha256": "b" * 64,
                "memtier_version": "2.5.1",
                "memtier_source_sha256": "c" * 64,
                "binaries": binaries,
                "archive": {
                    "path": "pinned.tar.gz",
                    "sha256": hashlib.sha256(b"archive-bytes").hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    return root


def _nodehost(**overrides):
    base = {
        "nodehost_id": "nodehost-az-a-00",
        "az_id": "az-a",
        "ordinal": 0,
        "container_name": "vslab-run-1-nodehost-az-a-00",
        "bundle_name": "vslab-bundle-run-1-nodehost-az-a-00",
        "remote_bundle_dir": "/tmp/vslab-bundle-run-1-nodehost-az-a-00",
        "bundle_artifact_dir": "/local/bundles/vslab-bundle-run-1-nodehost-az-a-00",
        "logical_node_count": 3,
        "host_id": "host-00",
        "host_control_endpoint": dict(CONTROL),
        "host_data_address": "10.0.0.1",
        "host_client_address": "192.168.0.1",
        "native_bundle_digest": "d" * 64,
    }
    base.update(overrides)
    return base


def _node(**overrides):
    base = {
        "logical_id": "node-000",
        "nodehost_id": "nodehost-az-a-00",
        # `_prepare_process_node_metadata` writes this on every node.
        "run_id": "run-1",
        "client_port": 7400,
        "pid": 4242,
        "data_dir": "/tmp/valkey-scale-lab/run-1/node-000",
        "config_file": "/tmp/valkey-scale-lab/run-1/node-000/valkey.conf",
        "pid_file": "/tmp/valkey-scale-lab/run-1/node-000/valkey.pid",
        "host_control_endpoint": dict(CONTROL),
        "host_id": "host-00",
        "native_bundle_digest": "d" * 64,
    }
    base.update(overrides)
    return base


def _backend(transport: FakeTransport, tmp_path: Path | None = None) -> NativeMultiEcsBackend:
    backend = NativeMultiEcsBackend(
        transport=transport,
        inventory_path=_manifest(tmp_path) if tmp_path else None,
    )
    backend._placed["nodehost-az-a-00"] = {
        "host_control_endpoint": dict(CONTROL),
        "host_client_address": "192.168.0.1",
        "native_bundle_digest": "d" * 64,
    }
    return backend


# --------------------------------------------------------------------------
# the fleet manifest
# --------------------------------------------------------------------------


def test_a_manifest_is_read_into_neutral_records(tmp_path: Path) -> None:
    inventory = load_host_inventory(_manifest(tmp_path))
    assert [host.host_id for host in inventory.hosts] == ["host-00", "host-01"]
    assert inventory.by_az().keys() == {"az-a", "az-b"}
    record = inventory.placement_records()[0]
    assert record["data_address"] == "10.0.0.1"
    assert record["client_port_first"] == 7400


def test_a_manifest_that_is_not_one_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({"artifact_type": "something_else", "hosts": []}), encoding="utf-8")
    with pytest.raises(HostInventoryError, match="not a 'host_inventory'"):
        load_host_inventory(path)


def test_a_host_missing_an_address_is_refused(tmp_path: Path) -> None:
    manifest = json.loads(_manifest(tmp_path).read_text())
    del manifest["hosts"][0]["data_address"]
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(HostInventoryError, match="data_address"):
        load_host_inventory(path)


def test_a_missing_manifest_names_the_path(tmp_path: Path) -> None:
    with pytest.raises(HostInventoryError, match="no fleet manifest"):
        load_host_inventory(tmp_path / "absent.json")


# --------------------------------------------------------------------------
# placement - the join, and its two refusals
# --------------------------------------------------------------------------


def _plan(fleet_hosts, *, nodes_per_az: int = 2, port_base: int = 7400, nodehosts_per_az: int = 1):
    nodes = []
    ordinal = 0
    for az in ("az-a", "az-b"):
        for index in range(nodes_per_az):
            nodes.append(
                {
                    "logical_id": f"node-{ordinal:03d}",
                    "az_id": az,
                    "ordinal": ordinal,
                    "role": "primary" if index == 0 else "replica",
                    "shard_id": f"shard-{index}",
                    "client_port": port_base + ordinal,
                    "cluster_bus_port": port_base + 10000 + ordinal,
                }
            )
            ordinal += 1
    config = {
        "runtime": {"nodehosts_per_az": nodehosts_per_az, "max_logical_nodes_per_nodehost": 25},
        "network": {"azs": ["az-a", "az-b"], "virtual_az_mode": "multi"},
        "cluster": {"replicas_per_shard": 1},
    }
    return build_nodehost_density_plan(
        config=config,
        nodes=nodes,
        run_id="run-1",
        assign=True,
        fleet_hosts=fleet_hosts,
        runtime_type="native_multi_ecs",
    )


def test_placement_joins_nodehosts_to_hosts_by_availability_zone(tmp_path: Path) -> None:
    fleet = load_host_inventory(_manifest(tmp_path)).placement_records()
    plan = _plan(fleet)
    placed = {item["nodehost_id"]: item for item in plan["nodehosts"]}
    assert len(placed) == 2
    for nodehost in placed.values():
        assert nodehost["host_id"] in {"host-00", "host-01"}
        assert nodehost["host_control_endpoint"]["user"] == "ops"
        # The az the plan asked for is the az the host is in - not merely some host.
        expected_az = "az-a" if nodehost["host_id"] == "host-00" else "az-b"
        assert nodehost["az_id"] == expected_az
    assert {item["host_id"] for item in placed.values()} == {"host-00", "host-01"}


def test_placement_refuses_two_nodehosts_on_one_host(tmp_path: Path) -> None:
    """The constraint the fault actuator depends on.

    `pause_nodehost` and `isolate_nodehost` act on a host. Two nodehosts sharing
    one would make a host-scoped fault take out a domain the plan believed was
    independent, and the fault evidence would describe something that never held.
    """
    fleet = load_host_inventory(_manifest(tmp_path)).placement_records()
    with pytest.raises(NodehostDensityError, match="exactly one nodehost per host"):
        _plan(fleet, nodehosts_per_az=2, nodes_per_az=4)


def test_placement_refuses_ports_outside_a_hosts_declared_range(tmp_path: Path) -> None:
    fleet = load_host_inventory(_manifest(tmp_path, first_port=31000, per_host=60)).placement_records()
    with pytest.raises(NodehostDensityError, match="31000-31059"):
        _plan(fleet, port_base=7400)


def test_placement_checks_client_ports_and_not_the_cluster_bus(tmp_path: Path) -> None:
    """The bus is peer traffic on the fleet's own network.

    A host's published client range says nothing about it, so requiring the bus
    ports to fall inside that range would refuse every correct configuration -
    `cluster_bus_port_base` is ten thousand above `port_base` by convention.
    """
    fleet = load_host_inventory(_manifest(tmp_path, first_port=7400, per_host=10)).placement_records()
    plan = _plan(fleet, port_base=7400)
    bus_ports = [17400, 17401, 17402, 17403]
    assert all(port > 7409 for port in bus_ports)
    assert len(plan["nodehosts"]) == 2


def test_a_plan_with_no_fleet_is_untouched() -> None:
    """Every Docker run takes this path, and must be byte-identical."""
    plan = _plan(None)
    assert {item["host_id"] for item in plan["nodehosts"]} == {"local"}
    assert all("host_control_endpoint" not in item for item in plan["nodehosts"])


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------


def test_verify_image_returns_the_bundle_evidence_under_the_keys_the_run_reads(tmp_path: Path) -> None:
    backend = NativeMultiEcsBackend(transport=FakeTransport(), bundle_dir=_bundle(tmp_path))
    evidence = backend.verify_image("valkey-scale-lab/valkey:9.1.0-myslots")
    # `_write_cluster_myslots_report` reads exactly this key off the preflight
    # result and stamps it on every observed node.
    assert "valkey_server_sha256" in evidence
    assert evidence["status"] == "PASS"
    assert "cluster_myslots_command" in evidence["not_verified"]
    assert evidence["image"] == "valkey-scale-lab/valkey:9.1.0-myslots"


def test_verify_image_refuses_a_bundle_that_is_not_the_build_the_run_named(tmp_path: Path) -> None:
    backend = NativeMultiEcsBackend(transport=FakeTransport(), bundle_dir=_bundle(tmp_path, version="9.0.4"))
    with pytest.raises(NativeRuntimeError, match="not the one that would be shipped"):
        backend.verify_image("valkey-scale-lab/valkey:9.1.0-myslots")


def test_verify_image_refuses_when_no_bundle_was_configured() -> None:
    with pytest.raises(NativeRuntimeError, match="native_bundle_dir"):
        NativeMultiEcsBackend(transport=FakeTransport()).verify_image("valkey:9.1.0")


def test_a_native_run_needs_both_a_fleet_and_a_build() -> None:
    with pytest.raises(NativeRuntimeError, match="host_inventory_path and runtime.native_bundle_dir"):
        build_native_backend_for_run({})
    with pytest.raises(NativeRuntimeError, match="native_bundle_dir"):
        build_native_backend_for_run({"host_inventory_path": "/fleet.json"})


# --------------------------------------------------------------------------
# ownership
# --------------------------------------------------------------------------


def test_reclaim_run_clears_the_runs_own_path_on_every_host(tmp_path: Path) -> None:
    transport = FakeTransport()
    backend = NativeMultiEcsBackend(transport=transport, inventory_path=_manifest(tmp_path))
    backend.reclaim_run(capability_id="local_full_flow", run_id="run-1")
    assert len(transport.commands) == 2
    for _address, argv in transport.commands:
        assert "/tmp/valkey-scale-lab/run-1" in argv[-1]
        assert "kill -KILL" in argv[-1]
    assert {address for address, _ in transport.commands} == {"192.168.0.1", "192.168.0.2"}


def test_reclaim_run_reports_a_host_it_could_not_clear(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.default = (1, "", "permission denied")
    backend = NativeMultiEcsBackend(transport=transport, inventory_path=_manifest(tmp_path))
    with pytest.raises(NativeRuntimeError, match="could not clear every host"):
        backend.reclaim_run(capability_id="local_full_flow", run_id="run-1")


def test_create_network_refuses_a_fleet_whose_hosts_cannot_see_each_other(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.respond("ip route get", 1, "", "unreachable")
    backend = NativeMultiEcsBackend(transport=transport, inventory_path=_manifest(tmp_path))
    with pytest.raises(NativeRuntimeError, match="not one network scope"):
        backend.create_network(network_name="run-net", capability_id="local_full_flow", run_id="run-1")


def test_create_network_records_the_scope_it_verified(tmp_path: Path) -> None:
    transport = FakeTransport()
    backend = NativeMultiEcsBackend(transport=transport, inventory_path=_manifest(tmp_path))
    backend.create_network(network_name="run-net", capability_id="local_full_flow", run_id="run-1")
    assert backend._network_scope == "run-net"
    assert transport.ran("ip route get 10.0.0.2")


# --------------------------------------------------------------------------
# claiming a host
# --------------------------------------------------------------------------


def _started_backend(tmp_path: Path, transport: FakeTransport) -> NativeMultiEcsBackend:
    backend = NativeMultiEcsBackend(transport=transport, bundle_dir=_bundle(tmp_path))
    backend.verify_image("valkey:9.1.0")
    return backend


def test_start_nodehost_installs_the_pinned_bundle_and_reports_the_peer_address(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.respond("test -f", 1)  # not installed yet
    transport.respond("ls -A", 0, "")  # no residue
    backend = _started_backend(tmp_path, transport)
    nodehost = _nodehost()
    del nodehost["native_bundle_digest"]

    address = backend.start_nodehost(
        nodehost,
        network_name="run-net",
        image="valkey:9.1.0",
        capability_id="local_full_flow",
        scenario="local_full_flow",
        run_id="run-1",
    )

    assert address.handle == "vslab-run-1-nodehost-az-a-00"
    # The peer address, which is what `cluster-announce-ip` carries - not the
    # address the controller speaks RESP to.
    assert address.address == "10.0.0.1"
    assert transport.puts and transport.puts[0][1].endswith("pinned.tar.gz")
    assert transport.ran("sha256sum")
    assert transport.ran("tar -xzf")


def test_start_nodehost_skips_a_transfer_when_the_digest_is_already_installed(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.respond("test -f", 0)  # the marker is there
    transport.respond("ls -A", 0, "")
    backend = _started_backend(tmp_path, transport)
    backend.start_nodehost(
        _nodehost(),
        network_name="run-net",
        image="valkey:9.1.0",
        capability_id="local_full_flow",
        scenario="local_full_flow",
        run_id="run-1",
    )
    assert transport.puts == []
    assert not transport.ran("tar -xzf")


def test_start_nodehost_refuses_a_host_still_holding_this_runs_state(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.respond("ls -A", 0, "node-000")
    backend = _started_backend(tmp_path, transport)
    with pytest.raises(NativeRuntimeError, match="already carries state"):
        backend.start_nodehost(
            _nodehost(),
            network_name="run-net",
            image="valkey:9.1.0",
            capability_id="local_full_flow",
            scenario="local_full_flow",
            run_id="run-1",
        )


def test_start_nodehost_refuses_a_nodehost_that_was_never_placed(tmp_path: Path) -> None:
    backend = _started_backend(tmp_path, FakeTransport())
    nodehost = _nodehost()
    del nodehost["host_control_endpoint"]
    with pytest.raises(HostInventoryError, match="never placed"):
        backend.start_nodehost(
            nodehost,
            network_name="run-net",
            image="valkey:9.1.0",
            capability_id="local_full_flow",
            scenario="local_full_flow",
            run_id="run-1",
        )


# --------------------------------------------------------------------------
# the run bundle and the processes
# --------------------------------------------------------------------------


def test_the_run_bundle_is_sent_and_installed_where_the_lifecycle_expects_it(tmp_path: Path) -> None:
    transport = FakeTransport()
    backend = _backend(transport)
    nodehost = _nodehost()
    backend.send_bundle(nodehost)
    backend.install_bundle(nodehost)
    assert transport.puts == [
        ("10.0.0.11", "/local/bundles/vslab-bundle-run-1-nodehost-az-a-00", "/tmp/")
    ]
    assert transport.last() == ["sh", "/tmp/vslab-bundle-run-1-nodehost-az-a-00/install.sh"]


def test_starting_processes_puts_the_pinned_binaries_on_path(tmp_path: Path) -> None:
    """`start_all.sh` invokes bare `valkey-server`, so `PATH` has to carry it.

    Supplied per command rather than written into the host's profile: a run must
    not leave a host's environment changed behind it.
    """
    transport = FakeTransport()
    backend = _backend(transport)
    backend.start_node_processes(_nodehost())
    argv = transport.last()
    assert argv[0:2] == ["sh", "-c"]
    assert argv[2].startswith(f"PATH={NATIVE_INSTALL_ROOT}/dddddddddddddddd/bin:$PATH; ")
    assert "start_all.sh" in argv[2]


def test_collect_node_pids_parses_what_the_bundle_script_prints(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.respond("collect_pidfiles.sh", 0, "node-000\t4242\nnode-001\t4243\n")
    backend = _backend(transport)
    assert backend.collect_node_pids(_nodehost()) == {"node-000": 4242, "node-001": 4243}


def test_collect_node_pids_refuses_a_value_that_is_not_a_pid(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.respond("collect_pidfiles.sh", 0, "node-000\tMISSING\n")
    backend = _backend(transport)
    with pytest.raises(NativeRuntimeError, match="invalid pidfile value"):
        backend.collect_node_pids(_nodehost())


def test_client_host_is_the_client_endpoint_and_not_the_peer_address() -> None:
    """The mistake the three-address manifest exists to make visible.

    Returning the peer address here yields a cluster that forms and cannot be
    reached; returning the client address as the peer address yields one that is
    reachable and never forms.
    """
    backend = _backend(FakeTransport())
    assert backend.client_host(_node()) == "192.168.0.1"


def test_client_host_refuses_a_node_whose_nodehost_this_run_never_started() -> None:
    backend = _backend(FakeTransport())
    with pytest.raises(NativeRuntimeError, match="has not started"):
        backend.client_host(_node(nodehost_id="nodehost-az-z-99"))


# --------------------------------------------------------------------------
# one node's process
# --------------------------------------------------------------------------


def test_stop_node_asks_the_server_to_leave_then_confirms_the_process_is_gone(fast_clock) -> None:
    transport = FakeTransport()
    transport.respond("VSLAB_GONE", 0, "VSLAB_GONE")
    transport.respond("/proc/4242/stat", 0, "VSLAB_GONE")
    backend = _backend(transport)
    records = backend.stop_node(_node(), command_kind="owned_valkey_process_restart_stop")

    assert [record["command_kind"] for record in records] == [
        "owned_valkey_process_restart_stop_shutdown_nosave"
    ]
    assert records[0]["status"] == "PASS"
    assert set(records[0]) == {
        "command_kind", "argv", "started_at_unix_ms", "ended_at_unix_ms",
        "status", "stdout_tail", "stderr_tail", "returncode",
    }
    assert transport.ran("SHUTDOWN NOSAVE")
    assert transport.ran("/proc/4242/stat")


def test_stop_node_falls_back_to_term_when_the_server_does_not_leave(fast_clock) -> None:
    transport = FakeTransport()
    responses = {"count": 0}

    original = transport.run

    def run(control_endpoint, argv, *, timeout):  # noqa: ANN001
        joined = " ".join(str(item) for item in argv)
        if "/proc/4242/stat" in joined:
            responses["count"] += 1
            # Still alive until the TERM has been sent.
            transport.default = (0, "VSLAB_ALIVE" if not transport.ran("kill -TERM") else "VSLAB_GONE", "")
        return original(control_endpoint, argv, timeout=timeout)

    transport.run = run  # type: ignore[method-assign]
    backend = _backend(transport)
    records = backend.stop_node(_node(), command_kind="owned")
    assert [record["command_kind"] for record in records] == [
        "owned_shutdown_nosave",
        "owned_kill_term_fallback",
    ]


def test_start_node_with_a_fresh_identity_removes_the_dataset_as_well(
    tmp_path: Path, fast_clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`313cacc9` in a second implementation.

    Removing only `nodes.conf` leaves a `dump.rdb` behind, and `CLUSTER
    REPLICATE` refuses a node that still holds keys. It looked intermittent
    because the RDB is only sometimes on disk.
    """
    transport = FakeTransport()
    backend = _backend(transport)
    # The readiness poll speaks RESP over a socket, which a hermetic test has
    # nothing to answer with. Refusing to connect is what a node that has not
    # come up yet does anyway, and the commands issued before giving up are what
    # this test is about.
    monkeypatch.setattr(
        backend, "_ping", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("refused"))
    )
    with pytest.raises(NativeRuntimeError, match="did not restart"):
        backend.start_node(_node(), fresh_cluster_identity=True)
    discard = [argv for _a, argv in transport.commands if "nodes.conf" in " ".join(argv)]
    assert discard, "the fresh-identity path must discard the prior state"
    assert "dump.rdb" in " ".join(discard[0])


# --------------------------------------------------------------------------
# the actuator
# --------------------------------------------------------------------------


def test_kill_node_sends_kill_and_records_whether_the_process_went(fast_clock) -> None:
    transport = FakeTransport()
    transport.respond("/proc/4242/stat", 0, "VSLAB_GONE")
    backend = _backend(transport)
    records = backend.kill_node(_node())
    assert len(records) == 1
    assert records[0]["result"] == "OK"
    assert records[0]["status"] == "PASS"
    assert "action" in records[0]
    assert transport.ran("kill -KILL 4242")


def test_kill_node_reports_a_failure_to_act_rather_than_raising(fast_clock) -> None:
    """§9.1: an actuator that could not act is a tool error, reported.

    Raising would take the verdict away from the caller, which owns it.
    """
    transport = FakeTransport()
    transport.respond("kill -KILL", 1, "", "no such process")
    transport.respond("/proc/4242/stat", 0, "VSLAB_ALIVE")
    backend = _backend(transport)
    records = backend.kill_node(_node())
    assert records[0]["status"] == "FAIL"
    assert "process_gone=False" in records[0]["result"]


def test_pause_and_resume_a_node_signal_that_process_only() -> None:
    transport = FakeTransport()
    backend = _backend(transport)
    assert backend.pause_node(_node())[0]["command_kind"] == "owned_valkey_process_pause"
    assert transport.ran("kill -STOP 4242")
    assert backend.resume_node(_node())[0]["command_kind"] == "owned_valkey_process_resume"
    assert transport.ran("kill -CONT 4242")


def test_pause_nodehost_signals_every_process_this_run_started_there() -> None:
    """Not `docker pause`'s cgroup freeze, and not the host either.

    Suspending the host would take sshd with it and leave the actuator unable to
    undo its own action. The unit is the run's own processes, which is the same
    observable fault by a mechanism this backend owns.
    """
    transport = FakeTransport()
    backend = _backend(transport)
    record = backend.pause_nodehost(_nodehost())[0]
    assert record["command_kind"] == "owned_nodehost_pause"
    argv = transport.last()
    assert "/tmp/valkey-scale-lab/run-1" in argv[-1]
    assert "kill -STOP" in argv[-1]


def test_the_actuator_signals_what_is_running_not_what_a_pidfile_remembers() -> None:
    """Roadmap item 1.4 §8.3, decided by roadmap item 1.5's own measurement.

    The actuator used to enumerate `<run_root>/*/valkey.pid`, on the argument
    that a pidfile is current for a node that is running. Measured on two hosts
    after a real `kill_node`: **2 pidfiles, 1 live process**, because a
    SIGKILLed node leaves its pidfile holding a dead pid. The count
    self-corrected, but the actuator had attempted a signal to a pid it did not
    own - the collateral-signal risk on a busy host.

    It now walks `/proc` by working directory, the one notion of "what is
    running" both cleanup paths already share, and the pidfile is not consulted.
    """
    transport = FakeTransport()
    backend = _backend(transport)

    for act, signal in ((backend.pause_nodehost, "STOP"), (backend.resume_nodehost, "CONT")):
        act(_nodehost())
        script = transport.last()[-1]
        assert "valkey.pid" not in script
        assert "/proc/" in script and "cwd" in script
        assert f'kill -{signal} "$pid"' in script


def test_isolating_a_host_keeps_only_the_channel_that_can_undo_it() -> None:
    transport = FakeTransport()
    backend = _backend(transport)
    records = backend.isolate_nodehost(_nodehost())
    script = transport.commands[0][1][-1]
    assert "iptables -N VSLAB-NODEHOST-AZ-A-00" in script
    assert "-j DROP" in script
    # The control port is read from the session rather than assumed, because the
    # manifest's port and the port sshd listens on differ whenever the endpoint
    # is forwarded.
    assert "SSH_CONNECTION" in script
    assert '--dport "$ctl" -j RETURN' in script
    assert records[0]["command_kind"] == "owned_nodehost_network_disconnect"


def test_a_failed_isolation_undoes_itself_and_is_a_tool_error() -> None:
    transport = FakeTransport()
    transport.respond("iptables -N", 1, "", "iptables not permitted")
    backend = _backend(transport)
    with pytest.raises(NativeRuntimeError, match="could not isolate"):
        backend.isolate_nodehost(_nodehost())
    assert transport.ran("iptables -D INPUT")


def test_an_isolation_whose_rules_are_not_installed_is_refused() -> None:
    """Confirming is part of the operation, not a second call.

    A backend that reported success without checking would let the stage judge a
    partition that never happened.
    """
    transport = FakeTransport()
    # The confirm, not the install: the install script contains `iptables -C
    # INPUT -j <chain> 2>/dev/null ||` too, and matching that would test the
    # wrong failure.
    transport.respond("&& iptables -C OUTPUT", 1, "", "no chain")
    backend = _backend(transport)
    with pytest.raises(NativeRuntimeError, match="are not installed"):
        backend.isolate_nodehost(_nodehost())


def test_rejoining_removes_the_chain_and_tolerates_it_being_gone() -> None:
    transport = FakeTransport()
    backend = _backend(transport)
    record = backend.rejoin_nodehost(_nodehost())[0]
    script = transport.last()[-1]
    assert "iptables -X VSLAB-NODEHOST-AZ-A-00" in script
    assert script.endswith("exit 0")
    assert record["command_kind"] == "owned_nodehost_network_connect"


# --------------------------------------------------------------------------
# evidence
# --------------------------------------------------------------------------


def test_the_resource_agent_ships_the_package_and_launches_the_same_module() -> None:
    """§11.1's sampler is unchanged; only how it gets there differs."""
    transport = FakeTransport()
    backend = _backend(transport)
    agent = backend.resource_sampler(
        [_node()], sampler_id="nodehost-az-a-00", processes=[("node-000", 4242)], expected_gone=[]
    )
    agent.start()
    assert any(remote.endswith("valkey_scale_lab") for _a, _l, remote in transport.puts)
    assert transport.ran("valkey_scale_lab.observability.resource_agent")
    agent.mark_expected_gone_active()
    assert transport.ran("expected_gone_active")


def test_the_resource_agent_lives_under_the_run_root_so_teardown_reaches_it() -> None:
    """Roadmap item 1.4: a sampler's files were outside every ownership mark.

    `sampler_id` is the `nodehost_id` and names no run, so
    `/tmp/vslab-resource-agent/<nodehost_id>` said nothing about whose it was and
    nothing removed it. Under the run root it needs no removal step of its own,
    and a sampler still running after an abort has its cwd inside the tree the
    process scan walks.
    """
    transport = FakeTransport()
    backend = _backend(transport)
    agent = backend.resource_sampler(
        [_node()], sampler_id="nodehost-az-a-00", processes=[("node-000", 4242)], expected_gone=[]
    )
    agent.start()
    root = "/tmp/valkey-scale-lab/run-1/.resource-agent"
    assert all(remote.startswith(root) for _a, _l, remote in transport.puts)
    assert not transport.ran("/tmp/vslab-resource-agent")
    launched = [argv for _a, argv in transport.commands if "resource_agent" in " ".join(argv)]
    assert launched and f"cd {root}" in " ".join(launched[0])


def test_both_backends_expose_the_identity_the_observation_layer_reads() -> None:
    """The attribute `ResourceSampler` did not declare, and a run died on.

    `observability/stability.py` and `resource_observation.py` both read
    `runner.sampler.sampler_id` and `runner.sampler.processes` to say which host
    a sample came from. Only the Docker agent carried it; the native one
    satisfied the protocol as written and failed 340 s into the first native
    exact-30 with `'NativeResourceAgent' object has no attribute 'sampler'`.

    Asserted against *both* backends and through the same expression the
    observation layer uses, because a test that checked only the new backend
    would not have stopped the protocol under-stating its contract in the first
    place.
    """
    native = _backend(FakeTransport()).resource_sampler(
        [_node()], sampler_id="nodehost-az-a-00", processes=[("node-000", 4242)], expected_gone=[]
    )
    docker = DockerNodeBackend().resource_sampler(
        [{"nodehost_container_id": "abc123"}],
        sampler_id="nodehost-az-a-00",
        processes=[("node-000", 4242)],
        expected_gone=[],
    )

    for agent in (native, docker):
        assert agent.sampler.sampler_id == "nodehost-az-a-00"
        assert [
            (process.logical_id, process.pid) for process in agent.sampler.processes
        ] == [("node-000", 4242)]


def test_a_sampler_needs_a_node_to_locate_its_host() -> None:
    backend = _backend(FakeTransport())
    with pytest.raises(NativeRuntimeError, match="at least one node"):
        backend.resource_sampler([], sampler_id="s", processes=[], expected_gone=[])


def test_the_load_lane_runs_on_the_nodes_own_host_and_is_collected_back(tmp_path: Path) -> None:
    transport = FakeTransport()
    backend = _backend(transport)
    lane = backend.load_lane_host(_node())
    # memtier runs beside the node, so the node answers on that host's loopback.
    assert lane.seed_host == "127.0.0.1"
    lane.collect_evidence("/tmp/lane", tmp_path / "out")
    assert transport.gets == [("10.0.0.11", "/tmp/lane/.", str(tmp_path / "out"))]


def test_a_transport_that_cannot_express_a_local_argv_says_so() -> None:
    """The Load Lane needs an argv it can spawn, not a call it can make.

    The argv is recorded evidence - the lane reports it and the stability
    observation keeps it - so a transport with no local form has to refuse
    rather than quietly run the workload some other way.
    """
    backend = _backend(FakeTransport())
    with pytest.raises(NativeRuntimeError, match="cannot express a load-lane command"):
        backend.load_lane_host(_node()).command(["memtier_benchmark"], remote_dir="/tmp/lane")


# --------------------------------------------------------------------------
# teardown
# --------------------------------------------------------------------------


def _state(**overrides):
    base = {
        "capability_id": "local_full_flow",
        "scenario": "local_full_flow",
        "backend_id": "native_multi_ecs",
        "runtime": {"type": "native_multi_ecs", "run_id": "run-1"},
        "nodehosts": [_nodehost()],
        "nodes": [_node(), _node(logical_id="node-001", pid=4243)],
    }
    base.update(overrides)
    return base


def test_release_run_terminates_removes_and_then_measures_what_is_left() -> None:
    transport = FakeTransport()
    backend = NativeMultiEcsBackend(transport=transport)
    teardown = backend.release_run(_state())
    kinds = [action["action"] for action in teardown.actions]
    assert kinds == ["terminate", "verify_exit", "remove", "remove", "scan"]
    assert [action["type"] for action in teardown.actions][2:4] == [
        "nodehost_firewall_rules",
        "nodehost_run_state",
    ]
    assert teardown.resources_remaining == []
    assert teardown.errors == []
    assert transport.ran("rm -rf /tmp/valkey-scale-lab/run-1")


def test_release_run_terminates_what_is_alive_not_what_state_remembers() -> None:
    """Roadmap item 1.4's central change, and the measurement behind it.

    `state.json` is last written before the management matrix, so by cleanup the
    rolling restart and the fault matrix have replaced every pid in it - fifty
    pids and zero overlap on both frozen baselines. Teardown therefore signals
    nothing state names; it asks the host which processes are running out of this
    run's tree and signals those.
    """
    transport = FakeTransport()
    backend = NativeMultiEcsBackend(transport=transport)
    teardown = backend.release_run(_state())

    assert not transport.ran("kill -TERM 4242")
    assert not transport.ran("kill -TERM 4243")
    signalling = [
        " ".join(argv) for _a, argv in transport.commands if "kill -TERM" in " ".join(argv)
    ]
    assert len(signalling) == 1
    # By working directory, prefix-safely, out of /proc - never by argv.
    assert 'readlink "$entry/cwd"' in signalling[0]
    assert 'case "$cwd/" in "$root"/*' in signalling[0]
    assert "ps -eo args=" not in signalling[0]
    # What state believed is still recorded beside what was signalled: the gap
    # between them is the evidence for the staleness.
    terminate = teardown.actions[0]
    assert terminate["state_pid_count"] == 2
    assert terminate["pid_count"] == 0


def test_release_run_continues_a_suspended_process_before_terminating_it() -> None:
    """A process the fault actuator suspended cannot act on `TERM`.

    A run aborted with a nodehost paused would otherwise sit out the whole
    termination wait and be killed at the end of it. The actuator is entitled to
    leave a domain suspended; coping is teardown's job.
    """
    transport = FakeTransport()
    NativeMultiEcsBackend(transport=transport).release_run(_state())
    terminate = next(
        " ".join(argv) for _a, argv in transport.commands if "kill -TERM" in " ".join(argv)
    )
    assert terminate.index('kill -CONT "$pid"') < terminate.index('kill -TERM "$pid"')


def test_release_run_kills_what_would_not_terminate_and_reports_it() -> None:
    row = "515\t/tmp/valkey-scale-lab/run-1/node-000\t/opt/bin/valkey-server\n"
    transport = FakeTransport()
    # The on-host wait reports one survivor; the kill pass reports killing it;
    # the recheck afterwards finds the tree empty.
    transport.respond("attempt=0; while", 0, row)
    transport.respond('kill -KILL "$pid"', 0, row)
    backend = NativeMultiEcsBackend(transport=transport)
    verify = backend.release_run(_state()).actions[1]
    assert verify["action"] == "verify_exit"
    assert verify["status"] == "SKIPPED_WITH_REASON"
    assert verify["alive_pid_count"] == 0
    assert verify["killed_pid_count"] == 1


def test_verify_exit_kills_more_than_once_because_a_fork_outlives_its_parent() -> None:
    """Killing a process is not the same as emptying the tree.

    A process that has forked leaves a child holding the working directory, and
    the child is reparented rather than killed with it. Measured on a simulated
    host, and `valkey-server` has this shape whenever a background save is in
    flight - which the generated config's default save policy allows at any
    moment. So the kill escalates in bounded rounds, rechecking between them.
    """
    parent = "515\t/tmp/valkey-scale-lab/run-1/node-000\t/opt/bin/valkey-server\n"
    child = "902\t/tmp/valkey-scale-lab/run-1/node-000\t/opt/bin/valkey-server\n"

    class Forking(FakeTransport):
        rounds = 0

        def run(self, control_endpoint, argv, *, timeout):  # noqa: ANN001
            joined = " ".join(str(item) for item in argv)
            if "attempt=0; while" in joined:
                self.default = (0, parent, "")
            elif 'kill -KILL "$pid"' in joined:
                type(self).rounds += 1
                self.default = (0, parent if self.rounds == 1 else child, "")
            elif 'printf "%s\\t%s\\t%s\\n"' in joined:
                # The recheck: the forked child is still there after round one.
                self.default = (0, child if self.rounds == 1 else "", "")
            else:
                self.default = (0, "", "")
            return super().run(control_endpoint, argv, timeout=timeout)

    verify = NativeMultiEcsBackend(transport=Forking()).release_run(_state()).actions[1]
    assert verify["killed_pid_count"] == 2
    assert verify["alive_pid_count"] == 0


def test_release_run_reports_residue_rather_than_asserting_it_is_gone() -> None:
    """The criterion measured rather than asserted, in all three kinds.

    A backend that reported its own `rm` as proof would be asserting "no managed
    process or host resource behind" instead of measuring it - and there is no
    `docker rm -f` here to make the assertion true anyway.
    """
    transport = FakeTransport()
    transport.respond(
        "[ -e /tmp/valkey-scale-lab/run-1 ]",
        0,
        "state\n515\t/tmp/valkey-scale-lab/run-1/node-000\t/opt/bin/valkey-server\n",
    )
    transport.respond(
        "iptables -S 2>/dev/null | awk",
        0,
        'rule\t-A INPUT -m comment --comment "vslab-run=run-1" -j VSLAB-NODEHOST-AZ-A-00\n',
    )
    backend = NativeMultiEcsBackend(transport=transport)
    teardown = backend.release_run(_state())
    kinds = sorted(item["type"] for item in teardown.resources_remaining)
    assert kinds == ["nodehost_firewall_rule", "nodehost_run_state", "valkey_process"]
    process = next(row for row in teardown.resources_remaining if row["type"] == "valkey_process")
    assert process["pid"] == 515
    assert process["exe"] == "/opt/bin/valkey-server"


def test_release_run_removes_the_run_bundles_it_dropped_on_the_host() -> None:
    """Measured on the first native exact-50: four hosts each kept an 88 KB
    bundle under a `cleanup_report` saying `found: 0`.

    `_state_nodehost` records eight fields and `remote_bundle_dir` is not among
    them, so the removal that read it from state removed nothing. It is derived
    from the run id now, which is the same expression `reclaim_run` has always
    used - so the two cleanup paths agree about what a run owns.
    """
    transport = FakeTransport()
    backend = NativeMultiEcsBackend(transport=transport)
    removal = backend.release_run(_state()).actions[3]
    assert removal["type"] == "nodehost_run_state"
    assert removal["paths"] == [
        "/tmp/valkey-scale-lab/run-1",
        "/tmp/vslab-bundle-run-1-*",
    ]
    ran = next(
        " ".join(argv) for _a, argv in transport.commands if "rm -rf /tmp/vslab-bundle" in " ".join(argv)
    )
    # Unquoted, because the host's shell is what expands it.
    assert "rm -rf /tmp/vslab-bundle-run-1-*" in ran


def test_release_run_reports_a_bundle_it_could_not_remove() -> None:
    """The scan measured two of the three filesystem residues a native run
    leaves, so a bundle nothing removed read as `found: 0`."""
    transport = FakeTransport()
    transport.respond(
        "[ -e /tmp/valkey-scale-lab/run-1 ]",
        0,
        "bundle\t/tmp/vslab-bundle-run-1-nodehost-az-a-00\n",
    )
    backend = NativeMultiEcsBackend(transport=transport)
    teardown = backend.release_run(_state())
    left = [row for row in teardown.resources_remaining if row["type"] == "nodehost_run_bundle"]
    assert [row["path"] for row in left] == ["/tmp/vslab-bundle-run-1-nodehost-az-a-00"]
    scan = teardown.actions[4]
    assert scan["scanned"] == ["state", "bundle", "process", "firewall"]
    assert scan["found"] == 1


def test_release_run_removes_the_firewall_state_an_abort_would_strand() -> None:
    """Nothing removed these before roadmap item 1.4 - only `rejoin_nodehost`.

    A run that aborted while a host was isolated left a DROP chain and its two
    jumps installed, and the next run on that host inherited them.
    """
    transport = FakeTransport()
    transport.respond(
        "for spec in $(iptables -S",
        0,
        "jump\tINPUT\tVSLAB-NODEHOST-AZ-A-00\njump\tOUTPUT\tVSLAB-NODEHOST-AZ-A-00\nchain\tVSLAB-NODEHOST-AZ-A-00\n",
    )
    backend = NativeMultiEcsBackend(transport=transport)
    rules = backend.release_run(_state()).actions[2]
    assert rules["type"] == "nodehost_firewall_rules"
    assert (rules["jump_count"], rules["chain_count"]) == (2, 1)
    assert rules["chains_held"] == []
    # Found by the run's own mark, because a chain name cannot carry one.
    assert transport.ran("vslab-run=run-1")


def test_release_run_closes_the_control_channel_it_opened() -> None:
    """`HostTransport.close()` existed from item 1.2 and nothing ever called it.

    Measured: a process that exits without it leaves one `sshd` session alive on
    every host. `release_run` is the terminal operation, so it is where a
    transport this backend opened for itself is given back.
    """
    own = NativeMultiEcsBackend()
    own._transport = FakeTransport()
    own._owns_transport = True
    own.release_run(_state())
    assert own._transport is None

    # One it was handed belongs to whoever handed it over, who may still want it.
    injected = FakeTransport()
    NativeMultiEcsBackend(transport=injected).release_run(_state())
    assert injected.closed is False


def test_release_run_reports_a_host_that_stops_answering_instead_of_raising() -> None:
    """The seam: a resource that would not release is a row, not an exception.

    "The report is what the cleanup criterion is measured on and an exception
    erases it" - and a run whose host went away is exactly the run whose residue
    somebody needs to read about.
    """

    class Vanishing(FakeTransport):
        def run(self, control_endpoint, argv, *, timeout):  # noqa: ANN001
            if "kill -TERM" in " ".join(str(item) for item in argv):
                raise TransportError("connection closed by remote host")
            return super().run(control_endpoint, argv, timeout=timeout)

    teardown = NativeMultiEcsBackend(transport=Vanishing()).release_run(_state())
    assert teardown.errors and "connection closed" in teardown.errors[0]
    scan = teardown.actions[-1]
    assert scan["status"] == "FAIL"
    assert scan["unscannable"] == ["host"]
    assert [row["type"] for row in teardown.resources_remaining] == ["nodehost_unreachable"]


def test_a_host_that_cannot_be_asked_about_rules_is_not_a_host_without_rules() -> None:
    """The assert-rather-than-measure defect, one level down.

    If `iptables` is absent or not permitted, a scan that just greps its output
    reports "no rules" - the same shape of false clean the whole operation exists
    to avoid.
    """
    transport = FakeTransport()
    transport.respond("if ! iptables -S", 0, "unscannable\tfirewall\n")
    teardown = NativeMultiEcsBackend(transport=transport).release_run(_state())
    scan = teardown.actions[4]
    assert scan["action"] == "scan"
    assert scan["status"] == "FAIL"
    assert scan["unscannable"] == ["firewall"]


def test_release_run_reports_an_unreachable_nodehost_instead_of_raising() -> None:
    """A resource that would not release is a row; an exception erases the report."""
    transport = FakeTransport()
    backend = NativeMultiEcsBackend(transport=transport)
    nodehost = _nodehost()
    del nodehost["host_control_endpoint"]
    teardown = backend.release_run(_state(nodehosts=[nodehost]))
    assert teardown.actions == []
    assert teardown.errors and "never placed" in teardown.errors[0]


def test_release_run_refuses_a_state_that_does_not_describe_a_native_fleet() -> None:
    backend = NativeMultiEcsBackend(transport=FakeTransport())
    with pytest.raises(NativeRuntimeError, match="names no nodehosts"):
        backend.release_run(_state(nodehosts=[]))
    with pytest.raises(NativeRuntimeError, match="explicit run_id"):
        backend.release_run(_state(runtime={"type": "native_multi_ecs"}))


def test_release_run_does_not_depend_on_state_carrying_a_usable_pid() -> None:
    """The pids in state stopped being an input at roadmap item 1.4.

    They survive only as `state_pid_count`, which is a record of what the run
    believed rather than an instruction to teardown, so a state with no usable
    pid changes nothing about what is signalled.
    """
    transport = FakeTransport()
    backend = NativeMultiEcsBackend(transport=transport)
    teardown = backend.release_run(_state(nodes=[_node(pid=0)]))
    terminate = teardown.actions[0]
    assert terminate["status"] == "PASS"
    assert terminate["state_pid_count"] == 0
    assert transport.ran('kill -TERM "$pid"')


def test_reclaim_run_and_release_run_agree_about_what_is_running(tmp_path: Path) -> None:
    """Roadmap item 1.4 unified them; before it they were two answers.

    `reclaim_run` killed by reading each `<root>/*/valkey.pid` and `release_run`
    killed by `state.json`, and measurement showed neither is what is actually
    alive. One enumeration answers both. What stays different is what the seam
    already says is different: this one has nothing to report to, so it signals
    `KILL` outright.
    """
    reclaim_transport = FakeTransport()
    _backend(reclaim_transport, tmp_path).reclaim_run(capability_id="local_full_flow", run_id="run-1")
    reclaimed = " ".join(reclaim_transport.last())

    release_transport = FakeTransport()
    NativeMultiEcsBackend(transport=release_transport).release_run(_state())
    released = next(
        " ".join(argv) for _a, argv in release_transport.commands if "kill -TERM" in " ".join(argv)
    )

    walk = 'for entry in /proc/[0-9]*; do'
    assert walk in reclaimed and walk in released
    assert 'case "$cwd/" in "$root"/*' in reclaimed
    assert "valkey.pid" not in reclaimed
    assert 'kill -KILL "$pid"' in reclaimed


def test_reclaim_run_removes_the_rules_an_earlier_attempt_stranded(tmp_path: Path) -> None:
    transport = FakeTransport()
    _backend(transport, tmp_path).reclaim_run(capability_id="local_full_flow", run_id="run-1")
    reclaimed = " ".join(transport.last())
    assert "vslab-run=run-1" in reclaimed
    assert "iptables -D" in reclaimed and "iptables -X" in reclaimed
    assert "rm -rf /tmp/valkey-scale-lab/run-1" in reclaimed


# --------------------------------------------------------------------------
# the registry, and the transport's measured constraint
# --------------------------------------------------------------------------


def test_native_multi_ecs_is_registered_because_the_backend_exists() -> None:
    spec = resolve_backend("native_multi_ecs")
    assert spec.implements_profile("exact-50")
    assert spec.implements_scenario("local_full_flow")
    # The Gate's Docker-daemon check is a backend property, and this backend has
    # no daemon to check.
    assert spec.requires_local_docker_daemon is False
    # Node ports live on the hosts, so the controller's loopback says nothing
    # about them and the run must not preflight them there.
    assert spec.publishes_node_ports_on_controller is False


def test_the_backend_a_run_gets_is_configured_and_the_one_teardown_gets_is_not(tmp_path: Path) -> None:
    spec = resolve_backend("native_multi_ecs")
    configured = spec.build_for_run(
        {"host_inventory_path": str(_manifest(tmp_path)), "native_bundle_dir": str(_bundle(tmp_path))}
    )
    assert configured.fleet_placement_records()[0]["host_id"] == "host-00"
    assert spec.node_backend is not None
    with pytest.raises(NativeRuntimeError, match="without a fleet manifest"):
        spec.node_backend().inventory()


def test_the_control_socket_path_is_held_under_the_platform_limit(tmp_path: Path) -> None:
    """Measured: the first transport spike run failed on exactly this.

    `ControlPath` is a Unix domain socket path and `sockaddr_un` caps it at 104
    bytes, which a run's artifacts directory exceeds on its own.
    """
    # The root is the shape of a real run's artifacts directory rather than
    # `tmp_path` itself, because `tmp_path`'s own length is a property of the
    # platform: 127 bytes on macOS under /var/folders, about 60 on Linux under
    # /tmp. Naming the nesting that motivates the constant makes the test say
    # the same thing in both places.
    run_root = (
        tmp_path
        / "artifacts"
        / "gate-runs"
        / "gate-20260812T092306Z-de92aa1f"
        / "001-real.local.full-flow"
        / "runtime"
        / "ssh"
    )
    assert len(str(run_root).encode("utf-8")) > CONTROL_PATH_MAX_BYTES
    transport = MultiplexedSshTransport(control_root=run_root)
    with pytest.raises(TransportError, match=f"platform limit is {CONTROL_PATH_MAX_BYTES}"):
        transport._control_path(CONTROL)


def test_the_transport_reuses_one_control_socket_per_host(tmp_path: Path) -> None:
    """One master per host is what puts the transport under the budget.

    Measured against the rolling restart's 60-75 ms: multiplexed 10.8 ms,
    un-multiplexed 63.8 ms.
    """
    short_root = Path("/tmp/vslab-test-cm")
    short_root.mkdir(parents=True, exist_ok=True)
    transport = MultiplexedSshTransport(control_root=short_root)
    first = transport._control_path(CONTROL)
    again = transport._control_path(dict(CONTROL))
    other = transport._control_path({**CONTROL, "address": "10.0.0.12"})
    assert first == again
    assert other != first


# --------------------------------------------------------------------------
# The resource preflight, and the two checks that are about Docker rather than
# about the run. Measured on the M3-B controller at `1cdfacd3`: they were the
# only two failures of fifteen, and both fail because that machine has no
# daemon - which a native run does not need.
# --------------------------------------------------------------------------


def _preflight_names(report: dict) -> dict[str, str]:
    return {check["name"]: check["status"] for check in report["checks"]}


def test_a_backend_needing_no_local_daemon_is_not_blocked_by_daemon_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`docker_available` and `previous_cleanup_state` both shell out to docker."""
    from valkey_scale_lab import resource

    # Nothing is stubbed here on purpose: the point is that neither Docker
    # helper is reached. If either were, this would try to run `docker` and the
    # assertions below would depend on whether the test machine has one.
    monkeypatch.setattr(
        resource,
        "_docker_details",
        lambda: pytest.fail("the daemon was asked about on a backend that needs none"),
    )
    monkeypatch.setattr(
        resource,
        "_cleanup_state_check",
        lambda *args: pytest.fail("docker ps was run on a backend that needs none"),
    )
    monkeypatch.setattr(
        resource, "_port_check", lambda base, count, name: resource._check(name, True, {})
    )

    report = resource.run_resource_preflight(
        "templates/configs/scale_50.yaml",
        tmp_path / "preflight.json",
        backend_id="native_multi_ecs",
    )

    names = _preflight_names(report)
    assert names["docker_available"] == "SKIPPED_WITH_REASON"
    assert names["previous_cleanup_state"] == "SKIPPED_WITH_REASON"
    skipped = [c for c in report["checks"] if c["status"] == "SKIPPED_WITH_REASON"]
    # The reason is the evidence: a dropped row would leave two preflights
    # differing by a missing name with nothing saying why.
    assert all("native_multi_ecs" in c["details"]["reason"] for c in skipped)
    assert report["can_run"] is True


def test_a_docker_backend_still_gets_both_daemon_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other direction, which is what stops this from being a way out."""
    from valkey_scale_lab import resource

    asked: list[str] = []
    monkeypatch.setattr(
        resource,
        "_docker_details",
        lambda: (asked.append("docker_info"), {"available": True, "server_version": "t"})[1],
    )
    monkeypatch.setattr(
        resource,
        "_cleanup_state_check",
        lambda capability_id, scenario, node_count: (
            asked.append("docker_ps"),
            resource._check("previous_cleanup_state", True, {"node_count": node_count}),
        )[1],
    )
    monkeypatch.setattr(
        resource, "_port_check", lambda base, count, name: resource._check(name, True, {})
    )

    report = resource.run_resource_preflight(
        "templates/configs/scale_50.yaml",
        tmp_path / "preflight.json",
        backend_id="docker_process",
    )

    assert asked == ["docker_info", "docker_ps"]
    assert _preflight_names(report)["docker_available"] == "PASS"


def test_a_caller_that_names_no_backend_keeps_the_check_it_always_had(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`cli preflight` and the scale ladder ask about a machine, not about a run."""
    from valkey_scale_lab import resource

    asked: list[str] = []
    monkeypatch.setattr(
        resource,
        "_docker_details",
        lambda: (asked.append("docker_info"), {"available": True, "server_version": "t"})[1],
    )
    monkeypatch.setattr(
        resource,
        "_cleanup_state_check",
        lambda capability_id, scenario, node_count: resource._check(
            "previous_cleanup_state", True, {"node_count": node_count}
        ),
    )
    monkeypatch.setattr(
        resource, "_port_check", lambda base, count, name: resource._check(name, True, {})
    )

    resource.run_resource_preflight("templates/configs/scale_50.yaml", tmp_path / "preflight.json")

    assert asked == ["docker_info"]


def test_a_skipped_check_is_the_only_non_pass_status_that_does_not_block() -> None:
    """`_check` produces PASS or FAIL and nothing else, so nothing else can slip in."""
    from valkey_scale_lab import resource

    assert resource._check("x", False, {})["status"] == "FAIL"
    assert resource.NON_BLOCKING_CHECK_STATUSES == {"PASS", "SKIPPED_WITH_REASON"}
    assert "FAIL" not in resource.NON_BLOCKING_CHECK_STATUSES


# --------------------------------------------------------------------------
# The memory budget, which used to ask the controller about memory the run
# spends on eight other machines. Measured on the M3-B controller: exact-200
# wanted 12800 MB against 12117 MB there, while each placed host held 1600 MB
# against 7.7 GiB.
# --------------------------------------------------------------------------


class _MemoryTransport:
    """Answers `/proc/meminfo` per address, in kB, as the real hosts do."""

    def __init__(self, available_kb_by_address: dict[str, int | None]) -> None:
        self._available = available_kb_by_address
        self.asked: list[str] = []
        self.closed = False

    def run(self, control_endpoint, argv, *, timeout):  # noqa: ANN001
        address = str(control_endpoint["address"])
        self.asked.append(address)
        value = self._available.get(address)
        if value is None:
            raise TransportError(f"could not reach {address}")
        return CommandResult(
            argv=[str(item) for item in argv],
            returncode=0,
            stdout=f"{value}\n",
            stderr="",
            started_at_unix_ms=0,
            ended_at_unix_ms=1,
        )

    def close(self) -> None:
        self.closed = True


def _placed_plan(memory_limit_mb: int = 64) -> dict:
    """A density plan with placement, in the shape the planner produces."""
    return {
        "nodehosts": [
            {
                "nodehost_id": "nodehost-az-a-00",
                "host_id": "vslab-host-a-1",
                "host_control_endpoint": {**CONTROL, "address": "10.148.0.9"},
            },
            {
                "nodehost_id": "nodehost-az-b-00",
                "host_id": "vslab-host-b-1",
                "host_control_endpoint": {**CONTROL, "address": "10.148.0.13"},
            },
        ],
        "nodehost_density": {
            "logical_nodes_per_nodehost": {"nodehost-az-a-00": 25, "nodehost-az-b-00": 25}
        },
    }


def test_memory_is_compared_against_the_host_each_nodehost_is_placed_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from valkey_scale_lab import resource

    # 7.7 GiB free on each host, which is what a c4a-standard-2 reports.
    transport = _MemoryTransport({"10.148.0.9": 7_900_000, "10.148.0.13": 7_900_000})
    monkeypatch.setattr(resource, "MultiplexedSshTransport", lambda *a, **k: transport)
    # The controller could not hold this run: 200 x 64 MB is 12800 MB.
    monkeypatch.setattr(resource, "_host_available_memory_mb", lambda: 12_117)

    check = resource._memory_check(200, 64, density_plan=_placed_plan())

    assert check["status"] == "PASS"
    assert check["details"]["compared_against"] == "placed_host"
    assert check["details"]["required_memory_mb"] == 12_800
    rows = {row["nodehost_id"]: row for row in check["details"]["per_nodehost"]}
    assert rows["nodehost-az-a-00"]["projected_memory_mb"] == 1_600
    assert rows["nodehost-az-a-00"]["host_id"] == "vslab-host-a-1"
    assert all(row["fits"] for row in check["details"]["per_nodehost"])
    assert transport.closed is True


def test_a_nodehost_that_does_not_fit_its_own_host_fails_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from valkey_scale_lab import resource

    transport = _MemoryTransport({"10.148.0.9": 7_900_000, "10.148.0.13": 800_000})
    monkeypatch.setattr(resource, "MultiplexedSshTransport", lambda *a, **k: transport)

    check = resource._memory_check(200, 64, density_plan=_placed_plan())

    assert check["status"] == "FAIL"
    rows = {row["nodehost_id"]: row for row in check["details"]["per_nodehost"]}
    assert rows["nodehost-az-a-00"]["fits"] is True
    assert rows["nodehost-az-b-00"]["fits"] is False


def test_a_host_that_will_not_answer_fails_rather_than_being_assumed_to_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed, the same way `create_network` refuses a fleet it cannot see."""
    from valkey_scale_lab import resource

    transport = _MemoryTransport({"10.148.0.9": 7_900_000, "10.148.0.13": None})
    monkeypatch.setattr(resource, "MultiplexedSshTransport", lambda *a, **k: transport)

    check = resource._memory_check(200, 64, density_plan=_placed_plan())

    assert check["status"] == "FAIL"
    unreachable = [row for row in check["details"]["per_nodehost"] if not row["fits"]]
    assert len(unreachable) == 1
    assert unreachable[0]["host_available_memory_mb"] == "MISSING"
    assert "could not reach" in unreachable[0]["error"]
    assert transport.closed is True


def test_a_run_with_no_fleet_still_compares_against_the_machine_it_runs_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every Docker run: the nodes are here, so this machine is the right one."""
    from valkey_scale_lab import resource

    monkeypatch.setattr(
        resource,
        "MultiplexedSshTransport",
        lambda *a, **k: pytest.fail("a fleet was contacted for a run that named none"),
    )
    monkeypatch.setattr(resource, "_host_available_memory_mb", lambda: 12_117)

    plan = {"nodehost_density": {"logical_nodes_per_nodehost": {"nodehost-az-a-00": 50}}}
    check = resource._memory_check(50, 64, density_plan=plan)

    assert check["status"] == "PASS"
    assert check["details"]["compared_against"] == "controller"
    assert check["details"]["host_available_memory_mb"] == 12_117
