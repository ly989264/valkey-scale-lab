from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
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


def test_report_checks_distinguish_measured_missing_skipped_and_no_baseline() -> None:
    artifact = build()
    statuses = {check["name"]: check["status"] for check in artifact["report_checks"]}

    assert statuses["metric_status_measured_present"] == "PASS"
    assert statuses["metric_status_missing_present"] == "PASS"
    assert statuses["metric_status_skipped_with_reason_present"] == "PASS"
    assert statuses["metric_status_no_baseline_yet_present"] == "PASS"
    assert statuses["rendered_views_not_measured_sources"] == "PASS"
    assert statuses["report_index_source_of_truth_false"] == "PASS"
    assert statuses["rendered_reports_source_of_truth_false"] == "PASS"


def test_missing_metrics_csv_keeps_l06_required_statuses(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/render_audit_report.py",
            "--input-dir",
            "artifacts/loop_engineering/reports",
            "--out-dir",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    rows = list(csv.DictReader((tmp_path / "missing_metrics.csv").open(encoding="utf-8")))
    statuses = {row["status"] for row in rows}
    assert {"MISSING", "SKIPPED_WITH_REASON", "NO_BASELINE_YET"} <= statuses
    assert any(row["metric"] == "failover.split_brain_duration_ms" for row in rows)
    assert all(row["reason"] for row in rows)


def test_loop_report_index_tracks_small_real_parity_source(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/render_audit_report.py",
            "--input-dir",
            "artifacts/loop_engineering/reports",
            "--out-dir",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    index = json.loads((tmp_path / "report_index.json").read_text(encoding="utf-8"))
    sources = {source["path"]: source for source in index["source_artifacts"]}
    parity = "artifacts/loop_engineering/reports/small_real_parity_audit.json"
    assert parity in sources
    assert sources[parity]["source_of_truth"] is True
    assert all(report["source_of_truth"] is False for report in index["reports"])
