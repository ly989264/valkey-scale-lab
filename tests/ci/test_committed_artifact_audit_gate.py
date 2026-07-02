from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))

from schema_validator import load_json, validate


P13_ID = "P13_SCALE_LADDER_50_100"
P14_ID = "P14_SCALE_1000_OPTIN_DRYRUN"
REPORT_SCHEMA = Path("schemas/artifact/audit_report.schema.json")
WORKFLOW = Path(".github/workflows/github-coverage-gates.yml")


def run_committed_audit(out: Path) -> dict:
    result = subprocess.run(
        [sys.executable, "scripts/audit_committed_artifacts.py", "--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def test_committed_artifact_audit_report_is_schema_valid(tmp_path: Path) -> None:
    report_path = tmp_path / "audit_report.json"
    report = run_committed_audit(report_path)

    assert validate(report, load_json(REPORT_SCHEMA)) == []
    assert report["status"] == "PASS"
    assert report["summary"]["blocking_findings_count"] == 0


def test_committed_artifact_audit_covers_p00_through_p13_and_p14_boundary(tmp_path: Path) -> None:
    report = run_committed_audit(tmp_path / "audit_report.json")
    automatic = report["audit_scope"]["automatic_phase_ids"]

    assert automatic[0] == "P00_REPO_CONTRACT"
    assert automatic[-1] == P13_ID
    assert len(automatic) == 14
    assert P14_ID not in automatic
    assert report["audit_scope"]["optional_phase_ids"] == [P14_ID]
    assert report["p14_boundary"]["status"] == "SKIPPED_WITH_REASON"
    assert report["p14_boundary"]["opt_in_required"] is True
    assert report["p14_boundary"]["dry_run_only"] is True
    assert report["p14_boundary"]["real_evidence_count"] == 0


def test_committed_artifact_audit_keeps_p13_historical_drift_nonblocking(tmp_path: Path) -> None:
    report = run_committed_audit(tmp_path / "audit_report.json")
    p13 = next(phase for phase in report["phase_results"] if phase["phase_id"] == P13_ID)
    mismatches = [
        finding
        for finding in report["findings"]
        if finding.get("phase_id") == P13_ID and finding["category"] == "gate_command_mismatch"
    ]

    assert p13["status"] == "PASS"
    assert report["summary"]["real_evidence_count"] >= 11
    assert len(mismatches) in {0, 1}
    for mismatch in mismatches:
        assert mismatch["classification"] == "historical"
        assert mismatch["blocking"] is False
    assert report["summary"]["blocking_findings_count"] == 0


def test_committed_artifact_audit_manifest_sha_drift_is_explicitly_allowlisted(tmp_path: Path) -> None:
    report = run_committed_audit(tmp_path / "audit_report.json")
    automatic = set(report["audit_scope"]["automatic_phase_ids"])
    manifest_findings = [
        finding for finding in report["findings"] if finding["category"] == "manifest_sha256_mismatch"
    ]

    manifest_phase_ids = {finding["phase_id"] for finding in manifest_findings}
    assert manifest_phase_ids == set() or manifest_phase_ids == automatic
    for finding in manifest_findings:
        assert finding["classification"] == "historical"
        assert finding["blocking"] is False
        assert any("allowlist=legacy_gate_manifest_sha256" in item for item in finding["evidence"])


def test_github_coverage_workflow_runs_committed_artifact_audit() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required_commands = [
        "python3 scripts/audit_committed_artifacts.py --out artifacts/loop_engineering/reports/audit_report.json",
        (
            "python3 scripts/validate_json_schema.py --schema schemas/artifact/audit_report.schema.json "
            "--instance artifacts/loop_engineering/reports/audit_report.json"
        ),
        "python3 -m pytest -q tests/audit tests/ci/test_committed_artifact_audit_gate.py",
    ]
    for command in required_commands:
        assert command in text
