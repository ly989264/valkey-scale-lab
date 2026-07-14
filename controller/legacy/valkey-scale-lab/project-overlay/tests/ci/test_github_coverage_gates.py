from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/github-coverage-gates.yml")


def test_github_coverage_gate_exists_and_runs_on_standard_events() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "name: github-coverage-gates" in text
    assert "pull_request:" in text
    assert "push:" in text
    assert "workflow_dispatch:" in text


def test_github_coverage_gate_runs_harness_and_domain_tests() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required_commands = [
        "python3 scripts/codex_gate.py precheck --all",
        "python3 scripts/safety_scan.py",
        "python3 -m pytest -q tests/ci/test_postcheck_compatibility.py",
        "python3 -m pytest -q tests/unit tests/ci/test_github_coverage_gates.py",
        "python3 -m pytest -q tests/config tests/planner",
        "python3 -m pytest -q tests/integration tests/fault tests/failover tests/orchestrator",
        "python3 -m pytest -q tests/analysis tests/report tests/stability tests/scale",
        "python3 scripts/final_audit_gate.py --out-dir artifacts/loop_engineering/final_audit",
        "python3 -m pytest -q tests/final_audit tests/ci/test_final_audit_workflow_gate.py",
    ]
    for command in required_commands:
        assert command in text


def test_github_coverage_gate_stays_on_fast_non_opt_in_paths() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    forbidden_tokens = [
        "P14_SCALE_1000_OPTIN_DRYRUN",
        "VSLAB_ALLOW_1000_DRYRUN",
        "scripts/valkey_e2e_gate.py",
        "scripts/fault_safety_gate.py",
        "scripts/fault_failover_gate.py",
    ]
    for token in forbidden_tokens:
        assert token not in text
