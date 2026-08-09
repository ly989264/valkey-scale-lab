"""Hermetic checks for the product-owned exact real-Gate path.

These tests never contact Docker or Valkey and are not real admission evidence.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import pytest

from valkey_scale_lab.gates import real as exact_gate
from valkey_scale_lab.gates import (
    FaultTargetKind,
    GateRequest,
    GateService,
    GateStatus,
    ProductGateAdapter,
    ProductRuntimeEntrypoints,
    OwnedFaultScope,
    StepStatus,
)
from valkey_scale_lab.evidence import RawSourceErrors
from valkey_scale_lab.observability.contracts import CollectionError
from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.runtime.docker_runtime import DockerRuntimeError
from valkey_scale_lab.scenarios import compile_gate_plan, load_local_full_flow_definition


DEFINITION = load_local_full_flow_definition()


def _request(tmp_path: Path, *, nodes: int = 50) -> GateRequest:
    run_id = f"refactored-real-{nodes}"
    owner = f"product-owner-{nodes}"
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
) -> ProductRuntimeEntrypoints:
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

    def execute(**kwargs: Any) -> dict[str, Any]:
        calls.append("create")
        state = {
            "capability_id": kwargs["capability_id"],
            "scenario_id": kwargs["scenario_id"],
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

    return ProductRuntimeEntrypoints(
        execute=execute,
        cleanup=cleanup,
        preflight=preflight,
        live_probe=live_probe,
    )


def _execute(tmp_path: Path, entrypoints: ProductRuntimeEntrypoints, *, nodes: int = 50):
    request = _request(tmp_path, nodes=nodes)
    adapter = ProductGateAdapter(entrypoints)
    result = GateService().execute(
        compile_gate_plan(DEFINITION, nodes),
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
    assert result.cleanup_failure.reason == "cleanup did not PASS"
    message = exact_gate._gate_failure_message(result)
    assert "probe primary failure" in message
    assert "cleanup did not PASS" in message
    assert calls.count("cleanup") == 1


def test_run_exact_gate_uses_compiled_service_then_canonical_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    product_digest = "a" * 64
    monkeypatch.setattr(exact_gate, "_require_docker_daemon", lambda: None)

    def preflight(_config: Any, out: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append("preflight")
        report = {
            "schema_version": "v1",
            "status": "PASS",
            "can_run": True,
            "nodes_requested": 50,
            "node_count": 50,
            "checks": [{"name": "hermetic", "status": "PASS"}],
            "capability_id": kwargs["capability_id"],
            "scenario_name": kwargs["scenario"],
        }
        Path(out).write_text(json.dumps(report), encoding="utf-8")
        return report

    def execute(**kwargs: Any) -> dict[str, Any]:
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
            "cluster_id": "owned-runtime-50",
            "capability_id": kwargs["capability_id"],
            "scenario_id": kwargs["scenario_id"],
            "runtime": {
                "run_id": "owned-runtime-50"
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

    monkeypatch.setattr(exact_gate, "run_resource_preflight", preflight)
    monkeypatch.setattr(exact_gate, "execute_scenario", execute)
    monkeypatch.setattr(exact_gate, "cleanup_scenario", cleanup)
    monkeypatch.setattr(
        exact_gate,
        "_management_cluster_health",
        probe_health,
    )
    monkeypatch.setattr(exact_gate, "_observed_versions", lambda _nodes: ["9.1.2"])
    # Two entry points into the validator from this module: `run_exact_gate` reads
    # the split, because the kind of a source-evidence problem decides whether the
    # run reports FAIL or ERROR, and `build_admission_from_sources` re-checks
    # admissibility through the flat helper.
    monkeypatch.setattr(
        exact_gate, "validate_raw_sources_by_kind", lambda *_args: RawSourceErrors()
    )
    monkeypatch.setattr(exact_gate, "validate_raw_sources", lambda *_args: ())
    monkeypatch.setattr(exact_gate, "_build_candidate_admission", build)

    result = exact_gate.run_exact_gate(
        definition=DEFINITION,
        scale=50,
        config_path="templates/configs/scale_50.yaml",
        evidence_dir=tmp_path / "scale-50",
        run_id="exact-run-50",
        ownership_id="product-owner-50",
        provenance_id="capture-50",
        product_digest=product_digest,
    )

    assert result == {"status": "PASS", "requested_nodes": 50}
    assert calls == ["preflight", "create", "probe", "cleanup", "admission"]


def test_an_unreachable_docker_daemon_is_a_tool_error_not_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§12.1's 任务未发起: nothing was observed, so nothing can have failed.

    This is also the only tool error in the product that can be staged on a real
    invocation - point `DOCKER_HOST` at a socket that does not exist - which is
    what the whole ERROR verdict's real-run evidence rests on.
    """

    class Unreachable:
        returncode = 1
        stdout = ""
        stderr = "dial unix /nonexistent/docker.sock: connect: no such file or directory"

    monkeypatch.setattr(
        exact_gate.subprocess, "run", lambda *_a, **_k: Unreachable()
    )
    with pytest.raises(CollectionError, match="requires an available Docker daemon"):
        exact_gate._require_docker_daemon()

    def no_binary(*_a: Any, **_k: Any) -> Any:
        raise FileNotFoundError(2, "No such file or directory: 'docker'")

    monkeypatch.setattr(exact_gate.subprocess, "run", no_binary)
    with pytest.raises(CollectionError, match="could not run the Docker client"):
        exact_gate._require_docker_daemon()


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (CollectionError("resource sampler produced no evidence"), CollectionError),
        (DockerRuntimeError("cluster convergence did not hold"), DockerRuntimeError),
    ],
)
def test_a_step_tool_error_leaves_the_gate_as_a_tool_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raised: Exception,
    expected: type[Exception],
) -> None:
    """The kind of failure has to survive the Gate, which flattens every step
    exception into `GateStatus.FAIL`.

    §12.2's final result is not the Gate's lifecycle status - a collector that
    broke mid-run is not a fourth lifecycle outcome - so the class of the
    re-raised exception is what carries the distinction out to the run's own
    result.
    """

    monkeypatch.setattr(exact_gate, "_require_docker_daemon", lambda: None)
    cleanups: list[str] = []

    def preflight(_config: Any, out: Any, **kwargs: Any) -> dict[str, Any]:
        report = {
            "schema_version": "v1",
            "status": "PASS",
            "can_run": True,
            "nodes_requested": 50,
            "node_count": 50,
            "checks": [{"name": "hermetic", "status": "PASS"}],
            "capability_id": kwargs["capability_id"],
            "scenario_name": kwargs["scenario"],
        }
        Path(out).write_text(json.dumps(report), encoding="utf-8")
        return report

    def execute(**_kwargs: Any) -> dict[str, Any]:
        raise raised

    def cleanup(**kwargs: Any) -> dict[str, Any]:
        cleanups.append("cleanup")
        report = {
            "schema_version": "v1",
            "status": "PASS",
            "resources_remaining": [],
            "cleanup_errors": [],
        }
        Path(kwargs["out_path"]).write_text(json.dumps(report), encoding="utf-8")
        return report

    monkeypatch.setattr(exact_gate, "run_resource_preflight", preflight)
    monkeypatch.setattr(exact_gate, "execute_scenario", execute)
    monkeypatch.setattr(exact_gate, "cleanup_scenario", cleanup)

    with pytest.raises(expected) as excinfo:
        exact_gate.run_exact_gate(
            definition=DEFINITION,
            scale=50,
            config_path="templates/configs/scale_50.yaml",
            evidence_dir=tmp_path / "scale-50",
            run_id="exact-run-50",
            ownership_id="product-owner-50",
            provenance_id="capture-50",
            product_digest="a" * 64,
        )

    # `CollectionError` is a `RuntimeError` and `DockerRuntimeError` is not one
    # of its subclasses, so the exact class is what has to be asserted in both
    # directions: a cluster failure must not arrive as a tool error either.
    assert excinfo.type is expected
    assert cleanups == []  # runtime_start never produced state, so there is none
    code = "STEP_TOOL_ERROR" if expected is CollectionError else "STEP_EXCEPTION"
    assert code in str(excinfo.value)
    assert str(raised) in str(excinfo.value)

    # The failing run's own evidence, which used to not exist: measured across
    # both exact-200 baselines, every artifact a failing run leaves says PASS or
    # is absent, and only the Gate's summary reported the failure.
    verdict = json.loads(
        (tmp_path / "scale-50/runtime/run_verdict.json").read_text(encoding="utf-8")
    )
    assert verdict["status"] == ("ERROR" if expected is CollectionError else "FAIL")
    assert verdict["gate_status"] == "FAIL"
    # `execute_scenario` is the `runtime_start` handler, so that is the stage that
    # failed, and the preflight before it is the one stage that got a verdict.
    assert [(row["name"], row["status"]) for row in verdict["checks"]] == [
        ("resource_preflight", "OK"),
        ("runtime_start", "FAIL" if expected is DockerRuntimeError else "ERROR"),
        # The terminal stage is in the aggregation: `GateResult.steps` stops before
        # it and `step_results` appends it, and cleanup is the one stage whose
        # verdict must never be missing.
        ("cleanup", "OK"),
    ]
    failed = [row for row in verdict["checks"] if row["status"] != "OK"]
    assert str(raised) in failed[0]["reason"]
    # §12.2 lists tool errors separately, and only when there are any.
    assert verdict["tool_errors"] == (
        ["runtime_start"] if expected is CollectionError else []
    )
    # The nine stages fail-fast never ran are recorded, not counted as
    # observations - neither as OK, which would be a claim, nor as ERROR, which
    # would put fail-fast's own bookkeeping into tool_errors.
    assert [row["stage"] for row in verdict["stages_not_run"]] == [
        "cluster_form",
        "stabilize",
        "baseline_workload",
        "management_matrix",
        "fault_matrix",
        "recovery",
        "artifact_validation",
        "analysis",
        "report",
    ]
    assert all(row["reason"] for row in verdict["stages_not_run"])
    names = {row["name"] for row in verdict["checks"]}
    assert names.isdisjoint({row["stage"] for row in verdict["stages_not_run"]})


def test_large_partition_observations_keep_cluster_state_in_bounded_excerpts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nodes = [
        {
            "logical_id": "isolated",
            "nodehost_id": "nodehost-a",
            "nodehost_container_name": "nodehost-a",
            "nodehost_container_ip": "172.18.0.2",
            "client_port": 7000,
        },
        {
            "logical_id": "majority",
            "nodehost_id": "nodehost-b",
            "nodehost_container_name": "nodehost-b",
            "client_port": 7001,
        },
    ]
    nodehost = {
        "nodehost_id": "nodehost-a",
        "container_name": "nodehost-a",
        "container_ip": "172.18.0.2",
        "network_name": "owned-network",
    }

    def run_docker(args: list[str], **_kwargs: Any) -> docker_runtime.DockerResult:
        if args[0] == "inspect":
            return docker_runtime.DockerResult("{}\n", "", 0)
        return docker_runtime.DockerResult("", "", 0)

    def host_command(_node: dict[str, Any], *args: Any, **_kwargs: Any) -> str:
        if args == ("PING",):
            return "PONG"
        return "cluster_state:ok\n" + ("cluster_stat:1\n" * 200)

    monkeypatch.setattr(docker_runtime, "run_docker", run_docker)
    monkeypatch.setattr(docker_runtime, "_node_host_command", host_command)
    monkeypatch.setattr(
        docker_runtime,
        "_local_full_flow_wait_clean_cluster_snapshot",
        lambda *_args, **_kwargs: None,
    )

    details = docker_runtime._local_full_flow_network_disconnect_probe(
        nodehost,
        nodes,
        "network_partition",
        backend=docker_runtime.DockerNodeBackend(),
    )

    docker_runtime._local_full_flow_validate_fault_probe_observation(
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
        "capability_id": "local_full_flow",
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
            capability_id=state["capability_id"],
            run_id=state["runtime"]["run_id"],
        )
