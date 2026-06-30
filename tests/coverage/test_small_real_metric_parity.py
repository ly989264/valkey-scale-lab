from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit_small_real_scenario_parity.py"

spec = importlib.util.spec_from_file_location("audit_small_real_scenario_parity", SCRIPT)
small_real = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = small_real
spec.loader.exec_module(small_real)


def build() -> dict:
    audit = small_real.SmallRealParityAudit(
        REPO_ROOT,
        require_fake=True,
        require_real=True,
        validate_report_views=True,
    )
    return audit.build()


def metric_by_name(artifact: dict, name: str) -> list[dict]:
    return [metric for metric in artifact["metrics"] if metric["name"] == name]


def test_required_surfaces_have_separate_fake_and_small_real_metric_layers() -> None:
    artifact = build()
    required = {spec.surface for spec in small_real.SURFACES}

    fake_surfaces = {metric["surface"] for metric in artifact["metrics"] if metric["evidence_layer"] == "fake"}
    real_surfaces = {metric["surface"] for metric in artifact["metrics"] if metric["evidence_layer"] == "small-real"}

    assert required <= fake_surfaces
    assert required <= real_surfaces
    assert all(metric["real_valkey_coverage"] is False for metric in artifact["metrics"] if metric["evidence_layer"] == "fake")


def test_fault_and_failover_skipped_data_path_semantics_are_preserved() -> None:
    artifact = build()
    names = [
        "fault_sandbox.real_evidence.data_path_result",
        "failover_primary_stop.real_evidence.data_path_result",
        "fault_sandbox.observed_impact",
    ]

    for name in names:
        metrics = metric_by_name(artifact, name)
        assert metrics
        assert metrics[0]["value_status"] == "SKIPPED_WITH_REASON"
        assert metrics[0]["missing_semantics"]["reason"]


def test_failover_split_brain_is_explicit_missing() -> None:
    artifact = build()
    metric = next(
        metric
        for metric in metric_by_name(artifact, "failover_primary_stop.split_brain_duration_ms")
        if metric["evidence_layer"] == "small-real"
    )

    assert metric["value"] is None
    assert metric["value_status"] == "MISSING"
    assert metric["missing_semantics"]["reason"] == "not_measured_by_primary_stop_gate"


def test_stability_no_baseline_values_are_not_fabricated() -> None:
    artifact = build()
    metrics = [
        metric
        for metric in artifact["metrics"]
        if metric["surface"] == "stability_soak" and metric["value_status"] == "NO_BASELINE_YET"
    ]

    assert metrics
    assert all(metric["value"] is None for metric in metrics)
    assert all(metric["missing_semantics"]["reason"] for metric in metrics)


def test_cleanup_surface_covers_all_small_real_cleanup_reports() -> None:
    artifact = build()
    cleanup = next(surface for surface in artifact["surfaces"] if surface["surface"] == "cleanup")

    assert len(cleanup["real_coverage"]["source_artifacts"]) == 9
    assert cleanup["real_coverage"]["evidence_class"] == "source_artifact"
    assert cleanup["real_coverage"]["real_valkey_coverage"] is False
