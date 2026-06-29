from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab.report import render_report


def test_report_renderer_writes_index_tables_chart_and_phase_summary(tmp_path: Path) -> None:
    analysis = {
        "schema_version": "v1",
        "artifact_type": "analysis_summary",
        "phase_id": "P09_ANALYSIS_REPORTING",
        "run_id": "p09-run",
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "test", "version": "v1"},
        "status": "PASS",
        "source": {"phase_id": "P08_FAILOVER_SPLIT_BRAIN"},
        "findings": [{"name": "failover", "status": "PASS"}],
        "metrics": [
            {"name": "failover_latency_ms", "status": "PASS", "value": 10.0, "unit": "ms"},
            {"name": "split_brain_duration_ms", "status": "MISSING", "value": None, "unit": "ms"},
        ],
        "missing_metrics": [
            {"metric": "split_brain_duration_ms", "status": "MISSING", "reason": "not measured"}
        ],
        "baseline_comparison": {
            "comparisons": [
                {
                    "metric": "failover_latency_ms",
                    "current_value": 10.0,
                    "baseline_value": None,
                    "delta": None,
                    "unit": "ms",
                    "status": "NO_BASELINE_YET",
                }
            ]
        },
    }
    analysis_path = tmp_path / "analysis_summary.json"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")

    index = render_report(analysis_path, tmp_path / "report", tmp_path / "report_index.json")

    report_paths = {Path(item["path"]).name for item in index["reports"]}
    assert {"index.html", "report.md", "metrics.csv", "missing_metrics.csv", "baseline_comparison.csv", "metric_chart.svg"} == report_paths
    assert (tmp_path / "phase_summary.json").exists()
    assert "MISSING" in (tmp_path / "report" / "missing_metrics.csv").read_text(encoding="utf-8")


def test_report_renderer_marks_empty_missing_metrics_as_none(tmp_path: Path) -> None:
    analysis = {
        "schema_version": "v1",
        "artifact_type": "analysis_summary",
        "phase_id": "P09_ANALYSIS_REPORTING",
        "run_id": "p09-empty-missing",
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "test", "version": "v1"},
        "status": "PASS",
        "source": {"phase_id": "P08_FAILOVER_SPLIT_BRAIN"},
        "findings": [],
        "metrics": [{"name": "cluster_state_ok", "status": "PASS", "value": 1, "unit": "bool"}],
        "missing_metrics": [],
        "baseline_comparison": {"comparisons": []},
    }
    analysis_path = tmp_path / "analysis_summary.json"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")

    render_report(analysis_path, tmp_path / "report", tmp_path / "report_index.json")

    markdown = (tmp_path / "report" / "report.md").read_text(encoding="utf-8")
    html = (tmp_path / "report" / "index.html").read_text(encoding="utf-8")
    assert "- none" in markdown
    assert '<tr><td colspan="3">none</td></tr>' in html
