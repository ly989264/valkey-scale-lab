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
                "topology_observer_count": 1,
                "missing_live_nodes": [],
                "errors": [],
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
