from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class MilestoneIdentity:
    id: str
    version: str
    title: str
    final_goal: str


@dataclass(frozen=True)
class SuccessConditionDefinition:
    id: str
    statement: str
    evaluator_ids: tuple[str, ...]
    evidence_requirement_ids: tuple[str, ...]
    required: bool


@dataclass(frozen=True)
class EvaluatorDefinition:
    id: str
    mode: str
    authority: str
    trust_mode: str
    argv: tuple[str, ...]
    cwd: str
    timeout_seconds: int
    inputs: tuple[str, ...]
    output_schema: str
    cost: str
    cost_units: int
    capabilities: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mode": self.mode,
            "authority": self.authority,
            "trust_mode": self.trust_mode,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "timeout_seconds": self.timeout_seconds,
            "inputs": list(self.inputs),
            "output_schema": self.output_schema,
            "cost": self.cost,
            "cost_units": self.cost_units,
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True)
class EvidenceFreshnessDefinition:
    max_age_seconds: int
    bind_to_product_digest: bool
    bind_to_run_id: bool


@dataclass(frozen=True)
class EvidenceRequirementDefinition:
    id: str
    statement: str
    capture_class: str
    provenance_required: bool
    freshness: EvidenceFreshnessDefinition
    substitution_policy: str
    admission_evaluator_ids: tuple[str, ...]


@dataclass(frozen=True)
class CapabilityPolicyDefinition:
    id: str
    operator_approval_required: bool
    max_uses: int
    cost_units_per_use: int


@dataclass(frozen=True)
class SafetyDefinition:
    product_roots: tuple[str, ...]
    context_roots: tuple[str, ...]
    mutable_roots: tuple[str, ...]
    immutable_roots: tuple[str, ...]
    evaluator_roots: tuple[str, ...]
    authority_roots: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    capability_policies: tuple[CapabilityPolicyDefinition, ...]
    forbidden_effects: tuple[str, ...]

    @property
    def allowed_capabilities(self) -> tuple[str, ...]:
        return tuple(policy.id for policy in self.capability_policies)


@dataclass(frozen=True)
class ResourceBudgetDefinition:
    max_iterations: int
    max_objective_attempts: int
    max_planning_rounds_per_iteration: int
    max_wall_seconds: int
    max_worker_seconds: int
    max_evaluator_seconds: int
    max_cost_units: int
    max_context_bytes: int
    max_write_bytes: int
    max_evidence_bytes: int
    max_transaction_bytes: int
    max_capability_runs: int
    max_operator_runs: int
    max_diagnostic_iterations: int

    def __getitem__(self, key: str) -> int:
        try:
            value = getattr(self, key)
        except AttributeError as exc:
            raise KeyError(key) from exc
        if not isinstance(value, int):  # pragma: no cover - dataclass invariant
            raise KeyError(key)
        return value


@dataclass(frozen=True)
class TerminationDefinition:
    max_consecutive_no_material_progress: int
    max_consecutive_environment_blocked: int
    max_no_legal_plan_rounds: int
    integrity_anomaly: str
    budget_exhaustion: str
    operator_abort: str


@dataclass(frozen=True)
class MilestoneContract:
    schema_version: str
    milestone: MilestoneIdentity
    success_conditions: tuple[SuccessConditionDefinition, ...]
    evaluators: tuple[EvaluatorDefinition, ...]
    evidence_requirements: tuple[EvidenceRequirementDefinition, ...]
    safety: SafetyDefinition
    resource_budget: ResourceBudgetDefinition
    termination: TerminationDefinition

    def success_condition(self, condition_id: str) -> SuccessConditionDefinition:
        return _by_id(self.success_conditions, condition_id)

    def evaluator(self, evaluator_id: str) -> EvaluatorDefinition:
        return _by_id(self.evaluators, evaluator_id)

    def evidence_requirement(self, requirement_id: str) -> EvidenceRequirementDefinition:
        return _by_id(self.evidence_requirements, requirement_id)


def _by_id(values: Iterable[Any], value_id: str) -> Any:
    for value in values:
        if value.id == value_id:
            return value
    raise KeyError(value_id)
