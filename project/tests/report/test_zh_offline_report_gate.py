from __future__ import annotations

import subprocess
import sys
import json
from pathlib import Path

from valkey_scale_lab.report.render import render_report


ROOT = Path(__file__).resolve().parents[2]


def test_zh_offline_report_gate_accepts_canonical_layout(tmp_path: Path) -> None:
    analysis_path = tmp_path / "analysis_summary.json"
    reports_dir = tmp_path / "reports"
    analysis_path.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "artifact_type": "analysis_summary",
                "capability_id": "analysis_reporting",
                "run_id": "analysis-reporting",
                "created_at": "2026-06-28T00:00:00Z",
                "status": "PASS",
                "source": {"capability_id": "test"},
                "findings": [],
                "metrics": [],
                "missing_metrics": [],
                "baseline_comparison": {"comparisons": []},
                "resource_analysis": {
                    "status": "PASS",
                    "per_window": [],
                    "abnormal_nodes_topN": [],
                },
            }
        ),
        encoding="utf-8",
    )
    render_report(analysis_path, reports_dir, reports_dir / "report_index.json")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "assert_zh_offline_report_contract.py"),
            "--reports-dir",
            str(reports_dir),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_zh_offline_report_gate_rejects_external_url(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    (reports_dir / "exports").mkdir(parents=True)
    (reports_dir / "assets").mkdir()
    (reports_dir / "index.html").write_text("<html><script src=\"https://cdn.example/chart.js\"></script>中文自动化可视化分析报告</html>", encoding="utf-8")
    (reports_dir / "report.md").write_text("# 中文自动化可视化分析报告\n\n## 总览页\n", encoding="utf-8")
    (reports_dir / "exports" / "metrics.csv").write_text("metric,value\nx,1\n", encoding="utf-8")
    (reports_dir / "assets" / "chart.svg").write_text("<svg></svg>\n", encoding="utf-8")
    (reports_dir / "report_index.json").write_text(
        '{"offline_policy":{"artifact_only":true,"llm_used":false,"external_urls_allowed":false,"cdn_allowed":false},"exports":[],"assets":[],"conclusion_summary":{"source":"artifact_derived"}}',
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "assert_zh_offline_report_contract.py"),
            "--reports-dir",
            str(reports_dir),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 1
    assert "external URL" in result.stderr
