from __future__ import annotations

from typing import Any, Iterable

from .contracts import ArtifactRecord, RawCapture
from .manifest import canonical_json_digest


PROVENANCE_SCHEMA_VERSION = "valkey-scale-lab-evidence-provenance-v1"


def provenance_node_id(run_id: str, kind: str, source_sha256: str) -> str:
    return f"artifact-{canonical_json_digest([run_id, kind, source_sha256])[:24]}"


def build_provenance_document(
    capture: RawCapture,
    records: Iterable[ArtifactRecord],
) -> dict[str, Any]:
    rows = tuple(records)
    value: dict[str, Any] = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "run_id": capture.run_id,
        "definition_digest": capture.definition_digest,
        "capture_nodes": [
            {
                "id": f"raw-{artifact.sha256[:24]}",
                "path": f"runtime/{artifact.name}",
                "sha256": artifact.sha256,
            }
            for artifact in capture.artifacts
        ],
        "admission_nodes": [
            {
                "id": record.provenance_node_id,
                "kind": record.kind,
                "path": record.path,
                "sha256": record.sha256,
                "source_path": record.source_path,
                "source_sha256": record.source_sha256,
                "transform_id": record.transform_id,
            }
            for record in rows
        ],
    }
    value["provenance_digest"] = canonical_json_digest(value)
    return value

