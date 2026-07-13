"""Hermetic checks for the controller-owned refactored real-Gate path.

These tests never contact Docker or Valkey and are not real admission evidence.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import pytest

from valkey_scale_lab import milestone1_gate
from valkey_scale_lab.gates import (
    FaultTargetKind,
    GateRequest,
    GateService,
    GateStatus,
    LegacyGateAdapter,
    LegacyRuntimeEntrypoints,
    OwnedFaultScope,
    StepStatus,
)
from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.scenarios import compile_gate_plan, load_milestone1_definition


def _request(tmp_path: Path, *, nodes: int = 50) -> GateRequest:
    run_id = f"refactored-real-{nodes}"
    owner = f"controller-owner-{nodes}"
    return GateRequest(
        run_id=run_id,
        ownership_id=owner,
        provenance_id=f"capture-{nodes}",
        requested_nodes=nodes,
        artifact_root=tmp_path / f"evidence-{nodes}",
        fault_scope=OwnedFaultScope(
            run_id=run_id,
            ownership_id=owner,
            kind=FaultTargetKind.NAMESPACE,
            resource_ids=(f"sandbox-{nodes}",),
        ),
    )


def _entrypoints(
    calls: list[str],
    *,
    observed_nodes: int = 50,
    preflight_passes: bool = True,
    preflight_nodes: int | None = None,
    probe: Callable[..., dict[str, Any]] | None = None,
    cleanup_status: str = "PASS",
) -> LegacyRuntimeEntrypoints:
    def preflight(**kwargs: Any) -> dict[str, Any]:
        calls.append("preflight")
        report = {
            "status": "PASS" if preflight_passes else "FAIL",
            "can_run": preflight_passes,
            "nodes_requested": (
                kwargs["requested_nodes"]
                if preflight_nodes is None
                else preflight_nodes
            ),
        }
        Path(kwargs["out_path"]).write_text(json.dumps(report), encoding="utf-8")
        return report

    def create(**kwargs: Any) -> dict[str, Any]:
        calls.append("create")
        state = {
            "phase_id": kwargs["phase"],
            "scenario": kwargs["scenario"],
            "runtime": {"run_id": "owned-legacy-runtime"},
            "nodes": [
                {"logical_id": f"node-{index:03d}"}
                for index in range(observed_nodes)
            ],
        }
        path = Path(kwargs["state_out"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
        return state

    def live_probe(**kwargs: Any) -> dict[str, Any]:
        calls.append("probe")
        if probe is not None:
            return probe(**kwargs)
        return {
            "status": "PASS",
            "observed_nodes": kwargs["requested_nodes"],
            "independent_probe": {
                "cluster_state": "ok",
                "known_nodes": kwargs["requested_nodes"],
                "slots_assigned": 16384,
                "slots_ok": 16384,
            },
            "valkey_versions": ["9.1.2"],
        }

    def cleanup(**kwargs: Any) -> dict[str, Any]:
        calls.append("cleanup")
        report = {
            "status": cleanup_status,
            "run_id": "owned-legacy-runtime",
            "resources_remaining": [] if cleanup_status == "PASS" else ["owned"],
            "cleanup_errors": [] if cleanup_status == "PASS" else ["cleanup failed"],
        }
        Path(kwargs["out_path"]).write_text(json.dumps(report), encoding="utf-8")
        return report

    return LegacyRuntimeEntrypoints(
        create=create,
        cleanup=cleanup,
        preflight=preflight,
        live_probe=live_probe,
    )


def _execute(tmp_path: Path, entrypoints: LegacyRuntimeEntrypoints, *, nodes: int = 50):
    request = _request(tmp_path, nodes=nodes)
    adapter = LegacyGateAdapter(entrypoints)
    result = GateService().execute(
        compile_gate_plan(load_milestone1_definition(), nodes),
        request,
        adapter.adapter_bundle(),
    )
    snapshot = adapter.execution_snapshot(
        run_id=request.run_id,
        ownership_id=request.ownership_id,
        provenance_id=request.provenance_id,
    )
    return result, snapshot


def test_real_projection_orders_preflight_probe_and_single_outer_cleanup(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    result, snapshot = _execute(tmp_path, _entrypoints(calls))

    assert result.status is GateStatus.PASS
    assert calls == ["preflight", "create", "probe", "cleanup"]
    assert sum(step.step_id == "cleanup" for step in result.step_results) == 1
    assert any(
        row["name"] == "cleanup" and row["status"] == "PASS"
        for row in snapshot.setup_segments
    )
    assert snapshot.live_probe_result is not None
    assert snapshot.live_probe_result["observed_nodes"] == 50
    assert snapshot.state is not None
    with pytest.raises(TypeError):
        snapshot.state["nodes"] = ()  # type: ignore[index]


def test_blocked_preflight_never_creates_runtime(tmp_path: Path) -> None:
    calls: list[str] = []

    result, _snapshot = _execute(
        tmp_path,
        _entrypoints(calls, preflight_passes=False),
    )

    assert result.status is GateStatus.BLOCKED
    assert result.steps[0].status is StepStatus.BLOCKED
    assert calls == ["preflight"]


def test_preflight_node_mismatch_blocks_without_downscaling(tmp_path: Path) -> None:
    calls: list[str] = []

    result, _snapshot = _execute(
        tmp_path,
        _entrypoints(calls, preflight_nodes=49),
    )

    assert result.status is GateStatus.BLOCKED
    assert result.steps[0].status is StepStatus.BLOCKED
    assert "requested=50, observed=49" in (result.primary_failure.reason if result.primary_failure else "")
    assert calls == ["preflight"]


def test_live_probe_failure_still_cleans_exactly_once(tmp_path: Path) -> None:
    calls: list[str] = []

    def fail_probe(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("live exact probe failed")

    result, _snapshot = _execute(
        tmp_path,
        _entrypoints(calls, probe=fail_probe),
    )

    assert result.status is GateStatus.FAIL
    assert result.primary_failure is not None
    assert result.primary_failure.step_id == "recovery"
    assert result.primary_failure.reason == "live exact probe failed"
    assert calls == ["preflight", "create", "probe", "cleanup"]
    assert calls.count("cleanup") == 1


def test_runtime_returning_49_nodes_fails_without_downscale(tmp_path: Path) -> None:
    calls: list[str] = []

    result, _snapshot = _execute(
        tmp_path,
        _entrypoints(calls, observed_nodes=49),
    )

    assert result.status is GateStatus.FAIL
    assert result.requested_nodes == 50
    assert result.primary_failure is not None
    assert "requested=50, observed=49" in result.primary_failure.reason
    assert calls == ["preflight", "create", "cleanup"]


def test_probe_and_cleanup_failures_are_both_preserved(tmp_path: Path) -> None:
    calls: list[str] = []

    def fail_probe(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("probe primary failure")

    result, _snapshot = _execute(
        tmp_path,
        _entrypoints(calls, probe=fail_probe, cleanup_status="FAIL"),
    )

    assert result.primary_failure is not None
    assert result.primary_failure.reason == "probe primary failure"
    assert result.cleanup_failure is not None
    assert result.cleanup_failure.reason == "legacy cleanup did not PASS"
    message = milestone1_gate._gate_failure_message(result)
    assert "probe primary failure" in message
    assert "legacy cleanup did not PASS" in message
    assert calls.count("cleanup") == 1


def test_run_real_gate_uses_compiled_service_then_canonical_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    product_digest = "a" * 64
    monkeypatch.setenv("VSLAB_META_M1_CONTROLLER_OWNED", "1")
    monkeypatch.setenv("VSLAB_META_M1_PRODUCT_DIGEST", product_digest)
    monkeypatch.setattr(milestone1_gate, "_require_docker_daemon", lambda: None)

    def preflight(_config: Any, out: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append("preflight")
        report = {
            "schema_version": "v1",
            "status": "PASS",
            "can_run": True,
            "nodes_requested": 50,
            "node_count": 50,
            "checks": [{"name": "hermetic", "status": "PASS"}],
            "phase_id": kwargs["phase_id"],
            "scenario_name": kwargs["scenario"],
        }
        Path(out).write_text(json.dumps(report), encoding="utf-8")
        return report

    def create(**kwargs: Any) -> dict[str, Any]:
        calls.append("create")
        timeline = kwargs["setup_timeline"]
        for name, category in [
            ("runtime_boot", "runtime_start"),
            ("cluster_boot", "cluster_formation"),
            ("stabilize", "stabilize"),
            ("baseline_workload", "baseline_workload"),
            ("management_matrix", "management_matrix"),
            ("fault_matrix", "fault_matrix"),
            ("recovery", "recovery"),
            ("artifact_validation", "artifact_validation"),
            ("analysis", "analysis"),
            ("report", "report"),
        ]:
            with timeline.span(name, category):
                time.sleep(0.0001)
        state = {
            "cluster_id": milestone1_gate._run_id(kwargs["phase"], kwargs["scenario"]),
            "phase_id": kwargs["phase"],
            "scenario": kwargs["scenario"],
            "runtime": {
                "run_id": milestone1_gate._run_id(kwargs["phase"], kwargs["scenario"])
            },
            "nodes": [{"logical_id": f"node-{index:03d}"} for index in range(50)],
        }
        state_path = Path(kwargs["state_out"])
        state_path.write_text(json.dumps(state), encoding="utf-8")
        (Path(kwargs["artifacts_dir"]) / "events.jsonl").write_text("", encoding="utf-8")
        return state

    def cleanup(**kwargs: Any) -> dict[str, Any]:
        calls.append("cleanup")
        report = {
            "schema_version": "v1",
            "status": "PASS",
            "resources_remaining": [],
            "cleanup_errors": [],
        }
        Path(kwargs["out_path"]).write_text(json.dumps(report), encoding="utf-8")
        return report

    def build(base: Path, scale: int, digest: str, **kwargs: Any) -> dict[str, Any]:
        calls.append("admission")
        assert scale == 50
        assert digest == product_digest
        assert kwargs["valkey_versions"] == ["9.1.2"]
        assert kwargs["independent_probe"]["known_nodes"] == 50
        assert (base / "runtime/lifecycle_timeline.json").is_file()
        return {"status": "PASS", "requested_nodes": scale}

    def probe_health(_nodes: Any) -> dict[str, Any]:
        calls.append("probe")
        return {
            "cluster_state": "ok",
            "known_nodes": 50,
            "slots_assigned": 16384,
            "slots_ok": 16384,
        }

    monkeypatch.setattr(milestone1_gate, "run_resource_preflight", preflight)
    monkeypatch.setattr(milestone1_gate, "create_scenario", create)
    monkeypatch.setattr(milestone1_gate, "cleanup_scenario", cleanup)
    monkeypatch.setattr(
        milestone1_gate,
        "_p17_cluster_health",
        probe_health,
    )
    monkeypatch.setattr(milestone1_gate, "_observed_versions", lambda _nodes: ["9.1.2"])
    monkeypatch.setattr(milestone1_gate, "validate_raw_sources", lambda *_args: ())
    monkeypatch.setattr(milestone1_gate, "_build_candidate_admission", build)

    result = milestone1_gate.run_real_gate(50, tmp_path / "scale-50")

    assert result == {"status": "PASS", "requested_nodes": 50}
    assert calls == ["preflight", "create", "probe", "cleanup", "admission"]


def test_large_partition_observations_keep_cluster_state_in_bounded_excerpts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nodes = [
        {
            "logical_id": "isolated",
            "nodehost_container_name": "nodehost-a",
            "nodehost_container_ip": "172.18.0.2",
            "client_port": 7000,
        },
        {
            "logical_id": "majority",
            "nodehost_container_name": "nodehost-b",
            "client_port": 7001,
        },
    ]

    def run_docker(args: list[str], **_kwargs: Any) -> docker_runtime.DockerResult:
        if args[0] == "inspect":
            return docker_runtime.DockerResult("{}\n", "", 0)
        return docker_runtime.DockerResult("", "", 0)

    def node_command(_node: dict[str, Any], *args: Any, **_kwargs: Any) -> str:
        if args == ("PING",):
            return "PONG"
        return "cluster_state:ok\n" + ("cluster_stat:1\n" * 200)

    monkeypatch.setattr(docker_runtime, "run_docker", run_docker)
    monkeypatch.setattr(docker_runtime, "_node_command", node_command)
    monkeypatch.setattr(
        docker_runtime,
        "_p36_wait_clean_cluster_snapshot",
        lambda *_args, **_kwargs: None,
    )

    details = docker_runtime._p36_network_disconnect_probe(
        "owned-network",
        "nodehost-a",
        nodes,
        "network_partition",
    )

    docker_runtime._p36_validate_fault_probe_observation(
        "network_partition", details
    )
    assert len(details["majority_cluster_info"]) <= 1000
    assert len(details["isolated_cluster_info"]) <= 1000
    assert details["majority_cluster_info"].startswith("cluster_state:ok")
    assert details["isolated_cluster_info"].startswith("cluster_state:ok")


def test_cleanup_ownership_check_accepts_an_already_removed_owned_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {
        "phase_id": "P36_FULL_FLOW_E2E_50_100_200_REAL",
        "runtime": {"run_id": "owned-run"},
        "nodehosts": [
            {"nodehost_id": "az-a-00", "container_name": "removed-nodehost"}
        ],
        "nodes": [
            {
                "logical_id": "node-000",
                "nodehost_id": "az-a-00",
                "nodehost_container_name": "removed-nodehost",
                "pid": 101,
            }
        ],
    }

    def missing_only(
        args: list[str], **_kwargs: Any
    ) -> docker_runtime.DockerResult:
        assert args[:2] == ["inspect", "-f"]
        return docker_runtime.DockerResult(
            "", "Error: No such object: removed-nodehost", 1
        )

    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        missing_only,
    )
    monkeypatch.setattr(
        docker_runtime,
        "_cleanup_resources_by_label",
        lambda **_kwargs: (
            [],
            {
                "cleanup_remove_containers_seconds": 0.0,
                "cleanup_remove_networks_seconds": 0.0,
            },
        ),
    )
    monkeypatch.setattr(
        docker_runtime,
        "owned_resources",
        lambda **_kwargs: [],
    )

    report = docker_runtime._cleanup_process_scenario(
        state=state,
        artifacts_dir=tmp_path,
        out_path=tmp_path / "cleanup.json",
    )

    assert report["status"] == "PASS"
    assert any(
        action["action"] == "already_absent"
        and action["container_name"] == "removed-nodehost"
        for action in report["cleanup_actions"]
    )

    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        lambda *_args, **_kwargs: docker_runtime.DockerResult(
            json.dumps({f"{docker_runtime.LABEL_PREFIX}.project": "other"}),
            "",
            0,
        ),
    )
    with pytest.raises(docker_runtime.DockerRuntimeError, match="not an owned"):
        docker_runtime._require_cleanup_owned_nodehosts(
            state,
            phase=state["phase_id"],
            run_id=state["runtime"]["run_id"],
        )
