from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit_small_real_scenario_parity.py"

spec = importlib.util.spec_from_file_location("audit_small_real_scenario_parity", SCRIPT)
small_real = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = small_real
spec.loader.exec_module(small_real)


def build(root: Path = REPO_ROOT) -> dict:
    audit = small_real.SmallRealParityAudit(
        root,
        require_fake=True,
        require_real=True,
        validate_report_views=True,
    )
    return audit.build()


def copy_minimal_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for surface in small_real.SURFACES:
        for path_text in [surface.evidence_path, surface.cleanup_path, *surface.metric_paths]:
            src = REPO_ROOT / path_text
            if src.exists():
                dst = root / path_text
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    shutil.copytree(REPO_ROOT / "schemas" / "artifact", root / "schemas" / "artifact")
    for path_text in [
        f"artifacts/loop_engineering/stages/{small_real.STAGE_ID}/current_harness_plan.json",
        "artifacts/loop_engineering/reports/metric_catalog.json",
        "artifacts/loop_engineering/reports/coverage_matrix.json",
        "artifacts/loop_engineering/reports/report_index.json",
    ]:
        src = REPO_ROOT / path_text
        dst = root / path_text
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return root


def test_current_repo_small_real_parity_audit_passes() -> None:
    artifact = build()

    assert artifact["status"] == "PASS"
    assert artifact["summary"]["surface_count"] == 8
    assert artifact["summary"]["fake_covered_count"] == 8
    assert artifact["summary"]["real_covered_count"] == 8
    assert artifact["summary"]["cleanup_pass_count"] == 8
    assert artifact["summary"]["blocking_findings_count"] == 0
    assert not artifact["findings"]


def test_parity_audit_requires_valkey_91_real_evidence(tmp_path: Path) -> None:
    root = copy_minimal_root(tmp_path)
    evidence = root / "artifacts/phases/P03_LOCAL_DOCKER_VALKEY/valkey_e2e_evidence.json"
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["valkey_versions"] = ["8.0.0"]
    evidence.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    artifact = build(root)

    assert artifact["status"] == "FAIL"
    assert any(finding["category"] == "invalid_real_evidence" for finding in artifact["findings"])


def test_parity_audit_rejects_rendered_view_as_measured_source(tmp_path: Path) -> None:
    root = copy_minimal_root(tmp_path)
    catalog_path = root / "artifacts/loop_engineering/reports/metric_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["metrics"][0]["value_status"] = "MEASURED"
    catalog["metrics"][0]["value"] = 1
    catalog["metrics"][0]["source_artifact"] = "artifacts/loop_engineering/reports/index.html"
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")

    artifact = build(root)

    assert artifact["status"] == "FAIL"
    assert any(finding["category"] == "rendered_view_metric_source" for finding in artifact["findings"])


def test_parity_audit_requires_reason_for_missing_split_brain(tmp_path: Path) -> None:
    root = copy_minimal_root(tmp_path)
    failover = root / "artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/failover_report.json"
    payload = json.loads(failover.read_text(encoding="utf-8"))
    payload["summary"]["split_brain_duration_ms"]["reason"] = ""
    failover.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    artifact = build(root)

    assert artifact["status"] == "FAIL"
    assert any(finding["category"] == "missing_reason_absent" for finding in artifact["findings"])


def test_schema_errors_are_not_silently_accepted(tmp_path: Path) -> None:
    root = copy_minimal_root(tmp_path)
    cleanup = root / "artifacts/phases/P03_LOCAL_DOCKER_VALKEY/cleanup_report.json"
    payload = json.loads(cleanup.read_text(encoding="utf-8"))
    payload.pop("status", None)
    cleanup.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    artifact = build(root)

    assert artifact["status"] == "FAIL"
    assert any(finding["category"] in {"schema_invalid", "cleanup_invalid"} for finding in artifact["findings"])


@pytest.mark.parametrize("surface", [spec.surface for spec in small_real.SURFACES])
def test_every_surface_has_fake_and_real_records(surface: str) -> None:
    artifact = build()
    record = next(item for item in artifact["surfaces"] if item["surface"] == surface)

    assert record["fake_coverage"]["present"] is True
    assert record["fake_coverage"]["evidence_class"] == "fake"
    assert record["fake_coverage"]["real_valkey_coverage"] is False
    assert record["real_coverage"]["present"] is True
    assert record["cleanup"]["status"] == "PASS"
