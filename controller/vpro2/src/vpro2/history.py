from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping


class PathDecision(str, Enum):
    NEW_PATH = "NEW_PATH"
    REOPENED_WITH_NEW_EVIDENCE = "REOPENED_WITH_NEW_EVIDENCE"
    REJECT_EQUIVALENT_REPEAT = "REJECT_EQUIVALENT_REPEAT"


class PathOutcome(str, Enum):
    MATERIAL_PROGRESS = "MATERIAL_PROGRESS"
    INFORMATION_GAIN = "INFORMATION_GAIN"
    NO_PROGRESS = "NO_PROGRESS"
    REGRESSION = "REGRESSION"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class StrategyDescriptor:
    """Semantic inputs used to identify an implementation path.

    Objective ids, titles, strategy labels, estimates, context expansion and
    evaluator ordering are intentionally excluded. Changing presentation must
    not create a fresh attempt budget for an equivalent action. A materially
    different tactic against the same root and write authority therefore needs
    new evaluator evidence before the fail-closed ledger will reopen it.
    """

    root_gap_id: str
    strategy_key: str
    write_paths: tuple[str, ...]
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.root_gap_id or not self.strategy_key.strip():
            raise ValueError("a strategy requires a root gap and stable strategy key")
        object.__setattr__(self, "strategy_key", _normalize_text(self.strategy_key))
        object.__setattr__(self, "write_paths", _normalize_paths(self.write_paths))
        object.__setattr__(self, "capabilities", tuple(sorted(set(self.capabilities))))

    @property
    def fingerprint(self) -> str:
        value = {
            "root_gap_id": self.root_gap_id,
            "write_paths": self.write_paths,
            "capabilities": self.capabilities,
        }
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PathAttempt:
    fingerprint: str
    evidence_basis_digest: str
    outcome: PathOutcome
    iteration: int
    objective_id: str

    def __post_init__(self) -> None:
        if not self.fingerprint or not self.evidence_basis_digest or not self.objective_id:
            raise ValueError("path attempts require fingerprint, evidence basis, and objective id")
        if self.iteration < 0:
            raise ValueError("path attempt iteration must not be negative")

    def as_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "evidence_basis_digest": self.evidence_basis_digest,
            "outcome": self.outcome.value,
            "iteration": self.iteration,
            "objective_id": self.objective_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PathAttempt":
        return cls(
            fingerprint=str(value["fingerprint"]),
            evidence_basis_digest=str(value["evidence_basis_digest"]),
            outcome=PathOutcome(str(value["outcome"])),
            iteration=int(value["iteration"]),
            objective_id=str(value["objective_id"]),
        )


@dataclass(frozen=True)
class PathAssessment:
    decision: PathDecision
    fingerprint: str
    previous_attempts: tuple[PathAttempt, ...]

    @property
    def allowed(self) -> bool:
        return self.decision is not PathDecision.REJECT_EQUIVALENT_REPEAT


@dataclass(frozen=True)
class PathLedger:
    attempts: tuple[PathAttempt, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempts", tuple(self.attempts))

    def as_list(self) -> list[dict[str, Any]]:
        return [attempt.as_dict() for attempt in self.attempts]

    @classmethod
    def from_list(cls, values: Iterable[Mapping[str, Any]]) -> "PathLedger":
        return cls(tuple(PathAttempt.from_dict(value) for value in values))

    def assess(
        self,
        strategy: StrategyDescriptor,
        *,
        evidence_basis_digest: str,
    ) -> PathAssessment:
        if not evidence_basis_digest:
            raise ValueError("path assessment requires a current trusted evidence basis")
        fingerprint = strategy.fingerprint
        previous = tuple(item for item in self.attempts if item.fingerprint == fingerprint)
        if not previous:
            decision = PathDecision.NEW_PATH
        elif evidence_basis_digest not in {item.evidence_basis_digest for item in previous}:
            decision = PathDecision.REOPENED_WITH_NEW_EVIDENCE
        else:
            decision = PathDecision.REJECT_EQUIVALENT_REPEAT
        return PathAssessment(decision, fingerprint, previous)

    def record(
        self,
        strategy: StrategyDescriptor,
        *,
        evidence_basis_digest: str,
        outcome: PathOutcome | str,
        iteration: int,
        objective_id: str,
    ) -> "PathLedger":
        parsed_outcome = outcome if isinstance(outcome, PathOutcome) else PathOutcome(outcome)
        attempt = PathAttempt(
            fingerprint=strategy.fingerprint,
            evidence_basis_digest=evidence_basis_digest,
            outcome=parsed_outcome,
            iteration=iteration,
            objective_id=objective_id,
        )
        return PathLedger((*self.attempts, attempt))


def strategy_fingerprint(strategy: StrategyDescriptor) -> str:
    return strategy.fingerprint


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _normalize_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    normalized = []
    for raw in paths:
        path = PurePosixPath(raw)
        normalized.append(path.as_posix())
    return tuple(sorted(set(normalized)))
