#!/usr/bin/env python3
"""Bring up a fleet of simulated ECS instances and emit its inventory manifest.

Lab tooling, outside the product. It imports nothing from `valkey_scale_lab`
and the product imports nothing from here. Docker stands where ECS will stand;
what crosses to the product is the manifest this writes, and nothing else.

The manifest names no container, no image and no Docker network, and it carries
no flag saying the fleet is simulated - a backend that could tell would make the
simulation worthless as evidence. What the harness knows about itself goes in a
sidecar `harness_provenance.json` beside the manifest, which the product never
reads. Whether a *run* records that its fleet was simulated is an evidence
question for a later item, not this file's to answer.

Each host record carries three addresses, because a real host has three roles
and conflating them is the mistake this harness exists to make visible:

  control_endpoint  how the controller runs commands on the host
  data_address      what the host's processes announce, and what peers dial
  client_endpoint   where the controller speaks RESP to those processes

Under this harness the second and third differ, because the macOS host cannot
route Docker's network; on a real fleet they usually coincide and the manifest
says so by carrying the same address twice. Either way a backend reads the same
three fields.

Everything in a host record that a real fleet would also have is read from the
host itself over its control endpoint - address, kernel, cpu and memory - rather
than from `docker inspect`. That is not tidiness: it is the demonstration that
the manifest can be produced the same way against hosts nobody started.

  python3 scripts/simulated_hosts.py up --fleet-id sim-a --hosts 2
  python3 scripts/simulated_hosts.py down --fleet-id sim-a
  python3 scripts/simulated_hosts.py list
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Neutral on purpose: the private key path appears in the manifest, and a
# directory called `simulated-*` would be exactly the tell this harness must not
# give the product.
STATE_ROOT = PROJECT_ROOT / "artifacts" / "host-fleets"
IMAGE = "valkey-scale-lab/simulated-host:debian13-sshd"
LABEL_PREFIX = "org.valkey-scale-lab"
FLEET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")
SSH_USER = "root"
READY_TIMEOUT_SECONDS = 60.0


class HarnessError(RuntimeError):
    pass


def _run(argv: list[str], *, timeout: float = 120.0, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode != 0:
        raise HarnessError(f"{' '.join(argv[:3])} failed ({result.returncode}): {result.stderr.strip()}")
    return result


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fleet_dir(fleet_id: str) -> Path:
    if not FLEET_ID_RE.fullmatch(fleet_id):
        raise HarnessError(f"fleet id must be lowercase alphanumeric with dashes: {fleet_id!r}")
    return STATE_ROOT / fleet_id


def _network_name(fleet_id: str) -> str:
    return f"vslab-sim-{fleet_id}"


def _container_name(fleet_id: str, index: int) -> str:
    return f"vslab-sim-{fleet_id}-{index:02d}"


def _host_id(index: int) -> str:
    return f"sim-host-{index:02d}"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _require_ports_free(ports: list[int]) -> None:
    taken = [port for port in ports if not _port_free(port)]
    if taken:
        raise HarnessError(f"ports already in use on 127.0.0.1: {taken[:8]}")


def client_port_blocks(base: int, hosts: int, per_host: int) -> list[tuple[int, int]]:
    """One contiguous, non-overlapping port block per host, inclusive at both ends.

    A block rather than a list because the controller cannot reach a host's
    processes on this harness except through published ports, and a real fleet
    states the same thing as a security-group range. The block is what the
    manifest hands a backend; which ports inside it a run uses is the run's.
    """
    if per_host < 1:
        raise HarnessError("each host needs at least one client port")
    return [(base + index * per_host, base + (index + 1) * per_host - 1) for index in range(hosts)]


def _ssh_argv(host: dict[str, Any], *, extra: list[str] | None = None) -> list[str]:
    control = host["control_endpoint"]
    argv = [
        "ssh",
        "-p",
        str(control["port"]),
        "-i",
        control["private_key_path"],
        "-o",
        f"UserKnownHostsFile={control['known_hosts_path']}",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
    ]
    argv.extend(extra or [])
    argv.append(f"{control['user']}@{control['address']}")
    return argv


def _ssh(host: dict[str, Any], command: str, *, timeout: float = 60.0, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(_ssh_argv(host) + [command], timeout=timeout, check=check)


def _keypair(fleet_dir: Path) -> tuple[Path, str]:
    key_path = fleet_dir / "ssh" / "id_ed25519"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        _run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                f"valkey-scale-lab-simulated-{fleet_dir.name}",
                "-f",
                str(key_path),
            ],
            timeout=60,
        )
        key_path.chmod(0o600)
    return key_path, (key_path.with_suffix(".pub")).read_text(encoding="utf-8").strip()


def _wait_for_sshd(port: int, deadline: float) -> None:
    last = ""
    while time.monotonic() < deadline:
        result = _run(["ssh-keyscan", "-p", str(port), "-t", "ed25519", "127.0.0.1"], timeout=15, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return
        last = result.stderr.strip()
        time.sleep(0.5)
    raise HarnessError(f"sshd on 127.0.0.1:{port} did not answer within the ready timeout: {last}")


def _known_hosts(fleet_dir: Path, hosts_ports: list[int]) -> tuple[Path, dict[int, str]]:
    known_hosts = fleet_dir / "ssh" / "known_hosts"
    lines: list[str] = []
    fingerprints: dict[int, str] = {}
    for port in hosts_ports:
        scanned = _run(["ssh-keyscan", "-p", str(port), "-t", "ed25519", "127.0.0.1"], timeout=20).stdout.strip()
        if not scanned:
            raise HarnessError(f"no host key served on 127.0.0.1:{port}")
        lines.append(scanned)
        listed = subprocess.run(
            ["ssh-keygen", "-lf", "-"], input=scanned + "\n", capture_output=True, text=True, timeout=20
        )
        if listed.returncode != 0:
            raise HarnessError(f"could not fingerprint the host key on port {port}: {listed.stderr.strip()}")
        fingerprints[port] = listed.stdout.split()[1]
    known_hosts.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return known_hosts, fingerprints


def _host_facts(host: dict[str, Any]) -> dict[str, Any]:
    """Read from the host what a real host would also be asked for."""
    script = (
        "set -eu; "
        ". /etc/os-release; "
        'printf "distribution=%s\\n" "$ID"; '
        'printf "version=%s\\n" "$VERSION_ID"; '
        'printf "kernel=%s\\n" "$(uname -r)"; '
        'printf "arch=%s\\n" "$(uname -m)"; '
        'printf "cpus=%s\\n" "$(getconf _NPROCESSORS_ONLN)"; '
        "printf \"memory_kb=%s\\n\" \"$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)\"; "
        "printf \"address=%s\\n\" \"$(ip -o -4 addr show scope global | awk 'NR==1 {split($4, a, \"/\"); print a[1]}')\""
    )
    parsed = dict(
        line.split("=", 1)
        for line in _ssh(host, script).stdout.strip().splitlines()
        if "=" in line
    )
    missing = {"distribution", "version", "kernel", "arch", "cpus", "memory_kb", "address"} - set(parsed)
    if missing:
        raise HarnessError(f"host did not report {sorted(missing)}")
    return {
        "data_address": parsed["address"],
        "os": {
            "kind": "linux",
            "distribution": parsed["distribution"],
            "version": parsed["version"],
            "kernel_release": parsed["kernel"],
            "arch": parsed["arch"],
        },
        "capacity": {
            "cpus": int(parsed["cpus"]),
            "memory_bytes": int(parsed["memory_kb"]) * 1024,
        },
    }


def _reject_container_vocabulary(manifest: dict[str, Any]) -> None:
    """The acceptance condition, enforced where the manifest is written.

    A manifest that leaked a container name, an image tag or a Docker network
    would let a backend behave differently against simulated hosts, and every
    result taken on them would then be about the harness rather than the
    product.
    """
    text = json.dumps(manifest)
    forbidden = ("container", "docker", "image", "vslab-sim", "simulated")
    hit = [word for word in forbidden if word in text.lower()]
    if hit:
        raise HarnessError(f"inventory manifest leaks harness vocabulary: {hit}")


def _build_manifest(*, fleet_id: str, hosts: list[dict[str, Any]]) -> dict[str, Any]:
    manifest = {
        "schema_version": "v1",
        "artifact_type": "host_inventory",
        "fleet_id": fleet_id,
        "generated_at": _now(),
        "host_count": len(hosts),
        "hosts": hosts,
    }
    _reject_container_vocabulary(manifest)
    return manifest


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _image_digest() -> str:
    return _run(["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"], timeout=60).stdout.strip()


def command_up(args: argparse.Namespace) -> int:
    fleet_dir = _fleet_dir(args.fleet_id)
    if (fleet_dir / "inventory.json").exists() and not args.force:
        raise HarnessError(f"fleet {args.fleet_id} already has an inventory; run `down` first or pass --force")
    for tool in ("docker", "ssh", "ssh-keygen", "ssh-keyscan"):
        if shutil.which(tool) is None:
            raise HarnessError(f"{tool} is required and is not on PATH")
    image_digest = _image_digest()

    azs = [az.strip() for az in args.azs.split(",") if az.strip()]
    if not azs:
        raise HarnessError("--azs must name at least one availability zone")

    ssh_ports = [args.ssh_port_base + index for index in range(args.hosts)]
    client_blocks = client_port_blocks(args.client_port_base, args.hosts, args.client_ports)
    if args.force:
        command_down(args)
    _require_ports_free(ssh_ports)
    _require_ports_free([port for first, last in client_blocks for port in range(first, last + 1)])

    fleet_dir.mkdir(parents=True, exist_ok=True)
    key_path, public_key = _keypair(fleet_dir)

    network = _network_name(args.fleet_id)
    existing = _run(["docker", "network", "ls", "--filter", f"name=^{network}$", "--format", "{{.Name}}"], timeout=60)
    if not existing.stdout.strip():
        _run(
            [
                "docker",
                "network",
                "create",
                "--label",
                f"{LABEL_PREFIX}.simulated-host.fleet_id={args.fleet_id}",
                network,
            ],
            timeout=120,
        )

    started = time.monotonic()
    for index in range(args.hosts):
        first, last = client_blocks[index]
        _run(
            [
                "docker",
                "run",
                "-d",
                "--init",
                "--cap-add",
                "NET_ADMIN",
                "--name",
                _container_name(args.fleet_id, index),
                "--hostname",
                _host_id(index),
                "--network",
                network,
                "--label",
                f"{LABEL_PREFIX}.simulated-host.fleet_id={args.fleet_id}",
                "--label",
                f"{LABEL_PREFIX}.simulated-host.host_id={_host_id(index)}",
                "-e",
                f"SIMULATED_HOST_AUTHORIZED_KEY={public_key}",
                "-p",
                f"127.0.0.1:{ssh_ports[index]}:22",
                "-p",
                f"127.0.0.1:{first}-{last}:{first}-{last}",
                IMAGE,
            ],
            timeout=300,
        )
    start_seconds = time.monotonic() - started

    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    for port in ssh_ports:
        _wait_for_sshd(port, deadline)
    known_hosts, fingerprints = _known_hosts(fleet_dir, ssh_ports)
    ready_seconds = time.monotonic() - started

    hosts: list[dict[str, Any]] = []
    for index in range(args.hosts):
        first, last = client_blocks[index]
        host = {
            "host_id": _host_id(index),
            "availability_zone": azs[index % len(azs)],
            "control_endpoint": {
                "protocols": ["ssh"],
                "address": "127.0.0.1",
                "port": ssh_ports[index],
                "user": SSH_USER,
                "private_key_path": str(key_path),
                "known_hosts_path": str(known_hosts),
                "host_key_fingerprint": fingerprints[ssh_ports[index]],
            },
            "client_endpoint": {
                "address": "127.0.0.1",
                "port_range": {"first": first, "last": last},
            },
        }
        host.update(_host_facts(host))
        hosts.append(host)

    manifest = _build_manifest(fleet_id=args.fleet_id, hosts=hosts)
    manifest_path = fleet_dir / "inventory.json"
    _write_json(manifest_path, manifest)
    _write_json(
        fleet_dir / "harness_provenance.json",
        {
            "schema_version": "v1",
            "artifact_type": "simulated_host_fleet_provenance",
            "fleet_id": args.fleet_id,
            "generated_at": _now(),
            "simulated": True,
            "image": IMAGE,
            "image_digest": image_digest,
            "network_name": network,
            "container_names": [_container_name(args.fleet_id, index) for index in range(args.hosts)],
            "host_count": args.hosts,
            "timing": {
                "container_start_seconds": round(start_seconds, 3),
                "ssh_ready_seconds": round(ready_seconds, 3),
            },
            "client_ports_published_per_host": args.client_ports,
        },
    )
    print(f"inventory: {manifest_path}")
    print(f"hosts: {args.hosts}  start: {start_seconds:.2f}s  ssh ready: {ready_seconds:.2f}s")
    return 0


def command_down(args: argparse.Namespace) -> int:
    fleet_dir = _fleet_dir(args.fleet_id)
    listed = _run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label={LABEL_PREFIX}.simulated-host.fleet_id={args.fleet_id}",
        ],
        timeout=60,
    ).stdout.split()
    for container in listed:
        _run(["docker", "rm", "-f", container], timeout=120, check=False)
    _run(["docker", "network", "rm", _network_name(args.fleet_id)], timeout=120, check=False)
    removed = fleet_dir / "inventory.json"
    if removed.exists():
        removed.unlink()
    print(f"removed {len(listed)} host(s) for fleet {args.fleet_id}")
    return 0


def command_list(_: argparse.Namespace) -> int:
    listed = _run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label={LABEL_PREFIX}.simulated-host.fleet_id",
            "--format",
            "{{.Names}}\t{{.Status}}",
        ],
        timeout=60,
    ).stdout.strip()
    print(listed or "no simulated hosts")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)

    up = subparsers.add_parser("up", help="start a fleet and write its inventory manifest")
    up.add_argument("--fleet-id", required=True)
    up.add_argument("--hosts", type=int, default=2)
    up.add_argument("--azs", default="az-a,az-b")
    up.add_argument("--ssh-port-base", type=int, default=22200)
    up.add_argument("--client-port-base", type=int, default=31000)
    up.add_argument(
        "--client-ports",
        type=int,
        default=60,
        help="ports per host the controller may reach, published as one range",
    )
    up.add_argument("--force", action="store_true")
    up.set_defaults(handler=command_up)

    down = subparsers.add_parser("down", help="remove a fleet")
    down.add_argument("--fleet-id", required=True)
    down.set_defaults(handler=command_down)

    listing = subparsers.add_parser("list", help="show every simulated host this harness started")
    listing.set_defaults(handler=command_list)

    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except HarnessError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
