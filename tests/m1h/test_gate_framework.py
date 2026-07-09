from __future__ import annotations

import json
import sys
from pathlib import Path

M1H = Path(__file__).resolve().parents[2] / "scripts" / "m1h"
sys.path.insert(0, str(M1H))

from assert_evidence_taxonomy import validate_manifest
from assert_no_fixture_fallback import scan_fixture_fallbacks
from assert_no_legacy_m1_pass import validate_current_acceptance, validate_no_legacy_pass
from assert_no_simulated_subagents import scan_stage_artifacts
from assert_stage_exit import H00_REQUIRED_GATE_RESULTS, H01_REQUIRED_GATE_RESULTS, REQUIRED_SCRIPTS, validate_stage_exit
from build_acceptance_reset import build_acceptance_reset
from capability_gate import evaluate_capability
from common import gate_result_path, write_gate_result, write_json
from manifest import REQUIRED_CLAIMS, build_manifest, claim_id


def test_write_gate_result_shape(tmp_path: Path) -> None:
    result = write_gate_result(
        root=tmp_path,
        stage_id="H00_BOOTSTRAP_HARD_GATES",
        gate_name="sample_gate",
        status="PASS",
        inputs=["input.json"],
    )
    path = gate_result_path(tmp_path, "H00_BOOTSTRAP_HARD_GATES", "sample_gate")
    assert path.exists()
    assert result["schema_version"] == "v1"
    assert result["artifact_type"] == "m1h_gate_result"
    assert result["status"] == "PASS"
    assert isinstance(result["source_commit"], str)


def test_build_manifest_emits_all_required_claims_blocked_not_false_pass(tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    claim_ids = {claim["claim_id"] for claim in manifest["claims"]}
    assert claim_ids == {claim_id(capability, scale) for capability, scale in REQUIRED_CLAIMS}
    assert all(claim["status"] == "BLOCKED_WITH_REASON" for claim in manifest["claims"])
    assert all(claim["evidence_kind"] == "BLOCKED_WITH_REASON" for claim in manifest["claims"])


def test_taxonomy_rejects_required_fixture_pass(tmp_path: Path) -> None:
    fixture = tmp_path / "tests" / "fixtures" / "x.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("{}", encoding="utf-8")
    manifest = {
        "schema_version": "v1",
        "artifact_type": "m1h_evidence_manifest",
        "claims": [
            {
                "claim_id": "management_matrix.real_exact.50",
                "stage_id": "M1H",
                "capability": "management_matrix",
                "scale": 50,
                "evidence_kind": "FIXTURE_ONLY",
                "required_for_milestone_pass": True,
                "source_artifacts": ["tests/fixtures/x.json"],
                "semantic_checks": {"operation_semantics_present": True},
                "status": "PASS",
            }
        ],
    }
    path = tmp_path / "manifest.json"
    write_json(path, manifest)
    violations, _blocked = validate_manifest(tmp_path, path)
    codes = {item["code"] for item in violations}
    assert "required_pass_disallowed_kind" in codes


def test_fixture_fallback_scanner_reports_file_and_line(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "assert_milestone1_acceptance.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "\n".join(
            [
                "def check(root):",
                "    matrix = {}",
                "    if not matrix:",
                "        matrix = root / 'tests/fixtures/management_matrix/success.json'",
                "    return 'PASS' if matrix else 'FAIL'",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "m1h").mkdir(parents=True)
    violations = scan_fixture_fallbacks(tmp_path)
    assert violations
    assert violations[0]["path"] == "scripts/assert_milestone1_acceptance.py"
    assert violations[0]["line"] == 4


def test_legacy_pass_gate_rejects_nonpromotable_required_pass(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    acceptance_path = tmp_path / "acceptance.json"
    write_json(
        manifest_path,
        {
            "claims": [
                {
                    "claim_id": "fault_timeline.real_exact.50",
                    "required_for_milestone_pass": True,
                    "evidence_kind": "LEGACY_EVIDENCE_ONLY",
                    "status": "PASS",
                }
            ]
        },
    )
    write_json(acceptance_path, _minimal_acceptance_reset(tmp_path, blocked_reason="blocked"))
    violations, _blocked, _extra = validate_no_legacy_pass(manifest_path, acceptance_path)
    assert "legacy_or_nonpromotable_pass" in {item["code"] for item in violations}


def test_acceptance_reset_blocks_all_claims_from_manifest(tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest_path = tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json"
    write_json(manifest_path, manifest)
    report, violations = build_acceptance_reset(
        tmp_path,
        manifest_path,
        stage_id="H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET",
    )
    assert not violations
    assert report["artifact_type"] == "milestone1_acceptance_reset"
    assert report["hardening_loop_status"] == "PASS"
    assert report["milestone1_status"] == "BLOCKED_WITH_REASON"
    assert report["false_pass_prevented"] is True
    assert report["required_claim_count"] == len(REQUIRED_CLAIMS)
    assert report["passed_claim_count"] == 0
    assert report["blocked_claim_count"] == len(REQUIRED_CLAIMS)
    assert all(claim["acceptance_status"] == "BLOCKED_WITH_REASON" for claim in report["claims"])
    assert all(claim["reason"] for claim in report["claims"])


def test_acceptance_reset_rejects_fixture_or_legacy_pass_count(tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["claims"][0].update(
        {
            "status": "PASS",
            "evidence_kind": "FIXTURE_ONLY",
            "source_artifacts": ["tests/fixtures/example.json"],
            "semantic_checks": {"m1_format_fields_complete": True, "hardening_stage_accepted": True},
        }
    )
    manifest["claims"][1].update(
        {
            "status": "PASS",
            "evidence_kind": "LEGACY_EVIDENCE_ONLY",
            "source_artifacts": ["artifacts/phases/legacy.json"],
            "semantic_checks": {"m1_format_fields_complete": True, "hardening_stage_accepted": True},
        }
    )
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    report, violations = build_acceptance_reset(tmp_path, manifest_path, stage_id="H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET")
    assert report["passed_claim_count"] == 0
    assert report["failed_claim_count"] == 2
    assert {item["code"] for item in violations} == {"nonpromotable_required_pass"}


def test_current_acceptance_rejects_fixture_backed_pass(tmp_path: Path) -> None:
    report = _minimal_acceptance_reset(tmp_path, blocked_reason="blocked")
    first = report["claims"][0]
    first.update(
        {
            "acceptance_status": "PASS",
            "evidence_kind": "REAL_EXACT_SCALE",
            "source_artifacts": ["tests/fixtures/unsafe.json"],
            "semantic_checks": {"m1_format_fields_complete": True, "hardening_stage_accepted": True},
        }
    )
    report["passed_claim_count"] = 1
    report["blocked_claim_count"] = len(REQUIRED_CLAIMS) - 1
    path = tmp_path / "acceptance.json"
    violations, _blocked = validate_current_acceptance(report, path)
    assert "acceptance_fixture_pass" in {item["code"] for item in violations}


def test_historical_m1_pass_is_allowed_only_when_superseded(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    acceptance_path = tmp_path / "acceptance.json"
    historical_path = tmp_path / "runs" / "m1-s09-local" / "artifacts" / "goal_loop" / "M1-S09" / "milestone1_acceptance_report.json"
    write_json(manifest_path, build_manifest(tmp_path))
    reset = _minimal_acceptance_reset(tmp_path, blocked_reason="blocked")
    reset["supersedes"] = [historical_path.as_posix()]
    write_json(acceptance_path, reset)
    write_json(
        historical_path,
        {
            "milestone1_status": "PASS",
            "source_artifacts": [{"path": "tests/fixtures/unsafe.json"}],
            "heavy_real_rungs": [{"status": "PASS", "metrics": "SKIPPED_WITH_REASON", "report": "SKIPPED_WITH_REASON"}],
        },
    )
    violations, _blocked, extra = validate_no_legacy_pass(manifest_path, acceptance_path, historical_acceptance_path=historical_path)
    assert not violations
    assert extra["superseded_inputs"][0]["path"] == historical_path.as_posix()

    reset.pop("supersedes")
    write_json(acceptance_path, reset)
    violations, _blocked, _extra = validate_no_legacy_pass(manifest_path, acceptance_path, historical_acceptance_path=historical_path)
    assert "legacy_acceptance_fixture_pass" in {item["code"] for item in violations}


def test_current_acceptance_rejects_missing_blocked_reason(tmp_path: Path) -> None:
    report = _minimal_acceptance_reset(tmp_path, blocked_reason="blocked")
    report["claims"][0]["reason"] = ""
    violations, _blocked = validate_current_acceptance(report, tmp_path / "acceptance.json")
    assert "acceptance_blocked_reason_missing" in {item["code"] for item in violations}


def test_no_simulated_subagent_valid_and_forbidden_paths(tmp_path: Path) -> None:
    stage = tmp_path / "runs" / "m1-hardening" / "H00_BOOTSTRAP_HARD_GATES"
    (stage / "agents").mkdir(parents=True)
    (stage / "handoff").mkdir()
    valid = "role: design\nagent_invocation: real_subagent\nstage_id: H00_BOOTSTRAP_HARD_GATES\nsource_commit_before: abc\n"
    (stage / "agents" / "design.md").write_text(valid, encoding="utf-8")
    (stage / "handoff" / "DESIGN_BRIEF.md").write_text(valid, encoding="utf-8")
    violations, blocked = scan_stage_artifacts(tmp_path, "H00_BOOTSTRAP_HARD_GATES")
    assert not violations
    assert not blocked
    (stage / "agents" / "worker.md").write_text(
        "role: worker\nagent_invocation: real_subagent\nstage_id: H00_BOOTSTRAP_HARD_GATES\nsource_commit_before: abc\nsimulated worker subagent\n",
        encoding="utf-8",
    )
    violations, _blocked = scan_stage_artifacts(tmp_path, "H00_BOOTSTRAP_HARD_GATES")
    assert any(item["code"] == "forbidden_subagent_phrase" and item["line"] == 5 for item in violations)


def test_stage_exit_blocks_missing_artifacts_and_passes_complete_stage(tmp_path: Path) -> None:
    violations, blocked = validate_stage_exit(tmp_path, "H00_BOOTSTRAP_HARD_GATES")
    assert violations
    assert blocked
    for script in REQUIRED_SCRIPTS:
        path = tmp_path / "scripts" / "m1h" / script
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# script\n", encoding="utf-8")
    write_json(tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json", {"claims": []})
    for gate in H00_REQUIRED_GATE_RESULTS:
        write_json(
            tmp_path / "runs" / "m1-hardening" / "H00_BOOTSTRAP_HARD_GATES" / "artifacts" / "gates" / f"{gate}.json",
            {
                "schema_version": "v1",
                "artifact_type": "m1h_gate_result",
                "stage_id": "H00_BOOTSTRAP_HARD_GATES",
                "gate_name": gate,
                "status": "PASS",
                "checked_at": "2026-01-01T00:00:00Z",
                "inputs": [],
                "violations": [],
                "blocked_reasons": [],
                "source_commit": "abc",
            },
        )
    stage = tmp_path / "runs" / "m1-hardening" / "H00_BOOTSTRAP_HARD_GATES"
    for rel in ["agents/design.md", "agents/worker.md", "agents/review.md", "handoff/DESIGN_BRIEF.md", "handoff/WORKER_SUMMARY.md"]:
        path = stage / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")
    (stage / "handoff" / "REVIEW.md").write_text("Decision: PASS\n", encoding="utf-8")
    violations, blocked = validate_stage_exit(tmp_path, "H00_BOOTSTRAP_HARD_GATES")
    assert not violations
    assert not blocked


def test_h01_stage_exit_requires_reset_gate_and_artifact(tmp_path: Path) -> None:
    for script in REQUIRED_SCRIPTS:
        path = tmp_path / "scripts" / "m1h" / script
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# script\n", encoding="utf-8")
    write_json(tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json", {"claims": []})
    stage_id = "H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET"
    stage = tmp_path / "runs" / "m1-hardening" / stage_id
    for gate in H01_REQUIRED_GATE_RESULTS:
        if gate == "build_acceptance_reset":
            continue
        write_json(
            stage / "artifacts" / "gates" / f"{gate}.json",
            _gate_payload(stage_id, gate),
        )
    for rel in ["agents/design.md", "agents/worker.md", "agents/review.md", "handoff/DESIGN_BRIEF.md", "handoff/WORKER_SUMMARY.md"]:
        path = stage / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")
    (stage / "handoff" / "REVIEW.md").write_text("Decision: PASS\n", encoding="utf-8")
    violations, blocked = validate_stage_exit(tmp_path, stage_id)
    assert any("build_acceptance_reset.json is missing" in item for item in blocked)
    assert any("milestone1_acceptance_reset.json is missing" in item for item in blocked)

    write_json(stage / "artifacts" / "gates" / "build_acceptance_reset.json", _gate_payload(stage_id, "build_acceptance_reset"))
    write_json(stage / "artifacts" / "milestone1_acceptance_reset.json", _minimal_acceptance_reset(tmp_path, blocked_reason="blocked", stage_id=stage_id))
    violations, blocked = validate_stage_exit(tmp_path, stage_id)
    assert not violations
    assert not blocked


def test_capability_gate_pass_and_blocked(tmp_path: Path) -> None:
    pass_claim = {
        "claim_id": "management_matrix.real_exact.50",
        "capability": "management_matrix",
        "scale": 50,
        "evidence_kind": "REAL_EXACT_SCALE",
        "status": "PASS",
        "semantic_checks": {
            "exact_scale_observed": True,
            "management_matrix_present": True,
            "operation_semantics_present": True,
            "workload_telemetry_present": True,
            "m1_format_fields_complete": True,
            "hardening_stage_accepted": True,
        },
    }
    blocked_claim = {
        "claim_id": "management_matrix.real_exact.100",
        "capability": "management_matrix",
        "scale": 100,
        "evidence_kind": "BLOCKED_WITH_REASON",
        "status": "BLOCKED_WITH_REASON",
        "semantic_checks": {"exact_scale_observed": False},
        "reason": "missing",
    }
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, {"claims": [pass_claim, blocked_claim]})
    status, violations, blocked, extra = evaluate_capability(tmp_path, manifest_path, "management_matrix", {50})
    assert status == "PASS"
    assert not violations
    assert extra["passed_claims"] == ["management_matrix.real_exact.50"]
    status, violations, blocked, _extra = evaluate_capability(tmp_path, manifest_path, "management_matrix", {50, 100})
    assert status == "BLOCKED_WITH_REASON"
    assert not violations
    assert blocked


def _minimal_acceptance_reset(tmp_path: Path, *, blocked_reason: str, stage_id: str = "H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET") -> dict[str, object]:
    claims = [
        {
            "claim_id": claim_id(capability, scale),
            "capability": capability,
            "scale": scale,
            "required_for_milestone_pass": True,
            "evidence_kind": "BLOCKED_WITH_REASON",
            "source_status": "BLOCKED_WITH_REASON",
            "acceptance_status": "BLOCKED_WITH_REASON",
            "reason": blocked_reason,
            "semantic_checks": {"exact_scale_observed": False},
            "source_artifacts": [],
        }
        for capability, scale in REQUIRED_CLAIMS
    ]
    return {
        "schema_version": "v1",
        "artifact_type": "milestone1_acceptance_reset",
        "stage_id": stage_id,
        "hardening_loop_status": "PASS",
        "milestone1_status": "BLOCKED_WITH_REASON",
        "false_pass_prevented": True,
        "required_claim_count": len(REQUIRED_CLAIMS),
        "passed_claim_count": 0,
        "blocked_claim_count": len(REQUIRED_CLAIMS),
        "failed_claim_count": 0,
        "claims": claims,
        "missing_claims": [claim["claim_id"] for claim in claims],
        "blocked_reasons": [blocked_reason],
        "source_manifest": "runs/m1-hardening/evidence_manifest.json",
    }


def _gate_payload(stage_id: str, gate_name: str) -> dict[str, object]:
    return {
        "schema_version": "v1",
        "artifact_type": "m1h_gate_result",
        "stage_id": stage_id,
        "gate_name": gate_name,
        "status": "PASS",
        "checked_at": "2026-01-01T00:00:00Z",
        "inputs": [],
        "violations": [],
        "blocked_reasons": [],
        "source_commit": "abc",
    }
