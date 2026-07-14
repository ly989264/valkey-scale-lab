from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .models import ResourceBudgetDefinition
from .planner import ObjectiveProposal, PlanningLimits


class BudgetError(RuntimeError):
    pass


@dataclass
class BudgetLedger:
    created_at_unix: int
    iterations: int = 0
    objective_attempts: int = 0
    planning_rounds: int = 0
    worker_seconds: float = 0.0
    evaluator_seconds: float = 0.0
    cost_units: int = 0
    context_bytes: int = 0
    write_bytes: int = 0
    evidence_bytes: int = 0
    transaction_bytes: int = 0
    capability_runs: int = 0
    operator_runs: int = 0
    diagnostic_iterations: int = 0

    @classmethod
    def fresh(cls, *, now: int | None = None) -> "BudgetLedger":
        return cls(created_at_unix=int(time.time()) if now is None else now)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BudgetLedger":
        return cls(**dict(value))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def remaining_limits(
        self,
        budget: ResourceBudgetDefinition,
        *,
        approved_capabilities: tuple[str, ...] = (),
        capability_uses: tuple[tuple[str, int], ...] = (),
    ) -> PlanningLimits:
        return PlanningLimits(
            remaining_cost_units=max(0, budget.max_cost_units - self.cost_units),
            remaining_context_bytes=max(0, budget.max_context_bytes - self.context_bytes),
            remaining_write_bytes=max(0, budget.max_write_bytes - self.write_bytes),
            remaining_worker_seconds=max(0, int(budget.max_worker_seconds - self.worker_seconds)),
            remaining_evaluator_seconds=max(0, int(budget.max_evaluator_seconds - self.evaluator_seconds)),
            remaining_capability_runs=max(0, budget.max_capability_runs - self.capability_runs),
            remaining_operator_runs=max(0, budget.max_operator_runs - self.operator_runs),
            approved_capabilities=approved_capabilities,
            capability_uses=capability_uses,
        )

    def ensure_run_available(
        self,
        budget: ResourceBudgetDefinition,
        *,
        now: int | None = None,
    ) -> None:
        current = int(time.time()) if now is None else now
        checks = {
            "max_iterations": (self.iterations, budget.max_iterations),
            "max_objective_attempts": (self.objective_attempts, budget.max_objective_attempts),
            "max_wall_seconds": (current - self.created_at_unix, budget.max_wall_seconds),
            "max_worker_seconds": (self.worker_seconds, budget.max_worker_seconds),
            "max_evaluator_seconds": (self.evaluator_seconds, budget.max_evaluator_seconds),
            "max_cost_units": (self.cost_units, budget.max_cost_units),
            "max_context_bytes": (self.context_bytes, budget.max_context_bytes),
            "max_write_bytes": (self.write_bytes, budget.max_write_bytes),
            "max_evidence_bytes": (self.evidence_bytes, budget.max_evidence_bytes),
            "max_transaction_bytes": (self.transaction_bytes, budget.max_transaction_bytes),
            "max_capability_runs": (self.capability_runs, budget.max_capability_runs),
            "max_operator_runs": (self.operator_runs, budget.max_operator_runs),
            "max_diagnostic_iterations": (self.diagnostic_iterations, budget.max_diagnostic_iterations),
        }
        exhausted = [name for name, (used, maximum) in checks.items() if used >= maximum and maximum > 0]
        if exhausted:
            raise BudgetError(f"resource budget exhausted: {sorted(exhausted)}")

    def reserve_objective(
        self,
        proposal: ObjectiveProposal,
        budget: ResourceBudgetDefinition,
        *,
        diagnostic: bool = False,
    ) -> None:
        projected = {
            "objective_attempts": self.objective_attempts + 1,
            "worker_seconds": self.worker_seconds + proposal.estimated_worker_seconds,
            "evaluator_seconds": self.evaluator_seconds + proposal.estimated_evaluator_seconds,
            "cost_units": self.cost_units + proposal.estimated_cost_units,
            "context_bytes": self.context_bytes + proposal.estimated_context_bytes,
            "write_bytes": self.write_bytes + proposal.estimated_write_bytes,
            "capability_runs": self.capability_runs + len(proposal.capabilities),
            "diagnostic_iterations": self.diagnostic_iterations + (1 if diagnostic else 0),
        }
        maxima = {
            "objective_attempts": budget.max_objective_attempts,
            "worker_seconds": budget.max_worker_seconds,
            "evaluator_seconds": budget.max_evaluator_seconds,
            "cost_units": budget.max_cost_units,
            "context_bytes": budget.max_context_bytes,
            "write_bytes": budget.max_write_bytes,
            "capability_runs": budget.max_capability_runs,
            "diagnostic_iterations": budget.max_diagnostic_iterations,
        }
        exceeded = [name for name, value in projected.items() if value > maxima[name]]
        if exceeded:
            raise BudgetError(f"objective reservation exceeds budget: {sorted(exceeded)}")
        for name, value in projected.items():
            setattr(self, name, value)

    def charge_evaluation(
        self,
        *,
        seconds: float,
        cost_units: int,
        evidence_bytes: int,
        budget: ResourceBudgetDefinition,
    ) -> None:
        projected = {
            "evaluator_seconds": self.evaluator_seconds + seconds,
            "cost_units": self.cost_units + cost_units,
            "evidence_bytes": self.evidence_bytes + evidence_bytes,
        }
        maxima = {
            "evaluator_seconds": budget.max_evaluator_seconds,
            "cost_units": budget.max_cost_units,
            "evidence_bytes": budget.max_evidence_bytes,
        }
        exceeded = [name for name, value in projected.items() if value > maxima[name]]
        if exceeded:
            raise BudgetError(f"evaluation exceeds budget: {sorted(exceeded)}")
        for name, value in projected.items():
            setattr(self, name, value)

    def charge_planning_round(self, budget: ResourceBudgetDefinition) -> None:
        if self.planning_rounds + 1 > budget.max_iterations * budget.max_planning_rounds_per_iteration:
            raise BudgetError("planning round budget exhausted")
        self.planning_rounds += 1

    def charge_operator_run(self, budget: ResourceBudgetDefinition) -> None:
        if self.operator_runs + 1 > budget.max_operator_runs:
            raise BudgetError("operator run budget exhausted")
        self.operator_runs += 1
