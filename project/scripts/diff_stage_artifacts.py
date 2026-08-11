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

Comparing two *backends* adds one thing to read carefully, and it is read here
rather than normalised. `argv` is backend-specific by construction - a native
run issues `sh -c "PATH=...; valkey-server <conf>"` over ssh where a Docker run
issues `docker exec <container> valkey-server <conf>` - so the command-log views
can never be equal across backends and will report DIFFERS on every native
candidate. **That is an expected runtime difference and not a defect, and it is
not a reason to drop argv from the views.** A command log exists to say exactly
what was executed; a view that collapsed argv would keep scoring green while the
wrong command ran, which is the failure the seeded-regression rule in CLAUDE.md
exists to prevent. Operator decision, 2026-08-11: keep the raw argv and carry
the distinction in how the result is read.

So read a cross-backend command-log diff by what is *around* argv. Measured
across two native exact-50 runs at roadmap item 1.5 rung 2: `argv` is the entire
difference in `fault_command_log` - 17 rows and nothing else - and 212 of 1592
rows in `management_command_log`, with `command_kind`, `operation_id`,
`target_logical_id`, `status`, `returncode` and `attempt_count` identical
throughout. Those are the fields that carry the claim; a delta in any of them is
a finding, and a delta confined to argv is the runtime showing through.
`project/docs/simulated_ladder_slice_map.md` §14.5 has the measurement.
"""

from __future__ import annotations

import argparse
import collections
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
    """An id with no known node becomes UNKNOWN rather than disappearing.

    Keys are renamed as well as values. `management_sequence.json` keys its
    per-primary `slot_counts` by node id, so a view that only rewrote values
    would report twenty-five lines of pure identity noise and hide the slot
    counts underneath it.
    """
    rename = lambda text: NODE_ID.sub(  # noqa: E731
        lambda match: names.get(match.group(0), "<node:UNKNOWN>"), text
    )
    if isinstance(value, dict):
        return {rename(key): rename_node_ids(item, names) for key, item in value.items()}
    if isinstance(value, list):
        return [rename_node_ids(item, names) for item in value]
    if isinstance(value, str):
        return rename(value)
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


# `management_matrix` measures far more than the earlier stages did, and names
# almost none of it in a way the shared IGNORED regex catches. Over the frozen
# exact-50 baseline its artifacts carry 479 `wall_ms`, 400 `*_wall_ms`, 150
# `wait_ms`, 400 `*_at_ms` and 3,206 `started/ended_at_unix_ms`. Widening
# IGNORED to `.*_ms` would take `cluster_node_timeout_ms` and its siblings with
# it, which the note on IGNORED says must stay compared, so the rule is
# stage-local: a measured `_ms` value is replaced, not dropped, so that the
# field's disappearance still shows.
CONFIGURED_MS = {"sample_interval_ms", "timeout_ms"}
MEASURED_MS = re.compile(r"^.*_ms$")
# A restart's whole point is that the pid changed, so which pid it is now is
# noise and whether there is one is evidence - the same choice `scrub` makes.
PID_FIELDS = {"pid", "process_pid_before", "process_pid_after"}
# The replica sync gate's evidence is `master_link_status: up`,
# `master_sync_in_progress: 0` and the caught-up verdict, all of which stay
# compared. The byte offsets themselves differ by tens of bytes per run.
REPL_OFFSET_FIELDS = {"primary_repl_offset", "replica_repl_offset"}
ORDERLESS_FIELDS: set[str] = set()
# How many probes a health gate needed depends on whether the first
# representative round came back clean; when it does not, the gate falls back to
# one diagnostic round over the whole fleet. That is a retry counter, and the
# two frozen baseline runs happening to agree on it (50 and 376) is not evidence
# that it is deterministic - a third run recorded 100 and 482. `cluster_form`
# already reports `runtime_all_node_light_probe` for the same reason instead of
# diffing it, so these are reported by `main` rather than compared. The gate's
# verdict, its cluster state, its known nodes and its slot count are all still
# compared in full.
PROBE_COUNT_FIELDS = {
    "retry_count",
    "full_probe_count",
    "representative_probe_count",
    "node_command_count",
}
# A health gate's *retry record* is non-deterministic in every part: how many
# rounds it took, what each round saw mid-restart, and whether it had to
# escalate from the representative sample to a diagnostic sweep. Its *verdict*
# is not, and that is what this stage owes: that every batch was gated, and that
# the gate ended with a clean cluster. So the fields below are compared and the
# retry record around them is replaced - drawn once, here, rather than field by
# field as each new run turns up another one that moves.
PROBE_VERDICT_FIELDS = {
    "status",
    "gate_kind",
    "batch_id",
    "cluster_state",
    "known_nodes",
    "slots_assigned",
    "command_ref",
}
# Matched anywhere in a string, not anchored: a reference is often carried as
# `management_command_log.jsonl#<command_id>`, and the artifact it names is
# evidence that must survive while the ordinal inside it does not.
COMMAND_ID = re.compile(r"[A-Za-z0-9_.]+(?:-[A-Za-z0-9_.]+)*-cmd-\d{4}")


def management_scrub(value: Any) -> Any:
    """`scrub`, plus the four replacements this stage's artifacts need."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in sorted(value.items()):
            if IGNORED.match(key):
                continue
            if MEASURED_MS.match(key) and key not in CONFIGURED_MS and isinstance(item, (int, float)):
                result[key] = "<MEASURED_MS>"
            elif key in PID_FIELDS and isinstance(item, int):
                result[key] = "<PID>"
            elif key in REPL_OFFSET_FIELDS and isinstance(item, int):
                result[key] = "<OFFSET>"
            elif key == "attempts" and isinstance(item, list):
                # The rounds a gate needed, and what each saw before the cluster
                # settled. A run that restarts a replica may observe
                # replica_count 24 once and 25 the next round; both are correct.
                result[key] = "<PROBE_ATTEMPTS>"
            elif key in PROBE_COUNT_FIELDS and isinstance(item, int):
                result[key] = "<PROBE_COUNT>"
            elif key == "sample_scope":
                # Which sample a gate settled on depends on whether the first
                # representative round was clean. Reported with the counts.
                result[key] = "<PROBE_SCOPE>"
            elif key == "probed_node_ids" and isinstance(item, list):
                # Which nodes a gate sampled follows from the scope above.
                result[key] = "<PROBE_NODES>"
            elif key in ORDERLESS_FIELDS and isinstance(item, list):
                result[key] = sorted(management_scrub(entry) for entry in item)
            elif key == "workload_impact" and isinstance(item, dict):
                result[key] = management_workload_impact(item)
            else:
                result[key] = management_scrub(item)
        return result
    if isinstance(value, list):
        return [management_scrub(item) for item in value]
    if isinstance(value, str):
        return ARTIFACTS_PATH.sub("<ARTIFACTS>/", GATE_RUN.sub("<GATE_RUN>", value))
    return value


def management_workload_impact(impact: dict[str, Any]) -> dict[str, Any]:
    """How many workload operations fitted beside a management operation, and
    how many of them failed, are real measurements of a real handoff - and they
    are not reproducible. The two frozen baseline runs recorded 164 against 244
    samples for `add_replica`, and 17 against 6 errors for
    `remove_primary_drained_or_safe_replaced`. Nothing can equate those without
    equating a regression too, so both counts are replaced and `main` reports
    them instead. `errors_observed_during_operation` is the verdict and stays:
    it is true for the same three operations in both runs.
    """
    return {
        key: ("<MEASURED_COUNT>" if key in {"sample_count", "error_count"} else management_scrub(item))
        for key, item in sorted(impact.items())
    }


def load_jsonl(path: Path) -> list[Any]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def command_kind_by_id(root: Path) -> dict[str, str]:
    """A command id is its position in the log, which is not what a reference
    to it means. Every added command shifts every later id, so comparing the
    ordinals makes an unrelated view differ for a reason that has nothing to do
    with it - which is what a pid, a node id and a gate run id are already
    renamed to avoid. What a `command_ref` carries is *which command* a probe or
    a handoff points at, so it is resolved to that command's kind."""
    return {
        str(row["command_id"]): str(row.get("command_kind", "UNKNOWN"))
        for row in load_jsonl(root / "management_command_log.jsonl")
        if row.get("command_id")
    }


def rename_command_ids(value: Any, kinds: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: rename_command_ids(item, kinds) for key, item in value.items()}
    if isinstance(value, list):
        return [rename_command_ids(item, kinds) for item in value]
    if isinstance(value, str):
        # An unresolvable reference becomes UNKNOWN rather than disappearing.
        return COMMAND_ID.sub(
            lambda match: f"<cmd:{kinds.get(match.group(0), 'UNKNOWN')}>", value
        )
    return value


def management_view(root: Path, document: Any) -> Any:
    """Every `management_matrix` view is normalised the same way.

    Node ids and nodehost addresses both appear inside this stage's evidence -
    a `CLUSTER MEET` and a `MIGRATE` name a peer by address in their argv - and
    both are named rather than dropped, for the reasons `node_id_names` and
    `nodehost_id_by_address` give.
    """
    value = rename_node_ids(management_scrub(document), node_id_names(root))
    value = rename_command_ids(value, command_kind_by_id(root))
    return rename_addresses(value, nodehost_id_by_address(root))


def rename_addresses(value: Any, by_address: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: rename_addresses(item, by_address) for key, item in value.items()}
    if isinstance(value, list):
        return [rename_addresses(item, by_address) for item in value]
    if isinstance(value, str):
        for address, nodehost_id in by_address.items():
            value = value.replace(address, f"<nodehost:{nodehost_id}>")
        return value
    return value


def management_owned(rows: list[Any]) -> list[Any]:
    """`full_flow_topology_snapshots.jsonl` and `workload_windows.json` are
    shared with `baseline_workload` and `fault_matrix`. Only the rows whose
    `operation_id` names a management operation belong to this stage: 44 of 46
    snapshots and 66 of 82 windows at exact-50."""
    return [row for row in rows if "-management-" in str(row.get("operation_id", ""))]


def management_topology_snapshots(root: Path) -> Any:
    return management_view(
        root, management_owned(load_jsonl(root / "full_flow_topology_snapshots.jsonl"))
    )


def management_workload_windows(root: Path) -> Any:
    """Verdicts only. A window also carries `achieved_qps`, `throughput_ratio`
    and a latency histogram, which are load measurements and differ on every
    run; what this stage owns is that each operation opened the windows it
    should have and that each one passed."""
    document = json.loads((root / "workload_windows.json").read_text(encoding="utf-8"))
    rows = [
        {key: window.get(key) for key in ("operation_id", "window_name", "status", "coverage_id", "workload_mode")}
        for window in management_owned(document["windows"])
    ]
    return scrub(sorted(rows, key=lambda row: (str(row["operation_id"]), str(row["window_name"]))))


def management_stability_observation(root: Path) -> Any:
    """The bounded-stability lane's verdicts, not its samples.

    `scalable_stability_observation.json` records every node's `CLUSTER INFO`,
    down to `cluster_stats_messages_ping_sent` - 40,168 diff lines between two
    runs of the same code. Reduced to the statuses and the structural scalars
    it still fails if a lane's verdict flips, a check disappears, or the light
    validation stops seeing every node in its right role.
    """
    document = json.loads(
        (root / "scalable_stability_observation.json").read_text(encoding="utf-8")
    )
    full = document["full_validation"]
    return scrub(
        {
            "keys": sorted(document),
            "status": document.get("status"),
            "artifact_type": document.get("artifact_type"),
            "capability_id": document.get("capability_id"),
            "check_status": {
                key: item["status"]
                for key, item in document.items()
                if isinstance(item, dict) and "status" in item
            },
            "full_validation_keys": sorted(full),
            "light_validation": {
                key: item
                for key, item in full["light_validation"].items()
                if not isinstance(item, (list, dict))
            },
        }
    )


def management_probe_counts(root: Path) -> str:
    """Reported, not diffed - see `PROBE_COUNT_FIELDS`."""
    plan = json.loads((root / "rolling_restart_plan.json").read_text(encoding="utf-8"))
    return " ".join(
        f"{operation['operation_name'].replace('rolling_restart_', '')}="
        f"rep{operation['health_probe_summary']['representative_probe_count']}"
        f"/full{operation['health_probe_summary']['full_probe_count']}"
        f"/retry{operation['health_probe_summary']['retry_count']}"
        f"/cmds{operation['health_probe_summary']['node_command_count']}"
        for operation in plan["operations"]
    )


def management_workload_counters(root: Path) -> str:
    """Reported, not diffed - see `management_workload_impact`."""
    document = json.loads((root / "management_sequence.json").read_text(encoding="utf-8"))
    return " ".join(
        f"{row['operation_name']}={row.get('workload_impact', {}).get('sample_count')}"
        f"/{row.get('workload_impact', {}).get('error_count')}"
        for row in document["result"]["operations"]
    )


# A pid inside a rendered command, rather than as a field. `scrub` replaces a
# `pid` key; the fault lane's owned actions carry the number inside the string
# ("docker exec host-a kill -STOP 15899", 15899 against 17208 between the two
# frozen baseline runs). The signal itself stays compared, because the image
# ships no kill binary and sending the wrong one is exactly the regression this
# view exists to catch.
KILL_PID = re.compile(r"(kill -[A-Z]+ )\d+")
# Live server state, in three fields that hold a whole `CLUSTER INFO`. Not just
# the counters move between two runs of the same code - the *key set* does,
# because `cluster_stats_messages_update_received` and its siblings appear only
# once such a message has been seen. What these fields carry as evidence is
# that a real CLUSTER INFO was observed and what `cluster_state` said, which is
# also all the observation validator reads, so that is what survives.
CLUSTER_INFO_FIELDS = {
    "observed_cluster_info",
    "majority_cluster_info",
    "isolated_cluster_info",
}
# Why a node could not be reached. Measured across six runs, the flavour is a
# race and not a fact: at 30 and 50 nodes `network_partition` records a socket
# timeout while the two split-brain scenarios record an EOF, and at 200 nodes
# `network_partition` records the EOF instead. The contract is that an
# unreachable isolated side states a reason at all - `85d5096a` made the silent
# absence a failure - so presence is compared and the flavour is reported.
UNREACHABLE_REASON_FIELDS = {"isolated_unreachable_reason", "error", "client_error"}
# The sandbox proxy binds whatever ephemeral port the OS hands it (49612
# against 51183 between the baselines). `target_port` is the node's planned
# client port and stays compared.
EPHEMERAL_PORT_FIELDS = {"listen_port"}
# Two row kinds whose `stdout_tail` is a re-serialisation of evidence this
# stage already compares in full elsewhere: an `owned_fault_probe` row carries
# `json.dumps(details)` and `fault_sequence` compares `details`; the actuator
# row carries the actuator record and `failover_observation:verdicts` compares
# it. Both are cut to the last 2000 characters, so the truncation window itself
# moves when the content grows - the baseline's partition row begins mid-line.
# Every other row keeps its stdout compared, which is where Slice 3's lesson
# actually applies: a `CLUSTER REPLICATE` reply of "OK" against an error is how
# the `docker exec` fallback was caught.
SERIALISED_STDOUT_KINDS = {"owned_fault_probe", "actuator_kill_primary"}
FAULT_COMMAND_ID = re.compile(
    r"local_full_flow-fault-[A-Za-z0-9_.-]+?-(?:cmd-\d{4}|actuator-[a-z-]+)"
)


def cluster_info_observation(text: str) -> dict[str, Any]:
    """A `CLUSTER INFO` text reduced to what it is evidence of."""
    if not text:
        return {"observed": False, "cluster_state": None, "truncated": False}
    rows = dict(
        line.split(":", 1)
        for line in text.replace("\r", "").strip().splitlines()
        if ":" in line
    )
    state = rows.get("cluster_state")
    # These fields are bounded at 1000 characters and `observed_cluster_info`
    # keeps the tail, so a longer INFO would drop `cluster_state` off the
    # front. Measured lengths run 794-999 at 30, 50 and 200 nodes, which is
    # close enough that the bound must show rather than read as an absence.
    return {
        "observed": True,
        "cluster_state": state,
        "truncated": state is None or "<truncated>" in text,
    }


def fault_scrub(value: Any) -> Any:
    """The five replacements this stage's artifacts need, over `management_scrub`.

    Layered rather than merged: everything `management_matrix` measured about
    `_ms` values, pids and node ids is true here too, and restating it would
    let the two drift.
    """
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in sorted(value.items()):
            if key in CLUSTER_INFO_FIELDS and isinstance(item, str):
                result[key] = cluster_info_observation(item)
            elif key in UNREACHABLE_REASON_FIELDS and isinstance(item, str):
                result[key] = "<UNREACHABLE>" if item else ""
            elif key in EPHEMERAL_PORT_FIELDS:
                result[key] = "<PORT>"
            else:
                result[key] = fault_scrub(item)
        return result
    if isinstance(value, list):
        return [fault_scrub(item) for item in value]
    if isinstance(value, str):
        return KILL_PID.sub(r"\1<PID>", value)
    return value


def fault_command_kind_by_id(root: Path) -> dict[str, str]:
    """As `command_kind_by_id`, over this stage's own log.

    `fault_sequence.json` lists each scenario's command ids as its evidence,
    and an id is its position in the log, so a row added anywhere shifts every
    later reference.
    """
    return {
        str(row["command_id"]): str(row.get("command_kind", "UNKNOWN"))
        for row in load_jsonl(root / "fault_command_log.jsonl")
        if row.get("command_id")
    }


def rename_fault_command_ids(value: Any, kinds: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: rename_fault_command_ids(item, kinds) for key, item in value.items()}
    if isinstance(value, list):
        return [rename_fault_command_ids(item, kinds) for item in value]
    if isinstance(value, str):
        return FAULT_COMMAND_ID.sub(
            lambda match: f"<cmd:{kinds.get(match.group(0), 'UNKNOWN')}>", value
        )
    return value


def fault_view(root: Path, document: Any) -> Any:
    """Every `fault_matrix` view is normalised the same way."""
    value = fault_scrub(management_scrub(document))
    value = rename_node_ids(value, node_id_names(root))
    value = rename_fault_command_ids(value, fault_command_kind_by_id(root))
    return rename_addresses(value, nodehost_id_by_address(root))


def fault_owned(rows: list[Any]) -> list[Any]:
    """`workload_windows.json` and `full_flow_topology_snapshots.jsonl` are
    shared with `baseline_workload` and `management_matrix`. 15 of 82 windows
    and 2 of 46 snapshot rows are this stage's at exact-50."""
    return [row for row in rows if "-fault-" in str(row.get("operation_id", ""))]


def fault_sequence(root: Path) -> Any:
    return fault_view(root, load(root / "fault_sequence.json"))


def fault_command_log(root: Path) -> Any:
    rows = [
        {
            **row,
            "stdout_tail": (
                "<OBSERVATION_JSON>"
                if row.get("command_kind") in SERIALISED_STDOUT_KINDS
                else row.get("stdout_tail")
            ),
        }
        for row in load_jsonl(root / "fault_command_log.jsonl")
    ]
    return fault_view(root, rows)


def _shard_of(logical_id: str) -> str:
    return str(logical_id).split("-replica")[0].replace("-primary", "")


def fault_topology_snapshots(root: Path) -> Any:
    """The stage's two snapshots as structure, not as a role placement.

    Which *named* node holds a shard's primary role after this stage is a live
    outcome, not a property of the stage. `az_stop` stops an AZ's nodehosts, every
    primary hosted there is promoted away from its original node, and whether it is
    still promoted when the snapshot is taken depends on `cluster-node-timeout`,
    gossip and whether the nodehost returned first. Measured: the `fault_after`
    snapshot left eight shards role-swapped in both frozen baselines and in two
    runs on 2026-08-09, and seven in a third - `shard-0012` recovered its original
    placement - with every invariant below identical and the run PASS either way.

    Six runs agreeing did not make the field deterministic, which is the trap
    CLAUDE.md names. So the boundary is drawn once by what the field is: the
    invariants are compared and the placement is reported by
    `fault_topology_placement` instead. Comparing it literally would fail a diff
    for a cluster that recovered correctly, and a view that goes red on healthy
    variance stops being able to show a regression.
    """

    snapshots = fault_owned(load_jsonl(root / "full_flow_topology_snapshots.jsonl"))
    rows = []
    for snapshot in snapshots:
        nodes = [node for node in snapshot.get("nodes", []) if isinstance(node, dict) and node.get("role")]
        primaries = [node for node in nodes if node["role"] == "primary"]
        shards = collections.Counter(_shard_of(node["logical_id"]) for node in primaries)
        rows.append(
            {
                "snapshot_id": snapshot.get("snapshot_id"),
                "node_count": len(nodes),
                "primary_count": len(primaries),
                "replica_count": sum(1 for node in nodes if node["role"] == "replica"),
                # The invariant a healthy cluster holds however the roles landed.
                "shards_with_one_primary": sum(1 for count in shards.values() if count == 1),
                "shards_not_singly_owned": sorted(
                    shard for shard, count in shards.items() if count != 1
                ),
                "link_states": sorted({str(node.get("link_state")) for node in nodes}),
                "slots": snapshot.get("slots"),
                "cluster_state": snapshot.get("cluster_state"),
            }
        )
    return fault_view(root, sorted(rows, key=lambda row: str(row["snapshot_id"])))


def fault_topology_placement(root: Path) -> str:
    """Reported, not diffed - see `fault_topology_snapshots`.

    A regression that left the cluster genuinely mis-placed still has to be
    visible, so the count of role-swapped shards and their names are printed.
    """

    snapshots = fault_owned(load_jsonl(root / "full_flow_topology_snapshots.jsonl"))
    parts = []
    for snapshot in sorted(snapshots, key=lambda row: str(row.get("snapshot_id"))):
        swapped = sorted(
            _shard_of(node["logical_id"])
            for node in snapshot.get("nodes", [])
            if isinstance(node, dict)
            and node.get("role") == "replica"
            and str(node.get("logical_id", "")).endswith("-primary")
        )
        label = str(snapshot.get("snapshot_id", "")).rsplit("-", 1)[-1]
        parts.append(f"{label}: {len(swapped)} role-swapped {swapped}")
    return " | ".join(parts)


def fault_workload_windows(root: Path) -> Any:
    """Verdicts only, for the reason `management_workload_windows` gives."""
    document = json.loads((root / "workload_windows.json").read_text(encoding="utf-8"))
    rows = [
        {key: window.get(key) for key in ("operation_id", "window_name", "status", "coverage_id", "workload_mode")}
        for window in fault_owned(document["windows"])
    ]
    return scrub(sorted(rows, key=lambda row: (str(row["operation_id"]), str(row["window_name"]))))


def failover_observation(root: Path) -> Any:
    """The §9 verdicts of the primary-kill lane, not its samples.

    `scalable_primary_failover_observation.json` carries 453 Sentinel samples
    at 100ms, 95 affected-shard rounds, 102 connection events and a whole
    cluster validation - all live measurement, all different on every run.
    What the stage owes is that the actuator recorded the six things §9.1 names,
    that the control plane ran at §9.2's period, that convergence used §9.3's
    two-round rule, and that §9.4's two success conditions were judged apart.
    """
    document = json.loads(
        (root / "scalable_primary_failover_observation.json").read_text(encoding="utf-8")
    )
    actuator = document["actuator"]
    probe = document["sentinel_fault_probe"]
    convergence = document["affected_shard_convergence"]
    return rename_node_ids(
        scrub(
            {
                "keys": sorted(document),
                "status": document.get("status"),
                "artifact_type": document.get("artifact_type"),
                "target": document.get("target"),
                "failover_success": document.get("failover_success"),
                # §9.1's six fields: the three that describe the action are
                # compared, and the three timestamps are checked for presence,
                # since when it happened is a measurement.
                "actuator": {key: actuator.get(key) for key in ("target", "action", "result")},
                "actuator_stamps": sorted(
                    key for key, item in actuator.items() if isinstance(item, dict)
                ),
                "sentinel_prepare": {
                    key: item
                    for key, item in document["sentinel_prepare"].items()
                    if key != "connection_events"
                },
                "sentinel_fault_probe": {
                    key: item
                    for key, item in probe.items()
                    if key not in {"samples", "connection_events", "rto_ms", "stable_confirmed_at_monotonic"}
                },
                "sentinel_restore_probe": {
                    key: item
                    for key, item in document["sentinel_restore_probe"].items()
                    if key != "connection_events"
                },
                "convergence": {
                    key: item
                    for key, item in convergence.items()
                    if key not in {"rounds", "full_validation"}
                },
                "redundancy_recovery": document["redundancy_recovery"],
                "recovery_validation_status": document["recovery_validation"]["status"],
                "recovery_light_validation": {
                    key: item
                    for key, item in document["recovery_validation"]["light_validation"].items()
                    if not isinstance(item, (list, dict))
                },
                "load_preflight": document["load_preflight"],
                "load_result": document["load_result"],
            }
        ),
        node_id_names(root),
    )


def failover_recovery_numbers(root: Path) -> str:
    """Reported, not diffed. The RTO is the measurement the lane exists to make
    and it is different every run - 45.5s to 49.0s across six runs at three
    scales - so a candidate that made recovery dramatically worse must still be
    visible, just not as a diff result."""
    document = json.loads(
        (root / "scalable_primary_failover_observation.json").read_text(encoding="utf-8")
    )
    sequence = json.loads((root / "fault_sequence.json").read_text(encoding="utf-8"))
    details = sequence.get("failover_details", {})
    probe = document["sentinel_fault_probe"]
    return (
        f"rto={probe['rto_ms']}ms samples={len(probe['samples'])}"
        f" rounds={len(document['affected_shard_convergence']['rounds'])}"
        f" promotion={details.get('promotion_latency_ms')}ms"
        f" recovery={details.get('cluster_recovery_latency_ms')}ms"
    )


def fault_unreachable_reasons(root: Path) -> str:
    """Reported, not diffed - see `UNREACHABLE_REASON_FIELDS`."""
    sequence = json.loads((root / "fault_sequence.json").read_text(encoding="utf-8"))
    return " ".join(
        f"{row['id']}={row['details'].get('isolated_unreachable_reason') or '<answered>'!r}"
        for row in sequence["fault_results"]
        if "isolated_unreachable_reason" in row["details"]
    )


def fault_stage_shape(root: Path) -> str:
    """Reported beside the diff because it is the check exact-200 gets instead
    of one: the stage's shape is the same 9/12/15 at every scale."""
    sequence = json.loads((root / "fault_sequence.json").read_text(encoding="utf-8"))
    windows = json.loads((root / "workload_windows.json").read_text(encoding="utf-8"))
    return (
        f"scenarios={len(sequence['fault_results'])}"
        f" command_rows={len(load_jsonl(root / 'fault_command_log.jsonl'))}"
        f" windows={len(fault_owned(windows['windows']))}"
        f" status={sequence['status']}"
    )



# --- cleanup: roadmap item 0.5's own stage ------------------------------------
# `cleanup` is one of the twelve `lifecycle_timeline` steps, so this is a stage
# entry like the four before it. Item 0.5 moved the report's assembly above the
# seam and the acting below it; these are the artifacts that proves it on.


def cleanup_report(root: Path) -> Any:
    """The cleanup report, with the per-run identities its rows carry reduced.

    A container id, a network id and a pid are all per-run, and so is the exact
    set of pids a nodehost was running when it was released - but *how many*
    there were, and whether the row found any, is the evidence. So they become
    counts rather than exclusions, the way `scrub` already replaces `pid`.

    Both copies are read: `cleanup_report.json` and its
    `cleanup_report_<scenario>.json` twin must stay byte-identical, and a diff
    that read only one would not notice if they stopped being.
    """
    rows = []
    for path in sorted(root.glob("cleanup_report*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        rows.append({"artifact": path.name, "report": _cleanup_scrub(report)})
    return rows


_CLEANUP_PID_LISTS = (
    "live_pids",
    "zombie_pids",
    "unreadable_pids",
    "alive_pids",
)


def _cleanup_scrub(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        out = {}
        for name, item in sorted(value.items()):
            if IGNORED.match(name):
                continue
            if name in _CLEANUP_PID_LISTS and isinstance(item, list):
                out[f"{name}:count"] = len(item)
                continue
            if name in {"stdout", "stderr", "stdout_tail", "stderr_tail"}:
                # A residual scan prints the pids it found, so its text is the
                # same per-run identity as the list beside it.
                out[f"{name}:empty"] = not str(item).strip()
                continue
            if name == "id" and isinstance(item, str) and _CLEANUP_DOCKER_ID.fullmatch(item):
                out[name] = "<RESOURCE_ID>"
                continue
            out[name] = _cleanup_scrub(item, name)
        return out
    if isinstance(value, list):
        return [_cleanup_scrub(item, key) for item in value]
    return scrub(value)


_CLEANUP_DOCKER_ID = re.compile(r"[0-9a-f]{12,64}")


def load_lane_evidence(root: Path) -> str:
    """What the Load Lane's evidence upload actually brought back.

    Reported rather than diffed: memtier's latency numbers move between runs, so
    what this owns is that each file arrived, is non-empty, and that the two
    JSON results parse. Comparing the numbers would be comparing the cluster's
    behaviour, which is not what an evidence-upload boundary is responsible for.
    """
    lane = root / "load_lane"
    if not lane.is_dir():
        return "load_lane/ ABSENT"
    names: list[str] = []
    empty: list[str] = []
    invalid: list[str] = []
    for path in sorted(lane.iterdir()):
        if not path.is_file():
            continue
        names.append(path.name)
        if path.stat().st_size == 0:
            empty.append(path.name)
        if path.suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                invalid.append(path.name)
    return (
        f"{len(names)} files"
        f" | empty: {', '.join(empty) or 'none'}"
        f" | invalid json: {', '.join(invalid) or 'none'}"
        f" | {' '.join(names)}"
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
    "management_matrix": {
        "lifecycle_timeline:management_matrix": lambda root: lifecycle_step(
            root, "management_matrix"
        ),
        "rolling_restart_plan": lambda root: management_view(
            root, json.loads((root / "rolling_restart_plan.json").read_text(encoding="utf-8"))
        ),
        "rolling_restart_results": lambda root: management_view(
            root, load_jsonl(root / "rolling_restart_results.jsonl")
        ),
        "management_sequence": lambda root: management_view(
            root, json.loads((root / "management_sequence.json").read_text(encoding="utf-8"))
        ),
        "management_command_log": lambda root: management_view(
            root, load_jsonl(root / "management_command_log.jsonl")
        ),
        "topology_snapshots:management": management_topology_snapshots,
        "workload_windows:management": management_workload_windows,
        "stability_observation:verdicts": management_stability_observation,
    },
    "fault_matrix": {
        "lifecycle_timeline:fault_matrix": lambda root: lifecycle_step(root, "fault_matrix"),
        "fault_sequence": fault_sequence,
        "fault_command_log": fault_command_log,
        "failover_observation:verdicts": failover_observation,
        "topology_snapshots:fault": fault_topology_snapshots,
        "workload_windows:fault": fault_workload_windows,
    },
    "cleanup": {
        "lifecycle_timeline:cleanup": lambda root: lifecycle_step(root, "cleanup"),
        "cleanup_report": cleanup_report,
    },
}

# A stage may have evidence that cannot be diffed but must not go unreported.
STAGE_REPORTED: dict[str, dict[str, Callable[[Path], str]]] = {
    "cluster_form": {"runtime_all_node_light_probe": light_probe_retries},
    "management_matrix": {
        "workload_impact_samples/errors": management_workload_counters,
        "rolling_restart_probe_counts": management_probe_counts,
        # The Load Lane runs inside this stage's bounded stability window, so
        # its uploaded evidence is reported here. Reported, not diffed: see
        # `load_lane_evidence`.
        "load_lane_evidence": load_lane_evidence,
    },
    "fault_matrix": {
        "stage_shape": fault_stage_shape,
        "topology_placement": fault_topology_placement,
        "failover_recovery": failover_recovery_numbers,
        "isolated_unreachable_reasons": fault_unreachable_reasons,
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
