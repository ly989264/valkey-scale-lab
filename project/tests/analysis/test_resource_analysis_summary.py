from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab.analysis.summary import create_analysis_summary


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def test_analysis_summary_consumes_resource_observation(tmp_path: Path) -> None:
    _write(
        tmp_path / "run_summary.json",
        {"status": "PASS", "capability_id": "cap", "run_id": "run", "missing_metrics": []},
    )
    _write(
        tmp_path / "valkey_e2e_evidence.json",
        {"status": "PASS", "nodes_observed": 1, "valkey_versions": ["9.1.0"]},
    )
    _write(tmp_path / "failover_report.json", {"status": "PASS", "failovers": [], "summary": {}})
    _write(tmp_path / "cleanup_report.json", {"status": "PASS", "resources_remaining": []})
    _write(
        tmp_path / "resource_observation.json",
        {
            "status": "PASS",
            "resource_analyses": [
                {
                    "sampler_id": "host-a",
                    "analysis": {
                        "cpu": {"utilization_p95": 10.0, "utilization_peak": 12.0, "throttled_usec_delta": 2, "throttling_ratio": 0.1},
                        "memory": {"mem_available_min": 1000, "cgroup_headroom_min": 900, "oom_kill_delta": 0},
                        "network": {"eth0": {"rx_bytes_throughput_p95": 1, "tx_bytes_throughput_p95": 2, "rx_pps_p95": 3, "tx_pps_p95": 4, "rx_errors": {"delta": 0}, "rx_drops": {"delta": 0}, "tx_errors": {"delta": 0}, "tx_drops": {"delta": 0}}},
                        "processes": {"node-a": {"cpu_ticks_delta": 5}},
                        "process_totals": {"rss_bytes_max_sum": 500, "fd_count_max_sum": 7},
                        "collector": {"overrun_count": 0},
                        "timestamps": [{"kind": "host"}],
                        "timeline_correlation": {},
                    },
                }
            ],
        },
    )

    summary = create_analysis_summary(tmp_path, tmp_path / "analysis_summary.json")

    assert summary["resource_analysis"]["status"] == "PASS"
    assert summary["resource_analysis"]["aggregate"]["process_rss_bytes_max_sum"]["max"] == 500.0
    metric_names = {row["name"] for row in summary["metrics"]}
    assert "resource_network_error_drop_delta" in metric_names
