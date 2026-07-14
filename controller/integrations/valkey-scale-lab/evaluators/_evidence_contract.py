from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from _common import canonical_digest, file_digest, reject_duplicate_keys, safe_file
from _schema import validate as validate_schema


HEX32 = re.compile(r"[0-9a-f]{32}", re.ASCII)
HEX40 = re.compile(r"[0-9a-f]{40}", re.ASCII)


def validate_exact_evidence(
    *,
    root: Path,
    candidate: dict[str, Any],
    definition: dict[str, Any],
    candidate_schema: dict[str, Any],
    scale: int,
    invocation_run_id: str,
    product_digest: str,
) -> list[str]:
    errors = [f"candidate schema: {error}" for error in validate_schema(candidate, candidate_schema)]
    definition_digest = canonical_digest(definition)
    expected = {
        "schema_version": "valkey-exact-scale-admission-v1",
        "execution_kind": "REAL_VALKEY_EXACT_SCALE",
        "requested_nodes": scale,
        "observed_nodes": scale,
        "status": "PASS",
        "product_digest": product_digest,
        "invocation_run_id": invocation_run_id,
        "definition_digest": definition_digest,
    }
    for field, expected_value in expected.items():
        if candidate.get(field) != expected_value:
            errors.append(f"admission.{field} must be {expected_value!r}")
    run_id = candidate.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        errors.append("admission.run_id is missing")
        run_id = ""
    if HEX32.fullmatch(str(candidate.get("run_nonce", ""))) is None:
        errors.append("admission.run_nonce is invalid")
    if HEX40.fullmatch(str(candidate.get("source_commit", ""))) is None:
        errors.append("admission.source_commit is invalid")
    started = candidate.get("run_started_unix_ms")
    ended = candidate.get("run_ended_unix_ms")
    if (
        not isinstance(started, int)
        or isinstance(started, bool)
        or not isinstance(ended, int)
        or isinstance(ended, bool)
        or ended < started
    ):
        errors.append("admission timing is invalid")
    versions = candidate.get("valkey_versions")
    if not isinstance(versions, list) or not versions or any(
        re.fullmatch(r"9\.1(?:\.\d+)?", str(value)) is None for value in versions
    ):
        errors.append("admission.valkey_versions must contain observed Valkey 9.1.x versions")
    probe = candidate.get("independent_probe")
    probe_expected = {
        "status": "PASS",
        "observed_nodes": scale,
        "cluster_state": "ok",
        "slots_assigned": 16384,
        "slots_ok": 16384,
    }
    if not isinstance(probe, Mapping):
        errors.append("independent exact-scale probe is missing")
    else:
        for field, expected_value in probe_expected.items():
            if probe.get(field) != expected_value:
                errors.append(f"independent_probe.{field} must be {expected_value!r}")
        if not isinstance(probe.get("endpoint_count"), int) or probe["endpoint_count"] < 2:
            errors.append("independent_probe.endpoint_count must be at least 2")
    cleanup = candidate.get("cleanup")
    if (
        not isinstance(cleanup, Mapping)
        or cleanup.get("status") != "PASS"
        or cleanup.get("residual_owned_resources") != 0
        or cleanup.get("source") != "runtime/cleanup_report.json"
    ):
        errors.append("cleanup did not PASS with zero residual owned resources")

    artifacts = definition.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("declared scenario definition has no artifact contract")
        return errors
    raw_specs: dict[str, dict[str, Any]] = {}
    admission_specs: dict[str, dict[str, Any]] = {}
    for row in artifacts:
        if not isinstance(row, dict) or not isinstance(row.get("raw_name"), str):
            errors.append("declared scenario definition has an invalid artifact row")
            continue
        raw_name = row["raw_name"]
        if raw_name in raw_specs:
            errors.append(f"declared scenario definition repeats raw artifact {raw_name}")
        raw_specs[raw_name] = row
        for admission in row.get("admissions", []):
            if not isinstance(admission, dict) or not isinstance(admission.get("kind"), str):
                errors.append(f"declared scenario definition has an invalid admission for {raw_name}")
                continue
            kind = admission["kind"]
            if kind in admission_specs:
                errors.append(f"declared scenario definition repeats admitted artifact {kind}")
            admission_specs[kind] = {
                "format": row.get("format"),
                "source_raw_name": raw_name,
                "transform_id": admission.get("transform_id"),
            }

    objects, streams, raw_hashes = _load_raw_artifacts(root, raw_specs, errors)
    _validate_raw_semantics(
        root=root,
        definition=definition,
        objects=objects,
        streams=streams,
        run_id=run_id,
        scale=scale,
        errors=errors,
    )
    expected_capture = _expected_capture(
        definition_digest=definition_digest,
        raw_specs=raw_specs,
        raw_hashes=raw_hashes,
        run_id=run_id,
        scale=scale,
    )
    capture = _referenced_document(root, candidate.get("capture_manifest"), "capture manifest", errors)
    if capture is not None:
        if isinstance(capture.get("run_owner"), str):
            expected_capture["run_owner"] = capture["run_owner"]
            expected_capture["capture_digest"] = canonical_digest(expected_capture)
        if capture != expected_capture:
            errors.append("capture manifest does not match the complete declared scenario capture")
        if candidate.get("capture_digest") != expected_capture.get("capture_digest"):
            errors.append("admission capture digest does not match the complete capture manifest")

    records = _validate_admitted_artifacts(
        root=root,
        rows=candidate.get("artifacts"),
        admission_specs=admission_specs,
        raw_hashes=raw_hashes,
        run_id=run_id,
        scale=scale,
        errors=errors,
    )
    expected_provenance = _expected_provenance(
        definition_digest=definition_digest,
        raw_specs=raw_specs,
        raw_hashes=raw_hashes,
        run_id=run_id,
        records=records,
    )
    provenance = _referenced_document(root, candidate.get("provenance"), "provenance", errors)
    if provenance is not None and provenance != expected_provenance:
        errors.append("provenance does not contain the complete canonical capture-to-admission graph")
    provenance_ref = candidate.get("provenance")
    if isinstance(provenance_ref, Mapping) and provenance_ref.get("digest") != expected_provenance.get(
        "provenance_digest"
    ):
        errors.append("admission provenance digest mismatch")
    unsigned = dict(candidate)
    claimed = unsigned.pop("admission_digest", None)
    if claimed != canonical_digest(unsigned):
        errors.append("admission digest is forged or stale")
    return errors


def _load_raw_artifacts(
    root: Path,
    raw_specs: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, str]]:
    objects: dict[str, dict[str, Any]] = {}
    streams: dict[str, list[dict[str, Any]]] = {}
    hashes: dict[str, str] = {}
    for name, spec in raw_specs.items():
        path = safe_file(root, f"runtime/{name}")
        if path is None:
            if spec.get("required_raw") is True:
                errors.append(f"required raw artifact runtime/{name} is missing")
            continue
        hashes[name] = file_digest(path)
        try:
            if spec.get("format") == "json":
                value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
                if not isinstance(value, dict):
                    raise ValueError("JSON root is not an object")
                objects[name] = value
            elif spec.get("format") == "jsonl":
                values = [
                    json.loads(line, object_pairs_hook=reject_duplicate_keys)
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                if not values or any(not isinstance(item, dict) for item in values):
                    raise ValueError("JSONL must contain non-empty object rows")
                streams[name] = values
            else:
                errors.append(f"declared scenario has unsupported format for runtime/{name}")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"runtime/{name} is invalid: {exc}")
    return objects, streams, hashes


def _validate_raw_semantics(
    *,
    root: Path,
    definition: Mapping[str, Any],
    objects: Mapping[str, dict[str, Any]],
    streams: Mapping[str, list[dict[str, Any]]],
    run_id: str,
    scale: int,
    errors: list[str],
) -> None:
    run_state = objects.get("run_state.json", {})
    nodes = run_state.get("nodes") if isinstance(run_state.get("nodes"), list) else []
    logical_ids = [
        row.get("logical_id") for row in nodes if isinstance(row, dict) and row.get("logical_id")
    ]
    if (
        run_state.get("status") != "PASS"
        or run_state.get("run_id") != run_id
        or run_state.get("node_count") != scale
        or len(nodes) != scale
        or len(logical_ids) != scale
        or len(set(logical_ids)) != scale
    ):
        errors.append(f"runtime/run_state.json must prove exactly {scale} unique nodes for the admitted run")
    for name in (
        "workload_windows.json",
        "lifecycle_timeline.json",
        "scenario_results.json",
        "management_sequence.json",
        "fault_sequence.json",
        "cleanup_report.json",
        "analysis_summary.json",
        "report_index.json",
        "full_flow_result.json",
    ):
        value = objects.get(name, {})
        if value.get("status") != "PASS" or value.get("run_id") != run_id:
            errors.append(f"runtime/{name} must PASS for the admitted run")
    preflight = objects.get("resource_preflight.json", {})
    requested = preflight.get("nodes_requested", preflight.get("node_count"))
    if preflight.get("status") != "PASS" or preflight.get("can_run") is not True or requested != scale:
        errors.append(f"runtime/resource_preflight.json must admit exactly {scale} nodes")
    cleanup = objects.get("cleanup_report.json", {})
    if cleanup.get("resources_remaining") not in ([], None) or cleanup.get("cleanup_errors") not in (
        [],
        None,
    ):
        errors.append("runtime/cleanup_report.json reports residual resources")
    analysis = objects.get("analysis_summary.json", {})
    surfaces = definition.get("report_surfaces", [])
    if isinstance(surfaces, list) and any(surface not in analysis for surface in surfaces):
        errors.append("runtime/analysis_summary.json is missing declared report surfaces")
    windows = objects.get("workload_windows.json", {}).get("windows")
    if not isinstance(windows, list) or not windows or any(
        not isinstance(row, dict) or row.get("status") != "PASS" for row in windows
    ):
        errors.append("runtime/workload_windows.json has no passing measured window")

    for name, rows in streams.items():
        if any(row.get("run_id") != run_id for row in rows):
            errors.append(f"runtime/{name} contains cross-run evidence")
    _validate_missing_taxonomy(objects, streams, errors)
    events = streams.get("events.jsonl", [])
    event_by_id = {
        str(row["event_id"]): row
        for row in events
        if isinstance(row.get("event_id"), str) and row["event_id"]
    }
    if len(event_by_id) != len(events):
        errors.append("runtime/events.jsonl requires unique non-empty event_id values")
    commands: dict[str, tuple[str, dict[str, Any]]] = {}
    for stream_name, raw_name in (
        ("management", "management_command_log.jsonl"),
        ("fault", "fault_command_log.jsonl"),
    ):
        for row in streams.get(raw_name, []):
            command_id = row.get("command_id")
            if (
                not isinstance(command_id, str)
                or not command_id
                or command_id in commands
                or row.get("status") != "PASS"
                or not row.get("operation_id")
                or not row.get("scenario_id")
            ):
                errors.append(f"runtime/{raw_name} contains an invalid or duplicate command")
                continue
            commands[command_id] = (stream_name, row)
    metrics = streams.get("metrics_timeseries.jsonl", [])
    if not metrics or any(not row.get("metric_name") or "metric_value" not in row for row in metrics):
        errors.append("runtime/metrics_timeseries.jsonl has no valid measurements")

    lifecycle_rows = objects.get("lifecycle_timeline.json", {}).get("steps")
    lifecycle_by_id = {
        str(row.get("id")): row for row in lifecycle_rows if isinstance(row, dict)
    } if isinstance(lifecycle_rows, list) else {}
    lifecycle = definition.get("lifecycle", [])
    lifecycle_ids = [row.get("id") for row in lifecycle if isinstance(row, dict)]
    if set(lifecycle_by_id) != set(lifecycle_ids):
        errors.append("runtime/lifecycle_timeline.json does not cover the declared lifecycle")
    for step_id in lifecycle_ids:
        row = lifecycle_by_id.get(str(step_id), {})
        start, end = row.get("started_monotonic_ms"), row.get("ended_monotonic_ms")
        refs = row.get("event_ids")
        if (
            row.get("status") != "PASS"
            or row.get("run_id") != run_id
            or not isinstance(start, (int, float))
            or isinstance(start, bool)
            or not isinstance(end, (int, float))
            or isinstance(end, bool)
            or end <= start
            or not isinstance(refs, list)
            or not refs
            or any(
                str(ref) not in event_by_id
                or event_by_id[str(ref)].get("step_id") != step_id
                for ref in refs
            )
        ):
            errors.append(f"lifecycle step {step_id} lacks measured attributable evidence")

    declared: dict[str, str] = {}
    scenarios = definition.get("scenarios", {})
    if isinstance(scenarios, Mapping):
        for group in ("management", "fault"):
            for row in scenarios.get(group, []):
                if isinstance(row, dict) and isinstance(row.get("id"), str):
                    declared[row["id"]] = group
    scenario_rows = objects.get("scenario_results.json", {}).get("scenarios")
    scenario_by_id = {
        str(row.get("id")): row for row in scenario_rows if isinstance(row, dict)
    } if isinstance(scenario_rows, list) else {}
    if set(scenario_by_id) != set(declared):
        errors.append("runtime/scenario_results.json does not cover every declared scenario")
    operation_owner: dict[str, str] = {}
    for scenario_id, group in declared.items():
        row = scenario_by_id.get(scenario_id, {})
        event_refs = row.get("event_ids") if isinstance(row.get("event_ids"), list) else []
        command_refs = row.get("command_ids") if isinstance(row.get("command_ids"), list) else []
        evidence_refs = row.get("evidence_refs") if isinstance(row.get("evidence_refs"), list) else []
        if row.get("status") != "REAL_PASS" or row.get("run_id") != run_id:
            errors.append(f"scenario {scenario_id} is not a real passing observation")
        if not event_refs or not command_refs or not evidence_refs:
            errors.append(f"scenario {scenario_id} is missing evidence references")
        for reference in event_refs:
            event = event_by_id.get(str(reference))
            if event is None or event.get("scenario_id") != scenario_id:
                errors.append(f"scenario {scenario_id} has invalid event provenance")
                continue
            _claim_operation(event.get("operation_id"), scenario_id, operation_owner, errors)
        for reference in command_refs:
            command = commands.get(str(reference))
            if command is None or command[0] != group or command[1].get("scenario_id") != scenario_id:
                errors.append(f"scenario {scenario_id} has invalid command provenance")
                continue
            _claim_operation(command[1].get("operation_id"), scenario_id, operation_owner, errors)
        for reference in evidence_refs:
            if safe_file(root, reference) is None:
                errors.append(f"scenario {scenario_id} references missing evidence {reference}")


def _claim_operation(
    value: Any,
    scenario_id: str,
    owners: dict[str, str],
    errors: list[str],
) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"scenario {scenario_id} has no observed operation id")
        return
    previous = owners.setdefault(value, scenario_id)
    if previous != scenario_id:
        errors.append(f"operation {value} was relabelled from {previous} to {scenario_id}")


def _validate_missing_taxonomy(
    objects: Mapping[str, dict[str, Any]],
    streams: Mapping[str, list[dict[str, Any]]],
    errors: list[str],
) -> None:
    missing_statuses = {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"}

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            if value.get("status") in missing_statuses and not str(value.get("reason", "")).strip():
                errors.append(f"{path} missing-data status has no reason")
            for key, item in value.items():
                visit(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    for name, value in objects.items():
        visit(value, f"runtime/{name}")
    for name, rows in streams.items():
        visit(rows, f"runtime/{name}")


def _expected_capture(
    *,
    definition_digest: str,
    raw_specs: Mapping[str, Mapping[str, Any]],
    raw_hashes: Mapping[str, str],
    run_id: str,
    scale: int,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": "valkey-scale-lab-capture-manifest-v1",
        "run_id": run_id,
        "requested_nodes": scale,
        "observed_nodes": scale,
        "definition_digest": definition_digest,
        "artifacts": [
            {
                "name": name,
                "path": f"runtime/{name}",
                "format": spec.get("format"),
                "sha256": raw_hashes.get(name),
                "run_id": run_id,
            }
            for name, spec in raw_specs.items()
        ],
    }
    value["capture_digest"] = canonical_digest(value)
    return value


def _validate_admitted_artifacts(
    *,
    root: Path,
    rows: Any,
    admission_specs: Mapping[str, Mapping[str, Any]],
    raw_hashes: Mapping[str, str],
    run_id: str,
    scale: int,
    errors: list[str],
) -> list[dict[str, Any]]:
    by_kind: dict[str, dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("kind"), str):
                errors.append("admission artifact row is invalid")
                continue
            if row["kind"] in by_kind:
                errors.append(f"duplicate admitted artifact {row['kind']}")
            by_kind[row["kind"]] = row
    if set(by_kind) != set(admission_specs):
        errors.append("admission artifact kinds do not match the complete declared scenario")
    records: list[dict[str, Any]] = []
    for kind, spec in admission_specs.items():
        row = by_kind.get(kind)
        if row is None:
            continue
        suffix = spec.get("format")
        expected_path = f"runtime/admission_v2/{kind}.{suffix}"
        expected_source = f"runtime/{spec.get('source_raw_name')}"
        if row.get("path") != expected_path or row.get("source_path") != expected_source:
            errors.append(f"{kind} does not use its canonical admitted and raw paths")
        admitted = safe_file(root, expected_path)
        source = safe_file(root, expected_source)
        if admitted is None or source is None:
            errors.append(f"{kind} admitted or raw artifact is missing")
            continue
        if row.get("sha256") != file_digest(admitted):
            errors.append(f"{kind} admitted artifact digest mismatch")
        source_digest = raw_hashes.get(str(spec.get("source_raw_name")))
        if row.get("source_sha256") != source_digest or source_digest != file_digest(source):
            errors.append(f"{kind} raw source digest mismatch")
        if row.get("transform_id") != spec.get("transform_id"):
            errors.append(f"{kind} transform does not match the declared scenario")
        node_id = f"artifact-{canonical_digest([run_id, kind, source_digest])[:24]}"
        if row.get("provenance_node_id") != node_id:
            errors.append(f"{kind} provenance node id mismatch")
        try:
            if suffix == "json":
                documents = [
                    json.loads(admitted.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
                ]
            else:
                documents = [
                    json.loads(line, object_pairs_hook=reject_duplicate_keys)
                    for line in admitted.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{kind} admitted artifact is invalid JSON evidence: {exc}")
            documents = []
        if not documents or any(not isinstance(item, dict) for item in documents):
            errors.append(f"{kind} admitted artifact is empty")
        for document in documents:
            if isinstance(document, dict) and document.get("run_id") != run_id:
                errors.append(f"{kind} contains cross-run evidence")
            if isinstance(document, dict):
                observed = document.get("node_count", document.get("scale"))
                if observed is not None and observed != scale:
                    errors.append(f"{kind} contains downscaled evidence")
        records.append(
            {
                "id": node_id,
                "kind": kind,
                "path": expected_path,
                "sha256": row.get("sha256"),
                "source_path": expected_source,
                "source_sha256": source_digest,
                "transform_id": spec.get("transform_id"),
            }
        )
    return records


def _expected_provenance(
    *,
    definition_digest: str,
    raw_specs: Mapping[str, Mapping[str, Any]],
    raw_hashes: Mapping[str, str],
    run_id: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": "valkey-scale-lab-evidence-provenance-v1",
        "run_id": run_id,
        "definition_digest": definition_digest,
        "capture_nodes": [
            {
                "id": f"raw-{str(raw_hashes.get(name, ''))[:24]}",
                "path": f"runtime/{name}",
                "sha256": raw_hashes.get(name),
            }
            for name in raw_specs
        ],
        "admission_nodes": records,
    }
    value["provenance_digest"] = canonical_digest(value)
    return value


def _referenced_document(
    root: Path,
    reference: Any,
    name: str,
    errors: list[str],
) -> dict[str, Any] | None:
    if not isinstance(reference, Mapping):
        errors.append(f"{name} reference is missing")
        return None
    path = safe_file(root, reference.get("path"))
    if path is None or reference.get("sha256") != file_digest(path):
        errors.append(f"{name} reference is unsafe, missing, or has the wrong digest")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"{name} is invalid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{name} must contain an object")
        return None
    return value
