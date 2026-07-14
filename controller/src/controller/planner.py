from __future__ import annotations

from pathlib import PurePosixPath
from typing import Iterable

from .history import FailureHistory
from .models import GoalState, Objective


class PlanError(ValueError):
    pass


def validate_objective(
    objective: Objective,
    *,
    goal_state: GoalState,
    history: FailureHistory,
    allowed_write_paths: tuple[str, ...],
    protected_paths: tuple[str, ...] = (),
) -> None:
    current_gaps = {item.id for item in goal_state.gaps}
    unknown = set(objective.target_gap_ids) - current_gaps
    if unknown:
        raise PlanError(f"objective targets non-current gaps: {sorted(unknown)}")
    for path in objective.write_paths:
        if not _safe_relative(path):
            raise PlanError(f"unsafe objective write path: {path}")
        if not _covered(path, allowed_write_paths):
            raise PlanError(f"objective write path is outside the allowlist: {path}")
        if _overlaps_any(path, protected_paths):
            raise PlanError(f"objective write path overlaps a protected path: {path}")
    if history.equivalent_failed(objective, goal_state):
        raise PlanError("equivalent path already failed for the current Goal State")


def normalize_paths(paths: Iterable[str]) -> tuple[str, ...]:
    values = tuple(sorted(set(paths)))
    for value in values:
        if not _safe_relative(value):
            raise PlanError(f"unsafe relative path: {value}")
    return values


def path_is_covered(path: str, roots: tuple[str, ...]) -> bool:
    return _covered(path, roots)


def path_overlaps_any(path: str, roots: tuple[str, ...]) -> bool:
    return _overlaps_any(path, roots)


def _safe_relative(raw: str) -> bool:
    if not raw or "\\" in raw:
        return False
    path = PurePosixPath(raw)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def _covered(path: str, roots: tuple[str, ...]) -> bool:
    candidate = PurePosixPath(path)
    return any(candidate == PurePosixPath(root) or candidate.is_relative_to(PurePosixPath(root)) for root in roots)


def _overlaps_any(path: str, roots: tuple[str, ...]) -> bool:
    candidate = PurePosixPath(path)
    return any(
        candidate == PurePosixPath(root)
        or candidate.is_relative_to(PurePosixPath(root))
        or PurePosixPath(root).is_relative_to(candidate)
        for root in roots
    )
