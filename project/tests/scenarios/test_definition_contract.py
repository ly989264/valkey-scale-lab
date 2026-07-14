from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from valkey_scale_lab.scenarios import (
    HANDLER_REGISTRY,
    LOCAL_FULL_FLOW_DEFINITION_DIGEST,
    LOCAL_FULL_FLOW_DEFINITION_PATH,
    SCENARIO_SCHEMA_PATH,
    TRANSFORM_REGISTRY,
    ScenarioDefinitionError,
    definition_digest,
    load_local_full_flow_definition,
    load_scenario_definition,
    validate_scenario_definition,
)


def _document() -> dict:
    return json.loads(LOCAL_FULL_FLOW_DEFINITION_PATH.read_text(encoding="utf-8"))


def test_canonical_definition_is_schema_backed_typed_and_immutable() -> None:
    schema = json.loads(SCENARIO_SCHEMA_PATH.read_text(encoding="utf-8"))
    definition = load_local_full_flow_definition()

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert definition.digest == LOCAL_FULL_FLOW_DEFINITION_DIGEST
    assert definition.digest == definition_digest(_document())
    assert definition.lifecycle_steps[-1].id == "cleanup"
    assert definition.lifecycle_steps[-1].terminal is True
    assert definition.lifecycle_steps[-1].always_run is True
    assert all(not step.terminal for step in definition.lifecycle_steps[:-1])
    assert definition.schema_version == "gate-scenario-v3"
    assert definition.definition_id == "local_full_flow"
    assert definition.scale_policy.min_nodes == 30
    assert definition.scale_policy.max_nodes == 2000
    assert definition.raw_json_artifacts[-1].raw_name == "full_flow_result.json"
    assert definition.raw_json_artifacts[-1].admitted_kinds == ()

    with pytest.raises(FrozenInstanceError):
        definition.version = 2  # type: ignore[misc]
    with pytest.raises(TypeError):
        definition.fault_scenarios[4].parameters["delay_ms"] = 1  # type: ignore[index]


def test_digest_is_independent_of_json_key_order_and_whitespace() -> None:
    document = _document()
    reordered = dict(reversed(tuple(document.items())))
    assert definition_digest(document) == definition_digest(reordered)


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda doc: doc["lifecycle"].reverse(), "exact order"),
        (lambda doc: doc["lifecycle"][1].update(depends_on=["report"]), "linear DAG"),
        (lambda doc: doc["lifecycle"][-1].update(terminal=False), "terminal"),
        (lambda doc: doc["scenarios"]["fault"][0].update(id="network_loss"), "exact order"),
        (lambda doc: doc["scenarios"]["fault"][0].update(command_stream="command_log"), "fault_command_log"),
        (lambda doc: doc["scenarios"]["fault"][0].update(handler_id="plugin.arbitrary"), "unregistered"),
        (lambda doc: doc["scenarios"]["fault"][4]["parameters"].update(delay_ms=1), "closed handler parameters"),
        (lambda doc: doc["artifacts"][0].update(raw_name="../run_state.json"), "unsafe artifact path"),
        (lambda doc: doc["artifacts"][0]["admissions"][0].update(transform_id="arbitrary"), "unknown closed transform"),
        (lambda doc: doc["report_surfaces"].reverse(), "exact order"),
        (lambda doc: doc["scale_policy"].update(min_nodes=29), "expected 30"),
        (lambda doc: doc.update(unknown=True), "unknown keys"),
    ],
)
def test_semantic_validator_rejects_unsafe_or_noncanonical_content(
    mutate, expected: str
) -> None:
    document = deepcopy(_document())
    mutate(document)
    errors = validate_scenario_definition(document)
    assert errors
    assert expected in "; ".join(errors)


def test_loader_rejects_duplicate_json_object_keys(tmp_path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":"gate-scenario-v3","schema_version":"v3"}', encoding="utf-8")
    with pytest.raises(ScenarioDefinitionError, match="duplicate JSON object keys"):
        load_scenario_definition(path)


def test_validator_rejects_incompatible_known_artifact_transform() -> None:
    document = deepcopy(_document())
    document["artifacts"][0]["admissions"][0]["transform_id"] = "normalize_timestamp"

    errors = validate_scenario_definition(document)

    assert errors
    assert "run_state_to_metadata" in "; ".join(errors)


def test_handler_and_transform_registries_are_closed_and_executable() -> None:
    assert HANDLER_REGISTRY["product.cleanup"] == "lifecycle"
    assert "arbitrary" not in HANDLER_REGISTRY
    assert set(TRANSFORM_REGISTRY) == {
        "run_state_to_metadata",
        "normalize_timestamp",
        "recovery_health",
    }
    assert TRANSFORM_REGISTRY["normalize_timestamp"](
        {"ended_at_unix_ms": 123}
    )["timestamp_unix_ms"] == 123
