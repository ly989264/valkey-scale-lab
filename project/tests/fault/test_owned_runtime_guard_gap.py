from __future__ import annotations

import json
from pathlib import Path

import pytest

from valkey_scale_lab.fault.sandbox import FaultError, apply_fault, clear_fault


def test_node_stop_rejects_state_target_without_runtime_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "cluster_id": "claimed-run",
                "capability_id": "fault_matrix",
                "runtime": {"run_id": "claimed-run", "sandbox_network": True, "type": "docker"},
                "nodes": [
                    {
                        "logical_id": "shard-0000-primary",
                        "container_name": "foreign-container",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fault = tmp_path / "fault.json"
    fault.write_text(
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
    destructive_calls: list[list[str]] = []

    class Result:
        returncode = 0
        stderr = ""
        stdout = "{}"

    def fake_run_docker(args: list[str], **kwargs: object) -> Result:
        if args and args[0] in {"stop", "rm", "kill"}:
            destructive_calls.append(args)
        return Result()

    monkeypatch.setattr("valkey_scale_lab.fault.sandbox.run_docker", fake_run_docker)

    with pytest.raises(FaultError, match="owned|ownership|label"):
        apply_fault(
            state_path=state,
            target_logical_id="shard-0000-primary",
            fault_json=fault,
            out_path=tmp_path / "fault_apply.json",
        )

    assert destructive_calls == []


def test_node_stop_clear_rechecks_runtime_ownership_before_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "capability_id": "fault_matrix",
                "runtime": {"run_id": "claimed-run"},
                "nodes": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "fault_state_fault-primary-stop.json").write_text(
        json.dumps(
            {
                "fault_id": "fault-primary-stop",
                "fault_type": "node_stop",
                "capability_id": "fault_matrix",
                "run_id": "claimed-run",
                "target": {"container_name": "replaced-container"},
                "observed_impact": {
                    "action": "container_stop",
                    "container_name": "replaced-container",
                },
            }
        ),
        encoding="utf-8",
    )
    destructive_calls: list[list[str]] = []

    class Result:
        returncode = 0
        stderr = ""
        stdout = "{}"

    def fake_run_docker(args: list[str], **kwargs: object) -> Result:
        if args and args[0] in {"start", "exec"}:
            destructive_calls.append(args)
        return Result()

    monkeypatch.setattr("valkey_scale_lab.fault.sandbox.run_docker", fake_run_docker)

    with pytest.raises(FaultError, match="owned|ownership|label"):
        clear_fault(
            state_path=state,
            fault_id="fault-primary-stop",
            out_path=tmp_path / "fault_clear.json",
        )

    assert destructive_calls == []
