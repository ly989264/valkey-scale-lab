from __future__ import annotations

import json
from pathlib import Path

import pytest

from valkey_scale_lab.fault.sandbox import FaultError, apply_fault, clear_fault


def _state(path: Path) -> Path:
    data = {
        "schema_version": "v1",
        "cluster_id": "test",
        "phase_id": "P07_FAULT_INJECTION_SANDBOX",
        "runtime": {"run_id": "test-run", "sandbox_network": True},
        "nodes": [{"logical_id": "shard-0000-primary", "az_id": "az-a", "container_name": "owned"}],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_apply_and_clear_fault_report(tmp_path: Path) -> None:
    state = _state(tmp_path / "state.json")
    spec = tmp_path / "fault.json"
    spec.write_text(
        json.dumps(
            {
                "fault_id": "fault-sandbox-smoke",
                "type": "network_delay",
                "scope": "container_namespace_or_sandbox_proxy",
                "forbid_host_network_mutation": True,
            }
        ),
        encoding="utf-8",
    )
    apply_report = apply_fault(
        state_path=state,
        target_logical_id="shard-0000-primary",
        fault_json=spec,
        out_path=tmp_path / "fault_apply.json",
    )
    assert apply_report["status"] == "PASS"
    assert apply_report["safety_checks"]["host_network_mutated"] is False
    assert (tmp_path / "fault_state_fault-sandbox-smoke.json").exists()

    clear_report = clear_fault(state_path=state, fault_id="fault-sandbox-smoke", out_path=tmp_path / "fault_clear.json")
    assert clear_report["status"] == "PASS"
    assert not (tmp_path / "fault_state_fault-sandbox-smoke.json").exists()
    fault_report = json.loads((tmp_path / "fault_report.json").read_text(encoding="utf-8"))
    assert fault_report["artifact_type"] == "fault_report"
    assert fault_report["safety_checks"]["sandbox_only"] is True
    assert fault_report["faults"][0]["clear_status"] == "PASS"


def test_fault_requires_host_network_guard(tmp_path: Path) -> None:
    state = _state(tmp_path / "state.json")
    spec = tmp_path / "fault.json"
    spec.write_text(json.dumps({"fault_id": "bad", "type": "network_delay"}), encoding="utf-8")
    with pytest.raises(FaultError, match="forbid host network"):
        apply_fault(state_path=state, target_logical_id="shard-0000-primary", fault_json=spec, out_path=tmp_path / "out.json")


def test_node_stop_stops_owned_container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(tmp_path / "state.json")
    spec = tmp_path / "fault.json"
    spec.write_text(
        json.dumps(
            {
                "fault_id": "fault-primary-stop",
                "type": "node_stop",
                "scope": "owned_container_or_process",
                "forbid_host_network_mutation": True,
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run_docker(args: list[str], **kwargs: object) -> Result:
        calls.append(args)
        return Result()

    monkeypatch.setattr("valkey_scale_lab.fault.sandbox.run_docker", fake_run_docker)
    report = apply_fault(
        state_path=state,
        target_logical_id="shard-0000-primary",
        fault_json=spec,
        out_path=tmp_path / "fault_apply.json",
    )
    assert report["status"] == "PASS"
    assert calls == [["stop", "-t", "5", "owned"]]
