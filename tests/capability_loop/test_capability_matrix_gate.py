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
