from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))

from schema_validator import load_json, validate


SCHEMA = Path("schemas/artifact/p13_p14_scale_audit.schema.json")
WORKFLOW = Path(".github/workflows/github-coverage-gates.yml")


def test_p13_p14_scale_audit_cli_generates_schema_valid_report(tmp_path: Path) -> None:
    out = tmp_path / "p13_p14_scale_audit.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/audit_p13_p14_scale.py",
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert validate(report, load_json(SCHEMA)) == []
    assert report["status"] == "PASS"
    assert report["summary"]["p13_real_evidence_count"] == 2
    assert report["summary"]["p14_status"] == "SKIPPED_WITH_REASON"
    assert report["summary"]["p14_real_evidence_count"] == 0
    assert report["summary"]["p14_dry_run_only"] is True


def test_github_coverage_workflow_runs_static_p13_p14_scale_audit_gate() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required_commands = [
        "python3 scripts/audit_p13_p14_scale.py --out artifacts/loop_engineering/reports/p13_p14_scale_audit.json",
        (
            "python3 scripts/validate_json_schema.py --schema schemas/artifact/p13_p14_scale_audit.schema.json "
            "--instance artifacts/loop_engineering/reports/p13_p14_scale_audit.json"
        ),
        "python3 -m pytest -q tests/scale/test_p13_p14_scale_audit.py tests/ci/test_p13_p14_scale_audit_gate.py",
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
