from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__
from valkey_scale_lab.artifacts import artifact_record, load_json as load_artifact_json, resolve_artifact_input

PHASE_ID = "P09_ANALYSIS_REPORTING"
RUN_ID = "P09_ANALYSIS_REPORTING-analysis-20260628"
CREATED_AT = "2026-06-28T00:00:00Z"


class AnalysisError(RuntimeError):
    pass


def create_analysis_summary(input_dir: str | Path, out_path: str | Path) -> dict[str, Any]:
    source_dir, run_manifest = resolve_artifact_input(input_dir)
    if not source_dir.exists():
        raise AnalysisError(f"input artifact directory does not exist: {source_dir}")

    phase_summary = _load_required(source_dir / "phase_summary.json")
    evidence = _load_required(source_dir / "valkey_e2e_evidence.json")
    failover = _load_required(source_dir / "failover_report.json")
    cleanup = _load_required(source_dir / "cleanup_report.json")
    setup_telemetry = _load_optional(source_dir / "setup_telemetry.json")

    missing_metrics = _collect_missing_metrics(phase_summary, failover, setup_telemetry)
    failovers = list(failover.get("failovers", []))
    primary_failover = failovers[0] if failovers else {}
    failover_latency = primary_failover.get("failover_latency_ms", "MISSING")
    versions = sorted(str(item) for item in evidence.get("valkey_versions", []) if item)

    metrics = [
        _metric("nodes_observed_after_fault", evidence.get("nodes_observed", "MISSING"), "count"),
        _metric("failover_latency_ms", failover_latency, "ms"),
        _metric_from_optional("split_brain_duration_ms", failover.get("summary", {}).get("split_brain_duration_ms"), "ms"),
        _metric("cleanup_resources_remaining", len(cleanup.get("resources_remaining", [])), "count"),
    ]
    findings = [
        {
            "name": "source_phase",
            "status": phase_summary.get("status", "MISSING"),
            "source_phase_id": phase_summary.get("phase_id", "MISSING"),
            "source_run_id": phase_summary.get("run_id", "MISSING"),
        },
        {
            "name": "real_valkey_evidence",
            "status": evidence.get("status", "MISSING"),
            "real_valkey": evidence.get("real_valkey", False),
            "valkey_versions": versions,
            "cluster_state_observed": evidence.get("cluster_state_observed", "MISSING"),
            "nodes_observed": evidence.get("nodes_observed", "MISSING"),
        },
        {
            "name": "failover",
            "status": failover.get("status", "MISSING"),
            "target_logical_id": primary_failover.get("target_logical_id", "MISSING"),
            "old_primary_node_id": primary_failover.get("old_primary_node_id", "MISSING"),
            "promoted_node_id": primary_failover.get("promoted_node_id", "MISSING"),
            "failover_latency_ms": failover_latency,
        },
        {
            "name": "cleanup",
            "status": cleanup.get("status", "MISSING"),
            "resources_remaining": cleanup.get("resources_remaining", []),
        },
        {
            "name": "setup_telemetry",
            "status": setup_telemetry.get("status", "SKIPPED_WITH_REASON"),
            "node_count": setup_telemetry.get("node_count", "MISSING"),
            "total_setup_ms": setup_telemetry.get("metrics", {}).get("total_setup_ms", "MISSING") if isinstance(setup_telemetry.get("metrics"), dict) else "MISSING",
        },
    ]

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    baseline_path = out.parent / "baseline_comparison.json"
    metadata_refs = _metadata_refs(run_manifest)
    run_metadata = _load_run_metadata(run_manifest)
    output_run_id = _metadata_value(run_metadata, "run_id", RUN_ID)
    output_created_at = _metadata_value(run_metadata, "created_at", CREATED_AT)
    baseline = _baseline_comparison(metrics, source_dir, run_id=output_run_id, created_at=output_created_at)
    _write_json(baseline_path, baseline)

    summary = {
        "schema_version": "v1",
        "artifact_type": "analysis_summary",
        "phase_id": PHASE_ID,
        "run_id": output_run_id,
        "created_at": output_created_at,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "source": {
            "input_dir": source_dir.as_posix(),
            "input_kind": "run_manifest" if run_manifest else "artifact_dir",
            "phase_id": phase_summary.get("phase_id", "MISSING"),
            "run_id": phase_summary.get("run_id", "MISSING"),
        },
        "source_artifacts": [_artifact_record(path) for path in _source_artifact_paths(source_dir, out, baseline_path)],
        "run_manifest_ref": metadata_refs.get("run_manifest_ref"),
        "run_metadata_ref": metadata_refs.get("run_metadata_ref"),
        "run_metadata": run_metadata,
        "findings": findings,
        "metrics": metrics,
        "missing_metrics": missing_metrics,
        "setup_telemetry": setup_telemetry
        or {
            "status": "SKIPPED_WITH_REASON",
            "reason": "Input artifacts did not include setup_telemetry.json.",
        },
        "setup_aggregates": _setup_aggregates(setup_telemetry),
        "baseline_comparison": baseline,
        "sidecars": [
            {
                "path": _rel(baseline_path),
                "artifact_type": "baseline_comparison",
                "sha256": _sha256_file(baseline_path),
            }
        ],
    }
    _write_json(out, summary)
    return summary


def _load_required(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AnalysisError(f"required source artifact missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AnalysisError(f"source artifact must be a JSON object: {path}")
    return data


def _load_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _load_required(path)


def _metadata_refs(run_manifest: dict[str, Any] | None) -> dict[str, Any]:
    if not run_manifest:
        return {
            "run_manifest_ref": {
                "status": "SKIPPED_WITH_REASON",
                "reason": "Legacy artifact directory input did not include a run_manifest.json.",
            },
            "run_metadata_ref": {
                "status": "SKIPPED_WITH_REASON",
                "reason": "Legacy artifact directory input did not include a run_metadata.json.",
            },
        }
    manifest_path = Path(str(run_manifest["_manifest_path"]))
    metadata_ref = run_manifest.get("run_metadata_ref")
    if not isinstance(metadata_ref, dict):
        metadata_ref = {
            "status": "MISSING",
            "reason": "run_manifest.json did not include run_metadata_ref.",
            "impact": "Analysis cannot link report output back to run metadata.",
        }
    return {
        "run_manifest_ref": {
            "status": "SKIPPED_WITH_REASON",
            "reason": "The final run manifest is refreshed after analysis/report artifacts are written, so analysis records the manifest path without a pre-refresh hash.",
            "path": _rel(manifest_path),
        },
        "run_metadata_ref": metadata_ref,
    }


def _load_run_metadata(run_manifest: dict[str, Any] | None) -> dict[str, Any]:
    if not run_manifest:
        return {
            "status": "SKIPPED_WITH_REASON",
            "reason": "Legacy artifact directory input did not include run metadata.",
        }
    metadata_ref = run_manifest.get("run_metadata_ref")
    manifest_path = Path(str(run_manifest["_manifest_path"]))
    if not isinstance(metadata_ref, dict) or not isinstance(metadata_ref.get("path"), str):
        return {
            "status": "MISSING",
            "reason": "run_manifest.json did not include a readable run_metadata_ref.path.",
            "impact": "Analysis cannot display run-level provenance fields.",
        }
    metadata_path = Path(metadata_ref["path"])
    if not metadata_path.is_absolute():
        metadata_path = Path.cwd() / metadata_path
    try:
        return load_artifact_json(metadata_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "MISSING",
            "reason": f"Could not read run metadata: {exc}",
            "impact": "Analysis cannot display run-level provenance fields.",
        }


def _collect_missing_metrics(phase_summary: dict[str, Any], failover: dict[str, Any], setup_telemetry: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for item in phase_summary.get("missing_metrics", []):
        if isinstance(item, dict) and item.get("metric"):
            found[str(item["metric"])] = dict(item)
    for name, value in failover.get("summary", {}).items():
        if isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON"}:
            metric = str(name)
            found.setdefault(
                metric,
                {
                    "metric": metric,
                    "status": value["status"],
                    "reason": str(value.get("reason", "source artifact reported metric unavailable")),
                    "source": "failover_report.summary",
                },
            )
    if setup_telemetry:
        for item in setup_telemetry.get("missing_metrics", []):
            if isinstance(item, dict) and item.get("metric"):
                metric = f"setup.{item['metric']}"
                found.setdefault(
                    metric,
                    {
                        "metric": metric,
                        "status": item.get("status", "MISSING"),
                        "reason": item.get("reason", "setup telemetry reported metric unavailable"),
                        "impact": item.get("impact", ""),
                        "source": "setup_telemetry.missing_metrics",
                    },
                )
    return [found[key] for key in sorted(found)]


def _setup_aggregates(setup_telemetry: dict[str, Any]) -> dict[str, Any]:
    if not setup_telemetry:
        return {
            "status": "SKIPPED_WITH_REASON",
            "reason": "setup_telemetry.json was not present in the input artifacts.",
        }
    metrics = setup_telemetry.get("metrics", {})
    numeric = [
        {"metric": name, "value_ms": round(float(value), 3)}
        for name, value in metrics.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ] if isinstance(metrics, dict) else []
    phase_duration_ranking = sorted(numeric, key=lambda item: item["value_ms"], reverse=True)
    return {
        "status": setup_telemetry.get("status", "MISSING"),
        "node_count": setup_telemetry.get("node_count", "MISSING"),
        "phase_duration_ranking": phase_duration_ranking,
        "slowest_nodes_topN": setup_telemetry.get("slowest_nodes_topN", []),
        "slowest_replica_replicate_topN": setup_telemetry.get("slowest_replica_replicate_topN", []),
        "cleanup": setup_telemetry.get("cleanup", {}),
        "same_schema_scale_rungs": setup_telemetry.get("same_schema_scale_rungs", []),
    }


def _metric(name: str, value: Any, unit: str) -> dict[str, Any]:
    if value == "MISSING":
        return {"name": name, "status": "MISSING", "value": None, "unit": unit, "reason": "source artifact did not provide metric"}
    return {"name": name, "status": "PASS", "value": value, "unit": unit}


def _metric_from_optional(name: str, value: Any, unit: str) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON"}:
        return {
            "name": name,
            "status": value["status"],
            "value": value.get("value"),
            "unit": unit,
            "reason": value.get("reason", "source artifact reported metric unavailable"),
        }
    if isinstance(value, dict):
        return {"name": name, "status": "PASS", "value": value.get("value"), "unit": unit}
    return _metric(name, value if value is not None else "MISSING", unit)


def _metadata_value(metadata: dict[str, Any], key: str, fallback: str) -> str:
    value = metadata.get(key)
    if isinstance(value, str) and value:
        return value
    return fallback


def _baseline_comparison(metrics: list[dict[str, Any]], source_dir: Path, *, run_id: str = RUN_ID, created_at: str = CREATED_AT) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": "baseline_comparison",
        "phase_id": PHASE_ID,
        "run_id": run_id,
        "created_at": created_at,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "NO_BASELINE_YET",
        "baseline_source": {
            "status": "SKIPPED_WITH_REASON",
            "reason": "No versioned baseline artifact exists for the first analysis-reporting phase.",
        },
        "source_dir": source_dir.as_posix(),
        "comparisons": [
            {
                "metric": metric["name"],
                "current_value": metric.get("value"),
                "unit": metric.get("unit"),
                "status": "NO_BASELINE_YET" if metric.get("status") == "PASS" else metric.get("status"),
                "baseline_value": None,
                "delta": None,
            }
            for metric in metrics
        ],
    }


def _artifact_record(path: Path) -> dict[str, str]:
    return {"path": _rel(path), "sha256": _sha256_file(path)}


def _source_artifact_paths(source_dir: Path, out: Path, baseline_path: Path) -> list[Path]:
    excluded = {out.resolve(), baseline_path.resolve()}
    return [path for path in sorted(source_dir.glob("*.json")) if path.resolve() not in excluded]


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
