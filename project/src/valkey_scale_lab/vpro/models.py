from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MilestoneDefinition:
    id: str
    version: str
    title: str
    goal: str


@dataclass(frozen=True)
class ClauseDefinition:
    id: str
    text: str


@dataclass(frozen=True)
class TierDefinition:
    id: str
    rank: int
    cost: str
    reviewer_admissible: bool


@dataclass(frozen=True)
class CheckDefinition:
    id: str
    tier: str
    argv: tuple[str, ...]
    cwd: str
    timeout_seconds: int
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    authority: str
    capabilities: tuple[str, ...]
    cache: str
    mode: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tier": self.tier,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "timeout_seconds": self.timeout_seconds,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "authority": self.authority,
            "capabilities": list(self.capabilities),
            "cache": self.cache,
            "mode": self.mode,
        }


@dataclass(frozen=True)
class ObjectiveDefinition:
    id: str
    title: str
    depends_on: tuple[str, ...]
    clause_ids: tuple[str, ...]
    check_ids: tuple[str, ...]
    context_paths: tuple[str, ...]
    worker_write_paths: tuple[str, ...]
    required_for_milestone: bool


@dataclass(frozen=True)
class ProfileDefinition:
    id: str
    objective_ids: tuple[str, ...]
    include_dependency_closure: bool
    gate_ids: tuple[str, ...]
    claim: str


@dataclass(frozen=True)
class GateDefinition:
    id: str
    kind: str
    after_objective_ids: tuple[str, ...]
    check_ids: tuple[str, ...]
    preflight_check_ids: tuple[str, ...]
    capture_check_id: str | None
    admission_check_ids: tuple[str, ...]
    operator_approval_required: bool
    required_for_milestone: bool

    @property
    def all_check_ids(self) -> tuple[str, ...]:
        if self.kind == "program":
            return self.check_ids
        capture = (self.capture_check_id,) if self.capture_check_id is not None else ()
        return (*self.preflight_check_ids, *capture, *self.admission_check_ids)


@dataclass(frozen=True)
class BudgetDefinition:
    max_attempts: int
    stagnation_limit: int
    max_replans: int
    max_review_rounds: int
    max_new_gaps_per_review: int
    max_context_bytes: int
    failure_excerpt_bytes: int
    cache_unchanged_results: bool
    max_expensive_runs_per_input: int

    def __getitem__(self, key: str) -> int | bool:
        try:
            return getattr(self, key)
        except AttributeError as exc:
            raise KeyError(key) from exc


@dataclass(frozen=True)
class AcceptanceDefinition:
    objective_rule: str
    milestone_rule: str
    common_check_ids: tuple[str, ...]
    closure_check_ids: tuple[str, ...]
    evaluator_guard_check_ids: tuple[str, ...]
    budgets: BudgetDefinition


@dataclass(frozen=True)
class IntegrityDefinition:
    product_roots: tuple[str, ...]
    evaluator_paths: tuple[str, ...]
    evaluator_repair_paths: tuple[str, ...]
    authoritative_check_paths: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    allowed_tools: tuple[str, ...]

    @property
    def runtime_write_paths(self) -> tuple[str, ...]:
        """Compatibility name used by the controller for evidence outputs."""

        return self.evidence_roots


@dataclass(frozen=True)
class ResolvedProfile:
    profile: ProfileDefinition
    objectives: tuple[ObjectiveDefinition, ...]
    gates: tuple[GateDefinition, ...]

    @property
    def objective_ids(self) -> tuple[str, ...]:
        return tuple(objective.id for objective in self.objectives)

    @property
    def gate_ids(self) -> tuple[str, ...]:
        return tuple(gate.id for gate in self.gates)

    @property
    def claim(self) -> str:
        return self.profile.claim


@dataclass(frozen=True)
class BundleDefinition:
    schema_version: str
    milestone: MilestoneDefinition
    clauses: tuple[ClauseDefinition, ...]
    tiers: tuple[TierDefinition, ...]
    checks: tuple[CheckDefinition, ...]
    objectives: tuple[ObjectiveDefinition, ...]
    profiles: tuple[ProfileDefinition, ...]
    gates: tuple[GateDefinition, ...]
    acceptance: AcceptanceDefinition
    integrity: IntegrityDefinition

    def objective(self, objective_id: str) -> ObjectiveDefinition:
        return _by_id(self.objectives, objective_id)

    def check(self, check_id: str) -> CheckDefinition:
        return _by_id(self.checks, check_id)

    def tier(self, tier_id: str) -> TierDefinition:
        return _by_id(self.tiers, tier_id)

    def profile(self, profile_id: str) -> ProfileDefinition:
        return _by_id(self.profiles, profile_id)

    def gate(self, gate_id: str) -> GateDefinition:
        return _by_id(self.gates, gate_id)

    def resolve_profile(self, profile_id: str) -> ResolvedProfile:
        profile = self.profile(profile_id)
        selected = set(profile.objective_ids)
        if profile.include_dependency_closure:
            pending = list(profile.objective_ids)
            while pending:
                objective = self.objective(pending.pop())
                for dependency in objective.depends_on:
                    if dependency not in selected:
                        selected.add(dependency)
                        pending.append(dependency)
        objectives = tuple(objective for objective in self.objectives if objective.id in selected)
        gate_ids = set(profile.gate_ids)
        gates = tuple(gate for gate in self.gates if gate.id in gate_ids)
        return ResolvedProfile(profile=profile, objectives=objectives, gates=gates)


def _by_id(values: tuple[Any, ...], value_id: str) -> Any:
    for value in values:
        if value.id == value_id:
            return value
    raise KeyError(value_id)
