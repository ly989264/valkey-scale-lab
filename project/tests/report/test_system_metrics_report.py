from __future__ import annotations

from pathlib import Path

from valkey_scale_lab.analysis.summary import create_analysis_summary
from valkey_scale_lab.report.render import render_report


ROOT = Path(__file__).resolve().parents[2]


def test_report_renders_system_resource_trends_and_topn(tmp_path: Path) -> None:
    analysis_path = tmp_path / "analysis_summary.json"
    create_analysis_summary(ROOT / "tests" / "fixtures" / "system_metrics" / "success", analysis_path)
    index = render_report(analysis_path, tmp_path / "report", tmp_path / "report_index.json")
    html = (tmp_path / "report" / "index.html").read_text(encoding="utf-8")
    markdown = (tmp_path / "report" / "report.md").read_text(encoding="utf-8")
    assert "系统资源趋势" in html
    assert "系统异常节点 TopN" in markdown
    assert (tmp_path / "report" / "system_metrics_by_window.csv").exists()
    assert (tmp_path / "report" / "system_metrics_abnormal_nodes.csv").exists()
    assert (tmp_path / "report" / "system_resource_trends.svg").exists()
    assert (tmp_path / "report" / "exports" / "system_metrics_by_window.csv").exists()
    assert (tmp_path / "report" / "assets" / "system_resource_trends.svg").exists()
    assert index["system_metrics_report_inputs"]["csv"] == ["system_metrics_by_window.csv", "system_metrics_abnormal_nodes.csv"]
