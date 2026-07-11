from __future__ import annotations

from pathlib import Path

from valkey_scale_lab.analysis.summary import create_analysis_summary


ROOT = Path(__file__).resolve().parents[2]


def test_analysis_aggregates_system_metrics_by_node_and_window(tmp_path: Path) -> None:
    summary = create_analysis_summary(ROOT / "tests" / "fixtures" / "system_metrics" / "success", tmp_path / "analysis_summary.json")
    system = summary["system_metrics"]
    assert system["status"] == "PASS"
    assert system["sample_count"] > 0
    assert {"setup", "workload", "management", "fault", "cleanup"}.issubset(set(system["windows"]))
    assert system["per_node"]
    assert system["per_window"]
    assert system["abnormal_nodes_topN"]
    assert system["aggregate"]["rss_bytes"]["max"] > 0


def test_analysis_reports_missing_system_metrics_with_reason(tmp_path: Path) -> None:
    summary = create_analysis_summary(ROOT / "tests" / "fixtures" / "system_metrics" / "missing_metric", tmp_path / "analysis_summary.json")
    missing = [item for item in summary["missing_metrics"] if item["metric"].startswith("system.")]
    assert missing
    assert all(item["reason"] for item in missing)
