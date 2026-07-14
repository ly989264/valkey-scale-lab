from __future__ import annotations

import json
from pathlib import Path

from scripts.schema_validator import load_json, validate
from valkey_scale_lab.analysis import create_analysis_summary
from valkey_scale_lab.artifacts import build_run_metadata, create_run_context, load_run_manifest, write_run_manifest, write_run_metadata
from valkey_scale_lab.cli import main
from valkey_scale_lab.report import render_report

ROOT = Path(__file__).resolve().parents[2]


def test_run_context_writes_metadata_and_manifest_schema_valid(tmp_path: Path) -> None:
    config = tmp_path / "config.yml"
    config.write_text("cluster:\n  shards: 1\n", encoding="utf-8")
    context = create_run_context("run-metadata-unit", tmp_path / "runs")

    metadata = build_run_metadata(
        context,
        config_path=config,
        inventory={"nodes": [{"logical_id": "shard-0000-primary"}]},
        runtime_provider="fake",
        runtime_mode="unit",
        port_ranges={"client": {"start": 7000, "end": 7001}},
    )
    write_run_metadata(context, metadata)
    manifest = write_run_manifest(context, metadata=metadata)

    assert context.artifact_root.is_dir()
    assert context.log_root.is_dir()
    assert context.report_root.is_dir()
    assert context.state_root.is_dir()
    assert context.metadata_path == context.state_root / "run_metadata.json"
    assert context.manifest_path == context.state_root / "run_manifest.json"
    assert manifest["artifact_root"].endswith("runs/run-metadata-unit/artifacts")
    assert validate(metadata, load_json(ROOT / "schemas/artifact/run_metadata.schema.json")) == []
    assert validate(manifest, load_json(ROOT / "schemas/artifact/run_manifest.schema.json")) == []
    assert load_run_manifest(context.run_root)["run_id"] == "run-metadata-unit"


def test_analysis_and_report_accept_run_root_and_show_metadata(tmp_path: Path) -> None:
    context = create_run_context("run-metadata-analysis", tmp_path / "runs")
    _write_source_artifacts(context.artifact_root)
    metadata = build_run_metadata(context, runtime_provider="fake", runtime_mode="smoke")
    write_run_metadata(context, metadata)
    write_run_manifest(context, metadata=metadata)

    analysis_path = context.artifact_root / "analysis_summary.json"
    summary = create_analysis_summary(context.run_root, analysis_path)
    index = render_report(analysis_path, context.report_root, context.artifact_root / "report_index.json")

    assert summary["source"]["input_kind"] == "run_manifest"
    assert summary["run_id"] == "run-metadata-analysis"
    assert summary["created_at"] == metadata["created_at"]
    assert summary["run_metadata"]["run_id"] == "run-metadata-analysis"
    assert summary["run_manifest_ref"]["path"].endswith("run_manifest.json")
    assert index["run_id"] == "run-metadata-analysis"
    assert index["created_at"] == metadata["created_at"]
    assert index["run_metadata_ref"]["path"].endswith("run_metadata.json")
    assert "运行元数据" in (context.report_root / "report.md").read_text(encoding="utf-8")
    assert "run-metadata-analysis" in (context.report_root / "index.html").read_text(encoding="utf-8")


def test_legacy_artifact_directory_remains_supported(tmp_path: Path) -> None:
    source = tmp_path / "legacy_artifacts"
    _write_source_artifacts(source)

    summary = create_analysis_summary(source, tmp_path / "analysis_summary.json")

    assert summary["source"]["input_kind"] == "artifact_dir"
    assert summary["run_metadata"]["status"] == "SKIPPED_WITH_REASON"


def test_cli_run_init_defaults_to_run_scoped_state_metadata(tmp_path: Path, capsys) -> None:
    exit_code = main(["run", "init", "--run-id", "run-metadata-cli", "--runs-root", str(tmp_path / "runs")])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "run-metadata-cli" in output
    run_root = tmp_path / "runs" / "run-metadata-cli"
    assert (run_root / "artifacts").is_dir()
    assert (run_root / "logs").is_dir()
    assert (run_root / "reports").is_dir()
    assert (run_root / "state" / "run_metadata.json").exists()
    assert (run_root / "state" / "run_manifest.json").exists()


def test_blocked_dry_run_and_failure_fixtures_use_structured_reasons() -> None:
    schema = load_json(ROOT / "schemas/artifact/run_metadata.schema.json")
    for name in ["blocked", "dry_run", "failure"]:
        payload = load_json(ROOT / "tests/fixtures/run_metadata" / name / "run_metadata.json")
        assert validate(payload, schema) == []
        reasoned = [value for value in payload.values() if isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON"}]
        assert reasoned, name
        assert all(value.get("reason") for value in reasoned)


def _write_source_artifacts(source: Path) -> None:
    source.mkdir(parents=True, exist_ok=True)
    _write(
        source / "run_summary.json",
        {
            "capability_id": "fault_matrix",
            "run_id": "source-run",
            "status": "PASS",
            "missing_metrics": [{"metric": "split_brain_duration_ms", "status": "MISSING", "reason": "not measured"}],
        },
    )
    _write(
        source / "valkey_e2e_evidence.json",
        {
            "status": "PASS",
            "real_valkey": True,
            "valkey_versions": ["9.1.0"],
            "nodes_observed": 3,
            "cluster_state_observed": "ok",
        },
    )
    _write(
        source / "failover_report.json",
        {
            "status": "PASS",
            "failovers": [{"target_logical_id": "shard-0000-primary", "failover_latency_ms": 7}],
            "summary": {
                "split_brain_duration_ms": {
                    "status": "MISSING",
                    "reason": "not measured",
                    "impact": "split-brain window cannot be compared",
                }
            },
        },
    )
    _write(source / "cleanup_report.json", {"status": "PASS", "resources_remaining": []})


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")
