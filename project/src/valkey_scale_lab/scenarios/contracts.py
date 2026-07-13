from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple


def freeze_json(value: Any) -> Any:
    """Return a recursively immutable representation of JSON-compatible data."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    return value


@dataclass(frozen=True)
class LifecycleStep:
    id: str
    handler_id: str
    depends_on: Tuple[str, ...]
    always_run: bool = False
    terminal: bool = False


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    handler_id: str
    command_stream: str
    operations: Tuple[str, ...] = ()
    parameters: Mapping[str, Any] = dataclasses.field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", freeze_json(self.parameters))


@dataclass(frozen=True)
class AdmissionSpec:
    kind: str
    format: str
    source_raw_name: str
    transform_id: Optional[str] = None
    source_selector: Optional[str] = None

    @property
    def admitted_kind(self) -> str:
        return self.kind

    @property
    def source(self) -> str:
        if self.source_selector:
            return f"{self.source_raw_name}#/{self.source_selector}"
        return self.source_raw_name


@dataclass(frozen=True)
class ArtifactSpec:
    raw_name: str
    format: str
    admissions: Tuple[AdmissionSpec, ...] = ()
    required_raw: bool = True

    @property
    def source_path(self) -> str:
        return self.raw_name

    @property
    def source(self) -> str:
        return self.raw_name

    @property
    def id(self) -> str:
        return self.raw_name

    @property
    def required(self) -> bool:
        return self.required_raw

    @property
    def admitted(self) -> bool:
        return bool(self.admissions)

    @property
    def admitted_kinds(self) -> Tuple[str, ...]:
        return tuple(admission.kind for admission in self.admissions)

    @property
    def admitted_kind(self) -> Optional[str]:
        if len(self.admissions) == 1:
            return self.admissions[0].kind
        return None


@dataclass(frozen=True)
class ReportSurface:
    id: str


@dataclass(frozen=True)
class ScalePolicy:
    min_nodes: int
    max_nodes: int
    required_real_scales: Tuple[int, ...]
    runnable_not_required_scales: Tuple[int, ...]
    normal_development_cap: int
    bounded_exception_scale: int
    exact_requested_nodes: bool
    no_silent_downscale: bool
    bounded_exception_requires_resource_preflight: bool
    above_200_requires_operator_opt_in: bool
    above_200_requires_resource_preflight: bool
    above_200_requires_cost_acknowledgement: bool

    @property
    def real_above_cap_requires_opt_in(self) -> bool:
        """Compatibility spelling; the exact-200 bounded exception is handled separately."""
        return self.above_200_requires_operator_opt_in


@dataclass(frozen=True)
class ScenarioDefinition:
    schema_version: str
    definition_id: str
    version: int
    lifecycle_steps: Tuple[LifecycleStep, ...]
    management_scenarios: Tuple[ScenarioSpec, ...]
    fault_scenarios: Tuple[ScenarioSpec, ...]
    management_execution_order: Tuple[str, ...]
    artifacts: Tuple[ArtifactSpec, ...]
    report_surfaces: Tuple[ReportSurface, ...]
    scale_policy: ScalePolicy
    legacy_profiles: Tuple["LegacyProfileBinding", ...]
    legacy_projection_steps: Tuple[str, ...]
    digest: str

    @property
    def lifecycle_ids(self) -> Tuple[str, ...]:
        return tuple(step.id for step in self.lifecycle_steps)

    @property
    def management_ids(self) -> Tuple[str, ...]:
        return tuple(scenario.id for scenario in self.management_scenarios)

    @property
    def fault_ids(self) -> Tuple[str, ...]:
        return tuple(scenario.id for scenario in self.fault_scenarios)

    @property
    def scenario_ids(self) -> Tuple[str, ...]:
        return self.management_ids + self.fault_ids

    @property
    def artifact_ids(self) -> Tuple[str, ...]:
        return tuple(
            admission.kind
            for artifact in self.artifacts
            for admission in artifact.admissions
        )

    @property
    def admitted_artifact_ids(self) -> Tuple[str, ...]:
        return self.artifact_ids

    @property
    def raw_artifact_names(self) -> Tuple[str, ...]:
        return tuple(artifact.raw_name for artifact in self.artifacts)

    @property
    def report_ids(self) -> Tuple[str, ...]:
        return tuple(surface.id for surface in self.report_surfaces)

    @property
    def raw_json_artifacts(self) -> Tuple[ArtifactSpec, ...]:
        return tuple(artifact for artifact in self.artifacts if artifact.format == "json")

    @property
    def raw_jsonl_artifacts(self) -> Tuple[ArtifactSpec, ...]:
        return tuple(artifact for artifact in self.artifacts if artifact.format == "jsonl")

    @property
    def admitted_json_artifacts(self) -> Tuple[AdmissionSpec, ...]:
        return tuple(
            admission
            for artifact in self.raw_json_artifacts
            for admission in artifact.admissions
        )

    @property
    def admitted_jsonl_artifacts(self) -> Tuple[AdmissionSpec, ...]:
        return tuple(
            admission
            for artifact in self.raw_jsonl_artifacts
            for admission in artifact.admissions
        )


@dataclass(frozen=True)
class LegacyProfileBinding:
    requested_nodes: int
    runtime_phase: str
    runtime_scenario: str
    config_template: str


@dataclass(frozen=True)
class GatePlan:
    definition_id: str
    definition_version: int
    definition_digest: str
    requested_nodes: int
    exact: bool
    legacy_profile: Optional[LegacyProfileBinding]
    execution_mode: str
    required_completion_gate: bool
    runnable_not_gated: bool
    normal_development_eligible: bool
    automatic_execution_allowed: bool
    bounded_200_exception: bool
    requires_operator_opt_in: bool
    requires_resource_preflight: bool
    requires_cost_acknowledgement: bool
    downscale_allowed: bool
    lifecycle_steps: Tuple[LifecycleStep, ...]
    management_scenarios: Tuple[ScenarioSpec, ...]
    fault_scenarios: Tuple[ScenarioSpec, ...]
    management_execution_order: Tuple[str, ...]
    artifacts: Tuple[ArtifactSpec, ...]
    report_surfaces: Tuple[ReportSurface, ...]
    legacy_projection_steps: Tuple[str, ...]
    digest: str

    @property
    def exact_node_count(self) -> int:
        return self.requested_nodes

    @property
    def runtime_scenario(self) -> Optional[str]:
        return self.legacy_profile.runtime_scenario if self.legacy_profile else None

    @property
    def runtime_phase(self) -> Optional[str]:
        return self.legacy_profile.runtime_phase if self.legacy_profile else None

    @property
    def config_template(self) -> Optional[str]:
        return self.legacy_profile.config_template if self.legacy_profile else None

    @property
    def required_real_completion(self) -> bool:
        return self.required_completion_gate

    @property
    def runnable_not_required(self) -> bool:
        return self.runnable_not_gated

    @property
    def bounded_exception(self) -> bool:
        return self.bounded_200_exception

    @property
    def plan_digest(self) -> str:
        return self.digest

    @property
    def lifecycle_ids(self) -> Tuple[str, ...]:
        return tuple(step.id for step in self.lifecycle_steps)

    @property
    def scenario_ids(self) -> Tuple[str, ...]:
        return tuple(
            scenario.id
            for scenario in self.management_scenarios + self.fault_scenarios
        )

    @property
    def artifact_ids(self) -> Tuple[str, ...]:
        return tuple(
            admission.kind
            for artifact in self.artifacts
            for admission in artifact.admissions
        )

    @property
    def admitted_artifact_ids(self) -> Tuple[str, ...]:
        return self.artifact_ids

    @property
    def raw_artifact_names(self) -> Tuple[str, ...]:
        return tuple(artifact.raw_name for artifact in self.artifacts)

    @property
    def report_ids(self) -> Tuple[str, ...]:
        return tuple(surface.id for surface in self.report_surfaces)
