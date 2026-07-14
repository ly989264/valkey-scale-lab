from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    MISSING = "MISSING"
    BLOCKED_ENV = "BLOCKED_ENV"
    ERROR = "ERROR"
    STALE = "STALE"
    UNTRUSTED = "UNTRUSTED"
    SUBSTITUTED = "SUBSTITUTED"


class TerminalStatus(str, Enum):
    SUCCESS = "SUCCESS"
    STAGNATED = "STAGNATED"
    ENVIRONMENT_BLOCKED = "ENVIRONMENT_BLOCKED"
    NO_LEGAL_PLAN = "NO_LEGAL_PLAN"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


@dataclass(frozen=True)
class SuccessCondition:
    id: str
    statement: str
    evidence_requirement_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceRequirement:
    id: str
    statement: str
    kind: str
    source_id: str
    freshness_seconds: int
    provenance_required: bool
    substitution_policy: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True)
class TerminationConditions:
    max_iterations: int
    max_stagnant_iterations: int
    max_environment_retries: int
    max_no_plan_rounds: int
    max_wall_seconds: int


@dataclass(frozen=True)
class Milestone:
    schema_version: str
    id: str
    title: str
    goal: str
    success_conditions: tuple[SuccessCondition, ...]
    evidence_requirements: tuple[EvidenceRequirement, ...]
    termination: TerminationConditions


@dataclass(frozen=True)
class CheckResult:
    id: str
    status: CheckStatus
    summary: str
    artifact: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.id,
            "status": self.status.value,
            "summary": self.summary,
        }
        if self.artifact is not None:
            value["artifact"] = self.artifact
        if self.provenance:
            value["provenance"] = dict(self.provenance)
        return value


@dataclass(frozen=True)
class Gap:
    id: str
    kind: str
    statement: str
    status: CheckStatus
    summary: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "kind": self.kind,
            "statement": self.statement,
            "status": self.status.value,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class GoalState:
    iteration: int
    condition_results: tuple[CheckResult, ...]
    evidence_results: tuple[CheckResult, ...]
    gaps: tuple[Gap, ...]

    @property
    def complete(self) -> bool:
        return not self.gaps

    @property
    def passed_ids(self) -> frozenset[str]:
        condition_ids = {
            f"condition:{item.id}"
            for item in self.condition_results
            if item.status is CheckStatus.PASS
        }
        evidence_ids = {
            f"evidence:{item.id}"
            for item in self.evidence_results
            if item.status is CheckStatus.PASS
        }
        return frozenset((*condition_ids, *evidence_ids))

    @property
    def blocked_ids(self) -> frozenset[str]:
        blocked = {CheckStatus.BLOCKED_ENV, CheckStatus.ERROR}
        condition_ids = {
            f"condition:{item.id}"
            for item in self.condition_results
            if item.status in blocked
        }
        evidence_ids = {
            f"evidence:{item.id}"
            for item in self.evidence_results
            if item.status in blocked
        }
        return frozenset((*condition_ids, *evidence_ids))

    @property
    def basis(self) -> tuple[tuple[str, str, str], ...]:
        rows = [
            (
                f"condition:{item.id}",
                item.status.value,
                json.dumps(
                    {"artifact": item.artifact, "provenance": dict(item.provenance)},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            for item in self.condition_results
        ]
        rows.extend(
            (
                f"evidence:{item.id}",
                item.status.value,
                json.dumps(
                    {"artifact": item.artifact, "provenance": dict(item.provenance)},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            for item in self.evidence_results
        )
        return tuple(sorted(rows))

    def as_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "complete": self.complete,
            "condition_results": [item.as_dict() for item in self.condition_results],
            "evidence_results": [item.as_dict() for item in self.evidence_results],
            "gaps": [item.as_dict() for item in self.gaps],
        }


@dataclass(frozen=True)
class Objective:
    id: str
    title: str
    strategy: str
    target_gap_ids: tuple[str, ...]
    write_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("id", "title", "strategy"):
            if not getattr(self, name).strip():
                raise ValueError(f"objective {name} must not be empty")
        if not self.target_gap_ids:
            raise ValueError("objective must target at least one current gap")
        if not self.write_paths:
            raise ValueError("objective must declare at least one write path")
        object.__setattr__(self, "target_gap_ids", tuple(sorted(set(self.target_gap_ids))))
        object.__setattr__(self, "write_paths", tuple(sorted(set(self.write_paths))))

    @property
    def equivalence_key(self) -> tuple[tuple[str, ...], str, tuple[str, ...]]:
        normalized_strategy = " ".join(self.strategy.casefold().split())
        return self.target_gap_ids, normalized_strategy, self.write_paths

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "strategy": self.strategy,
            "target_gap_ids": list(self.target_gap_ids),
            "write_paths": list(self.write_paths),
        }


@dataclass(frozen=True)
class Attempt:
    iteration: int
    objective: Objective
    goal_basis: tuple[tuple[str, str, str], ...]
    outcome: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "objective": self.objective.as_dict(),
            "goal_basis": [list(item) for item in self.goal_basis],
            "outcome": self.outcome,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PlanContext:
    goal_state: GoalState
    failed_attempts: tuple[Attempt, ...]
    remaining_iterations: int
    remaining_wall_seconds: float


@dataclass(frozen=True)
class RunResult:
    milestone_id: str
    status: TerminalStatus
    reason: str
    goal_state: GoalState | None
    failed_attempts: tuple[Attempt, ...]
    retained_commits: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "controller-run-result-v1",
            "milestone_id": self.milestone_id,
            "status": self.status.value,
            "reason": self.reason,
            "goal_state": None if self.goal_state is None else self.goal_state.as_dict(),
            "failed_attempts": [item.as_dict() for item in self.failed_attempts],
            "retained_commits": list(self.retained_commits),
        }
