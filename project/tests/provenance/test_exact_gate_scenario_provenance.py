from __future__ import annotations

import json
from pathlib import Path

import pytest

from valkey_scale_lab.gates import real as exact_gate
from valkey_scale_lab.runtime.docker_runtime import DockerRuntimeError
from valkey_scale_lab.evidence import canonical_bundle_spec
from valkey_scale_lab.scenarios import load_local_full_flow_definition


RUN_ID = "review-scenario-provenance"
NOW_MS = 1_800_000_000_000
REPORT_SURFACES = {
    "topology_summary",
    "phase_durations",
    "bottlenecks",
    "resources",
    "workload_impact",
    "failover",
    "recovery",
    "error_summary",
    "missing_evidence",
}
DEFINITION = load_local_full_flow_definition()
SCENARIOS = [
    *canonical_bundle_spec(DEFINITION).management_scenario_ids,
    *canonical_bundle_spec(DEFINITION).fault_scenario_ids,
]


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_rejects_unclassified_source_rows_instead_of_inventing_scenario_provenance(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    common = {"schema_version": "v1", "status": "PASS", "run_id": RUN_ID, "node_count": 50}
    objects = {
        "run_state.json": {**common, "nodes": [{"logical_id": f"node-{index}"} for index in range(50)]},
        "resource_preflight.json": {**common, "can_run": True, "nodes_requested": 50},
        "workload_windows.json": common,
        "management_sequence.json": common,
        "fault_sequence.json": {**common, "recovery_health": {"status": "PASS"}},
        "cleanup_report.json": {**common, "resources_remaining": [], "cleanup_errors": []},
        "analysis_summary.json": {
            **common,
            **{surface: {} for surface in REPORT_SURFACES},
        },
        "report_index.json": common,
        "full_flow_result.json": common,
    }
    for name, value in objects.items():
        _write_json(runtime / name, value)

    # These rows deliberately contain no scenario identity. Fourteen generic
    # rows are enough for the current builder to assign one to every scenario
    # by list position, which turns absence of evidence into claimed evidence.
    commands = [
        {
            "schema_version": "v1",
            "run_id": RUN_ID,
            "command_id": f"generic-command-{index}",
            "command_kind": "ping",
            "status": "PASS",
            "ended_at_unix_ms": NOW_MS + index,
        }
        for index in range(len(SCENARIOS))
    ]
    events = [
        {
            "schema_version": "v1",
            "run_id": RUN_ID,
            "event_id": f"generic-event-{index}",
            "event_type": "heartbeat",
            "timestamp_unix_ms": NOW_MS + index,
            "monotonic_ms": float(index),
        }
        for index in range(len(SCENARIOS))
    ]
    _write_jsonl(runtime / "management_command_log.jsonl", commands[:4])
    _write_jsonl(runtime / "fault_command_log.jsonl", commands[4:])
    _write_jsonl(runtime / "events.jsonl", events)
    _write_jsonl(
        runtime / "metrics_timeseries.jsonl",
        [{"schema_version": "v1", "run_id": RUN_ID, "timestamp_unix_ms": NOW_MS, "metric_name": "used_memory", "metric_value": 1}],
    )

    with pytest.raises(DockerRuntimeError, match="scenario"):
        exact_gate.build_admission_from_sources(
            tmp_path,
            50,
            "a" * 64,
            definition=DEFINITION,
            valkey_versions=["9.1.0"],
            independent_probe={
                "cluster_state": "ok",
                "known_nodes": 50,
                "slots_assigned": 16384,
                "slots_ok": 16384,
            },
        )
