#!/usr/bin/env python3
"""Prove roadmap item 1.4's cleanup on simulated hosts, by placing real residue.

Lab tooling, outside the product, in the sense `simulated_hosts.py` is: it drives
`NativeMultiEcsBackend` from outside and then asks the hosts directly - over its
own ssh, not through the backend - what is left. A cleanup proof that asked the
thing being proved would be worth nothing.

What it places is the full residue set a native run can leave:

  * real `valkey-server` processes, started from the pinned bundle with the
    config the lifecycle generates (`daemonize yes`, `dir <data_dir>`);
  * a long-lived non-Valkey process with its working directory inside the run
    tree, standing for the on-host resource agent;
  * the run's state tree and its run bundle directory;
  * the actuator's iptables chain and both of its jumps, installed by
    `isolate_nodehost` itself;
  * an ssh control master per host.

Three subcommands:

  release   place the residue, then `release_run`, then check the hosts.
  abort     place the residue in a child process, SIGKILL it, then `reclaim_run`
            from this one, then check the hosts. This is the acceptance's "abort
            a simulated-host run mid-flight".
  stage     place the residue and wait to be killed. `abort` runs this.

This is not item 1.5's bring-up smoke: no cluster is formed, no scenario runs, no
Gate step is invoked, and the seam's operations are driven only as far as placing
residue needs.

    python3 scripts/native_cleanup_proof.py release --fleet-id sim-a
    python3 scripts/native_cleanup_proof.py abort   --fleet-id sim-a
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valkey_scale_lab.runtime.host_inventory import load_host_inventory  # noqa: E402
from valkey_scale_lab.runtime.host_transport import MultiplexedSshTransport  # noqa: E402
from valkey_scale_lab.runtime.native_backend import (  # noqa: E402
    NativeMultiEcsBackend,
    run_state_root,
)
from valkey_scale_lab.runtime.native_bundle import verify_native_bundle  # noqa: E402

RUN_ID = "cleanup-proof-run"
NODES_PER_HOST = 2


def _fleet_dir(fleet_id: str) -> Path:
    return ROOT / "artifacts" / "host-fleets" / fleet_id


def _bundle_dir() -> Path:
    roots = sorted((ROOT / "artifacts" / "native-bundles").glob("valkey-*"))
    if not roots:
        raise SystemExit("no native bundle built; run scripts/build_native_bundle.py")
    return roots[-1]


def _plan(fleet_id: str) -> tuple[list[dict], list[dict]]:
    """Nodehost and node records shaped the way the lifecycle shapes them."""
    inventory = load_host_inventory(_fleet_dir(fleet_id) / "inventory.json")
    nodehosts, nodes = [], []
    for index, host in enumerate(inventory.hosts):
        nodehost_id = f"nodehost-{host.az_id}-{index:02d}"
        nodehosts.append(
            {
                "nodehost_id": nodehost_id,
                "az_id": host.az_id,
                "ordinal": index,
                "container_name": f"vslab-{RUN_ID}-{nodehost_id}",
                "bundle_name": f"vslab-bundle-{RUN_ID}-{nodehost_id}",
                "remote_bundle_dir": f"/tmp/vslab-bundle-{RUN_ID}-{nodehost_id}",
                "host_id": host.host_id,
                "host_control_endpoint": dict(host.control_endpoint),
                "host_data_address": host.data_address,
                "host_client_address": host.client_address,
                "logical_node_count": NODES_PER_HOST,
            }
        )
        first_port = int(host.client_port_first)
        for ordinal in range(NODES_PER_HOST):
            logical_id = f"node-{index}{ordinal:02d}"
            data_dir = f"{run_state_root(RUN_ID)}/{logical_id}"
            nodes.append(
                {
                    "logical_id": logical_id,
                    "nodehost_id": nodehost_id,
                    "run_id": RUN_ID,
                    "client_port": first_port + ordinal,
                    "data_dir": data_dir,
                    "config_file": f"{data_dir}/valkey.conf",
                    "pid_file": f"{data_dir}/valkey.pid",
                    "log_file": f"{data_dir}/valkey.log",
                    "host_control_endpoint": dict(host.control_endpoint),
                    "host_id": host.host_id,
                    # Deliberately a pid that was never this run's. Teardown must
                    # not use it, and the report must show it did not.
                    "pid": 999_001 + ordinal,
                }
            )
    return nodehosts, nodes


def _state(nodehosts: list[dict], nodes: list[dict]) -> dict:
    return {
        "capability_id": "local_full_flow",
        "scenario": "local_full_flow",
        "backend_id": "native_multi_ecs",
        "runtime": {"type": "native_multi_ecs", "run_id": RUN_ID},
        "nodehosts": nodehosts,
        "nodes": nodes,
    }


def _config_text(node: dict) -> str:
    """`_process_config_text`'s shape, in the parts cleanup depends on."""
    return "\n".join(
        [
            f"port {node['client_port']}",
            "bind 0.0.0.0",
            "protected-mode no",
            "cluster-enabled yes",
            "cluster-config-file nodes.conf",
            f"cluster-port {node['client_port'] + 10000}",
            "appendonly no",
            f"dir {node['data_dir']}",
            "daemonize yes",
            f"pidfile {node['pid_file']}",
            f"logfile {node['log_file']}",
            "",
        ]
    )


def place(backend: NativeMultiEcsBackend, nodehosts: list[dict], nodes: list[dict]) -> None:
    """Put the whole residue set on the hosts."""
    evidence = verify_native_bundle(_bundle_dir())
    binpath = f"/opt/valkey-scale-lab/bundles/{str(evidence['archive_sha256'])[:16]}/bin"
    run_root = run_state_root(RUN_ID)
    # What the lifecycle does before `start_nodehost`, and for the same reason:
    # that operation refuses a host still carrying this run's state.
    backend.reclaim_run(capability_id="local_full_flow", run_id=RUN_ID)
    for nodehost in nodehosts:
        endpoint = nodehost["host_control_endpoint"]
        # The operation that claims a host and installs the pinned bundle on it,
        # because residue placed without it would not be the residue a run
        # leaves.
        backend.start_nodehost(
            nodehost,
            network_name="vslab-cleanup-proof",
            image="valkey-scale-lab/valkey:9.1.0",
            capability_id="local_full_flow",
            scenario="local_full_flow",
            run_id=RUN_ID,
        )
        backend._run(endpoint, ["mkdir", "-p", nodehost["remote_bundle_dir"]], timeout=60)
        hosted = [node for node in nodes if node["nodehost_id"] == nodehost["nodehost_id"]]
        for node in hosted:
            backend._run(endpoint, ["mkdir", "-p", node["data_dir"]], timeout=60)
            backend._run(
                endpoint,
                ["sh", "-c", f"cat > {node['config_file']} <<'EOF'\n{_config_text(node)}\nEOF"],
                timeout=60,
            )
            started = backend._run(
                endpoint,
                ["sh", "-c", f"PATH={binpath}:$PATH; valkey-server {node['config_file']}"],
                timeout=60,
            )
            if started.returncode != 0:
                raise SystemExit(f"could not start {node['logical_id']}: {started.stderr}")
        # Standing in for the on-host resource agent: a non-Valkey process whose
        # working directory is inside the run tree.
        agent_dir = f"{run_root}/.resource-agent/{nodehost['nodehost_id']}"
        backend._run(endpoint, ["mkdir", "-p", agent_dir], timeout=60)
        backend._run(
            endpoint,
            ["sh", "-c", f"cd {agent_dir} && nohup python3 -c 'import time; time.sleep(3600)' >/dev/null 2>&1 & sleep 0.2; echo ok"],
            timeout=60,
        )
    # The actuator's own rules, installed by the operation that installs them.
    backend.isolate_nodehost({**nodehosts[0], "run_id": RUN_ID})
    time.sleep(1.0)


def observe(fleet_id: str, nodehosts: list[dict]) -> dict:
    """Ask the hosts what is there, over a channel the product is not using."""
    transport = MultiplexedSshTransport(control_root="/tmp/vslab-proof-observer")
    run_root = run_state_root(RUN_ID)
    found: dict[str, dict] = {}
    try:
        for nodehost in nodehosts:
            endpoint = nodehost["host_control_endpoint"]
            processes = transport.run(
                endpoint,
                [
                    "sh",
                    "-c",
                    f"root={run_root}; for e in /proc/[0-9]*; do "
                    'c=$(readlink "$e/cwd" 2>/dev/null) || continue; '
                    'case "$c/" in "$root"/*) ;; *) continue;; esac; '
                    'printf "%s %s\\n" "${e#/proc/}" "$(readlink "$e/exe" 2>/dev/null)"; done; exit 0',
                ],
                timeout=60,
            )
            tree = transport.run(
                endpoint, ["sh", "-c", f"ls -d {run_root} {nodehost['remote_bundle_dir']} 2>/dev/null; exit 0"], timeout=60
            )
            rules = transport.run(
                endpoint, ["sh", "-c", "iptables -S | grep -E '^-N|vslab-run' ; exit 0"], timeout=60
            )
            # `[n]otty` so the probe's own shell, whose command line contains
            # the pattern, is not counted. Not `sshd:` - OpenSSH 9.8 renamed the
            # per-session process to `sshd-session`, and matching the old name
            # silently counted zero.
            sessions = transport.run(
                endpoint, ["sh", "-c", "ps -eo args= | grep -c '[n]otty' ; exit 0"], timeout=60
            )
            found[nodehost["host_id"]] = {
                "processes": [line for line in processes.stdout.splitlines() if line.strip()],
                "paths": [line for line in tree.stdout.splitlines() if line.strip()],
                "rules": [line for line in rules.stdout.splitlines() if line.strip()],
                # This observer holds exactly one session of its own on every
                # host; anything beyond it is a channel somebody else left open.
                "other_sessions": max(int(sessions.stdout.strip() or 0) - 1, 0),
            }
    finally:
        transport.close()
    return found


def _residue_total(observation: dict) -> int:
    """The three kinds roadmap item 1.4 names: processes, state, and rules.

    Open ssh sessions are counted and printed separately rather than folded in.
    They are the control channel, not a managed resource of the run, and unlike
    the three they carry no run-scoped mark - nothing on a host says which run an
    ssh session belongs to. `release_run` closes the ones it opened; an aborted
    controller's cannot be attributed by whatever reclaims after it. See the
    slice map §8.2.
    """
    return sum(
        len(host["processes"]) + len(host["paths"]) + len(host["rules"])
        for host in observation.values()
    )


def _session_total(observation: dict) -> int:
    return sum(host["other_sessions"] for host in observation.values())


def _report(label: str, observation: dict) -> None:
    print(f"\n=== {label} ===")
    for host_id, host in sorted(observation.items()):
        print(f"  {host_id}:")
        print(f"    processes in the run tree : {len(host['processes'])} {host['processes']}")
        print(f"    run paths                 : {host['paths']}")
        print(f"    firewall                  : {host['rules']}")
        print(f"    other ssh sessions        : {host['other_sessions']}")
    print(f"  TOTAL MANAGED RESIDUE (processes + state + rules): {_residue_total(observation)}")
    print(f"  open control channels (reported, not part of the verdict): {_session_total(observation)}")


def _backend(fleet_id: str) -> NativeMultiEcsBackend:
    backend = NativeMultiEcsBackend(
        bundle_dir=_bundle_dir(), inventory_path=_fleet_dir(fleet_id) / "inventory.json"
    )
    backend.verify_image("valkey-scale-lab/valkey:9.1.0")
    return backend


def cmd_stage(args: argparse.Namespace) -> int:
    nodehosts, nodes = _plan(args.fleet_id)
    place(_backend(args.fleet_id), nodehosts, nodes)
    print("STAGED", flush=True)
    time.sleep(3600)
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    nodehosts, nodes = _plan(args.fleet_id)
    backend = _backend(args.fleet_id)
    place(backend, nodehosts, nodes)
    _report("residue placed", observe(args.fleet_id, nodehosts))

    teardown = backend.release_run(_state(nodehosts, nodes))
    print("\n=== release_run report ===")
    for action in teardown.actions:
        print(f"  {action['id']:<24} {action['action']:<12} {action['status']:<20} "
              + json.dumps({k: v for k, v in action.items()
                            if k in {"pid_count", "state_pid_count", "alive_pid_count",
                                     "killed_pid_count", "jump_count", "chain_count", "found"}}))
    print(f"  resources_remaining: {teardown.resources_remaining}")
    print(f"  errors: {teardown.errors}")

    after = observe(args.fleet_id, nodehosts)
    _report("after release_run", after)
    return 0 if _residue_total(after) == 0 and not teardown.resources_remaining else 1


def cmd_abort(args: argparse.Namespace) -> int:
    nodehosts, _nodes = _plan(args.fleet_id)
    child = subprocess.Popen(
        [sys.executable, __file__, "stage", "--fleet-id", args.fleet_id],
        stdout=subprocess.PIPE, text=True,
    )
    assert child.stdout is not None
    for line in child.stdout:
        if line.strip() == "STAGED":
            break
    # SIGKILL, not SIGINT: an interrupt runs Python's finalizers and could be
    # argued to have been given a chance to clean up. This controller does not
    # get one.
    os.kill(child.pid, signal.SIGKILL)
    child.wait()
    print(f"controller pid {child.pid} SIGKILLed mid-flight")

    before = observe(args.fleet_id, nodehosts)
    _report("after the abort, before reclaim", before)
    if _residue_total(before) == 0:
        print("!! nothing was stranded, so the proof would prove nothing")
        return 1

    # A fresh process, which is what the next run would be.
    reclaim = subprocess.run(
        [sys.executable, __file__, "reclaim", "--fleet-id", args.fleet_id],
        capture_output=True, text=True,
    )
    print(reclaim.stdout.strip() or reclaim.stderr.strip())

    after = observe(args.fleet_id, nodehosts)
    _report("after reclaim_run", after)
    return 0 if _residue_total(after) == 0 else 1


def cmd_reclaim(args: argparse.Namespace) -> int:
    backend = _backend(args.fleet_id)
    backend.reclaim_run(capability_id="local_full_flow", run_id=RUN_ID)
    # `reclaim_run` deliberately does not close the channel the way `release_run`
    # does: on a run's own path it is called before `create_network` and the run
    # goes on using that transport. A caller that reclaims and then stops is the
    # one that has to give it back, which is what this is.
    backend._release_transport()
    print("reclaim_run returned")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["release", "abort", "stage", "reclaim"])
    parser.add_argument("--fleet-id", default="sim-a")
    args = parser.parse_args()
    return {
        "release": cmd_release,
        "abort": cmd_abort,
        "stage": cmd_stage,
        "reclaim": cmd_reclaim,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
