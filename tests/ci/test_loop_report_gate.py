from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))

from schema_validator import load_json, validate


SCHEMA = Path("schemas/artifact/loop_report_index.schema.json")
WORKFLOW = Path(".github/workflows/github-coverage-gates.yml")


def test_loop_report_cli_generates_schema_valid_report_index(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/render_audit_report.py",
            "--input-dir",
            "artifacts/loop_engineering/reports",
            "--out-dir",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    index = json.loads((tmp_path / "report_index.json").read_text(encoding="utf-8"))
    assert validate(index, load_json(SCHEMA)) == []
    assert index["status"] == "PASS"


def test_github_coverage_workflow_runs_static_loop_report_gate() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required_commands = [
        "python3 scripts/render_audit_report.py --input-dir artifacts/loop_engineering/reports --out-dir artifacts/loop_engineering/reports",
        (
            "python3 scripts/validate_json_schema.py --schema schemas/artifact/loop_report_index.schema.json "
            "--instance artifacts/loop_engineering/reports/report_index.json"
        ),
        "python3 -m pytest -q tests/report tests/visualization tests/ci/test_loop_report_gate.py",
    ]
    for command in required_commands:
        assert command in text

    forbidden_tokens = [
        "P14_SCALE_1000_OPTIN_DRYRUN",
        "VSLAB_ALLOW_1000_DRYRUN",
        "scripts/valkey_e2e_gate.py",
        "scripts/fault_safety_gate.py",
        "scripts/fault_failover_gate.py",
    ]
    for token in forbidden_tokens:
        assert token not in text
