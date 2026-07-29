from __future__ import annotations

from valkey_scale_lab.runtime import docker_runtime


def test_local_full_flow_analysis_reports_captured_resource_telemetry() -> None:
    run_id = "review-o2-resource-telemetry"
    resource_metric = {
        "schema_version": "v1",
        "artifact_type": "metric_sample",
        "capability_id": docker_runtime.LOCAL_FULL_FLOW_CAPABILITY,
        "run_id": run_id,
        "source_type": "resource_analysis",
        "source_id": "local_resource",
        "metric_name": "resource_process_rss_bytes_max_sum",
        "metric_value": 1024,
        "metric_unit": "bytes",
        "labels": {"lifecycle_window": "full_flow"},
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

    analysis = docker_runtime._local_full_flow_analysis_summary(
        docker_runtime.LOCAL_FULL_FLOW_CAPABILITY,
        docker_runtime.LOCAL_FULL_FLOW_SCENARIO,
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
    assert analysis["resources"]["metric_names"] == ["resource_process_rss_bytes_max_sum"]
