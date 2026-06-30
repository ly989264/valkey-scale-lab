from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))

from schema_validator import load_json, validate


SCHEMA = Path("schemas/artifact/small_real_parity_audit.schema.json")
WORKFLOW = Path(".github/workflows/github-coverage-gates.yml")


def test_small_real_parity_cli_generates_schema_valid_artifact(tmp_path: Path) -> None:
    out = tmp_path / "small_real_parity_audit.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/audit_small_real_scenario_parity.py",
            "--root",
            ".",
            "--out",
            str(out),
            "--require-fake",
            "--require-real",
            "--validate-report-views",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    artifact = json.loads(out.read_text(encoding="utf-8"))
    assert validate(artifact, load_json(SCHEMA)) == []
    assert artifact["status"] == "PASS"
    assert artifact["summary"]["blocking_findings_count"] == 0


def test_github_coverage_workflow_runs_small_real_parity_gate() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required_commands = [
        (
            "python3 scripts/audit_small_real_scenario_parity.py --root . "
            "--out artifacts/loop_engineering/reports/small_real_parity_audit.json "
            "--require-fake --require-real --validate-report-views"
        ),
        (
            "python3 scripts/validate_json_schema.py --schema schemas/artifact/small_real_parity_audit.schema.json "
            "--instance artifacts/loop_engineering/reports/small_real_parity_audit.json"
        ),
        (
            "python3 -m pytest -q tests/audit/test_small_real_scenario_parity.py "
            "tests/coverage/test_small_real_metric_parity.py tests/report/test_small_real_parity_report.py "
            "tests/real_valkey/test_small_real_gate_contract.py tests/ci/test_small_real_parity_gate.py"
        ),
    ]
    for command in required_commands:
        assert command in text

    forbidden_tokens = [
        "P14_SCALE_1000_OPTIN_DRYRUN",
        "VSLAB_ALLOW_1000_DRYRUN",
    ]
    for token in forbidden_tokens:
        assert token not in text
