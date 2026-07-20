from __future__ import annotations

import json
from pathlib import Path

import pytest

from valkey_scale_lab.fault.sandbox import FaultError, apply_fault, clear_fault


def _state(path: Path) -> Path:
    data = {
        "schema_version": "v1",
        "cluster_id": "test",
        "capability_id": "fault_matrix",
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
    assert apply_report["implementation_path"] == "sandbox_proxy"
    assert apply_report["safety_checks"]["host_network_mutated"] is False
    assert (tmp_path / "fault_state_fault-sandbox-smoke.json").exists()

    clear_report = clear_fault(state_path=state, fault_id="fault-sandbox-smoke", out_path=tmp_path / "fault_clear.json")
    assert clear_report["status"] == "PASS"
    assert clear_report["observed_impact"]["implementation_path"] == "sandbox_proxy"
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


def test_fault_rejects_unknown_target(tmp_path: Path) -> None:
    state = _state(tmp_path / "state.json")
    spec = tmp_path / "fault.json"
    spec.write_text(
        json.dumps(
            {
                "fault_id": "missing-target",
                "type": "network_delay",
                "forbid_host_network_mutation": True,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(FaultError, match="target logical id not found"):
        apply_fault(state_path=state, target_logical_id="shard-9999-primary", fault_json=spec, out_path=tmp_path / "out.json")


def test_fault_rejects_unsupported_fault_type(tmp_path: Path) -> None:
    state = _state(tmp_path / "state.json")
    spec = tmp_path / "fault.json"
    spec.write_text(
        json.dumps(
            {
                "fault_id": "unsafe-route",
                "type": "host_route_change",
                "forbid_host_network_mutation": True,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(FaultError, match="unsupported fault type"):
        apply_fault(state_path=state, target_logical_id="shard-0000-primary", fault_json=spec, out_path=tmp_path / "out.json")


def test_node_stop_requires_owned_process_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    def fake_run_docker(args: list[str], **kwargs: object) -> object:
        calls.append(args)
        raise AssertionError(f"node_stop without a process target must not call Docker: {args}")

    monkeypatch.setattr("valkey_scale_lab.fault.sandbox.run_docker", fake_run_docker)
    with pytest.raises(FaultError, match="owned-process target"):
        apply_fault(
            state_path=state,
            target_logical_id="shard-0000-primary",
            fault_json=spec,
            out_path=tmp_path / "fault_apply.json",
        )
    assert calls == []


def test_node_stop_process_runtime_targets_logical_pid_not_shared_nodehost(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = {
        "schema_version": "v1",
        "cluster_id": "test",
        "capability_id": "scale_ladder",
        "runtime": {"run_id": "test-run", "sandbox_network": True, "type": "docker_process"},
        "nodes": [
            {
                "logical_id": "shard-0000-primary",
                "az_id": "az-a",
                "container_name": "shared-nodehost",
                "nodehost_container_name": "shared-nodehost",
                "config_file": "/tmp/test-run/shard-0000-primary/valkey.conf",
                "pid": 101,
            },
            {
                "logical_id": "shard-0001-primary",
                "az_id": "az-b",
                "container_name": "shared-nodehost",
                "nodehost_container_name": "shared-nodehost",
                "pid": 202,
            },
        ],
    }
    state = tmp_path / "state.json"
    state.write_text(json.dumps(data), encoding="utf-8")
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
        def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run_docker(args: list[str], **kwargs: object) -> Result:
        calls.append(args)
        if args[0] == "inspect":
            return Result(
                stdout=json.dumps(
                    {
                        "org.valkey-scale-lab.project": "valkey-scale-lab",
                        "org.valkey-scale-lab.capability_id": "scale_ladder",
                        "org.valkey-scale-lab.run_id": "test-run",
                    }
                )
            )
        return Result()

    monkeypatch.setattr("valkey_scale_lab.fault.sandbox.run_docker", fake_run_docker)
    report = apply_fault(
        state_path=state,
        target_logical_id="shard-0000-primary",
        fault_json=spec,
        out_path=tmp_path / "fault_apply.json",
    )
    assert report["status"] == "PASS"
    fault_state = json.loads((tmp_path / "fault_state_fault-primary-stop.json").read_text(encoding="utf-8"))
    assert fault_state["observed_impact"]["action"] == "process_sigkill"
    assert fault_state["observed_impact"]["signal"] == "SIGKILL"
    assert fault_state["observed_impact"]["independent_runtime_state"]["probe"] == "container_proc_absent"
    assert calls == [
        ["inspect", "-f", "{{json .Config.Labels}}", "shared-nodehost"],
        ["exec", "shared-nodehost", "sh", "-c", "test -e /proc/101 && kill -0 101"],
        ["exec", "shared-nodehost", "sh", "-c", "kill -KILL 101"],
        ["exec", "shared-nodehost", "sh", "-c", "test ! -e /proc/101"],
    ]

    clear_report = clear_fault(state_path=state, fault_id="fault-primary-stop", out_path=tmp_path / "fault_clear.json")
    assert clear_report["status"] == "PASS"
    assert clear_report["observed_impact"]["action"] == "process_restart"
    assert calls == [
        ["inspect", "-f", "{{json .Config.Labels}}", "shared-nodehost"],
        ["exec", "shared-nodehost", "sh", "-c", "test -e /proc/101 && kill -0 101"],
        ["exec", "shared-nodehost", "sh", "-c", "kill -KILL 101"],
        ["exec", "shared-nodehost", "sh", "-c", "test ! -e /proc/101"],
        ["inspect", "-f", "{{json .Config.Labels}}", "shared-nodehost"],
        ["exec", "shared-nodehost", "sh", "-c", "valkey-server /tmp/test-run/shard-0000-primary/valkey.conf"],
    ]


def test_node_stop_fails_when_sigkill_target_remains_in_runtime_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = {
        "schema_version": "v1",
        "cluster_id": "test",
        "capability_id": "scale_ladder",
        "runtime": {"run_id": "test-run", "sandbox_network": True, "type": "docker_process"},
        "nodes": [
            {
                "logical_id": "shard-0000-primary",
                "az_id": "az-a",
                "nodehost_container_name": "shared-nodehost",
                "config_file": "/tmp/test-run/shard-0000-primary/valkey.conf",
                "pid": 101,
            }
        ],
    }
    state = tmp_path / "state.json"
    state.write_text(json.dumps(data), encoding="utf-8")
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

    class Result:
        def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run_docker(args: list[str], **kwargs: object) -> Result:
        if args[0] == "inspect":
            return Result(
                stdout=json.dumps(
                    {
                        "org.valkey-scale-lab.project": "valkey-scale-lab",
                        "org.valkey-scale-lab.capability_id": "scale_ladder",
                        "org.valkey-scale-lab.run_id": "test-run",
                    }
                )
            )
        if args == ["exec", "shared-nodehost", "sh", "-c", "test ! -e /proc/101"]:
            return Result(returncode=1, stderr="still present")
        return Result()

    monkeypatch.setattr("valkey_scale_lab.fault.sandbox.run_docker", fake_run_docker)
    ticks = iter([0.0, 0.1, 11.0])
    monkeypatch.setattr("valkey_scale_lab.fault.sandbox.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("valkey_scale_lab.fault.sandbox.time.sleep", lambda _seconds: None)

    with pytest.raises(FaultError, match="remained present"):
        apply_fault(
            state_path=state,
            target_logical_id="shard-0000-primary",
            fault_json=spec,
            out_path=tmp_path / "fault_apply.json",
        )
