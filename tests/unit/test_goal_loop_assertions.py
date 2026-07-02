from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType

from valkey_scale_lab.metrics import MISSING, TelemetryRun, workload_metrics


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, Path("scripts") / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_goal_loop_manifest_policy_allows_only_named_exceptions() -> None:
    gate = load_script("codex_gate")
    manifest = gate.load_manifest()

    assert gate.validate_manifest(manifest) == []

    by_id = {phase["id"]: phase for phase in manifest["phases"]}
    assert by_id["P15_GOAL_REBASE_HARNESS_EXTENSION"]["real_valkey_required"] is False
    assert by_id["P21_FAILOVER_LATENCY_CURVE_200"]["max_nodes"] == 200

    mutated = copy.deepcopy(manifest)
    by_id = {phase["id"]: phase for phase in mutated["phases"]}
    by_id["P22_FAULT_REPLICA_HOST_AZ_STOP"]["max_nodes"] = 200
    errors = gate.validate_manifest(mutated)
    assert any("P22_FAULT_REPLICA_HOST_AZ_STOP exceeds default 100-node cap" in error for error in errors)


def test_goal_loop_manifest_rejects_recursive_run_and_postcheck_gates() -> None:
    gate = load_script("codex_gate")
    manifest = gate.load_manifest()
    mutated = copy.deepcopy(manifest)
    phase = next(p for p in mutated["phases"] if p["id"] == "P15_GOAL_REBASE_HARNESS_EXTENSION")
    phase["gates"].append(
        {
            "name": "bad_recursive_gate",
            "kind": "harness",
            "command": "python3 scripts/codex_gate.py run --phase P15_GOAL_REBASE_HARNESS_EXTENSION",
            "timeout_seconds": 120,
            "required": True,
            "real_valkey": False,
        }
    )

    errors = gate.validate_manifest(mutated)
    assert any("recursive codex_gate run/postcheck is not allowed" in error for error in errors)


def test_goal_loop_manifest_preserves_p14_non_automatic() -> None:
    gate = load_script("codex_gate")
    manifest = gate.load_manifest()
    mutated = copy.deepcopy(manifest)
    phase = next(p for p in mutated["phases"] if p["id"] == "P14_SCALE_1000_OPTIN_DRYRUN")
    phase["automatic"] = True

    errors = gate.validate_manifest(mutated)
    assert any("P14 must not be automatic" in error for error in errors)


def test_goal_loop_assertion_stage_table_matches_manifest() -> None:
    assertion = load_script("assert_goal_loop_stage")
    gate = load_script("codex_gate")
    manifest = gate.load_manifest()
    phases = assertion.phase_map(manifest)

    expected_ids = [stage["id"] for stage in assertion.GOAL_STAGES]
    assert expected_ids == [phase["id"] for phase in manifest["phases"][-12:]]
    assert phases["P15_GOAL_REBASE_HARNESS_EXTENSION"]["fake_only_allowed"] is True
    assert phases["P21_FAILOVER_LATENCY_CURVE_200"]["max_nodes"] == 200
    p21_real_gates = [gate for gate in phases["P21_FAILOVER_LATENCY_CURVE_200"]["gates"] if gate.get("real_valkey")]
    assert p21_real_gates
    for gate_entry in p21_real_gates:
        command = gate_entry["command"]
        assert "scale_100.yaml" not in command
        assert "scale_200.yaml" in command
        assert "--min-nodes 200" in command


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def minimal_p16_artifacts(base: Path) -> None:
    telemetry = TelemetryRun(
        phase_id="P16_QUANT_TELEMETRY_UNIFICATION",
        scenario_name="goal_loop_quant_telemetry",
        run_id="run",
    )
    events = [
        telemetry.event(
            "workload_window_started",
            subject_type="workload_window",
            subject_id=name,
            message=f"{name} start",
            metadata={"window_name": name},
        )
        for name in ["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]
    ]
    finish_events = [
        telemetry.event(
            "workload_window_finished",
            subject_type="workload_window",
            subject_id=name,
            message=f"{name} end",
            metadata={"window_name": name},
        )
        for name in ["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]
    ]
    events.extend(finish_events)
    metric_rows = []
    for idx in range(6):
        metric_rows.append(
            telemetry.metric(
                source_type="valkey_info",
                source_id=f"node-{idx}",
                metric_name="valkey_info_sample",
                metric_value=True,
                metric_unit="status",
            )
        )
    metric_rows.append(
        telemetry.metric(
            source_type="cluster_info",
            source_id="node-0",
            metric_name="cluster_state",
            metric_value="ok",
            metric_unit="state",
        )
    )
    metric_rows.append(
        telemetry.metric(
            source_type="cluster_nodes",
            source_id="node-0",
            metric_name="cluster_nodes_line_count",
            metric_value=6,
            metric_unit="count",
        )
    )
    metric_rows.append(
        telemetry.metric(
            source_type="workload",
            source_id="baseline",
            metric_name="sample_count",
            metric_value=1,
            metric_unit="count",
            labels={"window_name": "baseline"},
        )
    )
    write_jsonl(base / "events.jsonl", events)
    write_jsonl(base / "metrics_timeseries.jsonl", metric_rows)
    metrics = workload_metrics(requested_qps=1.0, duration_seconds=1.0, latencies_ms=[1.0], error_texts=[])
    windows = []
    for idx, name in enumerate(["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]):
        windows.append(
            {
                "window_name": name,
                "start_event_id": events[idx]["event_id"],
                "end_event_id": finish_events[idx]["event_id"],
                "metrics": metrics,
            }
        )
    write_json(
        base / "workload_windows.json",
        {
            "schema_version": "v1",
            "artifact_type": "workload_windows",
            "phase_id": "P16_QUANT_TELEMETRY_UNIFICATION",
            "run_id": "run",
            "windows": windows,
        },
    )
    write_json(
        base / "valkey_e2e_evidence.json",
        {
            "status": "PASS",
            "nodes_observed": 6,
            "probes": [{"status": "PASS", "logical_id": f"node-{idx}"} for idx in range(6)],
        },
    )
    write_json(
        base / "quant_summary.json",
        {
            "runtime_claims": {
                "real_valkey_claimed": True,
                "management_runtime_claimed": False,
                "fault_runtime_claimed": False,
            },
            "counts": {
                "event_count": len(events),
                "metric_count": len(metric_rows),
            },
        },
    )


def test_p16_quant_assertion_accepts_minimal_valid_artifacts(tmp_path: Path) -> None:
    assertion = load_script("assert_quant_artifacts")
    minimal_p16_artifacts(tmp_path)

    errors: list[str] = []
    assertion.assert_p16_semantics(tmp_path, errors)

    assert errors == []


def test_p16_quant_assertion_requires_info_sample_per_live_node(tmp_path: Path) -> None:
    assertion = load_script("assert_quant_artifacts")
    minimal_p16_artifacts(tmp_path)
    rows = [
        json.loads(line)
        for line in (tmp_path / "metrics_timeseries.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    rows = [row for row in rows if not (row.get("source_type") == "valkey_info" and row.get("source_id") == "node-5")]
    write_jsonl(tmp_path / "metrics_timeseries.jsonl", rows)

    errors: list[str] = []
    assertion.assert_p16_semantics(tmp_path, errors)

    assert any("valkey_info metric per live node" in error for error in errors)


def test_p16_quant_assertion_requires_workload_missing_reason(tmp_path: Path) -> None:
    assertion = load_script("assert_quant_artifacts")
    minimal_p16_artifacts(tmp_path)
    workload = json.loads((tmp_path / "workload_windows.json").read_text(encoding="utf-8"))
    workload["windows"][0]["metrics"]["latency_p99_ms"] = MISSING
    workload["windows"][0]["metrics"]["missing_reasons"].pop("latency_p99_ms", None)
    write_json(tmp_path / "workload_windows.json", workload)

    errors: list[str] = []
    assertion.assert_p16_semantics(tmp_path, errors)

    assert any("MISSING metric latency_p99_ms requires" in error for error in errors)


def test_workload_metrics_encode_empty_latency_as_missing_with_reason() -> None:
    metrics = workload_metrics(requested_qps=1.0, duration_seconds=1.0, latencies_ms=[], error_texts=[])

    assert metrics["latency_p99_ms"] == MISSING
    assert metrics["missing_reasons"]["latency_p99_ms"]
