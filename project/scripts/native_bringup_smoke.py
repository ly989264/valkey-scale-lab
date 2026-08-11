#!/usr/bin/env python3
"""Drive every seam operation no host has ever run, against live simulated hosts.

Lab tooling for roadmap item 1.5. It is the ladder's first rung and exists for
one reason, stated by `native_backend_slice_map.md` §11: between "the backend
exists, hermetically proven" and a native exact-30, there is no step where a
single native operation has touched a host *through the product*. A first
exact-30 failure would then have a dozen unexercised argv in its search space.

So this is not a test of the cluster. There is no Gate run, no cluster, no
scenario and no verdict - just the backend, two hosts, and a report of what each
operation actually did.

**What it deliberately does not re-prove.** `verify_image`, `reclaim_run`,
`start_nodehost` (claim *and* bundle install), `isolate_nodehost` and
`release_run` already run against live hosts through
`scripts/native_cleanup_proof.py`. They appear here only where the sequence
needs them.

**Ordering is derived, not arbitrary.** §11 of that map names the three argv a
fake transport cannot shape-check, and they go first: the digest-addressed
install, because every later argv runs under the `PATH` it establishes; the
`PATH`-prefixed `start_all.sh`, because a bundle that installed and cannot start
is a different failure; and `isolate_nodehost` -> `rejoin_nodehost`, because a
wrong control-port exception locks the actuator out of the host.

    python3 scripts/simulated_hosts.py up --fleet-id sim-smoke --hosts 2
    python3 scripts/native_bringup_smoke.py --fleet-id sim-smoke
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valkey_scale_lab.runtime import docker_runtime as _runtime  # noqa: E402
from valkey_scale_lab.runtime.host_evidence import (  # noqa: E402
    collect_node_journals,
    read_host_clocks,
)
from valkey_scale_lab.runtime.host_inventory import load_host_inventory  # noqa: E402
from valkey_scale_lab.runtime.native_backend import (  # noqa: E402
    NativeMultiEcsBackend,
    run_state_root,
)

RUN_ID = "native-bringup-smoke"
CAPABILITY_ID = "local_full_flow"
SCENARIO = "local_full_flow"
NETWORK_NAME = "vslab-native-bringup-smoke"
IMAGE = "valkey-scale-lab/valkey:9.1.0-myslots"
NODES_PER_HOST = 2


class SmokeFailure(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Reporting: every operation says what the host answered, pass or fail.
# --------------------------------------------------------------------------


class Report:
    """One line per seam operation, so a failure names an operation not a stack."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def step(self, operation: str, body: Callable[[], Any]) -> Any:
        started = time.monotonic()
        try:
            observed = body()
        except Exception as error:  # noqa: BLE001 - the report is the point
            self.rows.append(
                {
                    "operation": operation,
                    "status": "FAIL",
                    "seconds": round(time.monotonic() - started, 3),
                    "observed": f"{type(error).__name__}: {error}",
                }
            )
            raise SmokeFailure(operation) from error
        self.rows.append(
            {
                "operation": operation,
                "status": "PASS",
                "seconds": round(time.monotonic() - started, 3),
                "observed": _describe(observed),
            }
        )
        return observed

    def render(self) -> str:
        width = max((len(row["operation"]) for row in self.rows), default=20)
        lines = []
        for row in self.rows:
            lines.append(
                f"  {row['status']:4}  {row['operation']:<{width}}  "
                f"{row['seconds']:7.3f}s  {row['observed']}"
            )
        return "\n".join(lines)


def _describe(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        return value if len(value) <= 110 else value[:107] + "..."
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)[:110]
    if isinstance(value, list):
        return f"{len(value)} row(s): " + json.dumps(value, sort_keys=True)[:90]
    return str(value)[:110]


# --------------------------------------------------------------------------
# The records the lifecycle would have produced.
# --------------------------------------------------------------------------


def _bundle_dir() -> Path:
    roots = sorted((ROOT / "artifacts" / "native-bundles").glob("valkey-*"))
    if not roots:
        raise SmokeFailure("no native bundle built; run scripts/build_native_bundle.py")
    return roots[-1]


def _plan(fleet_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Nodehost and node records in the shapes `runtime/lifecycle.py` produces.

    Hand-built rather than planned, because a plan needs a configuration and a
    scenario and this rung deliberately has neither. The shapes are what matter:
    the operations under test read these fields, so a record shaped differently
    would prove something about this script instead of about the backend.
    """
    inventory = load_host_inventory(ROOT / "artifacts" / "host-fleets" / fleet_id / "inventory.json")
    if len(inventory.hosts) < 2:
        raise SmokeFailure(
            f"the smoke needs at least two hosts to isolate one; {fleet_id} has {len(inventory.hosts)}"
        )
    nodehosts: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    for index, host in enumerate(inventory.hosts):
        nodehost_id = f"nodehost-{host.az_id}-{index:02d}"
        nodehosts.append(
            {
                "nodehost_id": nodehost_id,
                "az_id": host.az_id,
                "ordinal": index,
                "container_name": f"vslab-{RUN_ID}-{nodehost_id}",
                "host_id": host.host_id,
                "host_control_endpoint": dict(host.control_endpoint),
                "host_data_address": host.data_address,
                "host_client_address": host.client_address,
                "logical_node_count": NODES_PER_HOST,
                "run_id": RUN_ID,
            }
        )
        for ordinal in range(NODES_PER_HOST):
            nodes.append(
                {
                    "logical_id": f"smoke-{index:02d}-{ordinal:02d}",
                    "ordinal": index * NODES_PER_HOST + ordinal,
                    "nodehost_id": nodehost_id,
                    "az_id": host.az_id,
                    "role": "primary",
                    "shard_id": f"shard-{index:04d}",
                    "client_port": int(host.client_port_first) + ordinal,
                    "cluster_bus_port": int(host.client_port_first) + ordinal + 10000,
                    "runtime_type": "native_multi_ecs",
                    "host_control_endpoint": dict(host.control_endpoint),
                    "host_id": host.host_id,
                }
            )
    return nodehosts, nodes


# --------------------------------------------------------------------------
# The smoke itself.
# --------------------------------------------------------------------------


def run_smoke(fleet_id: str, artifacts: Path, report: Report) -> Report:
    nodehosts, nodes = _plan(fleet_id)
    backend = NativeMultiEcsBackend(
        inventory_path=str(ROOT / "artifacts" / "host-fleets" / fleet_id / "inventory.json"),
        bundle_dir=str(_bundle_dir()),
    )
    nodehost_by_id = {str(item["nodehost_id"]): item for item in nodehosts}
    first, second = nodehosts[0], nodehosts[1]

    # --- the sequence runtime_start runs, up to the point a cluster would form
    report.step("verify_image", lambda: backend.verify_image(IMAGE))
    report.step(
        "reclaim_run",
        lambda: backend.reclaim_run(capability_id=CAPABILITY_ID, run_id=RUN_ID),
    )
    report.step(
        "create_network",
        lambda: backend.create_network(
            network_name=NETWORK_NAME, capability_id=CAPABILITY_ID, run_id=RUN_ID
        ),
    )

    def claim(nodehost: dict[str, Any]) -> str:
        started = backend.start_nodehost(
            nodehost,
            network_name=NETWORK_NAME,
            image=IMAGE,
            capability_id=CAPABILITY_ID,
            scenario=SCENARIO,
            run_id=RUN_ID,
        )
        nodehost["container_id"] = started.handle
        nodehost["container_ip"] = started.address
        nodehost["network_name"] = NETWORK_NAME
        return f"handle={started.handle} address={started.address}"

    for nodehost in nodehosts:
        report.step(f"start_nodehost[{nodehost['host_id']}]", lambda nh=nodehost: claim(nh))

    # `host_evidence.clock_exchanges`, through the lifecycle's own caller. The
    # ssh path from a claimed host to a recorded offset has never run.
    report.step(
        "host_evidence.clock_exchanges",
        lambda: {
            nodehost_id: {
                "offset_ms": reading.get("offset_ms"),
                "bound_ms": reading.get("round_trip_ms"),
            }
            for nodehost_id, reading in read_host_clocks(backend, nodehosts).items()
        },
    )

    # `client_host` runs inside this, once per node, and the bundle it writes is
    # the real one - `install.sh`, `start_all.sh`, `collect_pidfiles.sh`.
    report.step(
        "client_host + nodehost bundle write",
        lambda: _runtime._prepare_process_nodehost_bundles(
            backend=backend,
            nodes=nodes,
            nodehosts=nodehosts,
            nodehost_by_id=nodehost_by_id,
            artifacts=artifacts,
            run_id=RUN_ID,
        ),
    )

    # --- the three argv a fake transport cannot shape-check, first
    for nodehost in nodehosts:
        report.step(f"send_bundle[{nodehost['host_id']}]", lambda nh=nodehost: backend.send_bundle(nh))
        report.step(
            f"install_bundle[{nodehost['host_id']}]", lambda nh=nodehost: backend.install_bundle(nh)
        )
    for nodehost in nodehosts:
        report.step(
            f"start_node_processes[{nodehost['host_id']}]",
            lambda nh=nodehost: backend.start_node_processes(nh),
        )
        report.step(
            f"collect_node_pids[{nodehost['host_id']}]",
            lambda nh=nodehost: _record_pids(backend, nh, nodes),
        )

    report.step(
        "wait_nodes_ready",
        lambda: backend.wait_nodes_ready(nodes, timeout=60.0),
    )
    report.step(
        "run_cluster_admin",
        lambda: backend.run_cluster_admin(
            nodes[0],
            ["-p", str(nodes[0]["client_port"]), "PING"],
            timeout=30.0,
            operation_id="smoke",
            command_kind="smoke_ping",
        ),
    )

    # --- the actuator, on a host we are willing to lose, and its success path
    report.step("isolate_nodehost", lambda: backend.isolate_nodehost(second))
    report.step("rejoin_nodehost", lambda: backend.rejoin_nodehost(second))

    # --- one process's lifecycle
    node = nodes[0]
    report.step("stop_node", lambda: backend.stop_node(node, command_kind="smoke_stop"))
    report.step(
        "start_node",
        lambda: backend.start_node(node, fresh_cluster_identity=False),
    )
    report.step("pause_node", lambda: backend.pause_node(node))
    report.step("resume_node", lambda: backend.resume_node(node))
    report.step("pause_nodehost", lambda: _pause_and_count(backend, first))
    report.step("resume_nodehost", lambda: backend.resume_nodehost(first))
    report.step("kill_node", lambda: backend.kill_node(node))

    # --- the two evidence surfaces with no on-host proof at all
    report.step(
        "host_evidence.collect_node_journal",
        lambda: _journals(backend, nodehosts, nodes, artifacts),
    )
    report.step("resource_sampler", lambda: _sampler(backend, first, nodes, artifacts))
    report.step("load_lane_host", lambda: _load_lane(backend, nodes[1], artifacts))

    # --- and put the hosts back
    report.step(
        "release_run",
        lambda: _release(backend, nodehosts, nodes),
    )
    return report


def _record_pids(backend: NativeMultiEcsBackend, nodehost: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, int]:
    collected = backend.collect_node_pids(nodehost)
    for node in nodes:
        if node["logical_id"] in collected:
            node["pid"] = int(collected[node["logical_id"]])
    return collected


def _pause_and_count(backend: NativeMultiEcsBackend, nodehost: dict[str, Any]) -> dict[str, Any]:
    """`pause_nodehost`, and the measurement roadmap item 1.5 owes §7.2.

    The actuator still enumerates `<run_root>/*/valkey.pid`, the notion of "what
    is running" both cleanup paths abandoned. What matters is whether the pidfile
    set and the live set agree at the moment pause acts; if they do not, the
    actuator can signal a reused pid. Reported here rather than asserted, because
    the decision belongs to the fault lane's own measurement at exact-30.
    """
    rows = backend.pause_nodehost(nodehost)
    signalled = rows[0].get("stdout_tail", "").strip() if rows else ""
    endpoint = nodehost["host_control_endpoint"]
    run_root = run_state_root(RUN_ID)
    pidfiles = backend._run(
        endpoint, ["sh", "-c", f'ls -1 {run_root}/*/valkey.pid 2>/dev/null | wc -l'], timeout=30
    ).stdout.strip()
    live = backend._run(
        endpoint,
        [
            "sh",
            "-c",
            "count=0; for p in /proc/[0-9]*; do "
            f'case "$(readlink "$p/cwd" 2>/dev/null)" in {run_root}/*) count=$((count+1));; esac; '
            "done; printf %s \"$count\"",
        ],
        timeout=30,
    ).stdout.strip()
    return {"signalled": signalled, "pidfiles": pidfiles, "live_owned_processes": live}


def _journals(
    backend: NativeMultiEcsBackend,
    nodehosts: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    artifacts: Path,
) -> dict[str, Any]:
    """Through the lifecycle's own caller, not the raw verb.

    `collect_node_journals` is what `runtime_start` calls, and it is the half of
    `host_evidence` that has never run over ssh through the product.
    """
    journals = artifacts / "node_journals"
    collected = collect_node_journals(backend, nodehosts, nodes, journals)
    files = sorted(journals.rglob("*.log"))
    return {
        "hosts": len(collected),
        "journals": len(files),
        "bytes": sum(item.stat().st_size for item in files),
    }


def _sampler(
    backend: NativeMultiEcsBackend,
    nodehost: dict[str, Any],
    nodes: list[dict[str, Any]],
    artifacts: Path,
) -> dict[str, Any]:
    hosted = [node for node in nodes if node["nodehost_id"] == nodehost["nodehost_id"]]
    sampler = backend.resource_sampler(
        hosted,
        sampler_id=str(nodehost["nodehost_id"]),
        processes=[
            (str(node["logical_id"]), int(node["pid"])) for node in hosted if node.get("pid")
        ],
        expected_gone=[],
    )
    sampler.start()
    time.sleep(3.0)
    stopped = sampler.stop()
    return {"samples": len(stopped.get("samples", [])), "keys": sorted(stopped)[:6]}


def _load_lane(backend: NativeMultiEcsBackend, node: dict[str, Any], artifacts: Path) -> dict[str, Any]:
    """The lane's two verbs: express a command, and bring back what it wrote."""
    lane = backend.load_lane_host(node)
    remote_dir = f"/tmp/vslab-load-lane/{RUN_ID}/smoke"
    # An **absolute** output path, because that is what the lane really does:
    # `_output_prefix` hands memtier `<remote_dir>/memtier_<label>.json`. The
    # first version of this step wrote a relative path and `collect_evidence`
    # correctly brought back an empty directory - the command's `exec` does not
    # cd into the directory its `mkdir -p` created. A transfer that copies
    # nothing is not proof of a transfer.
    argv = lane.command(
        ["sh", "-c", f"printf 'smoke\\n' > {remote_dir}/lane.json"], remote_dir=remote_dir
    )
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise SmokeFailure(f"load lane command failed: {result.stderr.strip()[:200]}")
    local = artifacts / "load_lane"
    lane.collect_evidence(remote_dir, local)
    collected = sorted(item.name for item in local.iterdir())
    if "lane.json" not in collected:
        raise SmokeFailure(
            f"the load lane wrote lane.json on the host and the collection brought back {collected}"
        )
    return {
        "seed_host": lane.seed_host,
        "collected": collected,
        "bytes": (local / "lane.json").stat().st_size,
    }


def _release(
    backend: NativeMultiEcsBackend, nodehosts: list[dict[str, Any]], nodes: list[dict[str, Any]]
) -> dict[str, Any]:
    teardown = backend.release_run(
        {
            "capability_id": CAPABILITY_ID,
            "scenario": SCENARIO,
            "backend_id": "native_multi_ecs",
            "runtime": {"type": "native_multi_ecs", "run_id": RUN_ID},
            "nodehosts": nodehosts,
            "nodes": nodes,
        }
    )
    residue = [row for row in teardown.actions if row.get("action") == "scan"]
    return {
        "actions": len(teardown.actions),
        "kinds": sorted({str(row.get("action")) for row in teardown.actions}),
        "residue_rows": [row.get("stdout", "")[:60] for row in residue],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fleet-id", default="sim-smoke")
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=ROOT / "artifacts" / "native-bringup-smoke",
        help="where the bundles and collected evidence land",
    )
    args = parser.parse_args()

    if args.artifacts.exists():
        shutil.rmtree(args.artifacts)
    args.artifacts.mkdir(parents=True)

    print(f"native bring-up smoke: fleet={args.fleet_id} artifacts={args.artifacts}")
    # The report is built outside the run and printed either way. A smoke whose
    # output vanished on the first failure would answer the one question it
    # exists to answer - which operation - with a stack trace.
    report = Report()
    failure: BaseException | None = None
    try:
        run_smoke(args.fleet_id, args.artifacts, report)
    except SmokeFailure as error:
        failure = error.__cause__ or error

    print(report.render())
    failed = [row for row in report.rows if row["status"] != "PASS"]
    print(f"\n{len(report.rows) - len(failed)}/{len(report.rows)} operations answered")
    (args.artifacts / "smoke_report.json").write_text(
        json.dumps(report.rows, indent=2) + "\n", encoding="utf-8"
    )
    if failure is not None:
        print("\n--- the failing operation, in full ---", file=sys.stderr)
        traceback.print_exception(type(failure), failure, failure.__traceback__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
