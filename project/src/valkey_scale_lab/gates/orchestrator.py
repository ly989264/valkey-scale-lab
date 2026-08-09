from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from valkey_scale_lab.observability.contracts import CollectionError
from valkey_scale_lab.scenarios import GatePlan
from valkey_scale_lab.scenarios.validation import LIFECYCLE_IDS

from .contracts import (
    AdapterBundle,
    ExecutionContext,
    FailureInfo,
    GateRequest,
    GateResult,
    GateStatus,
    StepResult,
    StepStatus,
)


class GateOrchestrationError(RuntimeError):
    pass


class GatePlanContractError(GateOrchestrationError):
    pass


class GateRequestContractError(GateOrchestrationError):
    pass


class GateOrchestrator:
    """Execute a compiled Gate plan and own the single cleanup boundary."""

    def execute(
        self,
        plan: GatePlan,
        request: GateRequest,
        adapters: AdapterBundle,
    ) -> GateResult:
        context = self._context(plan, request)
        steps: List[StepResult] = []
        primary_failure: Optional[FailureInfo] = None
        cleanup_failure: Optional[FailureInfo] = None
        cleanup_result: Optional[StepResult] = None

        try:
            contract_failure = self._contract_failure(plan, request)
            if contract_failure is not None:
                primary_failure = contract_failure
                steps.extend(
                    self._skipped_results(
                        context,
                        tuple(LIFECYCLE_IDS[:-1]),
                        contract_failure.reason,
                    )
                )
            else:
                request_failure = self._execution_permission_failure(plan, request)
                if request_failure is not None:
                    primary_failure = request_failure
                    steps.extend(
                        self._skipped_results(
                            context,
                            tuple(LIFECYCLE_IDS[:-1]),
                            request_failure.reason,
                        )
                    )
                else:
                    for index, step in enumerate(plan.lifecycle_steps[:-1]):
                        try:
                            result = self._execute_step(step.id, context, plan, adapters)
                            self._validate_step_result(step.id, context, result)
                        except Exception as exc:
                            primary_failure = self._exception_failure(step.id, exc)
                            result = StepResult.failed(
                                context,
                                step.id,
                                primary_failure.reason,
                                details={"error_code": primary_failure.code},
                            )
                        steps.append(result)
                        if result.status is not StepStatus.PASS:
                            if primary_failure is None:
                                failure_code = (
                                    "PREFLIGHT_BLOCKED"
                                    if step.id == "resource_preflight"
                                    and result.status is StepStatus.BLOCKED
                                    else "STEP_NOT_PASS"
                                )
                                primary_failure = FailureInfo(
                                    code=failure_code,
                                    reason=result.reason or "step did not pass",
                                    step_id=step.id,
                                )
                            remaining = tuple(
                                item.id for item in plan.lifecycle_steps[index + 1 : -1]
                            )
                            steps.extend(
                                self._skipped_results(
                                    context,
                                    remaining,
                                    f"fail-fast after {step.id}: {primary_failure.reason}",
                                )
                            )
                            break
        finally:
            try:
                cleanup_result = adapters.runtime.cleanup(context)
                self._validate_step_result("cleanup", context, cleanup_result)
                if cleanup_result.status is not StepStatus.PASS:
                    cleanup_failure = FailureInfo(
                        code="CLEANUP_NOT_PASS",
                        reason=cleanup_result.reason or "cleanup did not pass",
                        step_id="cleanup",
                    )
            except Exception as exc:
                cleanup_failure = self._exception_failure("cleanup", exc, cleanup=True)
                cleanup_result = StepResult.failed(
                    context,
                    "cleanup",
                    cleanup_failure.reason,
                    details={"error_code": cleanup_failure.code},
                )

        if cleanup_result is None:  # pragma: no cover - protected by finally
            raise AssertionError("cleanup boundary did not produce a result")
        if primary_failure is None and cleanup_failure is None:
            status = GateStatus.PASS
        elif primary_failure is not None and primary_failure.code in {
            "PREFLIGHT_BLOCKED",
            "REQUEST_OPERATOR_OPT_IN_REQUIRED",
            "REQUEST_COST_ACKNOWLEDGEMENT_REQUIRED",
        }:
            status = GateStatus.BLOCKED if cleanup_failure is None else GateStatus.FAIL
        else:
            status = GateStatus.FAIL
        return GateResult(
            status=status,
            run_id=context.run_id,
            ownership_id=context.ownership_id,
            provenance_id=context.provenance_id,
            requested_nodes=context.requested_nodes,
            definition_id=context.definition_id,
            definition_version=context.definition_version,
            definition_digest=context.definition_digest,
            plan_digest=context.plan_digest,
            steps=tuple(steps),
            cleanup_result=cleanup_result,
            primary_failure=primary_failure,
            cleanup_failure=cleanup_failure,
        )

    def _execute_step(
        self,
        step_id: str,
        context: ExecutionContext,
        plan: GatePlan,
        adapters: AdapterBundle,
    ) -> StepResult:
        runtime_dispatch: Dict[str, Callable[[ExecutionContext], StepResult]] = {
            "resource_preflight": adapters.runtime.resource_preflight,
            "runtime_start": adapters.runtime.runtime_start,
            "cluster_form": adapters.runtime.cluster_form,
            "stabilize": adapters.runtime.stabilize,
            "recovery": adapters.runtime.recovery,
        }
        if step_id in runtime_dispatch:
            return runtime_dispatch[step_id](context)
        if step_id == "baseline_workload":
            return adapters.workload.run_baseline(context)
        if step_id == "management_matrix":
            return adapters.management.run_matrix(
                context,
                plan.management_scenarios,
                plan.management_execution_order,
            )
        if step_id == "fault_matrix":
            if context.fault_scope.host_networking_allowed:
                raise GateRequestContractError("host networking faults are forbidden")
            return adapters.fault.run_matrix(
                context,
                plan.fault_scenarios,
                context.fault_scope,
            )
        if step_id == "artifact_validation":
            return adapters.artifact_validation.validate(context, plan.artifacts)
        if step_id == "analysis":
            return adapters.analysis.analyze(context)
        if step_id == "report":
            return adapters.report.render(context, plan.report_surfaces)
        raise GatePlanContractError(f"unknown lifecycle step {step_id}")

    @staticmethod
    def _validate_plan(plan: GatePlan) -> None:
        lifecycle_ids = tuple(step.id for step in plan.lifecycle_steps)
        if lifecycle_ids != tuple(LIFECYCLE_IDS):
            raise GatePlanContractError("Gate plan lifecycle is not canonical")
        cleanup = plan.lifecycle_steps[-1]
        if not cleanup.always_run or not cleanup.terminal:
            raise GatePlanContractError("cleanup must be the always-run terminal step")
        if lifecycle_ids.index("artifact_validation") > lifecycle_ids.index("analysis"):
            raise GatePlanContractError("artifact validation must precede analysis")
        if lifecycle_ids.index("analysis") > lifecycle_ids.index("report"):
            raise GatePlanContractError("analysis must precede report")
        if not plan.exact or plan.downscale_allowed:
            raise GatePlanContractError("Gate plan must preserve exact requested nodes")

    @staticmethod
    def _validate_request(plan: GatePlan, request: GateRequest) -> None:
        if request.requested_nodes != plan.requested_nodes:
            raise GateRequestContractError(
                "request requested_nodes must exactly match the compiled plan"
            )
        if (
            request.profile_id is not None
            and plan.profile_id is not None
            and request.profile_id != plan.profile_id
        ):
            raise GateRequestContractError(
                "request profile_id must match the exact scale selected by the plan"
            )

    @staticmethod
    def _execution_permission_failure(
        plan: GatePlan, request: GateRequest
    ) -> Optional[FailureInfo]:
        if plan.requires_operator_opt_in and not request.operator_opt_in:
            return FailureInfo(
                code="REQUEST_OPERATOR_OPT_IN_REQUIRED",
                reason="explicit operator opt-in is required for this Gate plan",
                step_id=None,
            )
        if plan.requires_cost_acknowledgement and not request.cost_acknowledged:
            return FailureInfo(
                code="REQUEST_COST_ACKNOWLEDGEMENT_REQUIRED",
                reason="explicit cost acknowledgement is required for this Gate plan",
                step_id=None,
            )
        return None

    def _contract_failure(
        self, plan: GatePlan, request: GateRequest
    ) -> Optional[FailureInfo]:
        try:
            self._validate_plan(plan)
            self._validate_request(plan, request)
        except GatePlanContractError as exc:
            return FailureInfo(
                code="PLAN_CONTRACT",
                reason=str(exc),
                step_id=None,
                exception_type=exc.__class__.__name__,
            )
        except GateRequestContractError as exc:
            return FailureInfo(
                code="REQUEST_CONTRACT",
                reason=str(exc),
                step_id=None,
                exception_type=exc.__class__.__name__,
            )
        return None

    @staticmethod
    def _context(plan: GatePlan, request: GateRequest) -> ExecutionContext:
        return ExecutionContext(
            run_id=request.run_id,
            ownership_id=request.ownership_id,
            provenance_id=request.provenance_id,
            requested_nodes=request.requested_nodes,
            artifact_root=request.artifact_root,
            definition_id=plan.definition_id,
            definition_version=plan.definition_version,
            definition_digest=plan.definition_digest,
            plan_digest=plan.digest,
            fault_scope=request.fault_scope,
            backend_id=request.backend_id,
            profile_id=request.profile_id or plan.profile_id or f"exact-{request.requested_nodes}",
            config_template=plan.config_template,
            configuration=request.configuration,
            metadata=request.metadata,
            operator_opt_in=request.operator_opt_in,
            cost_acknowledged=request.cost_acknowledged,
        )

    @staticmethod
    def _validate_step_result(
        expected_step_id: str,
        context: ExecutionContext,
        result: StepResult,
    ) -> None:
        if not isinstance(result, StepResult):
            raise TypeError("adapter must return StepResult")
        if result.step_id != expected_step_id:
            raise ValueError(
                f"adapter returned step_id {result.step_id!r}, expected {expected_step_id!r}"
            )
        if result.run_id != context.run_id:
            raise ValueError("adapter returned a cross-run result")
        if result.ownership_id != context.ownership_id:
            raise ValueError("adapter returned a cross-owner result")
        if result.provenance_id != context.provenance_id:
            raise ValueError("adapter returned cross-provenance result")
        artifact_root = context.artifact_root.resolve()
        for artifact_path in result.artifact_paths:
            candidate = (
                artifact_path
                if artifact_path.is_absolute()
                else artifact_root / artifact_path
            ).resolve()
            try:
                candidate.relative_to(artifact_root)
            except ValueError as exc:
                raise ValueError(
                    f"adapter returned an artifact outside owned artifact_root: "
                    f"{artifact_path}"
                ) from exc

    @staticmethod
    def _skipped_results(
        context: ExecutionContext,
        step_ids: Tuple[str, ...],
        reason: str,
    ) -> Tuple[StepResult, ...]:
        return tuple(
            StepResult(
                step_id=step_id,
                status=StepStatus.SKIPPED_WITH_REASON,
                run_id=context.run_id,
                ownership_id=context.ownership_id,
                provenance_id=context.provenance_id,
                reason=reason,
            )
            for step_id in step_ids
        )

    @staticmethod
    def _exception_failure(
        step_id: str, exc: Exception, *, cleanup: bool = False
    ) -> FailureInfo:
        prefix = "CLEANUP" if cleanup else "STEP"
        reason = str(exc).strip() or exc.__class__.__name__
        # §12.1 splits a step's failure two ways: the collector could not
        # complete, or it completed and observed something wrong. The exception
        # class is where that distinction is stated, and this is the only place
        # in the lifecycle that still holds the exception, so the code records
        # which kind it was rather than leaving callers to match on a name.
        kind = "TOOL_ERROR" if isinstance(exc, CollectionError) else "EXCEPTION"
        return FailureInfo(
            code=f"{prefix}_{kind}",
            reason=reason,
            step_id=step_id,
            exception_type=exc.__class__.__name__,
        )
