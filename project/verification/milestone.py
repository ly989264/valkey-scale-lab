from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from verification.catalog import GateError, ID_PATTERN, load_json_object


MILESTONE_ID_PATTERN = re.compile(r"^m[1-9][0-9]*$", re.ASCII)


@dataclass(frozen=True)
class MilestoneCheck:
    id: str
    parameters: Mapping[str, Any]
    parameters_declared: bool


@dataclass(frozen=True)
class Criterion:
    id: str
    statement: str
    checks: tuple[MilestoneCheck, ...] | None


@dataclass(frozen=True)
class Milestone:
    id: str
    goal: str
    criteria: tuple[Criterion, ...]

    @property
    def definition_status(self) -> str:
        return (
            "DEFINED"
            if any(criterion.checks is None for criterion in self.criteria)
            else "READY"
        )


def _require_exact_fields(
    value: Mapping[str, Any], required: set[str], location: str
) -> None:
    actual = set(value)
    if actual != required:
        missing = sorted(required - actual)
        extra = sorted(actual - required)
        details = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unexpected {extra}")
        raise GateError(f"{location} has invalid fields: {', '.join(details)}")


def _text(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateError(f"{location} must be non-empty text")
    return value.strip()


def _identifier(value: Any, location: str) -> str:
    if not isinstance(value, str) or ID_PATTERN.fullmatch(value) is None:
        raise GateError(f"{location} must be a lowercase identifier")
    return value


def load_milestone(path: Path, *, expected_id: str | None = None) -> Milestone:
    document = load_json_object(path)
    _require_exact_fields(document, {"id", "goal", "criteria"}, "milestone")
    milestone_id = document["id"]
    if (
        not isinstance(milestone_id, str)
        or MILESTONE_ID_PATTERN.fullmatch(milestone_id) is None
    ):
        raise GateError("milestone.id must use m followed by a positive integer")
    if expected_id is not None and milestone_id != expected_id:
        raise GateError(
            f"milestone id {milestone_id!r} does not match directory {expected_id!r}"
        )

    raw_criteria = document["criteria"]
    if not isinstance(raw_criteria, list) or not raw_criteria:
        raise GateError("milestone.criteria must be a non-empty array")
    criteria: list[Criterion] = []
    criterion_ids: set[str] = set()
    for criterion_index, raw_criterion in enumerate(raw_criteria):
        location = f"milestone.criteria[{criterion_index}]"
        if not isinstance(raw_criterion, dict):
            raise GateError(f"{location} must be an object")
        allowed = {"id", "statement", "check"}
        required = {"id", "statement"}
        missing = sorted(required - set(raw_criterion))
        extra = sorted(set(raw_criterion) - allowed)
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing {missing}")
            if extra:
                details.append(f"unexpected {extra}")
            raise GateError(f"{location} has invalid fields: {', '.join(details)}")
        criterion_id = _identifier(raw_criterion["id"], f"{location}.id")
        if criterion_id in criterion_ids:
            raise GateError(f"duplicate criterion id: {criterion_id}")
        criterion_ids.add(criterion_id)

        checks: tuple[MilestoneCheck, ...] | None = None
        if "check" in raw_criterion:
            raw_checks = raw_criterion["check"]
            if not isinstance(raw_checks, list) or not raw_checks:
                raise GateError(f"{location}.check must be a non-empty array when present")
            parsed_checks: list[MilestoneCheck] = []
            for check_index, raw_check in enumerate(raw_checks):
                check_location = f"{location}.check[{check_index}]"
                if not isinstance(raw_check, dict):
                    raise GateError(f"{check_location} must be an object")
                allowed_check_fields = {"id", "parameters"}
                if "id" not in raw_check or set(raw_check) - allowed_check_fields:
                    missing_check = [] if "id" in raw_check else ["id"]
                    extra_check = sorted(set(raw_check) - allowed_check_fields)
                    details = []
                    if missing_check:
                        details.append(f"missing {missing_check}")
                    if extra_check:
                        details.append(f"unexpected {extra_check}")
                    raise GateError(
                        f"{check_location} has invalid fields: {', '.join(details)}"
                    )
                parameters = raw_check.get("parameters", {})
                if not isinstance(parameters, dict):
                    raise GateError(f"{check_location}.parameters must be an object")
                parsed_checks.append(
                    MilestoneCheck(
                        _identifier(raw_check["id"], f"{check_location}.id"),
                        parameters,
                        "parameters" in raw_check,
                    )
                )
            checks = tuple(parsed_checks)
        criteria.append(
            Criterion(
                criterion_id,
                _text(raw_criterion["statement"], f"{location}.statement"),
                checks,
            )
        )
    return Milestone(
        milestone_id,
        _text(document["goal"], "milestone.goal"),
        tuple(criteria),
    )


def load_project_milestone(
    project_root: Path,
    milestone_id: str,
    *,
    milestones_root: Path | None = None,
) -> Milestone:
    if MILESTONE_ID_PATTERN.fullmatch(milestone_id) is None:
        raise GateError("milestone id must use m followed by a positive integer")
    root = milestones_root or project_root / "milestones"
    path = root / milestone_id / "milestone.json"
    return load_milestone(path, expected_id=milestone_id)
