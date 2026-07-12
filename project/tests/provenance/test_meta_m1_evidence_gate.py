from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import meta_m1_evidence_gate as gate


RUN_ID = "meta-m1-test-run"
RUN_STARTED = 1_800_000_000_000
RUN_ENDED = RUN_STARTED + 10_000


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_complete_bundle(root: Path, scale: int = 50) -> Path:
    base = root / f"scale-{scale}"
    runtime = base / "runtime"
    scenario_events = {name: f"event-scenario-{index}" for index, name in enumerate(sorted(gate.REQUIRED_SCENARIOS))}
    lifecycle_events = {name: f"event-lifecycle-{index}" for index, name in enumerate(sorted(gate.REQUIRED_LIFECYCLE))}
    scenario_commands = {name: f"command-{index}" for index, name in enumerate(sorted(gate.REQUIRED_SCENARIOS))}
    events = [
        {"schema_version": "v1", "run_id": RUN_ID, "event_id": event_id, "event_type": "scenario_observed", "scenario_id": name, "monotonic_ms": index, "timestamp_unix_ms": RUN_STARTED + index}
        for index, (name, event_id) in enumerate(scenario_events.items())
    ] + [
        {"schema_version": "v1", "run_id": RUN_ID, "event_id": event_id, "event_type": "lifecycle_observed", "step_id": name, "monotonic_ms": index + 100, "timestamp_unix_ms": RUN_STARTED + index + 100}
        for index, (name, event_id) in enumerate(lifecycle_events.items())
    ]
    commands = [
        {"schema_version": "v1", "run_id": RUN_ID, "command_id": command_id, "scenario_id": name, "status": "PASS", "timestamp_unix_ms": RUN_STARTED + index + 200}
        for index, (name, command_id) in enumerate(scenario_commands.items())
    ]
    _write_jsonl(runtime / "events.jsonl", events)
    _write_jsonl(runtime / "management_command_log.jsonl", commands[:7])
    _write_jsonl(runtime / "fault_command_log.jsonl", commands[7:])
    _write_jsonl(runtime / "metrics_timeseries.jsonl", [{"schema_version": "v1", "run_id": RUN_ID, "metric_name": "used_memory", "metric_value": 1, "timestamp_unix_ms": RUN_STARTED + 300}])

    common = {"schema_version": "v1", "status": "PASS", "run_id": RUN_ID, "node_count": scale, "created_at_unix_ms": RUN_STARTED + 500}
    objects = {
        "run_state.json": {**common, "artifact_type": "run_state", "nodes": [{"logical_id": f"node-{i}"} for i in range(scale)]},
        "resource_preflight.json": {**common, "artifact_type": "resource_preflight", "can_run": True, "nodes_requested": scale, "checks": [{"name": "memory", "status": "PASS"}]},
        "workload_windows.json": {**common, "artifact_type": "workload_windows", "windows": [{"window_name": "baseline", "status": "PASS"}]},
        "lifecycle_timeline.json": {
            **common,
            "artifact_type": "lifecycle_timeline",
            "steps": [
                {"id": name, "run_id": RUN_ID, "status": "PASS", "started_monotonic_ms": index * 10, "ended_monotonic_ms": index * 10 + 5, "event_ids": [lifecycle_events[name]]}
                for index, name in enumerate(sorted(gate.REQUIRED_LIFECYCLE))
            ],
        },
        "scenario_results.json": {
            **common,
            "artifact_type": "scenario_results",
            "scenarios": [
                {"id": name, "run_id": RUN_ID, "status": "REAL_PASS", "event_ids": [scenario_events[name]], "command_ids": [scenario_commands[name]], "evidence_refs": ["runtime/events.jsonl"]}
                for name in sorted(gate.REQUIRED_SCENARIOS)
            ],
        },
        "management_results.json": {**common, "artifact_type": "management_results", "operation_results": [{"id": "remove_replica", "status": "REAL_PASS"}]},
        "fault_results.json": {**common, "artifact_type": "fault_results", "fault_results": [{"id": "primary_failover", "status": "REAL_PASS"}]},
        "stability_results.json": {**common, "artifact_type": "stability_results", "health": {"status": "PASS"}},
        "cleanup_report.json": {**common, "artifact_type": "cleanup_report", "resources_remaining": [], "cleanup_errors": []},
        "analysis_summary.json": {**common, "artifact_type": "analysis_summary", **{name: {} for name in gate.REPORT_SURFACES}},
        "report_index.json": {**common, "artifact_type": "report_index", "views": [{"format": "json", "path": "analysis_summary.json", "status": "PASS"}]},
    }
    for name, value in objects.items():
        _write_json(runtime / name, value)

    paths = {
        "run_metadata": "runtime/run_state.json",
        "resource_preflight": "runtime/resource_preflight.json",
        "command_log": "runtime/management_command_log.jsonl",
        "fault_command_log": "runtime/fault_command_log.jsonl",
        "events": "runtime/events.jsonl",
        "metrics": "runtime/metrics_timeseries.jsonl",
        "workload_windows": "runtime/workload_windows.json",
        "lifecycle_timeline": "runtime/lifecycle_timeline.json",
        "scenario_results": "runtime/scenario_results.json",
        "management_results": "runtime/management_results.json",
        "fault_results": "runtime/fault_results.json",
        "stability_results": "runtime/stability_results.json",
        "cleanup_report": "runtime/cleanup_report.json",
        "analysis_summary": "runtime/analysis_summary.json",
        "report_index": "runtime/report_index.json",
    }
    admission = {
        "schema_version": "meta-m1-admission-v2",
        "execution_kind": "REAL_VALKEY_EXACT_SCALE",
        "run_id": RUN_ID,
        "run_nonce": "b" * 32,
        "run_started_unix_ms": RUN_STARTED,
        "run_ended_unix_ms": RUN_ENDED,
        "source_commit": "a" * 40,
        "product_digest": gate.product_tree_digest(gate.PROJECT_ROOT),
        "requested_nodes": scale,
        "observed_nodes": scale,
        "status": "PASS",
        "valkey_versions": ["9.1.0"],
        "independent_probe": {"status": "PASS", "observed_nodes": scale, "cluster_state": "ok", "slots_assigned": 16384, "slots_ok": 16384, "endpoint_count": 2},
        "cleanup": {"status": "PASS", "residual_owned_resources": 0},
        "artifacts": [{"kind": kind, "path": raw, "sha256": _hash(base / raw)} for kind, raw in paths.items()],
    }
    _write_json(base / "admission.json", admission)
    return base


def _rehash(base: Path, kind: str) -> None:
    admission = json.loads((base / "admission.json").read_text(encoding="utf-8"))
    item = next(value for value in admission["artifacts"] if value["kind"] == kind)
    item["sha256"] = _hash(base / item["path"])
    _write_json(base / "admission.json", admission)


def test_complete_semantic_bundle_passes(tmp_path: Path) -> None:
    build_complete_bundle(tmp_path)
    assert gate.evaluate(50, tmp_path) == []


def test_rejects_non_json_report_even_when_rehashed(tmp_path: Path) -> None:
    base = build_complete_bundle(tmp_path)
    (base / "runtime/report_index.json").write_text("not JSON\n", encoding="utf-8")
    _rehash(base, "report_index")
    assert any("report_index" in error and "JSON" in error for error in gate.evaluate(50, tmp_path))


def test_rejects_invalid_jsonl_even_when_rehashed(tmp_path: Path) -> None:
    base = build_complete_bundle(tmp_path)
    (base / "runtime/events.jsonl").write_text("not JSON\n", encoding="utf-8")
    _rehash(base, "events")
    assert any("events:1" in error and "JSON" in error for error in gate.evaluate(50, tmp_path))


def test_rejects_hardcoded_scenario_without_observation_refs(tmp_path: Path) -> None:
    base = build_complete_bundle(tmp_path)
    path = base / "runtime/scenario_results.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["scenarios"][0]["command_ids"] = ["invented-command"]
    _write_json(path, value)
    _rehash(base, "scenario_results")
    assert any("existing command_ids" in error for error in gate.evaluate(50, tmp_path))


def test_rejects_unmeasured_lifecycle_timing(tmp_path: Path) -> None:
    base = build_complete_bundle(tmp_path)
    path = base / "runtime/lifecycle_timeline.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["steps"][0].pop("started_monotonic_ms")
    _write_json(path, value)
    _rehash(base, "lifecycle_timeline")
    assert any("measured monotonic bounds" in error for error in gate.evaluate(50, tmp_path))


def test_rejects_stale_product_digest(tmp_path: Path) -> None:
    base = build_complete_bundle(tmp_path)
    path = base / "admission.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["product_digest"] = "0" * 64
    _write_json(path, value)
    assert any("product_digest" in error for error in gate.evaluate(50, tmp_path))


def test_rejects_artifact_timestamp_outside_measured_run(tmp_path: Path) -> None:
    base = build_complete_bundle(tmp_path)
    path = base / "runtime/analysis_summary.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["created_at_unix_ms"] = 1
    _write_json(path, value)
    _rehash(base, "analysis_summary")
    assert any("analysis_summary.created_at_unix_ms" in error for error in gate.evaluate(50, tmp_path))


def test_rejects_report_surface_that_does_not_show_evidence(tmp_path: Path) -> None:
    base = build_complete_bundle(tmp_path)
    path = base / "runtime/analysis_summary.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["topology_summary"] = None
    _write_json(path, value)
    _rehash(base, "analysis_summary")

    assert any("topology_summary" in error for error in gate.evaluate(50, tmp_path))
