#!/usr/bin/env python3
"""Write a fleet manifest, and validate it by loading it back through the product.

Lab tooling. The manifest is the one thing that crosses from the fleet to the
product (`simulated_host_and_native_bundle_map.md`), and until now the only
generator for a *real* fleet lived in a session scratchpad, which was lost. This
is that generator, version-controlled, so the next fleet rebuild is a command
rather than an archaeology exercise.

    ./scripts/make_fleet_manifest.py --fleet-id gce-m3b \\
        --user root \\
        --private-key ~/.ssh/vslab_fleet \\
        --known-hosts ~/.ssh/vslab_fleet_known_hosts \\
        --host az-a:vslab-host-a-1:10.148.0.36 \\
        --host az-b:vslab-host-b-1:10.148.0.42 \\
        --out artifacts/host-fleets/gce-m3b/inventory.json

**`host_id` is yours to choose and it is not the instance's name.**
`runtime/host_inventory.py` requires it only to be non-empty and unique; nothing
cross-checks it against the machine. That matters on a rebuild, because
`scripts/diff_stage_artifacts.py` compares `host_id` *literally* in
`state_before_cluster`, so a fleet that reuses the previous fleet's ids keeps its
frozen baselines comparable while one that takes GCE's generated names strands
them. Addresses do not have the same problem - the diff tool rewrites every
address to `<nodehost:ID>` before comparing.

The manifest must carry **no container, image or network vocabulary and no flag
saying whether the fleet is real or simulated**; a backend that could tell would
make every result taken on simulated hosts a fact about the harness. The field
set here is exactly what `host_inventory.py` reads and nothing more.

On a real fleet `data_address` and `client_endpoint.address` are the same
address, which is why one positional value fills both. Under the simulated
harness they differ, and `scripts/simulated_hosts.py` writes those manifests
itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_PORT_FIRST = 7000
DEFAULT_PORT_LAST = 32000


def build_manifest(
    *,
    fleet_id: str,
    hosts: list[tuple[str, str, str]],
    user: str,
    private_key: str,
    known_hosts: str,
    ssh_port: int,
    port_first: int,
    port_last: int,
) -> dict:
    return {
        "artifact_type": "host_inventory",
        "fleet_id": fleet_id,
        "hosts": [
            {
                "availability_zone": az,
                "host_id": host_id,
                "data_address": address,
                "client_endpoint": {
                    "address": address,
                    "port_range": {"first": port_first, "last": port_last},
                },
                "control_endpoint": {
                    "address": address,
                    "port": ssh_port,
                    "user": user,
                    "private_key_path": private_key,
                    "known_hosts_path": known_hosts,
                },
            }
            for az, host_id, address in hosts
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fleet-id", required=True)
    parser.add_argument(
        "--host",
        action="append",
        required=True,
        metavar="AZ:HOST_ID:ADDRESS",
        help="one per host; repeat. HOST_ID is the id the artifacts record, not the instance name.",
    )
    parser.add_argument("--user", default="root")
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--known-hosts", required=True)
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--port-first", type=int, default=DEFAULT_PORT_FIRST)
    parser.add_argument("--port-last", type=int, default=DEFAULT_PORT_LAST)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    hosts: list[tuple[str, str, str]] = []
    for item in args.host:
        parts = item.split(":")
        if len(parts) != 3 or not all(parts):
            parser.error(f"--host must be AZ:HOST_ID:ADDRESS, got {item!r}")
        hosts.append((parts[0], parts[1], parts[2]))

    manifest = build_manifest(
        fleet_id=args.fleet_id,
        hosts=hosts,
        user=args.user,
        private_key=str(Path(args.private_key).expanduser()),
        known_hosts=str(Path(args.known_hosts).expanduser()),
        ssh_port=args.ssh_port,
        port_first=args.port_first,
        port_last=args.port_last,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Validated by the product's own loader rather than by inspection, so a
    # manifest this writes is one a run can read - including the refusals
    # `host_inventory.py` owns, such as naming a host twice.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from valkey_scale_lab.runtime.host_inventory import load_host_inventory

    inventory = load_host_inventory(out)
    by_az = inventory.by_az()
    print(f"wrote {out} - fleet {inventory.fleet_id}, {len(inventory.hosts)} hosts")
    for az, items in by_az.items():
        print(f"  {az}: " + ", ".join(f"{host.host_id}={host.data_address}" for host in items))
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
