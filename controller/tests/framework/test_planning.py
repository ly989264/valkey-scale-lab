from __future__ import annotations

import unittest

from controller.delta import DeltaKind, compare_goal_states
from controller.gap_graph import (
    ConditionEvaluation,
    EvaluatorFact,
    GapGraph,
    GoalState,
)
from controller.history import (
    PathDecision,
    PathLedger,
    PathOutcome,
    StrategyDescriptor,
)
from controller.models import (
    CapabilityPolicyDefinition,
    EvaluatorDefinition,
    MilestoneContract,
    MilestoneIdentity,
    ResourceBudgetDefinition,
    SafetyDefinition,
    SuccessConditionDefinition,
    TerminationDefinition,
)
from controller.planner import (
    ObjectiveProposal,
    PlanningLimits,
    audit_and_rank,
    audit_proposal,
)


def _evaluation(
    condition_id: str,
    status: str,
    *,
    evidence: str | None = None,
    evaluator: str | None = None,
    trusted: bool = True,
    current: bool = True,
    weight: int = 1,
) -> ConditionEvaluation:
    return ConditionEvaluation(
        condition_id=condition_id,
        status=status,
        evaluator_ids=(evaluator,) if evaluator else (),
        evidence_digests=(evidence,) if evidence else (),
        trusted=trusted,
        current=current,
        impact_weight=weight,
    )


def _fact(
    source: str,
    target: str,
    evidence: str,
    *,
    trusted: bool = True,
    current: bool = True,
) -> EvaluatorFact:
    return EvaluatorFact(
        evaluator_id="dependency-evaluator",
        relation="BLOCKS",
        source_condition_id=source,
        target_condition_id=target,
        evidence_digest=evidence,
        trusted=trusted,
        current=current,
    )


def _evaluator(
    evaluator_id: str,
    *,
    cost: str = "cheap",
    cost_units: int = 1,
    capabilities: tuple[str, ...] = (),
) -> EvaluatorDefinition:
    return EvaluatorDefinition(
        id=evaluator_id,
        mode="condition",
        authority="evaluator",
        trust_mode="independent",
        argv=("python3", "checks/evaluate.py"),
        cwd=".",
        timeout_seconds=10,
        inputs=("checks/evaluate.py", "product"),
        output_schema="schemas/evaluation.json",
        cost=cost,
        cost_units=cost_units,
        capabilities=capabilities,
    )


def _contract() -> MilestoneContract:
    return MilestoneContract(
        schema_version="controller-milestone-v1",
        milestone=MilestoneIdentity("m", "1.0.0", "Milestone", "Reach all conditions"),
        success_conditions=(
            SuccessConditionDefinition("A", "A passes", ("eval-a",), (), True),
            SuccessConditionDefinition("B", "B passes", ("eval-b",), (), True),
            SuccessConditionDefinition("C", "C passes", ("eval-c",), (), True),
            SuccessConditionDefinition("D", "D passes", ("eval-d",), (), True),
        ),
        evaluators=(
            _evaluator("eval-a"),
            _evaluator("eval-b"),
            _evaluator("eval-c"),
            _evaluator("eval-d"),
            _evaluator("eval-network", cost_units=3, capabilities=("network",)),
        ),
        evidence_requirements=(),
        safety=SafetyDefinition(
            product_roots=("product",),
            context_roots=("product", "checks"),
            mutable_roots=("product",),
            immutable_roots=("policy",),
            evaluator_roots=("evaluators",),
            authority_roots=("checks",),
            evidence_roots=("evidence",),
            allowed_tools=("python3",),
            capability_policies=(
                CapabilityPolicyDefinition("network", True, 2, 2),
                CapabilityPolicyDefinition("local-process", False, 3, 1),
            ),
            forbidden_effects=("host-network-change",),
        ),
        resource_budget=ResourceBudgetDefinition(
            max_iterations=10,
            max_objective_attempts=3,
            max_planning_rounds_per_iteration=2,
            max_wall_seconds=1000,
            max_worker_seconds=100,
            max_evaluator_seconds=50,
            max_cost_units=100,
            max_context_bytes=10_000,
            max_write_bytes=5_000,
            max_evidence_bytes=10_000,
            max_transaction_bytes=10_000,
            max_capability_runs=3,
            max_operator_runs=2,
            max_diagnostic_iterations=2,
        ),
        termination=TerminationDefinition(
            max_consecutive_no_material_progress=3,
            max_consecutive_environment_blocked=2,
            max_no_legal_plan_rounds=2,
            integrity_anomaly="FAIL",
            budget_exhaustion="FAIL",
            operator_abort="FAIL",
        ),
    )


def _goal_state() -> GoalState:
    return GoalState(
        iteration=0,
        evaluations=(
            _evaluation("A", "FAIL", evidence="a", evaluator="eval-a", weight=2),
            _evaluation("B", "BLOCKED", evidence="b", evaluator="eval-b", weight=3),
            _evaluation("C", "UNKNOWN", evidence="c", evaluator="eval-c", weight=5),
            _evaluation("D", "FAIL", evidence="d", evaluator="eval-d", weight=1),
            _evaluation("E", "PASS", evidence="e", evaluator="eval-e", weight=100),
        ),
        evaluator_facts=(
            _fact("A", "B", "ab"),
            _fact("B", "A", "ba"),
            _fact("B", "C", "bc"),
            _fact("D", "C", "untrusted", trusted=False),
        ),
    )


def _proposal(
    objective_id: str,
    root_gap_id: str,
    evaluator_id: str,
    *,
    strategy_key: str | None = None,
    write_paths: tuple[str, ...] = ("product/work.py",),
    context_paths: tuple[str, ...] = ("product",),
    capabilities: tuple[str, ...] = (),
    expected_condition_ids: tuple[str, ...] | None = None,
    cost: int = 7,
    evaluator_seconds: int = 50,
) -> ObjectiveProposal:
    return ObjectiveProposal(
        objective_id=objective_id,
        title=f"Address {root_gap_id}",
        root_gap_id=root_gap_id,
        strategy_key=strategy_key or f"repair {root_gap_id}",
        context_paths=context_paths,
        write_paths=write_paths,
        capabilities=capabilities,
        evaluator_ids=(evaluator_id,),
        expected_condition_ids=expected_condition_ids or (root_gap_id,),
        estimated_cost_units=cost,
        estimated_context_bytes=100,
        estimated_write_bytes=100,
        estimated_worker_seconds=10,
        estimated_evaluator_seconds=evaluator_seconds,
    )


class GapGraphTests(unittest.TestCase):
    def test_graph_covers_every_non_pass_and_uses_only_trusted_current_facts(self) -> None:
        graph = GapGraph.from_goal_state(_goal_state())

        self.assertEqual(graph.condition_ids, ("A", "B", "C", "D"))
        self.assertEqual(
            {(edge.blocker_id, edge.blocked_id) for edge in graph.edges},
            {("A", "B"), ("B", "A"), ("B", "C")},
        )
        self.assertEqual(
            graph.strongly_connected_components(),
            (("A", "B"), ("C",), ("D",)),
        )

    def test_duplicate_fact_cannot_mint_a_new_evidence_basis(self) -> None:
        state = _goal_state()
        duplicate = GoalState(
            state.iteration,
            state.evaluations,
            (*state.evaluator_facts, state.evaluator_facts[0]),
        )

        self.assertEqual(state.evidence_basis_digest, duplicate.evidence_basis_digest)
        self.assertEqual(state.state_digest, duplicate.state_digest)

    def test_scc_roots_are_ranked_by_deterministic_reachable_impact(self) -> None:
        graph = GapGraph.from_goal_state(_goal_state())

        roots = graph.root_blockers()

        self.assertEqual([root.condition_ids for root in roots], [("A", "B"), ("D",)])
        self.assertEqual([root.impact_score for root in roots], [10, 1])
        self.assertEqual(roots[0].reachable_condition_ids, ("A", "B", "C"))
        reordered = GoalState(
            iteration=7,
            evaluations=tuple(reversed(_goal_state().evaluations)),
            evaluator_facts=tuple(reversed(_goal_state().evaluator_facts)),
        )
        self.assertEqual(graph.graph_digest, GapGraph.from_goal_state(reordered).graph_digest)
        self.assertEqual(roots, GapGraph.from_goal_state(reordered).root_blockers())

    def test_optional_gap_does_not_outrank_a_required_goal_blocker(self) -> None:
        optional = ConditionEvaluation(
            condition_id="optional",
            status="FAIL",
            evaluator_ids=("eval-optional",),
            evidence_digests=("optional-evidence",),
            trusted=True,
            current=True,
            required=False,
            impact_weight=100,
        )
        required = _evaluation(
            "required",
            "FAIL",
            evidence="required-evidence",
            evaluator="eval-required",
        )

        roots = GapGraph.from_goal_state(GoalState(0, (optional, required))).root_blockers()

        self.assertEqual([root.condition_ids for root in roots], [("required",), ("optional",)])
        self.assertEqual([root.impact_score for root in roots], [1, 0])

    def test_scc_analysis_is_iterative_for_large_contracts(self) -> None:
        count = 1_500
        evaluations = tuple(
            _evaluation(
                f"c{index:04d}",
                "FAIL",
                evidence=f"e{index}",
                evaluator="eval",
            )
            for index in range(count)
        )
        facts = tuple(
            _fact(f"c{index:04d}", f"c{index + 1:04d}", f"f{index}")
            for index in range(count - 1)
        )

        roots = GapGraph.from_goal_state(GoalState(0, evaluations, facts)).root_blockers()

        self.assertEqual(roots[0].condition_ids, ("c0000",))
        self.assertEqual(roots[0].impact_score, count)


class GoalDeltaTests(unittest.TestCase):
    def test_only_new_evaluator_proven_pass_is_material_progress(self) -> None:
        before = GoalState(0, (_evaluation("A", "FAIL", evidence="fail", evaluator="eval-a"),))
        proven = GoalState(1, (_evaluation("A", "PASS", evidence="pass", evaluator="eval-a"),))
        untrusted = GoalState(
            1,
            (_evaluation("A", "PASS", evidence="claim", evaluator="worker", trusted=False),),
        )

        self.assertEqual(compare_goal_states(before, proven).kind, DeltaKind.MATERIAL_PROGRESS)
        self.assertEqual(compare_goal_states(before, untrusted).kind, DeltaKind.NO_PROGRESS)

    def test_regression_dominates_a_simultaneous_local_gain(self) -> None:
        before = GoalState(
            0,
            (
                _evaluation("A", "PASS", evidence="pass-a", evaluator="eval-a"),
                _evaluation("B", "FAIL", evidence="fail-b", evaluator="eval-b"),
            ),
        )
        after = GoalState(
            1,
            (
                _evaluation("A", "FAIL", evidence="fail-a", evaluator="eval-a"),
                _evaluation("B", "PASS", evidence="pass-b", evaluator="eval-b"),
            ),
        )

        delta = compare_goal_states(before, after)

        self.assertEqual(delta.kind, DeltaKind.REGRESSION)
        self.assertEqual(delta.regressed_condition_ids, ("A",))
        self.assertEqual(delta.newly_proven_condition_ids, ("B",))

    def test_new_trusted_failure_fact_is_information_not_progress(self) -> None:
        evaluations = (
            _evaluation("A", "FAIL", evidence="a", evaluator="eval-a"),
            _evaluation("B", "BLOCKED", evidence="b", evaluator="eval-b"),
        )
        before = GoalState(0, evaluations)
        after = GoalState(1, evaluations, (_fact("A", "B", "new-causal-evidence"),))

        delta = compare_goal_states(before, after)

        self.assertEqual(delta.kind, DeltaKind.INFORMATION_GAIN)
        self.assertNotEqual(delta.before_gap_digest, delta.after_gap_digest)
        self.assertFalse(delta.should_retain_work)

    def test_iteration_or_reissued_identical_evidence_is_not_progress(self) -> None:
        evaluations = (_evaluation("A", "FAIL", evidence="same", evaluator="eval-a"),)
        self.assertEqual(
            compare_goal_states(GoalState(0, evaluations), GoalState(1, evaluations)).kind,
            DeltaKind.NO_PROGRESS,
        )


class PathLedgerTests(unittest.TestCase):
    def test_equivalent_strategy_is_rejected_until_new_evidence_reopens_it(self) -> None:
        first = StrategyDescriptor("A", "  Repair   Cache ", ("product/b.py", "product/a.py"))
        equivalent = StrategyDescriptor("A", "repair cache", ("product/a.py", "product/b.py"))
        ledger = PathLedger().record(
            first,
            evidence_basis_digest="basis-1",
            outcome=PathOutcome.NO_PROGRESS,
            iteration=1,
            objective_id="objective-1",
        )

        same = ledger.assess(equivalent, evidence_basis_digest="basis-1")
        reopened = ledger.assess(equivalent, evidence_basis_digest="basis-2")

        self.assertEqual(first.fingerprint, equivalent.fingerprint)
        self.assertEqual(same.decision, PathDecision.REJECT_EQUIVALENT_REPEAT)
        self.assertFalse(same.allowed)
        self.assertEqual(reopened.decision, PathDecision.REOPENED_WITH_NEW_EVIDENCE)
        self.assertTrue(reopened.allowed)
        self.assertEqual(PathLedger.from_list(ledger.as_list()), ledger)


class PlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = _contract()
        self.state = _goal_state()
        self.graph = GapGraph.from_goal_state(self.state)
        self.ledger = PathLedger()

    def test_valid_proposals_are_ranked_by_root_impact_before_cost(self) -> None:
        high_impact = _proposal("high", "A", "eval-a", cost=10)
        low_impact = _proposal("low", "D", "eval-d", cost=7)

        result = audit_and_rank(
            (low_impact, high_impact),
            contract=self.contract,
            graph=self.graph,
            ledger=self.ledger,
            evidence_basis_digest=self.state.evidence_basis_digest,
        )

        self.assertEqual([item.proposal.objective_id for item in result.ranked], ["high", "low"])
        self.assertFalse(result.rejected)

    def test_non_root_unmeasurable_and_out_of_bounds_proposals_fail_closed(self) -> None:
        proposal = _proposal(
            "bad",
            "C",
            "eval-a",
            context_paths=("secrets",),
            write_paths=("../escape", "checks/oracle.py"),
            capabilities=("host-admin",),
            expected_condition_ids=("D",),
        )

        audit = audit_proposal(
            proposal,
            contract=self.contract,
            graph=self.graph,
            ledger=self.ledger,
            evidence_basis_digest=self.state.evidence_basis_digest,
        )

        joined = "|".join(audit.reasons)
        self.assertIn("NOT_A_ROOT_GAP", joined)
        self.assertIn("ROOT_GAP_NOT_MEASURABLE", joined)
        self.assertIn("CONDITION_NOT_MEASURED:D", joined)
        self.assertIn("CONTEXT_OUT_OF_BOUNDS", joined)
        self.assertIn("WRITE_OUT_OF_BOUNDS", joined)
        self.assertIn("WRITE_OVERLAPS_PROTECTED_ROOT", joined)
        self.assertIn("CAPABILITY_OUT_OF_BOUNDS", joined)
        self.assertFalse(audit.accepted)

    def test_operator_approval_is_a_schedulable_state_not_a_hard_rejection(self) -> None:
        proposal = _proposal(
            "network",
            "A",
            "eval-a",
            capabilities=("network",),
            cost=9,
        )

        pending = audit_proposal(
            proposal,
            contract=self.contract,
            graph=self.graph,
            ledger=self.ledger,
            evidence_basis_digest=self.state.evidence_basis_digest,
        )
        approved = audit_proposal(
            proposal,
            contract=self.contract,
            graph=self.graph,
            ledger=self.ledger,
            evidence_basis_digest=self.state.evidence_basis_digest,
            limits=PlanningLimits(
                **{
                    **PlanningLimits.from_contract(self.contract).__dict__,
                    "approved_capabilities": ("network",),
                }
            ),
        )

        self.assertTrue(pending.accepted)
        self.assertTrue(pending.requires_operator_approval)
        self.assertEqual(pending.approval_required_capabilities, ("network",))
        self.assertTrue(approved.accepted)
        self.assertFalse(approved.requires_operator_approval)

    def test_declared_cost_and_runtime_budgets_are_enforced(self) -> None:
        underestimated = _proposal(
            "under",
            "A",
            "eval-network",
            capabilities=("network",),
            cost=4,
            evaluator_seconds=49,
        )
        limits = PlanningLimits(
            remaining_cost_units=3,
            remaining_context_bytes=10_000,
            remaining_write_bytes=5_000,
            remaining_worker_seconds=100,
            remaining_evaluator_seconds=50,
            remaining_capability_runs=0,
            remaining_operator_runs=2,
        )

        audit = audit_proposal(
            underestimated,
            contract=self.contract,
            graph=self.graph,
            ledger=self.ledger,
            evidence_basis_digest=self.state.evidence_basis_digest,
            limits=limits,
        )

        self.assertEqual(audit.minimum_cost_units, 9)
        self.assertIn("COST_ESTIMATE_BELOW_DECLARED_MINIMUM", audit.reasons)
        self.assertIn("EVALUATOR_TIME_ESTIMATE_BELOW_FULL_MILESTONE_PASS", audit.reasons)
        self.assertIn("COST_BUDGET_EXCEEDED", audit.reasons)
        self.assertIn("CAPABILITY_RUN_BUDGET_EXCEEDED", audit.reasons)

    def test_ledger_repeat_is_rejected_but_new_evidence_reopens_proposal(self) -> None:
        proposal = _proposal("repeat", "A", "eval-a")
        ledger = self.ledger.record(
            proposal.strategy,
            evidence_basis_digest="basis-1",
            outcome=PathOutcome.NO_PROGRESS,
            iteration=1,
            objective_id=proposal.objective_id,
        )

        repeated = audit_proposal(
            proposal,
            contract=self.contract,
            graph=self.graph,
            ledger=ledger,
            evidence_basis_digest="basis-1",
        )
        reopened = audit_proposal(
            proposal,
            contract=self.contract,
            graph=self.graph,
            ledger=ledger,
            evidence_basis_digest="basis-2",
        )

        self.assertIn("EQUIVALENT_PATH_ALREADY_TRIED", repeated.reasons)
        self.assertFalse(repeated.accepted)
        self.assertTrue(reopened.accepted)
        self.assertEqual(
            reopened.path_assessment.decision,
            PathDecision.REOPENED_WITH_NEW_EVIDENCE,
        )

    def test_same_round_equivalent_proposals_do_not_both_execute(self) -> None:
        first = _proposal("a", "A", "eval-a", strategy_key="repair A")
        duplicate = _proposal("b", "A", "eval-a", strategy_key=" REPAIR   a ")

        result = audit_and_rank(
            (duplicate, first),
            contract=self.contract,
            graph=self.graph,
            ledger=self.ledger,
            evidence_basis_digest=self.state.evidence_basis_digest,
        )

        self.assertEqual([item.proposal.objective_id for item in result.ranked], ["a"])
        self.assertEqual(result.rejected[0].proposal.objective_id, "b")
        self.assertIn("DUPLICATE_PROPOSAL_IN_ROUND", result.rejected[0].reasons)


if __name__ == "__main__":
    unittest.main()
