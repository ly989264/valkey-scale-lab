from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = ROOT / "tools" / "capability_matrix_gate.py"


def load_gate_module():
    spec = importlib.util.spec_from_file_location("capability_matrix_gate", GATE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_preserves_scale_policy():
    gate = load_gate_module()
    assert gate.check_manifest() == []


def test_negative_cases_are_expected_to_fail_invalid_inputs():
    gate = load_gate_module()
    cases = gate.make_negative_cases()
    assert cases
    assert {case["name"] for case in cases} == {
        "missing_artifact",
        "fake_real_valkey_evidence",
        "skip_as_pass",
        "cleanup_missing",
        "report_without_checksum",
        "old_artifact_reuse",
    }
    assert all(case["status"] == "PASS" for case in cases)


def test_baseline_rejects_fake_real_valkey_evidence(tmp_path):
    gate = load_gate_module()
    fake_evidence = tmp_path / "fake_evidence.json"
    fake_evidence.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "artifact_type": "valkey_e2e_evidence",
                "phase_id": "P12_SCALE_LADDER_10_30",
                "run_id": "fake",
                "created_at": "2026-07-02T00:00:00Z",
                "producer": {"name": "test", "version": "0"},
                "status": "PASS",
                "real_valkey": False,
                "valkey_version_prefix_required": "9.1.",
                "probe_result": "PASS",
                "nodes_observed": 30,
                "cluster_state_observed": "ok",
                "data_path_result": "PASS",
                "probes": [{"logical_id": "n0", "host": "127.0.0.1", "port": 1, "status": "PASS"}],
                "cleanup": {"status": "PASS"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    rel_evidence = fake_evidence.relative_to(gate.ROOT).as_posix() if fake_evidence.is_relative_to(gate.ROOT) else str(fake_evidence)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "artifact_type": "capability_matrix_baseline",
                "stage_id": "CML00_CAPABILITY_LOOP_BOOTSTRAP",
                "status": "PASS",
                "created_at": "2026-07-02T00:00:00Z",
                "capabilities": [
                    {
                        "capability": "fake",
                        "scale_nodes": 30,
                        "status": "PASS",
                        "real_valkey_required": True,
                        "cleanup_required": False,
                        "evidence_paths": [rel_evidence],
                        "cleanup_evidence_paths": [],
                        "report_artifacts": [],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    errors = gate.validate_baseline(baseline)
    assert any("fake real_valkey evidence" in error for error in errors)


def test_stage_manifest_requires_cml00_artifacts():
    manifest = json.loads((ROOT / "codex" / "capability_matrix_loop" / "stage_manifest.json").read_text())
    cml00 = next(stage for stage in manifest["stages"] if stage["id"] == "CML00_CAPABILITY_LOOP_BOOTSTRAP")
    required = {artifact["path"] for artifact in cml00["required_artifacts"]}
    assert "artifacts/capability_matrix_loop/CML00_CAPABILITY_LOOP_BOOTSTRAP/validation/previous_harness.log" in required
    assert "artifacts/capability_matrix_loop/CML00_CAPABILITY_LOOP_BOOTSTRAP/harness/harness_freeze.json" in required
    assert "artifacts/capability_matrix_loop/CML00_CAPABILITY_LOOP_BOOTSTRAP/reports/capability_matrix_baseline.json" in required


def test_stage_manifest_requires_cml01_observation_artifacts():
    manifest = json.loads((ROOT / "codex" / "capability_matrix_loop" / "stage_manifest.json").read_text())
    cml01 = next(stage for stage in manifest["stages"] if stage["id"] == "CML01_UNIFIED_OBSERVATION_AND_ARTIFACT_MODEL")
    required = {artifact["path"] for artifact in cml01["required_artifacts"]}
    assert cml01["max_real_nodes"] == 6
    assert cml01["real_valkey_required"] is True
    assert "artifacts/capability_matrix_loop/CML01_UNIFIED_OBSERVATION_AND_ARTIFACT_MODEL/samples/operation_event.jsonl" in required
    assert "artifacts/capability_matrix_loop/CML01_UNIFIED_OBSERVATION_AND_ARTIFACT_MODEL/samples/fault_event.jsonl" in required
    assert "artifacts/capability_matrix_loop/CML01_UNIFIED_OBSERVATION_AND_ARTIFACT_MODEL/samples/metrics_window.jsonl" in required
    assert "artifacts/capability_matrix_loop/CML01_UNIFIED_OBSERVATION_AND_ARTIFACT_MODEL/samples/workload_window.jsonl" in required
    assert "artifacts/capability_matrix_loop/CML01_UNIFIED_OBSERVATION_AND_ARTIFACT_MODEL/reports/report_index.json" in required
    assert {
        "empty metrics JSONL fails",
        "zero-filled missing metrics fail",
        "chart/report entry without source checksum fails",
        "old artifact reuse fails",
        "fake real_valkey evidence fails",
    }.issubset(set(cml01["negative_requirements"]))


def test_stage_manifest_requires_cml02_management_artifacts():
    manifest = json.loads((ROOT / "codex" / "capability_matrix_loop" / "stage_manifest.json").read_text())
    cml02 = next(stage for stage in manifest["stages"] if stage["id"] == "CML02_CLUSTER_MANAGEMENT_REAL_OPS_30")
    required = {artifact["path"] for artifact in cml02["required_artifacts"]}
    assert cml02["max_real_nodes"] == 30
    assert cml02["real_valkey_required"] is True
    assert "artifacts/capability_matrix_loop/CML02_CLUSTER_MANAGEMENT_REAL_OPS_30/samples/real_valkey_evidence_30.json" in required
    assert "artifacts/capability_matrix_loop/CML02_CLUSTER_MANAGEMENT_REAL_OPS_30/samples/state_scale_30.json" in required
    assert "artifacts/capability_matrix_loop/CML02_CLUSTER_MANAGEMENT_REAL_OPS_30/samples/cleanup_report_scale_30.json" in required
    assert "artifacts/capability_matrix_loop/CML02_CLUSTER_MANAGEMENT_REAL_OPS_30/samples/operation_event.jsonl" in required
    assert "artifacts/capability_matrix_loop/CML02_CLUSTER_MANAGEMENT_REAL_OPS_30/reports/management_ops.csv" in required
    assert {
        "wrong node count fails",
        "missing required management operation fails",
        "cleanup residue fails",
        "empty workload windows fail",
    }.issubset(set(cml02["negative_requirements"]))


def test_stage_manifest_requires_cml03_fault_artifacts():
    manifest = json.loads((ROOT / "codex" / "capability_matrix_loop" / "stage_manifest.json").read_text())
    cml03 = next(stage for stage in manifest["stages"] if stage["id"] == "CML03_PROCESS_AND_NODEHOST_FAULTS_30")
    required = {artifact["path"] for artifact in cml03["required_artifacts"]}
    assert cml03["max_real_nodes"] == 30
    assert cml03["real_valkey_required"] is True
    assert "artifacts/capability_matrix_loop/CML03_PROCESS_AND_NODEHOST_FAULTS_30/samples/real_valkey_evidence_fault_30.json" in required
    assert "artifacts/capability_matrix_loop/CML03_PROCESS_AND_NODEHOST_FAULTS_30/samples/fault_report_30.json" in required
    assert "artifacts/capability_matrix_loop/CML03_PROCESS_AND_NODEHOST_FAULTS_30/samples/failover_report_30.json" in required
    assert "artifacts/capability_matrix_loop/CML03_PROCESS_AND_NODEHOST_FAULTS_30/samples/workload_window_report_30.json" in required
    assert {
        "wrong fault scope fails",
        "missing after-clear recovery fails",
        "missing after-recovery workload window fails",
        "cleanup residue fails",
    }.issubset(set(cml03["negative_requirements"]))


def test_stage_manifest_requires_cml04_network_fault_artifacts():
    manifest = json.loads((ROOT / "codex" / "capability_matrix_loop" / "stage_manifest.json").read_text())
    cml04 = next(stage for stage in manifest["stages"] if stage["id"] == "CML04_NETWORK_PARTITION_AND_AZ_FAULTS_30")
    required = {artifact["path"] for artifact in cml04["required_artifacts"]}
    assert cml04["max_real_nodes"] == 30
    assert cml04["real_valkey_required"] is True
    assert "artifacts/capability_matrix_loop/CML04_NETWORK_PARTITION_AND_AZ_FAULTS_30/samples/real_valkey_evidence_network_30.json" in required
    assert "artifacts/capability_matrix_loop/CML04_NETWORK_PARTITION_AND_AZ_FAULTS_30/samples/network_fault_report_30.json" in required
    assert "artifacts/capability_matrix_loop/CML04_NETWORK_PARTITION_AND_AZ_FAULTS_30/samples/cleanup_report.json" in required
    assert {
        "host network scope fails",
        "wrong node count fails",
        "host network mutation fails",
    }.issubset(set(cml04["negative_requirements"]))


def test_stage_manifest_requires_cml05_failover_artifacts():
    manifest = json.loads((ROOT / "codex" / "capability_matrix_loop" / "stage_manifest.json").read_text())
    cml05 = next(stage for stage in manifest["stages"] if stage["id"] == "CML05_FAILOVER_LATENCY_AND_RECOVERY_30")
    required = {artifact["path"] for artifact in cml05["required_artifacts"]}
    assert cml05["max_real_nodes"] == 30
    assert cml05["real_valkey_required"] is True
    assert "artifacts/capability_matrix_loop/CML05_FAILOVER_LATENCY_AND_RECOVERY_30/samples/real_valkey_evidence_failover_30.json" in required
    assert "artifacts/capability_matrix_loop/CML05_FAILOVER_LATENCY_AND_RECOVERY_30/samples/failover_report_30.json" in required
    assert "artifacts/capability_matrix_loop/CML05_FAILOVER_LATENCY_AND_RECOVERY_30/samples/workload_window_report_30.json" in required
    assert {
        "missing failover latency fails",
        "missing promotion fails",
        "cleanup residue fails",
    }.issubset(set(cml05["negative_requirements"]))


def test_stage_manifest_requires_cml06_split_brain_artifacts():
    manifest = json.loads((ROOT / "codex" / "capability_matrix_loop" / "stage_manifest.json").read_text())
    cml06 = next(stage for stage in manifest["stages"] if stage["id"] == "CML06_SPLIT_BRAIN_INDICATORS_30")
    required = {artifact["path"] for artifact in cml06["required_artifacts"]}
    assert cml06["max_real_nodes"] == 30
    assert cml06["real_valkey_required"] is True
    assert "artifacts/capability_matrix_loop/CML06_SPLIT_BRAIN_INDICATORS_30/samples/real_valkey_evidence_split_brain_30.json" in required
    assert "artifacts/capability_matrix_loop/CML06_SPLIT_BRAIN_INDICATORS_30/samples/failover_report_30.json" in required
    assert {
        "zero-filled split-brain absence fails",
        "missing conflicting-primary reason fails",
    }.issubset(set(cml06["negative_requirements"]))


def test_stage_manifest_requires_cml07_workload_window_artifacts():
    manifest = json.loads((ROOT / "codex" / "capability_matrix_loop" / "stage_manifest.json").read_text())
    cml07 = next(stage for stage in manifest["stages"] if stage["id"] == "CML07_WORKLOAD_FAULT_WINDOWS_30")
    required = {artifact["path"] for artifact in cml07["required_artifacts"]}
    assert cml07["max_real_nodes"] == 30
    assert cml07["real_valkey_required"] is True
    assert "artifacts/capability_matrix_loop/CML07_WORKLOAD_FAULT_WINDOWS_30/samples/real_valkey_evidence_workload_windows_30.json" in required
    assert "artifacts/capability_matrix_loop/CML07_WORKLOAD_FAULT_WINDOWS_30/samples/workload_window_report_30.json" in required
    assert {
        "missing during workload window fails",
        "empty after-recovery samples fail",
        "missing data-path proof fails",
    }.issubset(set(cml07["negative_requirements"]))


def test_stage_manifest_requires_cml08_bounded_soak_artifacts():
    manifest = json.loads((ROOT / "codex" / "capability_matrix_loop" / "stage_manifest.json").read_text())
    cml08 = next(stage for stage in manifest["stages"] if stage["id"] == "CML08_BOUNDED_SOAK_30_60_MINUTES")
    required = {artifact["path"] for artifact in cml08["required_artifacts"]}
    assert cml08["max_real_nodes"] == 30
    assert cml08["real_valkey_required"] is True
    assert "artifacts/capability_matrix_loop/CML08_BOUNDED_SOAK_30_60_MINUTES/samples/real_valkey_evidence_bounded_soak_30.json" in required
    assert "artifacts/capability_matrix_loop/CML08_BOUNDED_SOAK_30_60_MINUTES/samples/bounded_soak_report_30_60.json" in required
    assert "artifacts/capability_matrix_loop/CML08_BOUNDED_SOAK_30_60_MINUTES/samples/soak_metrics_30_60.jsonl" in required
    assert {
        "short soak duration fails",
        "missing 60-minute checkpoint fails",
        "wrong node count fails",
    }.issubset(set(cml08["negative_requirements"]))


def test_stage_manifest_requires_cml09_reporting_close_artifacts():
    manifest = json.loads((ROOT / "codex" / "capability_matrix_loop" / "stage_manifest.json").read_text())
    cml09 = next(stage for stage in manifest["stages"] if stage["id"] == "CML09_REPORTING_AND_CAPABILITY_MATRIX_CLOSE_30")
    required = {artifact["path"] for artifact in cml09["required_artifacts"]}
    assert cml09["max_real_nodes"] == 30
    assert cml09["real_valkey_required"] is True
    assert "artifacts/capability_matrix_loop/CML09_REPORTING_AND_CAPABILITY_MATRIX_CLOSE_30/samples/real_valkey_evidence_reporting_close_30.json" in required
    assert "artifacts/capability_matrix_loop/CML09_REPORTING_AND_CAPABILITY_MATRIX_CLOSE_30/samples/evidence_index_30.json" in required
    assert "artifacts/capability_matrix_loop/CML09_REPORTING_AND_CAPABILITY_MATRIX_CLOSE_30/capability_matrix.json" in required
    assert {
        "missing capability evidence fails",
        "fake aggregate evidence fails",
        "wrong node count fails",
    }.issubset(set(cml09["negative_requirements"]))


def test_stage_manifest_requires_cml10_scale_replay_50_artifacts():
    manifest = json.loads((ROOT / "codex" / "capability_matrix_loop" / "stage_manifest.json").read_text())
    cml10 = next(stage for stage in manifest["stages"] if stage["id"] == "CML10_SCALE_REPLAY_50")
    required = {artifact["path"] for artifact in cml10["required_artifacts"]}
    assert cml10["max_real_nodes"] == 50
    assert cml10["real_valkey_required"] is True
    assert "artifacts/capability_matrix_loop/CML10_SCALE_REPLAY_50/samples/real_valkey_evidence_scale_replay_50.json" in required
    assert "artifacts/capability_matrix_loop/CML10_SCALE_REPLAY_50/samples/evidence_index_50.json" in required
    assert "artifacts/capability_matrix_loop/CML10_SCALE_REPLAY_50/capability_matrix.json" in required
    assert {
        "wrong 50-node count fails",
        "fake real Valkey evidence fails",
        "30-node evidence reuse fails",
        "network PASS without 50-node evidence fails",
    }.issubset(set(cml10["negative_requirements"]))
