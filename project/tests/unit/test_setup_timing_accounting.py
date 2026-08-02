from __future__ import annotations

import importlib.util
import time
from pathlib import Path


def _load_valkey_e2e_gate():
    path = Path("scripts/valkey_e2e_gate.py")
    spec = importlib.util.spec_from_file_location("valkey_e2e_gate_for_test", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_setup_timing_breakdown_accounts_gate_wall_time(tmp_path: Path) -> None:
    gate = _load_valkey_e2e_gate()
    accounting_timings = {
        "setup_command_wall": {
            "name": "setup_command_wall",
            "status": "PASS",
            "duration_seconds": 75.0,
            "count": 1,
            "details": {},
        },
        "setup_stdout_write": {
            "name": "setup_stdout_write",
            "status": "PASS",
            "duration_seconds": 0.01,
            "count": 1,
            "details": {},
        },
        "setup_stderr_write": {
            "name": "setup_stderr_write",
            "status": "PASS",
            "duration_seconds": 0.01,
            "count": 1,
            "details": {},
        },
        "state_load": {
            "name": "state_load",
            "status": "PASS",
            "duration_seconds": 0.02,
            "count": 1,
            "details": {},
        },
        "cleanup_command_wall": {
            "name": "cleanup_command_wall",
            "status": "PASS",
            "duration_seconds": 15.0,
            "count": 1,
            "details": {},
        },
        "cleanup_stdout_write": {
            "name": "cleanup_stdout_write",
            "status": "PASS",
            "duration_seconds": 0.01,
            "count": 1,
            "details": {},
        },
        "cleanup_stderr_write": {
            "name": "cleanup_stderr_write",
            "status": "PASS",
            "duration_seconds": 0.01,
            "count": 1,
            "details": {},
        },
    }
    artifact = gate.write_setup_timing_breakdown(
        tmp_path / "setup_timing_breakdown_exact-50.json",
        capability_id="scale_ladder",
        scenario="scale_ladder",
        profile_id="exact-50",
        run_id="test-run",
        node_count=50,
        runtime_entries=[
            {
                "name": "runtime_all_node_light_probe",
                "status": "PASS",
                "duration_seconds": 0.2,
                "count": 1,
                "details": {},
            },
            {
                "name": "runtime_final_full_probe",
                "status": "PASS",
                "duration_seconds": 0.0,
                "count": 1,
                "details": {},
            },
            {
                "name": "runtime_diagnostic_full_probe",
                "status": "FAIL",
                "duration_seconds": 0.3,
                "count": 1,
                "details": {"mode": "diagnostic"},
            },
        ],
        wrapper_timings={
            "wrapper_wait_cluster_ok": {
                "name": "wrapper_wait_cluster_ok",
                "status": "PASS",
                "duration_seconds": 0.5,
                "count": 1,
                "details": {},
            },
            "wrapper_data_path_probe": {
                "name": "wrapper_data_path_probe",
                "status": "PASS",
                "duration_seconds": 0.1,
                "count": 1,
                "details": {},
            },
            "cleanup": {
                "name": "cleanup",
                "status": "PASS",
                "duration_seconds": 15.0,
                "count": 1,
                "details": {},
            },
        },
        accounting_timings=accounting_timings,
        wait_timing={
            "representative_probe": {"duration_seconds": 0.1, "count": 1},
            "all_endpoint_light_probe": {"duration_seconds": 0.2, "count": 1},
            "final_full_probe": {"duration_seconds": 0.0, "count": 0},
            "diagnostic_full_probe": {"duration_seconds": 0.3, "count": 1},
        },
        status="PASS",
        gate_started_monotonic=time.monotonic() - 94.0,
    )

    summary = artifact["summary"]
    assert summary["total_gate_seconds"] >= 94.0
    assert summary["setup_command_wall_seconds"] == 75.0
    assert summary["cleanup_command_wall_seconds"] == 15.0
    assert summary["artifact_write_seconds"] >= 0.0
    assert summary["unattributed_seconds"] <= 10.0
    assert artifact["accounting"]["unattributed_status"] == "PASS"
    entries = {entry["name"]: entry for entry in artifact["timings"]}
    assert entries["runtime_all_node_light_probe"]["status"] == "PASS"
    assert entries["runtime_final_full_probe"]["status"] == "PASS"
    assert entries["runtime_diagnostic_full_probe"]["status"] == "FAIL"


def test_role_counts_from_light_probes() -> None:
    gate = _load_valkey_e2e_gate()

    assert gate.role_counts_from_probes(
        [
            {"status": "PASS", "role": "primary"},
            {"status": "PASS", "role": "replica"},
            {"status": "PASS", "role": "replica"},
        ]
    ) == {"primary": 1, "replica": 2, "handshake": 0, "fail": 0, "pfail": 0}
