from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .models import (
    EvidenceRequirement,
    Milestone,
    SuccessCondition,
    TerminationConditions,
)


SCHEMA_VERSION = "controller-milestone-v1"
_ID = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,127}\Z", re.ASCII)
_FORBIDDEN_CONTROL_FIELDS = {
    "objective",
    "objectives",
    "plan",
    "planner",
    "worker",
    "reviewer",
    "dependencies",
    "depends_on",
    "profile",
    "gate",
    "implementation_order",
    "allowed_write_paths",
    "evaluator_command",
}


class ContractError(ValueError):
    pass


def load_milestone(path: Path) -> Milestone:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError, ContractError) as exc:
        raise ContractError(f"cannot load milestone {path}: {exc}") from exc
    return parse_milestone(raw)


def parse_milestone(raw: Any) -> Milestone:
    document = _object(raw, "milestone document")
    _exact_keys(
        document,
        {
            "schema_version",
            "milestone",
            "success_conditions",
            "evidence_requirements",
            "termination",
        },
        "milestone document",
    )
    _reject_control_fields(document)
    if document["schema_version"] != SCHEMA_VERSION:
        raise ContractError(f"unsupported milestone schema: {document['schema_version']!r}")

    identity = _object(document["milestone"], "milestone")
    _exact_keys(identity, {"id", "title", "goal"}, "milestone")
    milestone_id = _identifier(identity["id"], "milestone.id")
    title = _text(identity["title"], "milestone.title")
    goal = _text(identity["goal"], "milestone.goal")

    evidence = tuple(
        _parse_evidence(item, index)
        for index, item in enumerate(_array(document["evidence_requirements"], "evidence_requirements"))
    )
    conditions = tuple(
        _parse_condition(item, index)
        for index, item in enumerate(
            _array(document["success_conditions"], "success_conditions", nonempty=True)
        )
    )
    termination = _parse_termination(document["termination"])
    _unique_ids(conditions, "success condition")
    _unique_ids(evidence, "evidence requirement")
    overlap = {item.id for item in conditions}.intersection(item.id for item in evidence)
    if overlap:
        raise ContractError(f"condition and evidence ids must not overlap: {sorted(overlap)}")
    evidence_ids = {item.id for item in evidence}
    for condition in conditions:
        unknown = set(condition.evidence_requirement_ids) - evidence_ids
        if unknown:
            raise ContractError(
                f"success condition {condition.id!r} references unknown evidence: {sorted(unknown)}"
            )
    return Milestone(
        schema_version=SCHEMA_VERSION,
        id=milestone_id,
        title=title,
        goal=goal,
        success_conditions=conditions,
        evidence_requirements=evidence,
        termination=termination,
    )


def _parse_condition(raw: Any, index: int) -> SuccessCondition:
    location = f"success_conditions[{index}]"
    value = _object(raw, location)
    _exact_keys(value, {"id", "statement", "evidence_requirement_ids"}, location)
    return SuccessCondition(
        id=_identifier(value["id"], f"{location}.id"),
        statement=_text(value["statement"], f"{location}.statement"),
        evidence_requirement_ids=_ids(
            value["evidence_requirement_ids"], f"{location}.evidence_requirement_ids"
        ),
    )


def _parse_evidence(raw: Any, index: int) -> EvidenceRequirement:
    location = f"evidence_requirements[{index}]"
    value = _object(raw, location)
    _exact_keys(
        value,
        {
            "id",
            "statement",
            "kind",
            "source_id",
            "freshness_seconds",
            "provenance_required",
            "substitution_policy",
            "parameters",
        },
        location,
    )
    kind = value["kind"]
    if kind not in {"VERIFICATION", "REAL"}:
        raise ContractError(f"{location}.kind must be VERIFICATION or REAL")
    if value["provenance_required"] is not True:
        raise ContractError(f"{location}.provenance_required must be true")
    if value["substitution_policy"] != "FORBIDDEN":
        raise ContractError(f"{location}.substitution_policy must be FORBIDDEN")
    return EvidenceRequirement(
        id=_identifier(value["id"], f"{location}.id"),
        statement=_text(value["statement"], f"{location}.statement"),
        kind=kind,
        source_id=_identifier(value["source_id"], f"{location}.source_id"),
        freshness_seconds=_positive_int(
            value["freshness_seconds"], f"{location}.freshness_seconds"
        ),
        provenance_required=True,
        substitution_policy="FORBIDDEN",
        parameters=dict(_object(value["parameters"], f"{location}.parameters")),
    )


def _parse_termination(raw: Any) -> TerminationConditions:
    value = _object(raw, "termination")
    fields = {
        "max_iterations",
        "max_stagnant_iterations",
        "max_environment_retries",
        "max_no_plan_rounds",
        "max_wall_seconds",
    }
    _exact_keys(value, fields, "termination")
    parsed = {name: _positive_int(value[name], f"termination.{name}") for name in fields}
    return TerminationConditions(**parsed)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_control_fields(value: Any, location: str = "milestone document") -> None:
    if isinstance(value, Mapping):
        forbidden = sorted(set(value).intersection(_FORBIDDEN_CONTROL_FIELDS))
        if forbidden:
            raise ContractError(f"{location} contains runtime control fields: {forbidden}")
        for key, item in value.items():
            _reject_control_fields(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_control_fields(item, f"{location}[{index}]")


def _object(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{location} must be an object")
    return value


def _array(value: Any, location: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        qualifier = "nonempty " if nonempty else ""
        raise ContractError(f"{location} must be a {qualifier}array")
    return value


def _text(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{location} must be nonempty text")
    return value.strip()


def _identifier(value: Any, location: str) -> str:
    text = _text(value, location)
    if _ID.fullmatch(text) is None:
        raise ContractError(f"{location} must be an identifier")
    return text


def _ids(value: Any, location: str) -> tuple[str, ...]:
    values = tuple(_identifier(item, f"{location}[]") for item in _array(value, location))
    if len(values) != len(set(values)):
        raise ContractError(f"{location} must contain unique ids")
    return values


def _positive_int(value: Any, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{location} must be a positive integer")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], location: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ContractError(
            f"{location} fields differ: missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _unique_ids(values: tuple[Any, ...], label: str) -> None:
    ids = [item.id for item in values]
    if len(ids) != len(set(ids)):
        raise ContractError(f"duplicate {label} id")
