from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Protocol, Tuple, runtime_checkable

from valkey_scale_lab.scenarios import ArtifactSpec, ReportSurface, ScenarioSpec
from valkey_scale_lab.scenarios.contracts import freeze_json


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class StepStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    SKIPPED_WITH_REASON = "SKIPPED_WITH_REASON"
    UNSUPPORTED_WITH_REASON = "UNSUPPORTED_WITH_REASON"


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


class FaultTargetKind(str, Enum):
    CONTAINER = "container"
    NAMESPACE = "namespace"
    PROCESS = "process"
    SANDBOX_PROXY = "sandbox_proxy"


@dataclass(frozen=True)
class OwnedFaultScope:
    run_id: str
    ownership_id: str
    kind: FaultTargetKind
    resource_ids: Tuple[str, ...]
    project_owned: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.resource_ids, (str, bytes)):
            raise TypeError("fault scope resource_ids must be a sequence of identifiers")
        object.__setattr__(self, "resource_ids", tuple(self.resource_ids))
        _require_identifier("fault scope run_id", self.run_id)
        _require_identifier("fault scope ownership_id", self.ownership_id)
        if not isinstance(self.kind, FaultTargetKind):
            raise TypeError("fault scope kind must be a FaultTargetKind")
        if not self.project_owned:
            raise ValueError("fault scope must be project-owned")
        if not self.resource_ids:
            raise ValueError("fault scope must name at least one owned resource")
        if len(set(self.resource_ids)) != len(self.resource_ids):
            raise ValueError("fault scope resource_ids must be collision-free")
        for resource_id in self.resource_ids:
            _require_identifier("fault scope resource_id", resource_id)

    @property
    def host_networking_allowed(self) -> bool:
        return False


@dataclass(frozen=True)
class GateRequest:
    run_id: str
    ownership_id: str
    provenance_id: str
    requested_nodes: int
    artifact_root: Path
    fault_scope: OwnedFaultScope
    backend_id: str = "docker_process"
    profile_id: Optional[str] = None
    operator_opt_in: bool = False
    cost_acknowledged: bool = False
    configuration: Mapping[str, Any] = dataclasses.field(
        default_factory=lambda: MappingProxyType({})
    )
    metadata: Mapping[str, Any] = dataclasses.field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        _require_identifier("run_id", self.run_id)
        _require_identifier("ownership_id", self.ownership_id)
        _require_identifier("provenance_id", self.provenance_id)
        if isinstance(self.requested_nodes, bool) or not isinstance(
            self.requested_nodes, int
        ):
            raise TypeError("requested_nodes must be an integer")
        if self.requested_nodes <= 0:
            raise ValueError("requested_nodes must be positive")
        if not isinstance(self.artifact_root, Path):
            raise TypeError("artifact_root must be a pathlib.Path")
        if self.fault_scope.run_id != self.run_id:
            raise ValueError("fault scope run_id must match request run_id")
        if self.fault_scope.ownership_id != self.ownership_id:
            raise ValueError("fault scope ownership_id must match request ownership_id")
        _require_identifier("backend_id", self.backend_id)
        if self.profile_id is not None:
            _require_identifier("profile_id", self.profile_id)
        if not isinstance(self.operator_opt_in, bool):
            raise TypeError("operator_opt_in must be a boolean")
        if not isinstance(self.cost_acknowledged, bool):
            raise TypeError("cost_acknowledged must be a boolean")
        if not isinstance(self.configuration, Mapping):
            raise TypeError("configuration must be a mapping")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        object.__setattr__(self, "configuration", freeze_json(self.configuration))
        object.__setattr__(self, "metadata", freeze_json(self.metadata))


@dataclass(frozen=True)
class ExecutionContext:
    run_id: str
    ownership_id: str
    provenance_id: str
    requested_nodes: int
    artifact_root: Path
    definition_id: str
    definition_version: int
    definition_digest: str
    plan_digest: str
    fault_scope: OwnedFaultScope
    backend_id: str
    profile_id: str
    config_template: Optional[str]
    configuration: Mapping[str, Any]
    metadata: Mapping[str, Any]
    operator_opt_in: bool = False
    cost_acknowledged: bool = False

    def __post_init__(self) -> None:
        _require_identifier("run_id", self.run_id)
        _require_identifier("ownership_id", self.ownership_id)
        _require_identifier("provenance_id", self.provenance_id)
        if self.fault_scope.run_id != self.run_id:
            raise ValueError("fault scope run_id must match context run_id")
        if self.fault_scope.ownership_id != self.ownership_id:
            raise ValueError("fault scope ownership_id must match context ownership_id")
        _require_identifier("backend_id", self.backend_id)
        _require_identifier("profile_id", self.profile_id)
        if not isinstance(self.operator_opt_in, bool):
            raise TypeError("operator_opt_in must be a boolean")
        if not isinstance(self.cost_acknowledged, bool):
            raise TypeError("cost_acknowledged must be a boolean")
        if isinstance(self.requested_nodes, bool) or not isinstance(
            self.requested_nodes, int
        ):
            raise TypeError("requested_nodes must be an integer")
        if not isinstance(self.configuration, Mapping):
            raise TypeError("configuration must be a mapping")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        object.__setattr__(self, "configuration", freeze_json(self.configuration))
        object.__setattr__(self, "metadata", freeze_json(self.metadata))


@dataclass(frozen=True)
class StepResult:
    step_id: str
    status: StepStatus
    run_id: str
    ownership_id: str
    provenance_id: str
    reason: Optional[str] = None
    artifact_paths: Tuple[Path, ...] = ()
    details: Mapping[str, Any] = dataclasses.field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_paths", tuple(self.artifact_paths))
        _require_identifier("step_id", self.step_id)
        _require_identifier("run_id", self.run_id)
        _require_identifier("ownership_id", self.ownership_id)
        _require_identifier("provenance_id", self.provenance_id)
        if not isinstance(self.status, StepStatus):
            raise TypeError("status must be a StepStatus")
        if self.status is not StepStatus.PASS and not self.reason:
            raise ValueError("non-PASS step results require a reason")
        if self.reason is not None and not isinstance(self.reason, str):
            raise TypeError("reason must be a string or None")
        if not all(isinstance(path, Path) for path in self.artifact_paths):
            raise TypeError("artifact_paths must contain pathlib.Path values")
        if not isinstance(self.details, Mapping):
            raise TypeError("details must be a mapping")
        object.__setattr__(self, "details", freeze_json(self.details))

    @classmethod
    def passed(
        cls,
        context: ExecutionContext,
        step_id: str,
        *,
        artifact_paths: Tuple[Path, ...] = (),
        details: Optional[Mapping[str, Any]] = None,
    ) -> "StepResult":
        return cls(
            step_id=step_id,
            status=StepStatus.PASS,
            run_id=context.run_id,
            ownership_id=context.ownership_id,
            provenance_id=context.provenance_id,
            artifact_paths=artifact_paths,
            details={} if details is None else details,
        )

    @classmethod
    def failed(
        cls,
        context: ExecutionContext,
        step_id: str,
        reason: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
    ) -> "StepResult":
        return cls(
            step_id=step_id,
            status=StepStatus.FAIL,
            run_id=context.run_id,
            ownership_id=context.ownership_id,
            provenance_id=context.provenance_id,
            reason=reason,
            details={} if details is None else details,
        )


@dataclass(frozen=True)
class FailureInfo:
    code: str
    reason: str
    step_id: Optional[str]
    exception_type: Optional[str] = None

    def __post_init__(self) -> None:
        _require_identifier("failure code", self.code)
        if not self.reason:
            raise ValueError("failure reason is required")


@dataclass(frozen=True)
class GateResult:
    status: GateStatus
    run_id: str
    ownership_id: str
    provenance_id: str
    requested_nodes: int
    definition_id: str
    definition_version: int
    definition_digest: str
    plan_digest: str
    steps: Tuple[StepResult, ...]
    cleanup_result: StepResult
    primary_failure: Optional[FailureInfo] = None
    cleanup_failure: Optional[FailureInfo] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))
        if not isinstance(self.status, GateStatus):
            raise TypeError("status must be a GateStatus")
        for result in self.steps + (self.cleanup_result,):
            if result.run_id != self.run_id:
                raise ValueError("step result run_id does not match gate result")
            if result.ownership_id != self.ownership_id:
                raise ValueError("step result ownership_id does not match gate result")
            if result.provenance_id != self.provenance_id:
                raise ValueError("step result provenance_id does not match gate result")
        if self.cleanup_result.step_id != "cleanup":
            raise ValueError("cleanup_result must have step_id 'cleanup'")
        if self.status is GateStatus.PASS:
            if self.primary_failure or self.cleanup_failure:
                raise ValueError("PASS cannot contain failures")
            if self.cleanup_result.status is not StepStatus.PASS:
                raise ValueError("cleanup failure prevents PASS")

    @property
    def step_results(self) -> Tuple[StepResult, ...]:
        return self.steps + (self.cleanup_result,)

    @property
    def passed(self) -> bool:
        return self.status is GateStatus.PASS

    @property
    def reason(self) -> Optional[str]:
        if self.primary_failure is not None:
            return self.primary_failure.reason
        if self.cleanup_failure is not None:
            return self.cleanup_failure.reason
        return None


@runtime_checkable
class RuntimeAdapter(Protocol):
    def resource_preflight(self, context: ExecutionContext) -> StepResult: ...
    def runtime_start(self, context: ExecutionContext) -> StepResult: ...
    def cluster_form(self, context: ExecutionContext) -> StepResult: ...
    def stabilize(self, context: ExecutionContext) -> StepResult: ...
    def recovery(self, context: ExecutionContext) -> StepResult: ...
    def cleanup(self, context: ExecutionContext) -> StepResult: ...


@runtime_checkable
class WorkloadAdapter(Protocol):
    def run_baseline(self, context: ExecutionContext) -> StepResult: ...


@runtime_checkable
class ManagementAdapter(Protocol):
    def run_matrix(
        self,
        context: ExecutionContext,
        scenarios: Tuple[ScenarioSpec, ...],
        execution_order: Tuple[str, ...],
    ) -> StepResult: ...


@runtime_checkable
class FaultAdapter(Protocol):
    def run_matrix(
        self,
        context: ExecutionContext,
        scenarios: Tuple[ScenarioSpec, ...],
        scope: OwnedFaultScope,
    ) -> StepResult: ...


@runtime_checkable
class ArtifactValidationAdapter(Protocol):
    def validate(
        self,
        context: ExecutionContext,
        artifacts: Tuple[ArtifactSpec, ...],
    ) -> StepResult: ...


@runtime_checkable
class AnalysisAdapter(Protocol):
    def analyze(self, context: ExecutionContext) -> StepResult: ...


@runtime_checkable
class ReportAdapter(Protocol):
    def render(
        self,
        context: ExecutionContext,
        surfaces: Tuple[ReportSurface, ...],
    ) -> StepResult: ...


@dataclass(frozen=True)
class AdapterBundle:
    runtime: RuntimeAdapter
    workload: WorkloadAdapter
    management: ManagementAdapter
    fault: FaultAdapter
    artifact_validation: ArtifactValidationAdapter
    analysis: AnalysisAdapter
    report: ReportAdapter


def _require_identifier(label: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a non-empty attributable identifier")
