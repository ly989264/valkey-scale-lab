from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_renderer_includes_scale_build_metrics_source(tmp_path: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            "scripts/audit_scale_build_metrics.py",
            "--root",
            ".",
            "--out",
            "artifacts/loop_engineering/reports/scale_build_metrics.json",
        ],
        cwd=REPO_ROOT,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "scripts/build_metric_coverage_matrix.py",
            "--out-dir",
            "artifacts/loop_engineering/reports",
        ],
        cwd=REPO_ROOT,
        check=True,
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/render_audit_report.py",
            "--input-dir",
            str(REPO_ROOT / "artifacts/loop_engineering/reports"),
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
    assert any(source["path"].endswith("scale_build_metrics.json") for source in index["source_artifacts"])
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Scale build rungs" in html
    assert "Measured build metrics" in html
