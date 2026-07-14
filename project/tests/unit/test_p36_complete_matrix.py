from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from valkey_scale_lab.gates import real as exact_gate
from valkey_scale_lab.evidence import canonical_bundle_spec
from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.scenarios import load_local_full_flow_definition


LIFECYCLE = list(canonical_bundle_spec(load_local_full_flow_definition()).lifecycle_ids)


def test_management_operations_map_to_observed_matrix_scenarios() -> None:
    assert docker_runtime._p36_management_scenario("add_replica") == "add_remove_node"
    assert docker_runtime._p36_management_scenario("reshard_with_keys") == "reshard_rebalance"
    assert docker_runtime._p36_management_scenario("rolling_restart_primary_safe") == "rolling_restart"


def test_fault_probe_emits_scenario_owned_command_events_metrics_and_window() -> None:
    commands: list[dict] = []
    events: list[dict] = []
    metrics: list[dict] = []
    windows: list[dict] = []
    result = docker_runtime._p36_execute_fault_probe(
        run_id="run-1",
        scale=50,
        scenario_id="network_delay",
        action=lambda: {"actions": ["sandbox_proxy network_delay"], "delay_injections": 1},
        command_log=commands,
        events=events,
        metrics=metrics,
        windows=windows,
    )
    assert result["result"]["status"] == "REAL_PASS"
    assert commands[0]["scenario_id"] == "network_delay"
    assert commands[0]["operation_id"] == "p36-fault-network_delay-50"
    assert result["evidence"]["command_ids"] == [commands[0]["command_id"]]
    assert {row["scenario_id"] for row in events} == {"network_delay"}
    assert metrics[0]["metric_value"] >= 0
    assert windows[0]["status"] == "PASS"


def test_event_normalization_uses_operation_identity_not_list_position() -> None:
    events = [
        {"operation_id": "operation-a", "event_id": "evt-0001"},
        {"operation_id": "operation-b", "event_id": "evt-0001"},
    ]
    windows = [
        {"operation_id": "operation-a", "start_event_id": "evt-0001", "end_event_id": "evt-0001", "metrics": {"window_start_event_id": "evt-0001", "window_end_event_id": "evt-0001"}},
        {"operation_id": "operation-b", "start_event_id": "evt-0001", "end_event_id": "evt-0001", "metrics": {"window_start_event_id": "evt-0001", "window_end_event_id": "evt-0001"}},
    ]
    docker_runtime._p36_normalize_event_ids(events, windows)
    assert events[0]["event_id"] == "operation-a-evt-0001"
    assert events[1]["event_id"] == "operation-b-evt-0001"
    assert windows[0]["start_event_id"] == events[0]["event_id"]
    assert windows[1]["start_event_id"] == events[1]["event_id"]


def test_lifecycle_artifact_uses_positive_measured_spans(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "events.jsonl").write_text("", encoding="utf-8")
    names = ["resource_preflight", "runtime_component", "cluster_component", *LIFECYCLE[3:]]
    categories = ["resource_preflight", "process_start", "cluster_formation", *LIFECYCLE[3:]]
    segments = [
        {"name": name, "category": category, "kind": "span", "status": "PASS", "start_monotonic": float(index + 1), "end_monotonic": float(index + 1.5)}
        for index, (name, category) in enumerate(zip(names, categories))
    ]
    exact_gate._write_measured_lifecycle(
        runtime,
        "run-1",
        50,
        SimpleNamespace(segments=segments),  # type: ignore[arg-type]
        LIFECYCLE,
    )
    artifact = json.loads((runtime / "lifecycle_timeline.json").read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in artifact["steps"]}
    assert set(by_id) == set(LIFECYCLE)
    assert all(row["duration_ms"] > 0 for row in by_id.values())
    assert by_id["resource_preflight"]["ended_monotonic_ms"] <= by_id["runtime_start"]["started_monotonic_ms"]
