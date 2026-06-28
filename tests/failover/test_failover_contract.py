from __future__ import annotations

import json
from pathlib import Path


def test_failover_report_shape_allows_measured_or_missing_duration(tmp_path: Path) -> None:
    report = {
        "schema_version": "v1",
        "artifact_type": "failover_report",
        "phase_id": "P08_FAILOVER_SPLIT_BRAIN",
        "run_id": "test",
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "test", "version": "v1"},
        "status": "PASS",
        "failovers": [
            {
                "fault_id": "fault-primary-stop",
                "target_logical_id": "shard-0000-primary",
                "promoted_node_id": "node-2",
                "failover_latency_ms": 1234.0,
            }
        ],
        "summary": {
            "primary_stop_observed": True,
            "promotion_observed": True,
            "split_brain_duration_ms": {
                "value": None,
                "status": "MISSING",
                "reason": "not_measured_by_primary_stop_gate",
            },
        },
    }
    path = tmp_path / "failover_report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["artifact_type"] == "failover_report"
    assert loaded["summary"]["promotion_observed"] is True
    assert loaded["summary"]["split_brain_duration_ms"]["status"] == "MISSING"
