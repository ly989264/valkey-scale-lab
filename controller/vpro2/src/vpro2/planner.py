from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable

from .gap_graph import GapGraph
from .history import PathAssessment, PathDecision, PathLedger, StrategyDescriptor
from .models import MilestoneContract


@dataclass(frozen=True)
class ObjectiveProposal:
    objective_id: str
    title: str
    root_gap_id: str
    strategy_key: str
    context_paths: tuple[str, ...]
    write_paths: tuple[str, ...]
    capabilities: tuple[str, ...]
    evaluator_ids: tuple[str, ...]
    expected_condition_ids: tuple[str, ...]
    estimated_cost_units: int
    estimated_context_bytes: int
    estimated_write_bytes: int
    estimated_worker_seconds: int
    estimated_evaluator_seconds: int

    def __post_init__(self) -> None:
        if not self.objective_id or not self.title.strip():
            raise ValueError("objective proposals require an id and title")
        for field in (
            "estimated_cost_units",
            "estimated_context_bytes",
            "estimated_write_bytes",
            "estimated_worker_seconds",
            "estimated_evaluator_seconds",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must not be negative")
        for field in (
            "context_paths",
            "write_paths",
            "capabilities",
            "evaluator_ids",
            "expected_condition_ids",
        ):
            object.__setattr__(self, field, tuple(sorted(set(getattr(self, field)))))

    @property
    def strategy(self) -> StrategyDescriptor:
        return StrategyDescriptor(
            root_gap_id=self.root_gap_id,
            strategy_key=self.strategy_key,
            write_paths=self.write_paths,
            capabilities=self.capabilities,
        )


@dataclass(frozen=True)
class PlanningLimits:
    remaining_cost_units: int
    remaining_context_bytes: int
    remaining_write_bytes: int
    remaining_worker_seconds: int
    remaining_evaluator_seconds: int
    remaining_capability_runs: int
    remaining_operator_runs: int
    approved_capabilities: tuple[str, ...] = ()
    capability_uses: tuple[tuple[str, int], ...] = ()

    @classmethod
    def from_contract(cls, contract: MilestoneContract) -> "PlanningLimits":
        budget = contract.resource_budget
        return cls(
            remaining_cost_units=budget.max_cost_units,
            remaining_context_bytes=budget.max_context_bytes,
            remaining_write_bytes=budget.max_write_bytes,
            remaining_worker_seconds=budget.max_worker_seconds,
            remaining_evaluator_seconds=budget.max_evaluator_seconds,
            remaining_capability_runs=budget.max_capability_runs,
            remaining_operator_runs=budget.max_operator_runs,
        )

    def __post_init__(self) -> None:
        for field in (
            "remaining_cost_units",
            "remaining_context_bytes",
            "remaining_write_bytes",
            "remaining_worker_seconds",
            "remaining_evaluator_seconds",
            "remaining_capability_runs",
            "remaining_operator_runs",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must not be negative")
        object.__setattr__(
            self,
            "approved_capabilities",
            tuple(sorted(set(self.approved_capabilities))),
        )
        uses = dict(self.capability_uses)
        if any(not key or value < 0 for key, value in uses.items()):
            raise ValueError("capability usage must use non-empty ids and non-negative counts")
        object.__setattr__(self, "capability_uses", tuple(sorted(uses.items())))

    @property
    def capability_use_map(self) -> dict[str, int]:
        return dict(self.capability_uses)


@dataclass(frozen=True)
class ProposalAudit:
    proposal: ObjectiveProposal
    reasons: tuple[str, ...]
    path_assessment: PathAssessment
    impact_score: int
    minimum_cost_units: int
    approval_required_capabilities: tuple[str, ...]
    operator_cost_approval_required: bool

    @property
    def accepted(self) -> bool:
        return not self.reasons

    @property
    def requires_operator_approval(self) -> bool:
        return bool(self.approval_required_capabilities) or self.operator_cost_approval_required


@dataclass(frozen=True)
class PlanningResult:
    ranked: tuple[ProposalAudit, ...]
    rejected: tuple[ProposalAudit, ...]


def audit_proposal(
    proposal: ObjectiveProposal,
    *,
    contract: MilestoneContract,
    graph: GapGraph,
    ledger: PathLedger,
    evidence_basis_digest: str,
    limits: PlanningLimits | None = None,
) -> ProposalAudit:
    limits = limits or PlanningLimits.from_contract(contract)
    reasons: list[str] = []
    safety = contract.safety
    budget = contract.resource_budget
    root_ids = set(graph.root_condition_ids)
    if proposal.root_gap_id not in root_ids:
        reasons.append("NOT_A_ROOT_GAP")
        impact_score = 0
    else:
        impact_score = graph.impact_for_root(proposal.root_gap_id)

    if proposal.root_gap_id not in proposal.expected_condition_ids:
        reasons.append("ROOT_GAP_NOT_MEASURABLE")
    if not proposal.expected_condition_ids or not proposal.evaluator_ids:
        reasons.append("NO_MEASURABLE_GOAL_DELTA")

    condition_ids = {condition.id for condition in contract.success_conditions}
    evaluator_ids = {evaluator.id for evaluator in contract.evaluators}
    unknown_conditions = sorted(set(proposal.expected_condition_ids) - condition_ids)
    unknown_evaluators = sorted(set(proposal.evaluator_ids) - evaluator_ids)
    if unknown_conditions:
        reasons.append("UNKNOWN_SUCCESS_CONDITION:" + ",".join(unknown_conditions))
    if unknown_evaluators:
        reasons.append("UNKNOWN_EVALUATOR:" + ",".join(unknown_evaluators))

    known_selected_evaluators = tuple(
        contract.evaluator(evaluator_id)
        for evaluator_id in proposal.evaluator_ids
        if evaluator_id in evaluator_ids
    )
    for condition_id in proposal.expected_condition_ids:
        if condition_id not in condition_ids:
            continue
        condition = contract.success_condition(condition_id)
        if not set(condition.evaluator_ids).intersection(proposal.evaluator_ids):
            reasons.append(f"CONDITION_NOT_MEASURED:{condition_id}")

    invalid_context = sorted(
        path
        for path in proposal.context_paths
        if not _safe_path(path) or not _covered(path, safety.context_roots)
    )
    if invalid_context:
        reasons.append("CONTEXT_OUT_OF_BOUNDS:" + ",".join(invalid_context))
    invalid_writes = sorted(
        path
        for path in proposal.write_paths
        if not _safe_path(path) or not _covered(path, safety.mutable_roots)
    )
    if invalid_writes:
        reasons.append("WRITE_OUT_OF_BOUNDS:" + ",".join(invalid_writes))
    forbidden_zones = (
        *safety.immutable_roots,
        *safety.evaluator_roots,
        *safety.authority_roots,
        *safety.evidence_roots,
    )
    overlapping_writes = sorted(
        path for path in proposal.write_paths if _overlaps_any(path, forbidden_zones)
    )
    if overlapping_writes:
        reasons.append("WRITE_OVERLAPS_PROTECTED_ROOT:" + ",".join(overlapping_writes))

    selected_capabilities = set(proposal.capabilities)
    selected_capabilities.update(
        capability for evaluator in known_selected_evaluators for capability in evaluator.capabilities
    )
    policies = {policy.id: policy for policy in safety.capability_policies}
    unknown_capabilities = sorted(selected_capabilities - set(policies))
    if unknown_capabilities:
        reasons.append("CAPABILITY_OUT_OF_BOUNDS:" + ",".join(unknown_capabilities))
    approved = set(limits.approved_capabilities)
    uses = limits.capability_use_map
    approval_required: list[str] = []
    for capability in sorted(selected_capabilities.intersection(policies)):
        policy = policies[capability]
        if uses.get(capability, 0) >= policy.max_uses:
            reasons.append(f"CAPABILITY_USE_EXHAUSTED:{capability}")
        if policy.operator_approval_required and capability not in approved:
            approval_required.append(capability)

    capability_cost = sum(
        policies[capability].cost_units_per_use
        for capability in selected_capabilities
        if capability in policies
    )
    evaluator_cost = sum(evaluator.cost_units for evaluator in contract.evaluators)
    minimum_cost = capability_cost + evaluator_cost
    if proposal.estimated_cost_units < minimum_cost:
        reasons.append("COST_ESTIMATE_BELOW_DECLARED_MINIMUM")
    minimum_evaluator_seconds = sum(
        evaluator.timeout_seconds for evaluator in contract.evaluators
    )
    if proposal.estimated_evaluator_seconds < minimum_evaluator_seconds:
        reasons.append("EVALUATOR_TIME_ESTIMATE_BELOW_FULL_MILESTONE_PASS")
    _budget_reason(
        reasons,
        proposal.estimated_cost_units,
        min(budget.max_cost_units, limits.remaining_cost_units),
        "COST_BUDGET_EXCEEDED",
    )
    _budget_reason(
        reasons,
        proposal.estimated_context_bytes,
        min(budget.max_context_bytes, limits.remaining_context_bytes),
        "CONTEXT_BUDGET_EXCEEDED",
    )
    _budget_reason(
        reasons,
        proposal.estimated_write_bytes,
        min(budget.max_write_bytes, limits.remaining_write_bytes),
        "WRITE_BUDGET_EXCEEDED",
    )
    _budget_reason(
        reasons,
        proposal.estimated_worker_seconds,
        min(budget.max_worker_seconds, limits.remaining_worker_seconds),
        "WORKER_TIME_BUDGET_EXCEEDED",
    )
    _budget_reason(
        reasons,
        proposal.estimated_evaluator_seconds,
        min(budget.max_evaluator_seconds, limits.remaining_evaluator_seconds),
        "EVALUATOR_TIME_BUDGET_EXCEEDED",
    )
    if len(selected_capabilities) > limits.remaining_capability_runs:
        reasons.append("CAPABILITY_RUN_BUDGET_EXCEEDED")
    operator_runs = any(
        capability in policies and policies[capability].operator_approval_required
        for capability in selected_capabilities
    )
    if operator_runs > min(budget.max_operator_runs, limits.remaining_operator_runs):
        reasons.append("OPERATOR_RUN_BUDGET_EXCEEDED")

    path_assessment = ledger.assess(
        proposal.strategy,
        evidence_basis_digest=evidence_basis_digest,
    )
    if path_assessment.decision is PathDecision.REJECT_EQUIVALENT_REPEAT:
        reasons.append("EQUIVALENT_PATH_ALREADY_TRIED")
    return ProposalAudit(
        proposal=proposal,
        reasons=tuple(sorted(set(reasons))),
        path_assessment=path_assessment,
        impact_score=impact_score,
        minimum_cost_units=minimum_cost,
        approval_required_capabilities=tuple(approval_required),
        operator_cost_approval_required=any(
            evaluator.cost == "operator" for evaluator in known_selected_evaluators
        ),
    )


def audit_and_rank(
    proposals: Iterable[ObjectiveProposal],
    *,
    contract: MilestoneContract,
    graph: GapGraph,
    ledger: PathLedger,
    evidence_basis_digest: str,
    limits: PlanningLimits | None = None,
) -> PlanningResult:
    audits = [
        audit_proposal(
            proposal,
            contract=contract,
            graph=graph,
            ledger=ledger,
            evidence_basis_digest=evidence_basis_digest,
            limits=limits,
        )
        for proposal in proposals
    ]
    # Equivalent candidates in one planning round consume one path at most.
    by_fingerprint: dict[str, list[int]] = {}
    for index, audit in enumerate(audits):
        by_fingerprint.setdefault(audit.path_assessment.fingerprint, []).append(index)
    for indexes in by_fingerprint.values():
        if len(indexes) < 2:
            continue
        keeper = min(indexes, key=lambda index: audits[index].proposal.objective_id)
        for index in indexes:
            if index == keeper:
                continue
            audit = audits[index]
            audits[index] = ProposalAudit(
                proposal=audit.proposal,
                reasons=tuple(sorted({*audit.reasons, "DUPLICATE_PROPOSAL_IN_ROUND"})),
                path_assessment=audit.path_assessment,
                impact_score=audit.impact_score,
                minimum_cost_units=audit.minimum_cost_units,
                approval_required_capabilities=audit.approval_required_capabilities,
                operator_cost_approval_required=audit.operator_cost_approval_required,
            )
    accepted = tuple(sorted((item for item in audits if item.accepted), key=_priority_key))
    rejected = tuple(sorted((item for item in audits if not item.accepted), key=_rejection_key))
    return PlanningResult(accepted, rejected)


def _priority_key(audit: ProposalAudit) -> tuple[object, ...]:
    proposal = audit.proposal
    return (
        -audit.impact_score,
        -len(proposal.expected_condition_ids),
        proposal.estimated_cost_units,
        proposal.estimated_worker_seconds + proposal.estimated_evaluator_seconds,
        proposal.estimated_write_bytes,
        len(proposal.write_paths),
        audit.path_assessment.fingerprint,
        proposal.objective_id,
    )


def _rejection_key(audit: ProposalAudit) -> tuple[object, ...]:
    return (audit.proposal.objective_id, audit.reasons)


def _budget_reason(reasons: list[str], estimate: int, available: int, reason: str) -> None:
    if estimate > available:
        reasons.append(reason)


def _safe_path(raw: str) -> bool:
    path = PurePosixPath(raw)
    return (
        bool(raw)
        and "\\" not in raw
        and raw == path.as_posix()
        and not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _covered(path: str, roots: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(root.rstrip("/") + "/") for root in roots)


def _overlaps_any(path: str, roots: tuple[str, ...]) -> bool:
    return any(
        path == root
        or path.startswith(root.rstrip("/") + "/")
        or root.startswith(path.rstrip("/") + "/")
        for root in roots
    )
