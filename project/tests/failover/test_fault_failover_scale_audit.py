from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))

from schema_validator import load_json, validate


REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT = REPO_ROOT / "scripts" / "audit_fault_failover_scale.py"
SCHEMA = REPO_ROOT / "schemas" / "artifact" / "fault_failover_scale.schema.json"
WINDOW_SCHEMA = REPO_ROOT / "schemas" / "artifact" / "workload_window_report.schema.json"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _phase_dir(root: Path, node_count: int) -> Path:
    if node_count == 30:
        return root / "artifacts" / "phases" / "P12_SCALE_LADDER_10_30"
    return root / "artifacts" / "phases" / "P13_SCALE_LADDER_50_100"


def _scenario(node_count: int) -> str:
    return f"scale_{node_count}_fault_failover"


def _phase(node_count: int) -> str:
    return "P12_SCALE_LADDER_10_30" if node_count == 30 else "P13_SCALE_LADDER_50_100"


def _bundle(root: Path, node_count: int) -> None:
    phase = _phase(node_count)
    scenario = _scenario(node_count)
    run_id = f"{phase}-{scenario}-test"
    base = _phase_dir(root, node_count)
    producer = {"name": "scripts/fault_failover_gate.py", "version": "v1"}
    _write(base / f"resource_preflight_fault_{node_count}.json", {
        "schema_version": "v1",
        "artifact_type": "resource_preflight",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-30T00:00:00Z",
        "producer": producer,
        "status": "PASS",
        "can_run": True,
        "node_count": node_count,
    })
    _write(base / f"fault_report_{node_count}.json", {
        "schema_version": "v1",
        "artifact_type": "fault_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-30T00:00:00Z",
        "producer": producer,
        "status": "PASS",
        "faults": [{
            "fault_id": "fault-primary-stop",
            "fault_type": "node_stop",
            "scope": "owned_container_or_process",
            "target_logical_id": "shard-0000-primary",
            "apply_status": "PASS",
            "clear_status": "PASS",
            "fault_apply_latency_ms": 12.5,
            "fault_clear_latency_ms": 1.0,
            "after_clear_nodes_observed": node_count,
            "after_clear_cluster_state": "ok",
        }],
        "safety_checks": {
            "host_network_mutated": False,
            "global_firewall_mutated": False,
            "sandbox_only": True,
        },
    })
    _write(base / f"failover_report_{node_count}.json", {
        "schema_version": "v1",
        "artifact_type": "failover_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-30T00:00:00Z",
        "producer": producer,
        "status": "PASS",
        "failovers": [{
            "fault_id": "fault-primary-stop",
            "target_logical_id": "shard-0000-primary",
            "old_primary_node_id": "old-node",
            "promoted_node_id": "new-node",
            "failover_latency_ms": 800.0,
        }],
        "summary": {
            "promotion_observed": True,
            "split_brain_duration_ms": {
                "value": None,
                "status": "MISSING",
                "reason": "primary_stop_gate_did_not_observe_conflicting_primaries",
            },
        },
    })
    _write(base / f"workload_window_report_{node_count}.json", {
        "schema_version": "v1",
        "artifact_type": "workload_window_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-30T00:00:00Z",
        "producer": producer,
        "status": "PASS",
        "node_count": node_count,
        "scenario": scenario,
        "windows": [
            {"name": "before_fault", "status": "MEASURED", "workload_scope": "failed_primary_slot", "source_logical_id": "shard-0000-primary", "operation_count": 10, "roundtrip_successes": 5, "roundtrip_failures": 0, "availability_percent": 100.0, "errors_total": 0, "timeouts_total": 0, "latency_ms": {"p50": 1.0, "p95": 2.0, "p99": 3.0}},
            {"name": "during_fault", "status": "MEASURED", "workload_scope": "failed_primary_slot", "source_logical_id": "shard-0000-primary", "operation_count": 10, "roundtrip_successes": 0, "roundtrip_failures": 5, "availability_percent": 0.0, "errors_total": 10, "timeouts_total": 0, "latency_ms": {"p50": 0.0, "p95": 0.0, "p99": 0.0}},
            {"name": "after_recovery", "status": "MEASURED", "workload_scope": "failed_primary_slot", "source_logical_id": "shard-0000-primary", "operation_count": 10, "roundtrip_successes": 5, "roundtrip_failures": 0, "availability_percent": 100.0, "errors_total": 0, "timeouts_total": 0, "latency_ms": {"p50": 1.0, "p95": 2.0, "p99": 3.0}},
        ],
    })
    _write(base / f"valkey_e2e_evidence_fault_{node_count}.json", {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-30T00:00:00Z",
        "producer": producer,
        "status": "PASS",
        "scenario": scenario,
        "real_valkey": True,
        "probe_result": "PASS",
        "nodes_observed_before": node_count,
        "nodes_observed": node_count - 1,
        "nodes_observed_after_clear": node_count,
        "cluster_state_observed": "ok",
        "data_path_result": "PASS",
        "observations": {
            "before_fault": {"status": "MEASURED", "nodes_observed": node_count, "cluster_state": "ok"},
            "during_fault": {"status": "MEASURED", "nodes_observed": node_count - 1, "cluster_state": "fail"},
            "after_promotion": {"status": "MEASURED", "nodes_observed": node_count - 1, "cluster_state": "ok"},
            "after_clear": {"status": "MEASURED", "nodes_observed": node_count, "cluster_state": "ok"},
        },
        "valkey_versions": ["9.1.0"],
        "selected_primary_logical_id": "shard-0000-primary",
        "cleanup": {"status": "PASS", "path": f"artifacts/phases/{phase}/cleanup_report_fault_{node_count}.json"},
        "errors": [],
    })
    _write(base / f"cleanup_report_fault_{node_count}.json", {
        "schema_version": "v1",
        "artifact_type": "cleanup_report",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-30T00:00:00Z",
        "producer": producer,
        "status": "PASS",
        "resources_remaining": [],
        "cleanup_actions": [],
    })


def _write_complete(root: Path) -> None:
    for node_count in [30, 50, 100]:
        _bundle(root, node_count)


def _run_audit(root: Path, out: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDIT), "--root", str(root), "--out", str(out)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_fault_failover_scale_audit_accepts_complete_bundle(tmp_path: Path) -> None:
    _write_complete(tmp_path)
    out = tmp_path / "artifacts" / "loop_engineering" / "reports" / "fault_failover_scale.json"
    result = _run_audit(tmp_path, out)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["summary"]["canonical_node_counts"] == [30, 50, 100]
    assert payload["summary"]["real_valkey_rung_count"] == 3
    assert validate(payload, load_json(SCHEMA)) == []


def test_fault_failover_scale_audit_rejects_explicit_fixture_evidence(tmp_path: Path) -> None:
    _write_complete(tmp_path)
    for node_count in [30, 50, 100]:
        path = _phase_dir(tmp_path, node_count) / f"valkey_e2e_evidence_fault_{node_count}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["fixture"] = True
        payload["evidence_origin"] = "generated_fixture"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    out = tmp_path / "fault_failover_scale.json"
    result = _run_audit(tmp_path, out)

    assert result.returncode == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert any(f["category"] == "fixture_evidence_forbidden" for f in payload["findings"])


def test_fault_failover_scale_audit_rejects_missing_workload_window(tmp_path: Path) -> None:
    _write_complete(tmp_path)
    (_phase_dir(tmp_path, 50) / "workload_window_report_50.json").unlink()
    out = tmp_path / "fault_failover_scale.json"
    result = _run_audit(tmp_path, out)
    assert result.returncode == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert any(f["category"] == "missing_l08_artifact" and f["node_count"] == 50 for f in payload["findings"])


def test_fault_failover_scale_audit_rejects_all_skipped_workload_windows(tmp_path: Path) -> None:
    _write_complete(tmp_path)
    path = _phase_dir(tmp_path, 30) / "workload_window_report_30.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for window in payload["windows"]:
        window["status"] = "SKIPPED_WITH_REASON"
        window["reason"] = "probe-only placeholder"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out = tmp_path / "fault_failover_scale.json"
    result = _run_audit(tmp_path, out)
    assert result.returncode == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert any(f["category"] == "workload_window_not_measured" and f["node_count"] == 30 for f in payload["findings"])


def test_fault_failover_scale_audit_rejects_background_workload_scope(tmp_path: Path) -> None:
    _write_complete(tmp_path)
    path = _phase_dir(tmp_path, 30) / "workload_window_report_30.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["windows"][1]["workload_scope"] = "cluster_background"
    payload["windows"][1]["source_logical_id"] = "shard-9999-primary"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out = tmp_path / "fault_failover_scale.json"
    result = _run_audit(tmp_path, out)
    assert result.returncode == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert any(f["category"] == "workload_window_invalid" and f["node_count"] == 30 for f in payload["findings"])


def test_fault_failover_scale_audit_rejects_missing_after_clear_observation(tmp_path: Path) -> None:
    _write_complete(tmp_path)
    path = _phase_dir(tmp_path, 100) / "valkey_e2e_evidence_fault_100.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["observations"].pop("after_clear")
    payload.pop("nodes_observed_after_clear")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out = tmp_path / "fault_failover_scale.json"
    result = _run_audit(tmp_path, out)
    assert result.returncode == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert any(f["category"] == "observation_invalid" and f["node_count"] == 100 for f in payload["findings"])


def test_fault_failover_scale_audit_rejects_missing_data_path_result(tmp_path: Path) -> None:
    _write_complete(tmp_path)
    path = _phase_dir(tmp_path, 50) / "valkey_e2e_evidence_fault_50.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["data_path_result"] = "MISSING"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out = tmp_path / "fault_failover_scale.json"
    result = _run_audit(tmp_path, out)
    assert result.returncode == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert any(f["category"] == "data_path_invalid" and f["node_count"] == 50 for f in payload["findings"])


def test_fault_failover_scale_audit_rejects_p14_real_fault_artifact(tmp_path: Path) -> None:
    _write_complete(tmp_path)
    _write(tmp_path / "artifacts" / "phases" / "P14_SCALE_1000_OPTIN_DRYRUN" / "valkey_e2e_evidence_fault_1000.json", {
        "artifact_type": "valkey_e2e_evidence",
        "real_valkey": True,
        "node_count": 1000,
        "status": "PASS",
    })
    out = tmp_path / "fault_failover_scale.json"
    result = _run_audit(tmp_path, out)
    assert result.returncode == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["p14_boundary"]["real_valkey_coverage"] is False
    assert any(f["category"] == "p14_real_fault_failover_forbidden" for f in payload["findings"])


def test_fault_failover_scale_audit_allows_p14_dryrun_resource_metadata(tmp_path: Path) -> None:
    _write_complete(tmp_path)
    _write(tmp_path / "artifacts" / "phases" / "P14_SCALE_1000_OPTIN_DRYRUN" / "resource_preflight_1000.json", {
        "artifact_type": "resource_preflight",
        "real_valkey": False,
        "node_count": 1000,
        "dry_run": True,
        "status": "PASS",
    })
    out = tmp_path / "fault_failover_scale.json"
    result = _run_audit(tmp_path, out)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["p14_boundary"]["status"] == "SKIPPED_WITH_REASON"
    assert not any(f["category"] == "p14_real_fault_failover_forbidden" for f in payload["findings"])


def test_workload_window_schema_requires_three_windows(tmp_path: Path) -> None:
    _write_complete(tmp_path)
    payload = json.loads((_phase_dir(tmp_path, 30) / "workload_window_report_30.json").read_text(encoding="utf-8"))
    schema = load_json(WINDOW_SCHEMA)
    assert validate(payload, schema) == []
    payload["windows"] = payload["windows"][:2]
    assert validate(payload, schema)
