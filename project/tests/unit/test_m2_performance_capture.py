from __future__ import annotations

from copy import deepcopy
from typing import Any

from scripts import m2_performance_capture as capture


def _analysis() -> dict[str, Any]:
    return {
        "cpu": {"throttled_usec_delta": 1},
        "memory": {},
        "network": {
            "eth0": {
                "rx_errors": {"delta": 0},
                "rx_drops": {"delta": 0},
                "tx_errors": {"delta": 0},
                "tx_drops": {"delta": 0},
            }
        },
        "processes": {"node-a": {"cpu_ticks_delta": 3}},
        "process_totals": {
            "rss_bytes_max_sum": 100,
            "fd_count_max_sum": 4,
        },
        "collector": {"overrun_count": 0},
        "expected_gone_processes": [],
        "timestamps": [],
        "timeline_correlation": {},
    }


def _observation() -> dict[str, Any]:
    analysis = _analysis()
    return {
        "artifact_type": "resource_observation",
        "status": "PASS",
        "duration_seconds": 5.0,
        "checks": [
            {
                "name": "resource_analysis:host-a",
                "status": "OK",
                "evidence": analysis,
            }
        ],
        "resource_documents": [
            {
                "static": {"sampler_id": "host-a"},
                "samples": [{"kind": "host"}, {"kind": "process"}],
                "errors": [],
            }
        ],
        "resource_analyses": [{"sampler_id": "host-a", "analysis": analysis}],
    }


def test_validate_resource_report_accepts_new_observation_contract() -> None:
    report = capture._validate_resource_report(_observation())

    assert report["resource_summary"]["process_rss_bytes_max_sum"] == 100
    assert report["resource_summary"]["process_fd_count_max_sum"] == 4


def test_validate_resource_report_rejects_missing_analyzer() -> None:
    report = _observation()
    report["checks"] = []
    report["resource_analyses"] = []

    try:
        capture._validate_resource_report(report)
    except capture.CaptureError as exc:
        assert "analyzer" in str(exc)
    else:
        raise AssertionError("missing analyzer output must fail")


def test_discovery_safety_uses_correctness_not_resource_values() -> None:
    trial = {
        "correctness": {
            "clean_topology": True,
            "split_brain": False,
            "slot_loss": False,
            "unexpected_pfail": 0,
            "unexpected_fail": 0,
            "unexpected_promotions": 0,
        },
        "resource_observation": {
            "process_rss_bytes_max_sum": 999999999,
            "process_fd_count_max_sum": 999999,
        },
    }

    assert capture._discovery_safety_clean(trial)


def test_discovery_resource_check_treats_high_values_as_diagnostics() -> None:
    baseline = {
        "resource_observation": {
            metric: 1.0 for metric in capture.RESOURCE_METRICS
        }
    }
    candidate = deepcopy(baseline)
    candidate["resource_observation"]["process_rss_bytes_max_sum"] = 1000000.0

    assert capture._discovery_resource_clean(baseline, candidate)
