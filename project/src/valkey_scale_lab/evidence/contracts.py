from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Tuple

from valkey_scale_lab.scenarios.contracts import ScenarioDefinition


def freeze_json(value: Any) -> Any:
    """Recursively freeze JSON-compatible values at the validation boundary."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    return value


class MissingStatus(str, Enum):
    MISSING = "MISSING"
    SKIPPED_WITH_REASON = "SKIPPED_WITH_REASON"
    UNSUPPORTED_WITH_REASON = "UNSUPPORTED_WITH_REASON"


MISSING_STATUSES = tuple(status.value for status in MissingStatus)


@dataclass(frozen=True)
class RunTiming:
    started_unix_ms: int
    ended_unix_ms: int

    def __post_init__(self) -> None:
        if isinstance(self.started_unix_ms, bool) or not isinstance(
            self.started_unix_ms, int
        ):
            raise ValueError("started_unix_ms must be an integer")
        if isinstance(self.ended_unix_ms, bool) or not isinstance(
            self.ended_unix_ms, int
        ):
            raise ValueError("ended_unix_ms must be an integer")
        if self.ended_unix_ms < self.started_unix_ms:
            raise ValueError("ended_unix_ms must not precede started_unix_ms")


@dataclass(frozen=True)
class EvidenceBundleSpec:
    schema_version: str
    definition_id: str
    definition_version: int
    definition_digest: str
    raw_artifact_names: Tuple[str, ...]
    required_raw_artifact_names: Tuple[str, ...]
    admitted_artifact_kinds: Tuple[str, ...]
    json_artifact_kinds: Tuple[str, ...]
    jsonl_artifact_kinds: Tuple[str, ...]
    lifecycle_ids: Tuple[str, ...]
    management_scenario_ids: Tuple[str, ...]
    fault_scenario_ids: Tuple[str, ...]
    report_surface_ids: Tuple[str, ...]
    raw_formats: Mapping[str, str] = dataclasses.field(
        default_factory=lambda: MappingProxyType({})
    )
    admission_sources: Mapping[str, str] = dataclasses.field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_formats", freeze_json(self.raw_formats))
        object.__setattr__(
            self, "admission_sources", freeze_json(self.admission_sources)
        )

    @classmethod
    def from_definition(cls, definition: ScenarioDefinition) -> "EvidenceBundleSpec":
        raw_formats = {
            artifact.raw_name: artifact.format for artifact in definition.artifacts
        }
        admission_sources = {
            admission.kind: artifact.raw_name
            for artifact in definition.artifacts
            for admission in artifact.admissions
        }
        json_kinds = tuple(
            admission.kind
            for artifact in definition.artifacts
            if artifact.format == "json"
            for admission in artifact.admissions
        )
        jsonl_kinds = tuple(
            admission.kind
            for artifact in definition.artifacts
            if artifact.format == "jsonl"
            for admission in artifact.admissions
        )
        return cls(
            schema_version="valkey-scale-lab-evidence-spec-v1",
            definition_id=definition.definition_id,
            definition_version=definition.version,
            definition_digest=definition.digest,
            raw_artifact_names=definition.raw_artifact_names,
            required_raw_artifact_names=tuple(
                artifact.raw_name
                for artifact in definition.artifacts
                if artifact.required_raw
            ),
            admitted_artifact_kinds=definition.admitted_artifact_ids,
            json_artifact_kinds=json_kinds,
            jsonl_artifact_kinds=jsonl_kinds,
            lifecycle_ids=definition.lifecycle_ids,
            management_scenario_ids=definition.management_ids,
            fault_scenario_ids=definition.fault_ids,
            report_surface_ids=definition.report_ids,
            raw_formats=raw_formats,
            admission_sources=admission_sources,
        )


@dataclass(frozen=True)
class RawArtifact:
    name: str
    path: Path
    format: str
    sha256: str
    run_id: str


@dataclass(frozen=True)
class RawCapture:
    root: Path
    run_id: str
    requested_nodes: int
    observed_nodes: int
    definition_digest: str
    artifacts: Tuple[RawArtifact, ...]


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    kind: str
    path: str
    format: str
    sha256: str
    source_path: str
    source_sha256: str
    transform_id: str | None
    provenance_node_id: str


@dataclass(frozen=True)
class ValidatedEvidenceBundle:
    root: Path
    run_id: str
    run_nonce: str
    requested_nodes: int
    observed_nodes: int
    definition_digest: str
    product_digest: str
    admission_digest: str
    artifacts: Tuple[ArtifactRecord, ...]
    admission: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "admission", freeze_json(self.admission))


class EvidenceValidationError(ValueError):
    def __init__(self, errors: Tuple[str, ...] | list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("invalid evidence: " + "; ".join(self.errors))

