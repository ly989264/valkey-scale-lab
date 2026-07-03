from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

from valkey_scale_lab.metrics import MISSING, TelemetryRun, workload_metrics, write_jsonl as metrics_write_jsonl


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
    manifest_ids = [phase["id"] for phase in manifest["phases"]]
    positions = [manifest_ids.index(stage_id) for stage_id in expected_ids]
    assert positions == sorted(positions)
    assert phases["P15_GOAL_REBASE_HARNESS_EXTENSION"]["fake_only_allowed"] is True
    assert phases["P21_FAILOVER_LATENCY_CURVE_200"]["max_nodes"] == 200
    p21_real_gates = [gate for gate in phases["P21_FAILOVER_LATENCY_CURVE_200"]["gates"] if gate.get("real_valkey")]
    assert p21_real_gates
    for gate_entry in p21_real_gates:
        command = gate_entry["command"]
        assert "scale_100.yaml" not in command
        assert "scale_200.yaml" in command
        assert "--min-nodes 200" in command


def test_strict_manifest_policy_appends_p27_p40_and_preserves_caps() -> None:
    gate = load_script("codex_gate")
    strict = load_script("assert_strict_stage_contract")
    manifest = gate.load_manifest()

    assert gate.validate_manifest(manifest) == []
    assert strict.validate_strict_contract("P27_STRICT_MATRIX_REBASE_HARNESS") == []

    by_id = {phase["id"]: phase for phase in manifest["phases"]}
    assert manifest["automatic_stop_after"] == "P40_STRICT_FINAL_AUDIT_CLOSEOUT"
    assert manifest["default_max_nodes"] == 100
    assert by_id["P14_SCALE_1000_OPTIN_DRYRUN"]["automatic"] is False
    assert by_id["P32_MANAGEMENT_MATRIX_200_REAL"]["max_nodes"] == 200
    assert by_id["P35_FAULT_FAILOVER_MATRIX_200_REAL"]["max_nodes"] == 200
    assert by_id["P36_FULL_FLOW_E2E_50_100_200_REAL"]["max_nodes"] == 200
    assert by_id["P37_200_PLUS_DRY_RUN_SUPPORT"]["execution_mode"] == "dry_run"
    assert by_id["P37_200_PLUS_DRY_RUN_SUPPORT"]["dry_run_target_nodes"] == [201, 250, 300, 500, 1000]


def test_p32_real_valkey_gate_has_bounded_inner_setup_timeout() -> None:
    gate = load_script("codex_gate")
    manifest = gate.load_manifest()

    by_id = {phase["id"]: phase for phase in manifest["phases"]}
    p32 = by_id["P32_MANAGEMENT_MATRIX_200_REAL"]
    real_gate = next(entry for entry in p32["gates"] if entry["name"] == "real_valkey_e2e")
    command = real_gate["command"]

    assert p32["max_nodes"] == 200
    assert real_gate["timeout_seconds"] == 7200
    assert "--scenario strict_management_matrix_200" in command
    assert "--config templates/configs/scale_200.yaml" in command
    assert "--min-nodes 200" in command
    assert "--setup-timeout 2400" in command
    assert "--probe-timeout 10" in command


def test_strict_manifest_rejects_default_raise_and_extra_200_exception() -> None:
    gate = load_script("codex_gate")
    manifest = gate.load_manifest()

    mutated = copy.deepcopy(manifest)
    mutated["default_max_nodes"] = 200
    errors = gate.validate_manifest(mutated)
    assert any("default_max_nodes must be exactly 100" in error for error in errors)

    mutated = copy.deepcopy(manifest)
    by_id = {phase["id"]: phase for phase in mutated["phases"]}
    by_id["P34_FAULT_FAILOVER_MATRIX_100_REAL"]["max_nodes"] = 200
    errors = gate.validate_manifest(mutated)
    assert any("P34_FAULT_FAILOVER_MATRIX_100_REAL exceeds default 100-node cap" in error for error in errors)


def test_strict_contract_fails_closed_on_missing_stage(tmp_path: Path) -> None:
    strict = load_script("assert_strict_stage_contract")
    manifest = load_script("codex_gate").load_manifest()
    mutated = copy.deepcopy(manifest)
    mutated["phases"] = [phase for phase in mutated["phases"] if phase["id"] != "P40_STRICT_FINAL_AUDIT_CLOSEOUT"]
    path = tmp_path / "manifest.json"
    write_json(path, mutated)

    errors = strict.validate_strict_contract("P27_STRICT_MATRIX_REBASE_HARNESS", path)

    assert any("missing strict stages" in error for error in errors)


def test_no_bypass_rejects_pass_only_gate_and_200_downshift(tmp_path: Path) -> None:
    bypass = load_script("assert_no_bypass")
    manifest = load_script("codex_gate").load_manifest()
    mutated = copy.deepcopy(manifest)
    by_id = {phase["id"]: phase for phase in mutated["phases"]}
    by_id["P32_MANAGEMENT_MATRIX_200_REAL"]["gates"].append(
        {
            "name": "bad",
            "kind": "harness",
            "command": "echo PASS",
            "timeout_seconds": 1,
            "required": True,
            "real_valkey": False,
        }
    )
    for gate in by_id["P32_MANAGEMENT_MATRIX_200_REAL"]["gates"]:
        gate["command"] = gate["command"].replace("--nodes 200", "--nodes 100")
    path = tmp_path / "manifest.json"
    write_json(path, mutated)

    errors = bypass.validate_manifest_for_bypass("P32_MANAGEMENT_MATRIX_200_REAL", path)

    assert any("PASS-only command" in error for error in errors)
    assert any("downshift" in error for error in errors)


def test_exact_scale_evidence_fails_closed_on_missing_artifacts() -> None:
    import subprocess

    proc = subprocess.run(
        [
            "python3",
            "scripts/assert_exact_scale_real_evidence.py",
            "--phase",
            "P99_MISSING_STRICT_REAL_STAGE",
            "--nodes",
            "50",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )

    assert proc.returncode == 1
    assert "real Valkey evidence missing" in proc.stderr


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


def test_strict_jsonl_writer_rejects_null_values(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"

    try:
        metrics_write_jsonl(path, [{"schema_version": "v1", "bad": None}])
    except ValueError as exc:
        assert "null is not an allowed telemetry value" in str(exc)
    else:
        raise AssertionError("write_jsonl accepted a null telemetry value")


def minimal_p29_artifacts(base: Path) -> None:
    phase = "P29_QUANT_TELEMETRY_COLLECTOR_HARDENING"
    telemetry = TelemetryRun(
        phase_id=phase,
        scenario_name="strict_telemetry_small_real",
        run_id="run-p29",
        coverage_id="p29.telemetry.strict_telemetry_small_real",
        scale=6,
        node_count=6,
    )
    events = []
    metric_rows = []
    for source_type in ["valkey_info", "cluster_info", "cluster_nodes", "docker_stats"]:
        metric_rows.append(
            telemetry.metric(
                source_type=source_type,
                source_id="node-0",
                metric_name=f"{source_type}_sample",
                metric_value=True,
                metric_unit="status",
            )
        )
    window_start_events = []
    window_finish_events = []
    windows = []
    for name in ["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]:
        start = telemetry.event(
            "workload_window_started",
            subject_type="workload_window",
            subject_id=name,
            message=f"{name} started",
            metadata={"window_name": name},
        )
        end = telemetry.event(
            "workload_window_finished",
            subject_type="workload_window",
            subject_id=name,
            message=f"{name} finished",
            metadata={"window_name": name},
        )
        events.extend([start, end])
        window_start_events.append(start)
        window_finish_events.append(end)
        metrics = workload_metrics(requested_qps=1.0, duration_seconds=1.0, latencies_ms=[1.0, 2.0], error_texts=[])
        metrics["window_start_event_id"] = start["event_id"]
        metrics["window_end_event_id"] = end["event_id"]
        windows.append(
            {
                "window_name": name,
                "start_event_id": start["event_id"],
                "end_event_id": end["event_id"],
                "window_start_event_id": start["event_id"],
                "window_end_event_id": end["event_id"],
                "status": "PASS",
                "metrics": metrics,
            }
        )
        metric_rows.append(
            telemetry.metric(
                source_type="workload",
                source_id=name,
                metric_name="sample_count",
                metric_value=2,
                metric_unit="count",
                labels={"window_name": name},
            )
        )
    write_jsonl(base / "events.jsonl", events)
    write_jsonl(base / "metrics_timeseries.jsonl", metric_rows)
    write_json(
        base / "workload_windows.json",
        {
            "schema_version": "v1",
            "artifact_type": "workload_windows",
            "phase_id": phase,
            "stage_id": phase,
            "run_id": "run-p29",
            "windows": windows,
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
                "node_count": 6,
                "event_count": len(events),
                "metric_count": len(metric_rows),
                "coverage_pass_count": 0,
            },
            "missing_data": [{"field": "large_scale_matrix_coverage", "status": "SKIPPED_WITH_REASON", "reason": "P29 does not claim matrix coverage."}],
        },
    )
    write_json(
        base / "coverage_ledger.json",
        {
            "stage_id": phase,
            "summary": {"real_runtime_claimed": False},
            "rows": [{"coverage_id": "50.lifecycle.telemetry_collect", "node_count": 50, "status": "PENDING"}],
        },
    )
    source_artifacts = []
    for name in ["events.jsonl", "metrics_timeseries.jsonl", "workload_windows.json", "quant_summary.json", "coverage_ledger.json"]:
        digest = hashlib.sha256((base / name).read_bytes()).hexdigest()
        source_artifacts.append({"path": f"artifacts/phases/{phase}/{name}", "sha256": digest, "status": "PASS"})
    write_json(
        base / "telemetry_completeness_report.json",
        {
            "status": "PASS",
            "node_count": 6,
            "scale": 6,
            "source_type_coverage": {
                source_type: {"status": "PASS", "row_count": 1}
                for source_type in ["valkey_info", "cluster_info", "cluster_nodes", "docker_stats", "workload"]
            },
            "schema_validations": [{"artifact": "events.jsonl", "status": "PASS"}],
            "provenance": {
                "source_artifacts": source_artifacts,
                "large_scale_coverage_claim": False,
                "matrix_rows_remain_pending": True,
            },
            "blocking_findings": [],
        },
    )
    write_json(base / "valkey_e2e_evidence.json", {"status": "PASS", "real_valkey": True, "nodes_observed": 6})
    write_json(base / "cleanup_report.json", {"status": "PASS"})


def test_p29_quant_completeness_accepts_strict_artifacts(tmp_path: Path) -> None:
    assertion = load_script("assert_quant_completeness")
    minimal_p29_artifacts(tmp_path)

    errors: list[str] = []
    assertion.assert_p29_semantics(tmp_path, errors)

    assert errors == []


def test_p29_quant_completeness_rejects_missing_metric_reason(tmp_path: Path) -> None:
    assertion = load_script("assert_quant_completeness")
    minimal_p29_artifacts(tmp_path)
    rows = [json.loads(line) for line in (tmp_path / "metrics_timeseries.jsonl").read_text(encoding="utf-8").splitlines()]
    rows[0]["metric_value"] = MISSING
    rows[0]["missing_reason"] = ""
    write_jsonl(tmp_path / "metrics_timeseries.jsonl", rows)

    errors: list[str] = []
    assertion.assert_p29_semantics(tmp_path, errors)

    assert any("MISSING metric requires missing_reason" in error for error in errors)


def test_p29_quant_completeness_rejects_coverage_pass_claim(tmp_path: Path) -> None:
    assertion = load_script("assert_quant_completeness")
    minimal_p29_artifacts(tmp_path)
    ledger = json.loads((tmp_path / "coverage_ledger.json").read_text(encoding="utf-8"))
    ledger["rows"][0]["status"] = "PASS"
    write_json(tmp_path / "coverage_ledger.json", ledger)

    errors: list[str] = []
    assertion.assert_p29_semantics(tmp_path, errors)

    assert any("must remain PENDING" in error for error in errors)


def p17_management_row(operation_name: str, node_count: int) -> dict:
    operation_id = f"{operation_name}-{node_count:02d}"
    return {
        "schema_version": "v1",
        "phase_id": "P17_MANAGEMENT_REMOVE_NODE",
        "operation_name": operation_name,
        "operation_id": operation_id,
        "node_count": node_count,
        "operation_status": "PASS",
        "started_at_unix_ms": 1,
        "ended_at_unix_ms": 2,
        "wall_ms": 1.0,
        "command_ms": 1.0,
        "convergence_ms": 1.0,
        "cluster_state_before": "ok",
        "cluster_state_after": "ok",
        "slots_before": 16384,
        "slots_after": 16384,
        "workload_window_ref": f"{operation_id}:event",
        "errors_by_type": {},
        "missing_fields": [],
        "real_execution_verified": True,
        "removed_node_absent": True,
        "removed_node_id": "node-id",
        "target_logical_id": "shard-0000-replica-00",
        "observed_nodes_after": node_count - 1,
        "removed_resource_cleanup": {"status": "PASS"},
        "sidecar_cleanup_status": "PASS",
    }


def write_p17_management_artifacts(base: Path, rows: list[dict]) -> None:
    phase = rows[0].get("phase_id", "P17_MANAGEMENT_REMOVE_NODE") if rows else "P17_MANAGEMENT_REMOVE_NODE"
    write_json(
        base / "management_ops_matrix.json",
        {
            "schema_version": "v1",
            "artifact_type": "management_ops_matrix",
            "phase_id": phase,
            "run_id": "run",
            "operations": [
                {
                    "operation_name": row["operation_name"],
                    "node_count": row["node_count"],
                    "operation_status": row["operation_status"],
                    "workload_window_ref": row["workload_window_ref"],
                }
                for row in rows
            ],
        },
    )
    write_jsonl(base / "management_operation_results.jsonl", rows)


def run_management_assertion(tmp_path: Path, monkeypatch, rows: list[dict], phase: str = "P17_MANAGEMENT_REMOVE_NODE") -> int:
    assertion = load_script("assert_management_ops_coverage")
    phase_dir = tmp_path / "artifacts" / "phases" / phase
    phase_dir.mkdir(parents=True, exist_ok=True)
    write_p17_management_artifacts(phase_dir, rows)
    if phase == "P18_MANAGEMENT_RESHARD_REBALANCE":
        write_jsonl(
            phase_dir / "reshard_slot_movements.jsonl",
            [
                {
                    "schema_version": "v1",
                    "phase_id": phase,
                    "run_id": "run",
                    "movement_id": f"{row['operation_id']}-move",
                    "operation_id": row["operation_id"],
                    "source_node_id": "source",
                    "target_node_id": "target",
                    "slot_start": 1,
                    "slot_end": 2,
                    "slot_count": 2,
                    "status": "PASS",
                }
                for row in rows
            ],
        )
        write_json(
            phase_dir / "rebalance_summary.json",
            {
                "schema_version": "v1",
                "artifact_type": "rebalance_summary",
                "phase_id": phase,
                "run_id": "run",
                "status": "PASS",
                "imbalance_before": 10.0,
                "imbalance_after": 5.0,
                "workload_impact_ref": "management_workload_impact.json",
            },
        )
    if phase == "P19_MANAGEMENT_ROLLING_RESTART":
        write_p19_rolling_restart_artifacts(phase_dir, rows)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_management_ops_coverage.py", "--phase", phase])
    return assertion.main()


def test_p17_management_assertion_requires_6_and_10_node_rows(tmp_path: Path, monkeypatch) -> None:
    rows = [
        p17_management_row("remove_replica", 6),
        p17_management_row("remove_primary_drained", 6),
        p17_management_row("remove_failed_node", 6),
    ]

    assert run_management_assertion(tmp_path, monkeypatch, rows) == 1


def test_p17_management_assertion_accepts_exact_required_rows(tmp_path: Path, monkeypatch) -> None:
    rows = [
        p17_management_row(operation, count)
        for operation in ["remove_replica", "remove_primary_drained", "remove_failed_node"]
        for count in [6, 10]
    ]

    assert run_management_assertion(tmp_path, monkeypatch, rows) == 0


def p18_management_row(operation_name: str, node_count: int) -> dict:
    row = p17_management_row(operation_name, node_count)
    operation_id = f"{operation_name}-{node_count:02d}"
    row.update(
        {
            "phase_id": "P18_MANAGEMENT_RESHARD_REBALANCE",
            "operation_id": operation_id,
            "workload_window_ref": f"{operation_id}:event",
            "slots_moved": 2,
            "slot_coverage_complete": True,
            "keys_moved": 1 if operation_name == "reshard_with_keys" else 0,
            "moved_keys_readable": True,
            "post_move_writable": True,
            "source_node_id": "source",
            "target_node_id": "target",
            "movement_ids": [f"{operation_id}-move"],
            "imbalance_before": 10.0 if operation_name == "rebalance_after_imbalance" else MISSING,
            "imbalance_after": 5.0 if operation_name == "rebalance_after_imbalance" else MISSING,
        }
    )
    return row


def test_p18_management_assertion_requires_exact_6_and_10_rows(tmp_path: Path, monkeypatch) -> None:
    rows = [
        p18_management_row("reshard_slot_range", 6),
        p18_management_row("reshard_with_keys", 6),
        p18_management_row("rebalance_after_imbalance", 6),
    ]

    assert run_management_assertion(tmp_path, monkeypatch, rows, phase="P18_MANAGEMENT_RESHARD_REBALANCE") == 1


def test_p18_management_assertion_rejects_noop_slot_movement(tmp_path: Path, monkeypatch) -> None:
    rows = [
        p18_management_row(operation, count)
        for operation in ["reshard_slot_range", "reshard_with_keys", "rebalance_after_imbalance"]
        for count in [6, 10]
    ]
    rows[0]["slots_moved"] = 0

    assert run_management_assertion(tmp_path, monkeypatch, rows, phase="P18_MANAGEMENT_RESHARD_REBALANCE") == 1


def test_p18_management_assertion_rejects_noop_rebalance(tmp_path: Path, monkeypatch) -> None:
    rows = [
        p18_management_row(operation, count)
        for operation in ["reshard_slot_range", "reshard_with_keys", "rebalance_after_imbalance"]
        for count in [6, 10]
    ]
    for row in rows:
        if row["operation_name"] == "rebalance_after_imbalance":
            row["imbalance_after"] = row["imbalance_before"]

    assert run_management_assertion(tmp_path, monkeypatch, rows, phase="P18_MANAGEMENT_RESHARD_REBALANCE") == 1


def p19_management_row(operation_name: str, node_count: int) -> dict:
    row = p17_management_row(operation_name, node_count)
    operation_id = f"{operation_name}-{node_count:02d}"
    row.update(
        {
            "phase_id": "P19_MANAGEMENT_ROLLING_RESTART",
            "operation_id": operation_id,
            "workload_window_ref": f"{operation_id}:event",
            "restart_count": node_count,
            "health_gate_count": node_count,
            "max_concurrent_restarts": 1,
            "safe_primary_path": "cluster_failover_takeover_before_owned_container_restart"
            if operation_name == "rolling_restart_primary_safe"
            else "replica_first_owned_container_restart",
        }
    )
    return row


def p19_nodes(node_count: int) -> list[dict]:
    primaries = node_count // 2
    nodes: list[dict] = []
    for shard in range(primaries):
        nodes.append({"logical_node_id": f"shard-{shard:04d}-primary", "planned_role": "primary", "shard_id": f"shard-{shard:04d}"})
        nodes.append({"logical_node_id": f"shard-{shard:04d}-replica-00", "planned_role": "replica", "shard_id": f"shard-{shard:04d}"})
    return nodes


def p19_order(operation_name: str, node_count: int) -> list[dict]:
    nodes = p19_nodes(node_count)
    if operation_name == "rolling_restart_replica_first":
        ordered = sorted(nodes, key=lambda item: (0 if item["planned_role"] == "replica" else 1, item["shard_id"], item["logical_node_id"]))
    else:
        ordered = sorted(nodes, key=lambda item: (item["shard_id"], 0 if item["planned_role"] == "primary" else 1, item["logical_node_id"]))
    return [{**node, "sequence": index, "container_name": f"container-{node['logical_node_id']}"} for index, node in enumerate(ordered, start=1)]


def p19_restart_result(operation_name: str, node_count: int, entry: dict, base_ms: int) -> dict:
    operation_id = f"{operation_name}-{node_count:02d}"
    role_before = entry["planned_role"]
    missing_fields = []
    if operation_name == "rolling_restart_primary_safe" and role_before != "primary":
        missing_fields = [
            {"field": "promotion_latency_ms", "status": MISSING, "reason": "Target was not primary at restart time."},
            {"field": "cluster_recovery_latency_ms", "status": MISSING, "reason": "Target was not primary at restart time."},
        ]
    if operation_name == "rolling_restart_primary_safe":
        missing_fields.extend(
            [
                {"field": "read_unavailability_ms", "status": MISSING, "reason": "No read outage observed."},
                {"field": "write_unavailability_ms", "status": MISSING, "reason": "No write outage observed."},
            ]
        )
    return {
        "schema_version": "v1",
        "phase_id": "P19_MANAGEMENT_ROLLING_RESTART",
        "run_id": "run",
        "operation_id": operation_id,
        "operation_name": operation_name,
        "node_count": node_count,
        "sequence": entry["sequence"],
        "node_logical_id": entry["logical_node_id"],
        "planned_role": entry["planned_role"],
        "role_before_restart": role_before,
        "max_concurrent_restarts": 1,
        "restart_started_at_ms": base_ms,
        "restart_completed_at_ms": base_ms + 10,
        "health_gate_started_at_ms": base_ms + 10,
        "health_gate_completed_at_ms": base_ms + 20,
        "health_gate_status": "PASS",
        "cluster_state_after_gate": "ok",
        "known_nodes_after_gate": node_count,
        "slots_after_gate": 16384,
        "command_ref": f"{operation_id}-cmd-{entry['sequence']:04d}",
        "command_status": "PASS",
        "workload_impact_ref": f"{operation_id}:event",
        "primary_safe_path": "cluster_failover_takeover_before_owned_container_restart"
        if operation_name == "rolling_restart_primary_safe" and role_before == "primary"
        else "not_required_for_replica_restart",
        "promotion_latency_ms": 7 if operation_name == "rolling_restart_primary_safe" and role_before == "primary" else MISSING,
        "cluster_recovery_latency_ms": 9 if operation_name == "rolling_restart_primary_safe" and role_before == "primary" else MISSING,
        "read_unavailability_ms": MISSING,
        "write_unavailability_ms": MISSING,
        "missing_fields": missing_fields,
    }


def write_p19_rolling_restart_artifacts(base: Path, rows: list[dict]) -> None:
    operations = []
    restart_results = []
    command_rows = []
    for row in rows:
        order = p19_order(row["operation_name"], row["node_count"])
        operation_id = row["operation_id"]
        operations.append(
            {
                "operation_id": operation_id,
                "operation_name": row["operation_name"],
                "node_count": row["node_count"],
                "max_concurrent_restarts": 1,
                "health_gate": {"required_after_each_restart": True, "required_between_nodes": True},
                "restart_order": order,
            }
        )
        for entry in order:
            result = p19_restart_result(row["operation_name"], row["node_count"], entry, base_ms=entry["sequence"] * 100)
            restart_results.append(result)
            command_rows.append(
                {
                    "schema_version": "v1",
                    "phase_id": "P19_MANAGEMENT_ROLLING_RESTART",
                    "run_id": "run",
                    "operation_id": operation_id,
                    "command_id": result["command_ref"],
                    "command_kind": "owned_container_restart",
                    "status": "PASS",
                }
            )
    write_json(
        base / "rolling_restart_plan.json",
        {
            "schema_version": "v1",
            "artifact_type": "rolling_restart_plan",
            "phase_id": "P19_MANAGEMENT_ROLLING_RESTART",
            "run_id": "run",
            "health_gate": {
                "required_between_nodes": True,
                "required_after_each_restart": True,
                "cluster_state": "ok",
                "slots_assigned": 16384,
                "max_concurrent_restarts": 1,
            },
            "restart_order": [{"operation_id": op["operation_id"], **entry} for op in operations for entry in op["restart_order"]],
            "operations": operations,
        },
    )
    write_jsonl(base / "rolling_restart_results.jsonl", restart_results)
    write_jsonl(base / "management_command_log.jsonl", command_rows)


def p19_required_rows() -> list[dict]:
    return [
        p19_management_row(operation, count)
        for operation in ["rolling_restart_replica_first", "rolling_restart_primary_safe"]
        for count in [6, 10]
    ]


def test_p19_management_assertion_accepts_valid_rolling_restart(tmp_path: Path, monkeypatch) -> None:
    assert run_management_assertion(tmp_path, monkeypatch, p19_required_rows(), phase="P19_MANAGEMENT_ROLLING_RESTART") == 0


def test_p19_management_assertion_rejects_missing_10_node_rows(tmp_path: Path, monkeypatch) -> None:
    rows = [
        p19_management_row("rolling_restart_replica_first", 6),
        p19_management_row("rolling_restart_primary_safe", 6),
    ]

    assert run_management_assertion(tmp_path, monkeypatch, rows, phase="P19_MANAGEMENT_ROLLING_RESTART") == 1


def test_p19_management_assertion_rejects_primary_before_replica(tmp_path: Path, monkeypatch) -> None:
    rows = p19_required_rows()
    assertion = load_script("assert_management_ops_coverage")
    phase = "P19_MANAGEMENT_ROLLING_RESTART"
    phase_dir = tmp_path / "artifacts" / "phases" / phase
    phase_dir.mkdir(parents=True)
    write_p17_management_artifacts(phase_dir, rows)
    write_p19_rolling_restart_artifacts(phase_dir, rows)
    plan = json.loads((phase_dir / "rolling_restart_plan.json").read_text(encoding="utf-8"))
    operation = next(item for item in plan["operations"] if item["operation_id"] == "rolling_restart_replica_first-06")
    operation["restart_order"] = sorted(operation["restart_order"], key=lambda item: 0 if item["planned_role"] == "primary" else 1)
    (phase_dir / "rolling_restart_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_management_ops_coverage.py", "--phase", phase])

    assert assertion.main() == 1


def test_p19_management_assertion_rejects_overlapping_restart_health_gate(tmp_path: Path, monkeypatch) -> None:
    rows = p19_required_rows()
    phase = "P19_MANAGEMENT_ROLLING_RESTART"
    assertion = load_script("assert_management_ops_coverage")
    phase_dir = tmp_path / "artifacts" / "phases" / phase
    phase_dir.mkdir(parents=True)
    write_p17_management_artifacts(phase_dir, rows)
    write_p19_rolling_restart_artifacts(phase_dir, rows)
    results = [json.loads(line) for line in (phase_dir / "rolling_restart_results.jsonl").read_text(encoding="utf-8").splitlines()]
    first = next(row for row in results if row["operation_id"] == "rolling_restart_replica_first-06" and row["sequence"] == 1)
    second = next(row for row in results if row["operation_id"] == "rolling_restart_replica_first-06" and row["sequence"] == 2)
    first["health_gate_completed_at_ms"] = 500
    second["restart_started_at_ms"] = 400
    write_jsonl(phase_dir / "rolling_restart_results.jsonl", results)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_management_ops_coverage.py", "--phase", phase])

    assert assertion.main() == 1


P20_PHASE = "P20_FAILOVER_LATENCY_CURVE_30_50_100"
P21_PHASE = "P21_FAILOVER_LATENCY_CURVE_200"


def p20_sample(rung: int, sample_index: int) -> dict:
    base = rung * 100000 + sample_index * 1000
    promotion = 100 + sample_index
    recovery = 200 + sample_index
    sample_id = f"rung-{rung}-sample-{sample_index:02d}"
    return {
        "schema_version": "v1",
        "phase_id": P20_PHASE,
        "run_id": f"{P20_PHASE}-scale-{rung}-sample-{sample_index:02d}",
        "scenario_name": f"scale_{rung}_sample_{sample_index:02d}_fault_failover",
        "node_count": rung,
        "rung": rung,
        "sample_index": sample_index,
        "sample_id": sample_id,
        "status": "PASS",
        "real_valkey": True,
        "state_ref": f"artifacts/phases/{P20_PHASE}/_p20_samples/{sample_id}/state.json",
        "evidence_ref": f"artifacts/phases/{P20_PHASE}/_p20_samples/{sample_id}/valkey_e2e_evidence.json",
        "cleanup_ref": f"artifacts/phases/{P20_PHASE}/_p20_samples/{sample_id}/cleanup_report.json",
        "cleanup_status": "PASS",
        "target_primary_logical_id": f"shard-{sample_index:04d}-primary",
        "target_primary_node_id": f"node-{rung}-{sample_index}",
        "target_primary_az_id": "az-a",
        "target_primary_host_id": "local",
        "replica_candidates": [f"replica-{rung}-{sample_index}"],
        "fault_injection_method": "project_fault_api_node_stop_owned_container_or_process",
        "promotion_detection_method": "live_cluster_nodes_expected_replica_primary",
        "slot_coverage_detection_method": "live_cluster_info_cluster_state_ok",
        "fault_injected_at_ms": base,
        "primary_unreachable_at_ms": base + 1,
        "replica_promoted_at_ms": base + promotion,
        "cluster_state_ok_at_ms": base + recovery,
        "slot_coverage_ok_at_ms": base + recovery,
        "first_successful_read_at_ms": base + recovery + 1,
        "first_successful_write_at_ms": base + recovery + 2,
        "fault_cleared_at_ms": base + recovery + 10,
        "old_primary_rejoined_at_ms": "MISSING",
        "promotion_latency_ms": promotion,
        "cluster_recovery_latency_ms": recovery,
        "read_unavailability_ms": recovery + 1,
        "write_unavailability_ms": recovery + 2,
        "split_brain_window_ms": "MISSING",
        "workload_impact_ref": f"artifacts/phases/{P20_PHASE}/workload_impact_report.json#{sample_id}",
    }


def write_p20_curve_bundle(base: Path, samples: list[dict]) -> None:
    base.mkdir(parents=True, exist_ok=True)
    for rung in [30, 50, 100]:
        write_json(
            base / f"resource_preflight_{rung}.json",
            {
                "schema_version": "v1",
                "artifact_type": "resource_preflight",
                "phase_id": P20_PHASE,
                "run_id": f"preflight-{rung}",
                "status": "PASS",
                "can_run": True,
                "node_count": rung,
                "checks": [{"name": "ok", "status": "PASS"}],
            },
        )
    write_jsonl(base / "failover_latency_samples.jsonl", samples)
    derived = []
    for rung in [30, 50, 100]:
        rung_samples = [sample for sample in samples if sample["rung"] == rung]
        for metric in ["promotion_latency_ms", "cluster_recovery_latency_ms"]:
            values = sorted(float(sample[metric]) for sample in rung_samples)
            derived.append(
                {
                    "rung": rung,
                    "node_count": rung,
                    "metric": metric,
                    "unit": "ms",
                    "sample_count": len(values),
                    "percentile_method": "nearest_rank_round_index",
                    "sample_refs": [sample["sample_id"] for sample in rung_samples],
                    "p50_ms": values[1],
                    "p95_ms": values[2],
                    "max_ms": values[2],
                }
            )
    write_json(
        base / "failover_latency_curve.json",
        {
            "schema_version": "v1",
            "artifact_type": "failover_latency_curve",
            "phase_id": P20_PHASE,
            "run_id": "curve",
            "rungs": [30, 50, 100],
            "sample_refs": [sample["sample_id"] for sample in samples],
            "derived_series": derived,
        },
    )


def run_p20_curve_assertion(tmp_path: Path, monkeypatch, samples: list[dict]) -> int:
    assertion = load_script("assert_failover_latency_curve")
    phase_dir = tmp_path / "artifacts" / "phases" / P20_PHASE
    write_p20_curve_bundle(phase_dir, samples)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_failover_latency_curve.py", "--phase", P20_PHASE])
    return assertion.main()


def test_p20_failover_curve_assertion_accepts_real_sample_bundle(tmp_path: Path, monkeypatch) -> None:
    samples = [p20_sample(rung, index) for rung in [30, 50, 100] for index in [1, 2, 3]]

    assert run_p20_curve_assertion(tmp_path, monkeypatch, samples) == 0


def test_p20_failover_curve_assertion_rejects_reused_state_ref(tmp_path: Path, monkeypatch) -> None:
    samples = [p20_sample(rung, index) for rung in [30, 50, 100] for index in [1, 2, 3]]
    samples[1]["state_ref"] = samples[0]["state_ref"]

    assert run_p20_curve_assertion(tmp_path, monkeypatch, samples) == 1


def test_p20_failover_curve_assertion_rejects_non_derived_curve_value(tmp_path: Path, monkeypatch) -> None:
    samples = [p20_sample(rung, index) for rung in [30, 50, 100] for index in [1, 2, 3]]
    assertion = load_script("assert_failover_latency_curve")
    phase_dir = tmp_path / "artifacts" / "phases" / P20_PHASE
    write_p20_curve_bundle(phase_dir, samples)
    curve = json.loads((phase_dir / "failover_latency_curve.json").read_text(encoding="utf-8"))
    curve["derived_series"][0]["p50_ms"] = 999999
    write_json(phase_dir / "failover_latency_curve.json", curve)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_failover_latency_curve.py", "--phase", P20_PHASE])

    assert assertion.main() == 1


def p21_sample(sample_index: int) -> dict:
    base = 20000000 + sample_index * 10000
    promotion = 500 + sample_index
    recovery = 800 + sample_index
    sample_id = f"rung-200-sample-{sample_index:02d}"
    return {
        "schema_version": "v1",
        "phase_id": P21_PHASE,
        "run_id": f"{P21_PHASE}-scale-200-sample-{sample_index:02d}",
        "scenario_name": f"scale_200_sample_{sample_index:02d}_fault_failover",
        "node_count": 200,
        "rung": 200,
        "sample_index": sample_index,
        "sample_id": sample_id,
        "status": "PASS",
        "real_valkey": True,
        "state_ref": f"artifacts/phases/{P21_PHASE}/_p21_samples/{sample_id}/state.json",
        "evidence_ref": f"artifacts/phases/{P21_PHASE}/_p21_samples/{sample_id}/valkey_e2e_evidence.json",
        "cleanup_ref": f"artifacts/phases/{P21_PHASE}/_p21_samples/{sample_id}/cleanup_report.json",
        "cleanup_status": "PASS",
        "target_primary_logical_id": f"shard-{sample_index:04d}-primary",
        "target_primary_node_id": f"node-200-{sample_index}",
        "target_primary_az_id": "az-a",
        "target_primary_host_id": "local",
        "replica_candidates": [f"replica-200-{sample_index}"],
        "promoted_node_id": f"replica-200-{sample_index}",
        "fault_injection_method": "project_fault_api_node_stop_owned_container_or_process",
        "promotion_detection_method": "live_cluster_nodes_expected_replica_primary",
        "slot_coverage_detection_method": "live_cluster_info_cluster_state_ok",
        "fault_injected_at_ms": base,
        "primary_unreachable_at_ms": base + 1,
        "replica_promoted_at_ms": base + promotion,
        "cluster_state_ok_at_ms": base + recovery,
        "slot_coverage_ok_at_ms": base + recovery,
        "first_successful_read_at_ms": base + recovery + 1,
        "first_successful_write_at_ms": base + recovery + 2,
        "fault_cleared_at_ms": base + recovery + 10,
        "old_primary_rejoined_at_ms": "MISSING",
        "promotion_latency_ms": promotion,
        "cluster_recovery_latency_ms": recovery,
        "read_unavailability_ms": recovery + 1,
        "write_unavailability_ms": recovery + 2,
        "split_brain_window_ms": "MISSING",
        "workload_impact_ref": f"artifacts/phases/{P21_PHASE}/workload_impact_report.json#{sample_id}",
    }


def p21_curve_payload(samples: list[dict]) -> dict:
    derived = []
    for metric in ["promotion_latency_ms", "cluster_recovery_latency_ms"]:
        values = sorted(float(sample[metric]) for sample in samples)
        derived.append(
            {
                "rung": 200,
                "node_count": 200,
                "metric": metric,
                "unit": "ms",
                "sample_count": len(values),
                "percentile_method": "nearest_rank_round_index",
                "sample_refs": [sample["sample_id"] for sample in samples],
                "p50_ms": values[1],
                "p95_ms": values[2],
                "max_ms": values[2],
            }
        )
    return {
        "schema_version": "v1",
        "artifact_type": "failover_latency_curve",
        "phase_id": P21_PHASE,
        "run_id": "p21-curve",
        "status": "PASS",
        "rungs": [200],
        "sample_refs": [sample["sample_id"] for sample in samples],
        "derived_series": derived,
    }


def write_p21_curve_bundle(tmp_path: Path, samples: list[dict]) -> Path:
    p20_dir = tmp_path / "artifacts" / "phases" / P20_PHASE
    p20_samples = [p20_sample(rung, index) for rung in [30, 50, 100] for index in [1, 2, 3]]
    write_p20_curve_bundle(p20_dir, p20_samples)
    p21_dir = tmp_path / "artifacts" / "phases" / P21_PHASE
    p21_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        p21_dir / "resource_preflight_200.json",
        {
            "schema_version": "v1",
            "artifact_type": "resource_preflight",
            "phase_id": P21_PHASE,
            "run_id": "p21-preflight",
            "created_at": "2026-06-28T00:00:00Z",
            "producer": {"name": "test", "version": "v1"},
            "status": "PASS",
            "can_run": True,
            "node_count": 200,
            "dry_run": False,
            "checks": [{"name": "ok", "status": "PASS"}],
        },
    )
    write_jsonl(p21_dir / "failover_latency_samples_200.jsonl", samples)
    curve = p21_curve_payload(samples)
    write_json(p21_dir / "failover_latency_curve_200.json", curve)
    p20_curve = json.loads((p20_dir / "failover_latency_curve.json").read_text(encoding="utf-8"))
    write_json(
        p21_dir / "failover_latency_curve_combined_30_50_100_200.json",
        {
            "schema_version": "v1",
            "artifact_type": "failover_latency_curve",
            "phase_id": P21_PHASE,
            "run_id": "combined",
            "status": "PASS",
            "rungs": [30, 50, 100, 200],
            "sample_refs": p20_curve["sample_refs"] + curve["sample_refs"],
            "source_artifacts": [
                f"artifacts/phases/{P20_PHASE}/failover_latency_curve.json",
                f"artifacts/phases/{P21_PHASE}/failover_latency_curve_200.json",
            ],
            "derived_series": p20_curve["derived_series"] + curve["derived_series"],
        },
    )
    return p21_dir


def run_p21_curve_assertion(tmp_path: Path, monkeypatch, samples: list[dict]) -> int:
    assertion = load_script("assert_failover_latency_curve")
    write_p21_curve_bundle(tmp_path, samples)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_failover_latency_curve.py", "--phase", P21_PHASE])
    return assertion.main()


def test_p21_failover_curve_assertion_accepts_real_200_bundle(tmp_path: Path, monkeypatch) -> None:
    assert run_p21_curve_assertion(tmp_path, monkeypatch, [p21_sample(index) for index in [1, 2, 3]]) == 0


def test_p21_failover_curve_assertion_rejects_downshifted_sample(tmp_path: Path, monkeypatch) -> None:
    samples = [p21_sample(index) for index in [1, 2, 3]]
    samples[0]["node_count"] = 100

    assert run_p21_curve_assertion(tmp_path, monkeypatch, samples) == 1


def test_p21_failover_curve_assertion_rejects_duplicate_state_ref(tmp_path: Path, monkeypatch) -> None:
    samples = [p21_sample(index) for index in [1, 2, 3]]
    samples[1]["state_ref"] = samples[0]["state_ref"]

    assert run_p21_curve_assertion(tmp_path, monkeypatch, samples) == 1


def test_p21_failover_curve_assertion_rejects_fake_or_unclean_sample(tmp_path: Path, monkeypatch) -> None:
    samples = [p21_sample(index) for index in [1, 2, 3]]
    samples[0]["real_valkey"] = False
    samples[1]["cleanup_status"] = "FAIL"

    assert run_p21_curve_assertion(tmp_path, monkeypatch, samples) == 1


def test_p21_failover_curve_assertion_rejects_bad_combined_curve(tmp_path: Path, monkeypatch) -> None:
    samples = [p21_sample(index) for index in [1, 2, 3]]
    p21_dir = write_p21_curve_bundle(tmp_path, samples)
    combined = json.loads((p21_dir / "failover_latency_curve_combined_30_50_100_200.json").read_text(encoding="utf-8"))
    combined["rungs"] = [30, 50, 100]
    write_json(p21_dir / "failover_latency_curve_combined_30_50_100_200.json", combined)
    assertion = load_script("assert_failover_latency_curve")
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_failover_latency_curve.py", "--phase", P21_PHASE])

    assert assertion.main() == 1


def test_failover_project_cleanup_retries_until_report_passes(tmp_path: Path, monkeypatch) -> None:
    gate = load_script("fault_failover_gate")
    state_path = tmp_path / "state.json"
    write_json(state_path, {"schema_version": "v1", "nodes": []})
    attempts = []

    def fake_run_cmd(cmd: list[str], timeout: int):
        attempts.append((cmd, timeout))
        out_path = Path(cmd[cmd.index("--out") + 1])
        status = "FAIL" if len(attempts) == 1 else "PASS"
        write_json(out_path, {
            "schema_version": "v1",
            "artifact_type": "cleanup_report",
            "phase_id": P21_PHASE,
            "run_id": "cleanup",
            "status": status,
            "resources_remaining": [] if status == "PASS" else [{"type": "container", "reason": "timeout"}],
            "cleanup_actions": [],
        })
        return type("Proc", (), {"returncode": 0 if status == "PASS" else 1, "stderr": "timeout"})()

    monkeypatch.setattr(gate, "run_cmd", fake_run_cmd)

    status, cleanup_path = gate.project_cleanup(P21_PHASE, state_path, tmp_path / "cleanup", tmp_path / "published.json")

    assert status == "PASS"
    assert cleanup_path == tmp_path / "published.json"
    assert json.loads(cleanup_path.read_text(encoding="utf-8"))["status"] == "PASS"
    assert (tmp_path / "cleanup" / "cleanup_retry_01_report.json").exists()
    assert len(attempts) == 2
    assert all(timeout == 420 for _, timeout in attempts)


def test_p21_single_sample_runs_inter_sample_cleanup_when_child_leaves_state(tmp_path: Path, monkeypatch) -> None:
    gate = load_script("fault_failover_gate")
    monkeypatch.setattr(gate, "p21_config_path", lambda: tmp_path / "scale_200.yaml")
    (tmp_path / "scale_200.yaml").write_text("profile_name: scale_200\n", encoding="utf-8")

    def fake_run_cmd(cmd: list[str], timeout: int):
        sample_dir = tmp_path / "_p21_samples" / "rung-200-sample-01"
        work_dir = sample_dir / "_fault_failover_work_scale_200_sample_01_fault_failover"
        work_dir.mkdir(parents=True, exist_ok=True)
        write_json(work_dir / "state_failover.json", {"schema_version": "v1", "nodes": []})
        write_json(sample_dir / "cleanup_report.json", {"schema_version": "v1", "artifact_type": "cleanup_report", "status": "FAIL"})
        return type("Proc", (), {"returncode": 1, "stdout": "", "stderr": "child failed"})()

    cleanup_calls = []

    def fake_cleanup(phase, state_path, artifact_dir, cleanup_path=None):
        cleanup_calls.append((phase, state_path, artifact_dir, cleanup_path))
        write_json(cleanup_path, {"schema_version": "v1", "artifact_type": "cleanup_report", "phase_id": phase, "status": "PASS"})
        return "PASS", cleanup_path

    monkeypatch.setattr(gate, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(gate, "project_cleanup", fake_cleanup)
    args = type("Args", (), {
        "phase": P21_PHASE,
        "wait_after_fault": 1,
        "failover_node_timeout_ms": 15000,
        "require_data_path": True,
    })()

    run = gate.run_p21_single_sample(args, tmp_path, 1)

    assert run["returncode"] == 1
    assert run["inter_sample_cleanup_status"] == "PASS"
    assert cleanup_calls
    assert cleanup_calls[0][1].name == "state_failover.json"


def test_p21_cleanup_salvage_only_accepts_cleanup_only_failure(tmp_path: Path) -> None:
    gate = load_script("fault_failover_gate")
    paths = {
        "evidence": tmp_path / "evidence.json",
        "cleanup_report": tmp_path / "cleanup.json",
        "failover_report": tmp_path / "failover.json",
        "fault_report": tmp_path / "fault.json",
        "workload_report": tmp_path / "workload.json",
    }
    write_json(paths["evidence"], {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "status": "FAIL",
        "probe_result": "FAIL",
        "errors": ["cleanup failed"],
        "cleanup": {"status": "FAIL"},
    })
    for key in ["failover_report", "fault_report", "workload_report"]:
        write_json(paths[key], {"schema_version": "v1", "artifact_type": key, "status": "FAIL"})
    retry = tmp_path / "retry_cleanup.json"
    write_json(retry, {"schema_version": "v1", "artifact_type": "cleanup_report", "status": "PASS", "resources_remaining": []})

    assert gate.salvage_p21_cleanup_only_failure(paths, retry) is True
    assert json.loads(paths["evidence"].read_text(encoding="utf-8"))["status"] == "PASS"
    assert json.loads(paths["cleanup_report"].read_text(encoding="utf-8"))["status"] == "PASS"

    write_json(paths["evidence"], {"status": "FAIL", "errors": ["cleanup failed", "promotion missing"]})
    assert gate.salvage_p21_cleanup_only_failure(paths, retry) is False


def p21_workload_rows() -> list[dict]:
    rows = []
    for sample in [p21_sample(index) for index in [1, 2, 3]]:
        for window_name in ["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]:
            rows.append(
                {
                    "window_name": window_name,
                    "sample_id": sample["sample_id"],
                    "rung": 200,
                    "node_count": 200,
                    "start_event_id": f"{sample['sample_id']}-{window_name}-start",
                    "end_event_id": f"{sample['sample_id']}-{window_name}-end",
                    "start_time_unix_ms": sample["fault_injected_at_ms"],
                    "end_time_unix_ms": sample["slot_coverage_ok_at_ms"],
                    "metrics": {
                        "requested_qps": 1.0,
                        "achieved_qps": 1.0,
                        "ok_ops": 1,
                        "error_ops": 0,
                        "error_rate": 0.0,
                        "latency_p50_ms": 1.0,
                        "latency_p90_ms": "MISSING",
                        "latency_p95_ms": 1.0,
                        "latency_p99_ms": 1.0,
                        "latency_p999_ms": "MISSING",
                        "timeout_count": 0,
                        "connection_error_count": 0,
                        "moved_redirection_count": 0,
                        "ask_redirection_count": 0,
                        "cluster_down_error_count": 0,
                        "readonly_error_count": 0,
                        "tryagain_error_count": 0,
                        "unknown_error_count": 0,
                        "sample_count": 1,
                        "missing_reasons": {
                            "latency_p90_ms": "not captured in synthetic test",
                            "latency_p999_ms": "not captured in synthetic test",
                        },
                    },
                }
            )
    return rows


def test_p21_workload_impact_assertion_requires_three_200_samples(tmp_path: Path, monkeypatch) -> None:
    assertion = load_script("assert_workload_impact")
    phase_dir = tmp_path / "artifacts" / "phases" / P21_PHASE
    phase_dir.mkdir(parents=True)
    rows = p21_workload_rows()
    write_json(
        phase_dir / "workload_impact_report.json",
        {
            "schema_version": "v1",
            "artifact_type": "workload_impact_report",
            "phase_id": P21_PHASE,
            "run_id": "workload",
            "status": "PASS",
            "windows": rows,
            "comparisons": [{"sample_id": f"rung-200-sample-{idx:02d}", "rung": 200, "node_count": 200} for idx in [1, 2, 3]],
        },
    )
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_workload_impact.py", "--phase", P21_PHASE])

    assert assertion.main() == 0

    rows[0]["node_count"] = 100
    write_json(
        phase_dir / "workload_impact_report.json",
        {
            "schema_version": "v1",
            "artifact_type": "workload_impact_report",
            "phase_id": P21_PHASE,
            "run_id": "workload",
            "status": "PASS",
            "windows": rows,
            "comparisons": [{"sample_id": f"rung-200-sample-{idx:02d}", "rung": 200, "node_count": 200} for idx in [1, 2, 3]],
        },
    )

    assert assertion.main() == 1


def test_p21_quant_assertion_checks_counts_and_real_runtime(tmp_path: Path, monkeypatch) -> None:
    assertion = load_script("assert_quant_artifacts")
    codex_dir = tmp_path / "codex"
    codex_dir.mkdir()
    write_json(
        codex_dir / "phase_manifest.json",
        {
            "phases": [
                {
                    "id": P21_PHASE,
                    "real_valkey_required": True,
                    "required_artifacts": [],
                }
            ]
        },
    )
    phase_dir = tmp_path / "artifacts" / "phases" / P21_PHASE
    samples = [p21_sample(index) for index in [1, 2, 3]]
    write_p21_curve_bundle(tmp_path, samples)
    rows = p21_workload_rows()
    events = [
        {
            "schema_version": "v1",
            "run_id": sample["run_id"],
            "phase_id": P21_PHASE,
            "scenario_name": "failover_curve_200",
            "sample_id": sample["sample_id"],
            "event_id": f"{sample['sample_id']}-fault",
            "event_type": "fault_injected",
            "timestamp_unix_ms": sample["fault_injected_at_ms"],
            "monotonic_ms": sample["fault_injected_at_ms"],
            "severity": "INFO",
            "subject_type": "failover_sample",
            "subject_id": sample["target_primary_logical_id"],
            "operation_id": "",
            "fault_id": "fault-primary-stop",
            "message": "fault",
            "metadata": {"rung": 200},
        }
        for sample in samples
    ]
    metrics = [
        {
            "schema_version": "v1",
            "run_id": sample["run_id"],
            "phase_id": P21_PHASE,
            "scenario_name": "failover_curve_200",
            "sample_id": sample["sample_id"],
            "timestamp_unix_ms": sample["slot_coverage_ok_at_ms"],
            "monotonic_ms": sample["slot_coverage_ok_at_ms"],
            "source_type": "harness",
            "source_id": sample["sample_id"],
            "metric_name": "promotion_latency_ms",
            "metric_value": sample["promotion_latency_ms"],
            "metric_unit": "ms",
            "labels": {"rung": 200},
            "missing_reason": "",
        }
        for sample in samples
    ]
    write_jsonl(phase_dir / "events.jsonl", events)
    write_jsonl(phase_dir / "metrics_timeseries.jsonl", metrics)
    write_json(phase_dir / "workload_windows.json", {"schema_version": "v1", "artifact_type": "workload_windows", "phase_id": P21_PHASE, "run_id": "workload", "status": "PASS", "windows": rows})
    write_json(phase_dir / "cleanup_report.json", {"schema_version": "v1", "artifact_type": "cleanup_report", "phase_id": P21_PHASE, "run_id": "cleanup", "status": "PASS", "resources_remaining": [], "cleanup_actions": []})
    write_json(phase_dir / "valkey_e2e_evidence.json", {"schema_version": "v1", "artifact_type": "valkey_e2e_evidence", "phase_id": P21_PHASE, "run_id": "evidence", "status": "PASS", "real_valkey": True, "nodes_observed": 200, "sample_refs": [sample["sample_id"] for sample in samples]})
    write_json(phase_dir / "quant_summary.json", {"schema_version": "v1", "artifact_type": "quant_summary", "phase_id": P21_PHASE, "run_id": "quant", "status": "PASS", "missing_data": [], "counts": {"event_count": len(events), "metric_count": len(metrics), "sample_count": 3, "node_count": 200}, "runtime_claims": {"real_valkey_claimed": True, "fault_runtime_claimed": True, "management_runtime_claimed": False}})
    write_json(phase_dir / "phase_summary.json", {"schema_version": "v1", "artifact_type": "phase_summary", "phase_id": P21_PHASE, "run_id": "phase", "status": "PASS", "missing_metrics": []})
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_quant_artifacts.py", "--phase", P21_PHASE])

    assert assertion.main() == 0


def test_p19_management_assertion_rejects_failed_health_gate(tmp_path: Path, monkeypatch) -> None:
    rows = p19_required_rows()
    phase = "P19_MANAGEMENT_ROLLING_RESTART"
    assertion = load_script("assert_management_ops_coverage")
    phase_dir = tmp_path / "artifacts" / "phases" / phase
    phase_dir.mkdir(parents=True)
    write_p17_management_artifacts(phase_dir, rows)
    write_p19_rolling_restart_artifacts(phase_dir, rows)
    results = [json.loads(line) for line in (phase_dir / "rolling_restart_results.jsonl").read_text(encoding="utf-8").splitlines()]
    results[0]["health_gate_status"] = "FAIL"
    write_jsonl(phase_dir / "rolling_restart_results.jsonl", results)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_management_ops_coverage.py", "--phase", phase])

    assert assertion.main() == 1


P22_PHASE = "P22_FAULT_REPLICA_HOST_AZ_STOP"
P22_FAULTS = ["replica_stop", "node_host_stop", "az_stop"]
P22_WINDOWS = ["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]


def p22_fault_row(fault_type: str, node_count: int) -> dict:
    target = {
        "logical_id": "shard-0000-replica-00" if fault_type == "replica_stop" else "shard-0000-primary",
        "role": "replica" if fault_type == "replica_stop" else "primary",
        "host_id": "p22-host-a",
        "az_id": "az-a",
        "nodehost_id": "nodehost-az-a",
    }
    selector = {"selector_type": "role", "selected_role": "replica", "promotion_expected": False}
    if fault_type == "node_host_stop":
        selector = {"selector_type": "logical_host_id", "selected_host_id": "p22-host-a", "logical_host_only": True}
    if fault_type == "az_stop":
        selector = {"selector_type": "virtual_az_id", "selected_az_id": "az-a", "virtual_az_only": True}
    sample_id = f"p22-{node_count}-{fault_type}"
    return {
        "schema_version": "v1",
        "phase_id": P22_PHASE,
        "run_id": "run",
        "scenario_name": f"p22_fault_matrix_{node_count}",
        "sample_id": sample_id,
        "node_count": node_count,
        "status": "PASS",
        "real_valkey": True,
        "fault_type": fault_type,
        "fault_id": f"{sample_id}-fault",
        "scope": "owned_container_or_process",
        "implementation_path": "owned_runtime_control",
        "targets": [target],
        "target_selector": selector,
        "apply_started_at_ms": 100,
        "apply_completed_at_ms": 110,
        "clear_started_at_ms": 120,
        "clear_completed_at_ms": 130,
        "recovery_completed_at_ms": 150,
        "safety_scope_verified": True,
        "cleanup_verified": True,
        "host_network_mutated": False,
        "physical_host_mutated": False,
        "physical_az_mutated": False,
        "observed_impact": {
            "unexpected_promotion_observed": False,
            "promotion_expected": False if fault_type == "replica_stop" else "MISSING",
            "split_brain_window_ms": 0,
        },
        "workload_impact_ref": f"workload_impact_report.json#{sample_id}",
    }


def p22_skip_row(fault_type: str) -> dict:
    sample_id = f"p22-30-{fault_type}"
    return {
        "schema_version": "v1",
        "phase_id": P22_PHASE,
        "run_id": "skip",
        "scenario_name": "p22_fault_matrix_30",
        "sample_id": sample_id,
        "node_count": 30,
        "status": "SKIPPED_WITH_REASON",
        "reason": "preflight failed",
        "preflight_ref": "resource_preflight_30.json",
        "fault_type": fault_type,
        "fault_id": f"{sample_id}-fault",
        "scope": "owned_container_or_process",
        "implementation_path": "unsupported_skipped_with_reason",
        "targets": [{"status": "SKIPPED_WITH_REASON"}],
        "apply_started_at_ms": "SKIPPED_WITH_REASON",
        "apply_completed_at_ms": "SKIPPED_WITH_REASON",
        "clear_started_at_ms": "SKIPPED_WITH_REASON",
        "clear_completed_at_ms": "SKIPPED_WITH_REASON",
        "recovery_completed_at_ms": "SKIPPED_WITH_REASON",
        "safety_scope_verified": True,
        "cleanup_verified": True,
        "workload_impact_ref": "SKIPPED_WITH_REASON",
    }


def p22_window(sample_id: str, fault_type: str, node_count: int, window_name: str) -> dict:
    return {
        "window_name": window_name,
        "sample_id": sample_id,
        "fault_id": f"{sample_id}-fault",
        "fault_type": fault_type,
        "node_count": node_count,
        "start_event_id": f"{sample_id}-{window_name}-start",
        "end_event_id": f"{sample_id}-{window_name}-end",
        "metrics": {
            "requested_qps": 1.0,
            "achieved_qps": 1.0,
            "ok_ops": 1,
            "error_ops": 0,
            "error_rate": 0.0,
            "latency_p50_ms": 1.0,
            "latency_p95_ms": 1.0,
            "latency_p99_ms": 1.0,
            "timeout_count": 0,
            "moved_redirection_count": 0,
            "ask_redirection_count": 0,
            "missing_reasons": {},
        },
    }


def write_p22_bundle(base: Path) -> list[dict]:
    rows = [p22_fault_row(fault, count) for fault in P22_FAULTS for count in [6, 10]]
    rows.extend(p22_skip_row(fault) for fault in P22_FAULTS)
    write_json(base / "resource_preflight_30.json", {"can_run": False, "status": "FAIL", "node_count": 30})
    write_jsonl(base / "fault_results.jsonl", rows)
    workload_rows = [
        p22_window(row["sample_id"], row["fault_type"], row["node_count"], window)
        for row in rows
        if row["status"] != "SKIPPED_WITH_REASON"
        for window in P22_WINDOWS
    ]
    write_json(
        base / "workload_impact_report.json",
        {
            "schema_version": "v1",
            "artifact_type": "workload_impact_report",
            "phase_id": P22_PHASE,
            "run_id": "run",
            "windows": workload_rows,
            "comparisons": [
                {
                    "sample_id": row["sample_id"],
                    "fault_type": row["fault_type"],
                    "node_count": row["node_count"],
                    "fault_window_qps_ratio": 1.0,
                    "fault_window_p99_delta_ms": 0.0,
                    "fault_window_error_rate_delta": 0.0,
                    "recovery_window_duration_ms": 1,
                    "post_recovery_qps_ratio": 1.0,
                }
                for row in rows
                if row["status"] != "SKIPPED_WITH_REASON"
            ],
        },
    )
    events = [
        {
            "schema_version": "v1",
            "run_id": "run",
            "phase_id": P22_PHASE,
            "scenario_name": "p22_fault_matrix",
            "sample_id": row["sample_id"],
            "event_id": f"{row['sample_id']}-fault",
            "event_type": "fault_apply_started",
            "timestamp_unix_ms": 100,
            "monotonic_ms": 100,
            "severity": "INFO",
            "subject_type": "fault",
            "subject_id": row["fault_type"],
            "operation_id": "",
            "fault_id": row["fault_id"],
            "message": "fault",
            "metadata": {},
        }
        for row in rows
        if row["status"] != "SKIPPED_WITH_REASON"
    ]
    metrics = [
        {
            "schema_version": "v1",
            "run_id": "run",
            "phase_id": P22_PHASE,
            "scenario_name": "p22_fault_matrix",
            "sample_id": row["sample_id"],
            "timestamp_unix_ms": 100,
            "monotonic_ms": 100,
            "source_type": "harness",
            "source_id": row["fault_id"],
            "metric_name": "target_count",
            "metric_value": 1,
            "metric_unit": "count",
            "labels": {},
            "missing_reason": "",
        }
        for row in rows
        if row["status"] != "SKIPPED_WITH_REASON"
    ]
    snapshots = [
        {
            "schema_version": "v1",
            "phase_id": P22_PHASE,
            "run_id": "run",
            "sample_id": row["sample_id"],
            "snapshot_id": f"{row['sample_id']}-before",
            "timestamp_unix_ms": 100,
            "nodes": [],
            "slots": {},
        }
        for row in rows
        if row["status"] != "SKIPPED_WITH_REASON"
    ]
    write_jsonl(base / "events.jsonl", events)
    write_jsonl(base / "metrics_timeseries.jsonl", metrics)
    write_jsonl(base / "fault_topology_snapshots.jsonl", snapshots)
    write_json(base / "valkey_e2e_evidence.json", {"status": "PASS", "real_valkey": True, "nodes_observed": 10})
    write_json(base / "quant_summary.json", {"counts": {"event_count": len(events), "metric_count": len(metrics), "fault_result_count": len(rows), "topology_snapshot_count": len(snapshots), "sample_count": 6}, "runtime_claims": {"real_valkey_claimed": True, "fault_runtime_claimed": True, "management_runtime_claimed": False}})
    return rows


def test_p22_fault_matrix_assertion_accepts_valid_bundle(tmp_path: Path, monkeypatch) -> None:
    assertion = load_script("assert_fault_matrix_coverage")
    phase_dir = tmp_path / "artifacts" / "phases" / P22_PHASE
    phase_dir.mkdir(parents=True)
    write_p22_bundle(phase_dir)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_fault_matrix_coverage.py", "--phase", P22_PHASE])

    assert assertion.main() == 0


def test_p22_fault_matrix_assertion_rejects_wrong_replica_role(tmp_path: Path, monkeypatch) -> None:
    assertion = load_script("assert_fault_matrix_coverage")
    phase_dir = tmp_path / "artifacts" / "phases" / P22_PHASE
    phase_dir.mkdir(parents=True)
    rows = write_p22_bundle(phase_dir)
    rows[0]["targets"][0]["role"] = "primary"
    write_jsonl(phase_dir / "fault_results.jsonl", rows)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_fault_matrix_coverage.py", "--phase", P22_PHASE])

    assert assertion.main() == 1


def test_p22_workload_assertion_rejects_missing_window(tmp_path: Path, monkeypatch) -> None:
    assertion = load_script("assert_workload_impact")
    phase_dir = tmp_path / "artifacts" / "phases" / P22_PHASE
    phase_dir.mkdir(parents=True)
    write_p22_bundle(phase_dir)
    report = json.loads((phase_dir / "workload_impact_report.json").read_text(encoding="utf-8"))
    report["windows"] = [row for row in report["windows"] if not (row["sample_id"] == "p22-6-replica_stop" and row["window_name"] == "event")]
    write_json(phase_dir / "workload_impact_report.json", report)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_workload_impact.py", "--phase", P22_PHASE])

    assert assertion.main() == 1


def test_p22_quant_assertion_rejects_missing_metric_sample(tmp_path: Path) -> None:
    assertion = load_script("assert_quant_artifacts")
    write_p22_bundle(tmp_path)
    metrics = [json.loads(line) for line in (tmp_path / "metrics_timeseries.jsonl").read_text(encoding="utf-8").splitlines()]
    metrics = [row for row in metrics if row["sample_id"] != "p22-6-replica_stop"]
    write_jsonl(tmp_path / "metrics_timeseries.jsonl", metrics)

    errors: list[str] = []
    assertion.assert_p22_semantics(tmp_path, errors)

    assert any("metrics_timeseries.jsonl missing sample IDs" in error for error in errors)


P23_PHASE = "P23_FAULT_NETWORK_DELAY_LOSS_FLAP"
P23_FAULTS = ["network_delay", "network_loss", "network_flap"]


def p23_fault_row(fault_type: str, node_count: int) -> dict:
    sample_id = f"p23-{node_count}-{fault_type}"
    params = {
        "network_delay": {"delay_ms": 75, "jitter_ms": 10, "affected_direction": "bidirectional_proxy_relay", "target_set": ["shard-0000-primary"], "duration_seconds": 1},
        "network_loss": {"loss_percent": 50.0, "correlation": 0.0, "affected_direction": "client_to_target_connection", "target_set": ["shard-0000-primary"], "duration_seconds": 1},
        "network_flap": {"up_ms": 80, "down_ms": 80, "iterations": 6, "target_set": ["shard-0000-primary"], "duration_seconds": 1},
    }[fault_type]
    stats = {"accepted_connections": 4, "proxied_connections": 2, "delay_injections": 2, "dropped_connections": 2, "flap_rejections": 2}
    return {
        "schema_version": "v1",
        "phase_id": P23_PHASE,
        "run_id": "run",
        "scenario_name": f"p23_fault_matrix_{node_count}",
        "sample_id": sample_id,
        "node_count": node_count,
        "status": "PASS",
        "real_valkey": True,
        "fault_type": fault_type,
        "fault_id": f"{sample_id}-fault",
        "scope": "sandbox_proxy",
        "implementation_path": "sandbox_proxy",
        "targets": [{"logical_id": "shard-0000-primary", "role": "primary", "host_id": "p23-host-a", "az_id": "az-a"}],
        "target_selector": {"selector_type": "primary_slot_owner", "selected_logical_id": "shard-0000-primary", "slot_range": [0, 5460], "slot": 42},
        "fault_parameters": params,
        "apply_started_at_ms": 100,
        "apply_completed_at_ms": 110,
        "clear_started_at_ms": 120,
        "clear_completed_at_ms": 130,
        "recovery_completed_at_ms": 150,
        "safety_scope_verified": True,
        "cleanup_verified": True,
        "host_network_mutated": False,
        "physical_host_mutated": False,
        "physical_az_mutated": False,
        "observed_impact": {
            "effect_observed": True,
            "proxy_stats": stats,
            "event_metrics": {"error_ops": 1, "latency_p99_ms": 100.0},
            "baseline_metrics": {"error_ops": 0, "latency_p99_ms": 1.0},
        },
        "workload_impact_ref": f"workload_impact_report.json#{sample_id}",
        "command_log_ref": f"network_fault_command_log.jsonl#{sample_id}-fault",
    }


def p23_command_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        for kind in ["sandbox_proxy_apply", "sandbox_proxy_clear"]:
            out.append(
                {
                    "schema_version": "v1",
                    "phase_id": P23_PHASE,
                    "run_id": "run",
                    "sample_id": row["sample_id"],
                    "fault_id": row["fault_id"],
                    "command_id": f"{row['fault_id']}-{kind}",
                    "command_kind": kind,
                    "started_at_unix_ms": 100,
                    "ended_at_unix_ms": 101,
                    "status": "PASS",
                    "implementation_path": "sandbox_proxy",
                    "host_network_mutated": False,
                    "details": {},
                }
            )
    return out


def p23_window(sample_id: str, fault_type: str, node_count: int, window_name: str) -> dict:
    error_ops = 1 if window_name == "event" and fault_type in {"network_loss", "network_flap"} else 0
    latency = 100.0 if window_name == "event" and fault_type == "network_delay" else 1.0
    return {
        "window_name": window_name,
        "sample_id": sample_id,
        "fault_id": f"{sample_id}-fault",
        "fault_type": fault_type,
        "node_count": node_count,
        "start_event_id": f"{sample_id}-{window_name}-start",
        "end_event_id": f"{sample_id}-{window_name}-end",
        "metrics": {
            "requested_qps": 1.0,
            "achieved_qps": 1.0,
            "ok_ops": 1,
            "error_ops": error_ops,
            "error_rate": float(error_ops),
            "latency_p50_ms": latency,
            "latency_p95_ms": latency,
            "latency_p99_ms": latency,
            "timeout_count": 0,
            "moved_redirection_count": 0,
            "ask_redirection_count": 0,
            "sample_count": 1,
            "missing_reasons": {},
        },
    }


def write_p23_bundle(base: Path) -> list[dict]:
    rows = [p23_fault_row(fault, count) for fault in P23_FAULTS for count in [6, 10]]
    write_jsonl(base / "fault_results.jsonl", rows)
    write_jsonl(base / "network_fault_command_log.jsonl", p23_command_rows(rows))
    write_json(base / "network_fault_report.json", {"schema_version": "v1", "artifact_type": "network_fault_report", "phase_id": P23_PHASE, "run_id": "run", "status": "PASS", "network_faults": rows, "safe_paths_exercised": ["sandbox_proxy"]})
    workload_rows = [
        p23_window(row["sample_id"], row["fault_type"], row["node_count"], window)
        for row in rows
        for window in P22_WINDOWS
    ]
    write_json(
        base / "workload_impact_report.json",
        {
            "schema_version": "v1",
            "artifact_type": "workload_impact_report",
            "phase_id": P23_PHASE,
            "run_id": "run",
            "windows": workload_rows,
            "comparisons": [
                {
                    "sample_id": row["sample_id"],
                    "fault_type": row["fault_type"],
                    "node_count": row["node_count"],
                    "fault_window_qps_ratio": 1.0,
                    "fault_window_p99_delta_ms": 99.0 if row["fault_type"] == "network_delay" else 0.0,
                    "fault_window_error_rate_delta": 1.0 if row["fault_type"] in {"network_loss", "network_flap"} else 0.0,
                    "recovery_window_duration_ms": 1,
                    "post_recovery_qps_ratio": 1.0,
                }
                for row in rows
            ],
        },
    )
    events = [
        {
            "schema_version": "v1",
            "run_id": "run",
            "phase_id": P23_PHASE,
            "scenario_name": "p23_fault_matrix",
            "sample_id": row["sample_id"],
            "event_id": f"{row['sample_id']}-fault",
            "event_type": "fault_apply_started",
            "timestamp_unix_ms": 100,
            "monotonic_ms": 100,
            "severity": "INFO",
            "subject_type": "fault",
            "subject_id": row["fault_type"],
            "operation_id": "",
            "fault_id": row["fault_id"],
            "message": "fault",
            "metadata": {},
        }
        for row in rows
    ]
    metrics = [
        {
            "schema_version": "v1",
            "run_id": "run",
            "phase_id": P23_PHASE,
            "scenario_name": "p23_fault_matrix",
            "sample_id": row["sample_id"],
            "timestamp_unix_ms": 100,
            "monotonic_ms": 100,
            "source_type": "harness",
            "source_id": row["fault_id"],
            "metric_name": "proxy_accepted_connections",
            "metric_value": 4,
            "metric_unit": "count",
            "labels": {},
            "missing_reason": "",
        }
        for row in rows
    ]
    write_jsonl(base / "events.jsonl", events)
    write_jsonl(base / "metrics_timeseries.jsonl", metrics)
    write_json(base / "valkey_e2e_evidence.json", {"status": "PASS", "real_valkey": True, "nodes_observed": 10, "valkey_versions": ["9.1.0"]})
    write_json(base / "quant_summary.json", {"counts": {"event_count": len(events), "metric_count": len(metrics), "fault_result_count": len(rows), "command_log_count": len(rows) * 2, "sample_count": len(rows)}, "runtime_claims": {"real_valkey_claimed": True, "fault_runtime_claimed": True, "management_runtime_claimed": False}})
    return rows


def test_p23_fault_matrix_assertion_accepts_valid_bundle(tmp_path: Path, monkeypatch) -> None:
    assertion = load_script("assert_fault_matrix_coverage")
    phase_dir = tmp_path / "artifacts" / "phases" / P23_PHASE
    phase_dir.mkdir(parents=True)
    write_p23_bundle(phase_dir)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_fault_matrix_coverage.py", "--phase", P23_PHASE])

    assert assertion.main() == 0


def test_p23_fault_matrix_assertion_rejects_partition_row(tmp_path: Path, monkeypatch) -> None:
    assertion = load_script("assert_fault_matrix_coverage")
    phase_dir = tmp_path / "artifacts" / "phases" / P23_PHASE
    phase_dir.mkdir(parents=True)
    rows = write_p23_bundle(phase_dir)
    rows.append({**p23_fault_row("network_loss", 6), "fault_type": "network_partition", "fault_id": "bad-partition"})
    write_jsonl(phase_dir / "fault_results.jsonl", rows)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_fault_matrix_coverage.py", "--phase", P23_PHASE])

    assert assertion.main() == 1


def test_p23_workload_assertion_rejects_missing_comparison(tmp_path: Path, monkeypatch) -> None:
    assertion = load_script("assert_workload_impact")
    phase_dir = tmp_path / "artifacts" / "phases" / P23_PHASE
    phase_dir.mkdir(parents=True)
    write_p23_bundle(phase_dir)
    report = json.loads((phase_dir / "workload_impact_report.json").read_text(encoding="utf-8"))
    report["comparisons"] = report["comparisons"][1:]
    write_json(phase_dir / "workload_impact_report.json", report)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_workload_impact.py", "--phase", P23_PHASE])

    assert assertion.main() == 1


def test_p23_quant_assertion_rejects_missing_command_log_fault(tmp_path: Path) -> None:
    assertion = load_script("assert_quant_artifacts")
    write_p23_bundle(tmp_path)
    commands = [json.loads(line) for line in (tmp_path / "network_fault_command_log.jsonl").read_text(encoding="utf-8").splitlines()]
    commands = [row for row in commands if row["fault_id"] != "p23-6-network_delay-fault"]
    write_jsonl(tmp_path / "network_fault_command_log.jsonl", commands)

    errors: list[str] = []
    assertion.assert_p23_semantics(tmp_path, errors)

    assert any("command log missing fault IDs" in error for error in errors)


P24_PHASE = "P24_PARTITION_SPLIT_BRAIN_MATRIX"
P24_FAULTS = ["network_partition_minority", "network_partition_majority", "split_brain_window_detection"]


def p24_fault_row(fault_type: str, node_count: int) -> dict:
    sample_id = f"p24-{node_count}-{fault_type}"
    groups = {"majority": ["node-a", "node-b", "node-c"], "minority": ["node-d"], "isolated": []}
    policy = {
        "block_between_groups": True,
        "allow_within_group": True,
        "implementation_path": "owned_docker_network_control",
        "host_network_mutated": False,
        "global_firewall_mutated": False,
        "physical_host_mutated": False,
    }
    return {
        "schema_version": "v1",
        "phase_id": P24_PHASE,
        "run_id": "run",
        "scenario_name": f"p24_partition_matrix_{node_count}",
        "sample_id": sample_id,
        "node_count": node_count,
        "status": "PASS",
        "real_valkey": True,
        "fault_type": fault_type,
        "fault_id": f"{sample_id}-fault",
        "scope": "owned_docker_network",
        "implementation_path": "owned_docker_network_control",
        "targets": [{"logical_id": "node-d", "role": "primary", "host_id": "p24-host-a", "az_id": "az-c"}],
        "target_selector": {"selector_type": "virtual_az_partition", "selected_az_id": "az-c", "groups": groups},
        "fault_parameters": {"groups": groups, "traffic_policy": policy, "side_measured": "minority" if fault_type == "network_partition_minority" else "majority"},
        "apply_started_at_ms": 100,
        "apply_completed_at_ms": 110,
        "clear_started_at_ms": 150,
        "clear_completed_at_ms": 160,
        "recovery_completed_at_ms": 180,
        "apply_duration_ms": 10,
        "clear_duration_ms": 10,
        "recovery_latency_ms": 20,
        "observed_effect_started_at_ms": 110,
        "safety_scope_verified": True,
        "cleanup_verified": True,
        "host_network_mutated": False,
        "global_firewall_mutated": False,
        "physical_host_mutated": False,
        "physical_az_mutated": False,
        "observed_impact": {
            "effect_observed": True,
            "majority_available": True,
            "minority_side_probed": True,
            "minority_host_blocked": True,
        },
        "partition_report_ref": f"partition_report.json#{sample_id}",
        "split_brain_report_ref": f"split_brain_report.json#{sample_id}",
        "workload_impact_ref": f"workload_impact_report.json#{sample_id}",
        "command_log_ref": f"network_partition_command_log.jsonl#{sample_id}-fault",
    }


def p24_command_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        for kind in ["owned_docker_network_disconnect", "owned_docker_network_connect"]:
            out.append(
                {
                    "schema_version": "v1",
                    "phase_id": P24_PHASE,
                    "run_id": "run",
                    "sample_id": row["sample_id"],
                    "fault_id": row["fault_id"],
                    "command_id": f"{row['fault_id']}-{kind}",
                    "command_kind": kind,
                    "started_at_unix_ms": 100,
                    "ended_at_unix_ms": 101,
                    "status": "PASS",
                    "implementation_path": "owned_docker_network_control",
                    "host_network_mutated": False,
                    "global_firewall_mutated": False,
                    "physical_host_mutated": False,
                    "details": {"docker_command_scope": "owned_stage_network_and_owned_nodehost_container"},
                }
            )
    return out


def p24_window(sample_id: str, fault_type: str, node_count: int, window_name: str) -> dict:
    side = "minority" if fault_type == "network_partition_minority" else "majority"
    return {
        "window_name": window_name,
        "sample_id": sample_id,
        "fault_id": f"{sample_id}-fault",
        "fault_type": fault_type,
        "node_count": node_count,
        "side_label": side if window_name != "all_run" else "aggregate",
        "start_event_id": f"{sample_id}-{window_name}-start",
        "end_event_id": f"{sample_id}-{window_name}-end",
        "metrics": {
            "requested_qps": 1.0,
            "achieved_qps": 1.0,
            "ok_ops": 1,
            "error_ops": 0,
            "error_rate": 0.0,
            "latency_p50_ms": 1.0,
            "latency_p95_ms": 1.0,
            "latency_p99_ms": 1.0,
            "timeout_count": 0,
            "moved_redirection_count": 0,
            "ask_redirection_count": 0,
            "sample_count": 1,
            "missing_reasons": {},
        },
    }


def p24_partition_sample(row: dict) -> dict:
    groups = row["fault_parameters"]["groups"]
    policy = row["fault_parameters"]["traffic_policy"]
    return {
        "sample_id": row["sample_id"],
        "fault_id": row["fault_id"],
        "fault_type": row["fault_type"],
        "node_count": row["node_count"],
        "groups": groups,
        "traffic_policy": policy,
        "probes": {
            "during_majority": [{"status": "PASS", "logical_id": "node-a"}],
            "during_minority_side": [{"status": "PASS", "logical_id": "node-d", "probe_method": "docker_exec_valkey_cli_loopback"}],
        },
        "side_view_comparison": {
            "majority": {"pass_probe_count": 1, "known_node_ids": ["a", "b"]},
            "minority": {"pass_probe_count": 1, "known_node_ids": ["d"]},
            "divergent": True,
        },
        "safety_scope": {"implementation_path": "owned_docker_network_control", "host_network_mutated": False, "global_firewall_mutated": False, "physical_host_mutated": False, "sudo_used": False},
    }


def p24_split_report(rows: list[dict]) -> dict:
    detector_results = [
        {"detector": "primary_slot_assignment_overlap", "status": "PASS", "ran": True, "indicator_observed": False, "started_at_ms": 100, "ended_at_ms": 101},
        {"detector": "partition_side_cluster_view_divergence", "status": "PASS", "ran": True, "indicator_observed": True, "started_at_ms": 100, "ended_at_ms": 102, "conflicting_nodes": ["partition_side_cluster_view_divergence"]},
        {"detector": "conflicting_write_probe", "status": "PASS", "ran": True, "indicator_observed": False, "started_at_ms": 100, "ended_at_ms": 101},
    ]
    return {
        "schema_version": "v1",
        "artifact_type": "split_brain_report",
        "phase_id": P24_PHASE,
        "run_id": "run",
        "status": "PASS",
        "detectors_run": ["primary_slot_assignment_overlap", "partition_side_cluster_view_divergence", "conflicting_write_probe"],
        "detector_results": detector_results,
        "indicator_observed": True,
        "indicator_start_ms": 100,
        "indicator_end_ms": 102,
        "split_brain_window_ms": 2,
        "conflicting_slots": [],
        "conflicting_nodes": ["partition_side_cluster_view_divergence"],
        "conflicting_write_keys": [],
        "missing_detectors_with_reason": [{"detector": "old_primary_accepts_write_after_promotion", "status": "MISSING", "reason": "No promotion condition was injected."}],
        "samples": [{"sample_id": row["sample_id"], "fault_id": row["fault_id"], "fault_type": row["fault_type"], "node_count": row["node_count"], "detector_results": detector_results} for row in rows],
        "side_view_comparisons": [{"sample_id": row["sample_id"], "majority": {"pass_probe_count": 1}, "minority": {"pass_probe_count": 1}} for row in rows],
    }


def write_p24_bundle(base: Path) -> list[dict]:
    rows = [p24_fault_row(fault, count) for fault in P24_FAULTS for count in [6, 10]]
    write_jsonl(base / "fault_results.jsonl", rows)
    write_jsonl(base / "network_partition_command_log.jsonl", p24_command_rows(rows))
    samples = [p24_partition_sample(row) for row in rows]
    write_json(base / "partition_report.json", {"schema_version": "v1", "artifact_type": "partition_report", "phase_id": P24_PHASE, "run_id": "run", "status": "PASS", "groups": samples[0]["groups"], "traffic_policy": samples[0]["traffic_policy"], "probes": samples, "samples": samples, "safety_scope": {"host_network_mutated": False, "global_firewall_mutated": False}})
    write_json(base / "split_brain_report.json", p24_split_report(rows))
    workload_rows = [p24_window(row["sample_id"], row["fault_type"], row["node_count"], window) for row in rows for window in P22_WINDOWS]
    write_json(
        base / "workload_impact_report.json",
        {
            "schema_version": "v1",
            "artifact_type": "workload_impact_report",
            "phase_id": P24_PHASE,
            "run_id": "run",
            "windows": workload_rows,
            "comparisons": [
                {
                    "sample_id": row["sample_id"],
                    "fault_type": row["fault_type"],
                    "node_count": row["node_count"],
                    "fault_window_qps_ratio": 1.0,
                    "fault_window_p99_delta_ms": 0.0,
                    "fault_window_error_rate_delta": 0.0,
                    "recovery_window_duration_ms": 1,
                    "post_recovery_qps_ratio": 1.0,
                }
                for row in rows
            ],
        },
    )
    events = [
        {
            "schema_version": "v1",
            "run_id": "run",
            "phase_id": P24_PHASE,
            "scenario_name": "p24_partition_matrix",
            "sample_id": row["sample_id"],
            "event_id": f"{row['sample_id']}-fault",
            "event_type": "fault_apply_started",
            "timestamp_unix_ms": 100,
            "monotonic_ms": 100,
            "severity": "INFO",
            "subject_type": "fault",
            "subject_id": row["fault_type"],
            "operation_id": "",
            "fault_id": row["fault_id"],
            "message": "fault",
            "metadata": {},
        }
        for row in rows
    ]
    metrics = [
        {
            "schema_version": "v1",
            "run_id": "run",
            "phase_id": P24_PHASE,
            "scenario_name": "p24_partition_matrix",
            "sample_id": row["sample_id"],
            "timestamp_unix_ms": 100,
            "monotonic_ms": 100,
            "source_type": "harness",
            "source_id": row["fault_id"],
            "metric_name": "split_brain_window_ms",
            "metric_value": 2,
            "metric_unit": "ms",
            "labels": {},
            "missing_reason": "",
        }
        for row in rows
    ]
    snapshots = [{"schema_version": "v1", "phase_id": P24_PHASE, "run_id": "run", "snapshot_id": f"{row['sample_id']}-during", "sample_id": row["sample_id"], "nodes": [], "slots": {}} for row in rows]
    write_jsonl(base / "events.jsonl", events)
    write_jsonl(base / "metrics_timeseries.jsonl", metrics)
    write_jsonl(base / "fault_topology_snapshots.jsonl", snapshots)
    write_json(base / "valkey_e2e_evidence.json", {"status": "PASS", "real_valkey": True, "nodes_observed": 10, "valkey_versions": ["9.1.0"]})
    write_json(base / "quant_summary.json", {"counts": {"event_count": len(events), "metric_count": len(metrics), "fault_result_count": len(rows), "topology_snapshot_count": len(snapshots), "command_log_count": len(rows) * 2, "sample_count": len(rows)}, "runtime_claims": {"real_valkey_claimed": True, "fault_runtime_claimed": True, "management_runtime_claimed": False}})
    return rows


def test_p24_fault_matrix_assertion_accepts_valid_bundle(tmp_path: Path, monkeypatch) -> None:
    assertion = load_script("assert_fault_matrix_coverage")
    phase_dir = tmp_path / "artifacts" / "phases" / P24_PHASE
    phase_dir.mkdir(parents=True)
    write_p24_bundle(phase_dir)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_fault_matrix_coverage.py", "--phase", P24_PHASE])

    assert assertion.main() == 0


def test_p24_fault_matrix_assertion_rejects_missing_required_row(tmp_path: Path, monkeypatch) -> None:
    assertion = load_script("assert_fault_matrix_coverage")
    phase_dir = tmp_path / "artifacts" / "phases" / P24_PHASE
    phase_dir.mkdir(parents=True)
    rows = write_p24_bundle(phase_dir)
    rows = [row for row in rows if row["fault_type"] != "network_partition_majority"]
    write_jsonl(phase_dir / "fault_results.jsonl", rows)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_fault_matrix_coverage.py", "--phase", P24_PHASE])

    assert assertion.main() == 1


def test_p24_fault_matrix_assertion_rejects_missing_side_probes_and_groups(tmp_path: Path, monkeypatch) -> None:
    assertion = load_script("assert_fault_matrix_coverage")
    phase_dir = tmp_path / "artifacts" / "phases" / P24_PHASE
    phase_dir.mkdir(parents=True)
    write_p24_bundle(phase_dir)
    report = json.loads((phase_dir / "partition_report.json").read_text(encoding="utf-8"))
    report["samples"][0]["groups"]["minority"] = []
    report["samples"][0]["probes"]["during_minority_side"] = []
    write_json(phase_dir / "partition_report.json", report)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_fault_matrix_coverage.py", "--phase", P24_PHASE])

    assert assertion.main() == 1


def test_p24_split_brain_assertion_rejects_missing_detector_reason(tmp_path: Path, monkeypatch) -> None:
    assertion = load_script("assert_split_brain_report")
    phase_dir = tmp_path / "artifacts" / "phases" / P24_PHASE
    phase_dir.mkdir(parents=True)
    rows = write_p24_bundle(phase_dir)
    report = p24_split_report(rows)
    report["missing_detectors_with_reason"] = []
    write_json(phase_dir / "split_brain_report.json", report)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_split_brain_report.py", "--phase", P24_PHASE])

    assert assertion.main() == 1


def test_p24_fault_matrix_assertion_rejects_host_network_mutation_evidence(tmp_path: Path, monkeypatch) -> None:
    assertion = load_script("assert_fault_matrix_coverage")
    phase_dir = tmp_path / "artifacts" / "phases" / P24_PHASE
    phase_dir.mkdir(parents=True)
    write_p24_bundle(phase_dir)
    commands = [json.loads(line) for line in (phase_dir / "network_partition_command_log.jsonl").read_text(encoding="utf-8").splitlines()]
    commands[0]["host_network_mutated"] = True
    commands[0]["details"]["forbidden"] = "ip" + "tables -A INPUT"
    write_jsonl(phase_dir / "network_partition_command_log.jsonl", commands)
    monkeypatch.setattr(assertion, "ROOT", tmp_path)
    monkeypatch.setattr(assertion, "validate_artifact", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["assert_fault_matrix_coverage.py", "--phase", P24_PHASE])

    assert assertion.main() == 1
