from __future__ import annotations

from pathlib import Path

import json


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "system_metrics"


def test_system_metrics_success_fixture_validates_schema() -> None:
    rows = [
        json.loads(line)
        for line in (FIXTURES / "success" / "system_metrics_timeseries.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows
    for row in rows[:80]:
        assert {"schema_version", "run_id", "phase_id", "scenario_name", "sample_id", "source_type", "source_id", "metric_name", "metric_value", "metric_unit", "labels", "missing_reason"}.issubset(row)
    report = json.loads((FIXTURES / "success" / "system_metrics_report.json").read_text(encoding="utf-8"))
    assert report["artifact_type"] == "system_metrics_report"
    assert report["sample_count"] == len(rows)


def test_system_metrics_missing_values_carry_reasons_and_node_ids() -> None:
    rows = [
        json.loads(line)
        for line in (FIXTURES / "success" / "system_metrics_timeseries.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    missing = [row for row in rows if row["metric_value"] == "MISSING"]
    assert missing
    assert all(row["missing_reason"] for row in missing)
    assert all(row["labels"].get("logical_node_id") for row in rows)
    assert {"setup", "workload", "management", "fault", "cleanup"}.issubset({row["labels"]["lifecycle_window"] for row in rows})
