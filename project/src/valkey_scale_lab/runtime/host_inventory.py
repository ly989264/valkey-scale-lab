"""The fleet a native run is given, read from the manifest and nothing else.

The product provisions no hosts. They arrive as a static inventory manifest - the
roadmap's "null choice" - and this module is the only place that knows the
manifest's field names. Everything downstream, the planner included, sees the
neutral records below.

The manifest is written by lab tooling outside the product and deliberately
carries no way to tell what is standing behind it: no container, no image, no
network, and no flag saying the fleet is simulated. A backend that could tell
would make every result taken on simulated hosts a fact about the harness rather
than about the product. This module must therefore never grow a "simulated"
branch, and the absence is enforced upstream at the manifest's write.

Three addresses per host, because a host has three roles the seam already
distinguishes - see `project/docs/simulated_host_and_native_bundle_map.md` §3.1:

  control_endpoint  where the controller runs commands
  data_address      what this host's processes announce, and what peers dial
  client_endpoint   where the controller speaks RESP, over a port *range*

Under the development harness the last two differ because the macOS host cannot
route the fleet's own network. On a real fleet they usually coincide and the
manifest carries the same address twice; the field set does not change, which is
the property that makes the harness worth having.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

INVENTORY_ARTIFACT_TYPE = "host_inventory"

_REQUIRED_HOST_KEYS = (
    "availability_zone",
    "client_endpoint",
    "control_endpoint",
    "data_address",
    "host_id",
)
_REQUIRED_CONTROL_KEYS = ("address", "known_hosts_path", "port", "private_key_path", "user")


class HostInventoryError(RuntimeError):
    """The fleet manifest is missing, malformed, or does not describe hosts."""


@dataclass(frozen=True)
class FleetHost:
    """One host, in the terms every consumer below the manifest uses."""

    host_id: str
    az_id: str
    control_endpoint: dict[str, Any]
    data_address: str
    client_address: str
    client_port_first: int
    client_port_last: int

    def holds_ports(self, ports: Sequence[int]) -> list[int]:
        """Which of `ports` fall outside what this host says it will serve.

        A range rather than a membership set because a real host states the same
        thing as a security-group range, and the run's port base is chosen by
        configuration that has never seen the manifest.
        """
        return sorted(
            port for port in ports if not self.client_port_first <= int(port) <= self.client_port_last
        )

    def as_placement_record(self) -> dict[str, Any]:
        """What a planner needs in order to place a nodehost here."""
        return {
            "host_id": self.host_id,
            "az_id": self.az_id,
            "control_endpoint": dict(self.control_endpoint),
            "data_address": self.data_address,
            "client_address": self.client_address,
            "client_port_first": self.client_port_first,
            "client_port_last": self.client_port_last,
        }


@dataclass(frozen=True)
class HostInventory:
    fleet_id: str
    hosts: tuple[FleetHost, ...]
    #: The digest of the manifest as read. A run records it so that "which fleet
    #: was this?" is answerable from the run's own evidence rather than from
    #: whichever manifest happens to be on disk later. It is deliberately the
    #: only thing about the fleet a run can say beyond its identity: what the
    #: fleet *is* lives in the harness's own sidecar, which the product never
    #: reads - see `cross_host_evidence_slice_map.md` §8.
    manifest_sha256: str = ""

    def by_az(self) -> dict[str, list[FleetHost]]:
        grouped: dict[str, list[FleetHost]] = {}
        for host in self.hosts:
            grouped.setdefault(host.az_id, []).append(host)
        return {az: sorted(items, key=lambda item: item.host_id) for az, items in sorted(grouped.items())}

    def placement_records(self) -> list[dict[str, Any]]:
        return [
            {
                **host.as_placement_record(),
                "fleet_id": self.fleet_id,
                "fleet_manifest_sha256": self.manifest_sha256,
            }
            for host in self.hosts
        ]

    def host(self, host_id: str) -> FleetHost:
        for host in self.hosts:
            if host.host_id == host_id:
                return host
        raise HostInventoryError(
            f"the fleet manifest describes no host {host_id!r}; "
            f"it has {', '.join(item.host_id for item in self.hosts) or 'none'}"
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HostInventoryError(message)


def _read_host(index: int, raw: Any) -> FleetHost:
    _require(isinstance(raw, dict), f"hosts[{index}] must be an object")
    missing = [key for key in _REQUIRED_HOST_KEYS if key not in raw]
    _require(not missing, f"hosts[{index}] is missing {missing}")

    control = raw["control_endpoint"]
    _require(isinstance(control, dict), f"hosts[{index}].control_endpoint must be an object")
    control_missing = [key for key in _REQUIRED_CONTROL_KEYS if key not in control]
    _require(
        not control_missing,
        f"hosts[{index}].control_endpoint is missing {control_missing}",
    )

    client = raw["client_endpoint"]
    _require(isinstance(client, dict), f"hosts[{index}].client_endpoint must be an object")
    _require("address" in client, f"hosts[{index}].client_endpoint is missing address")
    port_range = client.get("port_range")
    _require(
        isinstance(port_range, dict) and "first" in port_range and "last" in port_range,
        f"hosts[{index}].client_endpoint.port_range needs first and last",
    )
    first = int(port_range["first"])
    last = int(port_range["last"])
    _require(
        0 < first <= last <= 65535,
        f"hosts[{index}].client_endpoint.port_range is not a usable range: {first}-{last}",
    )

    host_id = str(raw["host_id"])
    _require(bool(host_id), f"hosts[{index}].host_id must not be empty")
    return FleetHost(
        host_id=host_id,
        az_id=str(raw["availability_zone"]),
        control_endpoint=dict(control),
        data_address=str(raw["data_address"]),
        client_address=str(client["address"]),
        client_port_first=first,
        client_port_last=last,
    )


def load_host_inventory(path: str | Path) -> HostInventory:
    """Read and check a fleet manifest.

    Fails closed on anything it cannot interpret. A run that proceeded on a
    half-understood manifest would place nodes on hosts it cannot reach and
    discover it during cluster formation, ten minutes later and as a different
    symptom.
    """
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise HostInventoryError(f"no fleet manifest at {manifest_path}")
    raw = manifest_path.read_bytes()
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise HostInventoryError(f"{manifest_path} is not readable JSON: {error}") from error
    _require(isinstance(manifest, dict), f"{manifest_path} must contain an object")
    _require(
        manifest.get("artifact_type") == INVENTORY_ARTIFACT_TYPE,
        f"{manifest_path} is a {manifest.get('artifact_type')!r}, not a {INVENTORY_ARTIFACT_TYPE!r}",
    )
    raw_hosts = manifest.get("hosts")
    _require(isinstance(raw_hosts, list) and raw_hosts, f"{manifest_path} describes no hosts")

    hosts = [_read_host(index, raw) for index, raw in enumerate(raw_hosts)]
    seen: set[str] = set()
    for host in hosts:
        if host.host_id in seen:
            raise HostInventoryError(f"{manifest_path} names host {host.host_id!r} twice")
        seen.add(host.host_id)
    return HostInventory(
        fleet_id=str(manifest.get("fleet_id", manifest_path.parent.name)),
        hosts=tuple(hosts),
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
    )


def control_endpoint_of(nodehost: Mapping[str, Any]) -> dict[str, Any]:
    """The control endpoint a placed nodehost carries, or a stated refusal.

    Placement writes this onto the nodehost so that everything afterwards -
    including a teardown that only ever sees `state.json` - can reach the host
    without reading a manifest again. A nodehost without one was not placed.
    """
    endpoint = nodehost.get("host_control_endpoint")
    if not isinstance(endpoint, dict) or not endpoint:
        raise HostInventoryError(
            f"nodehost {nodehost.get('nodehost_id', '?')!r} carries no host control endpoint, "
            "so it was never placed on a fleet host"
        )
    missing = [key for key in _REQUIRED_CONTROL_KEYS if key not in endpoint]
    if missing:
        raise HostInventoryError(
            f"nodehost {nodehost.get('nodehost_id', '?')!r} has an incomplete control endpoint: {missing}"
        )
    return dict(endpoint)
