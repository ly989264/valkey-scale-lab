from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from valkey_scale_lab.fault import sandbox


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_process_clear_waits_for_pid_and_ping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = tmp_path / "state.json"
    fault_id = "fault-node-stop"
    target = {
        "logical_id": "node-0",
        "nodehost_container_name": "owned-nodehost",
        "config_file": "/tmp/node-0/valkey.conf",
        "pid_file": "/tmp/node-0/valkey.pid",
        "client_port": 7800,
    }
    _write_json(state_path, {"capability_id": "fault_matrix", "runtime": {"run_id": "run-1"}, "nodes": [target]})
    _write_json(
        tmp_path / f"fault_state_{fault_id}.json",
        {
            "fault_id": fault_id,
            "fault_type": "node_stop",
            "capability_id": "fault_matrix",
            "run_id": "run-1",
            "target_logical_id": "node-0",
            "target": target,
            "observed_impact": {"action": "process_stop"},
            "safety_checks": {"sandbox_only": True},
        },
    )

    calls: list[list[str]] = []

    def fake_run_docker(args, timeout=30, check=True):
        calls.append(list(args))
        if args[:2] == ["inspect", "-f"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "org.valkey-scale-lab.project": "valkey-scale-lab",
                        "org.valkey-scale-lab.capability_id": "fault_matrix",
                        "org.valkey-scale-lab.run_id": "run-1",
                    }
                ),
                stderr="",
            )
        if args[:3] == ["exec", "owned-nodehost", "cat"]:
            return SimpleNamespace(returncode=0, stdout="4321\n", stderr="")
        if args[:3] == ["exec", "owned-nodehost", "valkey-cli"]:
            return SimpleNamespace(returncode=0, stdout="PONG\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sandbox, "run_docker", fake_run_docker)

    report = sandbox.clear_fault(state_path=state_path, fault_id=fault_id, out_path=tmp_path / "clear.json")

    assert report["status"] == "PASS"
    assert report["observed_impact"]["pid"] == 4321
    assert ["exec", "owned-nodehost", "rm", "-f", "/tmp/node-0/valkey.pid"] in calls
    assert ["exec", "owned-nodehost", "sh", "-c", "valkey-server /tmp/node-0/valkey.conf"] in calls
    assert ["exec", "owned-nodehost", "valkey-cli", "-p", "7800", "PING"] in calls


def test_process_clear_fails_if_restart_never_pings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = tmp_path / "state.json"
    fault_id = "fault-node-stop"
    target = {
        "logical_id": "node-0",
        "nodehost_container_name": "owned-nodehost",
        "config_file": "/tmp/node-0/valkey.conf",
        "pid_file": "/tmp/node-0/valkey.pid",
        "client_port": 7800,
    }
    _write_json(state_path, {"capability_id": "fault_matrix", "runtime": {"run_id": "run-1"}, "nodes": [target]})
    _write_json(
        tmp_path / f"fault_state_{fault_id}.json",
        {
            "fault_id": fault_id,
            "fault_type": "node_stop",
            "capability_id": "fault_matrix",
            "run_id": "run-1",
            "target_logical_id": "node-0",
            "target": target,
            "observed_impact": {"action": "process_stop"},
            "safety_checks": {"sandbox_only": True},
        },
    )

    def fake_run_docker(args, timeout=30, check=True):
        if args[:2] == ["inspect", "-f"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "org.valkey-scale-lab.project": "valkey-scale-lab",
                        "org.valkey-scale-lab.capability_id": "fault_matrix",
                        "org.valkey-scale-lab.run_id": "run-1",
                    }
                ),
                stderr="",
            )
        if args[:3] == ["exec", "owned-nodehost", "cat"]:
            return SimpleNamespace(returncode=0, stdout="4321\n", stderr="")
        if args[:3] == ["exec", "owned-nodehost", "valkey-cli"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="connection refused")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sandbox, "run_docker", fake_run_docker)
    monkeypatch.setattr(sandbox, "_process_restart_timeout_seconds", lambda _existing: 20.0)
    monkeypatch.setattr(sandbox, "_process_restart_attempts", lambda _existing: 1)
    ticks = iter([0.0, 0.1, 21.0])
    monkeypatch.setattr(sandbox.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(sandbox.time, "sleep", lambda _seconds: None)

    with pytest.raises(sandbox.FaultError, match="did not become ready"):
        sandbox.clear_fault(state_path=state_path, fault_id=fault_id, out_path=tmp_path / "clear.json")


def test_fault_matrix_200_process_clear_uses_longer_restart_readiness_timeout() -> None:
    assert sandbox._process_restart_timeout_seconds({"profile_id": "exact-200"}) == 90.0
    assert sandbox._process_restart_timeout_seconds({"profile_id": "exact-100"}) == 20.0
    assert sandbox._process_restart_stable_seconds({"profile_id": "exact-200"}) == 2.0
    assert sandbox._process_restart_stable_seconds({"profile_id": "exact-100"}) == 0.0
    assert sandbox._process_restart_attempts({"profile_id": "exact-200"}) == 2
    assert sandbox._process_restart_attempts({"profile_id": "exact-100"}) == 1
