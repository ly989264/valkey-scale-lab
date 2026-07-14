from __future__ import annotations

from pathlib import Path
import sys
import json

sys.path.insert(0, str(Path("scripts").resolve()))

import build_metric_coverage_matrix


def test_scale_build_metrics_populate_cluster_build_coverage() -> None:
    catalog, matrix = build_metric_coverage_matrix.build_reports(Path(".").resolve())

    assert catalog["status"] == "PASS"
    by_cell = {(entry["layer"], entry["surface"]): entry for entry in matrix["entries"]}
    for layer in ["30", "50", "100"]:
        entry = by_cell[(layer, "cluster_build")]
        assert entry["status"] == "COVERED"
        assert entry["evidence_class"] == "real_valkey"
        assert entry["real_valkey_coverage"] is True
        assert any(path.endswith(".json") for path in entry["source_artifacts"])
        assert any(name.startswith("cluster_build.") for name in entry["metric_names"])

    scale_1000 = by_cell[("1000-dry-run", "cluster_build")]
    assert scale_1000["real_valkey_coverage"] is False


def test_scale_build_missing_metrics_have_reasons() -> None:
    catalog, _ = build_metric_coverage_matrix.build_reports(Path(".").resolve())

    missing = [
        metric
        for metric in catalog["metrics"]
        if metric["surface"] == "cluster_build" and metric["evidence_layer"] == "30" and metric["value_status"] == "MISSING"
    ]
    assert missing
    assert all(metric["missing_semantics"]["reason"] for metric in missing)
    assert all(metric["source_artifact"].endswith("scale_build_metrics.json") for metric in missing)


def test_fault_failover_scale_metrics_populate_fault_failover_workload_cleanup_surfaces(tmp_path: Path) -> None:
    report = tmp_path / "artifacts" / "loop_engineering" / "reports" / "fault_failover_scale.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "artifact_type": "fault_failover_scale",
                "status": "PASS",
                "canonical_rungs": [
                    {
                        "node_count": 30,
                        "status": "PASS",
                        "scenario": "scale_30_fault_failover",
                        "real_valkey": True,
                        "metric_records": [
                            {"name": "fault.apply_latency_ms", "surface": "fault", "unit": "ms", "source_artifact": "artifacts/phases/P12_SCALE_LADDER_10_30/fault_report_30.json", "status": "MEASURED", "value": 12.0},
                            {"name": "failover.failover_latency_ms", "surface": "failover", "unit": "ms", "source_artifact": "artifacts/phases/P12_SCALE_LADDER_10_30/failover_report_30.json", "status": "MEASURED", "value": 900.0},
                            {"name": "workload.before_fault.operation_count", "surface": "workload", "unit": "count", "source_artifact": "artifacts/phases/P12_SCALE_LADDER_10_30/workload_window_report_30.json", "status": "MEASURED", "value": 30},
                            {"name": "fault.cleanup_residual_count", "surface": "cleanup", "unit": "count", "source_artifact": "artifacts/phases/P12_SCALE_LADDER_10_30/cleanup_report_fault_30.json", "status": "MEASURED", "value": 0},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    builder = build_metric_coverage_matrix.MetricCoverageBuilder(tmp_path)
    builder.add_fault_failover_scale_metrics()

    by_surface = {metric["surface"]: metric for metric in builder.metrics}
    for surface in ["fault", "failover", "workload", "cleanup"]:
        assert surface in by_surface
        assert by_surface[surface]["evidence_layer"] == "30"
        assert by_surface[surface]["real_valkey_coverage"] is True
    assert by_surface["workload"]["value_status"] == "MEASURED"
