from __future__ import annotations

import importlib.util
import json
import subprocess
import time
from pathlib import Path

from valkey_scale_lab.observability.sentinel import key_slot


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
    ) == {
        "primary": 1,
        "replica": 2,
        "handshake": {"status": "MISSING", "reason": "light probes do not observe CLUSTER NODES failure flags"},
        "fail": {"status": "MISSING", "reason": "light probes do not observe CLUSTER NODES failure flags"},
        "pfail": {"status": "MISSING", "reason": "light probes do not observe CLUSTER NODES failure flags"},
    }


def test_wrapper_timing_counts_integrated_replica_pipeline_once() -> None:
    gate = _load_valkey_e2e_gate()

    assert gate.cluster_create_duration_seconds(
        {
            "primary_cluster_create": {"duration_seconds": 1.0},
            "replica_replicate": {
                "duration_seconds": 2.0,
                "details": {"replica_meet_integrated_with_pipeline": True},
            },
        }
    ) == 3.0
    assert gate.cluster_create_duration_seconds(
        {
            "primary_cluster_create": {"duration_seconds": 1.0},
            "replica_replicate": {"duration_seconds": 2.0, "details": {}},
        }
    ) == "MISSING"


def _write_fake_state(path: Path, *, runtime_timings: list[dict[str, object]] | None = None) -> None:
    nodes = [
        {
            "logical_id": f"p{index}",
            "host": "127.0.0.1",
            "client_port": 7000 + index,
            "role": "primary",
            "container_ip": "127.0.0.1",
        }
        for index in range(50)
    ]
    state = {
        "runtime": {
            "run_id": "test-run",
            "sandbox_network": True,
            "timings": runtime_timings or [],
        },
        "nodes": nodes,
        "nodehosts": [],
    }
    path.write_text(json.dumps(state), encoding="utf-8")


def _fake_wrapper_argv(out: Path) -> list[str]:
    return [
        "valkey_e2e_gate.py",
        "--capability-id",
        "scale_ladder",
        "--config",
        "config.json",
        "--scenario",
        "scale_ladder",
        "--profile",
        "exact-50",
        "--out",
        str(out),
        "--min-nodes",
        "50",
        "--require-data-path",
    ]


def test_wrapper_success_selects_natural_probe_key_inside_data_path_timing(tmp_path: Path, monkeypatch) -> None:
    gate = _load_valkey_e2e_gate()
    out = tmp_path / "evidence.json"
    slot = 121
    bitmap = bytearray(2048)
    bitmap[slot >> 3] |= 1 << (slot & 7)
    commands: list[tuple[str, str]] = []

    def fake_run_cmd(cmd: list[str], timeout: int, env=None):
        if "--state-out" in cmd:
            _write_fake_state(Path(cmd[cmd.index("--state-out") + 1]))
        if "--out" in cmd:
            Path(cmd[cmd.index("--out") + 1]).write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_wait(*args, **kwargs):
        return True, [
            {
                "status": "PASS",
                "logical_id": "p0",
                "version": "9.1.0",
                "cluster_state": "ok",
                "role": "primary",
                "slot_bitmap": bytes(bitmap),
            }
        ]

    def fake_execute(endpoints, *args, timeout):
        commands.append((str(args[0]), str(args[1])))
        if args[0] == "SET":
            assert key_slot(str(args[1])) == slot
            return "OK"
        return "value-scale_ladder"

    monkeypatch.setattr(gate, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(gate, "wait_for_cluster_ok", fake_wait)
    monkeypatch.setattr(gate, "execute_cluster_command", fake_execute)
    monkeypatch.setattr(gate.sys, "argv", _fake_wrapper_argv(out))

    assert gate.main() == 0
    evidence = json.loads(out.read_text(encoding="utf-8"))
    timing = json.loads((tmp_path / "setup_timing_breakdown_exact-50.json").read_text(encoding="utf-8"))
    entries = {entry["name"]: entry for entry in timing["timings"]}

    assert evidence["data_path_result"] == "PASS"
    assert commands == [("SET", commands[0][1]), ("GET", commands[0][1])]
    assert entries["wrapper_data_path_probe"]["status"] == "PASS"
    assert entries["wrapper_data_path_probe"]["details"]["target_logical_id"] == "p0"
    assert entries["wrapper_data_path_probe"]["details"]["slot"] == slot


def test_wrapper_cluster_wait_failure_records_failed_data_path_timing_without_key_selection(tmp_path: Path, monkeypatch) -> None:
    gate = _load_valkey_e2e_gate()
    out = tmp_path / "evidence.json"

    def fake_run_cmd(cmd: list[str], timeout: int, env=None):
        if "--state-out" in cmd:
            _write_fake_state(Path(cmd[cmd.index("--state-out") + 1]))
        if "--out" in cmd:
            Path(cmd[cmd.index("--out") + 1]).write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(gate, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(gate, "wait_for_cluster_ok", lambda *args, **kwargs: (False, [{"status": "PASS", "cluster_state": "fail"}]))
    monkeypatch.setattr(gate, "natural_probe_key_from_topology", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("key selection must not run after cluster wait failure")))
    monkeypatch.setattr(gate, "execute_cluster_command", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("data command must not run after cluster wait failure")))
    monkeypatch.setattr(gate.sys, "argv", _fake_wrapper_argv(out))

    assert gate.main() == 1
    evidence = json.loads(out.read_text(encoding="utf-8"))
    timing = json.loads((tmp_path / "setup_timing_breakdown_exact-50.json").read_text(encoding="utf-8"))
    entries = {entry["name"]: entry for entry in timing["timings"]}

    assert evidence["data_path_result"] == "FAIL"
    assert entries["wrapper_data_path_probe"]["status"] == "FAIL"
    assert entries["wrapper_data_path_probe"]["details"]["reason"] == "cluster wait failed"
