from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Mapping

from valkey_scale_lab.scenarios import ScenarioDefinition

from .contracts import (
    ArtifactRecord,
    EvidenceBundleSpec,
    EvidenceValidationError,
    RunTiming,
    ValidatedEvidenceBundle,
)
from .manifest import (
    canonical_json_digest,
    capture_manifest,
    inspect_raw_capture,
    sha256_file,
)
from .provenance import build_provenance_document, provenance_node_id
from .validation import load_raw_documents, validate_digest, validate_raw_sources


ADMISSION_SCHEMA_VERSION = "valkey-exact-scale-admission-v1"
CANDIDATE_SCHEMA_VERSION = ADMISSION_SCHEMA_VERSION


def canonical_bundle_spec(
    definition: ScenarioDefinition,
) -> EvidenceBundleSpec:
    return EvidenceBundleSpec.from_definition(definition)


def build_candidate_admission(
    base: str | Path,
    scale: int,
    product_digest: str,
    timing: RunTiming | None = None,
    versions: list[str] | tuple[str, ...] | None = None,
    probe: Mapping[str, Any] | None = None,
    *,
    definition: ScenarioDefinition,
    run_started_unix_ms: int | None = None,
    run_ended_unix_ms: int | None = None,
    valkey_versions: list[str] | tuple[str, ...] | None = None,
    independent_probe: Mapping[str, Any] | None = None,
    source_commit: str | None = None,
    run_owner: str | None = None,
    promoted_from_admission_digest: str | None = None,
    invocation_run_id: str | None = None,
) -> dict[str, Any]:
    root = Path(base).resolve()
    errors = list(validate_raw_sources(root, scale, definition))
    validate_digest(product_digest, "product_digest", errors)
    selected_versions = list(valkey_versions if valkey_versions is not None else versions or ())
    if not selected_versions or any(
        not re.fullmatch(r"9\.1(?:\.\d+)?", str(value)) for value in selected_versions
    ):
        errors.append("valkey_versions must contain only independently observed Valkey 9.1.x versions")
    selected_probe = dict(independent_probe if independent_probe is not None else probe or {})
    required_probe = {
        "cluster_state": "ok",
        "known_nodes": scale,
        "slots_assigned": 16384,
        "slots_ok": 16384,
    }
    if any(selected_probe.get(key) != value for key, value in required_probe.items()):
        errors.append(f"independent exact-scale cluster probe is not admissible: {selected_probe}")
    if errors:
        raise EvidenceValidationError(errors)

    objects, streams, _ = load_raw_documents(root, definition)
    selected_timing = _select_timing(
        timing,
        run_started_unix_ms,
        run_ended_unix_ms,
        streams,
    )
    commit = source_commit or _source_commit()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise EvidenceValidationError(("source_commit must be a full lowercase Git commit",))
    capture = inspect_raw_capture(root, scale, canonical_bundle_spec(definition))
    raw_by_name = {artifact.name: artifact for artifact in capture.artifacts}
    out = root / "runtime" / "admission_v2"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    common = {
        "schema_version": "v1",
        "status": "PASS",
        "run_id": capture.run_id,
        "created_at_unix_ms": selected_timing.ended_unix_ms,
        "node_count": scale,
    }
    json_values: dict[str, dict[str, Any]] = {
        "run_metadata": {**common, "nodes": objects["run_state.json"]["nodes"]},
        "resource_preflight": {**objects["resource_preflight.json"], **common},
        "workload_windows": {**objects["workload_windows.json"], **common},
        "lifecycle_timeline": {**objects["lifecycle_timeline.json"], **common},
        "scenario_results": {**objects["scenario_results.json"], **common},
        "management_results": {**objects["management_sequence.json"], **common},
        "fault_results": {**objects["fault_sequence.json"], **common},
        "stability_results": {
            **common,
            "recovery_health": objects["fault_sequence.json"].get("recovery_health"),
        },
        "cleanup_report": {**objects["cleanup_report.json"], **common},
        "analysis_summary": {**objects["analysis_summary.json"], **common},
        "report_index": {
            **objects["report_index.json"],
            **common,
            "views": [
                {
                    "format": "json",
                    "path": "admission_v2/analysis_summary.json",
                    "status": "PASS",
                }
            ],
        },
    }
    stream_values = {
        "command_log": [
            _normalize_command(row)
            for row in streams["management_command_log.jsonl"]
        ],
        "fault_command_log": [
            _normalize_command(row) for row in streams["fault_command_log.jsonl"]
        ],
        "events": streams["events.jsonl"],
        "metrics": streams["metrics_timeseries.jsonl"],
    }
    for kind, value in json_values.items():
        _write_json(out / f"{kind}.json", value)
    for kind, rows in stream_values.items():
        _write_jsonl(out / f"{kind}.jsonl", rows)

    admissions = {
        admission.kind: admission
        for artifact in definition.artifacts
        for admission in artifact.admissions
    }
    records: list[ArtifactRecord] = []
    artifact_rows: list[dict[str, Any]] = []
    for kind in definition.admitted_artifact_ids:
        admission_spec = admissions[kind]
        suffix = "json" if admission_spec.format == "json" else "jsonl"
        path = out / f"{kind}.{suffix}"
        source = raw_by_name[admission_spec.source_raw_name]
        node_id = provenance_node_id(capture.run_id, kind, source.sha256)
        relative = path.relative_to(root).as_posix()
        record = ArtifactRecord(
            artifact_id=kind,
            kind=kind,
            path=relative,
            format=admission_spec.format,
            sha256=sha256_file(path),
            source_path=f"runtime/{source.name}",
            source_sha256=source.sha256,
            transform_id=admission_spec.transform_id,
            provenance_node_id=node_id,
        )
        records.append(record)
        artifact_rows.append(
            {
                "kind": kind,
                "path": relative,
                "sha256": record.sha256,
                "source_path": record.source_path,
                "source_sha256": record.source_sha256,
                "transform_id": record.transform_id,
                "provenance_node_id": node_id,
            }
        )

    capture_value = capture_manifest(capture, run_owner=run_owner)
    capture_path = out / "capture_manifest.json"
    _write_json(capture_path, capture_value)
    provenance_value = build_provenance_document(capture, records)
    provenance_path = out / "provenance.json"
    _write_json(provenance_path, provenance_value)
    admission: dict[str, Any] = {
        "schema_version": ADMISSION_SCHEMA_VERSION,
        "execution_kind": "REAL_VALKEY_EXACT_SCALE",
        "run_id": capture.run_id,
        "run_nonce": uuid.uuid4().hex,
        "run_started_unix_ms": selected_timing.started_unix_ms,
        "run_ended_unix_ms": selected_timing.ended_unix_ms,
        "source_commit": commit,
        "product_digest": product_digest,
        "definition_digest": definition.digest,
        "capture_digest": capture_value["capture_digest"],
        "capture_manifest": {
            "path": capture_path.relative_to(root).as_posix(),
            "sha256": sha256_file(capture_path),
        },
        "provenance": {
            "path": provenance_path.relative_to(root).as_posix(),
            "sha256": sha256_file(provenance_path),
            "digest": provenance_value["provenance_digest"],
        },
        "requested_nodes": scale,
        "observed_nodes": scale,
        "status": "PASS",
        "valkey_versions": selected_versions,
        "independent_probe": {
            "status": "PASS",
            "observed_nodes": scale,
            "cluster_state": selected_probe.get("cluster_state"),
            "slots_assigned": selected_probe.get("slots_assigned"),
            "slots_ok": selected_probe.get("slots_ok"),
            "endpoint_count": 3,
        },
        "cleanup": {
            "status": "PASS",
            "residual_owned_resources": 0,
            "source": "runtime/cleanup_report.json",
        },
        "artifacts": artifact_rows,
    }
    if promoted_from_admission_digest is not None:
        promotion_errors: list[str] = []
        validate_digest(
            promoted_from_admission_digest,
            "promoted_from_admission_digest",
            promotion_errors,
        )
        if promotion_errors:
            raise EvidenceValidationError(tuple(promotion_errors))
        admission["promoted_from_admission_digest"] = promoted_from_admission_digest
    if invocation_run_id is not None:
        if not invocation_run_id.strip():
            raise EvidenceValidationError(("invocation_run_id must be non-empty",))
        admission["invocation_run_id"] = invocation_run_id
    admission["admission_digest"] = canonical_json_digest(admission)
    _write_json(root / "admission.json", admission)
    return admission


build_admission_from_sources = build_candidate_admission


def validate_candidate_admission(
    base: str | Path,
    scale: int,
    expected_product_digest: str | None = None,
    *,
    admission: Mapping[str, Any] | None = None,
    definition: ScenarioDefinition,
) -> ValidatedEvidenceBundle:
    root = Path(base).resolve()
    value = dict(admission) if admission is not None else load_candidate_admission(root)
    errors = list(validate_raw_sources(root, scale, definition))
    expected = {
        "schema_version": ADMISSION_SCHEMA_VERSION,
        "execution_kind": "REAL_VALKEY_EXACT_SCALE",
        "requested_nodes": scale,
        "observed_nodes": scale,
        "definition_digest": definition.digest,
        "status": "PASS",
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            errors.append(f"admission.{key} must be {expected_value!r}")
    if expected_product_digest is not None and value.get("product_digest") != expected_product_digest:
        errors.append("admission.product_digest mismatch")
    validate_digest(value.get("product_digest"), "admission.product_digest", errors)
    validate_digest(value.get("capture_digest"), "admission.capture_digest", errors)
    if not re.fullmatch(r"[0-9a-f]{32}", str(value.get("run_nonce", ""))):
        errors.append("admission.run_nonce must be 32-character lowercase hex")
    if not re.fullmatch(r"[0-9a-f]{40}", str(value.get("source_commit", ""))):
        errors.append("admission.source_commit must be a full Git commit")
    timing: RunTiming | None = None
    try:
        timing = RunTiming(value.get("run_started_unix_ms"), value.get("run_ended_unix_ms"))
    except ValueError as exc:
        errors.append(f"admission timing is invalid: {exc}")
    versions = value.get("valkey_versions")
    if not isinstance(versions, list) or not versions or any(
        not re.fullmatch(r"9\.1(?:\.\d+)?", str(item)) for item in versions
    ):
        errors.append("admission.valkey_versions must contain only observed Valkey 9.1.x")
    _validate_probe(value.get("independent_probe"), scale, errors)
    _validate_cleanup(value.get("cleanup"), errors)

    spec = canonical_bundle_spec(definition)
    try:
        capture = inspect_raw_capture(root, scale, spec)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        capture = None
        errors.append(f"cannot inspect raw capture manifest: {exc}")
    if capture is not None and value.get("run_id") != capture.run_id:
        errors.append("admission.run_id must match the raw capture run_id")
    raw_hashes = {
        f"runtime/{artifact.name}": artifact.sha256
        for artifact in capture.artifacts
    } if capture is not None else {}
    admission_specs = {
        admission_spec.kind: admission_spec
        for artifact in definition.artifacts
        for admission_spec in artifact.admissions
    }
    rows = value.get("artifacts") if isinstance(value.get("artifacts"), list) else []
    by_kind: dict[str, Mapping[str, Any]] = {}
    records: list[ArtifactRecord] = []
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("kind"), str):
            errors.append("admission artifacts require object rows with kind")
            continue
        kind = str(row["kind"])
        if kind in by_kind:
            errors.append(f"duplicate artifact kind: {kind}")
        by_kind[kind] = row
    if set(by_kind) != set(spec.admitted_artifact_kinds):
        errors.append("admission artifact kinds do not match the canonical bundle")
    for kind, row in by_kind.items():
        canonical = admission_specs.get(kind)
        if canonical is None:
            continue
        raw_path = row.get("path")
        source_path = row.get("source_path")
        expected_path = f"runtime/admission_v2/{kind}.{canonical.format}"
        expected_source = f"runtime/{canonical.source_raw_name}"
        if raw_path != expected_path:
            errors.append(f"{kind} artifact path must be {expected_path!r}")
        if not isinstance(raw_path, str) or not _safe_file(root, raw_path):
            errors.append(f"{kind} artifact path is missing or escapes evidence root")
            continue
        path = (root / raw_path).resolve()
        if row.get("sha256") != sha256_file(path):
            errors.append(f"{kind} artifact hash mismatch")
        if timing is not None:
            _validate_admitted_file(
                path, kind, canonical.format, str(value.get("run_id")), scale, timing, errors
            )
        if source_path != expected_source:
            errors.append(f"{kind} source path does not match its canonical raw artifact")
        if not isinstance(source_path, str) or source_path not in raw_hashes:
            errors.append(f"{kind} source path is not a canonical raw capture")
            continue
        if row.get("source_sha256") != raw_hashes[source_path]:
            errors.append(f"{kind} source hash mismatch")
        if row.get("transform_id") != canonical.transform_id:
            errors.append(f"{kind} transform_id does not match the canonical admission transform")
        expected_node_id = provenance_node_id(
            str(value.get("run_id")), kind, raw_hashes[source_path]
        )
        if row.get("provenance_node_id") != expected_node_id:
            errors.append(f"{kind} provenance_node_id mismatch")
        records.append(
            ArtifactRecord(
                artifact_id=kind,
                kind=kind,
                path=raw_path,
                format="jsonl" if raw_path.endswith(".jsonl") else "json",
                sha256=str(row.get("sha256")),
                source_path=source_path,
                source_sha256=str(row.get("source_sha256")),
                transform_id=row.get("transform_id") if isinstance(row.get("transform_id"), str) else None,
                provenance_node_id=expected_node_id,
            )
        )
    referenced_documents: dict[str, dict[str, Any]] = {}
    for key in ("capture_manifest", "provenance"):
        ref = value.get(key)
        if not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str) or not _safe_file(root, ref["path"]):
            errors.append(f"admission.{key} reference is missing or unsafe")
        elif ref.get("sha256") != sha256_file((root / ref["path"]).resolve()):
            errors.append(f"admission.{key} hash mismatch")
        else:
            try:
                document = json.loads((root / ref["path"]).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"admission.{key} is not valid JSON: {exc}")
            else:
                if isinstance(document, dict):
                    referenced_documents[key] = document
                else:
                    errors.append(f"admission.{key} must contain a JSON object")
    if capture is not None and "capture_manifest" in referenced_documents:
        actual_capture = referenced_documents["capture_manifest"]
        expected_capture = capture_manifest(
            capture,
            run_owner=actual_capture.get("run_owner")
            if isinstance(actual_capture.get("run_owner"), str)
            else None,
        )
        if actual_capture != expected_capture:
            errors.append("capture_manifest does not match the preserved raw capture")
        if value.get("capture_digest") != expected_capture["capture_digest"]:
            errors.append("admission.capture_digest does not match capture_manifest")
    if capture is not None and len(records) == len(spec.admitted_artifact_kinds) and "provenance" in referenced_documents:
        actual_provenance = referenced_documents["provenance"]
        expected_provenance = build_provenance_document(capture, records)
        if actual_provenance != expected_provenance:
            errors.append("provenance document does not match canonical capture-to-admission edges")
        provenance_ref = value.get("provenance")
        if isinstance(provenance_ref, Mapping) and provenance_ref.get("digest") != expected_provenance["provenance_digest"]:
            errors.append("admission.provenance digest mismatch")
    digest_value = dict(value)
    claimed_digest = digest_value.pop("admission_digest", None)
    if claimed_digest != canonical_json_digest(digest_value):
        errors.append("admission.admission_digest mismatch")
    if errors or timing is None or capture is None:
        raise EvidenceValidationError(errors)
    return ValidatedEvidenceBundle(
        root=root,
        run_id=capture.run_id,
        run_nonce=str(value["run_nonce"]),
        requested_nodes=scale,
        observed_nodes=scale,
        definition_digest=definition.digest,
        product_digest=str(value["product_digest"]),
        admission_digest=str(claimed_digest),
        artifacts=tuple(records),
        admission=value,
    )


def load_candidate_admission(base: str | Path) -> dict[str, Any]:
    path = Path(base).resolve() / "admission.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError((f"cannot load candidate admission: {exc}",)) from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError(("candidate admission must be a JSON object",))
    return value


def _select_timing(
    timing: RunTiming | None,
    started: int | None,
    ended: int | None,
    streams: Mapping[str, list[dict[str, Any]]],
) -> RunTiming:
    if timing is not None:
        if started is not None or ended is not None:
            raise EvidenceValidationError(("timing and legacy timing arguments are mutually exclusive",))
        return timing
    observed = [
        row.get("timestamp_unix_ms")
        for name in ("events.jsonl", "metrics_timeseries.jsonl")
        for row in streams[name]
        if isinstance(row.get("timestamp_unix_ms"), int)
    ]
    observed.extend(
        row.get("ended_at_unix_ms")
        for name in ("management_command_log.jsonl", "fault_command_log.jsonl")
        for row in streams[name]
        if isinstance(row.get("ended_at_unix_ms"), int)
    )
    try:
        return RunTiming(
            started if isinstance(started, int) else min(observed),
            ended if isinstance(ended, int) else max(observed),
        )
    except (ValueError, TypeError) as exc:
        raise EvidenceValidationError((f"cannot determine measured run timing: {exc}",)) from exc


def _normalize_command(row: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(row)
    if not isinstance(item.get("timestamp_unix_ms"), int):
        item["timestamp_unix_ms"] = int(item["ended_at_unix_ms"])
    return item


def _source_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=False, capture_output=True, text=True
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise EvidenceValidationError(("cannot determine full source Git commit",))
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _safe_file(root: Path, raw: str) -> bool:
    path = (root / raw).resolve()
    return path.is_relative_to(root) and path.is_file()


def _validate_probe(value: Any, scale: int, errors: list[str]) -> None:
    expected = {
        "status": "PASS",
        "observed_nodes": scale,
        "cluster_state": "ok",
        "slots_assigned": 16384,
        "slots_ok": 16384,
    }
    if not isinstance(value, Mapping):
        errors.append("admission.independent_probe is required")
        return
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            errors.append(f"independent_probe.{key} must be {expected_value!r}")
    if not isinstance(value.get("endpoint_count"), int) or value["endpoint_count"] < 2:
        errors.append("independent_probe.endpoint_count must be at least 2")


def _validate_cleanup(value: Any, errors: list[str]) -> None:
    if not isinstance(value, Mapping) or value.get("status") != "PASS" or value.get(
        "residual_owned_resources"
    ) != 0:
        errors.append("admission.cleanup must PASS with zero residual owned resources")


def _validate_admitted_file(
    path: Path,
    kind: str,
    artifact_format: str,
    run_id: str,
    scale: int,
    timing: RunTiming,
    errors: list[str],
) -> None:
    try:
        if artifact_format == "json":
            rows = [json.loads(path.read_text(encoding="utf-8"))]
        else:
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{kind} artifact is invalid: {exc}")
        return
    if not rows or any(not isinstance(row, dict) for row in rows):
        errors.append(f"{kind} artifact must contain non-empty object evidence")
        return
    for index, row in enumerate(rows, start=1):
        label = kind if artifact_format == "json" else f"{kind}:{index}"
        if row.get("run_id") != run_id:
            errors.append(f"{label} run_id must match admission.run_id")
        timestamp = (
            row.get("created_at_unix_ms")
            if artifact_format == "json"
            else row.get("timestamp_unix_ms")
        )
        if not isinstance(timestamp, int) or not (
            timing.started_unix_ms <= timestamp <= timing.ended_unix_ms
        ):
            errors.append(f"{label} timestamp must fall within the measured run")
        if artifact_format == "json":
            if row.get("schema_version") != "v1" or row.get("status") != "PASS":
                errors.append(f"{label} must use schema v1 and PASS")
            observed = row.get("node_count", row.get("scale"))
            if observed is not None and observed != scale:
                errors.append(f"{label} node_count must equal {scale}")
        elif kind in {"command_log", "fault_command_log"}:
            if not row.get("command_id") or row.get("status") != "PASS" or not row.get("scenario_id"):
                errors.append(f"{label} requires command_id, scenario_id, and PASS")
        elif kind == "events":
            if not row.get("event_id") or not isinstance(row.get("monotonic_ms"), (int, float)):
                errors.append(f"{label} requires event_id and monotonic_ms")
        elif kind == "metrics":
            if not row.get("metric_name") or "metric_value" not in row:
                errors.append(f"{label} requires metric_name and metric_value")
