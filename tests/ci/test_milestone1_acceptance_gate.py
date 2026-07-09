from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_milestone1_acceptance_gate_writes_structured_report(tmp_path: Path) -> None:
    out = tmp_path / "milestone1_acceptance_report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "assert_milestone1_acceptance.py"),
            "--repo-root",
            str(ROOT),
            "--out",
            str(out),
            "--allow-blocked",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["artifact_type"] == "milestone1_acceptance_report"
    assert report["milestone1_status"] in {"PASS", "BLOCKED_WITH_REASON"}
    for key in [
        "cluster_setup",
        "management_ops",
        "fault_failover",
        "workload_benchmark",
        "system_metrics",
        "analysis",
        "visual_report_zh",
        "cleanup",
        "cross_scenario_coverage",
    ]:
        assert report[key] in {"PASS", "FAIL", "BLOCKED_WITH_REASON"}
    assert report["heavy_real_rungs"]
    assert all(row["status"] in {"PASS", "FAIL", "BLOCKED_WITH_REASON"} for row in report["heavy_real_rungs"])
    assert all(row.get("reason") for row in report["heavy_real_rungs"])
    if report["milestone1_status"] == "PASS":
        assert all(row["status"] == "PASS" for row in report["heavy_real_rungs"])
