from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .contracts import EvidenceBundleSpec, RawArtifact, RawCapture


CAPTURE_MANIFEST_SCHEMA_VERSION = "valkey-scale-lab-capture-manifest-v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_digest(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def inspect_raw_capture(
    base: Path,
    requested_nodes: int,
    spec: EvidenceBundleSpec,
) -> RawCapture:
    root = Path(base).resolve()
    runtime = root / "runtime"
    run_state = json.loads((runtime / "run_state.json").read_text(encoding="utf-8"))
    run_id = str(run_state["run_id"])
    observed_nodes = int(run_state["node_count"])
    artifacts = tuple(
        RawArtifact(
            name=name,
            path=runtime / name,
            format=spec.raw_formats[name],
            sha256=sha256_file(runtime / name),
            run_id=run_id,
        )
        for name in spec.raw_artifact_names
    )
    return RawCapture(
        root=root,
        run_id=run_id,
        requested_nodes=requested_nodes,
        observed_nodes=observed_nodes,
        definition_digest=spec.definition_digest,
        artifacts=artifacts,
    )


def capture_manifest(capture: RawCapture, *, run_owner: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": CAPTURE_MANIFEST_SCHEMA_VERSION,
        "run_id": capture.run_id,
        "requested_nodes": capture.requested_nodes,
        "observed_nodes": capture.observed_nodes,
        "definition_digest": capture.definition_digest,
        "artifacts": [
            {
                "name": artifact.name,
                "path": f"runtime/{artifact.name}",
                "format": artifact.format,
                "sha256": artifact.sha256,
                "run_id": artifact.run_id,
            }
            for artifact in capture.artifacts
        ],
    }
    if run_owner is not None:
        value["run_owner"] = run_owner
    value["capture_digest"] = canonical_json_digest(value)
    return value

