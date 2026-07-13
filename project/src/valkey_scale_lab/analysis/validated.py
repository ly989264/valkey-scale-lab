from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from valkey_scale_lab.evidence import (
    MISSING_STATUSES,
    ArtifactRecord,
    ValidatedEvidenceBundle,
)
from valkey_scale_lab.evidence.manifest import canonical_json_digest


ANALYSIS_SCHEMA_VERSION = "valkey-scale-lab-validated-analysis-v1"
SURFACE_NAMES = (
    "topology",
    "lifecycle_timing",
    "bottlenecks",
    "resources",
    "workload_impact",
    "management_operations",
    "failover",
    "recovery",
    "errors",
    "cleanup",
    "missing_evidence",
)


class ValidatedAnalysisError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedAnalysis:
    evidence_root: Path
    path: Path
    sha256: str
    run_id: str
    requested_nodes: int
    observed_nodes: int
    admission_digest: str
    definition_digest: str
    product_digest: str
    capture_digest: str
    provenance_digest: str
    source_artifacts: tuple[ArtifactRecord, ...]
    document: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_root", self.evidence_root.resolve())
        object.__setattr__(self, "path", self.path.resolve())
        object.__setattr__(self, "source_artifacts", tuple(self.source_artifacts))
        object.__setattr__(self, "document", _freeze(self.document))


def analyze_validated_evidence(
    bundle: ValidatedEvidenceBundle,
    out_path: str | Path,
) -> ValidatedAnalysis:
    if not isinstance(bundle, ValidatedEvidenceBundle):
        raise ValidatedAnalysisError(
            "analysis requires a ValidatedEvidenceBundle capability"
        )
    root = bundle.root.resolve()
    out = Path(out_path).resolve()
    if out == root or out.is_relative_to(root):
        raise ValidatedAnalysisError(
            "analysis output must be outside the validated evidence root"
        )

    artifacts = _load_artifacts(bundle)
    admission = bundle.admission
    admitted_digest = _required_digest(
        admission.get("admission_digest"), "admission"
    )
    if bundle.admission_digest != admitted_digest:
        raise ValidatedAnalysisError(
            "validated evidence admission digest does not match its admission document"
        )
    digest_value = _mutable_json(admission)
    digest_value.pop("admission_digest", None)
    if canonical_json_digest(digest_value) != admitted_digest:
        raise ValidatedAnalysisError(
            "validated evidence admission digest does not match its canonical document"
        )
    _validate_bundle_binding(bundle, admission)
    capture_digest = _required_digest(admission.get("capture_digest"), "capture")
    provenance_ref = admission.get("provenance")
    provenance_digest = _required_digest(
        provenance_ref.get("digest") if isinstance(provenance_ref, Mapping) else None,
        "provenance",
    )
    missing_items = _source_missing_items(artifacts)
    derived_missing: list[dict[str, Any]] = []
    surfaces = {
        "topology": _topology(bundle, artifacts),
        "lifecycle_timing": _lifecycle(artifacts, derived_missing),
        "resources": _resources(artifacts, derived_missing),
        "workload_impact": _workload(artifacts, derived_missing),
        "management_operations": _management(artifacts),
        "failover": _failover(artifacts, derived_missing),
        "recovery": _recovery(artifacts, derived_missing),
        "errors": _errors(artifacts),
        "cleanup": _cleanup(artifacts),
    }
    surfaces["bottlenecks"] = _bottlenecks(
        surfaces["lifecycle_timing"], artifacts, derived_missing
    )
    all_missing = _deduplicate_missing([*missing_items, *derived_missing])
    surfaces["missing_evidence"] = {
        "status": "OBSERVED",
        "count": len(all_missing),
        "items": all_missing,
    }

    source_artifacts = [_source_ref(record) for record in bundle.artifacts]
    document: dict[str, Any] = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "artifact_type": "validated_evidence_analysis",
        "status": "DERIVED",
        "run_id": bundle.run_id,
        "run_nonce": bundle.run_nonce,
        "requested_nodes": bundle.requested_nodes,
        "observed_nodes": bundle.observed_nodes,
        "digests": {
            "admission": admitted_digest,
            "definition": bundle.definition_digest,
            "product": bundle.product_digest,
            "run": capture_digest,
            "capture": capture_digest,
            "provenance": provenance_digest,
        },
        "provenance_refs": {
            "capture_manifest": _plain_mapping(admission.get("capture_manifest")),
            "provenance": _plain_mapping(provenance_ref),
        },
        "source_artifacts": source_artifacts,
        "surfaces": surfaces,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    digest = _sha256(out)
    return ValidatedAnalysis(
        evidence_root=root,
        path=out,
        sha256=digest,
        run_id=bundle.run_id,
        requested_nodes=bundle.requested_nodes,
        observed_nodes=bundle.observed_nodes,
        admission_digest=admitted_digest,
        definition_digest=bundle.definition_digest,
        product_digest=bundle.product_digest,
        capture_digest=capture_digest,
        provenance_digest=provenance_digest,
        source_artifacts=bundle.artifacts,
        document=document,
    )


def _validate_bundle_binding(
    bundle: ValidatedEvidenceBundle,
    admission: Mapping[str, Any],
) -> None:
    for field in (
        "run_id",
        "run_nonce",
        "requested_nodes",
        "observed_nodes",
        "definition_digest",
        "product_digest",
    ):
        if getattr(bundle, field) != admission.get(field):
            raise ValidatedAnalysisError(
                f"validated evidence {field} does not match its admission document"
            )

    rows = admission.get("artifacts")
    if not isinstance(rows, (list, tuple)) or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise ValidatedAnalysisError(
            "validated evidence admission artifact list is missing or invalid"
        )
    admitted_by_kind: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        kind = row.get("kind")
        if not isinstance(kind, str) or kind in admitted_by_kind:
            raise ValidatedAnalysisError(
                "validated evidence admission artifact kinds are invalid"
            )
        admitted_by_kind[kind] = row

    records_by_kind: dict[str, ArtifactRecord] = {}
    for record in bundle.artifacts:
        if record.kind in records_by_kind or record.artifact_id != record.kind:
            raise ValidatedAnalysisError(
                "validated evidence artifact identities are invalid"
            )
        records_by_kind[record.kind] = record
    if set(records_by_kind) != set(admitted_by_kind):
        raise ValidatedAnalysisError(
            "validated evidence artifacts do not match the complete admission artifact list"
        )

    for kind, record in records_by_kind.items():
        admitted = admitted_by_kind[kind]
        expected = {
            "kind": record.kind,
            "path": record.path,
            "sha256": record.sha256,
            "source_path": record.source_path,
            "source_sha256": record.source_sha256,
            "transform_id": record.transform_id,
            "provenance_node_id": record.provenance_node_id,
        }
        if any(admitted.get(field) != value for field, value in expected.items()):
            raise ValidatedAnalysisError(
                f"validated evidence artifact {kind} does not match its admission reference"
            )
        expected_format = "jsonl" if record.path.endswith(".jsonl") else "json"
        if record.format != expected_format:
            raise ValidatedAnalysisError(
                f"validated evidence artifact {kind} has an invalid format binding"
            )


def _load_artifacts(bundle: ValidatedEvidenceBundle) -> dict[str, Any]:
    root = bundle.root.resolve()
    loaded: dict[str, Any] = {}
    for record in bundle.artifacts:
        if record.kind in loaded:
            raise ValidatedAnalysisError(f"duplicate evidence artifact kind: {record.kind}")
        path = (root / record.path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValidatedAnalysisError(
                f"evidence artifact is missing or escapes its root: {record.kind}"
            )
        if _sha256(path) != record.sha256:
            raise ValidatedAnalysisError(
                f"evidence artifact hash changed after validation: {record.kind}"
            )
        try:
            if record.format == "json":
                value = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise ValidatedAnalysisError(
                        f"evidence artifact must contain a JSON object: {record.kind}"
                    )
            elif record.format == "jsonl":
                value = [
                    json.loads(line)
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                if not value or any(not isinstance(row, dict) for row in value):
                    raise ValidatedAnalysisError(
                        f"evidence stream must contain object rows: {record.kind}"
                    )
            else:
                raise ValidatedAnalysisError(
                    f"unsupported evidence artifact format: {record.format}"
                )
        except json.JSONDecodeError as exc:
            raise ValidatedAnalysisError(
                f"invalid validated artifact JSON for {record.kind}: {exc}"
            ) from exc
        loaded[record.kind] = value
    return loaded


def _topology(
    bundle: ValidatedEvidenceBundle, artifacts: Mapping[str, Any]
) -> dict[str, Any]:
    metadata = _object(artifacts, "run_metadata")
    nodes = metadata.get("nodes") if isinstance(metadata.get("nodes"), list) else []
    logical_ids = sorted(
        str(row["logical_id"])
        for row in nodes
        if isinstance(row, dict) and isinstance(row.get("logical_id"), str)
    )
    probe = bundle.admission.get("independent_probe")
    return {
        "status": "OBSERVED",
        "requested_nodes": bundle.requested_nodes,
        "observed_nodes": bundle.observed_nodes,
        "unique_logical_node_count": len(set(logical_ids)),
        "logical_ids": logical_ids,
        "cluster_state": probe.get("cluster_state") if isinstance(probe, Mapping) else _missing("Independent cluster state was not present."),
        "slots_assigned": probe.get("slots_assigned") if isinstance(probe, Mapping) else _missing("Independent slot assignment was not present."),
        "slots_ok": probe.get("slots_ok") if isinstance(probe, Mapping) else _missing("Independent healthy slot count was not present."),
        "valkey_versions": list(bundle.admission.get("valkey_versions", ())),
    }


def _lifecycle(
    artifacts: Mapping[str, Any], missing: list[dict[str, Any]]
) -> dict[str, Any]:
    source = _object(artifacts, "lifecycle_timeline")
    rows = source.get("steps") if isinstance(source.get("steps"), list) else []
    steps: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        start, end = row.get("started_monotonic_ms"), row.get("ended_monotonic_ms")
        duration = row.get("duration_ms")
        if not _number(duration) and _number(start) and _number(end):
            duration = float(end) - float(start)
        if not _number(duration):
            duration = _record_missing(
                missing,
                "lifecycle_timing",
                f"Lifecycle step {row.get('id', 'unknown')} had no measured duration.",
                "lifecycle_timeline",
            )
        steps.append(
            {
                "id": str(row.get("id", "")),
                "observed_status": row.get("status"),
                "started_monotonic_ms": start,
                "ended_monotonic_ms": end,
                "duration_ms": duration,
                "event_ids": list(row.get("event_ids", ())) if isinstance(row.get("event_ids"), list) else [],
            }
        )
    numeric = [float(row["duration_ms"]) for row in steps if _number(row["duration_ms"])]
    return {
        "status": "OBSERVED" if steps else "MISSING",
        **({} if steps else {"reason": "No validated lifecycle steps were available."}),
        "step_count": len(steps),
        "measured_duration_ms": sum(numeric),
        "steps": steps,
    }


def _resources(
    artifacts: Mapping[str, Any], missing: list[dict[str, Any]]
) -> dict[str, Any]:
    rows = _rows(artifacts, "metrics")
    grouped: dict[str, list[float]] = {}
    for row in rows:
        value = row.get("metric_value")
        if _number(value):
            grouped.setdefault(str(row.get("metric_name")), []).append(float(value))
    if not grouped:
        marker = _record_missing(
            missing,
            "resources",
            "No numeric resource or telemetry samples were present.",
            "metrics",
        )
        return {**marker, "sample_count": 0, "metrics": {}}
    return {
        "status": "OBSERVED",
        "sample_count": sum(len(values) for values in grouped.values()),
        "metrics": {
            name: {
                "sample_count": len(values),
                "min": min(values),
                "max": max(values),
                "mean": sum(values) / len(values),
            }
            for name, values in sorted(grouped.items())
        },
    }


def _workload(
    artifacts: Mapping[str, Any], missing: list[dict[str, Any]]
) -> dict[str, Any]:
    source = _object(artifacts, "workload_windows")
    rows = source.get("windows") if isinstance(source.get("windows"), list) else []
    if not rows:
        marker = _record_missing(
            missing,
            "workload_impact",
            "No validated workload windows were present.",
            "workload_windows",
        )
        return {**marker, "window_count": 0, "windows": []}
    windows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        selected = {
            name: value
            for name in (
                "achieved_qps",
                "latency_p50_ms",
                "latency_p95_ms",
                "latency_p99_ms",
                "error_rate",
                "duration_seconds",
                "sample_count",
            )
            if (value := row.get(name, metrics.get(name))) is not None
        }
        windows.append(
            {
                "window_name": row.get("window_name", _missing("Workload window name was absent.")),
                "operation_id": row.get("operation_id", _missing("Workload operation identity was absent.")),
                "observed_status": row.get("status"),
                "metrics": selected,
            }
        )
    return {"status": "OBSERVED", "window_count": len(windows), "windows": windows}


def _management(artifacts: Mapping[str, Any]) -> dict[str, Any]:
    source = _object(artifacts, "management_results")
    scenarios = _scenario_rows(artifacts, {"add_remove_node", "reshard_rebalance", "rolling_restart", "bounded_stability"})
    commands = _rows(artifacts, "command_log")
    result = source.get("result") if isinstance(source.get("result"), dict) else {}
    operations = result.get("operations") if isinstance(result.get("operations"), list) else source.get("operation_results", [])
    return {
        "status": "OBSERVED",
        "observed_status": source.get("status"),
        "operation_sequence": list(source.get("operation_sequence", ())) if isinstance(source.get("operation_sequence"), list) else [],
        "operations": operations if isinstance(operations, list) else [],
        "scenario_results": scenarios,
        "command_count": len(commands),
    }


def _failover(
    artifacts: Mapping[str, Any], missing: list[dict[str, Any]]
) -> dict[str, Any]:
    source = _object(artifacts, "fault_results")
    details = source.get("failover_details")
    if not isinstance(details, dict):
        details = _record_missing(
            missing,
            "failover",
            "Validated fault evidence did not contain failover detail measurements.",
            "fault_results",
        )
    return {
        "status": "OBSERVED",
        "scenario_result": next(iter(_scenario_rows(artifacts, {"primary_failover"})), _missing("Primary failover scenario result was absent.")),
        "target_primary_logical_id": source.get("target_primary_logical_id", _missing("Failover target identity was absent.")),
        "replacement_logical_id": source.get("replacement_logical_id", _missing("Promoted replacement identity was absent.")),
        "details": details,
    }


def _recovery(
    artifacts: Mapping[str, Any], missing: list[dict[str, Any]]
) -> dict[str, Any]:
    stability = _object(artifacts, "stability_results")
    health = stability.get("recovery_health")
    if not isinstance(health, dict):
        health = _object(artifacts, "fault_results").get("recovery_health")
    if not isinstance(health, dict):
        marker = _record_missing(
            missing,
            "recovery",
            "No validated recovery health snapshot was present.",
            "stability_results",
        )
        return marker
    return {"status": "OBSERVED", "health": health}


def _errors(artifacts: Mapping[str, Any]) -> dict[str, Any]:
    commands = [*_rows(artifacts, "command_log"), *_rows(artifacts, "fault_command_log")]
    command_errors = [
        {
            "command_id": row.get("command_id"),
            "scenario_id": row.get("scenario_id"),
            "observed_status": row.get("status"),
            "error_type": row.get("error_type", ""),
        }
        for row in commands
        if row.get("status") != "PASS" or row.get("error_type")
    ]
    windows = _object(artifacts, "workload_windows").get("windows", [])
    failed_windows = [row.get("window_name") for row in windows if isinstance(row, dict) and row.get("status") != "PASS"] if isinstance(windows, list) else []
    return {
        "status": "OBSERVED",
        "command_error_count": len(command_errors),
        "command_errors": command_errors,
        "failed_window_count": len(failed_windows),
        "failed_windows": failed_windows,
    }


def _cleanup(artifacts: Mapping[str, Any]) -> dict[str, Any]:
    source = _object(artifacts, "cleanup_report")
    remaining = source.get("resources_remaining")
    cleanup_errors = source.get("cleanup_errors")
    return {
        "status": "OBSERVED",
        "observed_status": source.get("status"),
        "residual_resources": list(remaining) if isinstance(remaining, list) else [],
        "cleanup_errors": list(cleanup_errors) if isinstance(cleanup_errors, list) else [],
    }


def _bottlenecks(
    lifecycle: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    missing: list[dict[str, Any]],
) -> dict[str, Any]:
    steps = [
        {"kind": "lifecycle_step", "id": row.get("id"), "duration_ms": row.get("duration_ms")}
        for row in lifecycle.get("steps", ())
        if isinstance(row, Mapping) and _number(row.get("duration_ms"))
    ]
    commands = []
    for stream in ("command_log", "fault_command_log"):
        for row in _rows(artifacts, stream):
            duration = row.get("duration_ms")
            if not _number(duration) and _number(row.get("started_at_unix_ms")) and _number(row.get("ended_at_unix_ms")):
                duration = float(row["ended_at_unix_ms"]) - float(row["started_at_unix_ms"])
            if _number(duration):
                commands.append(
                    {
                        "kind": "command",
                        "id": row.get("command_id"),
                        "scenario_id": row.get("scenario_id"),
                        "duration_ms": duration,
                    }
                )
    rows = sorted([*steps, *commands], key=lambda row: float(row["duration_ms"]), reverse=True)[:10]
    if not rows:
        marker = _record_missing(
            missing,
            "bottlenecks",
            "No measured lifecycle or command durations were present.",
            "lifecycle_timeline",
        )
        return {**marker, "slowest": []}
    return {"status": "OBSERVED", "slowest": rows}


def _scenario_rows(
    artifacts: Mapping[str, Any], selected: set[str]
) -> list[dict[str, Any]]:
    source = _object(artifacts, "scenario_results")
    rows = source.get("scenarios") if isinstance(source.get("scenarios"), list) else []
    return [
        {
            "id": row.get("id"),
            "observed_status": row.get("status"),
            "event_ids": list(row.get("event_ids", ())) if isinstance(row.get("event_ids"), list) else [],
            "command_ids": list(row.get("command_ids", ())) if isinstance(row.get("command_ids"), list) else [],
        }
        for row in rows
        if isinstance(row, dict) and row.get("id") in selected
    ]


def _source_missing_items(artifacts: Mapping[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(value: Any, kind: str, path: str) -> None:
        if isinstance(value, dict):
            if value.get("status") in MISSING_STATUSES:
                found.append(
                    {
                        "surface": kind,
                        "source_kind": kind,
                        "source_path": path,
                        "status": value["status"],
                        "reason": str(value.get("reason", "Validated source did not provide a reason.")),
                    }
                )
            for key, item in value.items():
                visit(item, kind, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, kind, f"{path}[{index}]")

    for kind, value in artifacts.items():
        visit(value, kind, "$")
    return found


def _record_missing(
    target: list[dict[str, Any]], surface: str, reason: str, source_kind: str
) -> dict[str, str]:
    marker = {
        "surface": surface,
        "source_kind": source_kind,
        "status": "MISSING",
        "reason": reason,
    }
    target.append(marker)
    return {"status": "MISSING", "reason": reason}


def _deduplicate_missing(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("surface", "unknown")),
            str(row.get("source_kind", "unknown")),
            str(row.get("source_path", "")),
            str(row.get("reason", "")),
        )
        by_key.setdefault(key, row)
    return [by_key[key] for key in sorted(by_key)]


def _source_ref(record: ArtifactRecord) -> dict[str, Any]:
    return {
        "kind": record.kind,
        "path": record.path,
        "format": record.format,
        "sha256": record.sha256,
        "source_path": record.source_path,
        "source_sha256": record.source_sha256,
        "transform_id": record.transform_id,
        "provenance_node_id": record.provenance_node_id,
    }


def _object(artifacts: Mapping[str, Any], kind: str) -> dict[str, Any]:
    value = artifacts.get(kind)
    return value if isinstance(value, dict) else {}


def _rows(artifacts: Mapping[str, Any], kind: str) -> list[dict[str, Any]]:
    value = artifacts.get(kind)
    return value if isinstance(value, list) else []


def _missing(reason: str) -> dict[str, str]:
    return {"status": "MISSING", "reason": reason}


def _number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _plain_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _required_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValidatedAnalysisError(
            f"validated evidence is missing its {label} digest"
        )
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _mutable_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _mutable_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mutable_json(item) for item in value]
    return value
