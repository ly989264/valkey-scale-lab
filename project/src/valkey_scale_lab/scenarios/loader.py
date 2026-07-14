from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    AdmissionSpec,
    ArtifactSpec,
    LegacyProfileBinding,
    LifecycleStep,
    ReportSurface,
    ScalePolicy,
    ScenarioDefinition,
    ScenarioSpec,
)
from .validation import validate_scenario_definition


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "scenario" / "gate_scenario.schema.json"
LOCAL_FULL_FLOW_DEFINITION_PATH = (
    Path(__file__).resolve().parent / "definitions" / "local_full_flow_v1.json"
)
CANONICAL_DEFINITION_PATH = LOCAL_FULL_FLOW_DEFINITION_PATH
LOCAL_FULL_FLOW_DEFINITION_ID = "local_full_flow"
LOCAL_FULL_FLOW_DEFINITION_VERSION = 1


class ScenarioDefinitionError(ValueError):
    def __init__(self, errors: tuple[str, ...]) -> None:
        self.errors = errors
        super().__init__("invalid scenario definition: " + "; ".join(errors))


def definition_digest(document: Mapping[str, Any]) -> str:
    payload = json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_scenario_definition(path: str | Path) -> ScenarioDefinition:
    source = Path(path)
    try:
        document = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ScenarioDefinitionError) as exc:
        if isinstance(exc, ScenarioDefinitionError):
            raise
        raise ScenarioDefinitionError((f"{source}: cannot load JSON definition: {exc}",)) from exc
    errors = validate_scenario_definition(document)
    if errors:
        raise ScenarioDefinitionError(errors)
    return _parse_definition(document)


@lru_cache(maxsize=1)
def load_local_full_flow_definition() -> ScenarioDefinition:
    definition = load_scenario_definition(LOCAL_FULL_FLOW_DEFINITION_PATH)
    if definition.digest != LOCAL_FULL_FLOW_DEFINITION_DIGEST:
        raise ScenarioDefinitionError(
            (
                "canonical local full-flow definition digest changed without updating its versioned digest",
            )
        )
    return definition


def _parse_definition(document: Mapping[str, Any]) -> ScenarioDefinition:
    lifecycle = tuple(
        LifecycleStep(
            id=row["id"],
            handler_id=row["handler_id"],
            depends_on=tuple(row["depends_on"]),
            always_run=row["always_run"],
            terminal=row["terminal"],
        )
        for row in document["lifecycle"]
    )

    def parse_scenarios(rows: list[dict[str, Any]]) -> tuple[ScenarioSpec, ...]:
        return tuple(
            ScenarioSpec(
                id=row["id"],
                handler_id=row["handler_id"],
                command_stream=row["command_stream"],
                operations=tuple(row["operations"]),
                parameters=row["parameters"],
            )
            for row in rows
        )

    artifacts: list[ArtifactSpec] = []
    for row in document["artifacts"]:
        admissions = tuple(
            AdmissionSpec(
                kind=admission["kind"],
                format=row["format"],
                source_raw_name=row["raw_name"],
                transform_id=admission.get("transform_id"),
                source_selector=admission.get("source_selector"),
            )
            for admission in row["admissions"]
        )
        artifacts.append(
            ArtifactSpec(
                raw_name=row["raw_name"],
                format=row["format"],
                admissions=admissions,
                required_raw=row["required_raw"],
            )
        )

    policy = document["scale_policy"]
    scale_policy = ScalePolicy(
        min_nodes=policy["min_nodes"],
        max_nodes=policy["max_nodes"],
        normal_development_cap=policy["normal_development_cap"],
        bounded_exception_scale=policy["bounded_exception_scale"],
        exact_requested_nodes=policy["exact_requested_nodes"],
        no_silent_downscale=policy["no_silent_downscale"],
        bounded_exception_requires_resource_preflight=policy[
            "bounded_exception_requires_resource_preflight"
        ],
        above_200_requires_operator_opt_in=policy[
            "above_200_requires_operator_opt_in"
        ],
        above_200_requires_resource_preflight=policy[
            "above_200_requires_resource_preflight"
        ],
        above_200_requires_cost_acknowledgement=policy[
            "above_200_requires_cost_acknowledgement"
        ],
    )
    legacy_profiles = tuple(
        LegacyProfileBinding(
            requested_nodes=row["requested_nodes"],
            runtime_phase=row["runtime_phase"],
            runtime_scenario=row["runtime_scenario"],
            config_template=row["config_template"],
        )
        for row in document["legacy_profiles"]
    )
    return ScenarioDefinition(
        schema_version=document["schema_version"],
        definition_id=document["definition_id"],
        version=document["version"],
        lifecycle_steps=lifecycle,
        management_scenarios=parse_scenarios(document["scenarios"]["management"]),
        fault_scenarios=parse_scenarios(document["scenarios"]["fault"]),
        management_execution_order=tuple(document["management_execution_order"]),
        artifacts=tuple(artifacts),
        report_surfaces=tuple(ReportSurface(id=item) for item in document["report_surfaces"]),
        scale_policy=scale_policy,
        legacy_profiles=legacy_profiles,
        legacy_projection_steps=tuple(document["legacy_projection_steps"]),
        digest=definition_digest(document),
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    duplicates: list[str] = []
    for key, item in pairs:
        if key in value:
            duplicates.append(key)
        value[key] = item
    if duplicates:
        raise ScenarioDefinitionError((f"duplicate JSON object keys: {sorted(set(duplicates))}",))
    return value


LOCAL_FULL_FLOW_DEFINITION_DIGEST = "02660b42dce250ccf8b64ea244d6673e3450eeceb45cba9568b46c9f4ee51921"
CANONICAL_DEFINITION_DIGEST = LOCAL_FULL_FLOW_DEFINITION_DIGEST
