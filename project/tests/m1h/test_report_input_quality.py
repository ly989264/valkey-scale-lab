from __future__ import annotations

import json
import sys
from pathlib import Path

M1H = Path(__file__).resolve().parents[2] / "scripts" / "m1h"
sys.path.insert(0, str(M1H))

from assert_report_input_quality import evaluate_report_input_quality
from assert_stage_exit import H09_REQUIRED_GATE_RESULTS, REQUIRED_SCRIPTS, validate_stage_exit
from common import write_json
from manifest import (
    H09_CANONICAL_REPORT_INPUT_KEYS,
    H09_OFFLINE_POLICY_FIELDS,
    H09_REPORT_REQUIRED_SOURCE_CLAIMS,
    build_manifest,
    build_report_claim,
    claim_id,
)


def test_report_input_quality_gate_accepts_honest_blocked_current_shape(tmp_path: Path) -> None:
    _write_minimal_render_only_index(tmp_path, 50)
    manifest = build_manifest(tmp_path)
    manifest_path = tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json"
    write_json(manifest_path, manifest)

    status, violations, blocked, extra = evaluate_report_input_quality(tmp_path, manifest_path)

    assert status == "PASS"
    assert not violations
    assert extra["passed_report_claim_count"] == 0
    assert extra["blocked_report_claim_count"] == 4
    assert len(blocked) == 4


def test_report_claim_passes_only_with_accepted_same_scale_source_claims(tmp_path: Path) -> None:
    scale = 50
    ledger = _accepted_dependency_ledger(tmp_path, scale)
    _write_valid_report_index(tmp_path, scale)
    report_claim = build_report_claim(tmp_path, scale, ledger)
    manifest = _manifest_with_report_claim(tmp_path, report_claim, ledger)
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)

    status, violations, _blocked, extra = evaluate_report_input_quality(tmp_path, manifest_path)

    assert status == "PASS"
    assert not violations
    assert report_claim["status"] == "PASS"
    assert report_claim["diagnostics"]["report_h09_acceptance"]["accepted"] is True
    assert extra["passed_report_claim_count"] == 1


def test_report_claim_stays_blocked_when_required_source_claim_is_blocked(tmp_path: Path) -> None:
    scale = 50
    ledger = _accepted_dependency_ledger(tmp_path, scale)
    blocked_cid = claim_id("fault_timeline", scale)
    ledger[("fault_timeline", scale)].update(
        {
            "status": "BLOCKED_WITH_REASON",
            "evidence_kind": "BLOCKED_WITH_REASON",
            "reason": "fault timeline intentionally blocked",
        }
    )
    _write_valid_report_index(tmp_path, scale)

    report_claim = build_report_claim(tmp_path, scale, ledger)

    assert report_claim["status"] == "BLOCKED_WITH_REASON"
    assert blocked_cid in report_claim["reason"]


def test_report_input_quality_rejects_crafted_pass_without_h09_diagnostics(tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    report_claim = _claim(manifest, claim_id("report", 50))
    report_claim.update({"status": "PASS", "evidence_kind": "REAL_EXACT_SCALE"})
    report_claim.pop("diagnostics", None)
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)

    status, violations, _blocked, _extra = evaluate_report_input_quality(tmp_path, manifest_path)

    assert status == "FAIL"
    assert "report_pass_without_h09_diagnostics" in {item["code"] for item in violations}


def test_report_input_quality_rejects_crafted_pass_with_blocked_dependencies(tmp_path: Path) -> None:
    scale = 50
    manifest = build_manifest(tmp_path)
    report_claim = _claim(manifest, claim_id("report", scale))
    required_ids = [claim_id(capability, scale) for capability in H09_REPORT_REQUIRED_SOURCE_CLAIMS[scale]]
    report_claim.update(
        {
            "status": "PASS",
            "evidence_kind": "REAL_EXACT_SCALE",
            "source_artifacts": ["artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_50/report_index.json"],
            "semantic_checks": {"m1_format_fields_complete": True, "hardening_stage_accepted": True},
            "diagnostics": {
                "report_h09_acceptance": {
                    "accepted": True,
                    "source_quality_status": "PASS",
                    "render_status": "PASS",
                    "required_source_claims": required_ids,
                    "cited_source_claims": required_ids,
                    "accepted_source_claims": required_ids,
                    "source_artifact_refs": [],
                    "reasons": [],
                }
            },
        }
    )
    _write_valid_report_index(tmp_path, scale)
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)

    status, violations, _blocked, _extra = evaluate_report_input_quality(tmp_path, manifest_path)

    assert status == "FAIL"
    assert "report_pass_with_blocked_source_claim" in {item["code"] for item in violations}


def test_report_input_quality_rejects_invalid_offline_policy_or_missing_sections_for_pass(tmp_path: Path) -> None:
    scale = 50
    manifest = _passing_report_manifest(tmp_path, scale)
    index_path = tmp_path / "artifacts" / "phases" / "P36_FULL_FLOW_E2E_50_100_200_REAL" / "full_flow_50" / "report_index.json"
    index = {
        "schema_version": "v1",
        "artifact_type": "report_index",
        "status": "PASS",
        "scale": scale,
        "node_count": scale,
        "offline_policy": {"artifact_only": True},
        "source_quality": {"source_claim_refs": [claim_id(capability, scale) for capability in H09_REPORT_REQUIRED_SOURCE_CLAIMS[scale]]},
    }
    write_json(index_path, index)
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)

    status, violations, _blocked, _extra = evaluate_report_input_quality(tmp_path, manifest_path)

    codes = {item["code"] for item in violations}
    assert status == "FAIL"
    assert "report_offline_policy_invalid" in codes
    assert "report_required_section_missing" in codes


def test_report_input_quality_rejects_derivation_policy_without_exact_offline_policy_for_pass(tmp_path: Path) -> None:
    scale = 50
    manifest = _passing_report_manifest(tmp_path, scale)
    index_path = tmp_path / "artifacts" / "phases" / "P36_FULL_FLOW_E2E_50_100_200_REAL" / "full_flow_50" / "report_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index.pop("offline_policy")
    index["derivation_policy"] = {
        "artifact_only": True,
        "rendered_views_as_metric_sources": False,
        "source_scenarios_rerun": False,
        "log_parsing": False,
    }
    write_json(index_path, index)
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)

    status, violations, _blocked, _extra = evaluate_report_input_quality(tmp_path, manifest_path)

    assert status == "FAIL"
    assert "report_offline_policy_invalid" in {item["code"] for item in violations}


def test_report_input_quality_rejects_rendered_files_as_only_source_refs_for_pass(tmp_path: Path) -> None:
    scale = 50
    manifest = _passing_report_manifest(tmp_path, scale)
    report_claim = _claim(manifest, claim_id("report", scale))
    report_claim["diagnostics"]["report_h09_acceptance"]["source_artifact_refs"] = ["report.md", "index.html"]
    index_path = tmp_path / "artifacts" / "phases" / "P36_FULL_FLOW_E2E_50_100_200_REAL" / "full_flow_50" / "report_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for key in H09_CANONICAL_REPORT_INPUT_KEYS:
        index[key] = {"source_artifacts": ["report.md", "index.html"]}
    index["source_quality"]["source_artifact_refs"] = ["report.md", "index.html"]
    write_json(index_path, index)
    (index_path.parent / "report.md").write_text("# report\n", encoding="utf-8")
    (index_path.parent / "index.html").write_text("<html></html>\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)

    status, violations, _blocked, _extra = evaluate_report_input_quality(tmp_path, manifest_path)

    assert status == "FAIL"
    assert "report_pass_backed_only_by_report_files" in {item["code"] for item in violations}
    assert "report_view_source_ref_missing" in {item["code"] for item in violations}


def test_report_input_quality_rejects_fixture_or_legacy_report_sources_for_pass(tmp_path: Path) -> None:
    scale = 50
    for bad_ref, expected_code in [
        ("tests/fixtures/report/source.json", "report_fixture_source_promoted"),
        ("artifacts/phases/legacy_report/source.json", "report_legacy_source_promoted"),
    ]:
        manifest = _passing_report_manifest(tmp_path, scale)
        report_claim = _claim(manifest, claim_id("report", scale))
        report_claim["diagnostics"]["report_h09_acceptance"]["source_artifact_refs"] = [bad_ref]
        manifest_path = tmp_path / f"{expected_code}.json"
        write_json(manifest_path, manifest)

        status, violations, _blocked, _extra = evaluate_report_input_quality(tmp_path, manifest_path)

        assert status == "FAIL"
        assert expected_code in {item["code"] for item in violations}


def test_h09_stage_exit_requires_report_input_quality_gate(tmp_path: Path) -> None:
    stage_id = "H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING"
    for script in REQUIRED_SCRIPTS:
        path = tmp_path / "scripts" / "m1h" / script
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# script\n", encoding="utf-8")
    write_json(tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json", {"claims": []})
    stage = tmp_path / "runs" / "m1-hardening" / stage_id
    for rel in ["agents/design.md", "agents/worker.md", "agents/review.md", "handoff/DESIGN_BRIEF.md", "handoff/WORKER_SUMMARY.md"]:
        path = stage / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("role: worker\nagent_invocation: real_subagent\nstage_id: H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING\n", encoding="utf-8")
    (stage / "handoff" / "REVIEW.md").write_text("Decision: PASS\n", encoding="utf-8")
    for gate in H09_REQUIRED_GATE_RESULTS:
        if gate == "assert_report_input_quality":
            continue
        write_json(stage / "artifacts" / "gates" / f"{gate}.json", _gate_payload(stage_id, gate))

    violations, blocked = validate_stage_exit(tmp_path, stage_id)
    assert not violations
    assert any("assert_report_input_quality.json is missing" in item for item in blocked)

    write_json(stage / "artifacts" / "gates" / "assert_report_input_quality.json", _gate_payload(stage_id, "assert_report_input_quality"))
    violations, blocked = validate_stage_exit(tmp_path, stage_id)
    assert not violations
    assert not blocked


def _passing_report_manifest(tmp_path: Path, scale: int) -> dict[str, object]:
    ledger = _accepted_dependency_ledger(tmp_path, scale)
    _write_valid_report_index(tmp_path, scale)
    report_claim = build_report_claim(tmp_path, scale, ledger)
    assert report_claim["status"] == "PASS"
    return _manifest_with_report_claim(tmp_path, report_claim, ledger)


def _manifest_with_report_claim(tmp_path: Path, report_claim: dict[str, object], ledger: dict[tuple[str, int], dict[str, object]]) -> dict[str, object]:
    manifest = build_manifest(tmp_path)
    claims = [claim for claim in manifest["claims"] if claim["claim_id"] != report_claim["claim_id"]]
    existing = {claim["claim_id"] for claim in claims}
    for dep_claim in ledger.values():
        if dep_claim["claim_id"] in existing:
            claims = [dep_claim if claim["claim_id"] == dep_claim["claim_id"] else claim for claim in claims]
        else:
            claims.append(dep_claim)
    claims.append(report_claim)
    manifest["claims"] = claims
    return manifest


def _accepted_dependency_ledger(tmp_path: Path, scale: int) -> dict[tuple[str, int], dict[str, object]]:
    ledger: dict[tuple[str, int], dict[str, object]] = {}
    for capability in H09_REPORT_REQUIRED_SOURCE_CLAIMS[scale]:
        source = tmp_path / "artifacts" / "source_claims" / f"{capability}_{scale}.json"
        write_json(source, {"status": "PASS"})
        ledger[(capability, scale)] = {
            "claim_id": claim_id(capability, scale),
            "stage_id": "M1H",
            "capability": capability,
            "scale": scale,
            "evidence_kind": "REAL_EXACT_SCALE",
            "required_for_milestone_pass": True,
            "source_artifacts": [source.relative_to(tmp_path).as_posix()],
            "semantic_checks": {"m1_format_fields_complete": True, "hardening_stage_accepted": True, "exact_scale_observed": True},
            "status": "PASS",
        }
    return ledger


def _write_minimal_render_only_index(tmp_path: Path, scale: int) -> None:
    path = tmp_path / "artifacts" / "phases" / "P36_FULL_FLOW_E2E_50_100_200_REAL" / f"full_flow_{scale}" / "report_index.json"
    write_json(path, {"schema_version": "v1", "artifact_type": "p36_report_index", "status": "PASS", "scale": scale, "node_count": scale, "views": [{"path": "report_index.json", "status": "PASS"}]})


def _write_valid_report_index(tmp_path: Path, scale: int) -> None:
    base = tmp_path / "artifacts" / "phases" / "P36_FULL_FLOW_E2E_50_100_200_REAL" / f"full_flow_{scale}"
    source_refs = []
    for name in ["setup.json", "command.json", "management.json", "workload.json", "fault.json", "system.json", "cleanup.json", "missing_metrics.json"]:
        path = base / "sources" / name
        write_json(path, {"status": "PASS"})
        source_refs.append(path.relative_to(base).as_posix())
    required_ids = [claim_id(capability, scale) for capability in H09_REPORT_REQUIRED_SOURCE_CLAIMS[scale]]
    index = {
        "schema_version": "v1",
        "artifact_type": "report_index",
        "status": "PASS",
        "render_status": "PASS",
        "scale": scale,
        "node_count": scale,
        "offline_policy": dict(H09_OFFLINE_POLICY_FIELDS),
        "source_quality": {"source_claim_refs": required_ids, "source_artifact_refs": source_refs},
    }
    for key, ref in zip(H09_CANONICAL_REPORT_INPUT_KEYS, source_refs):
        index[key] = {"source_artifacts": [ref]}
    write_json(base / "report_index.json", index)


def _claim(manifest: dict[str, object], cid: str) -> dict[str, object]:
    for claim in manifest["claims"]:
        if claim["claim_id"] == cid:
            return claim
    raise AssertionError(f"missing claim {cid}")


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
