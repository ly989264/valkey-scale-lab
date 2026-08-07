#!/usr/bin/env python3
"""Diff one lifecycle stage's artifacts between two runs.

The refactor's per-slice acceptance bar compares a real run against the frozen
pre-refactor baseline in `artifacts/baselines/`, ignoring only timestamps,
durations, run ids and temporary paths. This is the tool that does it.

    ./scripts/diff_stage_artifacts.py --stage runtime_start BASELINE CANDIDATE

BASELINE and CANDIDATE are the `runtime` directories of a gate run, for example
`artifacts/gate-runs/<run>/001-real.local.full-flow/runtime`.

Calibrate before trusting a result. Diffing the two baseline runs against each
other must report every view identical:

    ./scripts/diff_stage_artifacts.py --stage runtime_start \\
        artifacts/baselines/exact-50-6b6f57fd/run-1/001-real.local.full-flow/runtime \\
        artifacts/baselines/exact-50-6b6f57fd/run-2/001-real.local.full-flow/runtime

Two runs of the same code differ in more than the clock, and a normalisation
that hides those differences would hide a regression with them. Everything this
tool ignores is listed in IGNORED below, and anything that varies per run but
still carries evidence is renamed rather than dropped, so that its absence
cannot pass as a match.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path
from typing import Any, Callable

# A measured duration varies per run; a configured one must not. Every
# `_seconds` field in these artifacts is measured, but `_ms` splits both ways -
# `cluster_node_timeout_ms` and its siblings are configuration, and dropping
# them would let a change to the cluster timeout contract diff clean.
IGNORED = re.compile(
    r"^("
    r".*_seconds"
    r"|duration_ms"
    r"|.*_monotonic_ms"
    r"|created_at_unix_ms"
    r"|monotonic"
    r"|wall_time"
    r")$"
)
GATE_RUN = re.compile(r"gate-\d{8}T\d{6}Z-[0-9a-f]+")
ARTIFACTS_PATH = re.compile(r"^/.*/artifacts/")


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            # A pid varies per run like a timestamp does, but whether a node has
            # one at all is evidence, so it is replaced rather than dropped.
            key: ("<PID>" if key == "pid" and isinstance(item, int) else scrub(item))
            for key, item in sorted(value.items())
            if not IGNORED.match(key)
        }
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        return ARTIFACTS_PATH.sub("<ARTIFACTS>/", GATE_RUN.sub("<GATE_RUN>", value))
    return value


def load(path: Path) -> Any:
    return scrub(json.loads(path.read_text(encoding="utf-8")))


def nodehost_id_by_address(root: Path) -> dict[str, str]:
    """Docker hands out the subnet in nodehost start order, so an address is
    only comparable across runs once it is named by the nodehost holding it."""
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    return {
        str(node["nodehost_container_ip"]): str(node["nodehost_id"])
        for node in state["nodes"]
        if node.get("nodehost_container_ip")
    }


def lifecycle_step(root: Path, stage: str) -> Any:
    steps = json.loads((root / "lifecycle_timeline.json").read_text(encoding="utf-8"))["steps"]
    return scrub([step for step in steps if step["id"] == stage])


def timing_rows(root: Path, names: set[str]) -> Any:
    document = json.loads(
        (root / "runtime_timing_breakdown_local_full_flow.json").read_text(encoding="utf-8")
    )
    return scrub([row for row in document.get("timings", []) if row.get("name") in names])


def bundle_manifests(root: Path) -> Any:
    return {
        path.parent.name: load(path)
        for path in sorted(root.glob("nodehost_bundles/*/manifest.json"))
    }


def node_configs(root: Path) -> Any:
    by_address = nodehost_id_by_address(root)
    configs = {}
    for path in sorted(root.glob("node_configs/*.conf")):
        text = path.read_text(encoding="utf-8")
        for address, nodehost_id in by_address.items():
            text = text.replace(address, f"<nodehost:{nodehost_id}>")
        configs[path.name] = text
    return configs


def state_before_cluster(root: Path) -> Any:
    """The part of state.json runtime_start writes, before cluster formation."""
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    runtime = state.get("runtime", {})
    node_fields = (
        "logical_id",
        "nodehost_id",
        "az_id",
        "host_id",
        "role",
        "shard_id",
        "client_port",
        "cluster_bus_port",
        "data_dir",
        "log_file",
        "config_file",
        "pid_file",
        "pid",
        "requested_cluster_node_timeout_ms",
        "effective_cluster_node_timeout_ms",
        "cluster_node_timeout_source",
    )
    return scrub(
        {
            "backend_id": state.get("backend_id"),
            "profile_id": state.get("profile_id"),
            "requested_nodes": state.get("requested_nodes"),
            "observed_nodes": state.get("observed_nodes"),
            "runtime_type": runtime.get("type"),
            "nodehost_count": runtime.get("nodehost_count"),
            "actual_nodehost_count": runtime.get("actual_nodehost_count"),
            "process_bootstrap_batching": runtime.get("process_bootstrap_batching"),
            "valkey_image_preflight": runtime.get("valkey_image_preflight"),
            "nodes": [{key: node.get(key) for key in node_fields} for node in state.get("nodes", [])],
        }
    )


# Each slice adds its stage here from its own slice map, once that map has said
# which artifacts the stage owns. Views are not written ahead of a slice.
STAGE_VIEWS: dict[str, dict[str, Callable[[Path], Any]]] = {
    "runtime_start": {
        "lifecycle_timeline:runtime_start": lambda root: lifecycle_step(root, "runtime_start"),
        "runtime_timing_breakdown:stage_rows": lambda root: timing_rows(
            root,
            {"nodehost_start", "process_config_prepare", "process_start", "process_ready_wait"},
        ),
        "nodehost_density_plan": lambda root: load(root / "nodehost_density_plan.json"),
        "generated_valkey_configs_manifest": lambda root: load(
            root / "generated_valkey_configs_manifest.json"
        ),
        "nodehost_bundle_manifests": bundle_manifests,
        "node_configs": node_configs,
        "state:before_cluster": state_before_cluster,
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=sorted(STAGE_VIEWS))
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()

    views = STAGE_VIEWS[args.stage]
    failures = 0
    for name, view in views.items():
        try:
            left, right = view(args.baseline), view(args.candidate)
        except Exception as exc:  # noqa: BLE001 - a view that cannot be built is a result
            print(f"{name}: ERROR {exc!r}")
            failures += 1
            continue
        if left == right:
            print(f"{name}: SAME")
            continue
        failures += 1
        print(f"{name}: DIFFERS")
        diff = difflib.unified_diff(
            json.dumps(left, indent=2, sort_keys=True).splitlines(),
            json.dumps(right, indent=2, sort_keys=True).splitlines(),
            "baseline",
            "candidate",
            lineterm="",
        )
        for line in list(diff)[:80]:
            print("   " + line)
    print(f"\n{len(views) - failures}/{len(views)} views identical")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
