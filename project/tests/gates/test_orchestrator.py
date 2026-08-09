from __future__ import annotations

import dataclasses
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, List, Mapping, Optional, Tuple

import pytest

from valkey_scale_lab.observability.contracts import CollectionError
from valkey_scale_lab.gates import (
    AdapterBundle,
    FaultTargetKind,
    GateOrchestrator,
    GateRequest,
    GateService,
    GateStatus,
    OwnedFaultScope,
    OwnershipCollisionError,
    StepResult,
    StepStatus,
)
from valkey_scale_lab.scenarios import (
    ArtifactSpec,
    ReportSurface,
    ScenarioSpec,
    compile_gate_plan,
    load_local_full_flow_definition,
)


class RecordingAdapters:
    def __init__(
        self,
        *,
        fail_step: Optional[str] = None,
        raise_step: Optional[str] = None,
        cleanup_raises: bool = False,
    ) -> None:
        self.calls: List[str] = []
        self.fail_step = fail_step
        self.raise_step = raise_step
        self.step_exception: Optional[Exception] = None
        self.cleanup_raises = cleanup_raises
        self.cleanup_count = 0
        self.management_payload: Optional[
            Tuple[Tuple[ScenarioSpec, ...], Tuple[str, ...]]
        ] = None
        self.fault_payload: Optional[
            Tuple[Tuple[ScenarioSpec, ...], OwnedFaultScope]
        ] = None
        self.artifact_payload: Optional[Tuple[ArtifactSpec, ...]] = None
        self.report_payload: Optional[Tuple[ReportSurface, ...]] = None

    @property
    def bundle(self) -> AdapterBundle:
        return AdapterBundle(
            runtime=self,
            workload=self,
            management=self,
            fault=self,
            artifact_validation=self,
            analysis=self,
            report=self,
        )

    def _run(self, context, step_id: str) -> StepResult:
        self.calls.append(step_id)
        if self.raise_step == step_id:
            raise self.step_exception or RuntimeError(f"{step_id} exploded")
        if self.fail_step == step_id:
            return StepResult.failed(context, step_id, f"{step_id} rejected")
        return StepResult.passed(context, step_id)

    def resource_preflight(self, context) -> StepResult:
        return self._run(context, "resource_preflight")

    def runtime_start(self, context) -> StepResult:
        return self._run(context, "runtime_start")

    def cluster_form(self, context) -> StepResult:
        return self._run(context, "cluster_form")

    def stabilize(self, context) -> StepResult:
        return self._run(context, "stabilize")

    def recovery(self, context) -> StepResult:
        return self._run(context, "recovery")

    def cleanup(self, context) -> StepResult:
        self.calls.append("cleanup")
        self.cleanup_count += 1
        if self.cleanup_raises:
            raise RuntimeError("cleanup exploded")
        if self.fail_step == "cleanup":
            return StepResult.failed(context, "cleanup", "owned resources remain")
        return StepResult.passed(context, "cleanup")

    def run_baseline(self, context) -> StepResult:
        return self._run(context, "baseline_workload")

    def run_matrix(self, context, scenarios, third) -> StepResult:
        if scenarios and scenarios[0].id == "add_remove_node":
            self.management_payload = (scenarios, third)
            return self._run(context, "management_matrix")
        self.fault_payload = (scenarios, third)
        return self._run(context, "fault_matrix")

    def validate(self, context, artifacts) -> StepResult:
        self.artifact_payload = artifacts
        return self._run(context, "artifact_validation")

    def analyze(self, context) -> StepResult:
        return self._run(context, "analysis")

    def render(self, context, surfaces) -> StepResult:
        self.report_payload = surfaces
        return self._run(context, "report")


def _plan(nodes: int = 50):
    return compile_gate_plan(load_local_full_flow_definition(), nodes)


def _request(tmp_path: Path, nodes: int = 50, **overrides: Any) -> GateRequest:
    values: Mapping[str, Any] = {
        "run_id": "run-001",
        "ownership_id": "owner-001",
        "provenance_id": "capture-001",
        "requested_nodes": nodes,
        "artifact_root": tmp_path / "artifacts",
        "fault_scope": OwnedFaultScope(
            run_id="run-001",
            ownership_id="owner-001",
            kind=FaultTargetKind.CONTAINER,
            resource_ids=("valkey-node-001",),
        ),
    }
    return GateRequest(**{**values, **overrides})


def test_executes_canonical_order_with_typed_adapter_dispatch(tmp_path: Path) -> None:
    plan = _plan()
    adapters = RecordingAdapters()

    result = GateOrchestrator().execute(plan, _request(tmp_path), adapters.bundle)

    assert result.status is GateStatus.PASS
    assert adapters.calls == [step.id for step in plan.lifecycle_steps]
    assert tuple(step.step_id for step in result.step_results) == tuple(adapters.calls)
    assert adapters.cleanup_count == 1
    assert adapters.management_payload == (
        plan.management_scenarios,
        plan.management_execution_order,
    )
    assert adapters.fault_payload == (plan.fault_scenarios, _request(tmp_path).fault_scope)
    assert adapters.artifact_payload == plan.artifacts
    assert adapters.report_payload == plan.report_surfaces
    assert result.run_id == "run-001"
    assert result.ownership_id == "owner-001"
    assert result.provenance_id == "capture-001"
    assert result.plan_digest == plan.digest


def test_preflight_failure_fails_fast_and_cleans_once(tmp_path: Path) -> None:
    adapters = RecordingAdapters(fail_step="resource_preflight")

    result = GateOrchestrator().execute(_plan(200), _request(tmp_path, 200), adapters.bundle)

    assert result.status is GateStatus.FAIL
    assert adapters.calls == ["resource_preflight", "cleanup"]
    assert adapters.cleanup_count == 1
    assert result.steps[0].status is StepStatus.FAIL
    assert all(
        step.status is StepStatus.SKIPPED_WITH_REASON for step in result.steps[1:]
    )
    assert all(step.reason for step in result.steps)
    assert result.primary_failure is not None
    assert result.primary_failure.step_id == "resource_preflight"
    assert result.cleanup_result.status is StepStatus.PASS


def test_blocked_resource_preflight_blocks_real_gate(tmp_path: Path) -> None:
    adapters = RecordingAdapters()

    def blocked(context) -> StepResult:
        adapters.calls.append("resource_preflight")
        return StepResult(
            step_id="resource_preflight",
            status=StepStatus.BLOCKED,
            run_id=context.run_id,
            ownership_id=context.ownership_id,
            provenance_id=context.provenance_id,
            reason="insufficient resources for exact 200-node run",
        )

    adapters.resource_preflight = blocked  # type: ignore[method-assign]
    result = GateOrchestrator().execute(
        _plan(200),
        _request(tmp_path, 200),
        adapters.bundle,
    )

    assert result.status is GateStatus.BLOCKED
    assert result.primary_failure is not None
    assert result.primary_failure.code == "PREFLIGHT_BLOCKED"
    assert adapters.calls == ["resource_preflight", "cleanup"]
    assert adapters.cleanup_count == 1


def test_step_exception_preserves_primary_failure_and_cleanup(tmp_path: Path) -> None:
    adapters = RecordingAdapters(raise_step="management_matrix")

    result = GateOrchestrator().execute(_plan(), _request(tmp_path), adapters.bundle)

    assert result.status is GateStatus.FAIL
    assert adapters.calls[-1] == "cleanup"
    assert adapters.cleanup_count == 1
    assert result.primary_failure is not None
    assert result.primary_failure.code == "STEP_EXCEPTION"
    assert result.primary_failure.exception_type == "RuntimeError"
    assert result.cleanup_failure is None


def test_a_collection_error_is_recorded_as_a_tool_error_not_a_step_exception(
    tmp_path: Path,
) -> None:
    """§12.1's first boundary: the collector could not complete the observation.

    A `RuntimeError` from a step means the step observed something wrong; a
    `CollectionError` means it never got to observe. Both still fail the gate -
    §12.2 keeps FAIL ahead of ERROR - but the run has to be able to say which,
    and this code is the only place downstream can learn it.
    """

    adapters = RecordingAdapters(raise_step="management_matrix")
    adapters.step_exception = CollectionError("resource sampler produced no evidence")

    result = GateOrchestrator().execute(_plan(), _request(tmp_path), adapters.bundle)

    assert result.status is GateStatus.FAIL
    assert result.primary_failure is not None
    assert result.primary_failure.code == "STEP_TOOL_ERROR"
    assert result.primary_failure.exception_type == "CollectionError"
    assert adapters.cleanup_count == 1


def test_cleanup_failure_alone_prevents_pass(tmp_path: Path) -> None:
    adapters = RecordingAdapters(fail_step="cleanup")

    result = GateOrchestrator().execute(_plan(), _request(tmp_path), adapters.bundle)

    assert result.status is GateStatus.FAIL
    assert result.primary_failure is None
    assert result.cleanup_failure is not None
    assert result.cleanup_failure.code == "CLEANUP_NOT_PASS"
    assert adapters.cleanup_count == 1


def test_dual_exceptions_preserve_primary_and_cleanup_outcome(tmp_path: Path) -> None:
    adapters = RecordingAdapters(
        raise_step="fault_matrix",
        cleanup_raises=True,
    )

    result = GateOrchestrator().execute(_plan(), _request(tmp_path), adapters.bundle)

    assert result.status is GateStatus.FAIL
    assert result.primary_failure is not None
    assert result.primary_failure.reason == "fault_matrix exploded"
    assert result.cleanup_failure is not None
    assert result.cleanup_failure.reason == "cleanup exploded"
    assert result.cleanup_result.status is StepStatus.FAIL
    assert adapters.cleanup_count == 1


def test_above_200_permissions_block_before_runtime_but_still_cleanup(
    tmp_path: Path,
) -> None:
    adapters = RecordingAdapters()

    result = GateOrchestrator().execute(
        _plan(201),
        _request(tmp_path, 201),
        adapters.bundle,
    )

    assert result.status is GateStatus.BLOCKED
    assert adapters.calls == ["cleanup"]
    assert adapters.cleanup_count == 1
    assert all(step.status is StepStatus.SKIPPED_WITH_REASON for step in result.steps)
    assert result.primary_failure is not None
    assert result.primary_failure.code == "REQUEST_OPERATOR_OPT_IN_REQUIRED"


def test_exact_2000_permissions_block_before_runtime_but_still_cleanup(
    tmp_path: Path,
) -> None:
    adapters = RecordingAdapters()

    result = GateOrchestrator().execute(
        _plan(2000),
        _request(tmp_path, 2000, profile_id="exact-2000"),
        adapters.bundle,
    )

    assert result.status is GateStatus.BLOCKED
    assert adapters.calls == ["cleanup"]
    assert adapters.cleanup_count == 1
    assert result.primary_failure is not None
    assert result.primary_failure.code == "REQUEST_OPERATOR_OPT_IN_REQUIRED"


def test_cost_acknowledgement_is_independently_required(tmp_path: Path) -> None:
    adapters = RecordingAdapters()
    result = GateOrchestrator().execute(
        _plan(201),
        _request(tmp_path, 201, operator_opt_in=True),
        adapters.bundle,
    )
    assert result.status is GateStatus.BLOCKED
    assert result.primary_failure is not None
    assert result.primary_failure.code == "REQUEST_COST_ACKNOWLEDGEMENT_REQUIRED"
    assert adapters.calls == ["cleanup"]


def test_cross_run_adapter_result_is_a_primary_failure(tmp_path: Path) -> None:
    adapters = RecordingAdapters()

    def wrong_result(context) -> StepResult:
        adapters.calls.append("cluster_form")
        return dataclasses.replace(
            StepResult.passed(context, "cluster_form"),
            run_id="another-run",
        )

    adapters.cluster_form = wrong_result  # type: ignore[method-assign]
    result = GateOrchestrator().execute(_plan(), _request(tmp_path), adapters.bundle)

    assert result.status is GateStatus.FAIL
    assert result.primary_failure is not None
    assert result.primary_failure.reason == "adapter returned a cross-run result"
    assert adapters.calls == [
        "resource_preflight",
        "runtime_start",
        "cluster_form",
        "cleanup",
    ]


def test_adapter_cannot_report_artifacts_outside_owned_root(tmp_path: Path) -> None:
    adapters = RecordingAdapters()

    def escaping_result(context) -> StepResult:
        adapters.calls.append("runtime_start")
        return StepResult.passed(
            context,
            "runtime_start",
            artifact_paths=(tmp_path.parent / "foreign.json",),
        )

    adapters.runtime_start = escaping_result  # type: ignore[method-assign]
    result = GateOrchestrator().execute(_plan(), _request(tmp_path), adapters.bundle)

    assert result.status is GateStatus.FAIL
    assert result.primary_failure is not None
    assert "outside owned artifact_root" in result.primary_failure.reason
    assert adapters.calls == ["resource_preflight", "runtime_start", "cleanup"]
    assert adapters.cleanup_count == 1


def test_mismatched_exact_request_is_reported_and_cleaned_once(tmp_path: Path) -> None:
    adapters = RecordingAdapters()

    result = GateOrchestrator().execute(
        _plan(50),
        _request(tmp_path, 51),
        adapters.bundle,
    )

    assert result.status is GateStatus.FAIL
    assert result.primary_failure is not None
    assert result.primary_failure.code == "REQUEST_CONTRACT"
    assert adapters.calls == ["cleanup"]
    assert adapters.cleanup_count == 1


def test_reordered_plan_is_rejected_before_dispatch_and_cleaned_once(
    tmp_path: Path,
) -> None:
    adapters = RecordingAdapters()
    plan = _plan()
    reordered = dataclasses.replace(
        plan,
        lifecycle_steps=tuple(reversed(plan.lifecycle_steps)),
    )

    result = GateOrchestrator().execute(
        reordered,
        _request(tmp_path),
        adapters.bundle,
    )

    assert result.status is GateStatus.FAIL
    assert result.primary_failure is not None
    assert result.primary_failure.code == "PLAN_CONTRACT"
    assert adapters.calls == ["cleanup"]
    assert adapters.cleanup_count == 1


def test_contracts_are_deeply_immutable_and_fault_scope_is_owned(
    tmp_path: Path,
) -> None:
    request = _request(
        tmp_path,
        configuration={"nested": {"nodes": [1, 2]}},
    )
    result = StepResult(
        step_id="sample",
        status=StepStatus.PASS,
        run_id=request.run_id,
        ownership_id=request.ownership_id,
        provenance_id=request.provenance_id,
        details={"nested": [1, 2]},
    )

    with pytest.raises(FrozenInstanceError):
        request.requested_nodes = 49  # type: ignore[misc]
    with pytest.raises(TypeError):
        request.configuration["new"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        request.configuration["nested"]["nodes"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        result.details["nested"] = ()  # type: ignore[index]
    assert request.fault_scope.host_networking_allowed is False

    with pytest.raises(ValueError, match="project-owned"):
        dataclasses.replace(request.fault_scope, project_owned=False)
    with pytest.raises(ValueError, match="collision-free"):
        dataclasses.replace(
            request.fault_scope,
            resource_ids=("same", "same"),
        )
    with pytest.raises(ValueError, match="must match"):
        dataclasses.replace(request, ownership_id="other-owner")


def test_gate_service_rejects_concurrent_ownership_collisions(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingOrchestrator:
        def execute(self, plan, request, adapters):
            entered.set()
            assert release.wait(2)
            return "done"

    service = GateService(orchestrator=BlockingOrchestrator())  # type: ignore[arg-type]
    adapters = RecordingAdapters()
    request = _request(tmp_path)
    results: List[str] = []
    thread = threading.Thread(
        target=lambda: results.append(
            service.execute(_plan(), request, adapters.bundle)  # type: ignore[arg-type]
        )
    )
    thread.start()
    assert entered.wait(2)

    with pytest.raises(OwnershipCollisionError, match="already active"):
        service.execute(_plan(), request, adapters.bundle)

    same_run = _request(
        tmp_path,
        ownership_id="owner-002",
        fault_scope=OwnedFaultScope(
            run_id="run-001",
            ownership_id="owner-002",
            kind=FaultTargetKind.CONTAINER,
            resource_ids=("valkey-node-002",),
        ),
    )
    with pytest.raises(OwnershipCollisionError, match="run_id .* already active"):
        service.execute(_plan(), same_run, adapters.bundle)

    same_root = _request(
        tmp_path,
        run_id="run-002",
        ownership_id="owner-003",
        fault_scope=OwnedFaultScope(
            run_id="run-002",
            ownership_id="owner-003",
            kind=FaultTargetKind.CONTAINER,
            resource_ids=("valkey-node-003",),
        ),
    )
    with pytest.raises(OwnershipCollisionError, match="artifact_root .* already active"):
        service.execute(_plan(), same_root, adapters.bundle)

    release.set()
    thread.join(timeout=2)
    assert results == ["done"]

    assert service.execute(_plan(), request, adapters.bundle) == "done"  # type: ignore[comparison-overlap]


def test_gate_service_registry_rejects_cross_instance_run_and_root_collisions(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingOrchestrator:
        def execute(self, plan, request, adapters):
            entered.set()
            assert release.wait(2)
            return "first"

    class ImmediateOrchestrator:
        def execute(self, plan, request, adapters):
            return "second"

    first = GateService(orchestrator=BlockingOrchestrator())  # type: ignore[arg-type]
    second = GateService(orchestrator=ImmediateOrchestrator())  # type: ignore[arg-type]
    adapters = RecordingAdapters()
    request = _request(tmp_path)
    thread = threading.Thread(
        target=lambda: first.execute(_plan(), request, adapters.bundle)
    )
    thread.start()
    assert entered.wait(2)

    same_run = _request(
        tmp_path,
        ownership_id="owner-002",
        artifact_root=tmp_path / "another-artifact-root",
        fault_scope=OwnedFaultScope(
            run_id="run-001",
            ownership_id="owner-002",
            kind=FaultTargetKind.CONTAINER,
            resource_ids=("valkey-node-002",),
        ),
    )
    with pytest.raises(OwnershipCollisionError, match="run_id .* already active"):
        second.execute(_plan(), same_run, adapters.bundle)

    same_root = _request(
        tmp_path,
        run_id="run-002",
        ownership_id="owner-003",
        fault_scope=OwnedFaultScope(
            run_id="run-002",
            ownership_id="owner-003",
            kind=FaultTargetKind.CONTAINER,
            resource_ids=("valkey-node-003",),
        ),
    )
    with pytest.raises(OwnershipCollisionError, match="artifact_root .* already active"):
        second.execute(_plan(), same_root, adapters.bundle)

    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_gate_service_releases_global_claim_after_orchestrator_error(
    tmp_path: Path,
) -> None:
    class RaisingOrchestrator:
        def execute(self, plan, request, adapters):
            raise RuntimeError("execution failed outside the result boundary")

    class ImmediateOrchestrator:
        def execute(self, plan, request, adapters):
            return "reused"

    request = _request(tmp_path)
    adapters = RecordingAdapters()
    failing = GateService(orchestrator=RaisingOrchestrator())  # type: ignore[arg-type]
    succeeding = GateService(orchestrator=ImmediateOrchestrator())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="outside the result boundary"):
        failing.execute(_plan(), request, adapters.bundle)

    assert succeeding.execute(_plan(), request, adapters.bundle) == "reused"  # type: ignore[comparison-overlap]


def test_fault_resource_claims_reject_partial_overlap_atomically_across_services(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingOrchestrator:
        def execute(self, plan, request, adapters):
            entered.set()
            assert release.wait(2)
            return "first"

    class ImmediateOrchestrator:
        def execute(self, plan, request, adapters):
            return "immediate"

    first_request = _request(
        tmp_path / "first",
        fault_scope=OwnedFaultScope(
            run_id="run-001",
            ownership_id="owner-001",
            kind=FaultTargetKind.CONTAINER,
            resource_ids=("resource-alpha", "resource-shared"),
        ),
    )
    overlapping_request = _request(
        tmp_path / "overlap",
        run_id="run-002",
        ownership_id="owner-002",
        provenance_id="capture-002",
        fault_scope=OwnedFaultScope(
            run_id="run-002",
            ownership_id="owner-002",
            kind=FaultTargetKind.CONTAINER,
            resource_ids=("resource-shared", "resource-beta"),
        ),
    )
    beta_only_request = _request(
        tmp_path / "beta-only",
        run_id="run-003",
        ownership_id="owner-003",
        provenance_id="capture-003",
        fault_scope=OwnedFaultScope(
            run_id="run-003",
            ownership_id="owner-003",
            kind=FaultTargetKind.CONTAINER,
            resource_ids=("resource-beta",),
        ),
    )
    adapters = RecordingAdapters()
    first = GateService(orchestrator=BlockingOrchestrator())  # type: ignore[arg-type]
    immediate = GateService(orchestrator=ImmediateOrchestrator())  # type: ignore[arg-type]
    thread = threading.Thread(
        target=lambda: first.execute(_plan(), first_request, adapters.bundle)
    )
    thread.start()
    assert entered.wait(2)

    try:
        with pytest.raises(OwnershipCollisionError, match="resource-shared"):
            immediate.execute(_plan(), overlapping_request, adapters.bundle)
        assert (
            immediate.execute(_plan(), beta_only_request, adapters.bundle)
            == "immediate"
        )
    finally:
        release.set()
        thread.join(timeout=2)

    assert not thread.is_alive()


def test_fault_resource_claims_are_global_across_kinds_and_released_after_error(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingOrchestrator:
        def execute(self, plan, request, adapters):
            entered.set()
            assert release.wait(2)
            return "first"

    class RaisingOrchestrator:
        def execute(self, plan, request, adapters):
            raise RuntimeError("fault execution failed")

    class ImmediateOrchestrator:
        def execute(self, plan, request, adapters):
            return "reused"

    container_request = _request(
        tmp_path / "container",
        fault_scope=OwnedFaultScope(
            run_id="run-001",
            ownership_id="owner-001",
            kind=FaultTargetKind.CONTAINER,
            resource_ids=("global-resource",),
        ),
    )
    process_request = _request(
        tmp_path / "process",
        run_id="run-002",
        ownership_id="owner-002",
        provenance_id="capture-002",
        fault_scope=OwnedFaultScope(
            run_id="run-002",
            ownership_id="owner-002",
            kind=FaultTargetKind.PROCESS,
            resource_ids=("global-resource",),
        ),
    )
    adapters = RecordingAdapters()
    blocking = GateService(orchestrator=BlockingOrchestrator())  # type: ignore[arg-type]
    raising = GateService(orchestrator=RaisingOrchestrator())  # type: ignore[arg-type]
    immediate = GateService(orchestrator=ImmediateOrchestrator())  # type: ignore[arg-type]
    thread = threading.Thread(
        target=lambda: blocking.execute(_plan(), container_request, adapters.bundle)
    )
    thread.start()
    assert entered.wait(2)

    try:
        with pytest.raises(OwnershipCollisionError, match="global-resource"):
            immediate.execute(_plan(), process_request, adapters.bundle)
    finally:
        release.set()
        thread.join(timeout=2)

    with pytest.raises(RuntimeError, match="fault execution failed"):
        raising.execute(_plan(), process_request, adapters.bundle)
    assert immediate.execute(_plan(), process_request, adapters.bundle) == "reused"
