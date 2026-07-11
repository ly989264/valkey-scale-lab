from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

M1H = Path(__file__).resolve().parents[2] / "scripts" / "m1h"
sys.path.insert(0, str(M1H))

from assert_final_milestone1_hardened import (  # noqa: E402
    H10_ARTIFACT_TYPE,
    H10_STAGE_ID,
    default_acceptance_out_path,
    evaluate_final,
)
from assert_stage_exit import H10_REQUIRED_GATE_RESULTS, REQUIRED_SCRIPTS, validate_stage_exit  # noqa: E402
from common import write_json  # noqa: E402
from manifest import CAPABILITY_REQUIRED_CHECKS, REQUIRED_CLAIMS, build_manifest, claim_id  # noqa: E402


def test_h10_final_gate_writes_hardened_acceptance_lists(tmp_path: Path) -> None:
    manifest_path = tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json"
    out_path = default_acceptance_out_path(tmp_path, H10_STAGE_ID)
    write_json(manifest_path, build_manifest(tmp_path))

    status, violations, blocked, extra = evaluate_final(
        tmp_path,
        manifest_path,
        out_path,
        stage_id=H10_STAGE_ID,
        historical_acceptance_report=None,
    )

    report = json.loads(out_path.read_text(encoding="utf-8"))
    required_ids = sorted(claim_id(capability, scale) for capability, scale in REQUIRED_CLAIMS)
    assert status == "PASS"
    assert not violations
    assert blocked
    assert extra["acceptance_report"] == str(out_path)
    assert report["artifact_type"] == H10_ARTIFACT_TYPE
    assert report["stage_id"] == H10_STAGE_ID
    assert report["hardening_loop_status"] == "PASS"
    assert report["milestone1_status"] == "BLOCKED_WITH_REASON"
    assert report["false_pass_prevented"] is True
    assert report["required_claims"] == required_ids
    assert report["passed_claims"] == []
    assert len(report["blocked_claims"]) == len(REQUIRED_CLAIMS)
    assert report["failed_claims"] == []
    assert "fixture_only_claims" in report
    assert "legacy_only_claims" in report


def test_h10_milestone_pass_requires_every_required_claim_promotable(tmp_path: Path) -> None:
    manifest_path = tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json"
    out_path = default_acceptance_out_path(tmp_path, H10_STAGE_ID)
    write_json(manifest_path, _all_pass_manifest())

    status, violations, blocked, _extra = evaluate_final(
        tmp_path,
        manifest_path,
        out_path,
        stage_id=H10_STAGE_ID,
        historical_acceptance_report=None,
    )

    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert status == "PASS"
    assert not violations
    assert not blocked
    assert report["milestone1_status"] == "PASS"
    assert report["false_pass_prevented"] is False
    assert report["passed_claim_count"] == len(REQUIRED_CLAIMS)
    assert report["passed_claims"] == report["required_claims"]
    assert report["blocked_claims"] == []
    assert report["failed_claims"] == []


@pytest.mark.parametrize(
    ("case_name", "mutate", "expected_code"),
    [
        (
            "fixture_kind",
            lambda claims: claims[0].update({"evidence_kind": "FIXTURE_ONLY", "source_artifacts": ["tests/fixtures/setup.json"]}),
            "nonpromotable_required_pass",
        ),
        (
            "legacy_kind",
            lambda claims: claims[1].update({"evidence_kind": "LEGACY_EVIDENCE_ONLY"}),
            "nonpromotable_required_pass",
        ),
        (
            "fixture_path",
            lambda claims: claims[2].update({"source_artifacts": ["tests/fixtures/unsafe.json"]}),
            "required_pass_failed_semantics",
        ),
        (
            "skipped_semantic",
            lambda claims: claims[3]["semantic_checks"].update({"setup_core_metrics_numeric": "SKIPPED_WITH_REASON"}),
            "required_pass_failed_semantics",
        ),
        (
            "rendered_only_report",
            lambda claims: _mutate_claim(
                claims,
                "report.real_exact.50",
                {"source_artifacts": ["artifacts/report/report_index.json", "artifacts/report/report.md"]},
            ),
            "h10_report_rendered_only_pass",
        ),
    ],
)
def test_h10_final_gate_fails_closed_on_nonpromotable_required_claims(
    tmp_path: Path,
    case_name: str,
    mutate,
    expected_code: str,
) -> None:
    del case_name
    manifest = _all_pass_manifest()
    mutate(manifest["claims"])
    manifest_path = tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json"
    out_path = default_acceptance_out_path(tmp_path, H10_STAGE_ID)
    write_json(manifest_path, manifest)

    status, violations, _blocked, _extra = evaluate_final(
        tmp_path,
        manifest_path,
        out_path,
        stage_id=H10_STAGE_ID,
        historical_acceptance_report=None,
    )

    assert status == "FAIL"
    assert expected_code in {item["code"] for item in violations}
    report = json.loads(out_path.read_text(encoding="utf-8"))
    if expected_code == "h10_report_rendered_only_pass":
        assert report["milestone1_status"] == "PASS"
    else:
        assert report["milestone1_status"] == "FAIL"


def test_h10_stage_exit_requires_final_gate_and_hardened_acceptance_artifact(tmp_path: Path) -> None:
    _seed_stage_exit_base(tmp_path)
    stage = tmp_path / "runs" / "m1-hardening" / H10_STAGE_ID
    (stage / "artifacts" / "gates" / "assert_final_milestone1_hardened.json").unlink()

    violations, blocked = validate_stage_exit(tmp_path, H10_STAGE_ID)
    assert not violations
    assert any("assert_final_milestone1_hardened.json is missing" in item for item in blocked)
    assert any("milestone1_hardened_acceptance.json is missing" in item for item in blocked)

    write_json(
        stage / "artifacts" / "gates" / "assert_final_milestone1_hardened.json",
        _gate_payload("assert_final_milestone1_hardened"),
    )
    status, violations, _blocked, _extra = evaluate_final(
        tmp_path,
        tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json",
        default_acceptance_out_path(tmp_path, H10_STAGE_ID),
        stage_id=H10_STAGE_ID,
        historical_acceptance_report=None,
    )
    assert status == "PASS"
    assert not violations

    violations, blocked = validate_stage_exit(tmp_path, H10_STAGE_ID)
    assert not violations
    assert not blocked


def _all_pass_manifest() -> dict[str, object]:
    return {
        "schema_version": "v1",
        "artifact_type": "m1h_evidence_manifest",
        "created_at": "2026-01-01T00:00:00Z",
        "source_commit": "test",
        "claims": [
            {
                "claim_id": claim_id(capability, scale),
                "stage_id": "M1H",
                "capability": capability,
                "scale": scale,
                "evidence_kind": "REAL_EXACT_SCALE",
                "required_for_milestone_pass": True,
                "source_artifacts": _source_artifacts(capability, scale),
                "semantic_checks": _passing_semantic_checks(capability),
                "status": "PASS",
            }
            for capability, scale in REQUIRED_CLAIMS
        ],
    }


def _passing_semantic_checks(capability: str) -> dict[str, object]:
    checks: dict[str, object] = {
        "m1_format_fields_complete": True,
        "hardening_stage_accepted": True,
        "exact_scale_observed": True,
    }
    for name in CAPABILITY_REQUIRED_CHECKS[capability]:
        checks[name] = True
    return checks


def _source_artifacts(capability: str, scale: int) -> list[str]:
    if capability == "report":
        return [
            f"artifacts/phases/source_{scale}/accepted_inputs.json",
            f"artifacts/phases/source_{scale}/report_index.json",
        ]
    return [f"artifacts/phases/source_{scale}/{capability}.json"]


def _mutate_claim(claims: list[dict[str, object]], target_claim_id: str, updates: dict[str, object]) -> None:
    for claim in claims:
        if claim.get("claim_id") == target_claim_id:
            claim.update(updates)
            return
    raise AssertionError(f"missing claim {target_claim_id}")


def _seed_stage_exit_base(tmp_path: Path) -> None:
    for script in REQUIRED_SCRIPTS:
        path = tmp_path / "scripts" / "m1h" / script
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# script\n", encoding="utf-8")
    write_json(tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json", build_manifest(tmp_path))
    stage = tmp_path / "runs" / "m1-hardening" / H10_STAGE_ID
    for gate in H10_REQUIRED_GATE_RESULTS:
        write_json(stage / "artifacts" / "gates" / f"{gate}.json", _gate_payload(gate))
    for rel in ["agents/design.md", "agents/worker.md", "agents/review.md", "handoff/DESIGN_BRIEF.md", "handoff/WORKER_SUMMARY.md"]:
        path = stage / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")
    (stage / "handoff" / "FINAL_HANDOFF.md").write_text("milestone1_hardened_acceptance.json\n", encoding="utf-8")
    (stage / "handoff" / "REVIEW.md").write_text("Decision: PASS\n", encoding="utf-8")


def _gate_payload(gate_name: str) -> dict[str, object]:
    return {
        "schema_version": "v1",
        "artifact_type": "m1h_gate_result",
        "stage_id": H10_STAGE_ID,
        "gate_name": gate_name,
        "status": "PASS",
        "checked_at": "2026-01-01T00:00:00Z",
        "inputs": [],
        "violations": [],
        "blocked_reasons": [],
        "source_commit": "abc",
    }
