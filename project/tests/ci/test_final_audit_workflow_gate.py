from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/github-coverage-gates.yml")


def test_github_coverage_gate_runs_final_audit() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python3 scripts/final_audit_gate.py --out-dir artifacts/loop_engineering/final_audit" in text
    assert "python3 scripts/validate_json_schema.py --schema schemas/artifact/final_audit_report.schema.json --instance artifacts/loop_engineering/final_audit/final_audit_report.json" in text
    assert "python3 -m pytest -q tests/final_audit tests/ci/test_final_audit_workflow_gate.py" in text


def test_github_coverage_gate_does_not_opt_in_p14_for_final_audit() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "VSLAB_ALLOW_1000_DRYRUN" not in text
    assert "P14_SCALE_1000_OPTIN_DRYRUN" not in text
    assert "scripts/valkey_e2e_gate.py" not in text
    assert "scripts/fault_safety_gate.py" not in text
    assert "scripts/fault_failover_gate.py" not in text
