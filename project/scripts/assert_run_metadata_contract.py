#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from schema_validator import load_json, validate

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="vslab-run-metadata-") as tmp:
        tmp_path = Path(tmp)
        _exercise_contract(tmp_path, errors)
    if errors:
        print("run metadata contract: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("run metadata contract: PASS")
    return 0


def _exercise_contract(tmp_path: Path, errors: list[str]) -> None:
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from valkey_scale_lab.analysis import create_analysis_summary
    from valkey_scale_lab.artifacts import build_run_metadata, create_run_context, load_run_manifest, write_run_manifest, write_run_metadata
    from valkey_scale_lab.report import render_report

    context = create_run_context("run-metadata-gate", tmp_path / "runs")
    _write_source_artifacts(context.artifact_root)
    metadata = build_run_metadata(context, runtime_provider="fake", runtime_mode="gate")
    write_run_metadata(context, metadata)
    manifest = write_run_manifest(context, metadata=metadata)

    errors.extend(_schema_errors("run_metadata", metadata, "schemas/artifact/run_metadata.schema.json"))
    errors.extend(_schema_errors("run_manifest", manifest, "schemas/artifact/run_manifest.schema.json"))
    _require_dirs(context, errors)

    loaded = load_run_manifest(context.manifest_path)
    if loaded.get("run_id") != "run-metadata-gate":
        errors.append("manifest reader did not preserve run_id")

    analysis = create_analysis_summary(context.run_root, context.artifact_root / "analysis_summary.json")
    index = render_report(context.artifact_root / "analysis_summary.json", context.report_root, context.artifact_root / "report_index.json")
    if analysis.get("source", {}).get("input_kind") != "run_manifest":
        errors.append("analysis did not prefer run manifest for run-root input")
    if not isinstance(analysis.get("run_metadata"), dict) or analysis["run_metadata"].get("run_id") != "run-metadata-gate":
        errors.append("analysis did not attach run metadata")
    if analysis.get("run_id") != "run-metadata-gate" or analysis.get("created_at") != metadata.get("created_at"):
        errors.append("analysis did not derive run_id/created_at from run metadata")
    if index.get("run_id") != "run-metadata-gate" or index.get("created_at") != metadata.get("created_at"):
        errors.append("report index did not derive run_id/created_at from analysis/run metadata")
    if not isinstance(index.get("run_metadata_ref"), dict) or "path" not in index["run_metadata_ref"]:
        errors.append("report_index did not reference run metadata")
    if "运行元数据" not in (context.report_root / "report.md").read_text(encoding="utf-8"):
        errors.append("markdown report body did not show run metadata")
    if str(context.artifact_root).find("/runs/") == -1:
        errors.append("new run did not default to runs/<run_id>/artifacts")

    legacy = tmp_path / "legacy"
    _write_source_artifacts(legacy)
    legacy_analysis = create_analysis_summary(legacy, tmp_path / "legacy_analysis.json")
    if legacy_analysis.get("run_metadata", {}).get("status") != "SKIPPED_WITH_REASON":
        errors.append("legacy explicit artifact directory did not remain compatible with structured skip metadata")
    _validate_reasoned_fixtures(errors)
    _validate_report_input_missing(errors, tmp_path)
    _validate_manifest_freshness(context, errors)


def _schema_errors(name: str, payload: dict[str, Any], schema_path: str) -> list[str]:
    return [f"{name}: {error}" for error in validate(payload, load_json(ROOT / schema_path))]


def _validate_reasoned_fixtures(errors: list[str]) -> None:
    schema = load_json(ROOT / "schemas/artifact/run_metadata.schema.json")
    for name in ["blocked", "dry_run", "failure"]:
        path = ROOT / "tests/fixtures/run_metadata" / name / "run_metadata.json"
        if not path.exists():
            errors.append(f"missing {name} run metadata fixture")
            continue
        payload = load_json(path)
        errors.extend(_schema_errors(f"{name} fixture", payload, "schemas/artifact/run_metadata.schema.json"))
        reasoned = [value for value in payload.values() if isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON"}]
        if not reasoned:
            errors.append(f"{name} fixture did not include structured missing/skipped values")
        for value in reasoned:
            if not value.get("reason"):
                errors.append(f"{name} fixture has status without reason: {value}")


def _validate_report_input_missing(errors: list[str], tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from valkey_scale_lab.report import render_report, ReportError

    try:
        render_report(tmp_path / "missing_analysis.json", tmp_path / "missing-report", tmp_path / "missing-report-index.json")
    except ReportError as exc:
        if "does not exist" not in str(exc):
            errors.append(f"report missing-input path did not explain missing source: {exc}")
    else:
        errors.append("report missing-input path unexpectedly succeeded")


def _validate_manifest_freshness(context: Any, errors: list[str]) -> None:
    from valkey_scale_lab.artifacts import write_run_manifest

    write_run_manifest(context)
    manifest = load_json(context.manifest_path)
    paths = {item.get("path", "") for item in manifest.get("artifacts", []) if isinstance(item, dict)}
    expected_suffixes = ["phase_summary.json", "analysis_summary.json", "report_index.json"]
    for suffix in expected_suffixes:
        if not any(path.endswith(suffix) for path in paths):
            errors.append(f"manifest did not include refreshed artifact ending with {suffix}")


def _require_dirs(context: Any, errors: list[str]) -> None:
    for attr in ["artifact_root", "log_root", "report_root", "state_root"]:
        path = getattr(context, attr)
        if not path.is_dir():
            errors.append(f"{attr} was not created: {path}")


def _write_source_artifacts(source: Path) -> None:
    source.mkdir(parents=True, exist_ok=True)
    _write(
        source / "phase_summary.json",
        {
            "phase_id": "P08_FAILOVER_SPLIT_BRAIN",
            "run_id": "source-run",
            "status": "PASS",
            "missing_metrics": [{"metric": "split_brain_duration_ms", "status": "MISSING", "reason": "not measured"}],
        },
    )
    _write(
        source / "valkey_e2e_evidence.json",
        {"status": "PASS", "real_valkey": True, "valkey_versions": ["9.1.0"], "nodes_observed": 3, "cluster_state_observed": "ok"},
    )
    _write(
        source / "failover_report.json",
        {
            "status": "PASS",
            "failovers": [{"target_logical_id": "shard-0000-primary", "failover_latency_ms": 7}],
            "summary": {"split_brain_duration_ms": {"status": "MISSING", "reason": "not measured"}},
        },
    )
    _write(source / "cleanup_report.json", {"status": "PASS", "resources_remaining": []})


def _write(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
