from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))

from schema_validator import load_json, validate


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_stability_soak_metrics_audit_gate(tmp_path: Path) -> None:
    out = tmp_path / "stability_soak_metrics.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/audit_stability_soak_metrics.py",
            "--root",
            ".",
            "--out",
            str(out),
            "--require-node-counts",
            "6,30,50,100",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert validate(report, load_json(REPO_ROOT / "schemas/artifact/stability_soak_rollup.schema.json")) == []
    assert report["status"] == "PASS"
    assert report["summary"]["required_node_counts"] == [6, 30, 50, 100]
    assert report["summary"]["blocking_findings_count"] == 0
    assert report["p14_boundary"]["real_valkey_coverage"] is False
    assert {profile["node_count"] for profile in report["profiles"]} == {6, 30, 50, 100}
    measured = next(profile for profile in report["profiles"] if profile["node_count"] == 6)
    assert measured["real_valkey_coverage"] is True
    for profile in report["profiles"]:
        if profile["node_count"] in {30, 50, 100}:
            assert profile["real_valkey_coverage"] is False
            assert profile["skip_category"] == "MEASUREMENT_DEFERRED_WITH_REVIEWED_REASON"
