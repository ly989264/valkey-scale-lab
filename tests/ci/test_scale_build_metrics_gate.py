from __future__ import annotations

import json
import copy
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))

from schema_validator import load_json, validate


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/github-coverage-gates.yml"
SCHEMA = REPO_ROOT / "schemas/artifact/scale_build_metrics.schema.json"


def test_scale_build_metrics_ci_gate(tmp_path: Path) -> None:
    out = tmp_path / "scale_build_metrics.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/audit_scale_build_metrics.py",
            "--root",
            ".",
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["summary"]["canonical_node_counts"] == [30, 50, 100]

    schema_result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_json_schema.py",
            "--schema",
            "schemas/artifact/scale_build_metrics.schema.json",
            "--instance",
            str(out),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert schema_result.returncode == 0, schema_result.stdout + schema_result.stderr


def test_scale_build_metrics_run_before_metric_coverage_matrix() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    scale_build_pos = workflow.index("python3 scripts/audit_scale_build_metrics.py --root . --out artifacts/loop_engineering/reports/scale_build_metrics.json")
    coverage_pos = workflow.index("python3 scripts/build_metric_coverage_matrix.py --out-dir artifacts/loop_engineering/reports")

    assert scale_build_pos < coverage_pos


def test_scale_build_metrics_schema_rejects_boundary_and_rung_drift(tmp_path: Path) -> None:
    out = tmp_path / "scale_build_metrics.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/audit_scale_build_metrics.py",
            "--root",
            ".",
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        check=True,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    schema = load_json(SCHEMA)

    duplicate = copy.deepcopy(payload)
    duplicate["summary"]["canonical_node_counts"] = [30, 30, 100]
    duplicate["canonical_rungs"][1]["node_count"] = 30
    assert validate(duplicate, schema)

    bad_p14 = copy.deepcopy(payload)
    bad_p14["p14_boundary"]["real_valkey_coverage"] = True
    bad_p14["p14_boundary"]["real_evidence_count"] = 1
    assert validate(bad_p14, schema)


def test_scale_build_metrics_records_preserve_value_reason_semantics(tmp_path: Path) -> None:
    out = tmp_path / "scale_build_metrics.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/audit_scale_build_metrics.py",
            "--root",
            ".",
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        check=True,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))

    for rung in payload["canonical_rungs"]:
        assert rung["node_count"] in {30, 50, 100}
        assert rung["findings"] == []
        for metric in rung["metric_records"]:
            assert metric["source_artifact"].endswith(".json")
            if metric["status"] == "MEASURED":
                assert metric["value"] is not None
            else:
                assert metric["reason"]

    missing_reason = copy.deepcopy(payload)
    missing_metric = next(
        metric
        for metric in missing_reason["canonical_rungs"][0]["metric_records"]
        if metric["status"] == "MISSING"
    )
    missing_metric["reason"] = ""
    assert any(
        metric["status"] != "MEASURED" and not metric["reason"]
        for rung in missing_reason["canonical_rungs"]
        for metric in rung["metric_records"]
    )

    measured_null = copy.deepcopy(payload)
    measured_metric = next(
        metric
        for metric in measured_null["canonical_rungs"][1]["metric_records"]
        if metric["status"] == "MEASURED"
    )
    measured_metric["value"] = None
    assert any(
        metric["status"] == "MEASURED" and metric["value"] is None
        for rung in measured_null["canonical_rungs"]
        for metric in rung["metric_records"]
    )
