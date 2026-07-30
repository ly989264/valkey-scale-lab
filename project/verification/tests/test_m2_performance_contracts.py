from __future__ import annotations

from copy import deepcopy
from typing import Any

from scripts import m2_performance_gate as M2


def _analysis() -> dict[str, Any]:
    return {
        "cpu": {"throttled_usec_delta": 2},
        "memory": {},
        "network": {
            "eth0": {
                "rx_errors": {"delta": 1},
                "rx_drops": {"delta": 0},
                "tx_errors": {"delta": 0},
                "tx_drops": {"delta": 1},
            }
        },
        "processes": {"node-a": {"cpu_ticks_delta": 7}},
        "process_totals": {
            "rss_bytes_max_sum": 140,
            "fd_count_max_sum": 5,
        },
        "collector": {"overrun_count": 0},
        "expected_gone_processes": [],
        "timestamps": [],
        "timeline_correlation": {},
    }


def _document() -> dict[str, Any]:
    analysis = _analysis()
    return {
        "artifact_type": "resource_observation",
        "status": "PASS",
        "duration_seconds": 5.0,
        "planned_kill_prefault_sample_complete": True,
        "expected_gone_processes": [],
        "checks": [
            {
                "name": "resource_analysis:host-a",
                "status": "OK",
                "evidence": analysis,
            }
        ],
        "resource_documents": [
            {
                "static": {"sampler_id": "host-a"},
                "samples": [
                    {"kind": "host"},
                    {
                        "kind": "process",
                        "processes": [
                            {"logical_id": "node-a", "pid": 123, "status": "OK"}
                        ],
                    },
                ],
                "errors": [],
            }
        ],
        "resource_analyses": [
            {"sampler_id": "host-a", "analysis": analysis}
        ],
        "m2_protocol_metrics": {
            "status": "PASS",
            "metrics": {
                "connection_count": 3,
                "cluster_bus_bytes": 40,
                "cluster_link_errors": 0,
                "buffer_overflows": 0,
            },
            "coverage": {
                "expected_live_node_count": 1,
                "node_metric_count": 1,
                "cluster_link_observer_count": 1,
                "missing_live_nodes": [],
                "errors": [],
            },
            "boundaries": {
                "end": {
                    "expected_live_nodes": ["node-a"],
                    "node_metrics": [
                        {
                            "logical_id": "node-a",
                            "valkey_node_id": "id-node-a",
                        }
                    ],
                    "cluster_link_observers": [
                        {
                            "logical_id": "node-a",
                            "valkey_node_id": "id-node-a",
                            "monotonic": 1.0,
                            "status": "OK",
                            "link_rows": [],
                            "expected_links": [],
                            "missing_links": [],
                            "cluster_link_count": 0,
                            "cluster_link_errors": 0,
                            "errors": [],
                        }
                    ],
                }
            },
        },
    }


def _trial(document: dict[str, Any]) -> dict[str, Any]:
    summary = M2._resource_observation_metrics(document)
    summary["duration_seconds"] = document["duration_seconds"]
    return {
        "trial_id": "trial-a",
        "scale": 1,
        "cell_id": "formation",
        "resource_observation": summary,
        "fault": None,
    }


def _m2_fault_topology_source() -> dict[str, Any]:
    controls = [
        {"logical_id": "primary-0", "shard_id": "shard-0", "role": "primary", "az_id": "az-a"},
        {"logical_id": "replica-0", "shard_id": "shard-0", "role": "replica", "az_id": "az-b"},
        {"logical_id": "primary-1", "shard_id": "shard-1", "role": "primary", "az_id": "az-a"},
        {"logical_id": "primary-2", "shard_id": "shard-2", "role": "primary", "az_id": "az-b"},
        {"logical_id": "primary-3", "shard_id": "shard-3", "role": "primary", "az_id": "az-c"},
    ]
    return {
        "status": "PASS",
        "versions": ["9.1.0"],
        "valkey_binary_sha256s": ["a" * 64],
        "topology_control": controls,
        "light_validation": {
            "status": "OK",
            "nodes_expected": 5,
            "nodes_observed": 5,
            "coverage": {
                "all_slots_covered_exactly_once": True,
                "primary_bitmaps_pairwise_disjoint": True,
            },
            "nodes": [
                _m2_light_node("primary-0", "id-primary-0", "primary", "shard-0"),
                _m2_light_node("replica-0", "id-replica-0", "replica", "shard-0", owner="id-primary-0"),
                _m2_light_node("primary-1", "id-primary-1", "primary", "shard-1"),
                _m2_light_node("primary-2", "id-primary-2", "primary", "shard-2"),
                _m2_light_node("primary-3", "id-primary-3", "primary", "shard-3"),
            ],
        },
        "topology_validation": {
            "status": "OK",
            "normalized_topology": {
                "shards": [
                    {
                        "primary_id": "id-primary-0",
                        "slots": [[0, 4095]],
                        "nodes": [
                            {"node_id": "id-primary-0", "role": "primary", "health": "online"},
                            {"node_id": "id-replica-0", "role": "replica", "health": "online"},
                        ],
                    },
                    {
                        "primary_id": "id-primary-1",
                        "slots": [[4096, 8191]],
                        "nodes": [
                            {"node_id": "id-primary-1", "role": "primary", "health": "online"},
                        ],
                    },
                    {
                        "primary_id": "id-primary-2",
                        "slots": [[8192, 12287]],
                        "nodes": [
                            {"node_id": "id-primary-2", "role": "primary", "health": "online"},
                        ],
                    },
                    {
                        "primary_id": "id-primary-3",
                        "slots": [[12288, 16383]],
                        "nodes": [
                            {"node_id": "id-primary-3", "role": "primary", "health": "online"},
                        ],
                    },
                ],
            },
        },
        "topology_control_digest": "unused",
    }


def _m2_light_node(
    logical_id: str,
    node_id: str,
    role: str,
    shard_id: str,
    *,
    owner: str | None = None,
) -> dict[str, Any]:
    return {
        "logical_id": logical_id,
        "myslots": {
            "node-id": node_id,
            "role": role,
            "shard-id": shard_id,
            "slot-owner-id": owner or node_id,
        },
        "cluster_info": {
            "cluster_slots_pfail": 0,
            "cluster_slots_fail": 0,
        },
        "role": {"replication_state": "connected"} if role == "replica" else {},
    }


def _m2_fault_state_source() -> dict[str, Any]:
    rows = []
    for logical_id, pid, port in (
        ("primary-0", 100, 7400),
        ("replica-0", 101, 7401),
        ("primary-1", 102, 7402),
        ("primary-2", 103, 7403),
        ("primary-3", 104, 7404),
    ):
        rows.append(
            {
                "logical_id": logical_id,
                "container_id": f"cid-{logical_id}",
                "container_name": f"container-{logical_id}",
                "pid": pid,
                "pid_file": f"/tmp/{logical_id}.pid",
                "config_file": f"/tmp/{logical_id}.conf",
                "client_port": port,
            }
        )
    return {"nodes": rows}


def _m2_logical_to_node_id() -> dict[str, str]:
    return {
        "primary-0": "id-primary-0",
        "replica-0": "id-replica-0",
        "primary-1": "id-primary-1",
        "primary-2": "id-primary-2",
        "primary-3": "id-primary-3",
    }


def _m2_affected_round(
    at: float,
    *,
    stable: bool,
    full: bool = False,
    pfail_slots: int = 0,
    fail_slots: int = 0,
    target_health: str = "online",
    non_target_health: str = "online",
) -> dict[str, Any]:
    observation = {
        "monotonic": at,
        "rows": [
                {
                    "logical_id": "replica-0",
                    "status": "OK",
                    "cluster_state": "ok" if stable else "fail",
                    "role": {"role": "primary"} if stable else {"role": "replica"},
                    "cluster_info": {
                        "cluster_nodes_pfail": str(pfail_slots),
                        "cluster_nodes_fail": str(fail_slots),
                        "cluster_slots_assigned": "16384",
                        "cluster_slots_ok": "16384",
                        "cluster_slots_pfail": "0",
                        "cluster_slots_fail": "0",
                    },
                }
            ],
        "candidate": (
            {"primary": "replica-0", "relationships": {"replica-0": "primary"}}
            if stable
            else None
        ),
    }
    affected_shards = [{"shard_id": "shard-0", "observation": observation}]
    affected_facts, _contract, _shards = M2._recompute_affected_fault_facts(
        affected_shards,
        target_node_ids={"id-primary-0"},
        replacement_by_shard={"shard-0": "replica-0"},
        logical_to_node_id=_m2_logical_to_node_id(),
        expected_nodes=5,
        full_validation_passed=full,
    )
    del target_health, non_target_health
    facts = M2._recompute_fault_round_facts(
        affected_facts,
        affected_shards,
        target_node_ids={"id-primary-0"},
    )
    return {
        "at_monotonic": at,
        "probe_started_at_monotonic": at - 0.01,
        "probe_duration_ms": 10.0,
        "affected_shards": affected_shards,
        "facts": facts,
    }


def _m2_fault_source_and_trial() -> tuple[dict[str, Any], dict[str, Any]]:
    markers = {
        "sigkill_barrier": 10.0,
        "all_processes_gone": 10.1,
        "first_pfail": 10.5,
        "quorum_fail": 11.0,
        "first_promotion": 11.5,
        "all_slots_covered_cluster_ok": 11.5,
        "stable_client_recovery": 12.0,
        "every_node_converged": 12.6,
    }
    batch = {
        "container_id": "cid-primary-0",
        "container_name": "container-primary-0",
        "logical_ids": ["primary-0"],
        "pids": [100],
        "ownership_id": "run-1",
        "argv": ["exec", "cid-primary-0", "sh", "-c", "kill -KILL 100"],
        "status": "PASS",
        "returncode": 0,
        "stdout": "",
        "started_at_monotonic": 10.0,
        "ended_at_monotonic": 10.05,
    }
    document = {
        "status": "PASS",
        "errors": [],
        "mode": "owned-process-sigkill",
        "signal": "SIGKILL",
        "commands": [M2.shlex.join(["docker", *batch["argv"]])],
        "command_batches": [batch],
        "barrier_monotonic": 10.0,
        "fault_apply_monotonic_ms": 10000.0,
        "signal_barrier_span_ms": 50.0,
        "primary_count": 2,
        "failed_primary_count": 1,
        "injection_skew_ms": 50.0,
        "targets": [
            {
                "logical_id": "primary-0",
                "shard_id": "shard-0",
                "pid": 100,
                "ownership_id": "run-1",
                "process_gone": True,
                "physical_fault_id": "fault-1",
                "status": "PASS",
                "error": "",
                "valkey_node_id": "id-primary-0",
                "signal_sent_at_monotonic_ms": 10000.0,
                "signal_completed_at_monotonic_ms": 10050.0,
                "process_gone_at_monotonic_ms": 10100.0,
            }
        ],
        "target_node_ids": ["id-primary-0"],
        "replacement_node_ids": ["id-replica-0"],
        "initial_roles": {
            "id-primary-0": "primary",
            "id-replica-0": "replica",
            "id-primary-1": "primary",
            "id-primary-2": "primary",
            "id-primary-3": "primary",
        },
        "node_shards": {
            "id-primary-0": "shard-0",
            "id-replica-0": "shard-0",
            "id-primary-1": "shard-1",
            "id-primary-2": "shard-2",
            "id-primary-3": "shard-3",
        },
        "monotonic_markers": markers,
        "observer_rounds": [
            _m2_affected_round(10.5, stable=False, pfail_slots=1),
            _m2_affected_round(11.0, stable=False, fail_slots=1, target_health="fail"),
            _m2_affected_round(11.5, stable=True, target_health="fail"),
            _m2_affected_round(12.0, stable=True, target_health="fail"),
            _m2_affected_round(13.0, stable=True, target_health="fail", full=True),
        ],
        "full_validation": {
            "status": "OK",
            "light_validation": {"status": "OK"},
            "topology_validation": {"status": "OK"},
        },
        "every_node_convergence_probe": {
            "probe_started_at_monotonic": 12.55,
            "at_monotonic": 12.6,
            "probe_duration_ms": 50.0,
        },
        "observed_safety": {
            "unexpected_pfail": 0,
            "unexpected_fail": 0,
            "observed_extra_failures": 0,
            "unexpected_promotions": 0,
            "split_brain": False,
        },
    }
    affected_topology_facts = M2._recompute_affected_fault_facts(
        document["observer_rounds"][3]["affected_shards"],
        target_node_ids={"id-primary-0"},
        replacement_by_shard={"shard-0": "replica-0"},
        logical_to_node_id=_m2_logical_to_node_id(),
        expected_nodes=5,
        full_validation_passed=True,
    )[0]
    document["topology_facts"] = M2._recompute_fault_round_facts(
        affected_topology_facts,
        document["observer_rounds"][3]["affected_shards"],
        target_node_ids={"id-primary-0"},
    )
    trial = {
        "trial_id": "fault-trial",
        "scale": 5,
        "ownership_id": "run-1",
        "fault": M2._compact_fault_summary(document),
        "monotonic_markers": dict(markers),
        "workload": {"duration_seconds": 3.0},
        "correctness": {
            "exact_membership": True,
            "observed_nodes": 5,
            "slots_covered": 16384,
            "replicas_synchronized": True,
            "clean_topology": True,
            "data_path": True,
            "split_brain": False,
            "unexpected_pfail": 0,
            "unexpected_fail": 0,
            "observed_extra_failures": 0,
            "unexpected_promotions": 0,
            "slot_loss": False,
        },
        "derived_intervals": {
            name: round(markers[end] - markers[start], 6)
            for name, (start, end) in {
                "kill_to_stable_seconds": ("sigkill_barrier", "stable_client_recovery"),
                "pfail_to_cluster_ok_seconds": ("first_pfail", "all_slots_covered_cluster_ok"),
                "process_gone_to_pfail_seconds": ("all_processes_gone", "first_pfail"),
                "cluster_ok_to_stable_seconds": ("all_slots_covered_cluster_ok", "stable_client_recovery"),
                "sigkill_to_pfail_seconds": ("sigkill_barrier", "first_pfail"),
                "pfail_to_quorum_fail_seconds": ("first_pfail", "quorum_fail"),
                "quorum_fail_to_promotion_seconds": ("quorum_fail", "first_promotion"),
                "promotion_to_cluster_ok_seconds": ("first_promotion", "all_slots_covered_cluster_ok"),
                "recovery_to_convergence_seconds": ("stable_client_recovery", "every_node_converged"),
            }.items()
        },
    }
    return document, trial


def test_m2_observation_source_accepts_new_contract() -> None:
    document = _document()
    errors: list[str] = []

    facts = M2._validate_resource_source(
        document,
        _trial(document),
        fault_trial=False,
        allow_initial_membership_transitions=False,
        state_document={"nodes": [{"logical_id": "node-a", "pid": 123}]},
        errors=errors,
    )

    assert errors == []
    assert facts["coverage"]["analysis_count"] == 1


def test_m2_observation_source_rejects_missing_valkey_cluster_metrics() -> None:
    document = _document()
    document["m2_protocol_metrics"]["status"] = "ERROR"
    errors: list[str] = []

    M2._validate_resource_source(
        document,
        _trial(_document()),
        fault_trial=False,
        allow_initial_membership_transitions=False,
        state_document={"nodes": [{"logical_id": "node-a", "pid": 123}]},
        errors=errors,
    )

    assert any("protocol resource metrics" in error for error in errors)


def test_m2_observation_source_rejects_missing_analyzer_output() -> None:
    document = _document()
    document["checks"] = []
    document["resource_analyses"] = []
    errors: list[str] = []

    M2._validate_resource_source(
        document,
        _trial(_document()),
        fault_trial=False,
        allow_initial_membership_transitions=False,
        state_document={"nodes": [{"logical_id": "node-a", "pid": 123}]},
        errors=errors,
    )

    assert any("analyzer was not called" in error for error in errors)


def test_m2_fault_source_requires_expected_gone_evidence() -> None:
    document = _document()
    analysis = document["resource_analyses"][0]["analysis"]
    analysis["expected_gone_processes"] = [
        {"logical_id": "node-a", "pid": 123, "reason": "planned"}
    ]
    document["expected_gone_processes"] = [{"logical_id": "node-a", "pid": 123}]
    trial = _trial(document)
    trial["fault"] = {
        "targets": [{"logical_id": "node-a", "pid": 123}]
    }
    errors: list[str] = []

    M2._validate_resource_source(
        document,
        trial,
        fault_trial=True,
        allow_initial_membership_transitions=False,
        state_document={"nodes": [{"logical_id": "node-a", "pid": 123}]},
        errors=errors,
    )

    assert errors == []


def test_m2_fault_source_rejects_missing_expected_gone_evidence() -> None:
    document = _document()
    trial = _trial(document)
    trial["fault"] = {
        "targets": [{"logical_id": "node-a", "pid": 123}]
    }
    errors: list[str] = []

    M2._validate_resource_source(
        document,
        trial,
        fault_trial=True,
        allow_initial_membership_transitions=False,
        state_document={"nodes": [{"logical_id": "node-a", "pid": 123}]},
        errors=errors,
    )

    assert any("planned SIGKILL target" in error for error in errors)


def test_m2_fault_source_accepts_scalable_observability_evidence() -> None:
    document, trial = _m2_fault_source_and_trial()
    errors: list[str] = []

    M2._validate_fault_source(
        document,
        trial,
        topology_document=_m2_fault_topology_source(),
        state_document=_m2_fault_state_source(),
        errors=errors,
    )

    assert errors == []


def test_m2_fault_source_rejects_legacy_topology_views() -> None:
    document, trial = _m2_fault_source_and_trial()
    document["observer_rounds"][0]["views_sha256"] = "a" * 64
    document["topology_view_dictionary"] = [{"sha256": "a" * 64, "views": []}]
    errors: list[str] = []

    M2._validate_fault_source(
        document,
        trial,
        topology_document=_m2_fault_topology_source(),
        state_document=_m2_fault_state_source(),
        errors=errors,
    )

    assert any("legacy topology views" in error for error in errors)


def test_m2_fault_source_rejects_missing_scalable_full_validation() -> None:
    document, trial = _m2_fault_source_and_trial()
    document["full_validation"] = {"status": "ERROR"}
    errors: list[str] = []

    M2._validate_fault_source(
        document,
        trial,
        topology_document=_m2_fault_topology_source(),
        state_document=_m2_fault_state_source(),
        errors=errors,
    )

    assert any("scalable full validation" in error for error in errors)


def test_m2_fault_source_rejects_tampered_raw_pfail_marker() -> None:
    document, trial = _m2_fault_source_and_trial()
    trial["monotonic_markers"]["first_pfail"] = 10.4
    errors: list[str] = []

    M2._validate_fault_source(
        document,
        trial,
        topology_document=_m2_fault_topology_source(),
        state_document=_m2_fault_state_source(),
        errors=errors,
    )

    assert any("first_pfail" in error and "source" in error for error in errors)


def test_m2_fault_source_rejects_raw_extra_failure_regression() -> None:
    document, trial = _m2_fault_source_and_trial()
    row = document["observer_rounds"][-1]["affected_shards"][0]["observation"]["rows"][0]
    row["cluster_info"]["cluster_nodes_fail"] = "2"
    errors: list[str] = []

    M2._validate_fault_source(
        document,
        trial,
        topology_document=_m2_fault_topology_source(),
        state_document=_m2_fault_state_source(),
        errors=errors,
    )

    assert any("regressed after every-node convergence" in error for error in errors)
    assert any("unexpected_fail" in error for error in errors)
    assert any("observed_extra_failures" in error for error in errors)


def test_m2_fault_source_rejects_raw_affected_slot_loss() -> None:
    document, trial = _m2_fault_source_and_trial()
    info = document["observer_rounds"][-1]["affected_shards"][0]["observation"]["rows"][0]["cluster_info"]
    info["cluster_slots_assigned"] = "16000"
    errors: list[str] = []

    M2._validate_fault_source(
        document,
        trial,
        topology_document=_m2_fault_topology_source(),
        state_document=_m2_fault_state_source(),
        errors=errors,
    )

    assert any("slot_loss" in error for error in errors)


def test_m2_fault_source_rejects_unexpected_global_observer_promotion() -> None:
    document, trial = _m2_fault_source_and_trial()
    document["observer_rounds"][-1]["affected_shards"][0]["observation"]["rows"].append(
        {
            "logical_id": "primary-1",
            "status": "OK",
            "cluster_state": "ok",
            "role": {"role": "primary"},
            "cluster_info": {
                "cluster_nodes_pfail": "0",
                "cluster_nodes_fail": "0",
                "cluster_slots_assigned": "16384",
                "cluster_slots_ok": "16384",
                "cluster_slots_pfail": "0",
                "cluster_slots_fail": "0",
            },
        }
    )
    errors: list[str] = []

    M2._validate_fault_source(
        document,
        trial,
        topology_document=_m2_fault_topology_source(),
        state_document=_m2_fault_state_source(),
        errors=errors,
    )

    assert any("unexpected_promotions" in error for error in errors)


def test_m2_fault_source_rejects_missing_affected_coverage() -> None:
    document, trial = _m2_fault_source_and_trial()
    document["observer_rounds"][-1]["affected_shards"] = []
    errors: list[str] = []

    M2._validate_fault_source(
        document,
        trial,
        topology_document=_m2_fault_topology_source(),
        state_document=_m2_fault_state_source(),
        errors=errors,
    )

    assert any("every affected shard" in error for error in errors)


def test_m2_protocol_source_rejects_missing_cluster_link_raw_evidence() -> None:
    document = _document()
    document["m2_protocol_metrics"]["boundaries"]["end"]["cluster_link_observers"] = []
    errors: list[str] = []

    M2._validate_resource_source(
        document,
        _trial(_document()),
        fault_trial=False,
        allow_initial_membership_transitions=False,
        state_document={"nodes": [{"logical_id": "node-a", "pid": 123}]},
        errors=errors,
    )

    assert any("cluster-link raw evidence" in error for error in errors)


def test_m2_protocol_source_allows_planned_down_empty_event_link_rows() -> None:
    facts = M2._recompute_m2_cluster_link_facts(
        [
            {
                "logical_id": "node-a",
                "valkey_node_id": "id-node-a",
                "link_rows": [
                    {
                        "peer_node_id": "id-node-b",
                        "direction": direction,
                        "events": "r",
                        "send_buffer_allocated": 4,
                        "send_buffer_used": 1,
                    }
                    for direction in ("from", "to")
                ]
                + [
                    {
                        "peer_node_id": "id-target",
                        "direction": "to",
                        "events": "",
                        "send_buffer_allocated": 4,
                        "send_buffer_used": 1,
                    }
                ],
            },
            {
                "logical_id": "node-b",
                "valkey_node_id": "id-node-b",
                "link_rows": [
                    {
                        "peer_node_id": "id-node-a",
                        "direction": direction,
                        "events": "r",
                        "send_buffer_allocated": 4,
                        "send_buffer_used": 1,
                    }
                    for direction in ("from", "to")
                ],
            }
        ],
        expected_live_logical_ids=["node-a", "node-b"],
        node_id_by_logical={"node-a": "id-node-a", "node-b": "id-node-b"},
        planned_down_node_ids={"id-target"},
    )
    bad_survivor = M2._recompute_m2_cluster_link_facts(
        [
            {
                "logical_id": "node-a",
                "valkey_node_id": "id-node-a",
                "link_rows": [
                    {
                        "peer_node_id": "id-node-b",
                        "direction": "to",
                        "events": "",
                        "send_buffer_allocated": 4,
                        "send_buffer_used": 1,
                    }
                ],
            }
        ],
        expected_live_logical_ids=["node-a", "node-b"],
        node_id_by_logical={"node-a": "id-node-a", "node-b": "id-node-b"},
        planned_down_node_ids={"id-target"},
    )

    assert facts["status"] == "PASS"
    assert facts["cluster_link_errors"] == 0
    assert bad_survivor["status"] == "FAIL"


def test_resource_pair_facts_ignore_high_resource_values() -> None:
    baseline = {"duration_seconds": 5.0, "coverage": {"analysis_count": 1, "process_count": 1}}
    candidate = deepcopy(baseline)

    assert M2._validate_equal_resource_observation_facts(baseline, candidate) == []


def test_resource_regression_rejects_candidate_over_ten_percent() -> None:
    baseline = {"resource_observation": {metric: 10.0 for metric in M2.RESOURCE_METRICS}}
    baseline["resource_observation"]["cluster_link_errors"] = 0.0
    baseline["resource_observation"]["buffer_overflows"] = 0.0
    candidate = deepcopy(baseline)
    candidate["resource_observation"]["process_rss_bytes_max_sum"] = 11.1

    assert not M2._resource_regression_clean(baseline, candidate)


def test_resource_regression_rejects_cluster_bus_over_ten_percent() -> None:
    baseline = {"resource_observation": {metric: 10.0 for metric in M2.RESOURCE_METRICS}}
    baseline["resource_observation"]["cluster_link_errors"] = 0.0
    baseline["resource_observation"]["buffer_overflows"] = 0.0
    candidate = deepcopy(baseline)
    candidate["resource_observation"]["cluster_bus_bytes"] = 11.1

    assert not M2._resource_regression_clean(baseline, candidate)


def test_resource_regression_rejects_link_or_buffer_safety_events() -> None:
    baseline = {"resource_observation": {metric: 10.0 for metric in M2.RESOURCE_METRICS}}
    baseline["resource_observation"]["cluster_link_errors"] = 0.0
    baseline["resource_observation"]["buffer_overflows"] = 0.0
    candidate = deepcopy(baseline)
    candidate["resource_observation"]["cluster_link_errors"] = 1.0

    assert not M2._resource_regression_clean(baseline, candidate)


def test_resource_regression_allows_candidate_at_ten_percent() -> None:
    baseline = {"resource_observation": {metric: 10.0 for metric in M2.RESOURCE_METRICS}}
    baseline["resource_observation"]["cluster_link_errors"] = 0.0
    baseline["resource_observation"]["buffer_overflows"] = 0.0
    candidate = deepcopy(baseline)
    candidate["resource_observation"]["process_fd_count_max_sum"] = 11.0
    candidate["resource_observation"]["process_cpu_ticks_delta_sum"] = 11.0
    candidate["resource_observation"]["connection_count"] = 11.0
    candidate["resource_observation"]["cluster_bus_bytes"] = 11.0

    assert M2._resource_regression_clean(baseline, candidate)
