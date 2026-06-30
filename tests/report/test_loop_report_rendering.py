from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))

from schema_validator import load_json, validate


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas/artifact/loop_report_index.schema.json"


def run_renderer(out_dir: Path, input_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/render_audit_report.py",
            "--input-dir",
            str(input_dir or REPO_ROOT / "artifacts/loop_engineering/reports"),
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_renderer_emits_required_outputs_and_schema_valid_index(tmp_path: Path) -> None:
    result = run_renderer(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    required = {
        "index.html",
        "coverage_matrix.csv",
        "coverage_heatmap.svg",
        "scale_ladder.svg",
        "p13_timing_waterfall.svg",
        "missing_metrics.csv",
        "provenance_graph.json",
        "report_index.json",
    }
    assert required <= {path.name for path in tmp_path.iterdir()}

    index = json.loads((tmp_path / "report_index.json").read_text(encoding="utf-8"))
    assert validate(index, load_json(SCHEMA)) == []
    assert index["status"] == "PASS"
    assert index["source_of_truth"] is False
    assert {Path(report["path"]).name for report in index["reports"]} >= (
        required - {"report_index.json", "provenance_graph.json"}
    )
    assert all(report["source_of_truth"] is False for report in index["reports"])
    assert any(source["path"].endswith("coverage_matrix.json") for source in index["source_artifacts"])
    assert any(source["path"].endswith("provenance_graph.json") for source in index["source_artifacts"])

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Valkey Scale Lab Audit Report" in html
    assert "artifacts/loop_engineering/reports/coverage_matrix.json" in html
    assert "P14 opt-in dry-run" in html
    assert "p13_timing_waterfall.svg" in html


def test_coverage_matrix_csv_matches_source_entries(tmp_path: Path) -> None:
    result = run_renderer(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr

    source = json.loads((REPO_ROOT / "artifacts/loop_engineering/reports/coverage_matrix.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((tmp_path / "coverage_matrix.csv").open(encoding="utf-8")))

    assert len(rows) == len(source["entries"])
    assert rows[0].keys() == {
        "layer",
        "surface",
        "status",
        "evidence_class",
        "metric_count",
        "real_valkey_coverage",
        "dry_run_only",
        "reason",
        "source_artifacts",
    }
    assert rows[0]["layer"] == source["layers"][0]
    assert rows[0]["surface"] == source["surfaces"][0]
    dry_rows = [row for row in rows if row["layer"] == "1000-dry-run"]
    assert dry_rows
    assert all(row["real_valkey_coverage"] == "false" for row in dry_rows)
    assert all(row["dry_run_only"] == "true" for row in dry_rows)


def test_missing_metrics_csv_preserves_reasons_and_statuses(tmp_path: Path) -> None:
    result = run_renderer(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr

    rows = list(csv.DictReader((tmp_path / "missing_metrics.csv").open(encoding="utf-8")))
    statuses = {row["status"] for row in rows}
    assert {"MISSING", "SKIPPED_WITH_REASON", "NO_BASELINE_YET"} <= statuses
    assert all(row["reason"] for row in rows)
    assert any(row["source_artifact"].endswith(".json") for row in rows)


def test_renderer_rejects_measured_metrics_sourced_from_rendered_views(tmp_path: Path) -> None:
    input_dir = tmp_path / "inputs"
    shutil.copytree(REPO_ROOT / "artifacts/loop_engineering/reports", input_dir)
    catalog_path = input_dir / "metric_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["metrics"][0]["value_status"] = "MEASURED"
    catalog["metrics"][0]["value"] = 1
    catalog["metrics"][0]["source_artifact"] = "artifacts/loop_engineering/reports/index.html"
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")

    result = run_renderer(tmp_path / "out", input_dir=input_dir)

    assert result.returncode != 0
    assert "rendered view cannot be a measured metric source" in result.stderr
