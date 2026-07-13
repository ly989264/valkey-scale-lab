from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from valkey_scale_lab import cli, milestone1_gate
from valkey_scale_lab.gates import (
    ExecutionContext,
    FaultTargetKind,
    GateRequest,
    GateService,
    GateStatus,
    OwnedFaultScope,
    StepStatus,
)
from valkey_scale_lab.gates.adapters import (
    AdapterCollisionError,
    AdapterOwnershipError,
    AdapterPathError,
    LegacyGateAdapter,
    LegacyRuntimeEntrypoints,
    build_legacy_adapter_bundle,
)
from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline
from valkey_scale_lab.scenarios import (
    ArtifactSpec,
    compile_gate_plan,
    load_milestone1_definition,
)
from valkey_scale_lab.scenarios.validation import LIFECYCLE_IDS


def _scope(run_id: str = "gate-run", ownership_id: str = "owner-1") -> OwnedFaultScope:
    return OwnedFaultScope(
        run_id=run_id,
        ownership_id=ownership_id,
        kind=FaultTargetKind.PROCESS,
        resource_ids=("owned-processes",),
    )


def _context(
    artifact_root: Path,
    *,
    run_id: str = "gate-run",
    ownership_id: str = "owner-1",
) -> ExecutionContext:
    definition = load_milestone1_definition()
    plan = compile_gate_plan(definition, 50)
    return ExecutionContext(
        run_id=run_id,
        ownership_id=ownership_id,
        provenance_id="provenance-1",
        requested_nodes=50,
        artifact_root=artifact_root,
        definition_id=plan.definition_id,
        definition_version=plan.definition_version,
        definition_digest=plan.definition_digest,
        plan_digest=plan.digest,
        fault_scope=_scope(run_id, ownership_id),
        runtime_phase=plan.runtime_phase,
        runtime_scenario=plan.runtime_scenario,
        config_template=plan.config_template,
        configuration={},
        metadata={},
    )


def _fake_entrypoints(calls: list[tuple[str, dict[str, Any]]]) -> LegacyRuntimeEntrypoints:
    def create(**kwargs: Any) -> dict[str, Any]:
        calls.append(("create", dict(kwargs)))
        state = {
            "phase_id": kwargs["phase"],
            "scenario": kwargs["scenario"],
            "runtime": {"run_id": "legacy-runtime-1"},
            "nodes": [{"logical_id": f"node-{index:03d}"} for index in range(50)],
        }
        Path(kwargs["state_out"]).write_text(
            json.dumps(state, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return state

    def cleanup(**kwargs: Any) -> dict[str, Any]:
        calls.append(("cleanup", dict(kwargs)))
        report = {
            "status": "PASS",
            "run_id": "legacy-runtime-1",
            "resources_remaining": [],
        }
        Path(kwargs["out_path"]).write_text(
            json.dumps(report, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report

    return LegacyRuntimeEntrypoints(create=create, cleanup=cleanup)


def test_service_delegates_once_with_legacy_arguments_and_confined_paths(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "gate-artifacts"
    calls: list[tuple[str, dict[str, Any]]] = []
    plan = compile_gate_plan(load_milestone1_definition(), 50)
    request = GateRequest(
        run_id="gate-run",
        ownership_id="owner-1",
        provenance_id="provenance-1",
        requested_nodes=50,
        artifact_root=artifact_root,
        fault_scope=_scope(),
    )

    result = GateService().execute(
        plan,
        request,
        build_legacy_adapter_bundle(_fake_entrypoints(calls)),
    )

    assert result.status is GateStatus.PASS
    assert [step.step_id for step in result.step_results] == list(LIFECYCLE_IDS)
    assert all(step.status is StepStatus.PASS for step in result.step_results)
    assert [name for name, _ in calls] == ["create", "cleanup"]

    create_args = calls[0][1]
    assert create_args["phase"] == plan.runtime_phase
    assert create_args["scenario"] == plan.runtime_scenario
    assert create_args["config_path"] == plan.config_template
    assert create_args["artifacts_dir"] == artifact_root.resolve() / "runtime"
    assert create_args["state_out"] == artifact_root.resolve() / "runtime" / "state.json"
    assert isinstance(create_args["setup_timeline"], SetupTimeline)
    assert set(create_args) == {
        "phase",
        "scenario",
        "config_path",
        "artifacts_dir",
        "state_out",
        "setup_timeline",
    }
    assert calls[1][1] == {
        "state_path": artifact_root.resolve() / "runtime" / "state.json",
        "artifacts_dir": artifact_root.resolve() / "runtime",
        "out_path": artifact_root.resolve() / "runtime" / "cleanup_report.json",
    }
    for step in result.step_results:
        assert step.details.get("admission_evidence") is False
        for path in step.artifact_paths:
            path.resolve().relative_to(artifact_root.resolve())


def test_adapter_rejects_owner_and_output_collisions_without_cleanup_takeover(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    adapter = LegacyGateAdapter(_fake_entrypoints(calls))
    owner = _context(tmp_path / "owned")
    other_owner = _context(
        tmp_path / "owned",
        ownership_id="owner-2",
    )
    adapter.resource_preflight(owner)

    with pytest.raises(AdapterCollisionError, match="another owner"):
        adapter.resource_preflight(other_owner)

    state_path = owner.artifact_root / "runtime" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "phase_id": owner.runtime_phase,
                "scenario": owner.runtime_scenario,
                "runtime": {"run_id": "unrelated-runtime"},
                "nodes": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AdapterCollisionError, match="already exists"):
        adapter.runtime_start(owner)

    cleanup = adapter.cleanup(owner)
    assert cleanup.status is StepStatus.PASS
    assert cleanup.details["cleanup_delegated"] is False
    assert calls == []


def test_adapter_rejects_cross_run_cleanup_and_escaping_artifact_paths(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    adapter = LegacyGateAdapter(_fake_entrypoints(calls))
    context = _context(tmp_path / "confined")
    adapter.resource_preflight(context)
    adapter.runtime_start(context)

    with pytest.raises(AdapterPathError, match="escapes artifact_root"):
        adapter.validate(
            context,
            (ArtifactSpec(raw_name="../escape.json", format="json"),),
        )

    state_path = context.artifact_root / "runtime" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["runtime"]["run_id"] = "cross-run-runtime"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(AdapterOwnershipError, match="run_id mismatch"):
        adapter.cleanup(context)
    assert [name for name, _ in calls] == ["create"]


def test_existing_cli_and_real_gate_facades_remain_bound_to_legacy_behavior() -> None:
    gate_args = cli.build_parser().parse_args(
        [
            "gate",
            "scenario",
            "--phase",
            "P03_LOCAL_DOCKER_VALKEY",
            "--scenario",
            "cluster_smoke",
            "--config",
            "templates/configs/single_mac_6node.yaml",
            "--artifacts-dir",
            "out",
            "--state-out",
            "out/state.json",
        ]
    )
    real_args = cli.build_parser().parse_args(
        ["milestone1", "real-gate", "--scale", "50", "--evidence-dir", "out"]
    )

    assert gate_args.func is cli._gate_scenario
    assert real_args.func is cli._milestone1_real_gate
    assert cli.create_scenario is docker_runtime.create_scenario
    assert cli.cleanup_scenario is docker_runtime.cleanup_scenario
    assert cli.run_real_gate is milestone1_gate.run_real_gate
