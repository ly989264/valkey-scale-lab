from __future__ import annotations

import hashlib
import json
from pathlib import Path

from valkey_scale_lab.gates import real as exact_gate
from valkey_scale_lab.evidence import canonical_bundle_spec
from valkey_scale_lab.scenarios import load_local_full_flow_definition


RUN_ID = "measured-source-run"
STARTED = 1_800_000_000_000
DEFINITION = load_local_full_flow_definition()
SPEC = canonical_bundle_spec(DEFINITION)
SCENARIOS = [*SPEC.management_scenario_ids, *SPEC.fault_scenario_ids]
LIFECYCLE = list(SPEC.lifecycle_ids)


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _bundle(root: Path) -> Path:
    runtime = root / "runtime"
    runtime.mkdir()
    common = {"schema_version": "v1", "status": "PASS", "run_id": RUN_ID, "node_count": 50}
    events: list[dict] = []
    management_commands: list[dict] = []
    fault_commands: list[dict] = []
    scenarios: list[dict] = []
    for index, scenario_id in enumerate(SCENARIOS):
        operation_id = f"observed-{scenario_id}"
        event_id = f"event-{scenario_id}"
        command_id = f"command-{scenario_id}"
        events.append(
            {
                "schema_version": "v1",
                "run_id": RUN_ID,
                "event_id": event_id,
                "event_type": "scenario_observed",
                "operation_id": operation_id,
                "scenario_id": scenario_id,
                "timestamp_unix_ms": STARTED + index,
                "monotonic_ms": float(index + 1),
            }
        )
        command = {
            "schema_version": "v1",
            "run_id": RUN_ID,
            "command_id": command_id,
            "command_kind": "observed_operation",
            "operation_id": operation_id,
            "scenario_id": scenario_id,
            "status": "PASS",
            "started_at_unix_ms": STARTED + 100 + index,
            "ended_at_unix_ms": STARTED + 101 + index,
        }
        (management_commands if index < 4 else fault_commands).append(command)
        scenarios.append(
            {
                "id": scenario_id,
                "run_id": RUN_ID,
                "status": "REAL_PASS",
                "event_ids": [event_id],
                "command_ids": [command_id],
                "evidence_refs": ["runtime/management_sequence.json" if index < 4 else "runtime/fault_sequence.json"],
            }
        )
    lifecycle_steps: list[dict] = []
    for index, step_id in enumerate(LIFECYCLE):
        event_id = f"lifecycle-{step_id}"
        events.append(
            {
                "schema_version": "v1",
                "run_id": RUN_ID,
                "event_id": event_id,
                "event_type": "lifecycle_step_measured",
                "operation_id": f"lifecycle:{step_id}",
                "scenario_id": "lifecycle",
                "step_id": step_id,
                "timestamp_unix_ms": STARTED + 300 + index,
                "monotonic_ms": float(100 + index * 10 + 5),
            }
        )
        lifecycle_steps.append(
            {
                "id": step_id,
                "run_id": RUN_ID,
                "status": "PASS",
                "started_monotonic_ms": float(100 + index * 10),
                "ended_monotonic_ms": float(100 + index * 10 + 5),
                "event_ids": [event_id],
            }
        )
    surfaces = {name: {} for name in {"topology_summary", "lifecycle_durations", "bottlenecks", "resources", "workload_impact", "failover", "recovery", "error_summary", "missing_evidence"}}
    # Item 1.3's host evidence, in the shape a real run writes: one row per
    # nodehost, every observed node journalled exactly once, and both ends of
    # the run clocked with the offset's own bound beside it.
    journal_rows: dict[str, list[dict]] = {"nodehost-a": [], "nodehost-b": []}
    for index in range(50):
        logical_id = f"node-{index}"
        nodehost_id = "nodehost-a" if index < 25 else "nodehost-b"
        host_id = "host-a" if index < 25 else "host-b"
        journal = runtime / "node_journals" / host_id / f"{logical_id}.log"
        journal.parent.mkdir(parents=True, exist_ok=True)
        payload = f"{logical_id} started\n".encode("utf-8")
        journal.write_bytes(payload)
        journal_rows[nodehost_id].append(
            {
                "logical_id": logical_id,
                "path": f"runtime/node_journals/{host_id}/{logical_id}.log",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
        )
    host_evidence_rows = [
        {
            "nodehost_id": nodehost_id,
            "host_id": host_id,
            "clock": {
                boundary: {
                    "controller_unix_ms": float(STARTED),
                    "host_unix_ms": float(STARTED),
                    "host_monotonic_seconds": 100.0,
                    "offset_ms": 0.0,
                    "uncertainty_ms": 4.0,
                    "round_trip_ms": 8.0,
                    "exchanges": 3,
                }
                for boundary in ("start", "end")
            },
            "journals": journal_rows[nodehost_id],
            "resource_sampler_ids": [nodehost_id],
            "load_lane_dirs": ["runtime/load_lane"] if nodehost_id == "nodehost-a" else [],
        }
        for nodehost_id, host_id in (("nodehost-a", "host-a"), ("nodehost-b", "host-b"))
    ]
    objects = {
        "run_state.json": {
            **common,
            "nodes": [{"logical_id": f"node-{index}"} for index in range(50)],
            "nodehosts": [{"nodehost_id": "nodehost-a"}, {"nodehost_id": "nodehost-b"}],
        },
        "host_evidence.json": {
            **common,
            "artifact_type": "host_evidence",
            "fleet_ids": ["fleet-a"],
            "host_count": 2,
            "hosts": host_evidence_rows,
            "timing": {"clock_start_seconds": 0.1, "clock_end_seconds": 0.1},
        },
        "resource_preflight.json": {**common, "run_id": "preflight-run", "can_run": True, "nodes_requested": 50},
        "workload_windows.json": {**common, "windows": [{"status": "PASS"}]},
        "lifecycle_timeline.json": {**common, "steps": lifecycle_steps},
        "scenario_results.json": {**common, "scenarios": scenarios},
        "management_sequence.json": common,
        "fault_sequence.json": {**common, "recovery_health": {"status": "PASS"}},
        "cleanup_report.json": {**common, "resources_remaining": [], "cleanup_errors": []},
        "analysis_summary.json": {**common, **surfaces},
        "report_index.json": {**common, "views": [{"status": "PASS", "path": "analysis_summary.json"}]},
        "full_flow_result.json": common,
    }
    for name, value in objects.items():
        _json(runtime / name, value)
    _jsonl(runtime / "management_command_log.jsonl", management_commands)
    _jsonl(runtime / "fault_command_log.jsonl", fault_commands)
    _jsonl(runtime / "events.jsonl", events)
    _jsonl(runtime / "metrics_timeseries.jsonl", [{"run_id": RUN_ID, "metric_name": "used_memory", "metric_value": 1, "timestamp_unix_ms": STARTED + 500}])
    return root


def test_builder_preserves_measured_scenario_and_lifecycle_provenance(tmp_path: Path) -> None:
    base = _bundle(tmp_path)
    admission = exact_gate.build_admission_from_sources(
        base,
        50,
        "a" * 64,
        definition=DEFINITION,
        run_started_unix_ms=STARTED,
        run_ended_unix_ms=STARTED + 1000,
        valkey_versions=["9.1.0"],
        independent_probe={"cluster_state": "ok", "known_nodes": 50, "slots_assigned": 16384, "slots_ok": 16384},
    )
    scenarios = json.loads((base / "runtime/admission_v2/scenario_results.json").read_text(encoding="utf-8"))["scenarios"]
    lifecycle = json.loads((base / "runtime/admission_v2/lifecycle_timeline.json").read_text(encoding="utf-8"))["steps"]
    assert admission["status"] == "PASS"
    assert [row["id"] for row in scenarios] == SCENARIOS
    assert all(row["ended_monotonic_ms"] > row["started_monotonic_ms"] for row in lifecycle)


def test_source_validation_rejects_zero_duration_pass(tmp_path: Path) -> None:
    base = _bundle(tmp_path)
    path = base / "runtime/lifecycle_timeline.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["steps"][3]["ended_monotonic_ms"] = value["steps"][3]["started_monotonic_ms"]
    _json(path, value)
    assert any(
        "positive measured" in error
        for error in exact_gate.validate_admission_sources(base, 50, DEFINITION)
    )
