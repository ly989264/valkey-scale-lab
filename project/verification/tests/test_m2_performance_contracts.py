from __future__ import annotations

import gzip
import importlib.util
import hashlib
import json
import math
import tarfile
from copy import deepcopy
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "m2_performance_gate.py"
SPEC = importlib.util.spec_from_file_location("m2_performance_gate", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
M2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M2)
DISCOVERY_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "m2_candidate_discovery.py"
DISCOVERY_SPEC = importlib.util.spec_from_file_location(
    "m2_candidate_discovery", DISCOVERY_SCRIPT_PATH
)
assert DISCOVERY_SPEC is not None and DISCOVERY_SPEC.loader is not None
DISCOVERY = importlib.util.module_from_spec(DISCOVERY_SPEC)
DISCOVERY_SPEC.loader.exec_module(DISCOVERY)
from valkey_scale_lab.runtime.setup_timeline import (  # noqa: E402
    REQUIRED_SETUP_SEGMENTS,
    build_setup_timeline_artifact,
)

SHA = "a" * 64
CONTROL_DIGESTS = {
    "valkey_binary": SHA,
    "product": SHA,
    "configuration_except_treatment": SHA,
    "topology": SHA,
    "placement": SHA,
    "host": SHA,
    "workload": SHA,
    "resource_preflight": SHA,
}


def _protocol() -> dict[str, object]:
    return {
        "percentile_method": "nearest-rank",
        "paired": True,
        "arm_order": "alternating-AB-BA",
        "fresh_cluster_per_arm": True,
        "cleanup_between_arms": True,
        "fixture_admission_allowed": False,
        "historical_admission_allowed": False,
        "downscale_allowed": False,
        "takeover_allowed": False,
        "formation_pairs_per_scale": 7,
        "failover_pairs_per_cell": 10,
        "stable_window_seconds": 1,
        "stable_window_min_pairs": 10,
        "affected_shard_max_interval_ms": 100,
        "soak_seconds": 1800,
    }


def _trial(
    invocation: str,
    trial_id: str,
    pair_id: str,
    cell_id: str,
    arm: str,
    order: int,
    scale: int,
    treatment: dict[str, object],
    duration: float,
) -> dict[str, object]:
    run_id = f"{invocation}-{trial_id}"
    root = f"trials/{trial_id}"
    markers = {
        "last_process_ping": 0.0,
        "first_membership_command": duration * 0.1,
        "all_primaries_known": duration * 0.2,
        "all_slots_assigned": duration * 0.4,
        "all_replicas_attached": duration * 0.6,
        "all_replicas_synchronized": duration * 0.7,
        "every_node_clean": duration * 0.9,
        "data_path_probe": duration,
    }
    cleanup_ref = f"{root}/cleanup_report.json"
    provenance_ref = f"{root}/evidence_provenance.json"
    source_refs = [
        {"category": category, "path": f"{root}/{name}", "sha256": SHA}
        for category, name in (
            ("attempt", "attempt.json"),
            ("state", "state.json"),
            ("cleanup", "cleanup_report.json"),
            ("provenance", "evidence_provenance.json"),
            ("timeline", "timeline.json"),
            ("command_log", "command_log.jsonl"),
            ("resource", "resource_window.json"),
            ("workload", "workload.jsonl"),
            ("topology", "topology.json"),
        )
    ]
    return {
        "trial_id": trial_id,
        "pair_id": pair_id,
        "cell_id": cell_id,
        "arm": arm,
        "order": order,
        "scale": scale,
        "run_id": run_id,
        "ownership_id": run_id,
        "evidence_root": root,
        "real_valkey": True,
        "fresh_cluster": True,
        "treatment": treatment,
        "timing_source": "monotonic-observed",
        "unexplained_seconds": 0.0,
        "monotonic_markers": markers,
        "derived_intervals": {"formation_seconds": duration},
        "correctness": {
            "exact_membership": True,
            "observed_nodes": scale,
            "slots_covered": 16384,
            "replicas_synchronized": True,
            "clean_topology": True,
            "data_path": True,
            "split_brain": False,
            "unexpected_pfail": 0,
            "unexpected_fail": 0,
            "unexpected_promotions": 0,
            "slot_loss": False,
        },
        "resource_window": {
            "duration_seconds": 120.0,
            "peak_rss_bytes": 100.0,
            "cpu_time_seconds": 100.0,
            "fd_count": 100.0,
            "connection_count": 100.0,
            "cluster_bus_bytes": 100.0,
            "cluster_link_errors": 0,
            "buffer_overflows": 0,
        },
        "workload": {
            "duration_seconds": 120.0,
            "set_throughput_ops_per_second": 100.0,
            "p99_latency_ms": 1.0,
            "errors": 0,
            "persistent_cluster_client": True,
            "per_operation_process_spawn": False,
            "affected_shard_max_interval_ms": 100.0,
            "stable_shards": [],
        },
        "fault": None,
        "cleanup": {
            "status": "PASS",
            "resources_remaining": [],
            "cleanup_errors": [],
            "evidence_ref": cleanup_ref,
        },
        "provenance": {
            "status": "PASS",
            "current_invocation": True,
            "invocation_run_id": invocation,
            "product_owned": True,
            "fixture": False,
            "historical": False,
            "valkey_versions": ["9.1.0"],
            "definition_digest": SHA,
            "valkey_binary_digest": SHA,
            "product_digest": SHA,
            "configuration_digest": SHA,
            "environment_digest": SHA,
            "topology_digest": SHA,
            "placement_digest": SHA,
            "workload_digest": SHA,
            "command_digest": SHA,
            "capture_digest": SHA,
            "resource_preflight_digest": SHA,
            "evidence_ref": provenance_ref,
        },
        "source_sha256s": source_refs,
        "control_digests": dict(CONTROL_DIGESTS),
    }


def _formation_report() -> dict[str, object]:
    invocation = "m2-contract"
    baseline = {
        "kind": "cluster_create_strategy",
        "value": "valkey_cli_cluster_create_primaries",
    }
    candidates = [
        {
            "kind": "cluster_create_strategy",
            "value": "manual_tree_meet_parallel_slots",
        },
        *[
            {
                "kind": "cluster_create_strategy",
                "value": "tree_meet_addslotsrange",
                "bounded_parallelism": parallelism,
            }
            for parallelism in (4, 8, 16)
        ],
    ]
    selected = candidates[2]
    trials: list[dict[str, object]] = []
    pairs: list[dict[str, object]] = []
    cells: list[dict[str, object]] = []
    source_refs: list[dict[str, object]] = []
    ordinal = 0

    def add_cell(
        cell_id: str,
        campaign_step: str,
        scale: int,
        candidate: dict[str, object],
        count: int,
        candidate_duration: float,
        status: str = "PASS",
    ) -> None:
        nonlocal ordinal
        cells.append(
            {
                "cell_id": cell_id,
                "campaign_step": campaign_step,
                "scale": scale,
                "failure_rate": "none",
                "required_pairs": count,
                "candidate": candidate,
                "status": status,
            }
        )
        for sequence in range(1, count + 1):
            pair_id = f"{cell_id}-p{sequence:02d}"
            order_name = "AB" if sequence % 2 else "BA"
            baseline_order, candidate_order = ((1, 2) if order_name == "AB" else (2, 1))
            ordinal += 1
            baseline_trial = _trial(
                invocation,
                f"t{ordinal:03d}-a",
                pair_id,
                cell_id,
                "baseline",
                baseline_order,
                scale,
                baseline,
                100.0,
            )
            ordinal += 1
            candidate_trial = _trial(
                invocation,
                f"t{ordinal:03d}-b",
                pair_id,
                cell_id,
                "candidate",
                candidate_order,
                scale,
                candidate,
                candidate_duration,
            )
            trials.extend([baseline_trial, candidate_trial])
            source_refs.extend(baseline_trial["source_sha256s"])
            source_refs.extend(candidate_trial["source_sha256s"])
            pairs.append(
                {
                    "pair_id": pair_id,
                    "cell_id": cell_id,
                    "sequence": sequence,
                    "order": order_name,
                    "baseline_trial_id": baseline_trial["trial_id"],
                    "candidate_trial_id": candidate_trial["trial_id"],
                    "equal_observation_seconds": 120.0,
                    "control_digests": dict(CONTROL_DIGESTS),
                }
            )

    for index, candidate in enumerate(candidates):
        add_cell(
            f"discovery-{index}",
            "discovery",
            50,
            candidate,
            1,
            70.0 if candidate == selected else 110.0,
            "PASS" if candidate == selected else "FAIL",
        )
    for scale in (50, 100, 200):
        add_cell(
            f"promotion-{scale}",
            "promotion",
            scale,
            selected,
            7,
            60.0 if scale == 50 else 50.0,
        )

    report: dict[str, object] = {
        "schema_version": "m2-performance-report-v1",
        "artifact_type": "m2_performance_report",
        "campaign_id": invocation,
        "invocation_run_id": invocation,
        "experiment_kind": "formation",
        "created_at": "2026-07-19T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": "0.0.0"},
        "status": "PASS",
        "real_valkey": True,
        "execution_mode": "valkey-real",
        "baseline": baseline,
        "candidates": candidates,
        "selected_candidate": selected,
        "current_defaults": {
            "cluster_create_strategy": selected["value"],
            "cluster_node_timeout_ms": 30000,
        },
        "protocol": _protocol(),
        "started_trial_ids": [trial["trial_id"] for trial in trials],
        "trials": trials,
        "pairs": pairs,
        "cells": cells,
        "criterion_results": [
            {"criterion_id": criterion_id, "status": "PASS", "errors": []}
            for criterion_id in sorted(M2.CRITERIA_BY_KIND["formation"])
        ],
        "invalid_samples": [],
        "source_refs": source_refs,
        "errors": [],
        "report_digest": "",
    }
    report["report_digest"] = M2.report_digest(report)
    return report


def _formation_discovery_campaign() -> dict[str, object]:
    report = _formation_report()
    discovery_cells = [
        deepcopy(cell)
        for cell in report["cells"]
        if cell["campaign_step"] == "discovery"
    ]
    cell_ids = {cell["cell_id"] for cell in discovery_cells}
    trials = [
        deepcopy(trial)
        for trial in report["trials"]
        if trial["cell_id"] in cell_ids
    ]
    trial_ids = {trial["trial_id"] for trial in trials}
    pairs = [
        deepcopy(pair)
        for pair in report["pairs"]
        if pair["cell_id"] in cell_ids
    ]
    source_refs = [
        deepcopy(ref)
        for trial in trials
        for ref in trial["source_sha256s"]
    ]
    return {
        "campaign_id": report["campaign_id"],
        "invocation_run_id": report["invocation_run_id"],
        "experiment_kind": "formation",
        "status": "PASS",
        "real_valkey": True,
        "execution_mode": "valkey-real",
        "baseline": deepcopy(report["baseline"]),
        "candidates": deepcopy(report["candidates"]),
        "current_defaults": deepcopy(report["current_defaults"]),
        "protocol": deepcopy(report["protocol"]),
        "started_trial_ids": [
            trial_id
            for trial_id in report["started_trial_ids"]
            if trial_id in trial_ids
        ],
        "trials": trials,
        "pairs": pairs,
        "cells": discovery_cells,
        "invalid_samples": [],
        "source_refs": source_refs,
        "errors": [],
    }


def _intern_resource_directional_links(resource: dict[str, object]) -> None:
    entries: dict[str, dict[str, object]] = {}
    for sample in resource["samples"]:
        for nodehost in sample["nodehosts"]:
            for process in nodehost["processes"]:
                links = process.pop("directional_cluster_links")
                digest = M2._canonical_digest(links)
                entries.setdefault(
                    digest,
                    {
                        "sha256": digest,
                        "directional_cluster_links": links,
                    },
                )
                process["directional_cluster_links_sha256"] = digest
    resource["directional_cluster_links_dictionary"] = [
        entries[digest]
        for digest in sorted(entries)
    ]


def _expand_resource_directional_links(resource: dict[str, object]) -> None:
    entries = {
        entry["sha256"]: entry["directional_cluster_links"]
        for entry in resource.pop("directional_cluster_links_dictionary")
    }
    for sample in resource["samples"]:
        for nodehost in sample["nodehosts"]:
            for process in nodehost["processes"]:
                digest = process.pop("directional_cluster_links_sha256")
                process["directional_cluster_links"] = deepcopy(entries[digest])


def _write_valid_trial_sources(
    report: dict[str, object],
    trial: dict[str, object],
    artifacts_dir: Path,
) -> dict[str, Path]:
    invocation_trial_ids = {str(row["trial_id"]) for row in report["trials"]}
    report["pairs"] = [
        pair
        for pair in report["pairs"]
        if pair["baseline_trial_id"] in invocation_trial_ids
        and pair["candidate_trial_id"] in invocation_trial_ids
    ]
    scale = int(trial["scale"])
    duration = float(trial["derived_intervals"]["formation_seconds"])
    segment_rows: list[dict[str, object]] = []
    required_segment_names = [
        name
        for name in REQUIRED_SETUP_SEGMENTS
        if name != "scale_ladder_artifact_write"
    ]
    required_segment_names.insert(
        required_segment_names.index("cluster_snapshot_write"),
        "cluster_final_full_snapshot",
    )
    for index, name in enumerate(required_segment_names):
        start = float(index)
        end = duration if index == len(required_segment_names) - 1 else float(index + 1)
        segment_rows.append(
            {
                "id": f"segment_{index + 1:03d}",
                "name": name,
                "kind": "span",
                "category": "contract",
                "start_monotonic": start,
                "end_monotonic": end,
                "duration_seconds": end - start,
                "status": "PASS",
                "details": {},
            }
        )
    marker_rows = [
        {
            "id": f"event_{index:03d}",
            "name": name,
            "category": "m2_measurement",
            "at_monotonic": trial["monotonic_markers"][name],
            "elapsed_seconds": trial["monotonic_markers"][name],
            "details": {"source": "contract"},
        }
        for index, name in enumerate(M2.FORMATION_MARKERS, start=1)
    ]
    timeline = build_setup_timeline_artifact(
        capability_id="m2_contract",
        run_id=str(trial["run_id"]),
        scenario="cluster_timeout",
        profile_id=f"exact-{scale}",
        node_count=scale,
        status="PASS",
        segments=segment_rows,
        events=marker_rows,
        setup_command_wall_seconds=duration,
        real_valkey_evidence_summary={
            "status": "PASS",
            "real_valkey": True,
            "nodes_observed": scale,
            "data_path_result": "PASS",
            "role_counts": {"primary": scale // 2, "replica": scale // 2},
            "valkey_versions": list(trial["provenance"]["valkey_versions"]),
        },
        extra={
            "setup_command_wall_source": {
                "status": "PASS",
                "clock": "monotonic",
                "started_at_monotonic": 0.0,
                "ended_at_monotonic": duration,
            }
        },
    )
    node_rows: dict[str, dict[str, object]] = {}
    primary_count = scale // 2
    for index in range(scale):
        primary = index < primary_count
        node_id = f"node-{index:03d}"
        shard_index = index if primary else index - primary_count
        first_slot = (shard_index * 16384) // primary_count
        last_slot = ((shard_index + 1) * 16384) // primary_count - 1
        node_rows[node_id] = {
            "node_id": node_id,
            "flags": ["master" if primary else "slave"],
            "role": "primary" if primary else "replica",
            "master_id": "-" if primary else f"node-{shard_index:03d}",
            "link_state": "connected",
            "slots": [f"{first_slot}-{last_slot}"] if primary else [],
        }
    topology_probes = []
    for index in range(scale):
        logical_id = f"node-{index:03d}"
        view = deepcopy(node_rows)
        view[logical_id]["flags"] = [*view[logical_id]["flags"], "myself"]
        topology_probes.append(
            {
                "logical_id": logical_id,
                "status": "PASS",
                "ping": "PONG",
                "cluster_state": "ok",
                "cluster_slots_assigned": 16384,
                "cluster_slots_ok": 16384,
                "cluster_known_nodes": scale,
                "cluster_nodes": view,
            }
        )
    topology = {
        "status": "PASS",
        "versions": list(trial["provenance"]["valkey_versions"]),
        "valkey_binary_sha256s": ["b" * 64],
        "topology_control": [
            {
                "logical_id": f"node-{index:03d}",
                "shard_id": f"shard-{(index if index < primary_count else index - primary_count):03d}",
                "role": "primary" if index < primary_count else "replica",
                "az_id": f"az-{index % 3}",
            }
            for index in range(scale)
        ],
        "placement_control": [
            {
                "logical_id": f"node-{index:03d}",
                "nodehost_id": f"host-{index:03d}",
                "host_id": "contract-host",
                "az_id": f"az-{index % 3}",
            }
            for index in range(scale)
        ],
        "environment_control": {"docker_server": "contract", "host": "contract-host"},
        "probes": topology_probes,
    }
    treatment = trial["treatment"]
    strategy = (
        treatment["cluster_create_strategy"]
        if treatment["kind"] == "selected_settings"
        else treatment["value"]
        if treatment["kind"] == "cluster_create_strategy"
        else treatment.get("cluster_create_strategy", M2.BASELINE_FORMATION["value"])
    )
    timeout_ms = (
        treatment["cluster_node_timeout_ms"]
        if treatment["kind"] == "selected_settings"
        else treatment["value"]
        if treatment["kind"] == "cluster_node_timeout_ms"
        else 30000
    )
    state_nodes = [
        {
            "logical_id": f"node-{index:03d}",
            "container_name": "contract-nodehost",
            "container_id": "contract-container-id",
            "nodehost_id": "contract-nodehost",
            "pid": 10000 + index,
            "pid_file": f"/tmp/node-{index:03d}/valkey.pid",
            "config_file": f"/tmp/node-{index:03d}/valkey.conf",
            "client_port": 7000 + index,
            "simulated": False,
        }
        for index in range(scale)
    ]
    state_runtime = {
        "type": "docker_process",
        "project": "valkey-scale-lab",
        "run_id": trial["run_id"],
        "logical_node_count": scale,
        "cluster_create_strategy": strategy,
        "effective_cluster_node_timeout_ms": timeout_ms,
    }
    if isinstance(treatment.get("bounded_parallelism"), int):
        state_runtime["cluster_create_parallelism"] = treatment["bounded_parallelism"]
    state = {
        "backend_id": "docker_process",
        "capability_id": "m2_contract",
        "requested_nodes": scale,
        "observed_nodes": scale,
        "runtime": state_runtime,
        "nodehosts": [
            {
                "nodehost_id": "contract-nodehost",
                "container_id": "contract-container-id",
                "container_name": "contract-nodehost",
            }
        ],
        "nodes": state_nodes,
    }

    summary_resource = trial["resource_window"]
    resource_duration = float(summary_resource["duration_seconds"])
    target_pids = [int(target["pid"]) for target in (trial.get("fault") or {}).get("targets", [])]
    barrier = float(trial["monotonic_markers"].get("sigkill_barrier", 0.0))
    fault_resource = bool(target_pids)
    sample_times = (
        [barrier - 1.0, barrier, barrier + resource_duration]
        if fault_resource
        else [0.0, resource_duration]
    )

    def resource_process(node: dict[str, object], sample_index: int) -> dict[str, object]:
        return {
            "pid": node["pid"],
            "logical_id": node["logical_id"],
            "client_port": node["client_port"],
            "cpu_ticks": 1000 + sample_index * 100,
            "rss_bytes": 1000,
            "fd_count": 2,
            "connection_count": 1,
            "cluster_stats_bytes_sent": 10000 + sample_index * 20,
            "cluster_stats_bytes_received": 5000 + sample_index * 10,
            "cluster_stats_messages_sent": 1000 + sample_index * 2,
            "cluster_stats_messages_received": 500 + sample_index,
            "total_cluster_links_buffer_limit_exceeded": 0,
            "cluster_link_count": scale - 1,
            "cluster_link_errors": 0,
            "non_connected_cluster_link_count": 0,
            "non_connected_cluster_links": [],
            "directional_cluster_links": [],
        }

    resource_samples = []
    for sample_index, sample_time in enumerate(sample_times):
        gone = set(target_pids) if fault_resource and sample_index > 0 else set()
        sample = {
            "sample_index": sample_index,
            "scheduled_offset_seconds": (
                -1.0
                if fault_resource and sample_index == 0
                else float((sample_index - 1) * resource_duration)
                if fault_resource
                else float(sample_index * resource_duration)
            ),
            "timestamp_unix_ms": 1_700_000_000_000 + int(sample_time * 1000),
            "scheduled_at_monotonic_seconds": sample_time,
            "started_at_monotonic_seconds": sample_time,
            "ended_at_monotonic_seconds": sample_time,
            "schedule_lag_seconds": 0.0,
            "nodehosts": [
                {
                    "nodehost_id": "contract-nodehost",
                    "container_id": "contract-container-id",
                    "container_name": "contract-nodehost",
                    "ownership_id": trial["ownership_id"],
                    "clock_ticks_per_second": 100,
                    "page_size_bytes": 4096,
                    "processes": [
                        resource_process(node, sample_index)
                        for node in state_nodes
                        if node["pid"] not in gone
                    ],
                    "gone_pids": sorted(gone),
                    "namespace_network": {
                        "rx_bytes": 10000 + sample_index * 100,
                        "tx_bytes": 20000 + sample_index * 100,
                        "scope": "controlled-window container namespace",
                    },
                }
            ],
            "status": "PASS",
            "errors": [],
        }
        if fault_resource:
            sample["sample_phase"] = "pre_barrier" if sample_index == 0 else "window"
        resource_samples.append(sample)

    fault_bindings = [
        {
            "pid": int(node["pid"]),
            "logical_id": node["logical_id"],
            "client_port": node["client_port"],
            "nodehost_id": node["nodehost_id"],
            "container_id": node["container_id"],
            "ownership_id": trial["ownership_id"],
        }
        for node in state_nodes
        if node["pid"] in set(target_pids)
    ]
    target_processes = [
        {
            "nodehost_id": str(node["nodehost_id"]),
            "container_id": str(node["container_id"]),
            "pid": int(node["pid"]),
        }
        for node in state_nodes
        if node["pid"] in set(target_pids)
    ]
    window_samples = resource_samples[1:] if fault_resource else resource_samples
    resource = {
        "schema_version": "v1",
        "artifact_type": "m2_resource_window",
        "status": "PASS",
        "summary": "contract resource window",
        "window_name": "m2-contract",
        "duration_seconds": resource_duration,
        "interval_seconds": resource_duration,
        "clock_source": "injected_wall_unix_ms_and_monotonic_seconds",
        "ownership": {
            "project": "valkey-scale-lab",
            "ownership_ids": [trial["ownership_id"]],
            "container_ids": ["contract-container-id"],
            "pids": [node["pid"] for node in state_nodes],
            "client_ports": [node["client_port"] for node in state_nodes],
        },
        "coverage": {
            "complete": True,
            "expected_sample_count": len(resource_samples),
            "observed_sample_count": len(resource_samples),
            "nodehost_count": 1,
            "process_count": scale,
            "sample_timestamps_unix_ms": [sample["timestamp_unix_ms"] for sample in resource_samples],
            "sample_monotonic_seconds": [sample["started_at_monotonic_seconds"] for sample in resource_samples],
            "scheduled_offsets_seconds": [sample["scheduled_offset_seconds"] for sample in resource_samples],
            "actual_window_start_monotonic_seconds": window_samples[0]["started_at_monotonic_seconds"],
            "actual_window_end_monotonic_seconds": window_samples[-1]["started_at_monotonic_seconds"],
            "actual_window_span_seconds": resource_duration,
            "sampling_envelope_end_monotonic_seconds": window_samples[-1]["ended_at_monotonic_seconds"],
            "sampling_envelope_span_seconds": resource_duration,
            "max_schedule_lag_seconds": 0.0,
            "max_sample_collection_seconds": 0.0,
        },
        "fault_target_capture": {
            "expected_gone_processes": target_processes,
            "observed_gone_processes": target_processes,
            "captured_before_gone_processes": target_processes,
            "binding_status": "PASS",
            "bindings": fault_bindings,
        },
        "metrics": {},
        "diagnostics": {},
        "samples": resource_samples,
        "errors": [],
    }
    recomputed_resource = M2.validate_and_aggregate_m2_resource_samples(resource)
    assert recomputed_resource["status"] == "PASS", recomputed_resource["errors"]
    resource["metrics"] = recomputed_resource["metrics"]
    resource["diagnostics"] = recomputed_resource["diagnostics"]
    summary_resource.update(recomputed_resource["metrics"])
    summary_workload = trial["workload"]
    workload = {
        "status": "PASS",
        "requested_duration_seconds": summary_workload["duration_seconds"],
        "duration_seconds": summary_workload["duration_seconds"],
        "value_size_bytes": 512,
        "set_throughput_ops_per_second": summary_workload["set_throughput_ops_per_second"],
        "p99_latency_ms": summary_workload["p99_latency_ms"],
        "errors": [],
        "error_count": summary_workload["errors"],
        "timeout_count": 0,
        "persistent_cluster_client": summary_workload["persistent_cluster_client"],
        "per_operation_process_spawn": summary_workload["per_operation_process_spawn"],
        "affected_shard_max_interval_ms": summary_workload["affected_shard_max_interval_ms"],
        "stable_shards": summary_workload["stable_shards"],
    }
    if trial.get("fault") is None:
        workload.update(
            {
                "started_at_monotonic": 400.0,
                "ended_at_monotonic": 520.0,
                "operation_count": 12000,
                "latency_operation": "SET",
                "latency_histogram": {
                    "schema_version": M2.LATENCY_HISTOGRAM_SCHEMA_VERSION,
                    "buckets": [
                        {
                            "index": M2._latency_bucket_index_from_upper(1.0),
                            "count": 12000,
                        }
                    ],
                },
            }
        )
    if trial.get("fault") is not None:
        markers = trial["monotonic_markers"]
        barrier = float(markers["sigkill_barrier"])
        stable_endpoint = float(markers["stable_client_recovery"])
        workload_duration = float(summary_workload["duration_seconds"])
        starts = [round(barrier + index * 0.1, 6) for index in range(int(workload_duration * 10) + 1)]
        affected_attempts = []
        control_attempts = []
        for index, started in enumerate(starts):
            failed = index == 0
            completed = round(started + 0.001, 6)
            affected_attempts.append(
                {
                    "started_at_monotonic": started,
                    "completed_at_monotonic": completed,
                    "set_completed_at_monotonic": round(started + 0.0004, 6)
                    if not failed
                    else "MISSING",
                    "get_completed_at_monotonic": round(started + 0.0008, 6)
                    if not failed
                    else "MISSING",
                    "latency_ms": 1.0,
                    "set_succeeded": not failed,
                    "get_succeeded": not failed,
                    "value_matches": not failed,
                    "timed_out": False,
                    "error": "expected recovery failure" if failed else "",
                    "moved_count": 0,
                    "ask_count": 0,
                    "status": "FAIL" if failed else "PASS",
                }
            )
            control_attempts.append(
                {
                    "started_at_monotonic": started,
                    "completed_at_monotonic": completed,
                    "set_completed_at_monotonic": round(started + 0.0004, 6),
                    "get_completed_at_monotonic": round(started + 0.0008, 6),
                    "latency_ms": 1.0,
                    "set_succeeded": True,
                    "get_succeeded": True,
                    "value_matches": True,
                    "timed_out": False,
                    "error": "",
                    "moved_count": 0,
                    "ask_count": 0,
                    "status": "PASS",
                }
            )
        affected_series = {
            "shard_id": "shard-000",
            "affected": True,
            "key": "{contract-affected}:value",
            "attempts": affected_attempts,
            "attempt_count": len(starts),
            "set_success_count": len(starts) - 1,
            "get_success_count": len(starts) - 1,
            "error_count": 1,
            "timeout_count": 0,
            "moved_count": 0,
            "ask_count": 0,
        }
        control_series = {
            "shard_id": "shard-control",
            "affected": False,
            "key": "{contract-control}:value",
            "attempts": control_attempts,
            "attempt_count": len(starts),
            "set_success_count": len(starts),
            "get_success_count": len(starts),
            "error_count": 0,
            "timeout_count": 0,
            "moved_count": 0,
            "ask_count": 0,
        }
        workload.update(
            {
                "observed_duration_seconds": workload_duration,
                "errors": ["expected recovery failure"],
                "error_count": 1,
                "timeout_count": 0,
                "accumulator": {
                    "status": "PASS",
                    "window_ms": 1000.0,
                    "min_pairs": 10,
                    "max_pair_interval_ms": 100.0,
                    "required_shards": ["shard-000"],
                    "stable_endpoint_monotonic_ms": stable_endpoint * 1000.0,
                    "stable_window_skew_ms": 0.0,
                    "shards": [
                        {
                            "shard_id": "shard-000",
                            "status": "PASS",
                            "stable_at_monotonic_ms": stable_endpoint * 1000.0,
                            "sample_count": 11,
                            "failed_pair_count": 0,
                            "timeout_count": 0,
                            "cadence_gap_count": 0,
                        }
                    ],
                },
                "pre_fault_warmups": [{"status": "PASS", "shard_id": "shard-000"}],
                "first_success": {
                    "first_affected_write": barrier + 0.1004,
                    "first_affected_read": barrier + 0.1008,
                },
                "per_shard": [
                    {
                        "shard_id": "shard-000",
                        "affected": True,
                        "attempt_count": len(starts),
                        "max_attempt_interval_ms": 100.0,
                        "status": "PASS",
                    },
                    {
                        "shard_id": "shard-control",
                        "affected": False,
                        "attempt_count": len(starts),
                        "max_attempt_interval_ms": 100.0,
                        "status": "PASS",
                    },
                ],
                "client_series": [affected_series, control_series],
                "unaffected_control_shards": ["shard-control"],
            }
        )
    elif str(trial.get("cell_id", "")).startswith("stability-"):
        baseline_roles = {
            node_id: str(row["role"])
            for node_id, row in node_rows.items()
        }
        sample_probes = [topology_probes[0]]
        facts = M2._recompute_stability_facts(
            sample_probes,
            expected_nodes=scale,
            baseline_roles=baseline_roles,
        )
        workload["stability_observation"] = {
            "artifact_type": "m2_stability_observation",
            "status": "PASS",
            "duration_seconds": summary_workload["duration_seconds"],
            "observed_duration_seconds": summary_workload["duration_seconds"],
            "interval_seconds": summary_workload["duration_seconds"],
            "expected_sample_count": 2,
            "observed_sample_count": 2,
            "observer_count": 1,
            "max_sample_interval_ms": summary_workload["duration_seconds"] * 1000.0,
            "baseline_roles": baseline_roles,
            "samples": [
                {
                    "sample_index": index,
                    "started_at_monotonic": index * summary_workload["duration_seconds"],
                    "ended_at_monotonic": index * summary_workload["duration_seconds"],
                    "facts": facts,
                    "probes": sample_probes,
                }
                for index in range(2)
            ],
            "errors": [],
        }
    documents: dict[str, object] = {
        "attempt": {
            "artifact_type": "m2_trial_attempt",
            "status": "PASS",
            "trial_id": trial["trial_id"],
            "run_id": trial["run_id"],
            "ownership_id": trial["ownership_id"],
            "trial_started_at_monotonic": -1.0,
            "trial_ended_at_monotonic": max(sample_times) + 2.0,
            "setup": {
                "returncode": 0,
                "started_at_monotonic": 0.0,
                "ended_at_monotonic": max(duration, max(sample_times)) + 0.5,
            },
            "cleanup": {
                "returncode": 0,
                "started_at_monotonic": max(duration, max(sample_times)) + 0.5,
                "ended_at_monotonic": max(sample_times) + 1.0,
            },
        },
        "state": state,
        "cleanup": {
            "schema_version": "v1",
            "artifact_type": "cleanup_report",
            "capability_id": "m2_contract",
            "run_id": trial["run_id"],
            "created_at": "2026-07-19T00:00:00Z",
            "producer": {"name": "valkey-scale-lab", "version": "0.0.0"},
            "status": "PASS",
            "resources_remaining": [],
            "cleanup_actions": [],
            "cleanup_errors": [],
        },
        "timeline": timeline,
        "command_log": {
            "schema_version": "v1",
            "artifact_type": "runtime_command_log_entry",
            "run_id": trial["run_id"],
            "sequence": 1,
            "command_kind": "cluster_probe",
            "argv": ["valkey-cli", "PING"],
            "started_at_monotonic_ms": 1000.0,
            "ended_at_monotonic_ms": 1001.0,
            "monotonic_duration_ms": 1.0,
            "status": "PASS",
        },
        "resource": resource,
        "workload": workload,
        "topology": topology,
    }
    if trial.get("fault") is not None:
        fault_document = deepcopy(trial["fault"])
        trial["fault"] = M2._compact_fault_summary(fault_document)
        documents["fault"] = fault_document
    _intern_resource_directional_links(documents["resource"])

    preflight = {
        "schema_version": "v1",
        "artifact_type": "resource_preflight",
        "capability_id": "m2_contract",
        "run_id": str(report["invocation_run_id"]),
        "created_at": "2026-07-19T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": "0.0.0"},
        "status": "PASS",
        "node_count": scale,
        "profile_id": f"exact-{scale}",
        "can_run": True,
        "dry_run": False,
        "checks": [{"id": "contract", "status": "PASS"}],
    }
    preflight_path = artifacts_dir / f"resource_preflight_{trial['trial_id']}.json"
    preflight_payload = json.dumps(preflight, sort_keys=True) + "\n"
    preflight_path.write_text(preflight_payload, encoding="utf-8")
    preflight_ref = {
        "category": "preflight",
        "path": preflight_path.relative_to(artifacts_dir).as_posix(),
        "sha256": hashlib.sha256(preflight_payload.encode("utf-8")).hexdigest(),
    }
    report["source_refs"].append(preflight_ref)

    refs = {ref["category"]: ref for ref in trial["source_sha256s"]}
    top_refs = {ref["path"]: ref for ref in report["source_refs"]}
    paths: dict[str, Path] = {}
    for category, document in documents.items():
        ref = refs[category]
        path = artifacts_dir / ref["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if category == "command_log":
            payload = json.dumps(document, sort_keys=True) + "\n"
        else:
            payload = json.dumps(document, sort_keys=True) + "\n"
        path.write_text(payload, encoding="utf-8")
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        ref["sha256"] = digest
        top_refs[ref["path"]]["sha256"] = digest
        paths[category] = path

    provenance = trial["provenance"]
    provenance["definition_digest"] = M2._canonical_digest(
        {"mode": report["experiment_kind"], "protocol": report["protocol"]}
    )
    provenance["command_digest"] = refs["command_log"]["sha256"]
    provenance["product_digest"] = M2._current_product_digest()
    provenance["configuration_digest"] = M2._file_digest(
        PROJECT_ROOT / "templates" / "configs" / f"scale_{scale}.yaml"
    )
    provenance["valkey_binary_digest"] = M2._canonical_digest(
        {
            "versions": sorted(topology["versions"]),
            "valkey_binary_sha256s": sorted(topology["valkey_binary_sha256s"]),
        }
    )
    provenance["topology_digest"] = M2._canonical_digest(topology["topology_control"])
    provenance["placement_digest"] = M2._canonical_digest(topology["placement_control"])
    provenance["environment_digest"] = M2._canonical_digest(topology["environment_control"])
    targets = sorted(
        (
            {"logical_id": str(target["logical_id"]), "shard_id": str(target["shard_id"])}
            for target in (trial.get("fault") or {}).get("targets", [])
        ),
        key=lambda row: (row["logical_id"], row["shard_id"]),
    )
    provenance["workload_digest"] = M2._canonical_digest(
        {
            "value_size_bytes": workload["value_size_bytes"],
            "persistent": workload["persistent_cluster_client"],
            "duration": workload["requested_duration_seconds"],
            "fault_targets": targets,
        }
    )
    provenance["resource_preflight_digest"] = preflight_ref["sha256"]
    provenance["capture_digest"] = M2._canonical_digest(
        {
            category: ref["sha256"]
            for category, ref in refs.items()
            if category != "provenance"
        }
    )
    provenance_ref = refs["provenance"]
    provenance_path = artifacts_dir / provenance_ref["path"]
    payload = json.dumps(provenance, sort_keys=True) + "\n"
    provenance_path.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    provenance_ref["sha256"] = digest
    top_refs[provenance_ref["path"]]["sha256"] = digest
    paths["provenance"] = provenance_path
    paths["preflight"] = preflight_path
    trial["control_digests"] = {
        "valkey_binary": provenance["valkey_binary_digest"],
        "product": provenance["product_digest"],
        "configuration_except_treatment": provenance["configuration_digest"],
        "topology": provenance["topology_digest"],
        "placement": provenance["placement_digest"],
        "host": provenance["environment_digest"],
        "workload": provenance["workload_digest"],
        "resource_preflight": provenance["resource_preflight_digest"],
    }
    return paths


def _rewrite_bound_source(
    report: dict[str, object],
    trial: dict[str, object],
    path: Path,
    category: str,
    value: object,
) -> None:
    payload = json.dumps(value, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    ref = next(ref for ref in trial["source_sha256s"] if ref["category"] == category)
    ref["sha256"] = digest
    source_path = ref["path"]
    next(
        top_ref
        for top_ref in report["source_refs"]
        if top_ref["path"] == source_path and top_ref["category"] == category
    )["sha256"] = digest


def _retime_fault_attempt(attempt: dict[str, object], started: float) -> None:
    original = float(attempt["started_at_monotonic"])
    shift = started - original
    attempt["started_at_monotonic"] = round(started, 6)
    for field in (
        "completed_at_monotonic",
        "set_completed_at_monotonic",
        "get_completed_at_monotonic",
    ):
        value = attempt[field]
        if isinstance(value, (int, float)):
            attempt[field] = round(float(value) + shift, 6)


def _intern_fault_topology_views(fault: dict[str, object]) -> None:
    entries: dict[str, dict[str, object]] = {}

    def intern(views: object) -> str:
        digest = M2._canonical_digest(views)
        entries.setdefault(digest, {"sha256": digest, "views": views})
        return digest

    for round_row in fault["observer_rounds"]:
        round_row["views_sha256"] = intern(round_row.pop("views"))
    fault["every_node_convergence_views_sha256"] = intern(
        fault.pop("every_node_convergence_views")
    )
    fault["topology_view_dictionary"] = [
        entries[digest]
        for digest in sorted(entries)
    ]


def _fault_views_for_ref(
    fault: dict[str, object],
    digest: str,
) -> list[dict[str, object]]:
    matches = [
        entry["views"]
        for entry in fault["topology_view_dictionary"]
        if entry["sha256"] == digest
    ]
    assert len(matches) == 1
    return matches[0]


def _fault_round_views(
    fault: dict[str, object],
    index: int,
) -> list[dict[str, object]]:
    round_row = fault["observer_rounds"][index]
    return _fault_views_for_ref(fault, round_row["views_sha256"])


def _fault_convergence_views(
    fault: dict[str, object],
) -> list[dict[str, object]]:
    return _fault_views_for_ref(
        fault,
        fault["every_node_convergence_views_sha256"],
    )


def _rebind_fault_view_entry(
    fault: dict[str, object],
    old_digest: str,
) -> None:
    entry = next(
        entry
        for entry in fault["topology_view_dictionary"]
        if entry["sha256"] == old_digest
    )
    new_digest = M2._canonical_digest(entry["views"])
    entry["sha256"] = new_digest
    for round_row in fault["observer_rounds"]:
        if round_row["views_sha256"] == old_digest:
            round_row["views_sha256"] = new_digest
    if fault["every_node_convergence_views_sha256"] == old_digest:
        fault["every_node_convergence_views_sha256"] = new_digest


def _fault_source_report() -> tuple[dict[str, object], dict[str, object]]:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    markers = {
        "sigkill_barrier": 200.0,
        "all_processes_gone": 200.01,
        "first_pfail": 200.1,
        "quorum_fail": 200.2,
        "first_promotion": 200.3,
        "all_slots_covered_cluster_ok": 200.4,
        "stable_client_recovery": 201.401,
        "every_node_converged": 201.5,
    }
    trial["monotonic_markers"].update(markers)
    trial["derived_intervals"].update(
        {
            "kill_to_stable_seconds": 1.401,
            "pfail_to_cluster_ok_seconds": 0.3,
            "process_gone_to_pfail_seconds": 0.09,
            "cluster_ok_to_stable_seconds": 1.001,
            "sigkill_to_pfail_seconds": 0.1,
            "pfail_to_quorum_fail_seconds": 0.1,
            "quorum_fail_to_promotion_seconds": 0.1,
            "promotion_to_cluster_ok_seconds": 0.1,
            "recovery_to_convergence_seconds": 0.099,
            "sigkill_to_first_write_seconds": 0.1004,
            "sigkill_to_first_read_seconds": 0.1008,
        }
    )
    trial["workload"]["duration_seconds"] = 2.0
    trial["workload"]["set_throughput_ops_per_second"] = 20.5
    trial["workload"]["errors"] = 1
    trial["workload"]["affected_shard_max_interval_ms"] = 100.0
    trial["workload"]["stable_shards"] = [
        {
            "shard_id": "shard-000",
            "window_start_monotonic": 200.401,
            "window_seconds": 1,
            "consecutive_pairs": 11,
            "errors": 0,
            "timeouts": 0,
            "endpoint_monotonic": 201.401,
            "earliest_qualifying": True,
        }
    ]
    target_node_id = "node-000"
    replacement_node_id = "node-025"
    primary_count = 25
    initial_roles = {
        f"node-{index:03d}": "primary" if index < primary_count else "replica"
        for index in range(50)
    }
    node_shards = {
        f"node-{index:03d}": f"shard-{(index if index < primary_count else index - primary_count):03d}"
        for index in range(50)
    }
    initial_nodes: dict[str, dict[str, object]] = {}
    for index in range(50):
        node_id = f"node-{index:03d}"
        primary = index < primary_count
        shard_index = index if primary else index - primary_count
        first_slot = (shard_index * 16384) // primary_count
        last_slot = ((shard_index + 1) * 16384) // primary_count - 1
        initial_nodes[node_id] = {
            "node_id": node_id,
            "addr": f"127.0.0.1:{7000 + index}@{17000 + index}",
            "flags": ["master" if primary else "slave"],
            "role": "primary" if primary else "replica",
            "master_id": "-" if primary else f"node-{shard_index:03d}",
            "link_state": "connected",
            "slots": [f"{first_slot}-{last_slot}"] if primary else [],
        }

    def compact_view(
        logical_id: str,
        *,
        target_flags: list[str],
        replacement_role: str,
        cluster_ok: bool,
    ) -> dict[str, object]:
        cluster_nodes = deepcopy(initial_nodes)
        cluster_nodes[target_node_id]["flags"] = list(target_flags)
        cluster_nodes[target_node_id]["link_state"] = "disconnected"
        if replacement_role == "primary":
            cluster_nodes[replacement_node_id].update(
                {
                    "flags": ["master"],
                    "role": "primary",
                    "master_id": "-",
                    "slots": list(initial_nodes[target_node_id]["slots"]),
                }
            )
        cluster_nodes[logical_id]["flags"] = [*cluster_nodes[logical_id]["flags"], "myself"]
        return {
            "logical_id": logical_id,
            "status": "PASS",
            "cluster_state": "ok" if cluster_ok else "fail",
            "cluster_slots_assigned": 16384 if cluster_ok else 0,
            "cluster_slots_ok": 16384 if cluster_ok else 0,
            "cluster_known_nodes": 50,
            "cluster_nodes": cluster_nodes,
            "target_flags": {target_node_id: cluster_nodes[target_node_id]["flags"]},
            "replacement_roles": {replacement_node_id: replacement_role},
        }

    def facts_for(views: list[dict[str, object]]) -> dict[str, object]:
        recomputed, contract, _logical_ids = M2._recompute_compact_fault_facts(
            views,
            initial_roles=initial_roles,
            node_shards=node_shards,
            target_node_ids={target_node_id},
            replacement_node_ids={replacement_node_id},
            expected_nodes=50,
        )
        assert contract
        return recomputed

    round_specs = [
        (200.1, ["master", "pfail"], "replica", False),
        (200.2, ["master", "fail"], "replica", False),
        (200.3, ["master", "fail"], "primary", False),
        (200.4, ["master", "fail"], "primary", True),
        (201.4, ["master", "fail"], "primary", True),
        (202.0, ["master", "fail"], "primary", True),
    ]
    observer_rounds = []
    for index, (observed_at, flags, role, cluster_ok) in enumerate(round_specs):
        views = [
            compact_view(
                logical_id,
                target_flags=flags,
                replacement_role=role,
                cluster_ok=cluster_ok,
            )
            for logical_id in ("node-001", "node-002", "node-003")
        ]
        observer_rounds.append(
            {
                "at_monotonic": observed_at,
                "probe_started_at_monotonic": observed_at - 0.01,
                "probe_duration_ms": 10.0,
                "facts": facts_for(views),
                "views": views,
            }
        )
    convergence_views = [
        compact_view(
            f"node-{index + 1:03d}",
            target_flags=["master", "fail"],
            replacement_role="primary",
            cluster_ok=True,
        )
        for index in range(49)
    ]
    topology_facts = facts_for(convergence_views)
    fault_argv = [
        "exec",
        "contract-container-id",
        "sh",
        "-c",
        "kill -KILL 10000",
    ]
    trial["fault"] = {
        "status": "PASS",
        "errors": [],
        "mode": "owned-process-sigkill",
        "signal": "SIGKILL",
        "commands": [M2.shlex.join(["docker", *fault_argv])],
        "command_batches": [
            {
                "container_name": "contract-nodehost",
                "container_id": "contract-container-id",
                "logical_ids": ["node-000"],
                "pids": [10000],
                "ownership_id": trial["ownership_id"],
                "argv": fault_argv,
                "started_at_monotonic": 200.0,
                "ended_at_monotonic": 200.001,
                "returncode": 0,
                "stdout": "",
                "status": "PASS",
            }
        ],
        "barrier_monotonic": 200.0,
        "fault_apply_monotonic_ms": 200000.0,
        "injection_skew_ms": 1.0,
        "signal_barrier_span_ms": 1.0,
        "primary_count": 25,
        "failed_primary_count": 1,
        "targets": [
            {
                "logical_id": "node-000",
                "shard_id": "shard-000",
                "pid": 10000,
                "ownership_id": trial["ownership_id"],
                "process_gone": True,
                "signal_sent_at_monotonic_ms": 200000.0,
                "signal_completed_at_monotonic_ms": 200001.0,
                "process_gone_at_monotonic_ms": 200010.0,
                "status": "PASS",
                "valkey_node_id": target_node_id,
                "physical_fault_id": "fault-physical-001",
            }
        ],
        "monotonic_markers": markers,
        "initial_roles": initial_roles,
        "node_shards": node_shards,
        "observer_rounds": observer_rounds,
        "topology_facts": topology_facts,
        "observed_safety": {
            "unexpected_pfail": 0,
            "unexpected_fail": 0,
            "unexpected_promotions": 0,
            "split_brain": False,
        },
        "target_node_ids": [target_node_id],
        "replacement_node_ids": [replacement_node_id],
        "every_node_convergence_probe": {
            "at_monotonic": 201.5,
            "probe_started_at_monotonic": 201.49,
            "probe_duration_ms": 10.0,
        },
        "every_node_convergence_views": convergence_views,
    }
    _intern_fault_topology_views(trial["fault"])
    trial["correctness"].update(
        {
            "exact_membership": True,
            "observed_nodes": 50,
            "slots_covered": 16384,
            "replicas_synchronized": True,
            "clean_topology": True,
            "data_path": True,
            "split_brain": False,
            "unexpected_pfail": 0,
            "unexpected_fail": 0,
            "unexpected_promotions": 0,
            "slot_loss": False,
        }
    )
    trial["source_sha256s"].append(
        {
            "category": "fault",
            "path": f"{trial['evidence_root']}/fault_observation.json",
            "sha256": SHA,
        }
    )
    report["experiment_kind"] = "failover"
    report["trials"] = [trial]
    report["cells"] = [
        {
            "cell_id": trial["cell_id"],
            "campaign_step": "matrix",
            "scale": trial["scale"],
            "failure_rate": "one",
            "required_pairs": 1,
            "candidate": {"kind": "cluster_node_timeout_ms", "value": 15000},
            "status": "PASS",
        }
    ]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    return report, trial


def test_nearest_rank_uses_ceil_index_without_interpolation() -> None:
    assert M2.nearest_rank([1, 2, 3, 4, 5, 6, 7], 0.95) == 7
    assert M2.nearest_rank(list(range(1, 11)), 0.95) == 10
    assert M2.nearest_rank(list(range(1, 11)), 0.50) == 5
    with pytest.raises(ValueError):
        M2.nearest_rank([], 0.95)


def test_failed_primary_count_uses_half_up_not_bankers_rounding() -> None:
    assert M2.failed_primary_count(50, "one") == 1
    assert M2.failed_primary_count(50, "10_percent") == 3
    assert M2.failed_primary_count(50, "33_percent") == 8
    assert M2.failed_primary_count(200, "10_percent") == 10
    assert M2.failed_primary_count(200, "33_percent") == 33


def test_complete_formation_report_satisfies_semantic_contract() -> None:
    report = _formation_report()

    assert M2.validate_report(
        report,
        expected_kind="formation",
        expected_invocation_run_id="m2-contract",
    ) == []


def test_selection_only_formation_screen_accepts_zero_survivors() -> None:
    campaign = _formation_discovery_campaign()
    passing_cell = next(cell for cell in campaign["cells"] if cell["status"] == "PASS")
    passing_cell["status"] = "FAIL"
    pair = next(
        pair
        for pair in campaign["pairs"]
        if pair["cell_id"] == passing_cell["cell_id"]
    )
    candidate = next(
        trial
        for trial in campaign["trials"]
        if trial["trial_id"] == pair["candidate_trial_id"]
    )
    candidate["derived_intervals"]["formation_seconds"] = 110.0
    candidate["monotonic_markers"]["data_path_probe"] = 110.0

    assert all(
        cell["scale"] == 50
        and cell["failure_rate"] == "none"
        and cell["required_pairs"] == 1
        and cell["status"] == "FAIL"
        for cell in campaign["cells"]
    )
    assert M2.validate_discovery_campaign(
        campaign,
        expected_kind="formation",
        expected_invocation_run_id="m2-contract",
    ) == []


def test_selection_only_formation_screen_rejects_unsafe_candidate_without_failing_campaign() -> None:
    campaign = _formation_discovery_campaign()
    cell = next(cell for cell in campaign["cells"] if cell["status"] == "PASS")
    pair = next(pair for pair in campaign["pairs"] if pair["cell_id"] == cell["cell_id"])
    candidate = next(
        trial
        for trial in campaign["trials"]
        if trial["trial_id"] == pair["candidate_trial_id"]
    )
    candidate["resource_window"]["cluster_link_errors"] = 1
    cell["status"] = "FAIL"

    assert M2.validate_discovery_campaign(
        campaign,
        expected_kind="formation",
        expected_invocation_run_id="m2-contract",
    ) == []

    cell["status"] = "PASS"
    assert any(
        "status does not match measured screen result" in error
        for error in M2.validate_discovery_campaign(
            campaign,
            expected_kind="formation",
            expected_invocation_run_id="m2-contract",
        )
    )


def test_selection_only_formation_screen_rejects_resource_regression_without_failing_campaign() -> None:
    campaign = _formation_discovery_campaign()
    cell = next(cell for cell in campaign["cells"] if cell["status"] == "PASS")
    pair = next(pair for pair in campaign["pairs"] if pair["cell_id"] == cell["cell_id"])
    candidate = next(
        trial
        for trial in campaign["trials"]
        if trial["trial_id"] == pair["candidate_trial_id"]
    )
    candidate["resource_window"]["peak_rss_bytes"] = 111.0
    cell["status"] = "FAIL"

    assert M2.validate_discovery_campaign(
        campaign,
        expected_kind="formation",
        expected_invocation_run_id="m2-contract",
    ) == []

    cell["status"] = "PASS"
    errors = M2.validate_discovery_campaign(
        campaign,
        expected_kind="formation",
        expected_invocation_run_id="m2-contract",
    )
    assert any("regressed by more than 10 percent" in error for error in errors)
    assert any("status does not match measured screen result" in error for error in errors)


def test_discovery_rejects_nonfixed_formation_strategy() -> None:
    campaign = json.loads(
        json.dumps(_formation_discovery_campaign()).replace(
            "tree_meet_addslotsrange", "evil_addslotsrange"
        )
    )

    errors = M2.validate_discovery_campaign(
        campaign,
        expected_kind="formation",
        expected_invocation_run_id="m2-contract",
    )

    assert (
        "formation discovery must contain exactly the fixed manual-tree and ADDSLOTSRANGE candidates"
        in errors
    )


def test_discovery_rejects_duplicate_failover_timeout_candidate() -> None:
    current_strategy = M2._current_formation_strategy()
    baseline = {
        **M2.BASELINE_FAILOVER,
        "cluster_create_strategy": current_strategy,
    }
    candidates = [
        {
            "kind": "cluster_node_timeout_ms",
            "value": value,
            "cluster_create_strategy": current_strategy,
        }
        for value in (5000, 10000, 15000, 15000)
    ]
    errors: list[str] = []

    M2._validate_failover_discovery(
        {
            "baseline": baseline,
            "candidates": candidates,
            "current_defaults": {"cluster_create_strategy": current_strategy},
        },
        {},
        {},
        {},
        errors,
        require_selected=False,
    )

    assert (
        "failover screen must contain 5000, 10000, and 15000 ms with one current formation strategy"
        in errors
    )


def test_discovery_report_is_distinct_and_never_admission_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    formation = _formation_discovery_campaign()
    for cell in formation["cells"]:
        cell["status"] = "FAIL"
    campaigns = {
        "formation": formation,
        "failover": {"cells": []},
    }
    args = type(
        "Args",
        (),
        {"run_id": "m2-contract", "tested_sha": "b" * 40},
    )()
    report = DISCOVERY._build_report(
        args,
        status="PASS",
        campaigns=campaigns,
        survivors={"formation": [], "failover": []},
        errors=[],
    )
    monkeypatch.setattr(
        DISCOVERY.admission,
        "validate_discovery_campaign",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        DISCOVERY.admission,
        "validate_current_invocation_sources",
        lambda *_args, **_kwargs: [],
    )

    assert DISCOVERY.validate_discovery_report(
        report,
        artifacts_dir=tmp_path,
        expected_run_id="m2-contract",
        expected_sha="b" * 40,
    ) == []
    assert report["artifact_type"] == "m2_candidate_discovery"
    assert report["purpose"] == "candidate-selection-only"
    assert report["admission_evidence"] is False
    assert report["survivors"] == {"formation": [], "failover": []}
    assert "criterion_results" not in report
    assert M2.validate_report(report)


def test_formation_relative_absolute_and_resource_budgets_are_enforced() -> None:
    report = _formation_report()
    for trial in report["trials"]:
        if trial["arm"] != "candidate":
            continue
        if trial["cell_id"] == "promotion-50":
            trial["derived_intervals"]["formation_seconds"] = 61.0
            trial["monotonic_markers"]["data_path_probe"] = 61.0
        elif trial["cell_id"] == "promotion-100":
            trial["derived_intervals"]["formation_seconds"] = 71.0
            trial["monotonic_markers"]["data_path_probe"] = 71.0
    first_candidate = next(
        trial
        for trial in report["trials"]
        if trial["arm"] == "candidate" and trial["cell_id"] == "promotion-50"
    )
    first_candidate["resource_window"]["peak_rss_bytes"] = 111.0
    report["report_digest"] = M2.report_digest(report)

    errors = M2.validate_report(report)

    assert any("formation exact-50 observed p95 exceeds 60 seconds" in error for error in errors)
    assert any("formation exact-100 median improvement is below 30%" in error for error in errors)
    assert any("peak_rss_bytes regressed by more than 10 percent" in error for error in errors)


def test_failover_relative_and_absolute_budgets_are_enforced(monkeypatch) -> None:
    current_strategy = "future-promoted-strategy"
    monkeypatch.setattr(M2, "_current_formation_strategy", lambda: current_strategy)
    baseline = {
        "kind": "cluster_node_timeout_ms",
        "value": 30000,
        "cluster_create_strategy": current_strategy,
    }
    candidates = [
        {
            "kind": "cluster_node_timeout_ms",
            "value": value,
            "cluster_create_strategy": current_strategy,
        }
        for value in (5000, 10000, 15000)
    ]
    selected = candidates[0]
    cells: dict[str, dict[str, object]] = {}
    pairs_by_cell: dict[str, list[dict[str, object]]] = {}
    trials: dict[str, dict[str, object]] = {}

    def add_pair(
        cell_id: str,
        sequence: int,
        scale: int,
        baseline_rto: float,
        candidate_rto: float,
        pfail: float,
        detection: float,
        client: float,
    ) -> None:
        baseline_id = f"{cell_id}-b-{sequence}"
        candidate_id = f"{cell_id}-c-{sequence}"
        pairs_by_cell.setdefault(cell_id, []).append(
            {
                "pair_id": f"{cell_id}-p-{sequence}",
                "baseline_trial_id": baseline_id,
                "candidate_trial_id": candidate_id,
            }
        )
        for trial_id, arm, rto in (
            (baseline_id, "baseline", baseline_rto),
            (candidate_id, "candidate", candidate_rto),
        ):
            trials[trial_id] = {
                "trial_id": trial_id,
                "cell_id": cell_id,
                "arm": arm,
                "scale": scale,
                "derived_intervals": {
                    "kill_to_stable_seconds": rto,
                    "pfail_to_cluster_ok_seconds": pfail,
                    "process_gone_to_pfail_seconds": detection,
                    "cluster_ok_to_stable_seconds": client,
                },
                "monotonic_markers": {},
                "fault": {},
                "workload": {},
                "resource_window": {
                    "peak_rss_bytes": 100.0,
                    "cpu_time_seconds": 100.0,
                    "fd_count": 100.0,
                    "connection_count": 100.0,
                    "cluster_bus_bytes": 100.0,
                    "cluster_link_errors": 0,
                    "buffer_overflows": 0,
                },
            }

    for candidate in candidates:
        cell_id = f"discovery-{candidate['value']}"
        passed = candidate == selected
        cells[cell_id] = {
            "cell_id": cell_id,
            "campaign_step": "discovery",
            "scale": 50,
            "failure_rate": "one",
            "required_pairs": 1,
            "candidate": candidate,
            "status": "PASS" if passed else "FAIL",
        }
        if passed:
            add_pair(cell_id, 1, 50, 40.0, 20.0, 5.0, 5.0, 1.0)

    for scale in (50, 200):
        for rate in M2.FAILURE_RATES:
            cell_id = f"matrix-{scale}-{rate}"
            cells[cell_id] = {
                "cell_id": cell_id,
                "campaign_step": "matrix",
                "scale": scale,
                "failure_rate": rate,
                "required_pairs": 10,
                "candidate": selected,
                "status": "PASS",
            }
            for sequence in range(1, 11):
                if scale == 50 and rate == "one":
                    values = (100.0, 36.0, 11.0, 26.0, 2.1)
                elif scale == 50 and rate == "10_percent":
                    values = (40.0, 33.0, 14.0, 26.0, 1.0)
                else:
                    values = (40.0, 30.0, 24.0, 26.0, 1.0)
                add_pair(cell_id, sequence, scale, *values)

    errors: list[str] = []
    M2._validate_failover(
        {
            "baseline": baseline,
            "candidates": candidates,
            "selected_candidate": selected,
            "current_defaults": {"cluster_create_strategy": current_strategy},
        },
        trials,
        pairs_by_cell,
        cells,
        errors,
    )

    assert any("p50 improvement is below 20 percent" in error for error in errors)
    assert any("client RTO p95 exceeds its absolute budget" in error for error in errors)
    assert any("PFAIL-to-cluster-OK p95 exceeds its budget" in error for error in errors)
    assert any("process-gone-to-PFAIL p95 exceeds 25 seconds" in error for error in errors)
    assert any("cluster-OK to stable client exceeds 2 seconds" in error for error in errors)
    assert not any("current formation strategy" in error for error in errors)


def test_timeout_state_binds_the_paired_dynamic_formation_strategy() -> None:
    strategy = "future-promoted-strategy"
    trial = {
        "trial_id": "timeout-arm",
        "scale": 1,
        "run_id": "timeout-arm",
        "ownership_id": "timeout-arm",
        "treatment": {
            "kind": "cluster_node_timeout_ms",
            "value": 15000,
            "cluster_create_strategy": strategy,
        },
    }
    state = {
        "backend_id": "docker_process",
        "requested_nodes": 1,
        "observed_nodes": 1,
        "runtime": {
            "type": "docker_process",
            "project": "valkey-scale-lab",
            "run_id": "timeout-arm",
            "logical_node_count": 1,
            "cluster_create_strategy": strategy,
            "effective_cluster_node_timeout_ms": 15000,
        },
        "nodes": [
            {
                "logical_id": "node-000",
                "container_name": "container-000",
                "pid": 1000,
                "simulated": False,
            }
        ],
    }
    errors: list[str] = []

    M2._validate_state_source(state, trial, errors)

    assert errors == []


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda report: report["trials"][0].__setitem__("fresh_cluster", False), "fresh cluster"),
        (lambda report: report["trials"][0]["cleanup"].__setitem__("resources_remaining", [{}]), "owned resources"),
        (lambda report: report["trials"][0]["provenance"].__setitem__("historical", True), "historical evidence"),
        (lambda report: report["trials"][0].__setitem__("unexplained_seconds", 0.1), "unexplained wall time"),
        (lambda report: report["trials"][0]["resource_window"].__setitem__("fd_count", "MISSING"), "fd_count is missing"),
    ],
)
def test_report_rejects_invalid_samples_fail_closed(mutate, message: str) -> None:
    report = _formation_report()
    mutate(report)
    report["report_digest"] = M2.report_digest(report)

    errors = M2.validate_report(report)

    assert any(message in error for error in errors)


def test_source_validation_rejects_missing_and_historical_paths(tmp_path: Path) -> None:
    report = _formation_report()
    report["trials"] = [deepcopy(report["trials"][0])]
    trial = report["trials"][0]
    trial["evidence_root"] = "loop_evidence/old"

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("forbidden non-current evidence" in error for error in errors)
    assert any("missing" in error for error in errors)


_HISTORICAL_GATE_MANIFEST = json.loads(
    (
        PROJECT_ROOT
        / "tests"
        / "fixtures"
        / "m2_regressions"
        / "historical_gate_replays.json"
    ).read_text(encoding="utf-8")
)
_HISTORICAL_GATE_CASES = _HISTORICAL_GATE_MANIFEST["runs"]


def _historical_gate_case(run_id: str) -> dict[str, object]:
    return next(
        case
        for case in _HISTORICAL_GATE_CASES
        if case["source_run_id"] == run_id
    )


def _historical_gate_bundle_members(
    case: dict[str, object],
) -> dict[str, bytes]:
    fixture_dir = PROJECT_ROOT / "tests" / "fixtures" / "m2_regressions"
    fixture = case["fixture"]
    archive_path = fixture_dir / fixture["file"]
    compressed = archive_path.read_bytes()
    assert len(compressed) == fixture["gzip_bytes"]
    assert hashlib.sha256(compressed).hexdigest() == fixture["sha256"]
    assert compressed[4:8] == b"\0\0\0\0"

    members: dict[str, bytes] = {}
    with tarfile.open(archive_path, mode="r:gz") as archive:
        rows = archive.getmembers()
        assert [row.name for row in rows] == sorted(row.name for row in rows)
        for row in rows:
            assert row.isfile()
            assert row.uid == row.gid == row.mtime == 0
            source = archive.extractfile(row)
            assert source is not None
            members[row.name] = source.read()
    assert len(members) == fixture["file_count"]
    assert sum(len(value) for value in members.values()) == fixture["source_bytes"]
    return members


def _verified_historical_report(
    case: dict[str, object],
) -> tuple[dict[str, bytes], dict[str, object]]:
    members = _historical_gate_bundle_members(case)
    report_bytes = members["m2_candidate_discovery.json"]
    assert hashlib.sha256(report_bytes).hexdigest() == case["report_sha256"]
    report = json.loads(report_bytes)
    refs = [
        ref
        for campaign in report["campaigns"].values()
        for ref in campaign["source_refs"]
    ]
    assert set(members) == {
        "m2_candidate_discovery.json",
        *(ref["path"] for ref in refs),
    }
    for ref in refs:
        assert hashlib.sha256(members[ref["path"]]).hexdigest() == ref["sha256"]

    run_id = case["source_run_id"]
    artifact = case["evidence_artifact"]
    sealed = case["sealed_result"]
    assert case["source_run_attempt"] == 1
    assert artifact["name"] == f"m2-discovery-evidence-{run_id}-1"
    assert artifact["id"] > 0
    assert artifact["archive_size_bytes"] > 0
    assert M2.SHA256_RE.fullmatch(artifact["sha256"])
    assert M2.SHA256_RE.fullmatch(sealed["evidence_digest"])
    assert report["invocation_run_id"] == case["invocation_run_id"]
    assert report["tested_sha"] == case["producer_head_sha"]
    assert report["status"] == case["original_status"] == "FAIL"
    assert report["errors"] == [case["original_capture_error"]]
    assert report["report_digest"] == sealed["report_digest"]
    assert report["report_digest"] == M2.report_digest(report)
    return members, report


def _write_historical_members(members: dict[str, bytes], target_root: Path) -> None:
    for relative, payload in members.items():
        target = (target_root / relative).resolve()
        assert target.is_relative_to(target_root.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


def _historical_partial_resource_sources(
    members: dict[str, bytes],
    report: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    formation = report["campaigns"]["formation"]
    refs = {
        ref["category"]: ref
        for ref in formation["source_refs"]
    }
    state = json.loads(members[refs["state"]["path"]])
    timeline = json.loads(members[refs["timeline"]["path"]])
    resource = json.loads(members[refs["resource"]["path"]])
    first_membership = next(
        event
        for event in timeline["events"]
        if event["name"] == "first_membership_command"
    )
    trial = {
        "trial_id": timeline["run_id"],
        "run_id": timeline["run_id"],
        "cell_id": "formation-discovery-replay",
        "scale": state["requested_nodes"],
        "ownership_id": state["runtime"]["run_id"],
        "monotonic_markers": {
            "first_membership_command": first_membership["at_monotonic"],
        },
        "resource_window": {
            "duration_seconds": resource["duration_seconds"],
            **resource["metrics"],
        },
    }
    return trial, state, timeline, resource


def _resource_processes(resource: dict[str, object]) -> list[dict[str, object]]:
    return [
        process
        for sample in resource["samples"]
        for nodehost in sample["nodehosts"]
        for process in nodehost["processes"]
    ]


def _losslessly_intern_historical_resource(
    original: dict[str, object],
) -> dict[str, object]:
    adapted = deepcopy(original)
    _intern_resource_directional_links(adapted)
    expanded = deepcopy(adapted)
    _expand_resource_directional_links(expanded)
    assert expanded == original
    return adapted


def test_historical_gate_manifest_covers_all_requested_runs() -> None:
    assert _HISTORICAL_GATE_MANIFEST["replay_entrypoint"] == (
        "scripts.m2_candidate_discovery.validate_discovery_report"
    )
    assert _HISTORICAL_GATE_MANIFEST["expectation_scope"] == (
        "immutable original FAIL reports traverse the production discovery Gate "
        "and remain rejected; bounded lossless adapters exercise only the named "
        "lower Gate layer"
    )
    assert {case["source_run_id"] for case in _HISTORICAL_GATE_CASES} == {
        "29845739384",
        "29885627925",
        "29901022395",
        "29916936241",
        "29925711801",
        "29931564838",
        "29992169655",
        "29997723777",
    }
    assert len(_HISTORICAL_GATE_CASES) == 8
    assert _HISTORICAL_GATE_MANIFEST["replay_expectations"] == {
        "29845739384": {
            "classification": "LEGACY_SCHEMA_INCOMPLETE",
            "expected_gate": "REJECT",
            "adapter_expectation": "NONE",
        },
        "29885627925": {
            "classification": "LEGACY_SCHEMA_INCOMPLETE",
            "expected_gate": "REJECT",
            "adapter_expectation": "NONE",
        },
        "29901022395": {
            "classification": "LEGACY_SCHEMA_INCOMPLETE",
            "expected_gate": "REJECT",
            "adapter_expectation": "NONE",
        },
        "29916936241": {
            "classification": "FORMATION_CAMPAIGN_CURRENT_SCHEMA_PASS",
            "expected_gate": "REJECT",
            "adapter_expectation": "FORMATION_CAMPAIGN_GATE_PASS",
        },
        "29925711801": {
            "classification": "FORMATION_TRANSITION_CURRENT_SCHEMA_PASS",
            "expected_gate": "REJECT",
            "adapter_expectation": "RESOURCE_SOURCE_GATE_PASS",
        },
        "29931564838": {
            "classification": "FORMATION_TRANSITION_CURRENT_SCHEMA_PASS",
            "expected_gate": "REJECT",
            "adapter_expectation": "RESOURCE_SOURCE_GATE_PASS",
        },
        "29992169655": {
            "classification": "CAPTURE_IMPLEMENTATION_DEFECT_KILL_EXECUTABLE_127",
            "expected_gate": "REJECT",
            "adapter_expectation": "FAULT_SLICE_REJECT",
        },
        "29997723777": {
            "classification": "MEASUREMENT_RUNTIME_DEFECT_CADENCE_CONTRACT",
            "expected_gate": "REJECT",
            "adapter_expectation": "FAULT_SLICE_REJECT",
        },
    }


@pytest.mark.parametrize(
    "case",
    _HISTORICAL_GATE_CASES,
    ids=lambda case: f"run-{case['source_run_id']}",
)
def test_historical_original_bundle_is_provenance_bound(
    case: dict[str, object],
) -> None:
    _members, report = _verified_historical_report(case)
    assert report["status"] == "FAIL"


@pytest.mark.parametrize(
    "case",
    _HISTORICAL_GATE_CASES,
    ids=lambda case: f"run-{case['source_run_id']}",
)
def test_historical_original_failure_replays_through_production_gate(
    tmp_path: Path,
    case: dict[str, object],
) -> None:
    members, report = _verified_historical_report(case)
    _write_historical_members(members, tmp_path)

    errors = DISCOVERY.validate_discovery_report(
        report,
        artifacts_dir=tmp_path,
        expected_run_id=case["invocation_run_id"],
        expected_sha=case["producer_head_sha"],
    )

    assert _HISTORICAL_GATE_MANIFEST["replay_expectations"][
        case["source_run_id"]
    ]["expected_gate"] == "REJECT"
    assert "completed discovery report did not PASS cleanly" in errors


@pytest.mark.parametrize(
    "run_id",
    ["29845739384", "29885627925", "29901022395"],
)
def test_legacy_historical_resource_schema_fails_closed(run_id: str) -> None:
    case = _historical_gate_case(run_id)
    expectation = _HISTORICAL_GATE_MANIFEST["replay_expectations"][run_id]
    assert expectation == {
        "classification": "LEGACY_SCHEMA_INCOMPLETE",
        "expected_gate": "REJECT",
        "adapter_expectation": "NONE",
    }
    members, report = _verified_historical_report(case)
    trial, state, _timeline, resource = _historical_partial_resource_sources(
        members,
        report,
    )
    assert all("sample_phase" not in sample for sample in resource["samples"])
    assert all(
        "directional_cluster_links" not in process
        and "directional_cluster_links_sha256" not in process
        for process in _resource_processes(resource)
    )

    errors: list[str] = []
    M2._validate_resource_source(
        resource,
        trial,
        fault_trial=False,
        allow_initial_membership_transitions=True,
        state_document=state,
        errors=errors,
    )

    assert any("CLUSTER LINKS dictionary is missing" in error for error in errors)
    assert any("raw resource samples are incomplete or invalid" in error for error in errors)


def _historical_formation_transition_source_report(
    tmp_path: Path,
    run_id: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    case = _historical_gate_case(run_id)
    assert _HISTORICAL_GATE_MANIFEST["replay_expectations"][run_id][
        "adapter_expectation"
    ] == "RESOURCE_SOURCE_GATE_PASS"
    members, report = _verified_historical_report(case)
    partial_trial, state, timeline, original = _historical_partial_resource_sources(
        members,
        report,
    )
    assert original["metrics"]["cluster_link_errors"] in {1, 2}
    assert "post_formation" in {
        sample["sample_phase"]
        for sample in original["samples"]
    }

    source_report = _formation_report()
    trial = next(
        row
        for row in source_report["trials"]
        if row["scale"] == state["requested_nodes"]
    )
    runtime = state["runtime"]
    treatment = {
        "kind": "cluster_create_strategy",
        "value": runtime["cluster_create_strategy"],
    }
    if isinstance(runtime.get("cluster_create_parallelism"), int):
        treatment["bounded_parallelism"] = runtime["cluster_create_parallelism"]
    markers = {
        event["name"]: event["at_monotonic"]
        for event in timeline["events"]
        if event["name"] in M2.FORMATION_MARKERS
    }
    assert set(markers) == set(M2.FORMATION_MARKERS)
    trial.update(
        {
            "trial_id": partial_trial["trial_id"],
            "run_id": partial_trial["run_id"],
            "ownership_id": partial_trial["ownership_id"],
            "cell_id": "formation-discovery-transition-replay",
            "treatment": treatment,
            "monotonic_markers": markers,
            "derived_intervals": {
                "formation_seconds": (
                    markers["data_path_probe"] - markers["last_process_ping"]
                )
            },
            "resource_window": {
                "duration_seconds": original["duration_seconds"],
                **original["metrics"],
            },
        }
    )
    trial["provenance"]["invocation_run_id"] = case["invocation_run_id"]
    cell = {
        "cell_id": trial["cell_id"],
        "campaign_step": "discovery",
        "scale": trial["scale"],
        "failure_rate": "none",
        "required_pairs": 1,
        "candidate": treatment,
        "status": "FAIL",
    }
    source_report.update(
        {
            "campaign_id": case["invocation_run_id"],
            "invocation_run_id": case["invocation_run_id"],
            "status": "FAIL",
            "started_trial_ids": [trial["trial_id"]],
            "trials": [trial],
            "pairs": [],
            "cells": [cell],
            "source_refs": list(trial["source_sha256s"]),
            "errors": ["historical formation transition adapter"],
        }
    )
    paths = _write_valid_trial_sources(source_report, trial, tmp_path)

    adapted = _losslessly_intern_historical_resource(original)
    recomputed = M2.validate_and_aggregate_m2_resource_samples(
        adapted,
        allow_initial_membership_transitions=True,
    )
    assert recomputed["status"] == "PASS", recomputed["errors"]
    adapted["metrics"] = recomputed["metrics"]
    adapted["diagnostics"] = recomputed["diagnostics"]
    trial["resource_window"] = {
        "duration_seconds": adapted["duration_seconds"],
        **adapted["metrics"],
    }

    _rewrite_bound_source(
        source_report,
        trial,
        paths["state"],
        "state",
        state,
    )
    _rewrite_bound_source(
        source_report,
        trial,
        paths["timeline"],
        "timeline",
        timeline,
    )
    _rewrite_bound_source(
        source_report,
        trial,
        paths["resource"],
        "resource",
        adapted,
    )
    provenance = deepcopy(trial["provenance"])
    refs = {
        ref["category"]: ref
        for ref in trial["source_sha256s"]
    }
    provenance["capture_digest"] = M2._canonical_digest(
        {
            category: ref["sha256"]
            for category, ref in refs.items()
            if category != "provenance"
        }
    )
    trial["provenance"] = provenance
    _rewrite_bound_source(
        source_report,
        trial,
        paths["provenance"],
        "provenance",
        provenance,
    )
    return source_report, trial, cell


@pytest.mark.parametrize("run_id", ["29925711801", "29931564838"])
def test_historical_formation_transition_replays_through_source_gate(
    tmp_path: Path,
    run_id: str,
) -> None:
    report, trial, cell = _historical_formation_transition_source_report(
        tmp_path,
        run_id,
    )

    assert M2.validate_current_invocation_sources(
        report,
        artifacts_dir=tmp_path,
        allow_discovery_safety_rejections=True,
    ) == []

    trial["cell_id"] = "formation-soak-permission-negative"
    cell["cell_id"] = trial["cell_id"]
    errors = M2.validate_current_invocation_sources(
        report,
        artifacts_dir=tmp_path,
        allow_discovery_safety_rejections=True,
    )

    assert any(
        "resource metric cluster_link_errors is not raw-derived" in error
        for error in errors
    )


def _adapt_historical_formation_campaign(
    tmp_path: Path,
) -> dict[str, object]:
    case = _historical_gate_case("29916936241")
    assert _HISTORICAL_GATE_MANIFEST["replay_expectations"]["29916936241"][
        "adapter_expectation"
    ] == "FORMATION_CAMPAIGN_GATE_PASS"
    members, report = _verified_historical_report(case)
    _write_historical_members(members, tmp_path)
    formation = report["campaigns"]["formation"]
    current_product = M2._current_product_digest()

    for trial in formation["trials"]:
        refs = {
            ref["category"]: ref
            for ref in trial["source_sha256s"]
        }
        resource_path = tmp_path / refs["resource"]["path"]
        original_resource = json.loads(resource_path.read_text(encoding="utf-8"))
        resource = _losslessly_intern_historical_resource(original_resource)
        resource["metrics"]["cluster_link_errors"] = 0
        trial["resource_window"]["cluster_link_errors"] = 0
        _rewrite_bound_source(
            formation,
            trial,
            resource_path,
            "resource",
            resource,
        )

        workload_path = tmp_path / refs["workload"]["path"]
        workload = json.loads(workload_path.read_text(encoding="utf-8"))
        bucket_counts: dict[int, int] = {}
        for row in workload["latency_histogram"]:
            latency_ms = float(row["latency_ms"])
            tick = math.ceil(
                math.log2(latency_ms)
                * M2.LATENCY_HISTOGRAM_BUCKETS_PER_OCTAVE
                - 1e-12
            )
            bucket_index = tick - M2.LATENCY_HISTOGRAM_MIN_TICK
            bucket_counts[bucket_index] = (
                bucket_counts.get(bucket_index, 0) + int(row["count"])
            )
        workload["latency_histogram"] = {
            "schema_version": M2.LATENCY_HISTOGRAM_SCHEMA_VERSION,
            "buckets": [
                {"index": index, "count": count}
                for index, count in sorted(bucket_counts.items())
            ],
        }
        p99, _count, valid = M2._histogram_nearest_rank(
            workload["latency_histogram"],
            0.99,
        )
        assert valid and p99 is not None
        workload["p99_latency_ms"] = p99
        trial["workload"]["p99_latency_ms"] = p99
        _rewrite_bound_source(
            formation,
            trial,
            workload_path,
            "workload",
            workload,
        )

        provenance = deepcopy(trial["provenance"])
        provenance["product_digest"] = current_product
        trial["control_digests"]["product"] = current_product
        refs = {
            ref["category"]: ref
            for ref in trial["source_sha256s"]
        }
        provenance["capture_digest"] = M2._canonical_digest(
            {
                category: ref["sha256"]
                for category, ref in refs.items()
                if category != "provenance"
            }
        )
        trial["provenance"] = provenance
        _rewrite_bound_source(
            formation,
            trial,
            tmp_path / refs["provenance"]["path"],
            "provenance",
            provenance,
        )

    for pair in formation["pairs"]:
        pair["control_digests"]["product"] = current_product
    return formation


def test_historical_formation_campaign_replays_and_boundaries_fail_closed(
    tmp_path: Path,
) -> None:
    formation = _adapt_historical_formation_campaign(tmp_path)

    assert M2.validate_discovery_campaign(
        formation,
        expected_kind="formation",
        expected_invocation_run_id=formation["invocation_run_id"],
    ) == []
    assert M2.validate_current_invocation_sources(
        formation,
        artifacts_dir=tmp_path,
        allow_discovery_safety_rejections=True,
    ) == []

    trial = next(
        trial
        for trial in formation["trials"]
        if trial["cell_id"] == "formation-discovery-2"
        and trial["arm"] == "candidate"
    )
    trial["cell_id"] = "formation-soak-permission-negative"

    errors = M2.validate_current_invocation_sources(
        formation,
        artifacts_dir=tmp_path,
        allow_discovery_safety_rejections=True,
    )

    assert any(
        "resource metric cluster_link_errors is not raw-derived" in error
        for error in errors
    )
    trial["cell_id"] = "formation-discovery-2"

    trial = formation["trials"][0]
    refs = {
        ref["category"]: ref
        for ref in trial["source_sha256s"]
    }
    provenance = deepcopy(trial["provenance"])
    provenance["product_digest"] = "0" * 64
    trial["provenance"] = provenance
    trial["control_digests"]["product"] = "0" * 64
    _rewrite_bound_source(
        formation,
        trial,
        tmp_path / refs["provenance"]["path"],
        "provenance",
        provenance,
    )

    errors = M2.validate_current_invocation_sources(
        formation,
        artifacts_dir=tmp_path,
        allow_discovery_safety_rejections=True,
    )

    assert any(
        "provenance product digest does not match the current product tree" in error
        for error in errors
    )
    assert not any("sha256 does not match" in error for error in errors)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda report: report["trials"][0].pop("workload"), "missing required key 'workload'"),
        (lambda report: report["selected_candidate"].__setitem__("unbounded_fanout", True), "additional property not allowed"),
    ],
)
def test_referenced_schema_definitions_are_enforced(mutate, message: str) -> None:
    report = _formation_report()
    mutate(report)
    report["report_digest"] = M2.report_digest(report)

    assert any(message in error for error in M2.validate_report(report))


def test_every_started_trial_must_be_paired() -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][-1])
    trial["trial_id"] = "unpaired-trial"
    trial["pair_id"] = "unpaired-pair"
    trial["run_id"] = "m2-contract-unpaired-trial"
    trial["ownership_id"] = trial["run_id"]
    report["trials"].append(trial)
    report["started_trial_ids"].append(trial["trial_id"])
    report["report_digest"] = M2.report_digest(report)

    errors = M2.validate_report(report)

    assert "every started trial must be referenced by exactly one pair" in errors


def test_selected_candidate_must_win_formation_discovery() -> None:
    report = _formation_report()
    trial = next(
        trial
        for trial in report["trials"]
        if trial["cell_id"] == "discovery-2" and trial["arm"] == "candidate"
    )
    duration = 200.0
    trial["monotonic_markers"] = {
        name: duration * index / (len(M2.FORMATION_MARKERS) - 1)
        for index, name in enumerate(M2.FORMATION_MARKERS)
    }
    trial["derived_intervals"]["formation_seconds"] = duration
    report["report_digest"] = M2.report_digest(report)

    errors = M2.validate_report(report)

    assert "selected formation candidate did not beat baseline in discovery" in errors


def test_unexpected_cluster_event_and_control_mismatch_fail_closed() -> None:
    report = _formation_report()
    report["trials"][0]["correctness"]["unexpected_fail"] = 1
    report["trials"][1]["provenance"]["product_digest"] = "b" * 64
    report["report_digest"] = M2.report_digest(report)

    errors = M2.validate_report(report)

    assert any("nonzero unexpected_fail" in error for error in errors)
    assert any("product_digest does not match control product" in error for error in errors)


def test_missing_product_source_category_fails_closed() -> None:
    report = _formation_report()
    report["trials"][0]["source_sha256s"] = [
        ref
        for ref in report["trials"][0]["source_sha256s"]
        if ref["category"] != "command_log"
    ]
    report["report_digest"] = M2.report_digest(report)

    assert any("source categories must be exactly" in error for error in M2.validate_report(report))


def test_cleanup_source_is_parsed_and_bound_to_the_trial(tmp_path: Path) -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    report["trials"] = [trial]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    paths = _write_valid_trial_sources(report, trial, tmp_path)

    assert M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path) == []

    cleanup_path = paths["cleanup"]
    cleanup_document = json.loads(cleanup_path.read_text(encoding="utf-8"))
    cleanup_document["resources_remaining"] = [{"type": "owned-process"}]
    _rewrite_bound_source(report, trial, cleanup_path, "cleanup", cleanup_document)

    assert any(
        "reports residual resources" in error
        for error in M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)
    )


def test_bound_gzip_source_is_lossless_and_hashes_compressed_bytes(
    tmp_path: Path,
) -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    report["trials"] = [trial]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    source = paths["workload"]
    raw = source.read_bytes()
    compressed = source.with_name("workload.json.gz")
    with compressed.open("wb") as output:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=6,
            fileobj=output,
            mtime=0,
        ) as encoded:
            encoded.write(raw)
    source.unlink()

    digest = hashlib.sha256(compressed.read_bytes()).hexdigest()
    trial_ref = next(
        ref for ref in trial["source_sha256s"] if ref["category"] == "workload"
    )
    old_path = trial_ref["path"]
    trial_ref.update(
        {
            "path": compressed.relative_to(tmp_path).as_posix(),
            "sha256": digest,
        }
    )
    top_ref = next(
        ref
        for ref in report["source_refs"]
        if ref["category"] == "workload" and ref["path"] == old_path
    )
    top_ref.update({"path": trial_ref["path"], "sha256": digest})
    provenance = json.loads(paths["provenance"].read_text(encoding="utf-8"))
    provenance["capture_digest"] = M2._canonical_digest(
        {
            ref["category"]: ref["sha256"]
            for ref in trial["source_sha256s"]
            if ref["category"] != "provenance"
        }
    )
    trial["provenance"]["capture_digest"] = provenance["capture_digest"]
    _rewrite_bound_source(
        report,
        trial,
        paths["provenance"],
        "provenance",
        provenance,
    )

    assert M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path) == []
    tampered = bytearray(compressed.read_bytes())
    tampered[len(tampered) // 2] ^= 0x01
    compressed.write_bytes(tampered)
    assert any(
        "workload evidence is missing or not digest-bound" in error
        for error in M2.validate_current_invocation_sources(
            report,
            artifacts_dir=tmp_path,
        )
    )


@pytest.mark.parametrize(
    ("category", "mutate", "message"),
    [
        (
            "provenance",
            lambda value: value.__setitem__("product_digest", "b" * 64),
            "provenance source does not exactly match",
        ),
        (
            "timeline",
            lambda value: next(
                event for event in value["events"] if event["name"] == "data_path_probe"
            ).__setitem__("at_monotonic", 101.0),
            "marker data_path_probe does not match setup timeline source",
        ),
        (
            "timeline",
            lambda value: (
                value["segments"][1].__setitem__(
                    "start_monotonic", value["segments"][1]["start_monotonic"] + 0.5
                ),
                value["segments"][1].__setitem__(
                    "end_monotonic", value["segments"][1]["end_monotonic"] + 0.5
                ),
            ),
            "silent gap",
        ),
        (
            "timeline",
            lambda value: value["setup_command_wall_source"].__setitem__(
                "started_at_monotonic", -1.0
            ),
            "not bounded by the observed monotonic wrapper",
        ),
        (
            "resource",
            lambda value: value["metrics"].__setitem__("peak_rss_bytes", 101.0),
            "resource metric peak_rss_bytes is not raw-derived",
        ),
        (
            "resource",
            lambda value: value["coverage"].__setitem__("complete", False),
            "resource source coverage is incomplete",
        ),
        (
            "resource",
            lambda value: value["samples"][0]["nodehosts"][0]["processes"][0].pop(
                "non_connected_cluster_links"
            ),
            "raw resource samples are incomplete or invalid",
        ),
        (
            "resource",
            lambda value: value["samples"][0]["nodehosts"][0]["processes"][0].__setitem__(
                "cluster_link_errors", 1
            ),
            "raw resource samples are incomplete or invalid",
        ),
        (
            "resource",
            lambda value: value["ownership"]["pids"].pop(),
            "resource ownership is not bound to the runtime state",
        ),
        (
            "state",
            lambda value: value["runtime"].__setitem__("cluster_create_strategy", "not-the-treatment"),
            "state does not bind the cluster-create treatment",
        ),
        (
            "attempt",
            lambda value: value.__setitem__("status", "STARTED"),
            "attempt evidence does not bind the completed owned run",
        ),
        (
            "workload",
            lambda value: value.__setitem__("set_throughput_ops_per_second", 99.0),
            "workload metric set_throughput_ops_per_second does not match",
        ),
        (
            "topology",
            lambda value: value["probes"][0].__setitem__("cluster_slots_ok", 16000),
            "correctness clean_topology is not derived from raw topology probes",
        ),
        (
            "topology",
            lambda value: value.__setitem__("versions", ["9.1.99"]),
            "topology versions do not match provenance",
        ),
        (
            "command_log",
            lambda value: value.__setitem__("run_id", "different-owned-run"),
            "is not owned by the trial run",
        ),
        (
            "command_log",
            lambda value: value.pop("ended_at_monotonic_ms"),
            "lacks complete monotonic bounds",
        ),
    ],
)
def test_raw_source_summary_tampering_is_rejected(
    tmp_path: Path,
    category: str,
    mutate,
    message: str,
) -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    report["trials"] = [trial]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    value = json.loads(paths[category].read_text(encoding="utf-8"))
    mutate(value)
    _rewrite_bound_source(report, trial, paths[category], category, value)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any(message in error for error in errors)


def test_raw_resource_source_accepts_pre_establishment_handshake_transient(tmp_path: Path) -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    report["trials"] = [trial]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    resource = json.loads(paths["resource"].read_text(encoding="utf-8"))
    resource["samples"][0]["nodehosts"][0]["processes"][0][
        "non_connected_cluster_links"
    ] = [
        {
            "node_id": "a" * 40,
            "address": "127.0.0.1:7201@17201",
            "flags": ["handshake"],
            "master_id": "-",
            "link_state": "disconnected",
        }
    ]
    resource["samples"][0]["nodehosts"][0]["processes"][0][
        "non_connected_cluster_link_count"
    ] = 1
    _rewrite_bound_source(report, trial, paths["resource"], "resource", resource)
    refs = {ref["category"]: ref for ref in trial["source_sha256s"]}
    trial["provenance"]["capture_digest"] = M2._canonical_digest(
        {
            category: ref["sha256"]
            for category, ref in refs.items()
            if category != "provenance"
        }
    )
    _rewrite_bound_source(
        report,
        trial,
        paths["provenance"],
        "provenance",
        trial["provenance"],
    )

    assert M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path) == []


@pytest.mark.parametrize(
    "damage",
    [
        "inline",
        "missing_ref",
        "missing_entry",
        "missing_dictionary",
        "tampered_entry",
        "nonfinite_entry",
        "unreferenced_entry",
        "duplicate_entry",
    ],
)
def test_resource_directional_links_dictionary_fails_closed(
    tmp_path: Path,
    damage: str,
) -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    report["trials"] = [trial]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    resource = json.loads(paths["resource"].read_text(encoding="utf-8"))
    process = resource["samples"][0]["nodehosts"][0]["processes"][0]
    first_ref = process["directional_cluster_links_sha256"]
    first_entry = next(
        entry
        for entry in resource["directional_cluster_links_dictionary"]
        if entry["sha256"] == first_ref
    )
    link = {
        "direction": "to",
        "node_id": "a" * 40,
        "create_time": 1000,
        "events": "r",
        "send_buffer_allocated": 0,
        "send_buffer_used": 0,
    }
    if damage == "inline":
        process["directional_cluster_links"] = deepcopy(
            first_entry["directional_cluster_links"]
        )
    elif damage == "missing_ref":
        process.pop("directional_cluster_links_sha256")
    elif damage == "missing_entry":
        resource["directional_cluster_links_dictionary"].remove(first_entry)
    elif damage == "missing_dictionary":
        resource.pop("directional_cluster_links_dictionary")
    elif damage == "tampered_entry":
        first_entry["directional_cluster_links"].append(link)
    elif damage == "nonfinite_entry":
        first_entry["directional_cluster_links"].append(
            {**link, "send_buffer_used": float("nan")}
        )
    elif damage == "unreferenced_entry":
        extra_links = [link]
        resource["directional_cluster_links_dictionary"].append(
            {
                "sha256": M2._canonical_digest(extra_links),
                "directional_cluster_links": extra_links,
            }
        )
    else:
        resource["directional_cluster_links_dictionary"].append(
            deepcopy(first_entry)
        )
    _rewrite_bound_source(
        report,
        trial,
        paths["resource"],
        "resource",
        resource,
    )

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any(
        "resource directional CLUSTER LINKS" in error
        or "process contains inline directional CLUSTER LINKS" in error
        or "process directional CLUSTER LINKS reference" in error
        for error in errors
    )


@pytest.mark.parametrize(
    "transition_phase",
    [
        pytest.param("formation_bootstrap", id="event-between-samples"),
        pytest.param("formation_boundary", id="event-during-transition-sample"),
    ],
)
def test_formation_resource_contract_accepts_raw_proven_bootstrap_reconnect(
    tmp_path: Path,
    transition_phase: str,
) -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    report["trials"] = [trial]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    resource = json.loads(paths["resource"].read_text(encoding="utf-8"))
    _expand_resource_directional_links(resource)
    duration = float(resource["duration_seconds"])
    midpoint = duration / 2.0
    previous, recovered = resource["samples"]
    current = deepcopy(previous)
    resource["samples"] = [previous, current, recovered]
    resource["window_name"] = "m2-formation-bootstrap"
    resource["interval_seconds"] = midpoint

    for index, (sample, offset, sample_marker) in enumerate(
        zip(
            resource["samples"],
            (0.0, midpoint, duration),
            ("formation_bootstrap", transition_phase, "post_formation"),
        )
    ):
        sample["sample_index"] = index
        sample["scheduled_offset_seconds"] = offset
        sample["timestamp_unix_ms"] = 1_700_000_000_000 + int(offset * 1000)
        sample["scheduled_at_monotonic_seconds"] = offset
        sample["started_at_monotonic_seconds"] = offset
        sample["ended_at_monotonic_seconds"] = offset
        sample["sample_phase"] = sample_marker

    process_count = len(resource["samples"][0]["nodehosts"][0]["processes"])
    node_ids = [f"{index + 1:040x}" for index in range(process_count)]
    peer_id = node_ids[1]

    def directional(node_id: str, direction: str, create_time: int) -> dict[str, object]:
        return {
            "direction": direction,
            "node_id": node_id,
            "create_time": create_time,
            "events": "r",
            "send_buffer_allocated": 0,
            "send_buffer_used": 0,
        }

    for sample in resource["samples"]:
        for process_index, process in enumerate(sample["nodehosts"][0]["processes"]):
            process["cluster_link_count"] = process_count
            process["directional_cluster_links"] = [
                directional(node_id, direction, 1000)
                for peer_index, node_id in enumerate(node_ids)
                if peer_index != process_index
                for direction in ("to", "from")
            ]

    observed_processes = [sample["nodehosts"][0]["processes"][0] for sample in resource["samples"]]
    observed_processes[1].update(
        {
            "cluster_link_errors": 1,
            "non_connected_cluster_link_count": 1,
            "non_connected_cluster_links": [
                {
                    "node_id": peer_id,
                    "address": "127.0.0.1:7201@17201",
                    "flags": ["master"],
                    "master_id": "-",
                    "link_state": "disconnected",
                }
            ],
            "directional_cluster_links": [
                directional(
                    node_id,
                    direction,
                    2000 if node_id == peer_id and direction == "to" else 1000,
                )
                for peer_index, node_id in enumerate(node_ids)
                if peer_index != 0
                for direction in ("to", "from")
            ],
        }
    )
    observed_processes[2]["directional_cluster_links"] = [
        directional(
            node_id,
            direction,
            2000 if node_id == peer_id and direction == "to" else 1000,
        )
        for peer_index, node_id in enumerate(node_ids)
        if peer_index != 0
        for direction in ("to", "from")
    ]
    resource["coverage"].update(
        {
            "expected_sample_count": 3,
            "observed_sample_count": 3,
            "sample_timestamps_unix_ms": [
                sample["timestamp_unix_ms"] for sample in resource["samples"]
            ],
            "sample_monotonic_seconds": [
                sample["started_at_monotonic_seconds"] for sample in resource["samples"]
            ],
            "scheduled_offsets_seconds": [
                sample["scheduled_offset_seconds"] for sample in resource["samples"]
            ],
            "actual_window_start_monotonic_seconds": 0.0,
            "actual_window_end_monotonic_seconds": duration,
            "actual_window_span_seconds": duration,
            "sampling_envelope_end_monotonic_seconds": duration,
            "sampling_envelope_span_seconds": duration,
            "max_schedule_lag_seconds": 0.0,
            "max_sample_collection_seconds": 0.0,
        }
    )

    verdict = M2.validate_and_aggregate_m2_resource_samples(
        resource,
        allow_initial_membership_transitions=True,
    )

    assert verdict["status"] == "PASS", verdict["errors"]
    assert verdict["metrics"]["cluster_link_errors"] == 0
    missing_post_formation = deepcopy(resource)
    for sample, sample_phase in zip(
        missing_post_formation["samples"],
        ("formation_bootstrap", "formation_bootstrap", "formation_boundary"),
    ):
        sample["sample_phase"] = sample_phase
    missing_post_formation_verdict = M2.validate_and_aggregate_m2_resource_samples(
        missing_post_formation,
        allow_initial_membership_transitions=True,
    )
    assert missing_post_formation_verdict["status"] == "FAIL"
    assert any(
        "never reached a complete post-formation boundary" in error
        for error in missing_post_formation_verdict["errors"]
    )
    resource["metrics"] = verdict["metrics"]
    resource["diagnostics"] = verdict["diagnostics"]
    trial["resource_window"].update(verdict["metrics"])
    _intern_resource_directional_links(resource)
    _rewrite_bound_source(report, trial, paths["resource"], "resource", resource)
    refs = {ref["category"]: ref for ref in trial["source_sha256s"]}
    trial["provenance"]["capture_digest"] = M2._canonical_digest(
        {
            category: ref["sha256"]
            for category, ref in refs.items()
            if category != "provenance"
        }
    )
    _rewrite_bound_source(
        report,
        trial,
        paths["provenance"],
        "provenance",
        trial["provenance"],
    )

    assert M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path) == []


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["probes"][0]["cluster_nodes"]["node-000"]["flags"].remove("myself"),
            "logical-to-Valkey identity mapping is incomplete",
        ),
        (
            lambda value: (
                value["probes"][0]["cluster_nodes"]["node-025"].__setitem__("flags", ["master"]),
                value["probes"][0]["cluster_nodes"]["node-025"].__setitem__("role", "primary"),
            ),
            "observed roles do not match topology_control",
        ),
        (
            lambda value: value["probes"][0]["cluster_nodes"]["node-001"].__setitem__(
                "slots",
                value["probes"][0]["cluster_nodes"]["node-000"]["slots"],
            ),
            "correctness split_brain is not derived from raw topology probes",
        ),
        (
            lambda value: value["probes"][0]["cluster_nodes"]["node-001"]["flags"].append("pfail"),
            "correctness unexpected_pfail is not derived from raw topology probes",
        ),
        (
            lambda value: value["probes"][0]["cluster_nodes"]["node-001"].__setitem__(
                "link_state", "disconnected"
            ),
            "raw topology has a disconnected cluster link",
        ),
    ],
)
def test_topology_identity_roles_and_slots_are_rebuilt_from_raw_probes(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    report["trials"] = [trial]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    topology = json.loads(paths["topology"].read_text(encoding="utf-8"))
    mutate(topology)
    _rewrite_bound_source(report, trial, paths["topology"], "topology", topology)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any(message in error for error in errors)


def test_stability_baseline_roles_are_bound_to_pre_window_raw_topology(tmp_path: Path) -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    trial["cell_id"] = "stability-bootstrap"
    report["trials"] = [trial]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    paths = _write_valid_trial_sources(report, trial, tmp_path)

    assert M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path) == []

    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    workload["stability_observation"]["baseline_roles"]["node-025"] = "primary"
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("stability baseline roles do not match the pre-window raw topology" in error for error in errors)


def test_empty_raw_source_fails_closed_even_with_matching_digest(tmp_path: Path) -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    report["trials"] = [trial]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    _rewrite_bound_source(report, trial, paths["topology"], "topology", {})

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("topology evidence must contain a non-empty JSON object" in error for error in errors)


def test_steady_workload_histogram_must_measure_set_latency(tmp_path: Path) -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    report["trials"] = [trial]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    workload["latency_operation"] = "SET_GET_PAIR"
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("histogram is not identified as SET latency" in error for error in errors)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda histogram: histogram.update(
            {"schema_version": "unknown-histogram-schema"}
        ),
        lambda histogram: histogram.__setitem__(
            "buckets",
            [{"latency_ms": 1.234567, "count": 12000}],
        ),
        lambda histogram: histogram["buckets"][0].__setitem__(
            "index",
            M2.LATENCY_HISTOGRAM_MAX_INDEX + 1,
        ),
        lambda histogram: histogram["buckets"][0].__setitem__("index", 1.0),
        lambda histogram: histogram.__setitem__(
            "buckets",
            [
                {"index": M2._latency_bucket_index_from_upper(1.0), "count": 6000},
                {"index": M2._latency_bucket_index_from_upper(1.0), "count": 6000},
            ],
        ),
        lambda histogram: histogram.__setitem__(
            "buckets",
            [
                {"index": M2._latency_bucket_index_from_upper(2.0), "count": 6000},
                {"index": M2._latency_bucket_index_from_upper(1.0), "count": 6000},
            ],
        ),
        lambda histogram: histogram.__setitem__(
            "buckets",
            [
                {"index": index, "count": 1}
                for index in range(M2.LATENCY_HISTOGRAM_BUCKET_LIMIT + 1)
            ],
        ),
    ],
)
def test_steady_workload_rejects_invalid_histogram_schema_and_buckets(
    tmp_path: Path,
    mutate,
) -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    report["trials"] = [trial]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    mutate(workload["latency_histogram"])
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("latency histogram bins are invalid" in error for error in errors)


def test_steady_workload_p99_is_recomputed_from_histogram(
    tmp_path: Path,
) -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    report["trials"] = [trial]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    workload["latency_histogram"] = {
        "schema_version": M2.LATENCY_HISTOGRAM_SCHEMA_VERSION,
        "buckets": [
            {
                "index": M2._latency_bucket_index_from_upper(1.0),
                "count": 11879,
            },
            {
                "index": M2._latency_bucket_index_from_upper(2.0),
                "count": 121,
            },
        ],
    }
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("steady workload throughput or p99 is not raw-derived" in error for error in errors)


def test_pair_source_validation_rejects_unequal_actual_resource_windows(tmp_path: Path) -> None:
    report = _formation_report()
    pair = deepcopy(report["pairs"][0])
    trial_ids = {pair["baseline_trial_id"], pair["candidate_trial_id"]}
    report["trials"] = [
        deepcopy(trial)
        for trial in report["trials"]
        if trial["trial_id"] in trial_ids
    ]
    report["pairs"] = [pair]
    roots = {str(trial["evidence_root"]) for trial in report["trials"]}
    report["source_refs"] = [
        ref
        for ref in report["source_refs"]
        if any(str(ref["path"]).startswith(f"{root}/") for root in roots)
    ]
    paths_by_arm = {
        str(trial["arm"]): _write_valid_trial_sources(report, trial, tmp_path)
        for trial in report["trials"]
    }

    for arm, final_start in (("baseline", 119.5), ("candidate", 120.5)):
        trial = next(value for value in report["trials"] if value["arm"] == arm)
        path = paths_by_arm[arm]["resource"]
        resource = json.loads(path.read_text(encoding="utf-8"))
        final_sample = resource["samples"][-1]
        final_sample["started_at_monotonic_seconds"] = final_start
        final_sample["ended_at_monotonic_seconds"] = final_start
        final_sample["schedule_lag_seconds"] = max(final_start - 120.0, 0.0)
        coverage = resource["coverage"]
        coverage["sample_monotonic_seconds"][-1] = final_start
        coverage["actual_window_end_monotonic_seconds"] = final_start
        coverage["actual_window_span_seconds"] = final_start
        coverage["sampling_envelope_end_monotonic_seconds"] = final_start
        coverage["sampling_envelope_span_seconds"] = final_start
        coverage["max_schedule_lag_seconds"] = max(final_start - 120.0, 0.0)
        _rewrite_bound_source(report, trial, path, "resource", resource)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("resource windows have unequal actual_window_span_seconds" in error for error in errors)


def test_discovery_source_validation_preserves_candidate_safety_rejection(tmp_path: Path) -> None:
    report = _formation_discovery_campaign()
    cell = next(cell for cell in report["cells"] if cell["status"] == "PASS")
    pair = deepcopy(next(pair for pair in report["pairs"] if pair["cell_id"] == cell["cell_id"]))
    trial_ids = {pair["baseline_trial_id"], pair["candidate_trial_id"]}
    report["trials"] = [
        deepcopy(trial)
        for trial in report["trials"]
        if trial["trial_id"] in trial_ids
    ]
    report["pairs"] = [pair]
    report["cells"] = [cell]
    roots = {str(trial["evidence_root"]) for trial in report["trials"]}
    report["source_refs"] = [
        ref
        for ref in report["source_refs"]
        if any(str(ref["path"]).startswith(f"{root}/") for root in roots)
    ]
    paths_by_arm = {
        str(trial["arm"]): _write_valid_trial_sources(report, trial, tmp_path)
        for trial in report["trials"]
    }
    candidate = next(trial for trial in report["trials"] if trial["arm"] == "candidate")
    resource_path = paths_by_arm["candidate"]["resource"]
    resource = json.loads(resource_path.read_text(encoding="utf-8"))
    process = resource["samples"][0]["nodehosts"][0]["processes"][0]
    process["cluster_link_errors"] = 1
    process["non_connected_cluster_link_count"] = 1
    process["non_connected_cluster_links"] = [
        {
            "node_id": "b" * 40,
            "address": "127.0.0.1:7201@17201",
            "flags": ["master"],
            "master_id": "-",
            "link_state": "disconnected",
        }
    ]
    resource["metrics"]["cluster_link_errors"] = 1
    candidate["resource_window"]["cluster_link_errors"] = 1
    cell["status"] = "FAIL"
    _rewrite_bound_source(report, candidate, resource_path, "resource", resource)
    refs = {ref["category"]: ref for ref in candidate["source_sha256s"]}
    candidate["provenance"]["capture_digest"] = M2._canonical_digest(
        {
            category: ref["sha256"]
            for category, ref in refs.items()
            if category != "provenance"
        }
    )
    _rewrite_bound_source(
        report,
        candidate,
        paths_by_arm["candidate"]["provenance"],
        "provenance",
        candidate["provenance"],
    )
    report["source_refs"] = list(
        {
            (ref["category"], ref["sha256"]): ref
            for ref in report["source_refs"]
        }.values()
    )

    assert any(
        "candidate metric cluster_link_errors must be zero" in error
        for error in M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)
    )
    errors = M2.validate_current_invocation_sources(
        report,
        artifacts_dir=tmp_path,
        allow_discovery_safety_rejections=True,
    )
    assert not any(
        "candidate metric cluster_link_errors must be zero" in error
        for error in errors
    )


def test_fault_raw_source_binds_markers_intervals_stability_and_sigkill_targets(
    tmp_path: Path,
) -> None:
    report, trial = _fault_source_report()

    paths = _write_valid_trial_sources(report, trial, tmp_path)

    assert M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path) == []
    assert {
        "observer_rounds",
        "topology_view_dictionary",
        "every_node_convergence_views_sha256",
        "initial_roles",
        "node_shards",
    }.isdisjoint(trial["fault"])
    fault_document = json.loads(paths["fault"].read_text(encoding="utf-8"))
    assert fault_document["observer_rounds"]
    assert fault_document["topology_view_dictionary"]
    assert fault_document["every_node_convergence_views_sha256"]
    assert len(fault_document["observer_rounds"]) == 6
    assert len(fault_document["topology_view_dictionary"]) < 7


@pytest.mark.parametrize("master_id", ["MISSING", "node-002"])
def test_fault_gate_rejects_missing_or_cross_shard_replica_master(
    tmp_path: Path,
    master_id: str,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    fault = json.loads(paths["fault"].read_text(encoding="utf-8"))
    convergence_ref = fault["every_node_convergence_views_sha256"]
    replica = _fault_convergence_views(fault)[0]["cluster_nodes"]["node-026"]
    if master_id == "MISSING":
        del replica["master_id"]
    else:
        replica["master_id"] = master_id
    _rebind_fault_view_entry(fault, convergence_ref)
    _rewrite_bound_source(report, trial, paths["fault"], "fault", fault)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any(
        "every-node convergence" in error or "compact raw views" in error
        for error in errors
    )


@pytest.mark.parametrize(
    "damage",
    [
        "inline",
        "missing_ref",
        "missing_entry",
        "missing_dictionary",
        "tampered_entry",
        "nonfinite_entry",
        "unreferenced_entry",
        "duplicate_entry",
    ],
)
def test_fault_topology_view_dictionary_fails_closed(
    tmp_path: Path,
    damage: str,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    fault = json.loads(paths["fault"].read_text(encoding="utf-8"))
    first_ref = fault["observer_rounds"][0]["views_sha256"]
    first_entry = next(
        entry
        for entry in fault["topology_view_dictionary"]
        if entry["sha256"] == first_ref
    )
    if damage == "inline":
        fault["observer_rounds"][0]["views"] = deepcopy(first_entry["views"])
    elif damage == "missing_ref":
        fault["observer_rounds"][0].pop("views_sha256")
    elif damage == "missing_entry":
        fault["topology_view_dictionary"].remove(first_entry)
    elif damage == "missing_dictionary":
        fault.pop("topology_view_dictionary")
    elif damage == "tampered_entry":
        first_entry["views"][0]["status"] = "FAIL"
    elif damage == "nonfinite_entry":
        first_entry["views"][0]["cluster_slots_ok"] = float("nan")
    elif damage == "unreferenced_entry":
        extra_views = deepcopy(first_entry["views"])
        extra_views[0]["status"] = "FAIL"
        fault["topology_view_dictionary"].append(
            {
                "sha256": M2._canonical_digest(extra_views),
                "views": extra_views,
            }
        )
    else:
        fault["topology_view_dictionary"].append(deepcopy(first_entry))
    _rewrite_bound_source(report, trial, paths["fault"], "fault", fault)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any(
        "topology view dictionary" in error
        or "topology view reference" in error
        or "inline topology views" in error
        for error in errors
    )


@pytest.mark.parametrize("tamper_side", ["summary", "raw_source"])
def test_fault_compact_summary_tampering_fails_closed(
    tmp_path: Path,
    tamper_side: str,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    if tamper_side == "summary":
        trial["fault"]["failed_primary_count"] = 2
    else:
        fault = json.loads(paths["fault"].read_text(encoding="utf-8"))
        fault["failed_primary_count"] = 2
        _rewrite_bound_source(report, trial, paths["fault"], "fault", fault)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any(
        "fault summary is not the compact raw-derived projection" in error
        for error in errors
    )


def test_fault_resource_window_is_bound_to_the_sigkill_barrier(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    resource = json.loads(paths["resource"].read_text(encoding="utf-8"))
    resource["samples"][1]["started_at_monotonic_seconds"] = 199.5
    resource["coverage"]["sample_monotonic_seconds"][1] = 199.5
    _rewrite_bound_source(report, trial, paths["resource"], "resource", resource)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("resource window is not synchronized to the SIGKILL barrier" in error for error in errors)


def test_fault_command_source_rejects_coordinated_failover(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    command = json.loads(paths["command_log"].read_text(encoding="utf-8"))
    command["argv"] = ["valkey-cli", "CLUSTER", "FAILOVER", "TAKEOVER"]
    command["command_kind"] = "cluster_failover"
    _rewrite_bound_source(report, trial, paths["command_log"], "command_log", command)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("uses FAILOVER, FORCE, or TAKEOVER" in error for error in errors)


def test_empty_command_source_fails_closed() -> None:
    errors: list[str] = []

    M2._validate_command_source(
        [],
        {"trial_id": "empty-command-log", "run_id": "empty-command-log"},
        fault_trial=False,
        errors=errors,
    )

    assert errors == ["trial empty-command-log command source is empty"]


def test_fault_sigkill_command_batch_is_bound_to_owned_targets(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    fault = json.loads(paths["fault"].read_text(encoding="utf-8"))
    fault["command_batches"][0]["argv"][-1] = "10001"
    _rewrite_bound_source(report, trial, paths["fault"], "fault", fault)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("SIGKILL command batches are not bound" in error for error in errors)


def test_fault_sigkill_gate_rejects_shell_argv_tampering(
    tmp_path: Path,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    fault = json.loads(paths["fault"].read_text(encoding="utf-8"))
    fault["command_batches"][0]["argv"][2] = "bash"
    fault["commands"] = [
        M2.shlex.join(["docker", *fault["command_batches"][0]["argv"]])
    ]
    _rewrite_bound_source(report, trial, paths["fault"], "fault", fault)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("SIGKILL command batches are not bound" in error for error in errors)


def test_fault_sigkill_barrier_span_is_recomputed_from_raw_target_times(
    tmp_path: Path,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    fault = json.loads(paths["fault"].read_text(encoding="utf-8"))
    fault["targets"][0]["signal_completed_at_monotonic_ms"] = 201000.0
    fault["targets"][0]["process_gone_at_monotonic_ms"] = 201001.0
    fault["monotonic_markers"]["all_processes_gone"] = 201.001
    report["trials"][0]["monotonic_markers"]["all_processes_gone"] = 201.001
    _rewrite_bound_source(report, trial, paths["fault"], "fault", fault)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any(
        "SIGKILL barrier span is not raw-derived or exceeds 500 ms" in error
        for error in errors
    )


def test_fault_sigkill_gate_rejects_run_29992169655_direct_kill_argv(
    tmp_path: Path,
) -> None:
    case = next(
        row
        for row in _HISTORICAL_GATE_CASES
        if row["source_run_id"] == "29992169655"
    )
    members = _historical_gate_bundle_members(case)
    source = case["failure_sources"]["fault"]
    recorded_fault = json.loads(members[source["path"]])
    recorded = recorded_fault["command_batches"][0]
    assert recorded["argv"][2] == "kill"
    assert "exit=127" in recorded["error"]

    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    fault = json.loads(paths["fault"].read_text(encoding="utf-8"))
    direct_argv = list(recorded["argv"])
    direct_argv[1] = fault["command_batches"][0]["container_id"]
    direct_argv[-1] = str(fault["command_batches"][0]["pids"][0])
    fault["command_batches"][0]["argv"] = direct_argv
    fault["commands"] = [
        M2.shlex.join(["docker", *fault["command_batches"][0]["argv"]])
    ]
    _rewrite_bound_source(report, trial, paths["fault"], "fault", fault)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("SIGKILL command batches are not bound" in error for error in errors)


def test_fault_marker_tampering_is_rejected_after_digest_refresh(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    fault = json.loads(paths["fault"].read_text(encoding="utf-8"))
    fault["monotonic_markers"]["first_pfail"] = 201.5
    _rewrite_bound_source(report, trial, paths["fault"], "fault", fault)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("fault marker first_pfail does not match its source" in error for error in errors)


def test_fault_stable_shard_source_must_match_trial_summary(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    workload["stable_shards"] = []
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("workload field stable_shards does not match its summary" in error for error in errors)


def test_fault_client_cadence_is_recomputed_from_attempt_timestamps(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    affected = next(row for row in workload["client_series"] if row["affected"] is True)
    _retime_fault_attempt(affected["attempts"][5], 200.65)
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("cadence is missing, exceeds 100 ms, or is not raw-derived" in error for error in errors)


@pytest.mark.parametrize(
    "duplicate_field",
    [
        "attempt_started_monotonic",
        "successful_pair_latencies_ms",
        "samples_through_stable_endpoint",
    ],
)
def test_fault_client_gate_rejects_duplicate_raw_views(
    tmp_path: Path,
    duplicate_field: str,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    affected = next(row for row in workload["client_series"] if row["affected"] is True)
    affected[duplicate_field] = []
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("raw attempts or summaries are inconsistent" in error for error in errors)


def test_run_29997723777_cadence_slice_is_rejected_by_gate_recomputation(
    tmp_path: Path,
) -> None:
    case = next(
        row
        for row in _HISTORICAL_GATE_CASES
        if row["source_run_id"] == "29997723777"
    )
    members = _historical_gate_bundle_members(case)
    source = case["failure_sources"]["workload"]
    historical_workload = json.loads(members[source["path"]])
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))

    for affected in (True, False):
        series = next(row for row in workload["client_series"] if row["affected"] is affected)
        starts = [
            float(attempt["started_at_monotonic"])
            for attempt in series["attempts"]
        ]
        historical_series = next(
            row
            for row in historical_workload["client_series"]
            if row["affected"] is affected
        )
        historical_starts = historical_series["attempt_started_monotonic"]
        historical_gap = max(
            right - left
            for left, right in zip(historical_starts, historical_starts[1:])
        )
        insertion = 6
        original_gap = starts[insertion] - starts[insertion - 1]
        shift = historical_gap - original_gap
        for index in range(insertion, len(starts)):
            next_start = round(starts[index] + shift, 6)
            _retime_fault_attempt(series["attempts"][index], next_start)

    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any(
        "affected shard shard-000 cadence is missing, exceeds 100 ms, or is not raw-derived"
        in error
        for error in errors
    )
    assert any(
        "unaffected control shard shard-control cadence is missing, exceeds 100 ms, or is not raw-derived"
        in error
        for error in errors
    )


@pytest.mark.parametrize("defect", ["missing", "out_of_order", "duplicate"])
def test_fault_client_attempt_timestamps_must_be_complete_and_strictly_increasing(
    tmp_path: Path,
    defect: str,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    affected = next(row for row in workload["client_series"] if row["affected"] is True)
    if defect == "missing":
        affected["attempts"][5]["started_at_monotonic"] = None
    elif defect == "out_of_order":
        affected["attempts"][5], affected["attempts"][6] = (
            affected["attempts"][6],
            affected["attempts"][5],
        )
    else:
        _retime_fault_attempt(
            affected["attempts"][6],
            float(affected["attempts"][5]["started_at_monotonic"]),
        )
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("affected shard shard-000 has an incomplete attempt series" in error for error in errors)


def test_fault_workload_error_count_must_include_measurement_failures(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    workload["errors"].append(
        "affected/control SET/GET attempt cadence exceeded 100 ms or was incomplete"
    )
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("workload error count does not match its summary" in error for error in errors)


def test_fault_workload_latency_is_recomputed_from_raw_attempt_timing(
    tmp_path: Path,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    affected = next(row for row in workload["client_series"] if row["affected"] is True)
    affected["attempts"][1]["latency_ms"] = 999999.0
    workload["p99_latency_ms"] = 999999.0
    trial["workload"]["p99_latency_ms"] = 999999.0
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("raw attempts or summaries are inconsistent" in error for error in errors)


def test_fault_workload_result_counts_are_recomputed_from_raw_attempts(
    tmp_path: Path,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    affected = next(row for row in workload["client_series"] if row["affected"] is True)
    affected.update(
        {
            "set_success_count": 0,
            "get_success_count": 0,
            "error_count": 999,
            "timeout_count": 999,
        }
    )
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("raw attempts or summaries are inconsistent" in error for error in errors)


@pytest.mark.parametrize("metric", ["throughput", "errors", "timeouts"])
def test_fault_workload_aggregates_are_recomputed_from_raw_attempts(
    tmp_path: Path,
    metric: str,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    if metric == "throughput":
        workload["set_throughput_ops_per_second"] = 999.0
        trial["workload"]["set_throughput_ops_per_second"] = 999.0
    elif metric == "errors":
        workload["errors"] = ["forged recovery error"]
    else:
        workload["timeout_count"] = 999
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any(
        "fault workload throughput, p99, errors, or timeouts are not raw-derived"
        in error
        for error in errors
    )


def test_fault_client_gate_retains_post_window_raw_attempt_without_counting_it(
    tmp_path: Path,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    window_end = (
        float(trial["monotonic_markers"]["sigkill_barrier"])
        + float(workload["requested_duration_seconds"])
    )
    for series in workload["client_series"]:
        post_window = deepcopy(series["attempts"][-1])
        _retime_fault_attempt(post_window, window_end + 0.05)
        series["attempts"].append(post_window)
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)
    refs = {ref["category"]: ref for ref in trial["source_sha256s"]}
    trial["provenance"]["capture_digest"] = M2._canonical_digest(
        {
            category: ref["sha256"]
            for category, ref in refs.items()
            if category != "provenance"
        }
    )
    _rewrite_bound_source(
        report,
        trial,
        paths["provenance"],
        "provenance",
        trial["provenance"],
    )

    assert M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path) == []

    for series in workload["client_series"]:
        series["attempt_count"] += 1
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)
    trial["provenance"]["capture_digest"] = M2._canonical_digest(
        {
            category: ref["sha256"]
            for category, ref in refs.items()
            if category != "provenance"
        }
    )
    _rewrite_bound_source(
        report,
        trial,
        paths["provenance"],
        "provenance",
        trial["provenance"],
    )
    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)
    assert any("raw attempts or summaries are inconsistent" in error for error in errors)


def test_fault_client_gate_clips_cross_boundary_intervals_to_the_closed_window(
    tmp_path: Path,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    barrier = float(trial["monotonic_markers"]["sigkill_barrier"])
    window_end = barrier + float(workload["requested_duration_seconds"])

    for series in workload["client_series"]:
        before = deepcopy(series["attempts"][0])
        _retime_fault_attempt(before, barrier - 0.09)
        _retime_fault_attempt(series["attempts"][0], barrier + 0.02)
        after = deepcopy(series["attempts"][-1])
        _retime_fault_attempt(series["attempts"][-1], window_end - 0.02)
        _retime_fault_attempt(after, window_end + 0.09)
        series["attempts"] = [before, *series["attempts"], after]

    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)
    refs = {ref["category"]: ref for ref in trial["source_sha256s"]}
    trial["provenance"]["capture_digest"] = M2._canonical_digest(
        {
            category: ref["sha256"]
            for category, ref in refs.items()
            if category != "provenance"
        }
    )
    _rewrite_bound_source(
        report,
        trial,
        paths["provenance"],
        "provenance",
        trial["provenance"],
    )

    assert all(
        len(series["attempts"]) == series["attempt_count"] + 2
        for series in workload["client_series"]
    )
    assert M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path) == []


@pytest.mark.parametrize("outside_boundary", ["before", "after"])
def test_fault_client_outside_boundary_timestamp_cannot_hide_a_window_edge_gap(
    tmp_path: Path,
    outside_boundary: str,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    barrier = float(trial["monotonic_markers"]["sigkill_barrier"])
    window_end = barrier + float(workload["requested_duration_seconds"])
    affected = next(row for row in workload["client_series"] if row["affected"] is True)
    if outside_boundary == "before":
        _retime_fault_attempt(affected["attempts"][0], barrier - 0.01)
        _retime_fault_attempt(affected["attempts"][1], barrier + 0.100001)
    else:
        _retime_fault_attempt(affected["attempts"][-2], window_end - 0.100001)
        _retime_fault_attempt(affected["attempts"][-1], window_end + 0.01)
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any(
        "affected shard shard-000 cadence is missing, exceeds 100 ms, or is not raw-derived"
        in error
        for error in errors
    )


def test_fault_unaffected_control_cadence_is_recomputed_from_attempt_timestamps(
    tmp_path: Path,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    control = next(row for row in workload["client_series"] if row["affected"] is False)
    _retime_fault_attempt(control["attempts"][5], 200.55)
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any(
        "unaffected control shard" in error
        and "cadence is missing, exceeds 100 ms, or is not raw-derived" in error
        for error in errors
    )


def test_fault_stable_recovery_is_recomputed_from_raw_set_get_pairs(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    affected = next(row for row in workload["client_series"] if row["affected"] is True)
    affected["attempts"][8].update(
        {
            "value_matches": False,
            "error": "tampered pair",
            "status": "FAIL",
        }
    )
    affected["error_count"] += 1
    workload["errors"].append("tampered pair")
    workload["error_count"] += 1
    trial["workload"]["errors"] += 1
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("stable summary is not the earliest raw one-second window" in error for error in errors)


def test_fault_first_success_rejects_an_operation_started_before_sigkill(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    affected = next(row for row in workload["client_series"] if row["affected"] is True)
    barrier = trial["monotonic_markers"]["sigkill_barrier"]
    pre_barrier = deepcopy(affected["attempts"][1])
    pre_barrier.update(
        {
            "started_at_monotonic": barrier - 0.01,
            "completed_at_monotonic": barrier + 0.01,
            "set_completed_at_monotonic": barrier,
            "get_completed_at_monotonic": barrier + 0.01,
            "latency_ms": 20.0,
        }
    )
    affected["attempts"].insert(0, pre_barrier)
    workload["first_success"].update(
        {
            "first_affected_write": barrier,
            "first_affected_read": barrier + 0.01,
        }
    )
    trial["derived_intervals"].update(
        {
            "sigkill_to_first_write_seconds": 0.0,
            "sigkill_to_first_read_seconds": 0.01,
        }
    )
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("raw attempts or summaries are inconsistent" in error for error in errors)
    assert any("sigkill_to_first_write_seconds is not bound to raw client recovery" in error for error in errors)


def test_fault_workload_rejects_a_truncated_error_array(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    workload = json.loads(paths["workload"].read_text(encoding="utf-8"))
    workload["errors"] = []
    _rewrite_bound_source(report, trial, paths["workload"], "workload", workload)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("workload error count does not match its summary" in error for error in errors)


def test_fault_transition_marker_is_recomputed_from_raw_observer_views(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    fault = json.loads(paths["fault"].read_text(encoding="utf-8"))
    target_id = fault["target_node_ids"][0]
    views_ref = fault["observer_rounds"][0]["views_sha256"]
    for view in _fault_round_views(fault, 0):
        view["target_flags"][target_id] = ["master"]
        view["cluster_nodes"][target_id]["flags"] = ["master"]
    _rebind_fault_view_entry(fault, views_ref)
    _rewrite_bound_source(report, trial, paths["fault"], "fault", fault)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("fault marker first_pfail is not the earliest raw observer transition" in error for error in errors)


def test_fault_unexpected_safety_is_aggregated_from_observer_facts(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    fault = json.loads(paths["fault"].read_text(encoding="utf-8"))
    views_ref = fault["observer_rounds"][0]["views_sha256"]
    _fault_round_views(fault, 0)[0]["cluster_nodes"]["node-001"]["flags"].append("fail")
    _rebind_fault_view_entry(fault, views_ref)
    _rewrite_bound_source(report, trial, paths["fault"], "fault", fault)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("unexpected safety summary is not derived from raw observer rounds" in error for error in errors)


def test_fault_every_node_convergence_is_recomputed_from_survivor_views(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    fault = json.loads(paths["fault"].read_text(encoding="utf-8"))
    views_ref = fault["every_node_convergence_views_sha256"]
    _fault_convergence_views(fault)[0]["cluster_slots_ok"] = 0
    _rebind_fault_view_entry(fault, views_ref)
    _rewrite_bound_source(report, trial, paths["fault"], "fault", fault)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("every-node convergence fact slots_covered is not derived" in error for error in errors)


def test_fault_every_node_convergence_requires_direct_probe_bounds(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    fault = json.loads(paths["fault"].read_text(encoding="utf-8"))
    fault["every_node_convergence_probe"]["probe_started_at_monotonic"] = 201.6
    _rewrite_bound_source(report, trial, paths["fault"], "fault", fault)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("convergence probe lacks direct monotonic bounds" in error for error in errors)


def test_fault_post_convergence_observer_round_cannot_regress(tmp_path: Path) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    fault = json.loads(paths["fault"].read_text(encoding="utf-8"))
    views_ref = fault["observer_rounds"][-1]["views_sha256"]
    _fault_round_views(fault, -1)[0]["cluster_slots_ok"] = 0
    _rebind_fault_view_entry(fault, views_ref)
    _rewrite_bound_source(report, trial, paths["fault"], "fault", fault)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("regressed after every-node convergence" in error for error in errors)


def test_fault_observer_rounds_must_cover_the_complete_fixed_window(
    tmp_path: Path,
) -> None:
    report, trial = _fault_source_report()
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    fault = json.loads(paths["fault"].read_text(encoding="utf-8"))
    fault["observer_rounds"][-1]["at_monotonic"] = 201.500001
    fault["observer_rounds"][-1]["probe_started_at_monotonic"] = 201.490001
    _rewrite_bound_source(report, trial, paths["fault"], "fault", fault)

    errors = M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path)

    assert any("do not cover the complete fixed window" in error for error in errors)


def test_blocked_capture_without_started_trials_needs_no_performance_sources(tmp_path: Path) -> None:
    report = {"status": "BLOCKED", "trials": [], "source_refs": []}

    assert M2.validate_current_invocation_sources(report, artifacts_dir=tmp_path) == []


def test_stability_requires_selected_paired_soak_and_validates_faults() -> None:
    selected = {
        "kind": "selected_settings",
        "value": "candidate",
        "cluster_create_strategy": "candidate_strategy",
        "cluster_node_timeout_ms": 15000,
    }
    other = {**selected, "cluster_node_timeout_ms": 10000}
    cells = {
        "bootstrap": {
            "cell_id": "bootstrap",
            "campaign_step": "stability",
            "scale": 200,
            "failure_rate": "none",
            "required_pairs": 1,
            "candidate": other,
            "status": "PASS",
        },
        "fault": {
            "cell_id": "fault",
            "campaign_step": "stability",
            "scale": 200,
            "failure_rate": "33_percent",
            "required_pairs": 1,
            "candidate": selected,
            "status": "PASS",
        },
        "soak": {
            "cell_id": "soak",
            "campaign_step": "soak",
            "scale": 200,
            "failure_rate": "none",
            "required_pairs": 0,
            "candidate": selected,
            "status": "PASS",
        },
    }
    errors: list[str] = []
    M2._validate_stability(
        {
            "baseline": {
                "kind": "selected_settings",
                "value": "baseline",
                "cluster_create_strategy": "valkey_cli_cluster_create_primaries",
                "cluster_node_timeout_ms": 30000,
            },
            "selected_candidate": selected,
        },
        {"fault-trial": {"trial_id": "fault-trial", "cell_id": "fault", "scale": 200}},
        {},
        cells,
        errors,
    )

    assert any("does not exercise selected settings" in error for error in errors)
    assert any("soak requires fewer than one pair" in error for error in errors)
    assert any("soak has no A/B pair" in error for error in errors)
    assert any("did not use owned-process SIGKILL" in error for error in errors)


def test_stability_workload_regression_uses_conservative_histogram_bounds() -> None:
    def histogram_p99(latency_ms: float) -> float:
        tick = math.ceil(
            math.log2(latency_ms) * M2.LATENCY_HISTOGRAM_BUCKETS_PER_OCTAVE
            - 1e-12
        )
        bucket_index = tick - M2.LATENCY_HISTOGRAM_MIN_TICK
        p99, count, valid = M2._histogram_nearest_rank(
            {
                "schema_version": M2.LATENCY_HISTOGRAM_SCHEMA_VERSION,
                "buckets": [{"index": bucket_index, "count": 1000}],
            },
            0.99,
        )
        assert valid and count == 1000 and p99 is not None
        return p99

    baseline = {
        "kind": "selected_settings",
        "value": "m1-defaults",
        "cluster_create_strategy": "valkey_cli_cluster_create_primaries",
        "cluster_node_timeout_ms": 30000,
    }
    selected = {
        "kind": "selected_settings",
        "value": "selected",
        "cluster_create_strategy": "candidate-strategy",
        "cluster_node_timeout_ms": 15000,
    }
    cells = {
        cell_id: {
            "cell_id": cell_id,
            "campaign_step": "soak" if cell_id == "soak" else "stability",
            "scale": 200,
            "failure_rate": "33_percent" if cell_id == "fault" else "none",
            "required_pairs": 1,
            "candidate": selected,
            "status": "PASS",
        }
        for cell_id in ("bootstrap", "fault", "soak")
    }
    pairs_by_cell: dict[str, list[dict[str, object]]] = {}
    trials: dict[str, dict[str, object]] = {}
    for cell_id in cells:
        duration = 1800.0 if cell_id == "soak" else 120.0
        baseline_id = f"{cell_id}-baseline"
        candidate_id = f"{cell_id}-candidate"
        pairs_by_cell[cell_id] = [
            {
                "pair_id": f"{cell_id}-pair",
                "baseline_trial_id": baseline_id,
                "candidate_trial_id": candidate_id,
                "equal_observation_seconds": duration,
            }
        ]
        for trial_id, arm, throughput, latency in (
            (baseline_id, "baseline", 100.0, histogram_p99(1.21)),
            (candidate_id, "candidate", 94.0, histogram_p99(1.34)),
        ):
            trials[trial_id] = {
                "trial_id": trial_id,
                "cell_id": cell_id,
                "arm": arm,
                "scale": 200,
                "resource_window": {"duration_seconds": duration},
                "workload": {
                    "duration_seconds": duration,
                    "set_throughput_ops_per_second": throughput,
                    "p99_latency_ms": latency,
                    "errors": 0,
                },
                "monotonic_markers": {},
                "fault": {},
            }

    errors: list[str] = []
    M2._validate_stability(
        {"baseline": baseline, "selected_candidate": selected},
        trials,
        pairs_by_cell,
        cells,
        errors,
    )

    assert any("throughput regressed by more than 5 percent" in error for error in errors)
    assert any("p99 latency regressed by more than 10 percent" in error for error in errors)

    for trial in trials.values():
        if trial["arm"] == "candidate":
            trial["workload"]["set_throughput_ops_per_second"] = 100.0
            trial["workload"]["p99_latency_ms"] = histogram_p99(1.28)
    boundary_errors: list[str] = []
    M2._validate_stability(
        {"baseline": baseline, "selected_candidate": selected},
        trials,
        pairs_by_cell,
        cells,
        boundary_errors,
    )

    assert not any("throughput regressed" in error for error in boundary_errors)
    assert not any("p99 latency regressed" in error for error in boundary_errors)


def test_runner_without_real_authorization_is_blocked_and_does_not_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = tmp_path / "result.json"
    monkeypatch.delenv(M2.AUTHORIZATION_ENV, raising=False)
    monkeypatch.setattr(
        M2,
        "capture_current_invocation",
        lambda _args: pytest.fail("an unauthorized fast test started a real capture"),
    )

    exit_code = M2.main(
        [
            "formation",
            "--selected-strategy",
            "current-default",
            "--run-id",
            "gate-run",
            "--artifacts-dir",
            str(tmp_path),
            "--result-path",
            str(result),
        ]
    )

    assert exit_code == 0
    assert json.loads(result.read_text(encoding="utf-8"))["status"] == "BLOCKED"
    assert set(json.loads(result.read_text(encoding="utf-8"))) == {"status", "summary"}


def test_runner_rejects_fixture_named_artifact_root_before_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(M2.AUTHORIZATION_ENV, "1")
    monkeypatch.setattr(
        M2,
        "capture_current_invocation",
        lambda _args: pytest.fail("a forbidden artifact root reached the real producer"),
    )
    args = M2._parser().parse_args(
        [
            "formation",
            "--selected-strategy",
            "current-default",
            "--run-id",
            "gate-run",
            "--artifacts-dir",
            str(tmp_path / "fixtures"),
            "--result-path",
            str(tmp_path / "result.json"),
        ]
    )

    status, summary = M2.run(args)

    assert status == "FAIL"
    assert "forbidden" in summary


def test_authorized_runner_invokes_current_capture_and_fails_without_its_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = tmp_path / "result.json"
    monkeypatch.setenv(M2.AUTHORIZATION_ENV, "1")
    calls: list[str] = []

    def fake_capture(args) -> tuple[str, str]:
        calls.append(args.run_id)
        return "FAIL", "fixture capture intentionally emitted no report"

    monkeypatch.setattr(M2, "capture_current_invocation", fake_capture)

    exit_code = M2.main(
        [
            "failover",
            "--selected-timeout-ms",
            "current-default",
            "--run-id",
            "gate-run",
            "--artifacts-dir",
            str(tmp_path),
            "--result-path",
            str(result),
        ]
    )

    assert exit_code == 0
    assert calls == ["gate-run"]
    assert json.loads(result.read_text(encoding="utf-8"))["status"] == "FAIL"


def test_authorized_runner_rejects_preexisting_evidence_without_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = tmp_path / "result.json"
    (tmp_path / M2.REPORT_NAME).write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv(M2.AUTHORIZATION_ENV, "1")
    monkeypatch.setattr(
        M2,
        "capture_current_invocation",
        lambda _args: pytest.fail("pre-existing evidence reached the real producer"),
    )

    exit_code = M2.main(
        [
            "formation",
            "--selected-strategy",
            "current-default",
            "--run-id",
            "gate-run",
            "--artifacts-dir",
            str(tmp_path),
            "--result-path",
            str(result),
        ]
    )

    assert exit_code == 0
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert "pre-existing" in payload["summary"]


def test_discovery_runner_without_authorization_is_blocked_before_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "discovery"
    result = tmp_path / "discovery-result.json"
    monkeypatch.delenv(DISCOVERY.admission.AUTHORIZATION_ENV, raising=False)
    monkeypatch.setattr(
        DISCOVERY,
        "_capture",
        lambda _args: pytest.fail("unauthorized discovery reached real capture"),
    )

    assert DISCOVERY.main(
        [
            "--run-id",
            "discovery-run",
            "--artifacts-dir",
            str(artifacts),
            "--result-path",
            str(result),
            "--tested-sha",
            "c" * 40,
        ]
    ) == 0

    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "BLOCKED"
    assert set(payload) == {"status", "summary"}
    report = json.loads((artifacts / DISCOVERY.REPORT_NAME).read_text(encoding="utf-8"))
    assert report["status"] == "BLOCKED"
    assert report["campaigns"] == {}


@pytest.mark.parametrize(
    ("tested_sha", "checkout_sha", "summary_fragment"),
    [
        ("short", "short", "full lowercase Git SHA"),
        ("c" * 40, "d" * 40, "checkout does not match"),
    ],
)
def test_discovery_runner_rejects_invalid_or_mismatched_sha_before_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tested_sha: str,
    checkout_sha: str,
    summary_fragment: str,
) -> None:
    result = tmp_path / "discovery-result.json"
    monkeypatch.setenv(DISCOVERY.admission.AUTHORIZATION_ENV, "discovery-run")
    monkeypatch.setattr(DISCOVERY, "_checkout_sha", lambda: checkout_sha)
    monkeypatch.setattr(
        DISCOVERY,
        "_capture",
        lambda _args: pytest.fail("invalid SHA discovery reached real capture"),
    )

    DISCOVERY.main(
        [
            "--run-id",
            "discovery-run",
            "--artifacts-dir",
            str(tmp_path / "discovery"),
            "--result-path",
            str(result),
            "--tested-sha",
            tested_sha,
        ]
    )

    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "BLOCKED"
    assert summary_fragment in payload["summary"]
    assert set(payload) == {"status", "summary"}


def test_discovery_runner_rejects_preexisting_or_forbidden_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DISCOVERY.admission.AUTHORIZATION_ENV, "discovery-run")
    monkeypatch.setattr(DISCOVERY, "_checkout_sha", lambda: "c" * 40)
    monkeypatch.setattr(
        DISCOVERY,
        "_capture",
        lambda _args: pytest.fail("unsafe artifacts reached real discovery"),
    )
    preexisting = tmp_path / "discovery"
    preexisting.mkdir()
    (preexisting / "old.json").write_text("{}\n", encoding="utf-8")

    preexisting_args = DISCOVERY._parser().parse_args(
        [
            "--run-id",
            "discovery-run",
            "--artifacts-dir",
            str(preexisting),
            "--result-path",
            str(tmp_path / "preexisting-result.json"),
            "--tested-sha",
            "c" * 40,
        ]
    )
    forbidden_args = DISCOVERY._parser().parse_args(
        [
            "--run-id",
            "discovery-run",
            "--artifacts-dir",
            str(tmp_path / "fixtures"),
            "--result-path",
            str(tmp_path / "forbidden-result.json"),
            "--tested-sha",
            "c" * 40,
        ]
    )

    preexisting_status, preexisting_summary = DISCOVERY.run(
        preexisting_args
    )
    assert (preexisting_status, preexisting_summary) == (
        "FAIL",
        "refusing pre-existing M2 discovery artifacts",
    )
    forbidden_status, forbidden_summary = DISCOVERY.run(
        forbidden_args
    )
    assert forbidden_status == "FAIL"
    assert "forbidden" in forbidden_summary


def test_discovery_environment_blocker_emits_distinct_blocked_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "discovery"
    result = tmp_path / "discovery-result.json"
    monkeypatch.setenv(DISCOVERY.admission.AUTHORIZATION_ENV, "discovery-run")
    monkeypatch.setattr(DISCOVERY, "_checkout_sha", lambda: "c" * 40)
    monkeypatch.setattr(DISCOVERY.capture, "_product_digest", lambda: SHA)

    def blocked_environment() -> dict[str, object]:
        raise DISCOVERY.capture.EnvironmentBlocked("Docker unavailable")

    monkeypatch.setattr(DISCOVERY.capture, "_environment_facts", blocked_environment)

    assert DISCOVERY.main(
        [
            "--run-id",
            "discovery-run",
            "--artifacts-dir",
            str(artifacts),
            "--result-path",
            str(result),
            "--tested-sha",
            "c" * 40,
        ]
    ) == 0

    payload = json.loads(result.read_text(encoding="utf-8"))
    report = json.loads(
        (artifacts / DISCOVERY.REPORT_NAME).read_text(encoding="utf-8")
    )
    assert payload["status"] == "BLOCKED"
    assert set(payload) == {"status", "summary"}
    assert report["artifact_type"] == "m2_candidate_discovery"
    assert report["purpose"] == "candidate-selection-only"
    assert report["admission_evidence"] is False
    assert report["status"] == "BLOCKED"
    assert report["real_valkey"] is False
    assert report["campaigns"] == {}
    assert report["report_digest"] == DISCOVERY.admission.report_digest(report)


def test_discovery_resource_preflight_blocker_remains_preflight_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "discovery"
    result = tmp_path / "discovery-result.json"
    monkeypatch.setenv(DISCOVERY.admission.AUTHORIZATION_ENV, "discovery-run")
    monkeypatch.setattr(DISCOVERY, "_checkout_sha", lambda: "c" * 40)
    monkeypatch.setattr(DISCOVERY.capture, "_product_digest", lambda: SHA)
    monkeypatch.setattr(DISCOVERY.capture, "_environment_facts", lambda: {})

    def blocked_preflight(*_args: object, **_kwargs: object) -> None:
        raise DISCOVERY.capture.EnvironmentBlocked(
            "resource preflight rejected the host"
        )

    monkeypatch.setattr(
        DISCOVERY.capture,
        "capture_formation_discovery",
        blocked_preflight,
    )

    assert DISCOVERY.main(
        [
            "--run-id",
            "discovery-run",
            "--artifacts-dir",
            str(artifacts),
            "--result-path",
            str(result),
            "--tested-sha",
            "c" * 40,
        ]
    ) == 0

    payload = json.loads(result.read_text(encoding="utf-8"))
    report = json.loads((artifacts / DISCOVERY.REPORT_NAME).read_text(encoding="utf-8"))
    assert payload["status"] == "BLOCKED"
    assert set(payload) == {"status", "summary"}
    assert report["campaigns"] == {}
    assert report["errors"] == ["ENVIRONMENT_BLOCKED: resource preflight rejected the host"]


@pytest.mark.parametrize(
    ("failure_phase", "exception_type"),
    [
        ("formation", DISCOVERY.capture.CaptureError),
        ("failover", RuntimeError),
    ],
)
def test_discovery_producer_keeps_only_completed_and_affected_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
    exception_type: type[Exception],
) -> None:
    artifacts = tmp_path / failure_phase
    args = DISCOVERY._parser().parse_args(
        [
            "--run-id",
            "discovery-run",
            "--artifacts-dir",
            str(artifacts),
            "--result-path",
            str(tmp_path / f"{failure_phase}-result.json"),
            "--tested-sha",
            "c" * 40,
        ]
    )

    def context(arguments, *, mode, **_kwargs):
        return DISCOVERY.SimpleNamespace(
            args=DISCOVERY.SimpleNamespace(run_id=arguments.run_id, mode=mode),
            started=True,
            started_trial_ids=[],
            trials=[],
            pairs=[],
            cells=[],
            invalid_samples=[],
            source_refs=[],
        )

    def formation_capture(*_args, **_kwargs):
        if failure_phase == "formation":
            raise exception_type("collector failed")
        return []

    def failover_capture(*_args, **_kwargs):
        raise exception_type("collector failed")

    monkeypatch.setattr(DISCOVERY, "_context", context)
    monkeypatch.setattr(DISCOVERY.capture, "_product_digest", lambda: SHA)
    monkeypatch.setattr(DISCOVERY.capture, "_environment_facts", lambda: {})
    monkeypatch.setattr(DISCOVERY.capture, "_digest", lambda _value: SHA)
    monkeypatch.setattr(
        DISCOVERY.capture, "capture_formation_discovery", formation_capture
    )
    monkeypatch.setattr(
        DISCOVERY.capture, "capture_failover_discovery", failover_capture
    )
    monkeypatch.setattr(
        DISCOVERY.admission, "validate_discovery_campaign", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        DISCOVERY.admission,
        "validate_current_invocation_sources",
        lambda *_args, **_kwargs: [],
    )

    status, _summary = DISCOVERY._capture(args)
    report = json.loads(
        (artifacts / DISCOVERY.REPORT_NAME).read_text(encoding="utf-8")
    )

    assert status == "FAIL"
    assert report["status"] == "FAIL"
    assert report["campaigns"][failure_phase]["errors"] == report["errors"]
    assert set(report["campaigns"]) == (
        {"formation"} if failure_phase == "formation" else {"formation", "failover"}
    )


def test_discovery_producer_replaces_current_phase_after_validation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "formation-validation"
    args = DISCOVERY._parser().parse_args(
        [
            "--run-id",
            "discovery-run",
            "--artifacts-dir",
            str(artifacts),
            "--result-path",
            str(tmp_path / "formation-validation-result.json"),
            "--tested-sha",
            "c" * 40,
        ]
    )

    def context(arguments, *, mode, **_kwargs):
        return DISCOVERY.SimpleNamespace(
            args=DISCOVERY.SimpleNamespace(run_id=arguments.run_id, mode=mode),
            started=True,
            started_trial_ids=[],
            trials=[],
            pairs=[],
            cells=[],
            invalid_samples=[],
            source_refs=[],
        )

    monkeypatch.setattr(DISCOVERY, "_context", context)
    monkeypatch.setattr(DISCOVERY.capture, "_product_digest", lambda: SHA)
    monkeypatch.setattr(DISCOVERY.capture, "_environment_facts", lambda: {})
    monkeypatch.setattr(DISCOVERY.capture, "_digest", lambda _value: SHA)
    monkeypatch.setattr(
        DISCOVERY.capture, "capture_formation_discovery", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        DISCOVERY.admission,
        "validate_discovery_campaign",
        lambda *_args, **_kwargs: ["producer/gate mismatch"],
    )
    monkeypatch.setattr(
        DISCOVERY.admission,
        "validate_current_invocation_sources",
        lambda *_args, **_kwargs: [],
    )

    status, _summary = DISCOVERY._capture(args)
    report = json.loads(
        (artifacts / DISCOVERY.REPORT_NAME).read_text(encoding="utf-8")
    )

    assert status == "FAIL"
    assert report["campaigns"]["formation"]["status"] == "FAIL"
    assert report["campaigns"]["formation"]["errors"] == report["errors"]
    assert "failover" not in report["campaigns"]


def test_resource_gate_expands_compact_links_without_copying_or_mutating_raw_source(
    tmp_path: Path,
) -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    report["trials"] = [trial]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    resource = json.loads(paths["resource"].read_text(encoding="utf-8"))
    dictionary_links = resource["directional_cluster_links_dictionary"][0][
        "directional_cluster_links"
    ]
    raw_process = resource["samples"][0]["nodehosts"][0]["processes"][0]
    raw_digest = raw_process["directional_cluster_links_sha256"]
    errors: list[str] = []

    expanded = M2._expand_resource_directional_links(
        resource,
        trial_id=trial["trial_id"],
        errors=errors,
    )
    expanded_process = expanded["samples"][0]["nodehosts"][0]["processes"][0]

    assert errors == []
    assert "directional_cluster_links_dictionary" not in expanded
    assert expanded_process["directional_cluster_links"] is dictionary_links
    assert "directional_cluster_links_sha256" not in expanded_process
    assert raw_process["directional_cluster_links_sha256"] == raw_digest
    assert "directional_cluster_links" not in raw_process
    assert "directional_cluster_links_dictionary" in resource


def test_resource_gate_retains_only_bounded_pair_facts_after_raw_validation(
    tmp_path: Path,
) -> None:
    report = _formation_report()
    trial = deepcopy(report["trials"][0])
    report["trials"] = [trial]
    report["source_refs"] = deepcopy(trial["source_sha256s"])
    paths = _write_valid_trial_sources(report, trial, tmp_path)
    resource = json.loads(paths["resource"].read_text(encoding="utf-8"))
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    raw_digest = M2._canonical_digest(resource)
    errors: list[str] = []

    pair_facts = M2._validate_resource_source(
        resource,
        trial,
        fault_trial=False,
        allow_initial_membership_transitions=True,
        state_document=state,
        errors=errors,
    )

    assert errors == []
    assert M2._canonical_digest(resource) == raw_digest
    assert set(pair_facts) == {
        "duration_seconds",
        "interval_seconds",
        "safety_metrics",
        "coverage",
    }
    assert pair_facts["safety_metrics"] == {
        "cluster_link_errors": 0,
        "buffer_overflows": 0,
    }
    assert set(pair_facts["coverage"]) == {
        "expected_sample_count",
        "observed_sample_count",
        "nodehost_count",
        "process_count",
        "actual_window_span_seconds",
        "sampling_envelope_span_seconds",
    }
    assert "samples" not in pair_facts
    assert "directional_cluster_links_dictionary" not in pair_facts
    assert M2._validate_equal_resource_window_facts(pair_facts, deepcopy(pair_facts)) == []

    unequal = deepcopy(pair_facts)
    unequal["coverage"]["actual_window_span_seconds"] = (
        float(unequal["coverage"]["actual_window_span_seconds"]) + 1.0
    )
    assert any(
        "actual_window_span_seconds" in error
        for error in M2._validate_equal_resource_window_facts(pair_facts, unequal)
    )
