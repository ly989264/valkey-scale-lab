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
NODE_ID = re.compile(r"\b[0-9a-f]{40}\b")

CLUSTER_FORM_TIMING_ROWS = {
    "primary_cluster_create",
    "cluster_slots_assign",
    "replica_meet",
    "replica_replicate",
    "runtime_representative_probe",
    "runtime_final_full_probe",
    "runtime_diagnostic_full_probe",
}


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


def node_id_names(root: Path) -> dict[str, str]:
    """Valkey generates a node id at node start, so it varies per run like a pid.

    Which node an id belongs to is evidence - a replica following the wrong
    primary must not diff clean - so an id is named rather than dropped.
    `cluster_myslots_report.json` is the artifact that records both halves.
    """
    report = json.loads((root / "cluster_myslots_report.json").read_text(encoding="utf-8"))
    return {str(node["node-id"]): f"<node:{node['logical_id']}>" for node in report["nodes"]}


def rename_node_ids(value: Any, names: dict[str, str]) -> Any:
    """An id with no known node becomes UNKNOWN rather than disappearing."""
    if isinstance(value, dict):
        return {key: rename_node_ids(item, names) for key, item in value.items()}
    if isinstance(value, list):
        return [rename_node_ids(item, names) for item in value]
    if isinstance(value, str):
        return NODE_ID.sub(lambda match: names.get(match.group(0), "<node:UNKNOWN>"), value)
    return value


def sorted_samples(summary: dict[str, Any]) -> dict[str, Any]:
    """Snapshot samples arrive in completion order, which is not evidence."""
    if isinstance(summary.get("samples"), list):
        summary = dict(summary)
        summary["samples"] = sorted(summary["samples"], key=lambda item: str(item["logical_id"]))
    return summary


def cluster_form_timing_rows(root: Path) -> Any:
    """The cluster_form rows of the timing breakdown.

    `runtime_all_node_light_probe` is deliberately absent. It counts convergence
    retries, and the two frozen baseline runs genuinely differ - one converged
    on its first attempt, the other needed thirty and recorded the interim
    failure. Nothing can normalise that apart without also hiding a regression,
    so `main` reports its count and status instead of diffing them.
    """
    names = node_id_names(root)
    rows = []
    for row in rename_node_ids(timing_rows(root, CLUSTER_FORM_TIMING_ROWS), names):
        details = row.get("details")
        if isinstance(details, dict):
            diagnostics = details.get("replica_diagnostics")
            if isinstance(diagnostics, list):
                details["replica_diagnostics"] = sorted(
                    diagnostics, key=lambda item: str(item["logical_id"])
                )
            slowest = details.get("slowest_replicas")
            if isinstance(slowest, list):
                # A ranking by a duration this tool already ignores: which
                # replicas were slowest is noise, what was recorded about them
                # is not. Every replica is still compared in full above.
                details["slowest_replicas"] = {
                    "row_count": len(slowest),
                    "row_content": sorted(
                        {
                            json.dumps(
                                {
                                    key: item[key]
                                    for key in item
                                    if key not in {"logical_id", "shard_id", "master_id"}
                                },
                                sort_keys=True,
                            )
                            for item in slowest
                        }
                    ),
                }
        rows.append(row)
    return rows


def cluster_snapshots(root: Path) -> Any:
    document = json.loads(
        (root / "cluster_snapshots_local_full_flow.json").read_text(encoding="utf-8")
    )
    return scrub([sorted_samples(snapshot) for snapshot in document])


def state_after_cluster(root: Path) -> Any:
    """The part of state.json cluster_form writes, the recorded operations."""
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    names = node_id_names(root)
    operations = []
    for operation in state.get("runtime", {}).get("operations", []):
        operation = dict(operation)
        details = operation.get("details")
        if isinstance(details, dict):
            operation["details"] = sorted_samples(details)
        operations.append(operation)
    return rename_node_ids(scrub(operations), names)


def light_probe_retries(root: Path) -> str:
    """Reported, not diffed - see `cluster_form_timing_rows`."""
    for row in json.loads(
        (root / "runtime_timing_breakdown_local_full_flow.json").read_text(encoding="utf-8")
    ).get("timings", []):
        if row.get("name") == "runtime_all_node_light_probe":
            return f"count={row.get('count')} status={row.get('status')}"
    return "absent"


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
    "cluster_form": {
        "lifecycle_timeline:cluster_form": lambda root: lifecycle_step(root, "cluster_form"),
        "runtime_timing_breakdown:stage_rows": cluster_form_timing_rows,
        "runtime_timing_breakdown:summary": lambda root: scrub(
            json.loads(
                (root / "runtime_timing_breakdown_local_full_flow.json").read_text(
                    encoding="utf-8"
                )
            ).get("summary", {})
        ),
        "cluster_snapshots": cluster_snapshots,
        "state:after_cluster": state_after_cluster,
    },
}

# A stage may have evidence that cannot be diffed but must not go unreported.
STAGE_REPORTED: dict[str, dict[str, Callable[[Path], str]]] = {
    "cluster_form": {"runtime_all_node_light_probe": light_probe_retries},
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=sorted(STAGE_VIEWS))
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()

    views = STAGE_VIEWS[args.stage]
    failures = 0
    unavailable = 0
    for name, view in views.items():
        def build(root: Path) -> tuple[Any, str | None]:
            try:
                return view(root), None
            except Exception as exc:  # noqa: BLE001 - a view that cannot be built is a result
                return None, repr(exc)

        left, left_error = build(args.baseline)
        right, right_error = build(args.candidate)
        if left_error and right_error == left_error:
            # A run that stopped before an artifact was written cannot supply
            # the view on either side. That is not a difference and not a match;
            # naming it keeps it from being read as either.
            unavailable += 1
            print(f"{name}: UNAVAILABLE in both runs: {left_error}")
            continue
        if left_error or right_error:
            failures += 1
            print(f"{name}: ERROR baseline={left_error} candidate={right_error}")
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
    for name, report in STAGE_REPORTED.get(args.stage, {}).items():
        print(f"{name}: REPORTED baseline={report(args.baseline)} candidate={report(args.candidate)}")
    comparable = len(views) - unavailable
    print(f"\n{comparable - failures}/{comparable} comparable views identical", end="")
    print(f", {unavailable} unavailable" if unavailable else "")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
