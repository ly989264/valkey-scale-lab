from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CheckDefinition:
    id: str
    level: int
    command: tuple[str, ...]
    timeout_seconds: int
    inputs: tuple[str, ...]
    digest_mode: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.id,
            "level": self.level,
            "command": list(self.command),
            "timeout_seconds": self.timeout_seconds,
            "inputs": list(self.inputs),
        }
        if self.digest_mode is not None:
            value["digest_mode"] = self.digest_mode
        return value


@dataclass(frozen=True)
class ObjectiveDefinition:
    id: str
    title: str
    depends_on: tuple[str, ...]
    clauses: tuple[str, ...]
    context_paths: tuple[str, ...]
    checks: tuple[CheckDefinition, ...]


@dataclass(frozen=True)
class GoalDefinition:
    schema_version: str
    goal_id: str
    goal: str
    scope_freeze: dict[str, Any]
    controller_policy: dict[str, Any]
    common_checks: tuple[CheckDefinition, ...]
    closure_checks: tuple[CheckDefinition, ...]
    evaluator_guard_checks: tuple[CheckDefinition, ...]
    kernel_manifest_path: str
    evaluator_paths: tuple[str, ...]
    evaluator_repair_paths: tuple[str, ...]
    product_roots: tuple[str, ...]
    product_excludes: tuple[str, ...]
    objectives: tuple[ObjectiveDefinition, ...]

    def objective(self, objective_id: str) -> ObjectiveDefinition:
        for objective in self.objectives:
            if objective.id == objective_id:
                return objective
        raise KeyError(objective_id)


@dataclass(frozen=True)
class KernelManifest:
    manifest_path: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class MigrationReceipt:
    source_state_path: str
    source_state_sha256: str
    source_control_sha256: str
    source_kernel_sha256: str
    source_evaluator_sha256: str
    source_last_event_hash: str
    evidence: tuple[dict[str, Any], ...]
