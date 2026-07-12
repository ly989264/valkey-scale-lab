from __future__ import annotations

from valkey_scale_lab.runtime import docker_runtime


def test_p36_analysis_reports_captured_resource_telemetry() -> None:
    run_id = "review-o2-resource-telemetry"
    resource_metric = {
        "schema_version": "v1",
        "artifact_type": "metric_sample",
        "phase_id": docker_runtime.P36_STAGE,
        "run_id": run_id,
        "source_type": "system_process",
        "source_id": "node-0001",
        "metric_name": "rss_bytes",
        "metric_value": 1024,
        "metric_unit": "bytes",
        "labels": {"logical_node_id": "node-0001", "lifecycle_window": "baseline_workload"},
    }
    management = {
        "summary": {"status": "PASS", "result": {"duration_ms": 1}, "source_refs": []},
        "topology": [],
    }
    fault = {
        "summary": {
            "status": "PASS",
            "failover_details": {"promotion_latency_ms": 1, "cluster_recovery_latency_ms": 1},
            "recovery_health": {"cluster_state": "ok"},
            "source_refs": [],
        },
        "topology": [],
    }

    analysis = docker_runtime._p36_analysis_summary(
        docker_runtime.P36_STAGE,
        docker_runtime.P36_SCENARIO_50,
        run_id,
        50,
        [],
        management,
        fault,
        [],
        [resource_metric],
        [],
    )

    assert analysis["resources"]["status"] == "PASS"
    assert analysis["resources"]["sample_count"] == 1
    assert analysis["resources"]["metric_names"] == ["rss_bytes"]
