from __future__ import annotations

from pathlib import Path

from valkey_scale_lab.analysis import create_analysis_summary
from valkey_scale_lab.report import render_report


def test_fault_timeline_flows_from_fixture_to_analysis_and_report(tmp_path: Path) -> None:
    source = Path("tests/fixtures/fault_timeline/success")
    analysis_path = tmp_path / "analysis_summary.json"
    summary = create_analysis_summary(source, analysis_path)

    assert summary["fault_timeline"]["row_count"] >= 12
    assert not summary["fault_timeline"]["fault_type_coverage"]["missing"]
    assert not summary["fault_timeline"]["scale_coverage"]["missing"]
    assert any(metric["name"] == "fault_failover_latency_p95_ms" for metric in summary["metrics"])

    index = render_report(analysis_path, tmp_path / "reports", tmp_path / "report_index.json")
    report_names = {Path(item["path"]).name for item in index["reports"]}
    assert "fault_timeline_events.csv" in report_names
    assert "failover_latency_distribution.svg" in report_names
    assert "fault_timeline_report_inputs" in index
    markdown = (tmp_path / "reports" / "report.md").read_text(encoding="utf-8")
    assert "## 故障 Timeline" in markdown
    assert "## Failover 延迟分布" in markdown
    assert "## Split-brain 窗口" in markdown
    assert "## 故障期间 Workload 影响" in markdown
