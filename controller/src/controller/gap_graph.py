from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable


PASS = "PASS"
BLOCKS = "BLOCKS"


def _digest(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ConditionEvaluation:
    """The evaluator-owned current result for one immutable success condition."""

    condition_id: str
    status: str
    evaluator_ids: tuple[str, ...] = ()
    evidence_digests: tuple[str, ...] = ()
    trusted: bool = False
    current: bool = False
    required: bool = True
    impact_weight: int = 1

    def __post_init__(self) -> None:
        if not self.condition_id:
            raise ValueError("condition_id must not be empty")
        if not self.status:
            raise ValueError("condition status must not be empty")
        if self.impact_weight < 1:
            raise ValueError("impact_weight must be positive")
        object.__setattr__(self, "status", self.status.upper())
        object.__setattr__(self, "evaluator_ids", tuple(sorted(set(self.evaluator_ids))))
        object.__setattr__(self, "evidence_digests", tuple(sorted(set(self.evidence_digests))))

    @property
    def is_proven_pass(self) -> bool:
        return (
            self.status == PASS
            and self.trusted
            and self.current
            and bool(self.evaluator_ids)
            and bool(self.evidence_digests)
        )


@dataclass(frozen=True)
class EvaluatorFact:
    """A current evaluator assertion that one condition blocks another."""

    evaluator_id: str
    relation: str
    source_condition_id: str
    target_condition_id: str
    evidence_digest: str
    trusted: bool = True
    current: bool = True

    def __post_init__(self) -> None:
        if not self.evaluator_id or not self.source_condition_id or not self.target_condition_id:
            raise ValueError("evaluator facts require an evaluator and two condition ids")
        if self.source_condition_id == self.target_condition_id:
            raise ValueError("a condition cannot directly block itself")
        if not self.evidence_digest:
            raise ValueError("evaluator facts require evidence")
        object.__setattr__(self, "relation", self.relation.upper())

    @property
    def is_admissible_block(self) -> bool:
        return self.relation == BLOCKS and self.trusted and self.current


@dataclass(frozen=True)
class GoalState:
    """A complete milestone evaluation snapshot, not a worker self-report."""

    iteration: int
    evaluations: tuple[ConditionEvaluation, ...]
    evaluator_facts: tuple[EvaluatorFact, ...] = ()

    def __post_init__(self) -> None:
        if self.iteration < 0:
            raise ValueError("iteration must not be negative")
        ids = [evaluation.condition_id for evaluation in self.evaluations]
        if len(ids) != len(set(ids)):
            raise ValueError("goal state contains duplicate condition evaluations")
        object.__setattr__(
            self,
            "evaluations",
            tuple(sorted(self.evaluations, key=lambda item: item.condition_id)),
        )
        object.__setattr__(
            self,
            "evaluator_facts",
            tuple(
                sorted(
                    set(self.evaluator_facts),
                    key=lambda item: (
                        item.source_condition_id,
                        item.target_condition_id,
                        item.evaluator_id,
                        item.evidence_digest,
                    ),
                )
            ),
        )

    def evaluation(self, condition_id: str) -> ConditionEvaluation:
        for evaluation in self.evaluations:
            if evaluation.condition_id == condition_id:
                return evaluation
        raise KeyError(condition_id)

    @property
    def evidence_basis_digest(self) -> str:
        return _digest(
            {
                "conditions": [
                    {
                        "condition_id": item.condition_id,
                        "status": item.status,
                        "evaluator_ids": item.evaluator_ids,
                        "evidence_digests": item.evidence_digests,
                    }
                    for item in self.evaluations
                    if item.trusted and item.current and item.evidence_digests
                ],
                "facts": [
                    {
                        "evaluator_id": fact.evaluator_id,
                        "relation": fact.relation,
                        "source": fact.source_condition_id,
                        "target": fact.target_condition_id,
                        "evidence_digest": fact.evidence_digest,
                    }
                    for fact in self.evaluator_facts
                    if fact.trusted and fact.current
                ],
            }
        )

    @property
    def state_digest(self) -> str:
        return _digest(
            {
                "evaluations": [
                    {
                        "condition_id": item.condition_id,
                        "status": item.status,
                        "evaluator_ids": item.evaluator_ids,
                        "evidence_digests": item.evidence_digests,
                        "trusted": item.trusted,
                        "current": item.current,
                        "required": item.required,
                        "impact_weight": item.impact_weight,
                    }
                    for item in self.evaluations
                ],
                "facts": [fact.__dict__ for fact in self.evaluator_facts],
            }
        )


@dataclass(frozen=True)
class GapNode:
    condition_id: str
    status: str
    required: bool
    impact_weight: int


@dataclass(frozen=True)
class GapEdge:
    blocker_id: str
    blocked_id: str
    evaluator_id: str
    evidence_digest: str


@dataclass(frozen=True)
class RootBlocker:
    condition_ids: tuple[str, ...]
    impact_score: int
    reachable_condition_ids: tuple[str, ...]


@dataclass(frozen=True)
class GapGraph:
    nodes: tuple[GapNode, ...]
    edges: tuple[GapEdge, ...]

    @classmethod
    def from_goal_state(cls, goal_state: GoalState) -> "GapGraph":
        nodes = tuple(
            GapNode(
                evaluation.condition_id,
                evaluation.status,
                evaluation.required,
                evaluation.impact_weight,
            )
            for evaluation in goal_state.evaluations
            if evaluation.status != PASS
        )
        gap_ids = {node.condition_id for node in nodes}
        edges = {
            GapEdge(
                fact.source_condition_id,
                fact.target_condition_id,
                fact.evaluator_id,
                fact.evidence_digest,
            )
            for fact in goal_state.evaluator_facts
            if fact.is_admissible_block
            and fact.source_condition_id in gap_ids
            and fact.target_condition_id in gap_ids
        }
        return cls(
            nodes=tuple(sorted(nodes, key=lambda item: item.condition_id)),
            edges=tuple(
                sorted(
                    edges,
                    key=lambda item: (
                        item.blocker_id,
                        item.blocked_id,
                        item.evaluator_id,
                        item.evidence_digest,
                    ),
                )
            ),
        )

    @property
    def condition_ids(self) -> tuple[str, ...]:
        return tuple(node.condition_id for node in self.nodes)

    @property
    def graph_digest(self) -> str:
        return _digest(
            {
                "nodes": [node.__dict__ for node in self.nodes],
                "edges": [edge.__dict__ for edge in self.edges],
            }
        )

    def strongly_connected_components(self) -> tuple[tuple[str, ...], ...]:
        adjacency = self._adjacency()
        reverse: dict[str, list[str]] = {node: [] for node in adjacency}
        for source, targets in adjacency.items():
            for target in targets:
                reverse[target].append(source)

        visited: set[str] = set()
        finish_order: list[str] = []
        for start in sorted(adjacency):
            if start in visited:
                continue
            visited.add(start)
            pending: list[tuple[str, bool]] = [(start, False)]
            while pending:
                node, expanded = pending.pop()
                if expanded:
                    finish_order.append(node)
                    continue
                pending.append((node, True))
                for target in reversed(adjacency[node]):
                    if target not in visited:
                        visited.add(target)
                        pending.append((target, False))

        components: list[tuple[str, ...]] = []
        assigned: set[str] = set()
        for start in reversed(finish_order):
            if start in assigned:
                continue
            members: list[str] = []
            pending = [start]
            assigned.add(start)
            while pending:
                node = pending.pop()
                members.append(node)
                for source in sorted(reverse[node], reverse=True):
                    if source not in assigned:
                        assigned.add(source)
                        pending.append(source)
            components.append(tuple(sorted(members)))
        return tuple(sorted(components))

    def root_blockers(self) -> tuple[RootBlocker, ...]:
        components = self.strongly_connected_components()
        if not components:
            return ()
        component_by_node = {
            node: index for index, component in enumerate(components) for node in component
        }
        outgoing: dict[int, set[int]] = {index: set() for index in range(len(components))}
        incoming: dict[int, set[int]] = {index: set() for index in range(len(components))}
        for edge in self.edges:
            source = component_by_node[edge.blocker_id]
            target = component_by_node[edge.blocked_id]
            if source == target:
                continue
            outgoing[source].add(target)
            incoming[target].add(source)
        weights = {
            node.condition_id: node.impact_weight if node.required else 0
            for node in self.nodes
        }
        roots: list[RootBlocker] = []
        for component_id, members in enumerate(components):
            if incoming[component_id]:
                continue
            reachable_components = _reachable(component_id, outgoing)
            reachable_nodes = tuple(
                sorted(
                    node
                    for reachable_component in reachable_components
                    for node in components[reachable_component]
                )
            )
            roots.append(
                RootBlocker(
                    condition_ids=members,
                    impact_score=sum(weights[node] for node in reachable_nodes),
                    reachable_condition_ids=reachable_nodes,
                )
            )
        return tuple(
            sorted(
                roots,
                key=lambda item: (-item.impact_score, item.condition_ids),
            )
        )

    @property
    def root_condition_ids(self) -> tuple[str, ...]:
        return tuple(
            condition_id
            for blocker in self.root_blockers()
            for condition_id in blocker.condition_ids
        )

    def impact_for_root(self, condition_id: str) -> int:
        for blocker in self.root_blockers():
            if condition_id in blocker.condition_ids:
                return blocker.impact_score
        raise KeyError(condition_id)

    def _adjacency(self) -> dict[str, tuple[str, ...]]:
        targets: dict[str, set[str]] = {node.condition_id: set() for node in self.nodes}
        for edge in self.edges:
            targets[edge.blocker_id].add(edge.blocked_id)
        return {node: tuple(sorted(values)) for node, values in targets.items()}


def build_gap_graph(goal_state: GoalState) -> GapGraph:
    return GapGraph.from_goal_state(goal_state)


def _reachable(start: int, outgoing: dict[int, set[int]]) -> set[int]:
    found: set[int] = set()
    pending = [start]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(sorted(outgoing[current], reverse=True))
    return found


def non_pass_condition_ids(evaluations: Iterable[ConditionEvaluation]) -> tuple[str, ...]:
    return tuple(sorted(item.condition_id for item in evaluations if item.status != PASS))
