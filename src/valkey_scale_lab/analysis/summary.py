from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__

PHASE_ID = "P09_ANALYSIS_REPORTING"
RUN_ID = "P09_ANALYSIS_REPORTING-analysis-20260628"
CREATED_AT = "2026-06-28T00:00:00Z"


class AnalysisError(RuntimeError):
    pass


def create_analysis_summary(input_dir: str | Path, out_path: str | Path) -> dict[str, Any]:
    source_dir = Path(input_dir)
    if not source_dir.exists():
        raise AnalysisError(f"input artifact directory does not exist: {source_dir}")

    phase_summary = _load_required(source_dir / "phase_summary.json")
    evidence = _load_required(source_dir / "valkey_e2e_evidence.json")
    failover = _load_required(source_dir / "failover_report.json")
    cleanup = _load_required(source_dir / "cleanup_report.json")

    missing_metrics = _collect_missing_metrics(phase_summary, failover)
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
    ]

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    baseline_path = out.parent / "baseline_comparison.json"
    baseline = _baseline_comparison(metrics, source_dir)
    _write_json(baseline_path, baseline)

    summary = {
        "schema_version": "v1",
        "artifact_type": "analysis_summary",
        "phase_id": PHASE_ID,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "source": {
            "input_dir": source_dir.as_posix(),
            "phase_id": phase_summary.get("phase_id", "MISSING"),
            "run_id": phase_summary.get("run_id", "MISSING"),
        },
        "source_artifacts": [_artifact_record(path) for path in sorted(source_dir.glob("*.json"))],
        "findings": findings,
        "metrics": metrics,
        "missing_metrics": missing_metrics,
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


def _collect_missing_metrics(phase_summary: dict[str, Any], failover: dict[str, Any]) -> list[dict[str, Any]]:
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
    return [found[key] for key in sorted(found)]


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


def _baseline_comparison(metrics: list[dict[str, Any]], source_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": "baseline_comparison",
        "phase_id": PHASE_ID,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
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
