from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))

from schema_validator import load_json, validate


METRIC_SCHEMA = Path("schemas/artifact/metric_catalog.schema.json")
COVERAGE_SCHEMA = Path("schemas/artifact/coverage_matrix.schema.json")
WORKFLOW = Path(".github/workflows/github-coverage-gates.yml")


def test_metric_coverage_cli_generates_schema_valid_reports(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_metric_coverage_matrix.py",
            "--out-dir",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    catalog = json.loads((tmp_path / "metric_catalog.json").read_text(encoding="utf-8"))
    matrix = json.loads((tmp_path / "coverage_matrix.json").read_text(encoding="utf-8"))
    assert validate(catalog, load_json(METRIC_SCHEMA)) == []
    assert validate(matrix, load_json(COVERAGE_SCHEMA)) == []
    assert catalog["status"] == "PASS"
    assert matrix["status"] == "PASS"


def test_github_coverage_workflow_runs_static_metric_coverage_gate() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required_commands = [
        "python3 scripts/build_metric_coverage_matrix.py --out-dir artifacts/loop_engineering/reports",
        (
            "python3 scripts/validate_json_schema.py --schema schemas/artifact/metric_catalog.schema.json "
            "--instance artifacts/loop_engineering/reports/metric_catalog.json"
        ),
        (
            "python3 scripts/validate_json_schema.py --schema schemas/artifact/coverage_matrix.schema.json "
            "--instance artifacts/loop_engineering/reports/coverage_matrix.json"
        ),
        "python3 -m pytest -q tests/metrics tests/coverage tests/ci/test_metric_coverage_gate.py",
    ]
    for command in required_commands:
        assert command in text

    forbidden_tokens = [
        "VSLAB_ALLOW_1000_DRYRUN",
        "scripts/valkey_e2e_gate.py",
        "scripts/fault_safety_gate.py",
        "scripts/fault_failover_gate.py",
    ]
    for token in forbidden_tokens:
        assert token not in text
