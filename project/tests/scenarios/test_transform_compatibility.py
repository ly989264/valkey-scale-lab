from __future__ import annotations

import json
from copy import deepcopy

import pytest

from valkey_scale_lab.scenarios import (
    ADMISSION_COMPATIBILITY,
    LOCAL_FULL_FLOW_DEFINITION_PATH,
    TRANSFORM_COMPATIBILITY,
    validate_scenario_definition,
)


def _document() -> dict:
    return json.loads(LOCAL_FULL_FLOW_DEFINITION_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (
            lambda doc: doc["artifacts"][0]["admissions"][0].pop(
                "transform_id"
            ),
            "run_state_to_metadata",
        ),
        (
            lambda doc: doc["artifacts"][6]["admissions"][1].update(
                source_selector="other"
            ),
            "recovery_health",
        ),
        (
            lambda doc: doc["artifacts"][12].update(format="json"),
            "requires 'jsonl'",
        ),
        (
            lambda doc: doc["artifacts"][14]["admissions"][0].update(
                transform_id="normalize_timestamp"
            ),
            "incompatible",
        ),
    ],
)
def test_validator_enforces_transform_source_format_selector_and_kind(
    mutate, expected: str
) -> None:
    document = deepcopy(_document())
    mutate(document)

    errors = validate_scenario_definition(document)

    assert errors
    assert expected in "; ".join(errors)


def test_transform_compatibility_registry_is_exact_and_immutable() -> None:
    assert {
        (
            transform_id,
            rule.source_raw_name,
            rule.source_format,
            rule.source_selector,
            rule.admitted_kind,
        )
        for transform_id, rules in TRANSFORM_COMPATIBILITY.items()
        for rule in rules
    } == {
        (
            "run_state_to_metadata",
            "run_state.json",
            "json",
            None,
            "run_metadata",
        ),
        (
            "normalize_timestamp",
            "management_command_log.jsonl",
            "jsonl",
            None,
            "command_log",
        ),
        (
            "normalize_timestamp",
            "fault_command_log.jsonl",
            "jsonl",
            None,
            "fault_command_log",
        ),
        (
            "recovery_health",
            "fault_sequence.json",
            "json",
            "recovery_health",
            "stability_results",
        ),
    }
    with pytest.raises(TypeError):
        TRANSFORM_COMPATIBILITY["other"] = ()  # type: ignore[index]


@pytest.mark.parametrize(
    "source_index, target_index",
    [
        (2, 1),
        (14, 13),
        (15, 14),
    ],
)
def test_identity_admissions_cannot_move_while_global_kind_order_is_retained(
    source_index: int, target_index: int
) -> None:
    document = deepcopy(_document())
    admission = document["artifacts"][source_index]["admissions"].pop()
    document["artifacts"][target_index]["admissions"].append(admission)

    errors = validate_scenario_definition(document)

    assert errors
    assert "incompatible admission" in "; ".join(errors)


def test_admission_registry_covers_every_admitted_kind_including_identity() -> None:
    document = _document()
    admitted_kinds = {
        admission["kind"]
        for artifact in document["artifacts"]
        for admission in artifact["admissions"]
    }

    assert set(ADMISSION_COMPATIBILITY) == admitted_kinds
    assert {
        kind
        for kind, rule in ADMISSION_COMPATIBILITY.items()
        if rule.transform_id is None
    } == {
        "resource_preflight",
        "workload_windows",
        "lifecycle_timeline",
        "scenario_results",
        "management_results",
        "fault_results",
        "cleanup_report",
        "host_evidence",
        "analysis_summary",
        "report_index",
        "events",
        "metrics",
    }
    with pytest.raises(TypeError):
        ADMISSION_COMPATIBILITY["other"] = ADMISSION_COMPATIBILITY["events"]  # type: ignore[index]
