from __future__ import annotations

from pathlib import Path
import sys

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
