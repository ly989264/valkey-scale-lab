from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab.analysis import create_analysis_summary


def test_analysis_preserves_missing_metrics_and_writes_baseline(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write(
        source / "phase_summary.json",
        {
            "phase_id": "P08_FAILOVER_SPLIT_BRAIN",
            "run_id": "p08-run",
            "status": "PASS",
            "missing_metrics": [
                {"metric": "split_brain_duration_ms", "status": "MISSING", "reason": "not measured"}
            ],
        },
    )
    _write(
        source / "valkey_e2e_evidence.json",
        {
            "status": "PASS",
            "real_valkey": True,
            "valkey_versions": ["9.1.0"],
            "nodes_observed": 5,
            "cluster_state_observed": "ok",
        },
    )
    _write(
        source / "failover_report.json",
        {
            "status": "PASS",
            "failovers": [{"target_logical_id": "shard-0000-primary", "failover_latency_ms": 12.5}],
            "summary": {
                "split_brain_duration_ms": {
                    "value": None,
                    "status": "MISSING",
                    "reason": "not measured",
                }
            },
        },
    )
    _write(source / "cleanup_report.json", {"status": "PASS", "resources_remaining": []})

    summary = create_analysis_summary(source, tmp_path / "analysis_summary.json")

    assert summary["status"] == "PASS"
    assert summary["missing_metrics"][0]["metric"] == "split_brain_duration_ms"
    assert summary["metrics"][1]["name"] == "failover_latency_ms"
    assert (tmp_path / "baseline_comparison.json").exists()
    assert summary["baseline_comparison"]["status"] == "NO_BASELINE_YET"


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")
