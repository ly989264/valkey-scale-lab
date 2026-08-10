"""The harness boundary, enforced where the inventory manifest is written.

The simulated-host harness is lab tooling outside the product, and its whole
value rests on one property: a backend consuming the manifest cannot tell the
hosts are containers. If it could, it could behave differently against them, and
every result taken on simulated hosts would be about the harness instead of the
product. That property is a string check, so it is testable, and these are the
tests that hold it.

Hermetic: nothing here starts a host or calls Docker.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import simulated_hosts  # noqa: E402


def _host(**overrides: object) -> dict[str, object]:
    host = {
        "host_id": "sim-host-00",
        "availability_zone": "az-a",
        "control_endpoint": {
            "protocols": ["ssh"],
            "address": "127.0.0.1",
            "port": 22200,
            "user": "root",
            "private_key_path": "/tmp/host-fleets/sim-a/ssh/id_ed25519",
            "known_hosts_path": "/tmp/host-fleets/sim-a/ssh/known_hosts",
            "host_key_fingerprint": "SHA256:abc",
        },
        "client_endpoint": {"address": "127.0.0.1", "port_range": {"first": 31000, "last": 31059}},
        "data_address": "172.18.0.2",
        "os": {
            "kind": "linux",
            "distribution": "debian",
            "version": "13",
            "kernel_release": "6.12.76-linuxkit",
            "arch": "aarch64",
        },
        "capacity": {"cpus": 10, "memory_bytes": 8217059328},
    }
    host.update(overrides)
    return host


def test_a_manifest_of_plain_hosts_is_accepted() -> None:
    manifest = simulated_hosts._build_manifest(fleet_id="sim-a", hosts=[_host()])

    assert manifest["artifact_type"] == "host_inventory"
    assert manifest["host_count"] == 1
    assert "simulated" not in json.dumps(manifest).lower()


def test_every_host_carries_the_three_addresses_a_backend_needs() -> None:
    """Control, data and client are three roles a real host also has: where the
    controller runs commands, what peers dial, and where the controller speaks
    RESP. Under this harness the last two differ because the macOS host cannot
    route Docker's network; on a real fleet the manifest repeats one address."""
    manifest = simulated_hosts._build_manifest(fleet_id="sim-a", hosts=[_host()])

    host = manifest["hosts"][0]
    assert host["control_endpoint"]["address"] and host["control_endpoint"]["port"]
    assert host["data_address"]
    assert host["client_endpoint"]["port_range"]["first"] <= host["client_endpoint"]["port_range"]["last"]


@pytest.mark.parametrize(
    "leak",
    [
        {"container_name": "vslab-sim-sim-a-00"},
        {"image": "valkey-scale-lab/simulated-host:debian13-sshd"},
        {"network_name": "vslab-sim-sim-a"},
        {"simulated": True},
    ],
    ids=["container-name", "image", "docker-network", "simulated-flag"],
)
def test_a_manifest_that_names_the_harness_is_refused(leak: dict[str, object]) -> None:
    with pytest.raises(simulated_hosts.HarnessError, match="leaks harness vocabulary"):
        simulated_hosts._build_manifest(fleet_id="sim-a", hosts=[_host(**leak)])


def test_a_key_path_under_a_harness_named_directory_is_refused() -> None:
    """Why the fleet's state does not live under `artifacts/simulated-hosts/`:
    the private key path is in the manifest, so the directory name is a tell."""
    host = _host()
    host["control_endpoint"] = dict(host["control_endpoint"])
    host["control_endpoint"]["private_key_path"] = "/tmp/simulated-hosts/sim-a/ssh/id_ed25519"

    with pytest.raises(simulated_hosts.HarnessError, match="leaks harness vocabulary"):
        simulated_hosts._build_manifest(fleet_id="sim-a", hosts=[host])


def test_client_port_blocks_do_not_overlap() -> None:
    blocks = simulated_hosts.client_port_blocks(31000, 3, 60)

    assert blocks == [(31000, 31059), (31060, 31119), (31120, 31179)]
    for (_, previous_last), (next_first, _) in zip(blocks, blocks[1:]):
        assert next_first > previous_last


def test_a_fleet_needs_at_least_one_client_port_per_host() -> None:
    with pytest.raises(simulated_hosts.HarnessError, match="at least one client port"):
        simulated_hosts.client_port_blocks(31000, 2, 0)


@pytest.mark.parametrize("fleet_id", ["Sim-A", "sim_a", "-sim", "", "a" * 40])
def test_an_unusable_fleet_id_is_refused(fleet_id: str) -> None:
    with pytest.raises(simulated_hosts.HarnessError, match="fleet id"):
        simulated_hosts._fleet_dir(fleet_id)
