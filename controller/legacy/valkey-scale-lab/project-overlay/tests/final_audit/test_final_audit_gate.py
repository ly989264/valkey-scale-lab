from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "final_audit_gate.py"

spec = importlib.util.spec_from_file_location("final_audit_gate", SCRIPT)
final_audit_gate = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(final_audit_gate)


def build_tmp_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for path in [
        "schemas",
        "scripts/schema_validator.py",
        "artifacts/loop_engineering/reports",
        "artifacts/phases/P13_SCALE_LADDER_50_100/scale_ladder_report.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_100.json",
    ]:
        source = REPO_ROOT / path
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    return root


def run_final_audit(root: Path, out_dir: Path) -> dict:
    audit = final_audit_gate.FinalAudit(root, out_dir)
    return audit.build()


def test_final_audit_gate_passes_current_repo(tmp_path: Path) -> None:
    report = run_final_audit(REPO_ROOT, tmp_path / "final_audit")

    assert report["status"] == "PASS"
    assert report["summary"]["blocking_findings_count"] == 0
    assert report["summary"]["source_artifact_count"] >= 10
    assert report["summary"]["missing_metric_impact_count"] > 0
    assert report["p14_boundary"]["dry_run_only"] is True
    assert report["p14_boundary"]["real_valkey_coverage"] is False
    html = (tmp_path / "final_audit" / "index.html").read_text(encoding="utf-8")
    assert report["root_commit_sha"] in html
    assert "coverage_matrix.csv" in html
    assert "missing_metrics.csv" in html


def test_final_audit_fails_when_dry_run_counts_as_real(tmp_path: Path) -> None:
    root = build_tmp_root(tmp_path)
    coverage_path = root / "artifacts/loop_engineering/reports/coverage_matrix.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    entry = next(item for item in coverage["entries"] if item["layer"] == "1000-dry-run")
    entry["real_valkey_coverage"] = True
    coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")

    report = run_final_audit(root, tmp_path / "out")

    assert report["status"] == "FAIL"
    assert any(finding["category"] == "dry_run_counted_as_real" for finding in report["findings"])


def test_final_audit_fails_when_missing_metric_lacks_impact(tmp_path: Path) -> None:
    root = build_tmp_root(tmp_path)
    catalog_path = root / "artifacts/loop_engineering/reports/metric_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    metric = next(item for item in catalog["metrics"] if item["value_status"] in {"MISSING", "SKIPPED_WITH_REASON", "NO_BASELINE_YET"})
    metric["impact"] = ""
    metric["missing_semantics"].pop("impact", None)
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")

    report = run_final_audit(root, tmp_path / "out")

    assert report["status"] == "FAIL"
    assert any(finding["category"] == "missing_metric_impact" for finding in report["findings"])


def test_final_audit_fails_when_report_is_source_of_truth(tmp_path: Path) -> None:
    root = build_tmp_root(tmp_path)
    index_path = root / "artifacts/loop_engineering/reports/report_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["reports"][0]["source_of_truth"] = True
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    report = run_final_audit(root, tmp_path / "out")

    assert report["status"] == "FAIL"
    assert any(finding["category"] in {"source_schema", "report_source_truth"} for finding in report["findings"])
